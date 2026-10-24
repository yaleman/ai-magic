# Codex preference sync

`ai_magic.codex_sync_cli` exports selected preferences and produces a conservative
three-way TOML merge. `compare` is read-only. Source deployment, plugin installation,
credentials, sessions, databases, caches and whole-directory synchronisation are
outside this tool. Authored plugins and skills stay in their source repositories.

The starter ownership profile is `examples/codex-sync/policy.toml`. It selects six
ordinary preferences and one example skill's explicit enabled choice/path template.
Adapt the example skill identity/template to a reviewed installed skill before use. It does
not own all of `tui`, `skills`, `plugins` or any other table. Only the policy's
selected leaf values can change. Keys not present in shared preferences are retained;
this version does not implement deletions.

The built-in ceiling permits model/reasoning/personality/web-search identifiers,
TUI status-line identifiers/colors, explicitly selected `@personal` plugin enabled
flags, and path-based skill enabled flags/templates. It rejects ownership of security,
project trust, auth, MCP, marketplaces, hooks, shell environment and arbitrary keys.
Runtime-managed plugin flags are not supported. New ownership classes require code
review; a policy file cannot grant them. Unknown destination tables/fields survive.

## Export on an authorised source host

Run from this repository after preparing its locked environment:

```sh
uv sync --locked
sync_dir="${CODEX_SYNC_DIR:?Set CODEX_SYNC_DIR to the reviewed shared-preferences directory}"
uv run --locked python -m ai_magic.codex_sync_cli export \
  --source "${CODEX_HOME:-$HOME/.codex}/config.toml" \
  --policy examples/codex-sync/policy.toml \
  --map "CODEX_HOME=${CODEX_HOME:-$HOME/.codex}" \
  --output "$sync_dir/preferences-review.toml"
```

Export reads only the specified config, not auth files or credential stores. Only
selected values enter the export. Review it before making it the shared snapshot.
Outputs are created exclusively with mode 0600; existing paths are never overwritten.
Preferences accept identifiers, not arbitrary instruction text or machine paths.

Path templates such as `{CODEX_HOME}/skills/example/SKILL.md` are portable references,
not source copies. Each target supplies its absolute root via `--map`. Export refuses
a source skill whose location disagrees with the explicit mapping. Duplicate skill
identities, named-vs-path ambiguity, missing mappings, traversal and introducing a
missing skill file are errors. This tool never installs or relocates that skill.
Resolve source/install content drift separately before deploying source revisions.

## Compare on an authorised destination host

Run locally on the destination after the repository, locked environment and reviewed
shared files are available there. No SSH or remote host access is performed:

```sh
sync_dir="${CODEX_SYNC_DIR:?Set CODEX_SYNC_DIR to the reviewed shared-preferences directory}"
review_dir="$(mktemp -d "${TMPDIR:-/tmp}/codex-compare.XXXXXX")"
printf 'Comparison artifacts: %s\n' "$review_dir"
uv run --locked --no-sync python -m ai_magic.codex_sync_cli compare \
  --destination "${CODEX_HOME:-$HOME/.codex}/config.toml" \
  --policy "$sync_dir/shared/ownership.toml" \
  --shared "$sync_dir/shared/preferences.toml" \
  --map "CODEX_HOME=${CODEX_HOME:-$HOME/.codex}" \
  --report "$review_dir/compare.json" --diff "$review_dir/compare.diff"
```

The report and diff show owned values only, with no unowned TOML context or full
candidate config. Local reports can contain selected local paths; keep them local.
Exit 0 means a non-conflicting plan, 2 means conflicts, and 1 means invalid input/IO.
No output file is a new live config. There is no source-to-destination full-file copy.

For a first import, omit `--base`: any different existing value is a conflict rather
than being silently overwritten. Later, `--base` must be the last shared snapshot
actually applied on that destination. Never use a source export as a fictitious
previously-applied baseline. If shared equals base but the destination differs, the
local edit wins. Omitted shared values never delete local keys. Conflicting plans
have no partial candidate or diff; inspect the conflict entries in JSON.

After reviewing a conflict, add an explicit decision and compare again:

```sh
# Choose only the reviewed key; all other conflicts remain unresolved.
uv run --locked --no-sync python -m ai_magic.codex_sync_cli compare \
  --destination "$target_config" --policy "$ownership" --shared "$preferences" \
  --map "CODEX_HOME=$target_codex_home" --resolve preference:model=shared
```

Use `=destination` to preserve that conflicting local choice. Unused/unknown
resolutions fail rather than widening the selection. Decisions bind to the report's
approval digest along with the destination bytes, absolute target path, inputs,
policy and root mappings. The digest is a stale-plan guard, not user authorization.

## Apply only after separate approval

No live apply is part of the initial build/comparison task. After approval, close any
app/CLI writers and prepare local recovery appropriate to the owned changes. Then
rerun the exact reviewed compare arguments as the explicit `apply` subcommand with
`--approve-digest` from that comparison. Unresolved conflicts, changed inputs,
destination edits, a different target or symlink targets cause refusal. An unchanged
plan does not rewrite the file. Successful apply preserves file mode and uses an
atomic replacement in the same directory. It does not create a full config backup
or export unowned credentials to a backup/report. Maintain the last actually applied
shared snapshot locally for future comparisons; the tool does not advance it on a
mere comparison or failed apply.

The app does not participate in this tool's locking. A final stale check catches
observed concurrent edits, but cannot eliminate the small check/replace race with
an uncooperative writer. Closing writers before applying is required. Atomic
replacement is not a guarantee that the app will accept every preference across
versions: check the installed CLI/app version and supported keys on each target.

## Development

```sh
uv run --locked pytest tests/test_codex_sync.py
uv run --locked ruff check ai_magic/codex_sync.py ai_magic/codex_sync_cli.py tests/test_codex_sync.py
uv run --locked ty check ai_magic/codex_sync.py ai_magic/codex_sync_cli.py
```

Tests use temporary configs and fake skill files. They check preservation, secret
non-export, conflicts and explicit decisions, per-host path mapping, arrays with
unowned entries, idempotence, stale plans, concurrent edits and permissions. No
service requests, plugin installs or live config writes are involved.
