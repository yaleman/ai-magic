#!/usr/bin/env python3
"""Collect a read-only triage snapshot of GitHub notifications and open PR checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse


def run_command(
    args: Sequence[str], *, allow_failure: bool = False
) -> tuple[int, str, str]:
    result = subprocess.run(
        list(args),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{' '.join(args)}: {detail}")
    return result.returncode, result.stdout, result.stderr


def run_gh(*args: str, allow_failure: bool = False) -> tuple[int, str, str]:
    return run_command(["gh", *args], allow_failure=allow_failure)


def fetch_notifications() -> list[dict[str, Any]]:
    _, raw, _ = run_gh(
        "api",
        "--paginate",
        "--slurp",
        "-H",
        "Accept: application/vnd.github+json",
        "/notifications?all=false&per_page=100",
    )
    pages = json.loads(raw)
    if not isinstance(pages, list):
        raise TypeError("GitHub returned a non-list notification response")
    if pages and isinstance(pages[0], dict):
        return pages
    return [item for page in pages for item in page]


def pull_request_reference(notification: dict[str, Any]) -> tuple[str, int] | None:
    subject = notification.get("subject")
    repository = notification.get("repository")
    if not isinstance(subject, dict) or not isinstance(repository, dict):
        return None
    if subject.get("type") != "PullRequest":
        return None
    repository_name = repository.get("full_name")
    subject_url = subject.get("url")
    if not isinstance(repository_name, str) or not isinstance(subject_url, str):
        return None
    path_parts = [part for part in urlparse(subject_url).path.split("/") if part]
    if len(path_parts) < 4 or path_parts[-2] != "pulls":
        return None
    try:
        return repository_name, int(path_parts[-1])
    except ValueError:
        return None


def fetch_pull_request(repository: str, number: int) -> dict[str, Any]:
    _, raw, _ = run_gh("api", f"/repos/{repository}/pulls/{number}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError(
            f"GitHub returned invalid PR metadata for {repository}#{number}"
        )
    return payload


def fetch_checks(repository: str, number: int) -> dict[str, Any]:
    returncode, raw, stderr = run_gh(
        "pr",
        "checks",
        str(number),
        "--repo",
        repository,
        "--json",
        "name,state,bucket,link,workflow",
        allow_failure=True,
    )
    if returncode != 0:
        return {"error": stderr.strip() or raw.strip() or "check lookup failed"}
    try:
        checks = json.loads(raw)
    except json.JSONDecodeError as error:
        return {"error": f"invalid check response: {error}"}
    return {"checks": checks}


def summarize_checks(check_data: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for check in check_data.get("checks", []):
        if not isinstance(check, dict):
            continue
        bucket = check.get("bucket", "unknown")
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def collect() -> dict[str, Any]:
    raw_notifications = fetch_notifications()
    pull_request_cache: dict[tuple[str, int], dict[str, Any]] = {}
    check_cache: dict[tuple[str, int], dict[str, Any]] = {}
    items: list[dict[str, Any]] = []

    for notification in raw_notifications:
        subject = notification.get("subject")
        repository = notification.get("repository")
        if not isinstance(subject, dict) or not isinstance(repository, dict):
            continue
        repository_name = repository.get("full_name")
        if not isinstance(repository_name, str):
            continue
        item: dict[str, Any] = {
            "id": notification.get("id"),
            "unread": notification.get("unread"),
            "reason": notification.get("reason"),
            "updated_at": notification.get("updated_at"),
            "repository": repository_name,
            "subject_type": subject.get("type"),
            "title": subject.get("title"),
            "url": repository.get("html_url"),
        }
        reference = pull_request_reference(notification)
        if reference is not None:
            repository_name, number = reference
            key = (repository_name, number)
            if key not in pull_request_cache:
                pull_request_cache[key] = fetch_pull_request(repository_name, number)
            pull_request = pull_request_cache[key]
            user = pull_request.get("user")
            item["pull_request"] = {
                "number": number,
                "url": pull_request.get("html_url"),
                "state": pull_request.get("state"),
                "merged_at": pull_request.get("merged_at"),
                "draft": pull_request.get("draft"),
                "mergeable": pull_request.get("mergeable"),
                "mergeable_state": pull_request.get("mergeable_state"),
                "author": user.get("login") if isinstance(user, dict) else None,
                "changed_files": pull_request.get("changed_files"),
                "additions": pull_request.get("additions"),
                "deletions": pull_request.get("deletions"),
            }
            if pull_request.get("state") == "open":
                if key not in check_cache:
                    check_cache[key] = fetch_checks(repository_name, number)
                item["checks"] = check_cache[key]
                item["check_summary"] = summarize_checks(check_cache[key])
        items.append(item)

    pull_requests = [item for item in items if "pull_request" in item]
    open_review_requests = [
        item
        for item in pull_requests
        if item.get("reason") == "review_requested"
        and item["pull_request"].get("state") == "open"
    ]
    merged_or_closed = [
        item for item in pull_requests if item["pull_request"].get("state") != "open"
    ]
    other_open_prs = [
        item
        for item in pull_requests
        if item not in open_review_requests
        and item["pull_request"].get("state") == "open"
    ]
    non_pr = [item for item in items if "pull_request" not in item]

    return {
        "notification_count": len(items),
        "pull_request_count": len(pull_requests),
        "open_review_request_count": len(open_review_requests),
        "merged_or_closed_count": len(merged_or_closed),
        "other_open_pr_count": len(other_open_prs),
        "non_pr_count": len(non_pr),
        "open_review_requests": open_review_requests,
        "other_open_prs": other_open_prs,
        "merged_or_closed": merged_or_closed,
        "non_pr": non_pr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit the complete JSON triage snapshot"
    )
    args = parser.parse_args()
    try:
        snapshot = collect()
    except (RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
        return 0

    print(f"Unread notifications: {snapshot['notification_count']}")
    print(f"Open review requests: {snapshot['open_review_request_count']}")
    print(f"Merged/closed PR notifications: {snapshot['merged_or_closed_count']}")
    print(f"Other open PR notifications: {snapshot['other_open_pr_count']}")
    print(f"Non-PR notifications: {snapshot['non_pr_count']}")
    for item in snapshot["open_review_requests"]:
        pull_request = item["pull_request"]
        summary = (
            ", ".join(
                f"{key}={value}" for key, value in item.get("check_summary", {}).items()
            )
            or "no checks"
        )
        print(
            f"{item['repository']}#{pull_request['number']} "
            f"[{pull_request['state']}] {item['title']} — {summary}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
