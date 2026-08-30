---
name: cloudflare-cache-purge
description: Use when asked to clear, flush, purge, invalidate, or refresh the Cloudflare cache for a domain, hostname, subdomain, or zone name.
---

# Cloudflare Cache Purge

## Overview
Purge cached Cloudflare content for one hostname using `CLOUDFLARE_API_TOKEN` from the shell environment.

## When To Use
- The user asks to clear, flush, purge, invalidate, or refresh Cloudflare cache.
- The request names a domain or subdomain, such as `example.com` or `www.example.com`.

Do not use for selective URL, tag, prefix, or file purges unless the user explicitly asks for that behavior and you update the request accordingly.

## Command
Run the skill-local helper:

```bash
$CODEX_HOME/skills/cloudflare-cache-purge/scripts/cloudflare_purge_cache.py www.example.com
```

The helper:
- Requires `CLOUDFLARE_API_TOKEN`.
- Looks up the active Cloudflare zone for the supplied hostname, trying the hostname first and then parent domains.
- Sends `{"hosts": ["www.example.com"]}` to Cloudflare's zone purge endpoint.
- Prints the purged hostname, zone name, and zone id on success.

## Rules
- If the user gives an exact domain/zone name, run the command without asking for confirmation.
- If the domain is missing, ask for it.
- If the helper says no zone was found for the hostname or parent domains, ask for the Cloudflare zone name.
- Do not print or log `CLOUDFLARE_API_TOKEN`.
- Report Cloudflare API errors exactly enough for the user to fix permissions or zone naming.

## Verification
For helper changes, run:

```bash
python3 $CODEX_HOME/skills/cloudflare-cache-purge/tests/test_cloudflare_purge_cache.py
```
