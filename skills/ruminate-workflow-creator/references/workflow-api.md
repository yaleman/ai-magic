# Workflow API Reference

## Source of truth
- OpenAPI JSON: `https://m1.housenet.yaleman.org:9000/api-doc/openapi.json`

## Quick inspection commands
```bash
curl -sS https://m1.housenet.yaleman.org:9000/api-doc/openapi.json | jq '.paths | keys[]' | rg '/api/v1/workflows|/api/v1/runs'
```

```bash
curl -sS https://m1.housenet.yaleman.org:9000/api-doc/openapi.json | jq '.paths["/api/v1/workflows"]'
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
curl -sS -X POST https://m1.housenet.yaleman.org:9000/api/v1/workflows/validate \
  -H 'content-type: application/json' \
  -d '{"name":"example","dag_text":"{\"nodes\":[],\"edges\":[]}"}'
```

Create:
```bash
curl -sS -X POST https://m1.housenet.yaleman.org:9000/api/v1/workflows \
  -H 'content-type: application/json' \
  -d '{"name":"example","dag_text":"{\"nodes\":[],\"edges\":[]}"}'
```

Update:
```bash
curl -sS -X PUT https://m1.housenet.yaleman.org:9000/api/v1/workflows/<workflow_id> \
  -H 'content-type: application/json' \
  -d '{"name":"example","dag_text":"{\"nodes\":[],\"edges\":[]}"}'
```

Trigger run:
```bash
curl -sS -X POST https://m1.housenet.yaleman.org:9000/api/v1/workflows/<workflow_id>/runs \
  -H 'content-type: application/json' \
  -d '{"input":{},"run_kind":"run","execution_policy":"fail_fast"}'
```
