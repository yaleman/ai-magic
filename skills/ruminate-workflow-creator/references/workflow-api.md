# Workflow API Reference

## Endpoint configuration
`https://example.com:9000` is a documentation placeholder only. Never request it.
Resolve a real endpoint from the user or `RUMINATE_BASE_URL` before using these
commands. Stop if it is missing or its hostname is `example.com` or a subdomain.
Do not source arbitrary files to obtain configuration. Keep real endpoints and
credentials outside tracked source.

The shell examples below assume `RUMINATE_BASE_URL` is already set to the real,
validated endpoint. All workflow and run paths are relative to that base URL.

## Source of truth
- OpenAPI JSON: `${RUMINATE_BASE_URL}/api-doc/openapi.json`

## Quick inspection commands
Before running a curl example, validate the configured URL (this makes no
network request):

```sh
python3 - <<'PYURL'
import os
from urllib.parse import urlsplit

url = urlsplit(os.environ.get("RUMINATE_BASE_URL", ""))
host = (url.hostname or "").lower().rstrip(".")
if url.scheme not in {"http", "https"} or not host or host == "example.com" or host.endswith(".example.com"):
    raise SystemExit("Set RUMINATE_BASE_URL to a real Ruminate endpoint; example.com is a placeholder")
PYURL
```

```bash
curl -sS "${RUMINATE_BASE_URL:?Set a real Ruminate base URL first}/api-doc/openapi.json" | jq '.paths | keys[]' | rg '/api/v1/workflows|/api/v1/runs'
```

```bash
curl -sS "${RUMINATE_BASE_URL:?Set a real Ruminate base URL first}/api-doc/openapi.json" | jq '.paths["/api/v1/workflows"]'
```

## Core endpoints
- `POST /api/v1/workflows/validate`
- `POST /api/v1/workflows`
- `GET /api/v1/workflows`
- `GET /api/v1/workflows/{workflow_id}`
- `PUT /api/v1/workflows/{workflow_id}`
- `GET /api/v1/workflows/{workflow_id}/versions`
- `DELETE /api/v1/workflows/{workflow_id}/versions/{version}`
- `POST /api/v1/workflows/{workflow_id}/runs`
- `GET /api/v1/runs`
- `POST /api/v1/runs/{run_id}/rerun`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/events`

## Minimal call patterns
Validate:
```bash
curl -sS -X POST "${RUMINATE_BASE_URL:?Set a real Ruminate base URL first}/api/v1/workflows/validate" \
  -H 'content-type: application/json' \
  -d '{"name":"example","dag_text":"{\"nodes\":[],\"edges\":[]}"}'
```

Create:
```bash
curl -sS -X POST "${RUMINATE_BASE_URL:?Set a real Ruminate base URL first}/api/v1/workflows" \
  -H 'content-type: application/json' \
  -d '{"name":"example","dag_text":"{\"nodes\":[],\"edges\":[]}"}'
```

Update:
```bash
curl -sS -X PUT "${RUMINATE_BASE_URL:?Set a real Ruminate base URL first}/api/v1/workflows/<workflow_id>" \
  -H 'content-type: application/json' \
  -d '{"name":"example","dag_text":"{\"nodes\":[],\"edges\":[]}"}'
```

Trigger run:
```bash
curl -sS -X POST "${RUMINATE_BASE_URL:?Set a real Ruminate base URL first}/api/v1/workflows/<workflow_id>/runs" \
  -H 'content-type: application/json' \
  -d '{"input":{},"run_kind":"run","execution_policy":"fail_fast"}'
```
