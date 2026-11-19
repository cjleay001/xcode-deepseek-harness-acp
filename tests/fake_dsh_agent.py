#!/usr/bin/env python3
"""Fake DSH ACP agent that emits prompt notifications and result in one burst."""

import json
import sys


def send(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
    sys.stdout.buffer.flush()


for raw_line in sys.stdin.buffer:
    request = json.loads(raw_line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": 1, "agentInfo": {"name": "fake-dsh", "version": "1"}}})
    elif method == "session/new":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "fake-session", "configOptions": [{"id": "model", "currentValue": "fake-model"}]}})
    elif method == "session/prompt":
        session_id = request["params"]["sessionId"]
        frames = [
            {"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": session_id, "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "DSH_ACP_OK"}}}},
            {"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": session_id, "update": {"sessionUpdate": "usage_update", "used": 1, "size": 10}}},
            {"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}},
        ]
        payload = b"".join(json.dumps(frame, separators=(",", ":")).encode() + b"\n" for frame in frames)
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
    elif method == "session/close":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    else:
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Unknown method"}})
