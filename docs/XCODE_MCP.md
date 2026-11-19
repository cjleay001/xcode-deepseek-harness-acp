# Xcode MCP 完整能力与 deferred 调用说明

本工具通过 Apple 自带的 `xcrun mcpbridge` 获取 Xcode 能力。当前在 **Xcode 27.1** 上可发现并接入 **54 个工具**，但不会把它们默认全部展开到模型上下文。

## 1. deferred 架构

```text
Xcode / DSH Agent
        │
        ▼
xcode_mcp_server.py
  - 连接 mcpbridge 并发现工具
  - 默认只公开核心工具和 xcode_tool_search
  - 按任务搜索 deferred 工具
  - 通过 notifications/tools/list_changed 增量公开
        │
        ▼
/usr/bin/xcrun mcpbridge
```

- 工具目录由 Xcode 动态提供，其他版本可能增减。
- `initialize` 按支持版本集合协商；客户端版本受支持时回显，未知版本回退到服务端支持的 `2025-11-25`，由客户端决定是否继续。上游返回版本也会校验，不能任意接受未知版本。
- 每个新 MCP 进程从核心集合开始；恢复 ACP 会话后可再次搜索。
- 新增工具在当前会话内保持，不随消息反复收缩，降低 schema 前缀和 KV Cache 抖动。

## 2. 首轮核心集合

默认公开以下 10 个 Xcode 工具及 `xcode_tool_search`：

| 工具 | 用途 |
|---|---|
| `XcodeOpenWorkspace` | 打开项目并获得工作区标识 |
| `XcodeListWorkspaces` | 列出打开的工作区 |
| `XcodeListSchemes` | 查看 Scheme 和活动项 |
| `XcodeListTargets` | 查看 Target 和产品类型 |
| `XcodeRead` | 读取项目文件 |
| `XcodeGrep` | 搜索项目内容 |
| `XcodeGlob` | 按通配符查找文件 |
| `BuildProject` | 构建项目并等待结果 |
| `GetBuildLog` | 获取构建日志 |
| `GetTargetBuildSettings` | 读取 Target 构建设置 |
| `xcode_tool_search` | 按任务搜索并挂载 deferred 工具 |

DSH 自带的文件、shell 和其他工具不因 deferred 而被删除。

## 3. 按任务搜索

`xcode_tool_search` 接受：

```json
{
  "query": "simulator screenshot and UI interaction",
  "limit": 6
}
```

执行后：

1. 按工具名、描述和任务关键词评分；
2. 返回最相关的最多 6 个工具的完整 schema；
3. 将这些工具加入可见集合；
4. 发送 `notifications/tools/list_changed`，使 DSH 后续步骤可以实际调用；
5. 返回 `added` 和 `visibleXcodeToolCount`。

高风险配置、删除、签名、本地化、崩溃和性能工具，只有查询中明确表达对应意图才返回。无匹配结果不会伪造成功。

`tools/list` 和 `tools/call` 使用同一允许集合：deferred 工具在搜索加入前不能直接调用，只有核心工具或本轮已加入的工具才会被转发到 `mcpbridge`。搜索加入后，后续步骤才可执行对应工具。

## 4. 完整工具目录

### 工作区、Scheme、Target 与项目创建（13）

| 工具 | 用途 |
|---|---|
| `XcodeOpenWorkspace` | 打开 `.xcodeproj` / `.xcworkspace` 并返回工作区标识 |
| `XcodeCloseWorkspace` | 关闭由 `XcodeOpenWorkspace` 打开的工作区 |
| `XcodeListWorkspaces` | 列出当前打开的工作区 |
| `XcodeListSchemes` | 列出 Scheme 及当前活动项 |
| `XcodeSwitchScheme` | 切换活动 Scheme |
| `XcodeListRunDestinations` | 列出模拟器、真机和构建目标 |
| `XcodeSwitchRunDestination` | 切换运行目标 |
| `XcodeListTargets` | 列出 Target、产品类型及测试角色 |
| `GetTargetBuildSettings` | 读取 Target 构建设置 |
| `UpdateTargetBuildSetting` | 修改、追加或删除 Target 构建设置 |
| `XcodeListTemplates` | 查询项目和 Target 模板及选项 |
| `XcodeNewProject` | 从模板创建新项目 |
| `XcodeNewTarget` | 从模板添加新 Target |

### 项目文件与构建配置（14）

| 工具 | 用途 |
|---|---|
| `XcodeLS` | 列出项目导航器中的文件和目录 |
| `XcodeGlob` | 按通配符查找项目文件 |
| `XcodeGrep` | 用正则搜索项目内容 |
| `XcodeRead` | 读取项目文件 |
| `XcodeWrite` | 创建或覆盖文件并加入项目结构 |
| `XcodeUpdate` | 替换项目文件中的文本 |
| `XcodeMV` | 移动或重命名文件、目录 |
| `XcodeMakeDir` | 创建目录和项目分组 |
| `XcodeRM` | 移除项目文件，可选删除磁盘文件 |
| `GetFileCompilerFlags` | 读取单文件编译参数 |
| `UpdateFileCompilerFlags` | 修改、追加或删除单文件编译参数 |
| `AddInfoPlist` | 添加或修改 Target 的 Info.plist 项 |
| `AddEntitlement` | 添加必要的代码签名 Entitlement |
| `XcodeRefreshCodeIssuesInFile` | 获取文件编译诊断，需要对应诊断服务 |

### 构建、运行、调试与 Preview（7）

| 工具 | 用途 |
|---|---|
| `BuildProject` | 构建当前项目并等待完成 |
| `GetBuildLog` | 查询构建日志，支持级别、正则和文件过滤 |
| `RunProject` | 构建并运行当前 Scheme，可附加调试器 |
| `StopProject` | 停止当前运行的 App |
| `InvokeDebuggerCommand` | 向活动 LLDB 会话发送 `bt`、`po`、`continue` 等命令 |
| `RunCodeSnippet` | 在指定 Swift 文件上下文中编译运行代码片段 |
| `RenderPreview` | 构建并渲染 SwiftUI Preview，返回快照和变体 |

`RunProject(attachDebugger=true)` 返回后，LLDB 可能仍在异步附加。若立即收到 `No active debug session`，应稍等再查询，不要误判为桥接失败。

### 模拟器、真机交互与控制台（6）

| 工具 | 用途 |
|---|---|
| `DeviceInteractionStartSession` | 无工作区的设备会话 |
| `DeviceInteractionStartWorkspaceSession` | 绑定工作区的设备会话，可构建、安装、运行 |
| `DeviceInteractionInstallAndRun` | 构建、安装并启动当前 App |
| `DeviceInteractionSynthesize` | 点击、滑动、输入、硬件按钮、旋转，并捕获截图、UI 层级和日志 |
| `DeviceInteractionEndSession` | 关闭设备会话，释放资源 |
| `GetConsoleOutput` | 获取 stdout、stderr 和 OSLog，支持过滤和上下文 |

推荐顺序：

```text
XcodeOpenWorkspace（如需要）
→ XcodeListRunDestinations
→ BuildProject
→ DeviceInteractionStartWorkspaceSession
→ DeviceInteractionInstallAndRun
→ DeviceInteractionSynthesize / GetConsoleOutput
→ DeviceInteractionEndSession
```

### 测试与 Test Plan（5）

| 工具 | 用途 |
|---|---|
| `XcodeListTestPlans` | 列出 Test Plan 及当前活动项 |
| `XcodeSwitchTestPlan` | 切换活动 Test Plan |
| `GetTestList` | 获取可运行测试及 Target/Test Identifier |
| `RunAllTests` | 运行活动 Test Plan 的全部测试 |
| `RunSomeTests` | 按 Target 和 Test Identifier 运行指定测试 |

没有测试 Target 或活动 Test Plan 时，工具可能返回“没有测试”，不代表 MCP 连接失败。

### Apple 文档与本地化（5）

| 工具 | 用途 |
|---|---|
| `DocumentationSearch` | 语义搜索 Apple Developer 文档，可按 Framework 限定 |
| `LocalizationPlanner` | 准备项目以添加语言或执行项目翻译 |
| `StringCatalogContext` | 读取 String Catalog 键的上下文和源语言值 |
| `StringCatalogRead` | 按翻译状态读取 String Catalog 键 |
| `StringCatalogEdit` | 写入翻译、变体和复数形式 |

在 Agent 中使用本地化工具时，应遵循工具描述中的前置要求，先加载对应的 `xcode-integration:translation-coordinator` 或 `xcode-integration:translation` 指令；本仓库不伪造这些技能。

### 崩溃与性能诊断（4）

| 工具 | 用途 |
|---|---|
| `GetTopCrashIssues` | 获取近 14 天的主要崩溃签名 |
| `GetCrashIssueLogs` | 获取指定崩溃签名的日志与诊断建议 |
| `GetTopFieldPerformanceIssues` | 查询启动、卡顿、磁盘写入、能耗等现场性能问题 |
| `GetFieldPerformanceIssueLogs` | 获取指定性能问题的详细日志和分析 |

这些工具依赖 App 的 Bundle ID、版本、平台、Apple 报表权限和可用数据。无权限或无数据时会返回明确错误。

## 5. 通用命令行

```bash
python3 scripts/xcode_mcp.py list
python3 scripts/xcode_mcp.py list --json
python3 scripts/xcode_mcp.py schema DeviceInteractionSynthesize

python3 scripts/xcode_mcp.py call XcodeListSchemes \
  --workspace /absolute/path/App.xcodeproj

python3 scripts/xcode_mcp.py call DocumentationSearch \
  --args '{"query":"UIViewController view lifecycle","frameworks":["UIKit"]}'

python3 scripts/xcode_mcp.py device-state \
  --workspace /absolute/path/App.xcodeproj \
  --bundle-id com.example.App \
  --run \
  --interaction-command "t 200 400"
```

- `call --workspace` 只在工具 schema 支持 `workspaceIdentifier` 时注入。
- 项目绝对路径会先通过 `XcodeOpenWorkspace` 解析为当前 `workspace-*` 标识。
- `device-state` 使用唯一会话名，并在 `finally` 中调用 `DeviceInteractionEndSession`。
- 不加 `--run` 时只捕获当前状态，`NotRun` 是合法结果，不代表桥接失败。
- 普通工具错误以 JSON 输出并返回退出码 `2`；协议、参数或启动错误返回 `1`。

## 6. 性能与隐私边界

- deferred 只减少模型工具 schema 和无效调用，**不减少 Agent 实际读取源码的网络暴露**。云端模型仍会处理任务所需的代码、日志和工具结果。
- 首次 MCP 连接和工具发现仍需执行，节省的是后续模型请求中的工具描述和部分推理开销。
- 本地 DSH 会话、附件、构建日志和 Xcode 日志可能包含代码与敏感信息，关闭会话不等于删除。
- 凭证只能存 DSH 凭证服务，不写入仓库、Xcode Environment 或文档。
- 设备会话 key 是工具链必需的临时凭据，模型在 Start/Synthesize/End 等连续调用中使用；不得把它写入公开文档或提交到仓库。
- 不自动启用 Xcode MCP，不执行 sudo，不设置“允许所有 Agent”。首次只授权当前 Agent 和必要工作区。
- `XcodeWrite`、`XcodeUpdate`、`XcodeMV`、`XcodeRM`、`XcodeNewProject`、`XcodeNewTarget` 及配置修改工具会改变项目，调用前应明确目标并备份。
- 崩溃、性能和文档工具可能访问 Apple 服务，只发送完成任务所需的查询和标识。
- ACP 代理只创建并清理自己的进程组，不触碰 XcodeService 或其他用户进程。

## 7. 已验证行为

- 初始只暴露核心工具与 `xcode_tool_search`；
- 搜索模拟器任务后通过 `notifications/tools/list_changed` 增量挂载设备工具；
- 新增加的工具可实际完成设备会话启动、点击、截图/UI 层级读取和关闭；
- 项目读取、文档搜索、构建设置、编译参数、构建日志、控制台和测试计划均可调用；
- 标准 ACP 握手、最小模型响应、恢复会话、异常退出和进程组清理均有回归覆盖。
