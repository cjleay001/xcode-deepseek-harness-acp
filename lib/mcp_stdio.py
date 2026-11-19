"""Small MCP JSON-RPC stdio client with bounded reads and deterministic cleanup."""

from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import threading
import time
from typing import Any

SENSITIVE_SESSION_KEYS = {"interactionSessionKey", "interactSessionKey"}
SUPPORTED_PROTOCOL_VERSIONS = {"2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}


def collect_session_secrets(value: Any) -> set[str]:
    secrets: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in SENSITIVE_SESSION_KEYS and isinstance(item, str) and item:
                secrets.add(item)
            else:
                secrets.update(collect_session_secrets(item))
    elif isinstance(value, list):
        for item in value:
            secrets.update(collect_session_secrets(item))
    return secrets


def redact_text(text: str, secrets: set[str] | tuple[str, ...] = ()) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[redacted]")
    patterns = [
        r'(?i)("(?:interactionSessionKey|interactSessionKey)"\s*:\s*")[^"]*(")',
        r'(?i)(\\"(?:interactionSessionKey|interactSessionKey)\\"\s*:\s*\\")[^"]*(\\")',
        r"(?i)('(?:interactionSessionKey|interactSessionKey)'\s*:\s*')[^']*(')",
    ]
    for pattern in patterns:
        text = re.sub(pattern, r'\1[redacted]\2', text)
    return text


def redact(value: Any, secrets: set[str] | tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key in SENSITIVE_SESSION_KEYS else redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


class McpStdioClient:
    def __init__(self, command: list[str], startup_timeout: float) -> None:
        self.startup_timeout = startup_timeout
        self.next_id = 0
        self.pending = bytearray()
        self.stderr_lines: list[str] = []
        self.session_secrets: set[str] = set()
        self.notifications: list[dict[str, Any]] = []
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=os.environ.copy(),
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.stderr_thread = threading.Thread(target=self._collect_stderr, daemon=True)
        self.stderr_thread.start()

    def _collect_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr_lines.append(line.decode("utf-8", "replace").rstrip())

    def _send(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        self.proc.stdin.write(payload.encode("utf-8"))
        self.proc.stdin.flush()

    def _next_message(self, deadline: float) -> dict[str, Any]:
        while True:
            newline = self.pending.find(b"\n")
            if newline >= 0:
                line = bytes(self.pending[: newline + 1])
                del self.pending[: newline + 1]
                return json.loads(line)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("Timed out waiting for the MCP response")
            chunk = os.read(self.proc.stdout.fileno(), 65_536)
            if not chunk:
                detail = "\n".join(self.stderr_lines[-10:])
                raise RuntimeError(f"MCP server exited before responding{': ' + detail if detail else ''}")
            self.pending.extend(chunk)

    def request(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            message = self._next_message(deadline)
            if "method" in message:
                self.notifications.append(message)
            if message.get("id") == request_id and ("result" in message or "error" in message):
                if "error" in message:
                    self.session_secrets.update(collect_session_secrets(message["error"]))
                    raise RuntimeError(f"{method} failed: {redact(message['error'], self.session_secrets)}")
                self.session_secrets.update(collect_session_secrets(message["result"]))
                return message["result"]
            if "method" in message and "id" in message:
                self._send({
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": -32601, "message": f"Client does not implement {message['method']}"},
                })

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict[str, Any]:
        result = self.request("initialize", {
            "protocolVersion": "2026-07-28",
            "capabilities": {},
            "clientInfo": {"name": "xcode-dsh-mcp-cli", "version": "1.0.0"},
        }, self.startup_timeout)
        protocol_version = result.get("protocolVersion")
        if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise RuntimeError(f"Unsupported MCP protocol version: {protocol_version!r}")
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self.request("tools/list", params, self.startup_timeout)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.selector.close()
        self.stderr_thread.join(timeout=1)
