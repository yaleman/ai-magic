---
name: workflow-creator
description: Create or update Ruminate workflows through the API. Use when a user asks to build, edit, validate, version, trigger, rerun, or inspect a workflow and you should drive `/api/v1/workflows*` and `/api/v1/runs*` endpoints from the OpenAPI spec at `https://m1.housenet.yaleman.org:9000/api-doc/openapi.json`.
---

# Workflow Creator

## Overview
Use the Ruminate API to create, validate, update, version, and execute workflows. Start from the live OpenAPI spec, then call only the endpoints needed for the request.

Read [references/workflow-api.md](references/workflow-api.md) before issuing workflow requests.

## Workflow
1. Fetch and inspect the live API spec from `https://m1.housenet.yaleman.org:9000/api-doc/openapi.json`.
2. Confirm authentication context (session cookie or bearer token) before calling protected endpoints.
3. Validate or normalize incoming DAG JSONC when a user provides workflow content.
4. Create or update the workflow with the minimum required payload.
5. Return key IDs and links (`workflow_id`, `version`, run IDs) and suggest next actions only when relevant.

## Execution Rules
- Use `POST /api/v1/workflows/validate` before persisting workflows when DAG content is new or changed.
- Use `POST /api/v1/workflows` for creation and `PUT /api/v1/workflows/{workflow_id}` for edits.
- Preserve user intent; do not invent extra nodes, edges, or modules beyond what is requested.
- Use exact endpoint field names from the OpenAPI document.
- When creating runs, use `POST /api/v1/workflows/{workflow_id}/runs` and then inspect status with run endpoints.
- Surface API errors directly with actionable fixes.

## Output Contract
- Report the exact API calls made.
- Report identifiers returned by the API.
- For mutations, report the final workflow version number.
- For run operations, report run status and any failure message.
