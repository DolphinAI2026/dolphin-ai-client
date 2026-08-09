# 桌面客户端单 URL 与本地 AI 跨平台技术方案

**文档 ID**：`ARCH-20260809-001-desktop-local-ai-cross-platform`  
**版本**：`1.0`  
**状态**：已确认，进入实现  
**适用工程**：`apaas-builder-ai`  
**目标平台**：Windows、Linux、macOS

## 架构目标与边界

桌面客户端初始化只要求用户输入一个远程服务 URL。该 URL 对应的远程平台负责声明认证、产品能力和服务地址，客户端不能根据域名、端口或路径猜测部署类型。

远程平台是以下对象的唯一事实源：

- 登录、用户、租户、组织和权限；
- Builder、Code 和产品入口；
- 应用、项目、工作区、代码仓库、会话、消息、任务和运行状态；
- 远程模型、MCP、Skill、知识库及应用绑定；
- 远程服务地址、协议版本和能力策略。

桌面端只拥有四类设备侧 AI 资源：本地模型、本地 MCP、本地 Skill、本地知识库。本地资源可以补充远程 Builder 和 Code，但不能创建独立的本地租户、本地应用或本地会话事实。

本地 AI 默认开启；本地 Code 和 Local Runtime 不默认开启。离线时只允许管理和测试本地 AI 资源，不提供独立 Builder 或 Code 工作流。

## 单 URL Discovery 与认证合同

客户端请求：

```text
GET <service-url>/.well-known/dolphin-desktop-bootstrap
```

如果用户填入带部署前缀的地址（例如 `/web-console` 或 `/backend`），客户端在当前路径返回 404 时会自动尝试父级路径；不会根据域名或固定默认地址猜测平台。

响应至少包含：

```json
{
  "schema_version": 1,
  "deployment_id": "deployment-stable-id",
  "platform": {
    "type": "control_plane",
    "name": "Dolphin AI"
  },
  "auth": {
    "provider": "control_plane",
    "login_url": "https://example.com/login",
    "api_base_url": "https://example.com",
    "logout_url": "https://example.com/logout"
  },
  "products": {
    "builder": { "enabled": true, "base_url": "https://example.com/builder" },
    "code": { "enabled": true, "base_url": "https://example.com/code" }
  },
  "remote_capabilities": {
    "models": true,
    "mcp": true,
    "skills": true,
    "knowledge_bases": true
  },
  "local_ai": {
    "enabled": true,
    "allowed_kinds": ["model", "mcp", "skill", "knowledge_base"],
    "bridge_protocol_version": 1
  }
}
```

`platform.type` 支持 `control_plane` 和 `apaas_builder`。`auth.provider` 支持现有远程 `control_plane` 与 `apaas` 认证，不得出现本地账号认证。`auth.login_url` 是浏览器可展示的服务根地址，`auth.api_base_url` 是 sidecar 调用认证接口的地址；aPaaS 常见的 `/backend` 只放在后者。纯 aPaaS Discovery 必须把 Code 标记为禁用。

桌面 sidecar 的旧 `/api/desktop-auth/login` 入口明确返回已过期，不参与桌面认证；桌面登录始终调用 sidecar 的 `/api/auth/login`，再由 `AUTH_PROVIDER` 转发到 Discovery 声明的远程认证服务。

所有绝对 URL 必须是无用户名、无密码、无 fragment 的 HTTP(S) 地址。生产部署要求 HTTPS；开发环境可以显式允许 HTTP。产品地址可以与 discovery 地址同源或跨源，但必须由响应明确声明。

客户端缓存最后一次有效 discovery 快照、ETag 和获取时间。重新发现失败时可以显示旧快照用于诊断，但不得用过期快照签发调用或伪造在线状态。切换 URL 或 `deployment_id` 后，旧登录态、绑定、调用票据和远程缓存全部失效。

## 远程事实源与本地 AI 资源

远程 Builder 和 Code 只显示 discovery 声明为启用的产品。桌面 Code 应用列表、会话历史和新建会话固定读取远程接口，不再使用 `local | remote` 应用来源作为产品模型，也不再提供“新建本地应用”入口。

本地 AI 统一使用资源记录：

```text
LocalAIResource
- resource_id: UUID
- device_id: UUID
- kind: model | mcp | skill | knowledge_base
- name
- revision
- state: ready | disabled | degraded | invalid
- capability_descriptor
- config_ref
- credential_ref
- content_digest
- created_at / updated_at
```

对外标识为：

```text
local-ai://<device-id>/<kind>/<resource-id>@<revision>
```

远程平台只保存资源标识、能力摘要和绑定范围，不保存本地文件路径、命令、Secret 或知识库正文。资源不能按名称跨设备静默替换，也不能在执行时自动漂移 revision。

首阶段复用 sidecar 的本地 SQLite 和现有模型、MCP、Skill、知识库页面，先完成配置边界和入口收敛；后续再把四类表统一投影为 `LocalAIResource` registry。

## 桌面本地 AI Bridge 协议

本地桥只监听 loopback，并由 Tauri 管理。远程服务不能直接访问用户本机端口。

调用链分两类：

1. 远程 WebView 通过 Tauri IPC 或本地 sidecar 调用本地资源；
2. 需要服务端持续编排时，本地桥主动建立到远程平台的出站 WSS。

每次执行必须携带短期、单次使用的 `resource_invocation_ticket`，至少绑定 deployment、device、user、tenant、application、session、resource ID/revision、operation、过期时间和 nonce。

统一流事件支持 accepted、delta、tool call、retrieval、progress、completed、failed、cancelled。实现必须支持取消、超时、背压和明确的断线恢复边界。有副作用的 MCP 工具在断线后不得自动重试。

高风险工具执行前必须在桌面端展示操作、目标和参数摘要并取得本次确认。知识检索按本地出站策略返回正文片段、摘要或仅引用，远程端不能提交任意本地文件路径。

## 资源标识、绑定与选择优先级

资源绑定由远程平台保存，按以下顺序解析：

1. 当前会话显式选择；
2. 应用绑定；
3. 租户绑定；
4. 用户在当前设备的默认资源；
5. 当前设备唯一满足能力要求的启用资源；
6. 无可用资源时返回明确错误。

每次本地执行重新验证调用票据。裸 `application_id`、资源名称或前端传入的本地路径不能成为授权依据。

## 数据、凭据与目录边界

平台默认目录使用各操作系统的应用数据目录，不在首次初始化要求用户选择工作区或 Git 目录：

```text
<app-data>/
├── desktop-config.json
├── app.db
├── ai-resources/
│   ├── skills/
│   ├── knowledge/
│   ├── model-cache/
│   └── mcp-runtime/
├── cache/
│   ├── discovery/
│   └── remote-bindings/
└── logs/
```

Secret 存储策略：

- Windows 使用 Credential Manager；
- macOS 使用 Keychain；
- Linux 使用 Secret Service；
- 系统凭据库不可用时使用设备密钥加密的 vault，设备密钥不得与密文同目录保存。

SQLite 只保存 `credential_ref`。日志禁止记录 Authorization、模型 Key、MCP Secret 环境变量、完整 prompt 和知识库正文。

## Runtime 生命周期

Tauri 启动顺序调整为：

```text
读取桌面配置
  -> 未初始化：显示单 URL 初始化页
  -> 已初始化：启动本地 sidecar
  -> sidecar 健康：打开远程登录或业务页面
```

Local Runtime Manager 不再参与默认启动。sidecar 不接收 `DOLPHIN_LOCAL_RUNTIME_MANAGER_URL`、`DOLPHIN_LOCAL_RUNTIME_MANAGER_TOKEN` 或 `DOLPHIN_AGENT_RUNTIME_PATH`，也不再因为本地 Runtime 不可用而阻断远程 Builder 和 Code。

现有 Local Runtime 模块暂时保留为未来本地 AI 资源进程的按需管理能力，但不能承担本地应用、工作区或会话语义。旧 `starting_runtime` 状态只做读取兼容，新的启动文案统一为“准备桌面服务”。

## Windows Linux macOS 打包

每个平台都原生构建 PyInstaller sidecar，不能跨平台复用二进制：

- Windows：`x86_64-pc-windows-msvc`，产出 NSIS 安装包和 portable ZIP；
- Linux：按宿主 target 产出 AppImage 和 deb；
- macOS：Apple Silicon 或 Intel 原生产出 app 和 dmg，Intel 可在 Apple Silicon 上通过 Rosetta 构建对应 sidecar。

默认打包不再执行 `prepare-local-runtime-appliance-*`，Tauri resources 不再包含 `resources/agent-runtime`。portable 只包含主程序、sidecar 和 Tauri 必需资源。

Windows 子进程使用无窗口启动标志；macOS/Linux 通过 Tauri sidecar 启动，不打开终端窗口。

## 配置迁移与兼容回退

桌面配置升级为 schema v2：

- `discovery_url` 成为用户输入和连接事实；
- 保存最后一次有效 `discovery` 快照；
- `local_ai_enabled` 默认 `true`；
- 旧 `login.base_url` 自动迁移为 `discovery_url`；
- 旧 `login.mode` 只用于迁移，运行时以 discovery 的 `auth.provider` 为准；
- 旧 `workspace_entry_scope` 只保留读取兼容，产品入口以 discovery 的 `products` 为准。

配置写入保持原子替换。升级前保留旧字段一个回滚周期，使旧客户端仍可读取；新客户端不得因 discovery 失败自动回到本地账号、固定域名或 always-on Local Runtime。

如果 discovery 不可用，客户端仍可进入本地 AI 设置和诊断页，但远程产品、应用和会话显示明确离线状态。

## 安全、离线、缓存与升级

discovery、认证和桥接在生产环境必须使用 TLS。设备注册密钥可撤销；调用票据短期且单次使用。MCP 默认最小文件根、最小环境变量和最小网络权限。Skill 导入校验来源、manifest 和 digest。知识库默认最小化出站内容。

registry、桥协议、Skill、MCP、模型和知识索引使用显式版本。升级失败时保留上一 revision；远程绑定不自动切换版本。远程要求的桥版本高于客户端支持版本时返回 `LOCAL_AI_BRIDGE_VERSION_UNSUPPORTED`。

## 实施阶段与文件 Ownership

首阶段目标是建立 discovery/configuration 基线、停止默认 Local Runtime，并让 Builder/Code 入口由远程能力决定。本阶段不实现完整 WSS、调用票据和本地 MCP 执行器。

首阶段文件 ownership：

- `backend/app/routes/desktop_bootstrap.py`：远程 discovery endpoint；
- `backend/app/main.py` 或既有路由注册模块：注册 discovery；
- `src-tauri/src/desktop_discovery.rs`：discovery client、校验和错误映射；
- `src-tauri/src/desktop_config.rs`：schema v2 和 v1 迁移；
- `src-tauri/src/desktop_backend.rs`：sidecar 独立启动和生命周期收敛；
- `src-tauri/src/lib.rs`、`src-tauri/permissions/desktop.toml`：命令与 ACL；
- `frontend/src/utils/desktop/setup.ts`：共享 discovery/config 类型和 invoke 门面；
- `frontend/src/views/DesktopSetupWizard.vue`：单 URL 初始化；
- `frontend/src/views/DesktopSettings.vue`：连接、本地 AI、存储与诊断；
- `frontend/src/stores/mode.ts`、`frontend/src/router/desktopGuard.ts`、`frontend/src/components/v2/RailSidebar.vue`、`frontend/src/api/codeRuntime.ts`：远程产品和远程 Code 事实源；
- `frontend/src/composables/useCapabilitiesHub.ts`：桌面显示本地模型、MCP、Skill、知识库；
- `scripts/build-desktop*.sh`、`scripts/build-desktop-windows.ps1`、`src-tauri/tauri.conf.json`：三平台制品。

回退方式：保留 schema v1 字段读取、旧 phase 枚举和 Local Runtime 模块，但默认启动策略固定为 `on_demand`。出现回归时可以恢复旧 UI 读取，不允许恢复本地账号登录或无条件 Runtime 启动。

## 验证矩阵与验收标准

聚焦验证只覆盖当前变更：

1. Rust `cargo check` 能编译桌面配置、discovery 和生命周期；
2. 前端 `npm run build:desktop` 通过；
3. Python discovery 路由和 sidecar 入口通过语法检查；
4. schema v1 配置可迁移到 v2，URL、平台类型和产品声明非法时被拒绝；
5. 未安装 Local Runtime appliance 时 sidecar 仍能启动并打开远程登录；
6. discovery 只启用 Builder 时不显示 Code，只启用 Code 时不显示 Builder；
7. 桌面 Code 应用和会话不再默认使用本地来源；
8. 本地模型、MCP、Skill、知识库入口在桌面可见，且不会写入远程事实对象；
9. Windows 构建不弹命令行，Linux/macOS 构建不依赖 agent-runtime 资源；
10. Windows NSIS/portable、Linux AppImage/deb、macOS app/dmg 的 bundle 配置正确。

后续阶段再分别验收本地模型流式调用、MCP 审批、知识检索、Skill revision 和远程绑定票据。
