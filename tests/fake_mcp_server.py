#!/usr/bin/env python3
"""Fake MCP server for pagination, schema, call, and error regressions."""

import json
import sys

TOOLS = [
    {"name": "Echo", "description": "Echo input", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "workspaceIdentifier": {"type": "string"}}}},
    {"name": "Fail", "description": "Return a tool error", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "DeviceInteractionStartSession", "description": "Start", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "DeviceInteractionSynthesize", "description": "Capture", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "DeviceInteractionEndSession", "description": "End", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "XcodeOpenWorkspace", "description": "Open", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "BuildProject", "description": "Build", "inputSchema": {"type": "object", "properties": {"workspaceIdentifier": {"type": "string"}}}},
    {"name": "DeviceInteractionStartWorkspaceSession", "description": "Start workspace session", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "DeviceInteractionInstallAndRun", "description": "Install and run", "inputSchema": {"type": "object", "properties": {}}},
]


def frame(message: dict) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode() + b"\n"


def send(message: dict) -> None:
    sys.stdout.buffer.write(frame(message))
    sys.stdout.buffer.flush()


for raw_line in sys.stdin.buffer:
    request = json.loads(raw_line)
    method = request.get("method")
    if method == "notifications/initialized":
        continue
    request_id = request.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2026-07-28", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-mcp", "version": "1"}}
    elif method == "tools/list":
        cursor = request.get("params", {}).get("cursor")
        result = {"tools": TOOLS[1:]} if cursor else {"tools": [TOOLS[0]], "nextCursor": "page-2"}
    elif method == "tools/call" and request["params"]["name"] == "Echo":
        arguments = request["params"]["arguments"]
        text = arguments.get("text", "")
        if arguments.get("workspaceIdentifier"):
            text += ":" + arguments["workspaceIdentifier"]
        result = {"content": [{"type": "text", "text": text}]}
    elif method == "tools/call" and request["params"]["name"] == "DeviceInteractionStartSession":
        result = {"structuredContent": {"interactionSessionKey": "secret-session", "deviceUUID": "fake-device", "deviceIsSimulator": True}}
    elif method == "tools/call" and request["params"]["name"] == "DeviceInteractionSynthesize":
        assert request["params"]["arguments"]["interactSessionKey"] == "secret-session"
        result = {"structuredContent": {"applicationState": "Running", "screenshotPath": "/tmp/fake.png", "hierarchyPath": "/tmp/fake.xml"}}
    elif method == "tools/call" and request["params"]["name"] == "DeviceInteractionEndSession":
        assert request["params"]["arguments"]["interactionSessionKey"] == "secret-session"
        result = {"content": [{"type": "text", "text": "ended"}]}
    elif method == "tools/call" and request["params"]["name"] == "XcodeOpenWorkspace":
        result = {"structuredContent": {"workspaceIdentifier": "workspace-fake", "workspacePath": request["params"]["arguments"]["path"]}}
    elif method == "tools/call" and request["params"]["name"] == "BuildProject":
        result = {"content": [{"type": "text", "text": "built"}]}
    elif method == "tools/call" and request["params"]["name"] == "DeviceInteractionStartWorkspaceSession":
        result = {"structuredContent": {"interactionSessionKey": "secret-session", "deviceUUID": "fake-device", "deviceIsSimulator": True}}
    elif method == "tools/call" and request["params"]["name"] == "DeviceInteractionInstallAndRun":
        result = {"content": [{"type": "text", "text": "running"}]}
    elif method == "tools/call":
        result = {"isError": True, "content": [{"type": "text", "text": "expected failure"}]}
    else:
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Unknown method"}})
        continue
    # Emit protocol responses in one burst to exercise raw buffered reads.
    sys.stdout.buffer.write(frame({"jsonrpc": "2.0", "id": request_id, "result": result}))
    sys.stdout.buffer.flush()
