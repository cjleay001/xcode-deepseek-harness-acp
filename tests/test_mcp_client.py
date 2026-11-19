#!/usr/bin/env python3
"""Regression tests for the generic Xcode MCP command-line client."""

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts" / "xcode_mcp.py"
COMMAND = f"{sys.executable} {ROOT / 'tests' / 'fake_mcp_server.py'}"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), "--command", COMMAND, *args],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
        env=os.environ.copy(),
    )


listed = run("list")
assert listed.returncode == 0, listed.stderr
assert listed.stdout.splitlines() == ["Echo", "Fail", "DeviceInteractionStartSession", "DeviceInteractionSynthesize", "DeviceInteractionEndSession", "XcodeOpenWorkspace", "BuildProject", "DeviceInteractionStartWorkspaceSession", "DeviceInteractionInstallAndRun"]

schema = run("schema", "Echo")
assert schema.returncode == 0, schema.stderr
assert json.loads(schema.stdout)["inputSchema"]["properties"]["text"]["type"] == "string"

called = run("call", "Echo", "--args", '{"text":"bridge-ok"}', "--workspace", "/tmp/App.xcodeproj")
assert called.returncode == 0, called.stderr
assert json.loads(called.stdout)["content"][0]["text"] == "bridge-ok:workspace-fake"

failed = run("call", "Fail")
assert failed.returncode == 2, failed.stdout + failed.stderr
assert json.loads(failed.stdout)["isError"] is True

started = run("call", "DeviceInteractionStartSession", "--args", '{"deviceIdentifier":"fake-device","sessionIdentifier":"Secret Test"}')
assert started.returncode == 0, started.stderr
assert "secret-session" not in started.stdout
assert "[redacted]" in started.stdout

state = run("device-state", "--device", "fake-device", "--bundle-id", "com.example.app")
assert state.returncode == 0, state.stderr
assert "secret-session" not in state.stdout
capture = json.loads(state.stdout)
assert capture["device"]["isSimulator"] is True
assert capture["capture"]["applicationState"] == "Running"
assert capture["built"] is False and capture["installedAndRunning"] is False

running = run("device-state", "--workspace", "/tmp/App.xcodeproj", "--run")
assert running.returncode == 0, running.stderr
running_capture = json.loads(running.stdout)
assert running_capture["built"] is True and running_capture["installedAndRunning"] is True
assert "secret-session" not in running.stdout

failed_secret = run("device-state", "--device", "fake-device", "--interaction-command", "fail")
assert failed_secret.returncode == 1
assert "secret-session" not in failed_secret.stderr
assert "[redacted]" in failed_secret.stderr
print("Generic MCP tools, device workflow and redaction tests: OK")
