---
name: github-notification-cleanup
description: Safely mark GitHub notifications as done when they refer to merged pull requests authored by Dependabot.
---

# GitHub Notification Cleanup

Use this skill to clean the authenticated user's GitHub notification feed.

## Matching rule

Mark a notification thread as done only when all of these are true:

- the notification is unread;
- the subject type is `PullRequest`;
- the pull request author is `dependabot[bot]` or `app/dependabot`;
- the pull request has a non-null `merged_at` value.

Use the pull request's actual `user.login` and `merged_at` fields. Do not infer authorship from the notification reason, workflow actor, branch name, title, or comment text.

## Workflow

1. Run `gh auth status` in a login shell so the user's configured GitHub environment is loaded. Stop if authentication fails.
2. Enumerate the unread notification feed and inspect the referenced pull requests.
3. Show the matching repository, PR number, title, author, merge time, and notification thread ID.
4. When the user asked to perform the cleanup, run the bundled script with `--apply`. Otherwise, perform a dry run and report what would be changed.
5. Mark each matching thread as read with `PATCH /notifications/threads/{thread_id}`.
6. Report successes and any individual failures. Do not mark unrelated issues, releases, open PRs, or closed-but-unmerged PRs as done.

## Bundled script

The script uses the GitHub CLI, follows notification pagination, caches repeated PR lookups, and is idempotent:

```sh
zsh -lic 'python3 /Users/yaleman/.codex/skills/github-notification-cleanup/scripts/cleanup.py'
zsh -lic 'python3 /Users/yaleman/.codex/skills/github-notification-cleanup/scripts/cleanup.py --apply'
```

The first command is a dry run. `--apply` is required for the write operation.

Do not print or inspect token values. If `gh auth status` reports an invalid or missing credential, stop and ask the user to repair authentication.
