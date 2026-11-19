# Xcode DeepSeek Harness ACP

让支持自定义 ACP Agent 的 Xcode 使用 **DeepSeek Harness** 作为编码助手，并提供按任务增量加载的 Xcode 工具。

## 当前方案

```text
Xcode
  │ ACP
  ▼
DSH ACP Agent
  │
  ▼
xcode_mcp_server.py（deferred MCP 适配器）
  │  默认只暴露 10 个核心工具 + xcode_tool_search
  │  搜索后发送 notifications/tools/list_changed
  ▼
/usr/bin/xcrun mcpbridge → Xcode / Simulator
```

工具发现仍在本地完成，但模型默认只看到较小的核心工具集。需要模拟器、测试、LLDB、文档或诊断工具时，通过 `xcode_tool_search` 获取对应工具的完整 schema，并在当前会话中继续保留，避免反复更换工具导致缓存抖动。

## 环境要求

- macOS
- 支持自定义 ACP Agent 的 Xcode
- DeepSeek Harness 桌面版，默认安装在 `/Applications/DeepSeek Harness.app`
- Python 3（仅使用标准库）

已验证版本：**Xcode 27.1 + DeepSeek Harness 0.2.2-rc.3**。

## 一键安装

1. 打开 **DeepSeek Harness → Plugins → Add plugin**。
2. 粘贴：

   ```text
   https://github.com/cjleay001/xcode-deepseek-harness-acp.git
   ```

3. 安装并启用 **Xcode ACP 集成**。
4. 重启 Xcode，在 **Settings → Intelligence** 中选择 **DeepSeek Harness**。

也可以执行命令行安装：

```bash
git clone https://github.com/cjleay001/xcode-deepseek-harness-acp.git
cd xcode-deepseek-harness-acp
./scripts/install.sh
```

安装器会备份不同内容的旧文件，并原子更新启动器、ACP 代理、deferred MCP 适配器和协议客户端。

## 默认核心工具

首轮模型请求只包含以下 Xcode 工具，其他 DSH 内置工具不受影响：

```text
XcodeOpenWorkspace
XcodeListWorkspaces
XcodeListSchemes
XcodeListTargets
XcodeRead
XcodeGrep
XcodeGlob
BuildProject
GetBuildLog
GetTargetBuildSettings
xcode_tool_search
```

## 按任务扩展工具

`xcode_tool_search` 接受自然语言 `query` 和可选 `limit`（1～8，默认 6）。例如：

```json
{
  "query": "simulator screenshot and UI interaction",
  "limit": 6
}
```

适配器会：

1. 在本地 deferred 目录中搜索相关工具；
2. 只把相关工具的完整 schema 加入可见集合；
3. 发送 `notifications/tools/list_changed`，让 DSH 在后续模型步骤中使用这些工具；
4. 返回 `added` 和 `visibleXcodeToolCount`。

新增工具在当前 ACP 会话内保持可用，不随每次消息反复增删。新进程或恢复会话会重新从核心集合开始，需要时再次搜索。

### 常见扩展组

| 任务 | 按需加载的工具示例 |
|---|---|
| 模拟器、UI 自动化 | `XcodeListRunDestinations`、`DeviceInteractionStartSession`、`DeviceInteractionStartWorkspaceSession`、`DeviceInteractionInstallAndRun`、`DeviceInteractionSynthesize`、`DeviceInteractionEndSession` |
| 测试 | `XcodeListTestPlans`、`XcodeSwitchTestPlan`、`GetTestList`、`RunAllTests`、`RunSomeTests` |
| LLDB 调试 | `RunProject`、`StopProject`、`InvokeDebuggerCommand` |
| Apple 文档 | `DocumentationSearch` |
| 崩溃和性能诊断 | `GetTopCrashIssues`、`GetCrashIssueLogs`、`GetTopFieldPerformanceIssues`、`GetFieldPerformanceIssueLogs` |
| 新建项目、Target、签名 | `XcodeNewProject`、`XcodeNewTarget`、`AddInfoPlist`、`AddEntitlement` |

项目创建、删除、Entitlement、本地化、崩溃和性能工具默认不展开，只有明确任务意图时才加入。

## 模拟器推荐流程

```text
XcodeOpenWorkspace（如需要）
→ XcodeListRunDestinations
→ BuildProject
→ DeviceInteractionStartWorkspaceSession
→ DeviceInteractionInstallAndRun
→ DeviceInteractionSynthesize / GetConsoleOutput
→ DeviceInteractionEndSession
```

大项目冷构建前不要直接进入 `DeviceInteractionInstallAndRun`，先完成 `BuildProject`，避免单次工具调用超时。

## 通用命令行接口

```bash
# 查看当前 Xcode 暴露的全部工具
python3 scripts/xcode_mcp.py list
python3 scripts/xcode_mcp.py schema DeviceInteractionSynthesize

# 调用任意工具；项目绝对路径会自动解析为 workspace identifier
python3 scripts/xcode_mcp.py call XcodeListSchemes \
  --workspace /absolute/path/App.xcodeproj

# 构建、安装运行、UI 捕获并自动清理设备会话
python3 scripts/xcode_mcp.py device-state \
  --workspace /absolute/path/App.xcodeproj \
  --bundle-id com.example.App --run
```

`scripts/xcode_mcp.py` 是独立的通用客户端；Xcode ACP 默认走 deferred 适配器，所以模型首轮不会得到完整 54 个工具。

## 模型与 Agent Plan

ACP 默认模型是 `deepseek-official / deepseek-v4-flash`。如果默认路由没有凭证，可将 `~/.dsh/profiles/acp/cordis.patch.yml` 中的 `acp` 配置改成桌面版正在使用的 provider 和 model。

火山方舟 Agent Plan 可以直接复用这条 DSH ACP 路径：

```text
Xcode → DSH ACP Agent → Agent Plan → 模型
```

API Key 通过 DSH 凭证服务保存，不要写入 Xcode Agent Environment、项目或本文档。

## 连接测试

```bash
python3 scripts/test_acp.py
```

成功时会看到：

```text
Handshake OK: deepseek-harness-acp
Response: DSH_ACP_OK
ACP smoke test passed.
```

基础测试默认 `DSH_XCODE_MCP=0`，避免受 Xcode 授权影响。需要验证自动 MCP 注入时，可显式改为 `auto`。

其他回归：

```bash
python3 tests/test_proxy.py
python3 tests/test_smoke_client.py
python3 tests/test_mcp_client.py
python3 tests/test_deferred_mcp.py
python3 tests/test_tool_catalog.py
```

## 禁用与回退

- `DSH_XCODE_MCP=0`：禁用 MCP 注入，保留 `xcodebuild + simctl`。
- `DSH_XCODE_MCP=auto`：默认，按 Xcode MCP 状态自动决定。
- `DSH_XCODE_MCP=1`：仅诊断时强制注入；不可用时可能创建会话失败。

## 隐私与安全

- deferred 机制只减少工具 schema 开销，**不保证源码不出本机**。模型实际读取的代码、日志和工具结果仍会按所选模型服务处理。
- ACP 会话、附件、构建日志和 UI 结果可能保留在本地 DSH 或 Xcode 存储中，`session/close` 不等于删除数据。
- 凭证只应放 DSH 凭证服务，不进入仓库、Xcode Environment 或配置文件。
- 设备会话 key 是工具链所需的临时值，Agent 在工具调用之间使用；文档和测试不会记录真实会话 key。
- 不自动启用 Xcode MCP、不执行 sudo、不开启“允许所有 Agent”。首次使用只授权当前 Agent 和必要工作区。

完整能力、54 项目录和前置条件见 [docs/XCODE_MCP.md](docs/XCODE_MCP.md)。

## 文件说明

```text
bin/dsh-acp-launcher.sh    ACP 启动器
bin/dsh_acp_proxy.py       会话创建/恢复时的 MCP 注入与进程管理
bin/xcode_mcp_server.py    核心工具、deferred 搜索和 list_changed
lib/mcp_stdio.py           有界 MCP JSON-RPC 客户端
scripts/install.sh         备份式安装与 Xcode 注册
scripts/test_acp.py        ACP 握手和最小模型调用
scripts/xcode_mcp.py       通用 Xcode MCP 客户端与设备工作流
tests/                     ACP、代理、deferred MCP 和文档回归
docs/XCODE_MCP.md          完整能力目录和使用说明
LICENSE                    MIT License
```

## License

[MIT](LICENSE)
