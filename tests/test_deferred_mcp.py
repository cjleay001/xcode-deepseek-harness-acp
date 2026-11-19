#!/usr/bin/env python3
"""End-to-end tests for deferred MCP discovery and list_changed additions."""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
from mcp_stdio import McpStdioClient

os.environ["XCODE_MCP_UPSTREAM"] = f"{sys.executable} {ROOT / 'tests' / 'fake_xcode_mcp.py'}"
client = McpStdioClient(
    [sys.executable, str(ROOT / "bin" / "xcode_mcp_server.py")],
    15,
)
try:
    initialized = client.initialize()
    assert initialized["capabilities"]["tools"]["listChanged"] is True
    initial = client.list_tools()
    initial_names = {tool["name"] for tool in initial}
    assert "xcode_tool_search" in initial_names
    assert "DeviceInteractionSynthesize" not in initial_names
    assert "BuildProject" in initial_names
    assert "XcodeNewTarget" not in initial_names

    found = client.request("tools/call", {
        "name": "xcode_tool_search",
        "arguments": {"query": "simulator screenshot", "limit": 6},
    }, 15)
    assert found["structuredContent"]["added"]
    assert any(tool["name"] == "DeviceInteractionSynthesize" for tool in found["structuredContent"]["tools"])
    assert all("inputSchema" in tool for tool in found["structuredContent"]["tools"])
    assert any(message.get("method") == "notifications/tools/list_changed" for message in client.notifications)

    expanded = client.list_tools()
    expanded_names = {tool["name"] for tool in expanded}
    assert "DeviceInteractionSynthesize" in expanded_names
    assert "XcodeNewTarget" not in expanded_names

    repeated = client.request("tools/call", {
        "name": "xcode_tool_search",
        "arguments": {"query": "simulator screenshot", "limit": 6},
    }, 15)
    assert repeated["structuredContent"]["added"] == []

    admin = client.request("tools/call", {
        "name": "xcode_tool_search",
        "arguments": {"query": "create new target and entitlement"},
    }, 15)
    assert any(tool["name"] == "XcodeNewTarget" for tool in admin["structuredContent"]["tools"])

    build = client.request("tools/call", {"name": "BuildProject", "arguments": {}}, 15)
    assert build["content"][0]["text"] == "built"

    secret = client.request("tools/call", {"name": "DeviceInteractionStartWorkspaceSession", "arguments": {}}, 15)
    serialized = json.dumps(secret)
    assert "secret-session" in serialized, "The model needs the original session key for chained device calls"
    print("Deferred MCP discovery, list_changed, forwarding and redaction tests: OK")
finally:
    client.close()
