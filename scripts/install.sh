#!/bin/bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_LAUNCHER="$ROOT/bin/dsh-acp-launcher.sh"
SOURCE_PROXY="$ROOT/bin/dsh_acp_proxy.py"
APP_ROOT="${DSH_APP_ROOT:-/Applications/DeepSeek Harness.app/Contents}"
BIN_DIR="$HOME/Library/Developer/Xcode/CodingAssistant/Bin"
ACP_DIR="$HOME/Library/Developer/Xcode/CodingAssistant/ACP"
INSTALLED_LAUNCHER="$BIN_DIR/dsh-acp-launcher.sh"
INSTALLED_PROXY="$BIN_DIR/dsh_acp_proxy.py"
AGENT_PLIST="$ACP_DIR/D5EAC000-0000-4000-8000-000000000001.plist"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'This installer supports macOS only.\n' >&2
  exit 1
fi

if [[ ! -x "$APP_ROOT/MacOS/DeepSeek Harness" || ! -f "$APP_ROOT/Resources/app.asar" ]]; then
  printf 'DeepSeek Harness was not found at %s\n' "$APP_ROOT" >&2
  printf 'Set DSH_APP_ROOT to the app Contents directory and retry.\n' >&2
  exit 1
fi

for command_name in python3 plutil; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command_name" >&2
    exit 1
  fi
done
PYTHON_BIN="$(command -v python3)"

printf 'Initializing the DSH ACP profile...\n'
"$SOURCE_LAUNCHER" --help >/dev/null

mkdir -p "$BIN_DIR" "$ACP_DIR"

python3 - "$SOURCE_LAUNCHER" "$SOURCE_PROXY" "$INSTALLED_LAUNCHER" "$INSTALLED_PROXY" "$AGENT_PLIST" "$APP_ROOT" "$PYTHON_BIN" <<'PY'
import os
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile
import time

source_launcher = Path(sys.argv[1])
source_proxy = Path(sys.argv[2])
installed_launcher = Path(sys.argv[3])
installed_proxy = Path(sys.argv[4])
plist_path = Path(sys.argv[5])
app_root = sys.argv[6]
python_bin = sys.argv[7]


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Refusing to replace symbolic link: {path}")
    if path.exists() and path.read_bytes() == data:
        path.chmod(mode)
        return
    if path.exists():
        stamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
        backup = path.with_name(f"{path.name}.backup.{stamp}.{os.getpid()}")
        shutil.copy2(path, backup)
        print(f"Backed up existing file to {backup}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


atomic_write(installed_launcher, source_launcher.read_bytes(), 0o755)
atomic_write(installed_proxy, source_proxy.read_bytes(), 0o755)
payload = {
    "agent": "/bin/bash",
    "arguments": [str(installed_launcher)],
    "environment": {
        "DSH_APP_ROOT": app_root,
        "DSH_ACP_PYTHON": python_bin,
        "DSH_XCODE_MCP": "auto",
    },
    "name": "DeepSeek Harness",
}
atomic_write(plist_path, plistlib.dumps(payload, sort_keys=False), 0o644)
PY

plutil -lint "$AGENT_PLIST" >/dev/null

printf '\nInstalled DeepSeek Harness as an Xcode ACP Agent.\n'
printf '1. Restart Xcode.\n'
printf '2. Open Settings > Intelligence and select DeepSeek Harness.\n'
printf '3. Run: python3 %s/scripts/test_acp.py\n' "$ROOT"
printf 'For native simulator runs, enable Xcode MCP and approve only this agent and your workspace when prompted.\n'
printf 'If the model has no credentials, configure the ACP provider/model as described in README.md.\n'
