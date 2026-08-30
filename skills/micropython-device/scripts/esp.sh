#!/usr/bin/env bash
set -euo pipefail

uvx --from esptool esptool "$@"
