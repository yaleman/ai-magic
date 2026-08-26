"""Export the last seven days of ccusage data to Splunk HEC."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator, Mapping
from datetime import date, datetime, time
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
            path=HEC_EVENT_PATH, query=b"auto_extract_timestamp=true"
        )


class ExportError(Exception):
    """An expected ccusage or HEC export failure."""


def current_local_time() -> datetime:
    """Return the current timezone-aware local time."""
    return datetime.now().astimezone()


def with_event_time(event: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Add a Splunk event timestamp using its period or the supplied local time."""
    period = event.get("period")
    if period is None:
        timestamp = now
    elif isinstance(period, str):
        try:
            period_date = date.fromisoformat(period)
        except ValueError as error:
            raise ExportError(
                f"ccusage period is not an ISO date: {period!r}"
            ) from error
        timestamp = datetime.combine(period_date, time(), tzinfo=now.tzinfo)
    else:
        raise ExportError("ccusage period must be a string")

    return {**event, "time": timestamp.timestamp()}


def daily_events(
    daily: list[dict[str, Any]],
) -> Iterator[tuple[str, dict[str, Any], str]]:
    """Split ccusage daily records into searchable agent statistics and models."""
    for daily_record in daily:
        period = daily_record.get("period")
        if period is not None and not isinstance(period, str):
            raise ExportError("ccusage daily entries must contain a period string")
        period_fields = {"period": period} if period is not None else {}
        period_description = period or "an unknown period"

        agents = daily_record.get("agents", [])
        if not isinstance(agents, list) or not all(
            isinstance(agent, Mapping) for agent in agents
        ):
            raise ExportError("ccusage daily agents must be a list of objects")

        agent_models: list[Mapping[str, Any]] = []
        for agent in agents:
            agent_name = agent.get("agent")
            if not isinstance(agent_name, str):
                raise ExportError("ccusage daily agents must contain an agent string")

            model_breakdowns = agent.get("modelBreakdowns", [])
            if not isinstance(model_breakdowns, list) or not all(
                isinstance(model, Mapping) for model in model_breakdowns
            ):
                raise ExportError(
                    "ccusage agent modelBreakdowns must be a list of objects"
                )

            for model in model_breakdowns:
                agent_models.append(model)
                yield (
                    "agent:model",
                    {**model, "agent": agent_name, **period_fields},
                    f"agent model event for {agent_name} during {period_description}",
                )

        model_breakdowns = daily_record.get("modelBreakdowns", [])
        if not isinstance(model_breakdowns, list) or not all(
            isinstance(model, Mapping) for model in model_breakdowns
        ):
            raise ExportError("ccusage daily modelBreakdowns must be a list of objects")

        unmatched_agent_models = list(agent_models)
        for model in model_breakdowns:
            if model in unmatched_agent_models:
                unmatched_agent_models.remove(model)
                continue
            yield (
                "agent:model",
                {**model, **period_fields},
                f"aggregate model event during {period_description}",
            )

        for agent in agents:
            yield (
                "agent:stats",
                {key: value for key, value in agent.items() if key != "modelBreakdowns"}
                | period_fields,
                f"agent stats event for {agent['agent']} during {period_description}",
            )


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
    payload = {
        "event": event,
        "index": settings.splunk_index,
        "sourcetype": f"ccusage:{dataset}",
    }

    if "time" in event:
        payload["time"] = event.pop("time")
    response = client.post(
        settings.hec_endpoint,
        headers={"Authorization": f"Splunk {settings.splunk_hec_token}"},
        json=payload,
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
    """Export split agent events in daily order followed by aggregate totals."""
    daily, totals = read_ccusage()
    now = current_local_time()
    with httpx.Client(timeout=30.0) as client:
        for dataset, event, description in daily_events(daily):
            upload_event(
                client, settings, dataset, with_event_time(event, now), description
            )
        upload_event(client, settings, "totals", with_event_time(totals, now), "totals")


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
