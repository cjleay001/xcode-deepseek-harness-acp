#!/bin/bash
set -euo pipefail

APP_ROOT="${DSH_APP_ROOT:-/Applications/DeepSeek Harness.app/Contents}"
APP_ASAR="$APP_ROOT/Resources/app.asar"
DSH_CLI="$APP_ROOT/Resources/app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"
DSH_NODE="$APP_ROOT/MacOS/DeepSeek Harness"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ACP_PROXY="$SCRIPT_DIR/dsh_acp_proxy.py"
ACP_PYTHON="${DSH_ACP_PYTHON:-python3}"

if [[ ! -x "$DSH_NODE" || ! -f "$APP_ASAR" ]]; then
  printf 'DeepSeek Harness was not found at %s\n' "$APP_ROOT" >&2
  printf 'Set DSH_APP_ROOT to the app Contents directory if it is installed elsewhere.\n' >&2
  exit 1
fi

if [[ ! -r "$ACP_PROXY" ]]; then
  printf 'ACP proxy not found: %s\n' "$ACP_PROXY" >&2
  exit 1
fi
if ! command -v "$ACP_PYTHON" >/dev/null 2>&1; then
  printf 'Python 3 is required for the ACP proxy: %s\n' "$ACP_PYTHON" >&2
  exit 1
fi

export ELECTRON_RUN_AS_NODE=1
export DSH_HOME="${DSH_HOME:-$HOME/.dsh}"

exec "$ACP_PYTHON" "$ACP_PROXY" -- "$DSH_NODE" "$DSH_CLI" --profile acp "$@"
