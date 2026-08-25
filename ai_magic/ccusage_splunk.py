"""Export the last seven days of ccusage data to Splunk HEC."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import Field, HttpUrl, ValidationError
from pydantic_settings import BaseSettings, CliImplicitFlag, SettingsConfigDict

CCUSAGE_COMMAND = [
    "ccusage",
    "daily",
    "--json",
    "--by-agent",
    "--compact",
    "--no-color",
    "--last",
    "7",
]
HEC_EVENT_PATH = "/services/collector/event"


class Settings(BaseSettings):
    """Configuration read from command-line environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        cli_kebab_case=True,
        cli_parse_args=True,
    )

    dry_run: CliImplicitFlag[bool] = Field(
        False, description="Print events to stdout instead of sending to Splunk"
    )
    splunk_index: str = "test"
    splunk_base_url: HttpUrl
    splunk_hec_token: str

    @property
    def hec_endpoint(self) -> httpx.URL:
        """Return the collector endpoint below the configured base URL."""
        return httpx.URL(str(self.splunk_base_url)).copy_with(
            path=HEC_EVENT_PATH, query=None
        )


class ExportError(Exception):
    """An expected ccusage or HEC export failure."""


def read_ccusage() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run ccusage and validate the two datasets required for export."""
    result = subprocess.run(
        CCUSAGE_COMMAND,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or "no error output"
        raise ExportError(
            f"ccusage failed with exit code {result.returncode}: {detail}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ExportError(f"ccusage returned invalid JSON: {error.msg}") from error

    if not isinstance(payload, Mapping):
        raise ExportError("ccusage JSON must be an object")

    daily = payload.get("daily")
    totals = payload.get("totals")
    if not isinstance(daily, list):
        raise ExportError("ccusage JSON must contain a daily list")
    if not isinstance(totals, dict):
        raise ExportError("ccusage JSON must contain a totals object")
    if not all(isinstance(item, dict) for item in daily):
        raise ExportError("ccusage daily entries must be objects")

    return daily, totals


def upload_event(
    client: httpx.Client,
    settings: Settings,
    dataset: str,
    event: dict[str, Any],
    description: str,
) -> None:
    """Send one dataset record to HEC and raise on any rejected event."""
    if settings.dry_run:
        print(f"Would send '{description}' to {settings.hec_endpoint}: {event}")
        return
    response = client.post(
        settings.hec_endpoint,
        headers={"Authorization": f"Splunk {settings.splunk_hec_token}"},
        json={
            "event": event,
            "index": settings.splunk_index,
            "sourcetype": f"ccusage:{dataset}",
        },
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise ExportError(
            f"HEC rejected {description}: HTTP {response.status_code}"
        ) from error

    try:
        hec_response = response.json()
    except json.JSONDecodeError as error:
        raise ExportError(f"HEC returned invalid JSON for {description}") from error
    if not isinstance(hec_response, Mapping) or hec_response.get("code") != 0:
        raise ExportError(f"HEC rejected {description}: {hec_response!r}")
    print(
        f"Successfully sent '{description}' to {settings.hec_endpoint}", file=sys.stderr
    )


def export(settings: Settings) -> None:
    """Export daily entries in order followed by the aggregate totals."""
    daily, totals = read_ccusage()
    with httpx.Client(timeout=30.0) as client:
        for item in daily:
            period = item.get("period", "unknown period")
            upload_event(client, settings, "daily", item, f"daily event for {period}")
        upload_event(client, settings, "totals", totals, "totals")


def main() -> int:
    """Run the exporter and present configuration/export failures on stderr."""
    try:
        export(Settings())
    except ValidationError as error:
        print(f"Invalid Splunk configuration: {error}", file=sys.stderr)
        return 2
    except (ExportError, httpx.HTTPError) as error:
        print(f"ccusage export failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
