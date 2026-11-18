# Xcode DeepSeek Harness ACP

让支持自定义 ACP Agent 的 Xcode 使用 **DeepSeek Harness** 作为编码助手。支持通过 DeepSeek Harness 插件管理器一键安装、Xcode 原生 MCP 构建运行，也保留命令行安装和 `simctl` 回退方式。

仓库不包含 Xcode 或 DeepSeek Harness 本体，也不包含任何 API Key、账号信息或本地会话。

## 环境要求

- macOS
- 支持自定义 ACP Agent 的 Xcode
- DeepSeek Harness 桌面版，默认安装在 `/Applications/DeepSeek Harness.app`
- Python 3（安装和连接测试均需要，仅使用标准库）

已验证版本：**Xcode 27.1 + DeepSeek Harness 0.2.2-rc.3**。

## 准备模型

先打开 DeepSeek Harness，确认你选择的模型可以正常对话。凭证应通过 DeepSeek Harness 的模型设置或凭证服务配置，不要写入本仓库。插件注册成功只表示 Xcode 已连接 ACP，不代表模型凭证已经配置。

## 方法一：通过 DeepSeek Harness 一键安装（推荐）

1. 打开 DeepSeek Harness 的 **Plugins → Add plugin**。
2. 粘贴以下仓库地址：

   ```text
   https://github.com/cjleay001/xcode-deepseek-harness-acp.git
   ```

3. 安装并启用 **Xcode ACP 集成**。启用时会自动完成 ACP 初始化、启动器安装和 Xcode 注册。
4. 重启 Xcode，打开 **Settings → Intelligence**，在编码助手中选择 **DeepSeek Harness**。

插件不会自动重启 Xcode，也不会读取或修改模型凭证。禁用或移除 DSH 插件不会删除已经写入 Xcode 的外部注册文件，因此 Agent 仍可能在 Xcode 中可用。

## 方法二：命令行安装（备选）

```bash
git clone https://github.com/cjleay001/xcode-deepseek-harness-acp.git
cd xcode-deepseek-harness-acp
./scripts/install.sh
```

两种方式都会：

- 初始化 `~/.dsh/profiles/acp`（如尚未创建）；
- 安装启动器和 stdio 代理到 `~/Library/Developer/Xcode/CodingAssistant/Bin/`；
- 在 Xcode 的 ACP 注册目录添加 `DeepSeek Harness`；
- 使用 `/bin/bash` 解释器启动脚本。

重装会原子更新工具自己的启动器和注册文件；如果原有内容不同，会先在同目录保留带时间戳的备份，不会覆盖备份。

如果 App 安装在其他位置，命令行安装前可将 `DSH_APP_ROOT` 设置为应用的 `Contents` 目录。

## 连接测试

```bash
python3 scripts/test_acp.py
```

测试会完成 ACP 握手、创建独立测试会话并发送一次最小提示词。看到以下结果即成功：

```text
Handshake OK: deepseek-harness-acp
Response: DSH_ACP_OK
ACP smoke test passed.
```

测试使用当前 ACP 模型，会产生一次少量模型调用。测试会话仅保存在用户本地 DSH 存储中，不写入仓库。可用 `DSH_ACP_WORKSPACE` 指定测试工作区，或用 `DSH_ACP_LAUNCHER` 指定其他启动器。为避免基础测试受 Xcode 授权影响，测试脚本默认设置 `DSH_XCODE_MCP=0`；需要验证自动注入时可显式改为 `auto`。

## 模拟器与 Xcode 原生 MCP

默认的 `DSH_XCODE_MCP=auto` 会读取 `xcrun mcp-server status`：**只有 Xcode MCP 已启用时**，启动器中的轻量 stdio 代理才会在 `session/new` 和 `session/resume` 中注入 `xcrun mcpbridge`。工具在首轮模型调用前完成发现，避免全局异步挂载造成的“第一轮没有 Xcode 工具”问题。

### 首次授权

1. 在 **Xcode → Settings → Intelligence → Model Context Protocol** 中允许外部 Agent 使用 Xcode 工具。
2. 第一次让 Agent 打开项目时，Xcode 会请求 Agent 和文件夹访问权限。请仅批准 **dsh-mcp-client / DeepSeek Harness** 与当前项目所在工作区，不要选择“允许所有 Agent”。
3. 可用 `xcrun mcp-server status --format json` 检查状态。代理不会替你启用 MCP、执行 sudo 或修改权限。

### 推荐运行顺序

为避免冷构建超过单次 MCP 工具默认的 60 秒等待时间，先构建，再进入设备交互：

```text
XcodeOpenWorkspace（如需要）
→ XcodeListRunDestinations
→ BuildProject
→ DeviceInteractionStartWorkspaceSession
→ DeviceInteractionInstallAndRun
→ GetConsoleOutput
→ DeviceInteractionEndSession
```

不要在大项目冷构建前直接调用 `DeviceInteractionInstallAndRun`。如果它超时，先单独完成 `BuildProject`，再重试设备交互。该流程已经通过真实 Objective-C App 的构建、安装、启动及控制台读取验证。

### 禁用与回退

- `DSH_XCODE_MCP=0`：禁用注入，保留 `xcodebuild + simctl` 回退。
- `DSH_XCODE_MCP=auto`：默认，按 Xcode MCP 启用状态决定。
- `DSH_XCODE_MCP=1`：仅诊断时强制注入；MCP 未启用或不可用时，会话创建可能失败。

可在 Xcode Agent 的 Environment 中修改该值。代理只转发 JSON-RPC 并在内存中修改会话的 MCP 声明，不记录提示词。

## 模型路由

ACP 默认使用：

```text
provider: deepseek-official
model: deepseek-v4-flash
```

如果该路由没有凭证，可将 `~/.dsh/profiles/acp/cordis.patch.yml` 中的用户配置合并为桌面版正在使用的路由，例如：

```yaml
- id: acp
  name: '@deepseek-ai/dsh-acp'
  config:
    provider: YOUR_PROVIDER_ID
    model: YOUR_MODEL_ID
```

请替换两个占位值，并保留文件中其他已有配置。**不要把 API Key、Token 或 `.credentials.yaml` 放入仓库。**

## 彻底移除

先在 DSH 中禁用或移除插件，再删除以下由安装器生成的文件并重启 Xcode：

```text
~/Library/Developer/Xcode/CodingAssistant/Bin/dsh-acp-launcher.sh
~/Library/Developer/Xcode/CodingAssistant/Bin/dsh_acp_proxy.py
~/Library/Developer/Xcode/CodingAssistant/ACP/D5EAC000-0000-4000-8000-000000000001.plist
```

如果这些文件也由你的命令行安装方式使用，请先确认再删除。安装器生成的 `.backup.*` 文件是本地备份，可按需保留或清理。

## 文件说明

```text
package.json               DSH bundle 清单
cordis.patch.yml           插件注册声明
index.js                   启用插件时执行本地安装
icon.svg                   插件图标
locale/                    中英文插件信息
bin/dsh-acp-launcher.sh    ACP stdio 启动器
bin/dsh_acp_proxy.py       按需注入 Xcode MCP 的转发代理
scripts/install.sh         本地安装与 Xcode 注册
scripts/test_acp.py        无第三方依赖的连接测试
tests/test_proxy.py        代理回归测试
LICENSE                    MIT License
```

## 常见问题

### 插件启用失败

在 **Plugins** 中查看插件的错误详情，确认当前为 macOS、DeepSeek Harness 安装路径正确且 Python 3 可用，然后重新启用插件。未启用成功时，重启 Xcode 也不会完成注册。

### 看不到 Agent

检查 DeepSeek Harness 安装路径，重新启用插件或运行安装器，然后重启 Xcode。

### 提示 `no API key`

说明 ACP 当前模型路由未配置凭证。切换到桌面版已验证可用的 provider/model，而不是把密钥写进脚本。

### 模拟器不是从 Device Hub 启动的

新版在 Xcode MCP 可用时优先使用 `BuildProject` 和 `DeviceInteractionInstallAndRun`，由 Xcode 原生设备流程完成构建和运行，不再只依赖 `simctl`。禁用 MCP 后才会使用 `xcodebuild + simctl` 回退；两种方式与 Device Hub 管理的是同一套 CoreSimulator 设备。

## 隐私与安全

- 命令行安装器运行阶段不需要网络、sudo 或第三方依赖；通过 GitHub 安装插件时，DSH 需要下载仓库。
- DSH 插件激活时会执行仓库内的 `scripts/install.sh`，只写入本文列出的 DSH ACP 和 Xcode 配置位置。
- 脚本不会读取、收集或上传凭证文件。
- 代理仅在内存中转发 ACP JSON-RPC、读取 Xcode MCP 启用状态并注入会话声明，不记录提示词，也不修改授权。
- 测试脚本只在本地通过 ACP 与 DeepSeek Harness 通信；模型请求由用户自己的配置处理。
- 本工具不会自动操作模拟器或修改项目；这些行为只发生在你明确交给 Agent 的任务中。

## License

[MIT](LICENSE)
