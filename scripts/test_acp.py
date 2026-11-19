#!/usr/bin/env python3
"""Run a minimal ACP handshake and prompt using only the Python standard library."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
INSTALLED_LAUNCHER = Path.home() / "Library/Developer/Xcode/CodingAssistant/Bin/dsh-acp-launcher.sh"
DEFAULT_LAUNCHER = INSTALLED_LAUNCHER if INSTALLED_LAUNCHER.is_file() else ROOT / "bin/dsh-acp-launcher.sh"
LAUNCHER = Path(os.environ.get("DSH_ACP_LAUNCHER", str(DEFAULT_LAUNCHER))).resolve()
WORKSPACE = Path(os.environ.get("DSH_ACP_WORKSPACE", str(Path.cwd()))).resolve()
PROMPT = os.environ.get("DSH_ACP_PROMPT", "Reply with exactly DSH_ACP_OK and nothing else.")
TIMEOUT = float(os.environ.get("DSH_ACP_TIMEOUT", "180"))

if not LAUNCHER.is_file():
    raise SystemExit(f"ACP launcher not found: {LAUNCHER}")
if not WORKSPACE.is_dir():
    raise SystemExit(f"Workspace not found: {WORKSPACE}")

proc = subprocess.Popen(
    [str(LAUNCHER)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    bufsize=0,
    env={**os.environ, "DSH_XCODE_MCP": os.environ.get("DSH_XCODE_MCP", "0")},
)
assert proc.stdin and proc.stdout and proc.stderr
stderr_lines: list[str] = []
received_text: list[str] = []
selector = selectors.DefaultSelector()
selector.register(proc.stdout, selectors.EVENT_READ)
next_id = 0
pending_stdout = bytearray()


def collect_stderr() -> None:
    for line in proc.stderr:
        stderr_lines.append(line.decode("utf-8", "replace").rstrip())


threading.Thread(target=collect_stderr, daemon=True).start()


def send(message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    proc.stdin.write(payload.encode("utf-8"))
    proc.stdin.flush()


def handle_notification(message: dict) -> None:
    if message.get("method") != "session/update":
        return
    update = message.get("params", {}).get("update", {})
    if update.get("sessionUpdate") != "agent_message_chunk":
        return
    content = update.get("content", {})
    if content.get("type") == "text":
        text = content.get("text", "")
        received_text.append(text)
        print(text, end="", flush=True)


def handle_client_request(message: dict) -> None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "session/request_permission":
        options = message.get("params", {}).get("options", [])
        option = next((item for item in options if item.get("kind") == "reject_once"), None)
        if option:
            send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"outcome": {"outcome": "selected", "optionId": option["optionId"]}},
            })
            return
    send({
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Smoke test does not implement {method}"},
    })


def next_message(deadline: float) -> dict:
    """Read raw frames so buffered responses never become invisible to select."""
    global pending_stdout
    while True:
        newline = pending_stdout.find(b"\n")
        if newline >= 0:
            line = bytes(pending_stdout[: newline + 1])
            del pending_stdout[: newline + 1]
            return json.loads(line)
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not selector.select(remaining):
            raise TimeoutError("Timed out waiting for the ACP response")
        chunk = os.read(proc.stdout.fileno(), 65_536)
        if not chunk:
            raise RuntimeError("ACP process exited while waiting for a response")
        pending_stdout.extend(chunk)


def call(method: str, params: dict, timeout: float = 45) -> dict:
    global next_id
    next_id += 1
    request_id = next_id
    send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    deadline = time.monotonic() + timeout
    while True:
        message = next_message(deadline)
        if message.get("id") == request_id and ("result" in message or "error" in message):
            if "error" in message:
                raise RuntimeError(f"{method} failed: {message['error']}")
            return message["result"]
        if "method" in message and "id" in message:
            handle_client_request(message)
        else:
            handle_notification(message)


try:
    initialized = call("initialize", {
        "protocolVersion": 1,
        "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False},
            "terminal": False,
        },
        "clientInfo": {"name": "xcode-dsh-acp-smoke-test", "version": "1.0.0"},
    })
    agent_info = initialized.get("agentInfo", {})
    print(f"Handshake OK: {agent_info.get('name', 'unknown')} {agent_info.get('version', '')}")

    created = call("session/new", {"cwd": str(WORKSPACE), "mcpServers": []})
    session_id = created["sessionId"]
    for option in created.get("configOptions", []):
        if option.get("id") == "model":
            print(f"Model: {option.get('currentValue', 'unknown')}")

    print("Response: ", end="", flush=True)
    prompted = call("session/prompt", {
        "sessionId": session_id,
        "prompt": [{"type": "text", "text": PROMPT}],
    }, timeout=TIMEOUT)
    print()
    response_text = "".join(received_text)
    if prompted.get("stopReason") != "end_turn":
        raise RuntimeError(f"Unexpected stop reason: {prompted.get('stopReason')}")
    if "DSH_ACP_OK" not in response_text:
        raise RuntimeError("The expected DSH_ACP_OK response was not received")
    call("session/close", {"sessionId": session_id})
    print("ACP smoke test passed.")
except Exception as exc:
    print(f"\nACP smoke test failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    if stderr_lines:
        print("ACP stderr (last 20 lines):\n" + "\n".join(stderr_lines[-20:]), file=sys.stderr)
    sys.exit(1)
finally:
    try:
        proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    selector.close()
