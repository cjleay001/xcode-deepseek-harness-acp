#!/usr/bin/env python3
"""Ensure burst ACP responses cannot hide a result in a text buffer."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
result = subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "test_acp.py")],
    text=True,
    capture_output=True,
    timeout=20,
    check=False,
    env={
        **os.environ,
        "DSH_ACP_LAUNCHER": str(ROOT / "tests" / "fake_dsh_agent.py"),
        "DSH_ACP_WORKSPACE": str(ROOT),
        "DSH_ACP_TIMEOUT": "5",
        "DSH_XCODE_MCP": "0",
    },
)
assert result.returncode == 0, result.stdout + result.stderr
assert "Response: DSH_ACP_OK" in result.stdout
assert "ACP smoke test passed." in result.stdout
print("ACP burst-response regression test: OK")
