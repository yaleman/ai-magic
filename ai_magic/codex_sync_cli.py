"""CLI boundary for the allowlisted config sync library."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ai_magic.codex_sync import (
    ErrorKind,
    Policy,
    Resolution,
    SyncError,
    apply_plan,
    export_preferences,
    plan_merge,
    read_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export or compare owned preferences; never sync the whole Codex home"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("export", "compare", "apply"):
        command = sub.add_parser(name)
        command.add_argument("--policy", type=Path, required=True)
        command.add_argument(
            "--map", action="append", default=[], metavar="ROOT=/absolute/path"
        )
        if name == "export":
            command.add_argument("--source", type=Path, required=True)
            command.add_argument(
                "--output",
                type=Path,
                help="Create exclusively; never overwrite an existing file",
            )
        else:
            command.add_argument("--destination", type=Path, required=True)
            command.add_argument("--shared", type=Path, required=True)
            command.add_argument(
                "--base",
                type=Path,
                help="Last actually applied shared snapshot, not a guessed baseline",
            )
            command.add_argument(
                "--resolve",
                action="append",
                default=[],
                metavar="SELECTOR=shared|destination",
            )
            if name == "compare":
                command.add_argument(
                    "--report",
                    type=Path,
                    help="Create an owned-key JSON report exclusively",
                )
                command.add_argument(
                    "--diff", type=Path, help="Create an owned-key diff exclusively"
                )
            else:
                command.add_argument("--approve-digest", required=True)
    args = parser.parse_args()
    try:
        policy = Policy.parse(args.policy.read_text())
        mappings = {}
        for value in args.map:
            name, separator, path = value.partition("=")
            if not separator or name in mappings:
                raise SyncError(
                    ErrorKind.INPUT,
                    "Mappings must have unique ROOT=absolute-path entries",
                )
            mappings[name] = Path(path).expanduser()
        if args.command == "export":
            result = export_preferences(read_config(args.source), policy, mappings)
            if args.output:
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(result)
            else:
                print(result, end="")
            return 0
        resolutions = {}
        for value in args.resolve:
            selector, separator, decision = value.rpartition("=")
            if not separator or selector in resolutions:
                raise SyncError(
                    ErrorKind.INPUT,
                    "Resolutions require unique SELECTOR=shared|destination entries",
                )
            try:
                resolutions[selector] = Resolution(decision)
            except ValueError:
                raise SyncError(
                    ErrorKind.INPUT, "Resolution must be shared or destination"
                ) from None
        plan = plan_merge(
            read_config(args.destination),
            args.shared.read_text(),
            args.base.read_text() if args.base else None,
            policy,
            mappings,
            str(args.destination.absolute()),
            resolutions,
        )
        report = json.dumps(plan.report(), indent=2) + "\n"
        if args.command == "apply":
            apply_plan(args.destination, plan, args.approve_digest)
            print(report, end="")
        else:
            for target, content in [(args.report, report), (args.diff, plan.diff())]:
                if target:
                    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "w") as stream:
                        stream.write(content)
            print(report, end="")
            if not args.diff:
                print(plan.diff(), end="")
        return 2 if plan.conflicts else 0
    except SyncError as error:
        print(f"{error.kind.value}: {error}", file=sys.stderr)
        return 2 if error.kind is ErrorKind.CONFLICT else 1
    except (OSError, UnicodeError):
        print(
            "io: cannot read input or exclusively write output; no private file contents reported",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
