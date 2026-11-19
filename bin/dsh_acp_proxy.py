#!/usr/bin/env python3
"""Forward ACP stdio and optionally inject Xcode MCP into new/resumed sessions."""

from __future__ import annotations

import json
import os
import select
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
        if not isinstance(status, dict):
            return False
        permission = status.get("permission")
        return isinstance(permission, dict) and permission.get("enabled") is True
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
    servers = params.get("mcpServers", [])
    if not isinstance(servers, list):
        return line
    if any(isinstance(server, dict) and server.get("name") == "xcode" for server in servers):
        return line
    message["params"] = {**params, "mcpServers": [*servers, XCODE_MCP_SERVER]}
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def forward_client_to_server(enabled: bool) -> None:
    """Use unbuffered reads so early server exit cannot strand a stdin lock."""
    global proc
    pending = bytearray()
    descriptor = sys.stdin.fileno()
    try:
        while proc.poll() is None:
            readable, _, _ = select.select([descriptor], [], [], 0.1)
            if not readable:
                continue
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            pending.extend(chunk)
            while True:
                newline = pending.find(b"\n")
                if newline < 0:
                    break
                line = bytes(pending[: newline + 1])
                del pending[: newline + 1]
                proc.stdin.write(inject_if_needed(line, enabled))
                proc.stdin.flush()
        if pending and proc.poll() is None:
            proc.stdin.write(inject_if_needed(bytes(pending), enabled))
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
        client_thread.join(timeout=2)
        server_thread.join(timeout=5)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
