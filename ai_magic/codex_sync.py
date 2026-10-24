"""Allowlisted Codex preference export and conservative three-way TOML merge."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

import tomlkit


class ErrorKind(Enum):
    INPUT = "input"
    OWNERSHIP = "ownership"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    STALE = "stale"
    IO = "io"


class SyncError(Exception):
    def __init__(self, kind: ErrorKind, message: str):
        self.kind = kind
        super().__init__(message)


class State(Enum):
    ABSENT = "absent"


class Status(Enum):
    SAME = "unchanged"
    LOCAL = "retain_destination"
    UPDATE = "update"
    CONFLICT = "conflict"


class Resolution(Enum):
    SHARED = "shared"
    DESTINATION = "destination"


class Kind(Enum):
    PREFERENCE = "preference"
    PLUGIN = "plugin_enabled"
    SKILL_FLAG = "skill_enabled"
    SKILL_PATH = "skill_path"


SAFE_KEYS = {
    "model": str,
    "model_reasoning_effort": str,
    "personality": str,
    "web_search": str,
    "tui.status_line": list,
    "tui.status_line_use_colors": bool,
}
ABSENT = State.ABSENT


def fail(message: str, kind: ErrorKind = ErrorKind.INPUT) -> NoReturn:
    raise SyncError(kind, message)


def read_config(path: Path) -> str:
    """Keep line endings intact so approval fingerprints bind to actual file bytes."""
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            return stream.read()
    except UnicodeError:
        fail("Configuration must be UTF-8 text; source contents omitted")


def load_toml(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        # Parser messages can include private source lines.
        fail("Invalid TOML; source contents omitted")


def exact_type(value: Any, expected: type) -> bool:
    return type(value) is expected


def preference_type(key: str, value: Any) -> None:
    if not exact_type(value, SAFE_KEYS[key]):
        fail("Invalid type for an owned preference")
    strings = (
        value if isinstance(value, list) else [value] if isinstance(value, str) else []
    )
    if any(
        not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", s)
        for s in strings
    ):
        fail(
            "Owned preferences must contain portable identifiers, not paths or arbitrary text"
        )


def string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        fail("Policy selectors must be lists of strings")
    if len(set(value)) != len(value):
        fail("Duplicate policy selectors")
    return tuple(value)


@dataclass(frozen=True)
class Policy:
    keys: tuple[str, ...]
    plugins: tuple[str, ...]
    skills: dict[str, str]

    @classmethod
    def parse(cls, text: str) -> Policy:
        data = load_toml(text)
        if set(data) - {"schema_version", "keys", "plugins", "skills"} or (
            type(data.get("schema_version")) is not int or data["schema_version"] != 1
        ):
            fail("Unsupported ownership policy")
        keys = string_list(data.get("keys", []))
        if set(keys) - SAFE_KEYS.keys():
            fail(
                "Policy attempts to own a protected or unsupported key",
                ErrorKind.OWNERSHIP,
            )
        plugins = string_list(data.get("plugins", []))
        if any(not re.fullmatch(r"[a-z0-9-]+@personal", x) for x in plugins):
            fail(
                "Only explicitly selected personal plugin enablement is supported",
                ErrorKind.OWNERSHIP,
            )
        skills = data.get("skills", {})
        if not isinstance(skills, dict):
            fail("Policy skills must map skill IDs to portable path templates")
        for name, template in skills.items():
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
                fail("Invalid skill identity")
            template_parts(template)
            if PurePosixPath(template).parts[-2:] != (name, "SKILL.md"):
                fail("Skill template must end in its identity/SKILL.md")
        return cls(keys, plugins, skills)


def template_parts(template: Any) -> tuple[str, str]:
    if not isinstance(template, str):
        fail("Path template must be a string")
    match = re.fullmatch(r"\{([A-Z][A-Z0-9_]*)\}/(.+)", template)
    if (
        not match
        or any(p in {"", ".", ".."} for p in match[2].split("/"))
        or "\\" in template
    ):
        fail("Use an explicit {ROOT}/relative/path template without traversal")
    return match[1], match[2]


def mapped_path(template: str, mappings: dict[str, Path]) -> str:
    root, relative = template_parts(template)
    if root not in mappings or not mappings[root].is_absolute():
        fail("A required absolute destination root mapping is missing")
    return str(mappings[root] / relative)


def nested_get(data: dict, parts: tuple[str, ...]) -> Any:
    node: Any = data
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return ABSENT
        node = node[part]
    return node


def nested_set(data: Any, parts: tuple[str, ...], value: Any) -> None:
    node = data
    for part in parts[:-1]:
        if part not in node:
            node[part] = tomlkit.table()
        if not isinstance(node[part], dict):
            fail("Owned key has an incompatible destination parent")
        node = node[part]
    node[parts[-1]] = value


def selected_skill(data: dict, identity: str) -> Any:
    entries = nested_get(data, ("skills", "config"))
    if entries is ABSENT:
        return ABSENT
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        fail("Unsupported skill configuration shape")
    matches = []
    for entry in entries:
        path = entry.get("path")
        path_match = isinstance(path, str) and PurePosixPath(path).parts[-2:] == (
            identity,
            "SKILL.md",
        )
        if entry.get("name") == identity or path_match:
            matches.append(entry)
    if len(matches) > 1:
        fail(
            "Multiple destination entries match an owned skill; resolve explicitly",
            ErrorKind.AMBIGUOUS,
        )
    if matches and "name" in matches[0]:
        fail(
            "Named skill entries are destination-owned; this policy requires a path entry",
            ErrorKind.OWNERSHIP,
        )
    return matches[0] if matches else ABSENT


@dataclass(frozen=True)
class Selector:
    kind: Kind
    key: str

    @property
    def label(self) -> str:
        return f"{self.kind.value}:{self.key}"

    def current(self, config: dict) -> Any:
        if self.kind is Kind.PREFERENCE:
            value = nested_get(config, tuple(self.key.split(".")))
            if value is not ABSENT:
                preference_type(self.key, value)
            return value
        if self.kind is Kind.PLUGIN:
            value = nested_get(config, ("plugins", self.key, "enabled"))
        else:
            entry = selected_skill(config, self.key)
            value = (
                ABSENT
                if entry is ABSENT
                else entry.get(
                    "enabled" if self.kind is Kind.SKILL_FLAG else "path", ABSENT
                )
            )
        if value is not ABSENT and not exact_type(
            value, str if self.kind is Kind.SKILL_PATH else bool
        ):
            fail("Invalid destination type for an owned declaration")
        return value

    def set(self, config: Any, value: Any) -> None:
        if self.kind is Kind.PREFERENCE:
            nested_set(config, tuple(self.key.split(".")), value)
        elif self.kind is Kind.PLUGIN:
            nested_set(config, ("plugins", self.key, "enabled"), value)
        else:
            if "skills" not in config:
                config["skills"] = tomlkit.table()
            if "config" not in config["skills"]:
                config["skills"]["config"] = tomlkit.aot()
            entry = selected_skill(config, self.key)
            if entry is ABSENT:
                # Add path first so subsequent selectors identify this entry.
                if self.kind is not Kind.SKILL_PATH:
                    fail("Skill path must be established before enablement")
                entry = tomlkit.table()
                entry["path"] = value
                config["skills"]["config"].append(entry)
                return
            entry["enabled" if self.kind is Kind.SKILL_FLAG else "path"] = value


def flatten(
    shared: dict, policy: Policy, mappings: dict[str, Path]
) -> dict[Selector, Any]:
    if set(shared) - {"schema_version", "values", "plugin_enabled", "skills"} or (
        type(shared.get("schema_version")) is not int or shared["schema_version"] != 1
    ):
        fail("Unsupported shared preference schema")
    result = {}
    values = shared.get("values", {})
    if not isinstance(values, dict):
        fail("Shared values must be a table")

    def walk(node: dict, prefix: str = "") -> None:
        for key, value in node.items():
            if "." in key:
                fail("Shared values require nested tables, not quoted dotted aliases")
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                if not any(k.startswith(path + ".") for k in policy.keys):
                    fail(
                        "Shared document contains an unowned table", ErrorKind.OWNERSHIP
                    )
                walk(value, path)
            else:
                if path not in policy.keys:
                    fail("Shared document contains an unowned key", ErrorKind.OWNERSHIP)
                preference_type(path, value)
                result[Selector(Kind.PREFERENCE, path)] = value

    walk(values)
    plugins = shared.get("plugin_enabled", {})
    if not isinstance(plugins, dict) or set(plugins) - set(policy.plugins):
        fail("Shared document contains an unowned plugin", ErrorKind.OWNERSHIP)
    for identity, enabled in plugins.items():
        if not exact_type(enabled, bool):
            fail("Plugin enabled must be a boolean")
        result[Selector(Kind.PLUGIN, identity)] = enabled
    skills = shared.get("skills", {})
    if not isinstance(skills, dict) or set(skills) - policy.skills.keys():
        fail("Shared document contains an unowned skill", ErrorKind.OWNERSHIP)
    for identity, entry in skills.items():
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "enabled"}
            or entry["path"] != policy.skills[identity]
            or not exact_type(entry["enabled"], bool)
        ):
            fail(
                "Shared skill must use the policy template and a boolean enabled value"
            )
        result[Selector(Kind.SKILL_PATH, identity)] = mapped_path(
            entry["path"], mappings
        )
        result[Selector(Kind.SKILL_FLAG, identity)] = entry["enabled"]
    return result


def export_preferences(
    config_text: str, policy: Policy, mappings: dict[str, Path]
) -> str:
    config = load_toml(config_text)
    doc = tomlkit.document()
    doc["schema_version"] = 1
    for key in policy.keys:
        value = Selector(Kind.PREFERENCE, key).current(config)
        if value is not ABSENT:
            nested_set(doc, ("values", *key.split(".")), value)
    for identity in policy.plugins:
        value = Selector(Kind.PLUGIN, identity).current(config)
        if value is not ABSENT:
            nested_set(doc, ("plugin_enabled", identity), value)
    for identity, template in policy.skills.items():
        entry = selected_skill(config, identity)
        if entry is ABSENT:
            continue
        if entry.get("path") != mapped_path(template, mappings):
            fail(
                "Source skill location differs from its explicit mapping; resolve drift before export",
                ErrorKind.CONFLICT,
            )
        if not exact_type(entry.get("enabled"), bool):
            fail("Owned skill lacks an explicit boolean enabled choice")
        nested_set(doc, ("skills", identity, "path"), template)
        nested_set(doc, ("skills", identity, "enabled"), entry["enabled"])
    # Validate that exporting did not introduce anything outside the ownership policy.
    flatten(load_toml(tomlkit.dumps(doc)), policy, mappings)
    return tomlkit.dumps(doc)


@dataclass(frozen=True)
class Change:
    selector: Selector
    before: Any
    desired: Any
    status: Status


@dataclass
class Plan:
    candidate: str
    changes: list[Change]
    digest: str
    destination_hash: str
    target: str

    @property
    def conflicts(self) -> bool:
        return any(c.status is Status.CONFLICT for c in self.changes)

    def report(self) -> dict:
        def shown(value: Any) -> dict:
            return (
                {"present": False}
                if value is ABSENT
                else {"present": True, "value": value}
            )

        return {
            "schema_version": 1,
            "approval_digest": self.digest,
            "conflicts": self.conflicts,
            "changes": [
                {
                    "key": c.selector.label,
                    "status": c.status.value,
                    "destination": shown(c.before),
                    "shared": shown(c.desired),
                }
                for c in self.changes
            ],
        }

    def diff(self) -> str:
        # Only selected preference/declaration values appear; no adjacent private TOML.
        if self.conflicts:
            return ""
        before = [
            f"{c.selector.label} = {json.dumps(c.before if c.before is not ABSENT else {'absent': True})}\n"
            for c in self.changes
            if c.status is Status.UPDATE
        ]
        after = [
            f"{c.selector.label} = {json.dumps(c.desired)}\n"
            for c in self.changes
            if c.status is Status.UPDATE
        ]
        return "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile="destination-owned-keys",
                tofile="proposed-owned-keys",
            )
        )


def fingerprint(text: str) -> str:
    # Byte hashing intentionally detects stale config edits, including formatting changes.
    return hashlib.sha256(text.encode()).hexdigest()


def plan_merge(
    destination: str,
    shared_text: str,
    base_text: str | None,
    policy: Policy,
    mappings: dict[str, Path],
    target: str = "",
    resolutions: dict[str, Resolution] | None = None,
) -> Plan:
    resolutions = resolutions or {}
    used_resolutions = set()
    current = load_toml(destination)
    desired = flatten(load_toml(shared_text), policy, mappings)
    base = (
        flatten(load_toml(base_text), policy, mappings) if base_text is not None else {}
    )
    doc = tomlkit.parse(destination)
    changes = []
    for selector, value in desired.items():
        local = selector.current(current)
        previous = base.get(selector, ABSENT)
        if local == value:
            status = Status.SAME
        elif value == previous:
            status = Status.LOCAL
        elif local == previous:
            status = Status.UPDATE
        else:
            status = Status.CONFLICT
        if status is Status.CONFLICT and selector.label in resolutions:
            status = (
                Status.UPDATE
                if resolutions[selector.label] is Resolution.SHARED
                else Status.LOCAL
            )
            used_resolutions.add(selector.label)
        changes.append(Change(selector, local, value, status))
    if used_resolutions != set(resolutions):
        fail("A resolution does not identify an actual conflicting owned key")
    # A conflicting plan never produces a partial candidate.
    if not any(c.status is Status.CONFLICT for c in changes):
        for change in changes:
            if change.status is Status.UPDATE:
                change.selector.set(doc, change.desired)
    candidate = tomlkit.dumps(doc)
    for change in changes:
        if (
            not any(c.status is Status.CONFLICT for c in changes)
            and change.status is Status.UPDATE
        ):
            if (
                change.selector.kind is Kind.SKILL_PATH
                and not Path(change.desired).is_file()
            ):
                fail(
                    "Mapped owned skill is missing; config sync never deploys source files",
                    ErrorKind.CONFLICT,
                )
            if change.selector.kind is Kind.SKILL_FLAG and change.desired is True:
                entry = selected_skill(load_toml(candidate), change.selector.key)
                if not Path(entry["path"]).is_file():
                    fail(
                        "Cannot enable an owned skill whose mapped file is missing",
                        ErrorKind.CONFLICT,
                    )
    expected = copy.deepcopy(current)
    if not any(c.status is Status.CONFLICT for c in changes):
        # Independently model only selected mutations in plain parsed data.
        for change in changes:
            if change.status is not Status.UPDATE:
                continue
            selector = change.selector
            if selector.kind in {Kind.PREFERENCE, Kind.PLUGIN}:
                parts = (
                    tuple(selector.key.split("."))
                    if selector.kind is Kind.PREFERENCE
                    else ("plugins", selector.key, "enabled")
                )
                node = expected
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                node[parts[-1]] = change.desired
            else:
                entry = selected_skill(expected, selector.key)
                if entry is ABSENT:
                    entry = {}
                    expected.setdefault("skills", {}).setdefault("config", []).append(
                        entry
                    )
                entry["path" if selector.kind is Kind.SKILL_PATH else "enabled"] = (
                    change.desired
                )
        if load_toml(candidate) != expected:
            fail("Candidate changed unowned destination semantics")
    binding = {
        "target": target,
        "destination_hash": fingerprint(destination),
        "candidate_hash": fingerprint(candidate),
        "shared": load_toml(shared_text),
        "base": load_toml(base_text) if base_text else None,
        "policy": {
            "keys": policy.keys,
            "plugins": policy.plugins,
            "skills": policy.skills,
        },
        "mappings": {k: str(v) for k, v in sorted(mappings.items())},
        "resolutions": {k: v.value for k, v in sorted(resolutions.items())},
    }
    digest = fingerprint(json.dumps(binding, sort_keys=True))
    return Plan(candidate, changes, digest, fingerprint(destination), target)


def apply_plan(target: Path, plan: Plan, approval_digest: str) -> None:
    if plan.conflicts:
        fail("Resolve conflicts before applying", ErrorKind.CONFLICT)
    if approval_digest != plan.digest:
        fail("Approval digest does not match this exact plan", ErrorKind.STALE)
    if plan.target != str(target.absolute()):
        fail("Plan belongs to a different destination", ErrorKind.STALE)
    if target.is_symlink() or not target.is_file():
        fail("Apply requires an existing regular, non-symlink configuration file")
    original = read_config(target)
    if fingerprint(original) != plan.destination_hash:
        fail("Destination changed after planning", ErrorKind.STALE)
    if original == plan.candidate:
        return
    fd, name = tempfile.mkstemp(prefix=".codex-sync-", dir=target.parent)
    temp = Path(name)
    try:
        os.fchmod(fd, stat.S_IMODE(target.stat().st_mode))
        with os.fdopen(fd, "w") as stream:
            stream.write(plan.candidate)
            stream.flush()
            os.fsync(stream.fileno())
        if fingerprint(read_config(target)) != plan.destination_hash:
            fail("Destination changed during apply", ErrorKind.STALE)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
