#!/usr/bin/env python3
"""Forward ACP stdio and optionally inject Xcode MCP into new/resumed sessions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

XCODE_MCP_SERVER = {
    "name": "xcode",
    "command": "/usr/bin/xcrun",
    "args": ["mcpbridge"],
    "env": [],
}
SESSION_METHODS = {"session/new", "session/resume"}


def xcode_mcp_enabled() -> bool:
    """Resolve auto/1/0 without enabling or changing Xcode permissions."""
    mode = os.environ.get("DSH_XCODE_MCP", "auto").strip().lower()
    if mode in {"0", "false", "no", "off"}:
        return False
    if mode in {"1", "true", "yes", "on"}:
        return True
    try:
        result = subprocess.run(
            ["/usr/bin/xcrun", "mcp-server", "status", "--format", "json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return False
        status = json.loads(result.stdout)
        return status.get("permission", {}).get("enabled") is True
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def inject_if_needed(line: bytes, enabled: bool) -> bytes:
    """Preserve unrelated frames and add Xcode only when no xcode entry exists."""
    if not enabled:
        return line
    try:
        message = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return line
    if not isinstance(message, dict) or message.get("method") not in SESSION_METHODS:
        return line
    params = message.get("params")
    if not isinstance(params, dict):
        return line
    servers = params.get("mcpServers")
    if not isinstance(servers, list):
        return line
    if any(isinstance(server, dict) and server.get("name") == "xcode" for server in servers):
        return line
    message["params"] = {**params, "mcpServers": [*servers, XCODE_MCP_SERVER]}
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def forward_client_to_server(enabled: bool) -> None:
    global proc
    try:
        for line in sys.stdin.buffer:
            proc.stdin.write(inject_if_needed(line, enabled))
            proc.stdin.flush()
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass


def forward_server_to_client() -> None:
    global proc
    try:
        for line in proc.stdout:
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
    except (BrokenPipeError, OSError):
        pass


def main() -> int:
    global proc
    if "--" not in sys.argv:
        print("Usage: dsh_acp_proxy.py -- <agent-command> [args...]", file=sys.stderr)
        return 2
    separator = sys.argv.index("--")
    command = sys.argv[separator + 1 :]
    if not command:
        print("Missing agent command after --", file=sys.stderr)
        return 2

    enabled = xcode_mcp_enabled()
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            bufsize=0,
            env=os.environ.copy(),
        )
    except OSError as exc:
        print(f"Unable to start ACP agent: {exc}", file=sys.stderr)
        return 1

    client_thread = threading.Thread(target=forward_client_to_server, args=(enabled,), daemon=True)
    server_thread = threading.Thread(target=forward_server_to_client, daemon=True)
    client_thread.start()
    server_thread.start()
    try:
        return_code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        server_thread.join(timeout=5)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
