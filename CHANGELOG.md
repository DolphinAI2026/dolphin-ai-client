# Changelog

## 2026-03-27

### AI Coding 模块

#### 架构变更
- **去掉 Claude Agent SDK 依赖**：Agent 引擎从 `claude-agent-sdk`（需安装 Claude CLI）重构为 httpx 直调 OpenAI 兼容 `/v1/chat/completions` API，支持 MiniMax / Qwen / DeepSeek 等国内大模型，客户部署零额外依赖。
- **去掉项目概念**：CodingPage 不再有"应用"层级，左侧直接展示工作区列表，用户发消息即自动创建工作区，简化操作流程。
- **LLM 模型前台配置**：管理员可在「环境管理 → 模型配置」页面配置接入的模型供应商、API 地址、Key 和参数，无需修改 .env 文件。

#### Agent Loop 优化（参考 Claude Agent SDK 模式）
- **流式 SSE Delta 累积**：LLM 响应通过 `stream: true` 流式接收，thinking / tool_calls delta 实时推送前端。
- **智能上下文压缩**：`_compress_context()` 方法在消息超过 10 条后自动截断早期 tool result（保留最近 8 条完整），防止 context 超限。
- **循环检测 + Nudge 注入**：连续 2 轮只读文件不写代码时，自动注入 nudge 消息强制模型立即并行写入所有组件文件。
- **重复读取拦截**：`read_files_set` 追踪已读文件，对重复 `read_file` 调用直接返回缓存提示，不重复消耗 token。
- **自适应 Result 截断**：根据剩余 context 预算（60K chars）动态调整 tool result 最大长度，越接近上限截断越激进。
- **并行 Tool Calls 支持**：通过 `tool_calls` 数组的 `index` 字段正确累积多个并行工具调用。
- **错误健壮性**：新增 `ReadTimeout`、`ConnectError`、API 状态码非 200 等异常处理，避免 Agent 静默失败。
- **优化 System Prompt**：强调"最多 8 轮"、"一次写完所有文件"、"不要反复读文件"，引导模型高效工作。

#### 组件沙箱预览
- **新增 `preview.py` 沙箱生成器**（489 行）：为表单组件、页面组件、移动端组件生成独立预览 HTML，内含 Vue 2 + Element UI CDN + Mock aPaaS SDK 环境。
- **新增 3 个预览 API**：`POST /preview`（触发构建）、`GET /preview/sandbox`（返回沙箱 HTML）、`GET /preview/dist/{filename}`（提供编译后的 UMD 文件）。
- **前端预览面板**：CodingPage 右侧新增可折叠的「组件预览」面板，支持编辑/只读模式切换和刷新。

#### 前端 SSE 渲染
- **轻量流式渲染**：流式阶段不走 markdown 解析，直接用 HTML 转义 + 基本格式化（`**bold**`、`` `code` ``、换行），避免 markdown 渲染器阻塞 UI。
- **`<think>` 标签过滤**：后端和前端双重过滤 MiniMax 的 `<think>...</think>` 输出，防止 HTML 渲染异常。
- **Heartbeat 透传**：SSE heartbeat 事件不再被 Agent 过滤，透传到前端保持连接活跃。

### 智能搭建模块

- 稳定增量更新与预览流程，修复增量执行中的状态同步和错误处理问题。
- 优化 ChatPage 对话页面的状态管理，新建对话时统一重置残留状态。
- 改进配置 diff 展示和 Generate 页面的交互体验。
- 调整数据库连接配置，增强连接池稳定性。
- 完善字段类型映射和配置校验逻辑。

### 通用

- 新增深色/浅色主题切换功能（右上角齿轮图标），支持蓝色主题色。
- 更新阿里云部署文档。

## 2026-03-26

### Changed

- 调整部署流程，暂时隐藏流程相关的前端展示和部署步骤，避免当前流程创建问题影响主链路使用。
- 优化权限组生成逻辑，同一角色的功能权限合并到一个权限组中，减少平台里的重复权限组。
- 修复表单权限 payload 中功能权限组对象字段名错误的问题，将 `PermissionObjects` 统一为平台实际识别的 `permissionObjects`，避免权限对象在平台页面丢失。
- 优化模型创建失败时的兜底处理，遇到“模型名称与数据库关键词重复”时会自动规避关键词后重试。
- 增加表单创建与表单保存相关日志，便于排查 `create_form_config` 与 `save_form_config` 的实际入参。
- 调整增量更新链路的 APaaS 连接选择逻辑，优先使用应用绑定环境/默认环境，修复错误租户上下文导致远端字典、模型等资源查询为空的问题。
- 将增量更新流式执行改为 `POST` 请求体承载配置，并保留 `SSE` 返回，避免大配置通过 query string 触发“连接错误”。
- 兼容文档版本的会话级暂存流程，允许 `document_versions` 先只绑定 `conversation_id`，并仅清理真正同时缺失 `application_id` 与 `conversation_id` 的孤立记录。
- 调整新建对话的前端状态清理逻辑，开启新对话时统一重置概览、模型、表单、权限、文档版本、部署面板、增量更新和变更计划等残留状态。
- 新增“部门选择”标准字段类型，并将表单组件映射为 `FORM_DEPARTMENT_SELECT`，同步更新文档解析、类型校验、配置 schema、组件生成和前端预览/差异展示。
- 隐藏聊天页中的内嵌“平台配置”入口与视图，部署完成后的“查看应用”改为返回应用列表，避免继续进入嵌入式平台页面。
- 优化聊天页与部署页的一键执行状态控制，执行过程中禁用重复点击的执行/重试按钮，避免并发触发相同步骤。
