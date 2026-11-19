#!/usr/bin/env python3
"""Small Xcode MCP fixture with core, device, admin, and secret results."""

import json
import sys

BASE = [
    "XcodeOpenWorkspace", "XcodeListWorkspaces", "XcodeListSchemes", "XcodeListTargets",
    "XcodeRead", "XcodeGrep", "XcodeGlob", "BuildProject", "GetBuildLog", "GetTargetBuildSettings",
]
DEVICE = [
    "XcodeListRunDestinations", "DeviceInteractionStartWorkspaceSession",
    "DeviceInteractionInstallAndRun", "DeviceInteractionSynthesize",
    "GetConsoleOutput", "DeviceInteractionEndSession",
]
ADMIN = ["XcodeNewTarget", "AddEntitlement", "XcodeRM"]
TOOLS = [
    {"name": name, "description": f"{name} builds and inspects an iOS project", "inputSchema": {"type": "object", "properties": {}}}
    for name in BASE
] + [
    {"name": name, "description": f"{name} simulator device run screenshot UI hierarchy", "inputSchema": {"type": "object", "properties": {}}}
    for name in DEVICE
] + [
    {"name": name, "description": f"{name} creates or deletes project settings", "inputSchema": {"type": "object", "properties": {}}}
    for name in ADMIN
]


def send(message):
    sys.stdout.buffer.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
    sys.stdout.buffer.flush()


for raw_line in sys.stdin.buffer:
    request = json.loads(raw_line)
    method = request.get("method")
    if method == "notifications/initialized":
        continue
    request_id = request.get("id")
    if method == "initialize":
        result = {"protocolVersion": "2026-07-28", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-xcode", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = request["params"]["name"]
        if name == "BuildProject":
            result = {"content": [{"type": "text", "text": "built"}]}
        elif name == "DeviceInteractionStartWorkspaceSession":
            result = {"structuredContent": {"interactionSessionKey": "secret-session", "deviceUUID": "fake-device", "deviceIsSimulator": True}}
        elif name == "DeviceInteractionSynthesize":
            result = {"structuredContent": {"applicationState": "Running", "screenshotPath": "/tmp/fake.png", "hierarchyPath": "/tmp/fake.xml"}}
        elif name == "DeviceInteractionEndSession":
            result = {"content": [{"type": "text", "text": "ended"}]}
        else:
            result = {"content": [{"type": "text", "text": name}]}
    elif method == "ping":
        result = {}
    else:
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Unknown method"}})
        continue
    send({"jsonrpc": "2.0", "id": request_id, "result": result})
