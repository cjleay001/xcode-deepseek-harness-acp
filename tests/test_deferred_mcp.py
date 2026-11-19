#!/usr/bin/env python3
"""End-to-end tests for deferred MCP discovery and list_changed additions."""

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
from mcp_stdio import McpStdioClient
sys.path.insert(0, str(ROOT / "bin"))
from xcode_mcp_server import rank_tools

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

    try:
        client.request("tools/call", {"name": "DeviceInteractionSynthesize", "arguments": {}}, 15)
        raise AssertionError("Deferred tool was callable before search")
    except RuntimeError as exc:
        assert "not enabled" in str(exc)

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

    fallback = client.request("initialize", {"protocolVersion": "1999-01-01", "capabilities": {}, "clientInfo": {"name": "fallback-test", "version": "1"}}, 15)
    assert fallback["protocolVersion"] == "2025-11-25"

    catalog = {tool["name"]: tool for tool in client.list_tools()}
    assert rank_tools(catalog, "and") == []
    assert not any(tool["name"] == "BuildProject" for tool in rank_tools(catalog, "ui"))
    prioritized = rank_tools(catalog, "simulator screenshot", 2)
    assert prioritized[0]["name"] != "BuildProject"

    build = client.request("tools/call", {"name": "BuildProject", "arguments": {}}, 15)
    assert build["content"][0]["text"] == "built"

    secret = client.request("tools/call", {"name": "DeviceInteractionStartWorkspaceSession", "arguments": {}}, 15)
    serialized = json.dumps(secret)
    assert "secret-session" in serialized, "The model needs the original session key for chained device calls"
    print("Deferred MCP discovery, list_changed, forwarding and redaction tests: OK")
finally:
    client.close()

# Unsupported upstream versions fail validation and are closed deterministically.
bad_client = McpStdioClient([sys.executable, str(ROOT / "tests" / "fake_bad_protocol.py")], 5)
try:
    try:
        bad_client.initialize()
        raise AssertionError("Unsupported protocol was accepted")
    except RuntimeError as exc:
        assert "Unsupported MCP protocol version" in str(exc)
finally:
    bad_client.close()

pid_path = ROOT / "tests" / ".tmp-bad-protocol.pid"
pid_path.unlink(missing_ok=True)
process = subprocess.Popen(
    [sys.executable, str(ROOT / "bin" / "xcode_mcp_server.py")],
    env={**os.environ, "XCODE_MCP_UPSTREAM": f"{sys.executable} {ROOT / 'tests' / 'fake_bad_protocol.py'}", "FAKE_PID_FILE": str(pid_path)},
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
assert process.wait(timeout=15) == 1
failed_pid = int(pid_path.read_text())
try:
    os.kill(failed_pid, 0)
    raise AssertionError("Failed upstream process was left running")
except ProcessLookupError:
    pass
pid_path.unlink(missing_ok=True)
print("Deferred negative protocol, gating, scoring and startup-cleanup tests: OK")
