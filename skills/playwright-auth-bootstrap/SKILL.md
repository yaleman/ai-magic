---
name: "playwright-auth-bootstrap"
description: "Use when you need to open a protected page in a real browser by seeding a local session and injecting the session cookie cleanly."
---

# Playwright Auth Bootstrap

Use this when a page is behind the app's session auth and you need to verify it in a browser.

## Workflow

1. Start or confirm the app is running with the repo's normal start task.
2. Resolve the app origin from `WEBSITES_FRONTEND_URL` or `.envrc`.
3. Seed a fresh session for the target user from the repository root.
4. Inject that session id into the active Playwright browser context for the app origin.
5. Navigate to the protected page and inspect it with `snapshot`.

## Resolve origin

Prefer the environment variable first:

```bash
app_url="${WEBSITES_FRONTEND_URL:-}"
```

If that is empty, source `.envrc` or read it directly:

```bash
set -a
[ -f .envrc ] && source .envrc
set +a
app_url="${WEBSITES_FRONTEND_URL}"
```

Use `app_url` as the browser origin. If you need only the hostname, derive it from `app_url` rather than hard-coding it.

## Session seed

From the repo root:

```bash
cargo run --bin session_seed -- --database-url 'sqlite://./database.sqlite?mode=rwc' --user-sub <subject>
```

If the user needs admin access, add `--set-admin`.

Keep the returned session id handy. It expires quickly.

## Browser injection

Use the Playwright browser session that is already open.

Inject the cookie on the app origin:

```js
await page.context().clearCookies();
await page.context().addCookies([
  {
    name: "id",
    value: "<session-id>",
    domain: "<hostname from app_url>",
    path: "/",
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
  },
]);
```

Then navigate to the protected page:

```js
await page.goto(`${app_url}/admin/...`);
```

If the browser still redirects to login, re-seed a new session and repeat immediately. Do not assume the old session is still valid.

## Troubleshooting

- Prefer a fresh session every time.
- Make sure the cookie is set for the hostname from `WEBSITES_FRONTEND_URL`, not the Kanidm host.
- If the page unexpectedly redirects, check whether the session expired while the server was rebuilding.
- Use a same-origin page like `/health` first if you need a stable place to inspect browser state.
