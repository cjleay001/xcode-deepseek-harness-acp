#!/usr/bin/env python3
"""MCP peer that returns an unsupported protocol version."""

import json
import os
from pathlib import Path
import sys

pid_file = os.environ.get("FAKE_PID_FILE")
if pid_file:
    Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
for raw_line in sys.stdin.buffer:
    request = json.loads(raw_line)
    if request.get("method") == "initialize":
        result = {"protocolVersion": "1999-01-01", "capabilities": {}, "serverInfo": {"name": "bad-protocol", "version": "1"}}
    else:
        result = {}
    sys.stdout.buffer.write(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}).encode() + b"\n")
    sys.stdout.buffer.flush()
