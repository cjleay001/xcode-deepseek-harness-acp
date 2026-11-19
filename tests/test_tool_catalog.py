#!/usr/bin/env python3
"""Ensure the public catalog covers every tool discovered on Xcode 27.1."""

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {
    "AddEntitlement", "AddInfoPlist", "BuildProject",
    "DeviceInteractionEndSession", "DeviceInteractionInstallAndRun", "DeviceInteractionStartSession",
    "DeviceInteractionStartWorkspaceSession", "DeviceInteractionSynthesize", "DocumentationSearch",
    "GetBuildLog", "GetConsoleOutput", "GetCrashIssueLogs", "GetFieldPerformanceIssueLogs",
    "GetFileCompilerFlags", "GetTargetBuildSettings", "GetTestList", "GetTopCrashIssues",
    "GetTopFieldPerformanceIssues", "InvokeDebuggerCommand", "LocalizationPlanner", "RenderPreview",
    "RunAllTests", "RunCodeSnippet", "RunProject", "RunSomeTests", "StopProject",
    "StringCatalogContext", "StringCatalogEdit", "StringCatalogRead", "UpdateFileCompilerFlags",
    "UpdateTargetBuildSetting", "XcodeCloseWorkspace", "XcodeGlob", "XcodeGrep", "XcodeLS",
    "XcodeListRunDestinations", "XcodeListSchemes", "XcodeListTargets", "XcodeListTemplates",
    "XcodeListTestPlans", "XcodeListWorkspaces", "XcodeMV", "XcodeMakeDir", "XcodeNewProject",
    "XcodeNewTarget", "XcodeOpenWorkspace", "XcodeRM", "XcodeRead", "XcodeRefreshCodeIssuesInFile",
    "XcodeSwitchRunDestination", "XcodeSwitchScheme", "XcodeSwitchTestPlan", "XcodeUpdate", "XcodeWrite",
}
assert len(EXPECTED) == 54
text = (ROOT / "docs" / "XCODE_MCP.md").read_text(encoding="utf-8")
documented = set(re.findall(r"`([A-Za-z]+)`", text))
missing = sorted(EXPECTED - documented)
assert not missing, f"Tools missing from documentation: {missing}"
manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
assert "scripts/xcode_mcp.py" in manifest["files"]
assert "docs/XCODE_MCP.md" in manifest["files"]
print("All 54 discovered Xcode MCP tools are documented and packaged")
