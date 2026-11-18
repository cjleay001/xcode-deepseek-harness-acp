#!/usr/bin/env python3
"""Minimal JSON-RPC peer used by the proxy regression tests."""

import json
import sys

for raw_line in sys.stdin:
    message = json.loads(raw_line)
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": 1, "agentInfo": {"name": "fake", "version": "1"}}
    elif method in {"session/new", "session/resume"}:
        result = {
            "sessionId": "fake-session",
            "mcpServers": message.get("params", {}).get("mcpServers"),
        }
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "result": result}) + "\n")
    sys.stdout.flush()
