#!/usr/bin/env python3
"""Regression tests for ACP stdio forwarding and Xcode MCP injection."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

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


def early_server_exit() -> None:
    process = subprocess.Popen(
        [sys.executable, str(PROXY), "--", sys.executable, "-c", "print('help')"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "DSH_XCODE_MCP": "0"},
    )
    return_code = process.wait(timeout=10)
    stdout = process.stdout.read()
    stderr = process.stderr.read()
    process.stdin.close()
    assert return_code == 0, stderr
    assert stdout == "help\n"


def malformed_status_is_fail_closed() -> None:
    spec = importlib.util.spec_from_file_location("dsh_acp_proxy", PROXY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with mock.patch.dict(os.environ, {"DSH_XCODE_MCP": "auto"}):
        for payload in ("[]", "null", '{"permission":[]}'):
            completed = SimpleNamespace(returncode=0, stdout=payload)
            with mock.patch.object(module.subprocess, "run", return_value=completed):
                assert module.xcode_mcp_enabled() is False


def main() -> None:
    resume_without_servers = session(5, method="session/resume")
    del resume_without_servers["params"]["mcpServers"]
    responses = run_frames([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        session(2),
        session(3, servers=[{"name": "xcode", "command": "/custom/xcode", "args": [], "env": []}]),
        session(4, method="session/resume"),
        resume_without_servers,
    ], "1")
    assert responses[0]["result"]["agentInfo"]["name"] == "fake"
    injected = responses[1]["result"]["mcpServers"]
    assert len(injected) == 1 and injected[0]["command"] == "/usr/bin/xcrun"
    assert injected[0]["args"] == ["mcpbridge"] and injected[0]["env"] == []
    existing = responses[2]["result"]["mcpServers"]
    assert len(existing) == 1 and existing[0]["command"] == "/custom/xcode"
    resumed = responses[3]["result"]["mcpServers"]
    assert len(resumed) == 1 and resumed[0]["name"] == "xcode"
    resumed_without = responses[4]["result"]["mcpServers"]
    assert len(resumed_without) == 1 and resumed_without[0]["name"] == "xcode"

    disabled = run_frames([session(1)], "0")
    assert disabled[0]["result"]["mcpServers"] == []
    early_server_exit()
    malformed_status_is_fail_closed()
    print("Proxy injection, resume, passthrough, opt-out, early-exit and status tests: OK")


if __name__ == "__main__":
    main()
