---
name: github-notification-review
description: Review the authenticated GitHub notification feed, triage actionable PRs and issues, and inspect open PR CI without changing GitHub state.
---

# GitHub Notification Review

Use this skill when the user asks to review, triage, or work through GitHub notifications.

## Safety and scope

This is a read-only review workflow. Do not mark notifications read, comment, approve, merge, rerun checks, or change repository state unless the user separately asks for that exact action.

Use the pull request's actual metadata, not notification text, to classify it:

- `user.login` identifies the PR author;
- `merged_at` identifies a merged PR;
- `state`, `draft`, `mergeable`, and `mergeable_state` describe current PR state;
- the notification `reason` identifies why the user was notified, not who authored the PR.

## Workflow

1. Run `gh auth status` in a login shell so the user's configured `GH_TOKEN`/`GITHUB_TOKEN` environment is loaded. Never print token values. If authentication fails, stop.
2. Fetch the unread notification feed with `gh api --paginate --slurp '/notifications?all=false&per_page=100'`.
3. Summarize the feed counts and group items into:
   - open review requests;
   - other open pull requests;
   - merged or closed pull-request notifications;
   - issues, advisories, releases, and other non-PR notifications.
4. For every pull-request notification, fetch current PR metadata from `/repos/{owner}/{repo}/pulls/{number}`. Do not trust stale notification state.
5. For every open PR, inspect GitHub Actions checks with:

   ```sh
   gh pr checks <number> --repo <owner>/<repo> --json name,state,bucket,link,workflow
   ```

   Use the available fields exactly; do not request unsupported fields such as `conclusion`.
6. Report a concise prioritized handoff: what is actionable, what is already complete, which checks fail, and the likely next action. Link directly to the relevant PRs and issues.
7. If a failed check needs deeper diagnosis, fetch its run/job log with `gh run view` or the GitHub Actions job-log connector, then distinguish source failures from workflow/configuration or transient runner failures.
8. Stop after the read-only triage and ask which item or batch the user wants to work on.

## Bundled review script

The script performs the feed, PR metadata, and open-PR check collection. It emits JSON for reliable summarization:

```sh
zsh -lic 'python3 /Users/yaleman/.codex/skills/github-notification-review/scripts/review.py --json'
```

Run it with network access if the sandbox blocks GitHub API requests. The script never performs GitHub writes.

For deeper CI diagnosis, keep the scope narrow and use the failing check's linked run/job rather than rerunning or changing anything automatically.
