---
name: "micropython-device"
description: "Use when interacting with or troubleshooting MicroPython devices over serial using mpfshell and esptool. Always run tools through uvx."
---

# MicroPython Device Skill (uvx-first)

Use this skill for day-to-day interaction, deploys, and troubleshooting of MicroPython devices over serial.

## Rules

- Use `uvx` for all invocations. Do not ask users to install `mpfshell` or `esptool` globally.
- Prefer non-interactive commands first for scripted diagnostics.
- Keep device checks concrete: file presence, Wi-Fi state, RTC sync, then reset/retest.

## Prerequisites

```bash
command -v uvx >/dev/null 2>&1
```

If missing, stop and ask the user to install `uv` first.

## Port discovery

```bash
ls -la /dev/cu.*
tio -l
```

For examples below:

- `PORT_MPF="tty.usbserial-0154E20F"` for `mpfshell`
- `PORT_DEV="/dev/cu.usbserial-0154E20F"` for `esptool`

## Command wrappers (copy/paste friendly)

```bash
MPF='uvx --python 3.9 mpfshell --nocache'
ESP='uvx --from esptool esptool'
```

Skill-local wrapper scripts are also available:

```bash
$CODEX_HOME/skills/micropython-device/scripts/mpf.sh --help
$CODEX_HOME/skills/micropython-device/scripts/esp.sh --help
```

## Core workflows

### 1) Verify device responds

```bash
$MPF -n -o "$PORT_MPF" -c 'ls; exit'
$ESP --port "$PORT_DEV" --baud 115200 chip-id
```

### 2) Upload app files

```bash
$MPF -n -o "$PORT_MPF" -c 'put boot.py; put main.py; put config.py; exit'
$MPF --reset -n -o "$PORT_MPF"
```

### 3) Run targeted REPL diagnostics

```bash
$MPF -n -o "$PORT_MPF" -c 'exec import network; exec w=network.WLAN(network.STA_IF); exec print("active=",w.active()); exec print("connected=",w.isconnected()); exec print("ifconfig=",w.ifconfig()); exit'

$MPF -n -o "$PORT_MPF" -c 'exec import machine; exec rtc=machine.RTC(); exec print("rtc_synced=",rtc.synced()); exit'

$MPF -n -o "$PORT_MPF" -c 'exec import machine,utime; exec rtc=machine.RTC(); exec rtc.ntp_sync(server="10.0.0.1", tz="GMT+0"); exec utime.sleep(3); exec print("synced_after_3s=",rtc.synced()); exit'
```

Important:

- In `mpfshell -c`, semicolons split shell commands.
- For Python snippets, use multiple `exec ...` commands (one statement per `exec`).

### 4) Capture startup behavior interactively

```bash
$MPF --reset -o "$PORT_MPF"
```

Inside `mpfshell`:

1. Run `repl`
2. At `>>>`, run `import main`
3. Observe serial status/errors from startup flow

## Troubleshooting playbook

### Symptom: “Hung on connecting Wi-Fi”

1. Check live network state from REPL:
```bash
$MPF -n -o "$PORT_MPF" -c 'exec import network; exec w=network.WLAN(network.STA_IF); exec print(w.isconnected()); exec print(w.ifconfig()); exit'
```
2. If `isconnected()` is true, check NTP sync state:
```bash
$MPF -n -o "$PORT_MPF" -c 'exec import machine; exec print(machine.RTC().synced()); exit'
```
3. If Wi-Fi is up but RTC sync is false, troubleshoot NTP host/reachability.

### Symptom: reset/upload appears to work but behavior unchanged

1. List remote files and verify timestamps/content.
2. Re-upload `main.py`, `boot.py`, `config.py`.
3. Hard reset with:
```bash
$MPF --reset -n -o "$PORT_MPF"
```

### Symptom: serial tool attaches but no useful output

1. Use non-interactive probes (`ls`, `exec print(...)`) to confirm REPL access.
2. Enter interactive `repl` and run `import main` manually.
3. If needed, use `esptool` chip checks:
```bash
$ESP --port "$PORT_DEV" --baud 115200 flash-id
$ESP --port "$PORT_DEV" --baud 115200 read-mac
```

## Guardrails

- Prefer reading state before flashing/erasing.
- Do not run `erase-flash` unless explicitly requested.
- Keep retry loops visible in device output and verify stage (Wi-Fi vs NTP) before changing code.
