#!/usr/bin/env python3
"""List, inspect, and call any tool exposed by `xcrun mcpbridge`."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import time
from typing import Any

DEFAULT_COMMAND = "/usr/bin/xcrun mcpbridge"


from pathlib import Path
import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.mcp_stdio import McpStdioClient


def parse_command(value: str) -> list[str]:
    command = shlex.split(value)
    if not command:
        raise ValueError("MCP command cannot be empty")
    return command


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


SENSITIVE_SESSION_KEYS = {"interactionSessionKey", "interactSessionKey"}


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
    """Redact named fields and previously observed session values in any text."""
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


def result_text(result: dict[str, Any]) -> str:
    return "\n".join(item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")


def require_success(result: dict[str, Any], action: str, secrets: set[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    if result.get("isError"):
        raise RuntimeError(f"{action} failed: {redact_text(result_text(result), secrets)}")
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
        client.session_secrets,
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
            client.session_secrets,
        )
        built = True
    try:
        started = structured(require_success(client.request("tools/call", {"name": start_name, "arguments": start_arguments}, options.timeout), start_name, client.session_secrets))
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
                client.session_secrets,
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
            client.session_secrets,
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
            require_success(ended, "DeviceInteractionEndSession", client.session_secrets)


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
            print_json(redact(device_state(client, options), client.session_secrets))
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
        print_json(redact(result, client.session_secrets))
        return 2 if result.get("isError") else 0
    except Exception as exc:
        secrets = client.session_secrets if client else set()
        print(redact_text(f"Xcode MCP error: {type(exc).__name__}: {exc}", secrets), file=sys.stderr)
        if client and client.stderr_lines:
            print(redact_text("MCP stderr (last 10 lines):\n" + "\n".join(client.stderr_lines[-10:]), secrets), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
