#!/usr/bin/env python3
"""Mark Dependabot notifications for merged pull requests as read."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

DEPENDABOT_LOGINS = {"dependabot[bot]", "app/dependabot"}


@dataclass(frozen=True)
class Candidate:
    thread_id: str
    repository: str
    pull_request: int
    title: str
    author: str
    merged_at: str


def run_gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown gh error"
        raise RuntimeError(detail)
    return result.stdout


def notifications() -> list[dict[str, object]]:
    raw = run_gh(
        "api",
        "--paginate",
        "--slurp",
        "-H",
        "Accept: application/vnd.github+json",
        "/notifications?all=false&per_page=100",
    )
    pages = json.loads(raw)
    return [item for page in pages for item in page]


def pull_request_reference(notification: dict[str, object]) -> tuple[str, int] | None:
    subject = notification.get("subject")
    repository = notification.get("repository")
    if not isinstance(subject, dict) or not isinstance(repository, dict):
        return None
    if subject.get("type") != "PullRequest":
        return None
    subject_url = subject.get("url")
    repository_name = repository.get("full_name")
    if not isinstance(subject_url, str) or not isinstance(repository_name, str):
        return None
    path_parts = [part for part in urlparse(subject_url).path.split("/") if part]
    if len(path_parts) < 4 or path_parts[-2] != "pulls":
        return None
    try:
        number = int(path_parts[-1])
    except ValueError:
        return None
    return repository_name, number


def find_candidates() -> list[Candidate]:
    result: list[Candidate] = []
    pull_requests: dict[tuple[str, int], dict[str, object]] = {}
    for notification in notifications():
        if notification.get("unread") is not True:
            continue
        reference = pull_request_reference(notification)
        if reference is None:
            continue
        repository, number = reference
        key = (repository, number)
        if key not in pull_requests:
            pull_requests[key] = json.loads(
                run_gh("api", f"/repos/{repository}/pulls/{number}")
            )
        pull_request = pull_requests[key]
        user = pull_request.get("user")
        author = user.get("login") if isinstance(user, dict) else None
        merged_at = pull_request.get("merged_at")
        if author not in DEPENDABOT_LOGINS or not isinstance(merged_at, str):
            continue
        thread_id = notification.get("id")
        title = pull_request.get("title")
        if not isinstance(thread_id, str) or not isinstance(title, str):
            continue
        result.append(
            Candidate(
                thread_id=thread_id,
                repository=repository,
                pull_request=number,
                title=title,
                author=author,
                merged_at=merged_at,
            )
        )
    return result


def mark_done(candidate: Candidate) -> None:
    run_gh(
        "api",
        "--method",
        "PATCH",
        "-H",
        "Accept: application/vnd.github+json",
        f"/notifications/threads/{candidate.thread_id}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="mark matching notification threads as read",
    )
    args = parser.parse_args()

    try:
        candidates = find_candidates()
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if not candidates:
        print("No unread notifications matched.")
        return 0

    failures = 0
    for candidate in candidates:
        action = "marking" if args.apply else "would mark"
        print(
            f"{action} {candidate.repository}#{candidate.pull_request}: "
            f"{candidate.title} (merged {candidate.merged_at}; "
            f"thread {candidate.thread_id})"
        )
        if not args.apply:
            continue
        try:
            mark_done(candidate)
        except RuntimeError as error:
            failures += 1
            print(
                f"error: could not mark thread {candidate.thread_id}: {error}",
                file=sys.stderr,
            )

    if failures:
        print(f"{failures} notification(s) failed.", file=sys.stderr)
        return 1
    if args.apply:
        print(f"Marked {len(candidates)} notification(s) as done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
