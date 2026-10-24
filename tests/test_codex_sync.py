import json
import subprocess
import sys
import tomllib

import pytest
import tomlkit

from ai_magic.codex_sync import (
    ErrorKind,
    Policy,
    Resolution,
    Status,
    SyncError,
    apply_plan,
    export_preferences,
    plan_merge,
    read_config,
)


def preferences(**values):
    return tomlkit.dumps({"schema_version": 1, "values": values})


@pytest.fixture
def policy():
    return Policy.parse(
        'schema_version = 1\nkeys = ["model", "model_reasoning_effort"]\n'
    )


def test_three_way_preserves_unowned_tables_comments_and_secrets(policy):
    current = """# user comment
model = "old" # retain comment
approval_policy = "never"
[projects."/local/project"]
trust_level = "trusted"
[mcp_servers.runtime]
command = "/app/managed/tool"
[mcp_servers.runtime.env]
PASSWORD = "DO-NOT-EXPORT"
[hooks.state.browser]
trusted_hash = "local-hash"
[future_app_setting]
unknown = [1, 2]
"""
    plan = plan_merge(
        current, preferences(model="new"), preferences(model="old"), policy, {}
    )
    assert not plan.conflicts
    assert 'model = "new" # retain comment' in plan.candidate
    before = tomllib.loads(current)
    after = tomllib.loads(plan.candidate)
    before["model"] = "new"
    assert after == before
    assert "DO-NOT-EXPORT" not in json.dumps(plan.report()) + plan.diff()
    exported = export_preferences(current, policy, {})
    assert "DO-NOT-EXPORT" not in exported
    assert "projects" not in exported


def test_first_import_conflict_has_no_partial_candidate(policy):
    current = 'model = "local"\n'
    plan = plan_merge(
        current,
        preferences(model="shared", model_reasoning_effort="high"),
        None,
        policy,
        {},
    )
    assert plan.conflicts
    assert plan.candidate == current
    assert not plan.diff()  # no partial proposal can be mistaken for an applicable plan


def test_destination_only_edits_retained_and_shared_omission_does_not_delete(policy):
    current = 'model = "local"\nmodel_reasoning_effort = "high"\n'
    plan = plan_merge(
        current,
        preferences(model="base"),
        preferences(model="base", model_reasoning_effort="medium"),
        policy,
        {},
    )
    assert plan.candidate == current
    assert plan.changes[0].status is Status.LOCAL


def test_explicit_conflict_resolution_is_per_key_and_bound_to_digest(policy):
    current = 'model = "local"\n'
    unresolved = plan_merge(current, preferences(model="shared"), None, policy, {})
    accepted = plan_merge(
        current,
        preferences(model="shared"),
        None,
        policy,
        {},
        resolutions={"preference:model": Resolution.SHARED},
    )
    retained = plan_merge(
        current,
        preferences(model="shared"),
        None,
        policy,
        {},
        resolutions={"preference:model": Resolution.DESTINATION},
    )
    assert unresolved.conflicts and not accepted.conflicts
    assert tomllib.loads(accepted.candidate)["model"] == "shared"
    assert retained.candidate == current
    assert accepted.digest != retained.digest != unresolved.digest
    with pytest.raises(SyncError):
        plan_merge(
            current,
            preferences(model="shared"),
            None,
            policy,
            {},
            resolutions={"preference:unowned": Resolution.SHARED},
        )


@pytest.mark.parametrize(
    "key",
    [
        "approval_policy",
        "sandbox_mode",
        "projects",
        "mcp_servers.remote.env.API_KEY",
        "marketplaces.personal.source",
        "desktop",
        "shell_environment_policy.set.PATH",
        "hooks.state",
    ],
)
def test_protected_policy_rejected(key):
    with pytest.raises(SyncError) as error:
        Policy.parse(tomlkit.dumps({"schema_version": 1, "keys": [key]}))
    assert error.value.kind is ErrorKind.OWNERSHIP


def test_unowned_shared_key_and_runtime_plugin_rejected(policy):
    with pytest.raises(SyncError):
        plan_merge("", preferences(approval_policy="never"), None, policy, {})
    with pytest.raises(SyncError):
        Policy.parse('schema_version=1\nplugins=["browser@openai-bundled"]')


def test_personal_plugin_merge_preserves_other_plugin_fields():
    policy = Policy.parse('schema_version=1\nplugins=["example@personal"]')
    shared = 'schema_version=1\n[plugin_enabled]\n"example@personal"=false\n'
    base = shared.replace("false", "true")
    current = '[plugins."example@personal"]\nenabled=true\nlocal_setting="retain"\n[plugins."browser@openai-bundled"]\nenabled=true\n'
    result = tomllib.loads(plan_merge(current, shared, base, policy, {}).candidate)
    assert result["plugins"]["example@personal"] == {
        "enabled": False,
        "local_setting": "retain",
    }
    assert result["plugins"]["browser@openai-bundled"]["enabled"] is True


@pytest.fixture
def skill_policy():
    return Policy.parse(
        'schema_version=1\n[skills]\nexample="{CODEX_HOME}/skills/example/SKILL.md"'
    )


def skill_preferences(enabled=False):
    return tomlkit.dumps(
        {
            "schema_version": 1,
            "skills": {
                "example": {
                    "path": "{CODEX_HOME}/skills/example/SKILL.md",
                    "enabled": enabled,
                }
            },
        }
    )


def install_fixture(root):
    p = root / "skills/example/SKILL.md"
    p.parent.mkdir(parents=True)
    p.write_text("fixture")
    return p


def test_skill_path_mapping_and_independent_host_roots(tmp_path, skill_policy):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    sp = install_fixture(source)
    dp = install_fixture(destination)
    config = tomlkit.dumps(
        {"skills": {"config": [{"path": str(sp), "enabled": False}]}}
    )
    portable = export_preferences(config, skill_policy, {"CODEX_HOME": source})
    assert str(source) not in portable
    assert "{CODEX_HOME}" in portable
    plan = plan_merge("", portable, None, skill_policy, {"CODEX_HOME": destination})
    assert tomllib.loads(plan.candidate)["skills"]["config"] == [
        {"path": str(dp), "enabled": False}
    ]


def test_path_drift_and_duplicates_are_not_silently_selected(tmp_path, skill_policy):
    root = tmp_path / "expected"
    install_fixture(root)
    current = tomlkit.dumps(
        {
            "skills": {
                "config": [{"path": "/other/skills/example/SKILL.md", "enabled": False}]
            }
        }
    )
    with pytest.raises(SyncError) as error:
        export_preferences(current, skill_policy, {"CODEX_HOME": root})
    assert error.value.kind is ErrorKind.CONFLICT
    assert plan_merge(
        current, skill_preferences(), None, skill_policy, {"CODEX_HOME": root}
    ).conflicts
    duplicate = tomlkit.dumps(
        {
            "skills": {
                "config": [
                    {"path": "/one/example/SKILL.md", "enabled": False},
                    {"path": "/two/example/SKILL.md", "enabled": False},
                ]
            }
        }
    )
    with pytest.raises(SyncError) as error:
        plan_merge(
            duplicate, skill_preferences(), None, skill_policy, {"CODEX_HOME": root}
        )
    assert error.value.kind is ErrorKind.AMBIGUOUS


def test_skill_array_merge_preserves_unowned_entries_and_properties(
    tmp_path, skill_policy
):
    root = tmp_path / "codex"
    p = install_fixture(root)
    current = tomlkit.dumps(
        {
            "skills": {
                "config": [
                    {"path": str(p), "enabled": True, "local": "retain"},
                    {"name": "unowned", "enabled": False},
                ]
            }
        }
    )
    candidate = plan_merge(
        current,
        skill_preferences(False),
        skill_preferences(True),
        skill_policy,
        {"CODEX_HOME": root},
    ).candidate
    assert tomllib.loads(candidate)["skills"]["config"] == [
        {"path": str(p), "enabled": False, "local": "retain"},
        {"name": "unowned", "enabled": False},
    ]


@pytest.mark.parametrize(
    "template",
    [
        "{ROOT}/../example/SKILL.md",
        "/source/example/SKILL.md",
        "{ROOT}/skills/other/SKILL.md",
    ],
)
def test_invalid_templates_rejected(template):
    with pytest.raises(SyncError):
        Policy.parse(
            tomlkit.dumps({"schema_version": 1, "skills": {"example": template}})
        )


def test_missing_mapping_and_missing_source_fail(tmp_path, skill_policy):
    with pytest.raises(SyncError):
        plan_merge("", skill_preferences(), None, skill_policy, {})
    with pytest.raises(SyncError) as error:
        plan_merge(
            "", skill_preferences(), None, skill_policy, {"CODEX_HOME": tmp_path}
        )
    assert error.value.kind is ErrorKind.CONFLICT


def test_apply_fixture_idempotence_permissions_and_digest(tmp_path, policy):
    target = tmp_path / "config.toml"
    target.write_text('model="old"\n[app]\nretain="local"\n')
    target.chmod(0o600)
    shared = preferences(model="new")
    base = preferences(model="old")
    plan = plan_merge(
        target.read_text(), shared, base, policy, {}, str(target.absolute())
    )
    with pytest.raises(SyncError):
        apply_plan(target, plan, "unreviewed")
    apply_plan(target, plan, plan.digest)
    assert target.stat().st_mode & 0o777 == 0o600
    again = plan_merge(
        target.read_text(), shared, shared, policy, {}, str(target.absolute())
    )
    assert all(c.status is Status.SAME for c in again.changes)
    assert not again.diff()
    before = target.stat().st_mtime_ns
    apply_plan(target, again, again.digest)
    assert target.stat().st_mtime_ns == before
    assert tomllib.loads(target.read_text())["app"] == {"retain": "local"}


def test_apply_rejects_stale_target_and_different_file(tmp_path, policy):
    target = tmp_path / "config.toml"
    target.write_text('model="old"\n')
    plan = plan_merge(
        target.read_text(),
        preferences(model="new"),
        preferences(model="old"),
        policy,
        {},
        str(target.absolute()),
    )
    other = tmp_path / "other.toml"
    other.write_text(target.read_text())
    with pytest.raises(SyncError):
        apply_plan(other, plan, plan.digest)
    target.write_text(target.read_text() + "# app edited formatting\n")
    with pytest.raises(SyncError) as error:
        apply_plan(target, plan, plan.digest)
    assert error.value.kind is ErrorKind.STALE
    assert "old" in target.read_text()


def test_apply_rejects_symlink(tmp_path, policy):
    real = tmp_path / "real.toml"
    real.write_text('model="old"\n')
    link = tmp_path / "config.toml"
    link.symlink_to(real)
    plan = plan_merge(
        link.read_text(),
        preferences(model="new"),
        preferences(model="old"),
        policy,
        {},
        str(link.absolute()),
    )
    with pytest.raises(SyncError):
        apply_plan(link, plan, plan.digest)


def test_invalid_toml_diagnostic_does_not_echo_source():
    with pytest.raises(SyncError) as error:
        Policy.parse("secret = DO-NOT-ECHO")
    assert "DO-NOT-ECHO" not in str(error.value)


def test_cli_compare_does_not_write_destination_and_export_is_exclusive(tmp_path):
    policy = tmp_path / "policy.toml"
    policy.write_text('schema_version=1\nkeys=["model"]')
    target = tmp_path / "config.toml"
    target.write_text('model="local"\n')
    shared = tmp_path / "shared.toml"
    shared.write_text(preferences(model="shared"))
    args = [
        sys.executable,
        "-m",
        "ai_magic.codex_sync_cli",
        "compare",
        "--destination",
        str(target),
        "--policy",
        str(policy),
        "--shared",
        str(shared),
    ]
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    assert result.returncode == 2 and "conflict" in result.stdout
    assert target.read_text() == 'model="local"\n'
    output = tmp_path / "export.toml"
    export = [
        sys.executable,
        "-m",
        "ai_magic.codex_sync_cli",
        "export",
        "--source",
        str(target),
        "--policy",
        str(policy),
        "--output",
        str(output),
    ]
    assert subprocess.run(export, check=False, capture_output=True).returncode == 0
    assert output.stat().st_mode & 0o777 == 0o600
    assert subprocess.run(export, check=False, capture_output=True).returncode == 1


def test_concurrent_edit_during_apply_is_preserved(tmp_path, policy, monkeypatch):
    import ai_magic.codex_sync as sync

    target = tmp_path / "config.toml"
    target.write_text('model="old"\n')
    plan = plan_merge(
        target.read_text(),
        preferences(model="new"),
        preferences(model="old"),
        policy,
        {},
        str(target.absolute()),
    )
    original = sync.tempfile.mkstemp

    def app_edits_after_planning(*args, **kwargs):
        result = original(*args, **kwargs)
        target.write_text('model="app-edited"\n')
        return result

    monkeypatch.setattr(sync.tempfile, "mkstemp", app_edits_after_planning)
    with pytest.raises(SyncError) as error:
        apply_plan(target, plan, plan.digest)
    assert error.value.kind is ErrorKind.STALE
    assert target.read_text() == 'model="app-edited"\n'
    assert not list(tmp_path.glob(".codex-sync-*"))


@pytest.mark.parametrize("version", [True, "1", 2])
def test_schema_version_is_strict(version):
    with pytest.raises(SyncError):
        Policy.parse(tomlkit.dumps({"schema_version": version, "keys": []}))


def test_unowned_empty_table_rejected(policy):
    with pytest.raises(SyncError) as error:
        plan_merge("", "schema_version=1\n[values.projects]", None, policy, {})
    assert error.value.kind is ErrorKind.OWNERSHIP


def test_line_ending_only_edit_invalidates_approval(tmp_path, policy):
    target = tmp_path / "config.toml"
    target.write_bytes(b'model="old"\r\n')
    plan = plan_merge(
        read_config(target),
        preferences(model="new"),
        preferences(model="old"),
        policy,
        {},
        str(target.absolute()),
    )
    target.write_bytes(b'model="old"\n')
    with pytest.raises(SyncError) as error:
        apply_plan(target, plan, plan.digest)
    assert error.value.kind is ErrorKind.STALE


def test_nested_preference_update_retains_tui_local_fields_and_comments():
    policy = Policy.parse('schema_version=1\nkeys=["tui.status_line"]')
    local = '[tui]\nstatus_line=["model"] # user layout\npet="local-pet"\nstatus_line_use_colors=false\n'
    shared = 'schema_version=1\n[values.tui]\nstatus_line=["model", "context-used"]'
    base = 'schema_version=1\n[values.tui]\nstatus_line=["model"]'
    plan = plan_merge(local, shared, base, policy, {})
    assert tomllib.loads(plan.candidate)["tui"] == {
        "status_line": ["model", "context-used"],
        "pet": "local-pet",
        "status_line_use_colors": False,
    }
    assert "# user layout" in plan.candidate


def test_quoted_dotted_alias_cannot_silently_override_selector():
    policy = Policy.parse('schema_version=1\nkeys=["tui.status_line"]')
    shared = 'schema_version=1\n[values]\n"tui.status_line"=["one"]\n[values.tui]\nstatus_line=["two"]'
    with pytest.raises(SyncError):
        plan_merge("", shared, None, policy, {})
