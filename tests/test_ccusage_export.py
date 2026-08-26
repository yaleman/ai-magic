import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock, patch

import httpx
import pytest

from ai_magic import ccusage_splunk


def settings(url: str = "https://splunk.example") -> ccusage_splunk.Settings:
    return ccusage_splunk.Settings(
        _cli_parse_args=False,
        splunk_base_url=url,
        splunk_hec_token="test-token",
    )


def ccusage_payload() -> dict[str, Any]:
    return {
        "daily": [
            {
                "period": "2026-08-24",
                "agents": [
                    {
                        "agent": "codex",
                        "totalCost": 1.25,
                        "modelBreakdowns": [{"modelName": "gpt-5.6-sol", "cost": 1.25}],
                    }
                ],
                "modelBreakdowns": [
                    {"modelName": "gpt-5.6-sol", "cost": 1.25},
                    {"modelName": "shared-model", "cost": 0.5},
                ],
            },
            {
                "period": "2026-08-25",
                "agents": [],
                "modelBreakdowns": [{"modelName": "aggregate", "cost": 2.50}],
            },
        ],
        "totals": {"totalCost": 3.75},
    }


def successful_response() -> Mock:
    response = Mock()
    response.json.return_value = {"code": 0, "text": "Success"}
    return response


def export_time() -> datetime:
    return datetime(
        2026, 8, 26, 14, 15, 16, 789_000, tzinfo=timezone(timedelta(hours=10))
    )


def test_export_splits_daily_records_into_agent_events_then_totals() -> None:
    completed = subprocess.CompletedProcess(
        ccusage_splunk.CCUSAGE_COMMAND,
        0,
        stdout=json.dumps(ccusage_payload()),
        stderr="",
    )
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=None)
    client.post.side_effect = [
        successful_response(),
        successful_response(),
        successful_response(),
        successful_response(),
        successful_response(),
    ]

    with (
        patch("ai_magic.ccusage_splunk.subprocess.run", return_value=completed),
        patch("ai_magic.ccusage_splunk.httpx.Client", return_value=client),
        patch("ai_magic.ccusage_splunk.current_local_time", return_value=export_time()),
    ):
        ccusage_splunk.export(settings())

    assert client.post.call_count == 5
    requests = [call.kwargs["json"] for call in client.post.call_args_list]
    assert [request["event"] for request in requests] == [
        {
            "modelName": "gpt-5.6-sol",
            "cost": 1.25,
            "agent": "codex",
            "period": "2026-08-24",
        },
        {
            "modelName": "shared-model",
            "cost": 0.5,
            "period": "2026-08-24",
        },
        {
            "agent": "codex",
            "totalCost": 1.25,
            "period": "2026-08-24",
        },
        {
            "modelName": "aggregate",
            "cost": 2.50,
            "period": "2026-08-25",
        },
        {"totalCost": 3.75},
    ]
    assert [request["sourcetype"] for request in requests] == [
        "ccusage:agent:model",
        "ccusage:agent:model",
        "ccusage:agent:stats",
        "ccusage:agent:model",
        "ccusage:totals",
    ]
    assert all(request["index"] == "test" for request in requests)
    assert client.post.call_args.kwargs["headers"] == {
        "Authorization": "Splunk test-token"
    }


def test_with_event_time_rejects_an_invalid_period() -> None:
    with pytest.raises(ccusage_splunk.ExportError, match="not an ISO date"):
        ccusage_splunk.with_event_time({"period": "not-a-date"})


def test_endpoint_uses_the_configured_url_port() -> None:
    assert str(settings().hec_endpoint).startswith(
        "https://splunk.example/services/collector/event"
    )
    assert str(settings("https://splunk.example:9999").hec_endpoint).startswith(
        "https://splunk.example:9999/services/collector/event"
    )


def test_settings_accept_cli_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ccusage-export",
            "--splunk-base-url",
            "https://collector.example",
            "--splunk-hec-token",
            "cli-token",
            "--splunk-index",
            "production",
        ],
    )
    configured = ccusage_splunk.Settings()

    assert configured.splunk_index == "production"
    assert configured.splunk_hec_token == "cli-token"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"totals": {}}, "daily list"),
        ({"daily": []}, "totals object"),
        ({"daily": ["not an object"], "totals": {}}, "entries must be objects"),
    ],
)
def test_read_ccusage_rejects_invalid_datasets(payload: object, message: str) -> None:
    completed = subprocess.CompletedProcess(
        ccusage_splunk.CCUSAGE_COMMAND, 0, stdout=json.dumps(payload), stderr=""
    )

    with (
        patch("ai_magic.ccusage_splunk.subprocess.run", return_value=completed),
        pytest.raises(ccusage_splunk.ExportError, match=message),
    ):
        ccusage_splunk.read_ccusage()


def test_read_ccusage_rejects_command_failure_and_invalid_json() -> None:
    failed = subprocess.CompletedProcess(
        ccusage_splunk.CCUSAGE_COMMAND, 3, stdout="", stderr="database unavailable"
    )
    with (
        patch("ai_magic.ccusage_splunk.subprocess.run", return_value=failed),
        pytest.raises(ccusage_splunk.ExportError, match="exit code 3"),
    ):
        ccusage_splunk.read_ccusage()

    invalid_json = subprocess.CompletedProcess(
        ccusage_splunk.CCUSAGE_COMMAND, 0, stdout="not json", stderr=""
    )
    with (
        patch("ai_magic.ccusage_splunk.subprocess.run", return_value=invalid_json),
        pytest.raises(ccusage_splunk.ExportError, match="invalid JSON"),
    ):
        ccusage_splunk.read_ccusage()


def test_export_stops_after_first_hec_failure() -> None:
    completed = subprocess.CompletedProcess(
        ccusage_splunk.CCUSAGE_COMMAND,
        0,
        stdout=json.dumps(ccusage_payload()),
        stderr="",
    )
    response = Mock(status_code=503)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "service unavailable",
        request=httpx.Request("POST", "https://splunk.example"),
        response=httpx.Response(503),
    )
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=None)
    client.post.return_value = response

    with (
        patch("ai_magic.ccusage_splunk.subprocess.run", return_value=completed),
        patch("ai_magic.ccusage_splunk.httpx.Client", return_value=client),
        pytest.raises(ccusage_splunk.ExportError, match="codex during 2026-08-24"),
    ):
        ccusage_splunk.export(settings())

    assert client.post.call_count == 1
