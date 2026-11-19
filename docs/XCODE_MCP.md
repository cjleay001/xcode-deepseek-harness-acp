# Xcode MCP 完整能力与调用方法

本工具通过 Apple 自带的 `xcrun mcpbridge` 接入 Xcode。当前在 **Xcode 27.1** 上发现并接入了 **54 个工具**。清单由 Xcode 动态返回，其他版本可能增减；本工具不按硬编码清单过滤功能。

## 三种使用方式

1. **DSH 插件会话**：启用 **Xcode ACP 集成** 后，DSH 通过 `@deepseek-ai/dsh-mcp-client` 注册 `mcp__xcode__*` 工具。新会话可直接要求 Agent 使用这些工具。
2. **Xcode ACP Agent**：启动器中的代理在 `session/new` 和 `session/resume` 时按需注入 `xcrun mcpbridge`，使 Xcode 中的 DeepSeek Harness Agent 获得同一组工具。
3. **独立命令行**：`scripts/xcode_mcp.py` 可发现、查看 schema 并调用任意 MCP 工具，不要求模型参与。

外部 `npx xcodebuildmcp` 不是 Apple 的 `mcpbridge`，不属于本工具的默认依赖。

## 命令行速查

```bash
# 列出当前 Xcode 支持的全部工具
python3 scripts/xcode_mcp.py list

# 输出完整工具定义和 JSON Schema
python3 scripts/xcode_mcp.py list --json
python3 scripts/xcode_mcp.py schema DeviceInteractionSynthesize

# 传 workspace identifier；也可直接传项目绝对路径，由客户端自动打开并解析
python3 scripts/xcode_mcp.py call XcodeListSchemes \
  --workspace /absolute/path/App.xcodeproj

# 调用任意工具；--args 必须是 JSON 对象
python3 scripts/xcode_mcp.py call DocumentationSearch \
  --args '{"query":"UIViewController view lifecycle","frameworks":["UIKit"]}'

# 构建、安装运行、点击、捕获截图/UI 层级/日志，然后自动关闭设备会话
python3 scripts/xcode_mcp.py device-state \
  --workspace /absolute/path/App.xcodeproj \
  --bundle-id com.example.App \
  --run \
  --interaction-command "t 200 400"
```

- `call` 的 `--workspace` 只在工具 schema 支持 `workspaceIdentifier` 时注入。
- 项目绝对路径会先通过 `XcodeOpenWorkspace` 解析为当前 `workspace-*` 标识，兼容 headless 调用。
- `device-state` 使用唯一会话名，不输出会话密钥，并在 `finally` 中调用 `DeviceInteractionEndSession`。
- `device-state` 不加 `--run` 时只捕获当前状态；`NotRun` 是合法结果，不代表桥接失败。
- `--interaction-command` 可执行点击、滑动、输入等操作；坐标应依据最新 UI 层级，不要只凭截图猜测。
- 普通工具错误以 JSON 输出并返回退出码 `2`；协议、参数或启动错误返回 `1`。

## 完整工具目录

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
| `XcodeListTemplates` | 查询 Xcode 项目和 Target 模板及选项 |
| `XcodeNewProject` | 从模板创建新项目 |
| `XcodeNewTarget` | 从模板添加新 Target |

### 项目文件与构建配置（14）

| 工具 | 用途 |
|---|---|
| `XcodeLS` | 列出项目导航器中的文件和目录 |
| `XcodeGlob` | 按通配符查找项目文件 |
| `XcodeGrep` | 用正则搜索项目内容 |
| `XcodeRead` | 读取项目文件 |
| `XcodeWrite` | 创建或覆盖项目文件并加入项目结构 |
| `XcodeUpdate` | 替换项目文件中的文本 |
| `XcodeMV` | 移动或重命名项目文件、目录 |
| `XcodeMakeDir` | 创建目录和项目分组 |
| `XcodeRM` | 移除项目文件，可选删除磁盘文件 |
| `GetFileCompilerFlags` | 读取单文件编译参数 |
| `UpdateFileCompilerFlags` | 修改、追加或删除单文件编译参数 |
| `AddInfoPlist` | 添加或修改 Target 的 Info.plist 项 |
| `AddEntitlement` | 添加必要的代码签名 Entitlement |
| `XcodeRefreshCodeIssuesInFile` | 获取文件的编译诊断；需要 Xcode 提供对应诊断服务 |

### 构建、运行、调试与 Preview（7）

| 工具 | 用途 |
|---|---|
| `BuildProject` | 构建当前项目并等待完成 |
| `GetBuildLog` | 查询构建日志，支持级别、正则和文件过滤 |
| `RunProject` | 构建并运行当前 Scheme，可附加调试器 |
| `StopProject` | 停止当前运行的 App |
| `InvokeDebuggerCommand` | 向活动 LLDB 会话发送 `bt`、`po`、`continue` 等命令 |
| `RunCodeSnippet` | 在指定 Swift 文件上下文中编译运行代码片段 |
| `RenderPreview` | 构建并渲染 SwiftUI Preview，返回快照及可用变体 |

`RunProject(attachDebugger=true)` 返回后，LLDB 可能仍在异步附加；若立即收到 `No active debug session`，请稍等再查询，不要误报为桥接失败。

### 模拟器、真机交互与控制台（6）

| 工具 | 用途 |
|---|---|
| `DeviceInteractionStartSession` | 无工作区的设备会话，用于运行时交互 |
| `DeviceInteractionStartWorkspaceSession` | 绑定工作区的设备会话，可构建、安装、运行 |
| `DeviceInteractionInstallAndRun` | 构建、安装并启动当前 App |
| `DeviceInteractionSynthesize` | 点击、滑动、输入、硬件按钮、旋转，并捕获截图、UI 层级和日志 |
| `DeviceInteractionEndSession` | 关闭设备会话，释放资源 |
| `GetConsoleOutput` | 获取 stdout、stderr 和 OSLog，支持过滤和上下文 |

推荐运行顺序：`XcodeOpenWorkspace（如需要） → XcodeListRunDestinations → BuildProject → DeviceInteractionStartWorkspaceSession → DeviceInteractionInstallAndRun → DeviceInteractionSynthesize/GetConsoleOutput → DeviceInteractionEndSession`。

### 测试与 Test Plan（5）

| 工具 | 用途 |
|---|---|
| `XcodeListTestPlans` | 列出 Test Plan 及当前活动项 |
| `XcodeSwitchTestPlan` | 切换活动 Test Plan |
| `GetTestList` | 获取可运行测试及 Target/Test Identifier |
| `RunAllTests` | 运行活动 Test Plan 的全部测试 |
| `RunSomeTests` | 按 Target 和 Test Identifier 运行指定测试 |

项目没有测试 Target 或活动 Test Plan 时，相关工具可能返回“没有测试”，这不表示 MCP 连接失败。

### Apple 文档与本地化（5）

| 工具 | 用途 |
|---|---|
| `DocumentationSearch` | 语义搜索 Apple Developer 文档，可按 Framework 限定 |
| `LocalizationPlanner` | 准备项目以添加语言或执行项目翻译 |
| `StringCatalogContext` | 读取 String Catalog 键的上下文和源语言值 |
| `StringCatalogRead` | 按翻译状态读取 String Catalog 键 |
| `StringCatalogEdit` | 写入翻译、变体和复数形式 |

本地化工具具有工具描述中的前置要求：在 Agent 中使用时，应先加载对应的 `xcode-integration:translation-coordinator` 或 `xcode-integration:translation` 指令；本仓库不伪造这些技能。

### 崩溃与性能诊断（4）

| 工具 | 用途 |
|---|---|
| `GetTopCrashIssues` | 获取近 14 天的主要崩溃签名 |
| `GetCrashIssueLogs` | 获取指定崩溃签名的日志与诊断建议 |
| `GetTopFieldPerformanceIssues` | 查询启动、卡顿、磁盘写入、能耗等现场性能问题 |
| `GetFieldPerformanceIssueLogs` | 获取指定性能问题的详细日志和分析 |

这些工具依赖 App 的 Bundle ID、版本、平台、Apple 报表权限和可用数据。无权限或无数据时的错误会原样返回。

## 安全边界

- 不自动启用 Xcode MCP，不执行 sudo，不设置“允许所有 Agent”。
- 首次使用只授权 `dsh-mcp-client / DeepSeek Harness` 与必要工作区。
- `XcodeWrite`、`XcodeUpdate`、`XcodeMV`、`XcodeRM`、`XcodeNewProject`、`XcodeNewTarget` 及配置修改工具会改变项目；调用前应明确目标并备份。
- 崩溃、性能和文档工具可能访问 Apple 服务；只发送完成任务所需的查询和标识。
- `device-state` 不记录提示词，不在结果中暴露设备会话密钥。
- 禁用 ACP 注入：设置 `DSH_XCODE_MCP=0`。禁用 DSH 插件会话工具：在插件设置中关闭 **Xcode ACP 集成**，或在启动 DSH 前设置 `DSH_XCODE_MCP=0`。
