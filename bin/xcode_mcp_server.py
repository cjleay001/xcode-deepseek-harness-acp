#!/usr/bin/env python3
"""Deferred Xcode MCP adapter: core tools, task search, and list_changed additions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any

try:
    from mcp_stdio import McpStdioClient, SUPPORTED_PROTOCOL_VERSIONS
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    from mcp_stdio import McpStdioClient, SUPPORTED_PROTOCOL_VERSIONS

BASE_TOOLS = [
    "XcodeOpenWorkspace",
    "XcodeListWorkspaces",
    "XcodeListSchemes",
    "XcodeListTargets",
    "XcodeRead",
    "XcodeGrep",
    "XcodeGlob",
    "BuildProject",
    "GetBuildLog",
    "GetTargetBuildSettings",
]
REQUIRED_TOOLS = {"XcodeOpenWorkspace", "BuildProject", "GetBuildLog"}
HIGH_RISK_PREFIXES = (
    "Add", "Update", "XcodeRM", "XcodeMV", "XcodeNew", "XcodeWrite", "XcodeUpdate",
    "StringCatalog", "Localization", "GetTop", "GetCrashIssueLogs", "GetFieldPerformanceIssueLogs",
)
HIGH_RISK_TERMS = (
    "entitlement", "签名", "新建项目", "新项目", "new project", "new target", "delete", "remove",
    "删除", "移除", "修改配置", "build setting", "compiler flag", "本地化", "翻译", "localiz",
    "translat", "crash", "崩溃", "performance", "性能", "field performance", "诊断", "diagnostic",
)
SYNONYMS = {
    "模拟器": "simulator device",
    "截图": "screenshot image capture",
    "点击": "tap click synthesize",
    "滑动": "swipe scroll synthesize",
    "输入": "type text synthesize",
    "构建": "build compile",
    "编译": "build compile",
    "运行": "run launch install",
    "启动": "run launch install",
    "调试": "debug debugger lldb",
    "断点": "breakpoint debug",
    "测试": "test xctest",
    "文档": "documentation docs",
    "崩溃": "crash diagnostic",
    "性能": "performance diagnostic",
    "日志": "log console output",
    "项目": "project workspace",
    "文件": "file read write",
    "权限": "entitlement permission",
    "本地化": "localization string catalog translation",
}
SEARCH_DEFINITION = {
    "name": "xcode_tool_search",
    "description": "Search deferred Xcode tools by task. Returns full schemas only for relevant tools and adds them for the rest of this session.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural-language task such as 'simulator screenshot' or 'unit tests'."},
            "limit": {"type": "number", "description": "Maximum tools to add, from 1 to 8. Defaults to 6."},
        },
        "required": ["query"],
    },
}
SENSITIVE_KEYS = {"interactionSessionKey", "interactSessionKey"}
FALLBACK_PROTOCOL_VERSION = "2025-11-25"


def collect_secrets(value: Any) -> set[str]:
    secrets: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in SENSITIVE_KEYS and isinstance(item, str) and item:
                secrets.add(item)
            else:
                secrets.update(collect_secrets(item))
    elif isinstance(value, list):
        for item in value:
            secrets.update(collect_secrets(item))
    return secrets


def redact_text(text: str, secrets: set[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r'(?i)("(?:interactionSessionKey|interactSessionKey)"\s*:\s*")[^"]*(")', r"\1[redacted]\2", text)
    text = re.sub(r"(?i)('(?:interactionSessionKey|interactSessionKey)'\s*:\s*')[^']*(')", r"\1[redacted]\2", text)
    return text


def redact(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, dict):
        return {key: "[redacted]" if key in SENSITIVE_KEYS else redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def has_high_risk_intent(query: str) -> bool:
    normalized = query.lower()
    return any(term in normalized for term in HIGH_RISK_TERMS)


def expanded_query(query: str) -> str:
    expanded = f" {query.lower()} "
    for chinese, english in SYNONYMS.items():
        if chinese in expanded:
            expanded += f" {english} "
    return expanded


STOP_WORDS = {
    "and", "or", "the", "a", "an", "to", "of", "in", "on", "for", "with", "by",
    "is", "are", "be", "can", "use", "using", "this", "that", "task",
}


def meaningful_tokens(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9_\u4e00-\u9fff]+", text.lower())
        if len(token) > 1 and token not in STOP_WORDS
    ]


def score_tool(definition: dict[str, Any], query: str) -> int:
    raw_name = definition["name"]
    name = raw_name.lower()
    description = str(definition.get("description", "")).lower()
    name_tokens = {
        token.lower() for token in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", raw_name)
    }
    terms = meaningful_tokens(expanded_query(query))
    if not terms:
        return 0
    phrase = " ".join(terms)
    score = 0
    if len(phrase) > 2 and phrase in name:
        score += 14
    if len(phrase) > 2 and phrase in description:
        score += 5
    for token in terms:
        if token in name_tokens:
            score += 5
        elif re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", description):
            score += 2
    return score


def rank_tools(catalog: dict[str, dict[str, Any]], query: str, limit: int = 6) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    allow_high_risk = has_high_risk_intent(query)
    capped_limit = max(1, min(8, limit if isinstance(limit, int) else 6))
    deferred = []
    core = []
    for definition in catalog.values():
        if not allow_high_risk and definition["name"].startswith(HIGH_RISK_PREFIXES):
            continue
        score = score_tool(definition, query)
        if score <= 0:
            continue
        entry = (score, definition)
        if definition["name"] in BASE_TOOLS:
            core.append(entry)
        else:
            deferred.append(entry)
    deferred.sort(key=lambda item: (-item[0], item[1]["name"]))
    core.sort(key=lambda item: (-item[0], item[1]["name"]))
    return [definition for _, definition in (deferred + core)[:capped_limit]]


class DeferredXcodeServer:
    def __init__(self) -> None:
        upstream_command = shlex.split(os.environ.get("XCODE_MCP_UPSTREAM", "/usr/bin/xcrun mcpbridge"))
        self.upstream = McpStdioClient(upstream_command, 20)
        try:
            self.upstream.initialize()
            definitions = self.upstream.list_tools()
            self.catalog = {definition["name"]: definition for definition in definitions}
            if not REQUIRED_TOOLS.issubset(self.catalog):
                raise RuntimeError("Xcode MCP did not provide the required core tools")
            self.allowed = set(BASE_TOOLS)
            self.next_id = 0
        except Exception:
            self.upstream.close()
            raise

    def send(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        sys.stdout.buffer.write(payload.encode("utf-8"))
        sys.stdout.buffer.flush()

    def visible_tools(self) -> list[dict[str, Any]]:
        visible = [self.catalog[name] for name in BASE_TOOLS]
        visible.extend(
            definition for name, definition in self.catalog.items()
            if name in self.allowed and name not in BASE_TOOLS
        )
        visible.append(SEARCH_DEFINITION)
        return visible

    def search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        matches = rank_tools(self.catalog, str(arguments.get("query", "")), arguments.get("limit", 6))
        added = []
        for definition in matches:
            if definition["name"] not in self.allowed:
                self.allowed.add(definition["name"])
                added.append(definition["name"])
        if added:
            self.send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed", "params": {}})
        payload = {
            "tools": matches,
            "added": added,
            "visibleXcodeToolCount": len(self.allowed),
            "note": "Added tools remain available for the rest of this session. No tools are removed later in the same session.",
        }
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}], "structuredContent": payload}

    def handle(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        if method == "notifications/initialized":
            return
        request_id = message.get("id")
        if method == "initialize":
            requested_version = message.get("params", {}).get("protocolVersion")
            protocol_version = requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS else FALLBACK_PROTOCOL_VERSION
            self.send({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "xcode-mcp-router", "version": "1.4.0"},
                },
            })
            return
        if method == "tools/list":
            self.send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.visible_tools()}})
            return
        if method == "tools/call":
            params = message.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                if name != "xcode_tool_search" and name not in self.allowed:
                    raise RuntimeError(f"Tool is not enabled yet: {name}. Call xcode_tool_search first.")
                if name == "xcode_tool_search":
                    result = self.search(arguments)
                else:
                    result = self.upstream.request("tools/call", {"name": name, "arguments": arguments}, 300)
                self.send({"jsonrpc": "2.0", "id": request_id, "result": result})
            except Exception as exc:
                self.send({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32603, "message": redact_text(str(exc), self.upstream.session_secrets)},
                })
            return
        if method == "ping":
            self.send({"jsonrpc": "2.0", "id": request_id, "result": {}})
            return
        if method in {"resources/list", "resources/templates/list"}:
            key = "resources" if method == "resources/list" else "resourceTemplates"
            self.send({"jsonrpc": "2.0", "id": request_id, "result": {key: []}})
            return
        if request_id is not None:
            self.send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}})

    def run(self) -> None:
        try:
            for raw_line in sys.stdin.buffer:
                if not raw_line.strip():
                    continue
                self.handle(json.loads(raw_line))
        finally:
            self.upstream.close()


def main() -> int:
    try:
        server = DeferredXcodeServer()
        server.run()
        return 0
    except Exception as exc:
        print(f"Xcode MCP adapter failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
