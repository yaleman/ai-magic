#!/usr/bin/env python3
"""Purge cached Cloudflare content for one hostname."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareError(Exception):
    """Raised when the Cloudflare API cannot complete the purge."""


@dataclass(frozen=True)
class PurgeResult:
    zone_id: str
    zone_name: str
    hostname: str
    purge_id: str | None


Opener = Callable[[Request], Any]


def normalize_hostname(hostname: str) -> str:
    normalized = hostname.strip().rstrip(".").lower()
    if not normalized or "/" in normalized or "://" in normalized or " " in normalized:
        raise CloudflareError(f"Invalid Cloudflare hostname: {hostname!r}")
    return normalized


def build_request(
    url: str, token: str, method: str = "GET", data: bytes | None = None
) -> Request:
    return Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "codex-cloudflare-cache-purge-skill/1.0",
        },
    )


def parse_response(response: Any) -> dict[str, Any]:
    try:
        payload = json.loads(response.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloudflareError(
            "Cloudflare returned a response that was not valid JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise CloudflareError("Cloudflare returned an unexpected response shape")

    if payload.get("success") is not True:
        raise CloudflareError(format_cloudflare_errors(payload))

    return payload


def format_cloudflare_errors(payload: Mapping[str, Any]) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        messages = []
        for error in errors:
            if isinstance(error, Mapping):
                code = error.get("code")
                message = error.get("message", "unknown Cloudflare API error")
                messages.append(f"{code}: {message}" if code else str(message))
            else:
                messages.append(str(error))
        return "; ".join(messages)
    return "Cloudflare API request failed"


def api_request(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=30) as response:
            return parse_response(response)
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CloudflareError(f"Cloudflare HTTP {exc.code}: {exc.reason}") from exc
        raise CloudflareError(format_cloudflare_errors(payload)) from exc
    except URLError as exc:
        raise CloudflareError(f"Could not reach Cloudflare API: {exc.reason}") from exc


def find_exact_zone(zone_name: str, token: str) -> tuple[str, str] | None:
    query = urlencode({"name": zone_name, "status": "active", "per_page": "50"})
    payload = api_request(build_request(f"{API_BASE}/zones?{query}", token))
    zones = payload.get("result")
    if not isinstance(zones, list):
        raise CloudflareError("Cloudflare zone lookup returned an unexpected result")

    exact_matches = [
        zone
        for zone in zones
        if isinstance(zone, Mapping)
        and zone.get("name") == zone_name
        and isinstance(zone.get("id"), str)
    ]
    if not exact_matches:
        return None
    if len(exact_matches) > 1:
        raise CloudflareError(
            f"Cloudflare returned multiple active zones named {zone_name}"
        )

    zone = exact_matches[0]
    return zone["id"], zone["name"]


def zone_candidates_for_hostname(hostname: str) -> list[str]:
    labels = hostname.split(".")
    return [".".join(labels[index:]) for index in range(max(len(labels) - 1, 0))]


def find_zone_for_hostname(hostname: str, token: str) -> tuple[str, str]:
    for candidate in zone_candidates_for_hostname(hostname):
        zone = find_exact_zone(candidate, token)
        if zone is not None:
            return zone
    raise CloudflareError(
        f"No Cloudflare zone found for {hostname} or its parent domains"
    )


def purge_hostname_cache(hostname: str, token: str) -> PurgeResult:
    normalized_hostname = normalize_hostname(hostname)
    zone_id, zone_name = find_zone_for_hostname(normalized_hostname, token)
    body = json.dumps({"hosts": [normalized_hostname]}).encode("utf-8")
    payload = api_request(
        build_request(
            f"{API_BASE}/zones/{zone_id}/purge_cache", token, method="POST", data=body
        ),
    )
    result = payload.get("result")
    purge_id = (
        result.get("id")
        if isinstance(result, Mapping) and isinstance(result.get("id"), str)
        else None
    )
    return PurgeResult(
        zone_id=zone_id,
        zone_name=zone_name,
        hostname=normalized_hostname,
        purge_id=purge_id,
    )


def main(
    argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    environment = os.environ if env is None else env

    if len(args) != 1 or args[0] in {"-h", "--help"}:
        print("Usage: cloudflare_purge_cache.py <hostname>", file=sys.stderr)
        raise SystemExit(2)

    token = environment.get("CLOUDFLARE_API_TOKEN")
    if not token:
        raise SystemExit("CLOUDFLARE_API_TOKEN is not set")

    try:
        result = purge_hostname_cache(args[0], token)
    except CloudflareError as exc:
        raise SystemExit(str(exc)) from exc

    purge_suffix = f" purge_id={result.purge_id}" if result.purge_id else ""
    print(
        f"Purged Cloudflare cache for host={result.hostname} zone={result.zone_name} "
        f"zone_id={result.zone_id}{purge_suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
