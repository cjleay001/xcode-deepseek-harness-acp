#!/usr/bin/env python3
"""Regression tests for ACP stdio forwarding and Xcode MCP injection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PROXY = ROOT / "bin" / "dsh_acp_proxy.py"
FAKE_SERVER = ROOT / "tests" / "fake_acp_server.py"


def run_frames(frames: list[dict], mode: str) -> list[dict]:
    payload = "".join(json.dumps(frame) + "\n" for frame in frames)
    result = subprocess.run(
        [sys.executable, str(PROXY), "--", sys.executable, str(FAKE_SERVER)],
        input=payload,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
        env={**os.environ, "DSH_XCODE_MCP": mode},
    )
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines()]


def session(request_id: int, method: str = "session/new", servers: list | None = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {"cwd": str(ROOT), "mcpServers": servers or []},
    }


def main() -> None:
    responses = run_frames([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        session(2),
        session(3, servers=[{"name": "xcode", "command": "/custom/xcode", "args": [], "env": []}]),
        session(4, method="session/resume"),
    ], "1")
    assert responses[0]["result"]["agentInfo"]["name"] == "fake"
    injected = responses[1]["result"]["mcpServers"]
    assert len(injected) == 1 and injected[0]["command"] == "/usr/bin/xcrun"
    assert injected[0]["args"] == ["mcpbridge"] and injected[0]["env"] == []
    existing = responses[2]["result"]["mcpServers"]
    assert len(existing) == 1 and existing[0]["command"] == "/custom/xcode"
    resumed = responses[3]["result"]["mcpServers"]
    assert len(resumed) == 1 and resumed[0]["name"] == "xcode"

    disabled = run_frames([session(1)], "0")
    assert disabled[0]["result"]["mcpServers"] == []
    print("Proxy injection, deduplication, resume, passthrough, and opt-out tests: OK")


if __name__ == "__main__":
    main()
