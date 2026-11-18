#!/bin/bash
set -euo pipefail

APP_ROOT="${DSH_APP_ROOT:-/Applications/DeepSeek Harness.app/Contents}"
APP_ASAR="$APP_ROOT/Resources/app.asar"
DSH_CLI="$APP_ROOT/Resources/app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"
DSH_NODE="$APP_ROOT/MacOS/DeepSeek Harness"

if [[ ! -x "$DSH_NODE" || ! -f "$APP_ASAR" ]]; then
  printf 'DeepSeek Harness was not found at %s\n' "$APP_ROOT" >&2
  printf 'Set DSH_APP_ROOT to the app Contents directory if it is installed elsewhere.\n' >&2
  exit 1
fi

export ELECTRON_RUN_AS_NODE=1
export DSH_HOME="${DSH_HOME:-$HOME/.dsh}"

exec "$DSH_NODE" "$DSH_CLI" --profile acp "$@"
