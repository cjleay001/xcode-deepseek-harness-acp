#!/usr/bin/env python3
"""List, inspect, and call any tool exposed by `xcrun mcpbridge`."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import shlex
import subprocess
import sys
import threading
import time
from typing import Any

DEFAULT_COMMAND = "/usr/bin/xcrun mcpbridge"


class McpStdioClient:
    """Small MCP JSON-RPC client with bounded reads and deterministic cleanup."""

    def __init__(self, command: list[str], startup_timeout: float) -> None:
        self.startup_timeout = startup_timeout
        self.next_id = 0
        self.pending = bytearray()
        self.stderr_lines: list[str] = []
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
            if message.get("id") == request_id and ("result" in message or "error" in message):
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
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
        self.selector.close()
        self.stderr_thread.join(timeout=1)


def parse_command(value: str) -> list[str]:
    command = shlex.split(value)
    if not command:
        raise ValueError("MCP command cannot be empty")
    return command


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


SENSITIVE_SESSION_KEYS = {"interactionSessionKey", "interactSessionKey"}


def redact_text(text: str) -> str:
    """Redact session secrets in nested or escaped JSON text."""
    text = re.sub(
        r'(?i)("(?:interactionSessionKey|interactSessionKey)"\s*:\s*")[^"]*(")',
        r'\1[redacted]\2',
        text,
    )
    return re.sub(
        r'(?i)(\\"(?:interactionSessionKey|interactSessionKey)\\"\s*:\s*\\")[^"]*(\\")',
        r'\1[redacted]\2',
        text,
    )


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key in SENSITIVE_SESSION_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def result_text(result: dict[str, Any]) -> str:
    return "\n".join(item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")


def require_success(result: dict[str, Any], action: str) -> dict[str, Any]:
    if result.get("isError"):
        raise RuntimeError(f"{action} failed: {redact_text(result_text(result))}")
    return result


def structured(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("structuredContent")
    if isinstance(value, dict):
        return value
    text = result_text(result)
    try:
        decoded = json.loads(text)
        return decoded if isinstance(decoded, dict) else {}
    except json.JSONDecodeError:
        return {}


def resolve_workspace(client: McpStdioClient, value: str, timeout: float) -> str:
    """Resolve an absolute project path to the identifier required by headless tools."""
    if not value.startswith("/"):
        return value
    result = require_success(
        client.request("tools/call", {"name": "XcodeOpenWorkspace", "arguments": {"path": value}}, timeout),
        "XcodeOpenWorkspace",
    )
    identifier = structured(result).get("workspaceIdentifier")
    if not identifier:
        raise RuntimeError("XcodeOpenWorkspace returned no workspaceIdentifier")
    return identifier


def device_state(client: McpStdioClient, options: argparse.Namespace) -> dict[str, Any]:
    session_key: str | None = None
    session_identifier = f"DSH Device State {time.time_ns()}"
    if options.workspace:
        start_arguments: dict[str, Any] = {
            "sessionIdentifier": session_identifier,
            "workspaceIdentifier": options.workspace,
        }
        start_name = "DeviceInteractionStartWorkspaceSession"
    else:
        if not options.device:
            raise ValueError("--device is required when --workspace is omitted")
        start_arguments = {"sessionIdentifier": session_identifier, "deviceIdentifier": options.device}
        start_name = "DeviceInteractionStartSession"
    if options.device:
        start_arguments["deviceIdentifier"] = options.device
    built = False
    installed_and_running = False
    if options.run:
        if not options.workspace:
            raise ValueError("--run requires --workspace")
        require_success(
            client.request(
                "tools/call",
                {"name": "BuildProject", "arguments": {"workspaceIdentifier": options.workspace}},
                options.timeout,
            ),
            "BuildProject",
        )
        built = True
    try:
        started = structured(require_success(client.request("tools/call", {"name": start_name, "arguments": start_arguments}, options.timeout), start_name))
        session_key = started.get("interactionSessionKey")
        if not session_key:
            raise RuntimeError(f"{start_name} returned no interactionSessionKey")
        if options.run:
            require_success(
                client.request(
                    "tools/call",
                    {"name": "DeviceInteractionInstallAndRun", "arguments": {"interactionSessionKey": session_key, "workspaceIdentifier": options.workspace}},
                    options.timeout,
                ),
                "DeviceInteractionInstallAndRun",
            )
            installed_and_running = True
        interaction: dict[str, Any] = {"interactSessionKey": session_key}
        if options.bundle_id:
            interaction["activationBundleId"] = options.bundle_id
        if options.interaction_command:
            interaction["interactionCommand"] = options.interaction_command
        captured = require_success(
            client.request("tools/call", {"name": "DeviceInteractionSynthesize", "arguments": interaction}, options.timeout),
            "DeviceInteractionSynthesize",
        )
        return {
            "device": {
                "uuid": started.get("deviceUUID"),
                "isSimulator": started.get("deviceIsSimulator"),
            },
            "built": built,
            "installedAndRunning": installed_and_running,
            "capture": structured(captured) or captured,
        }
    finally:
        if session_key:
            ended = client.request(
                "tools/call",
                {"name": "DeviceInteractionEndSession", "arguments": {"interactionSessionKey": session_key}},
                min(options.timeout, 60),
            )
            require_success(ended, "DeviceInteractionEndSession")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", default=os.environ.get("XCODE_MCP_COMMAND", DEFAULT_COMMAND), help="MCP server command (shell-style quoting, never a shell pipeline)")
    parser.add_argument("--startup-timeout", type=float, default=20, help="Initialization and tool discovery timeout in seconds")
    subparsers = parser.add_subparsers(dest="action", required=True)
    list_parser = subparsers.add_parser("list", help="List every available Xcode tool")
    list_parser.add_argument("--json", action="store_true", help="Print full tool definitions as JSON")
    schema_parser = subparsers.add_parser("schema", help="Print one tool's complete schema")
    schema_parser.add_argument("name", help="Tool name, for example BuildProject")
    call_parser = subparsers.add_parser("call", help="Call any tool by name")
    call_parser.add_argument("name", help="Tool name, for example XcodeListWorkspaces")
    call_parser.add_argument("--args", default="{}", help="JSON object containing tool arguments")
    call_parser.add_argument("--workspace", help="Workspace identifier or absolute project path, injected only when supported")
    call_parser.add_argument("--timeout", type=float, default=300, help="Tool call timeout in seconds")
    device_parser = subparsers.add_parser("device-state", help="Capture device UI, screenshot, hierarchy and logs, then close the session")
    device_parser.add_argument("--device", help="Device UDID, ECID, name, OS version or type; required without --workspace")
    device_parser.add_argument("--workspace", help="Workspace identifier or absolute project path for workspace-bound interaction")
    device_parser.add_argument("--bundle-id", help="Optional application bundle identifier to activate")
    device_parser.add_argument("--run", action="store_true", help="Build and install/run the app before capture; requires --workspace")
    device_parser.add_argument("--interaction-command", help="Optional synthesized command such as 't 100 200'; omit to only capture state")
    device_parser.add_argument("--timeout", type=float, default=300, help="Each device tool call timeout in seconds")
    options = parser.parse_args()

    client: McpStdioClient | None = None
    try:
        client = McpStdioClient(parse_command(options.command), options.startup_timeout)
        client.initialize()
        tools = client.list_tools()
        if options.action == "device-state":
            if options.workspace:
                options.workspace = resolve_workspace(client, options.workspace, options.timeout)
            print_json(redact(device_state(client, options)))
            return 0
        if options.action == "list":
            if options.json:
                print_json(tools)
            else:
                for tool in tools:
                    print(tool["name"])
            return 0
        matches = [tool for tool in tools if tool.get("name") == options.name]
        if not matches:
            available = ", ".join(sorted(tool.get("name", "") for tool in tools))
            raise ValueError(f"Unknown tool {options.name!r}. Available tools: {available}")
        if options.action == "schema":
            print_json(matches[0])
            return 0
        arguments = json.loads(options.args)
        if not isinstance(arguments, dict):
            raise ValueError("--args must be a JSON object")
        schema_properties = matches[0].get("inputSchema", {}).get("properties", {})
        if options.workspace and "workspaceIdentifier" in schema_properties:
            arguments.setdefault("workspaceIdentifier", resolve_workspace(client, options.workspace, options.timeout))
        result = client.request("tools/call", {"name": options.name, "arguments": arguments}, options.timeout)
        print_json(redact(result))
        return 2 if result.get("isError") else 0
    except Exception as exc:
        print(redact_text(f"Xcode MCP error: {type(exc).__name__}: {exc}"), file=sys.stderr)
        if client and client.stderr_lines:
            print(redact_text("MCP stderr (last 10 lines):\n" + "\n".join(client.stderr_lines[-10:])), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
