# 后端功能与能力地图（部署就绪评审）

> 文档版本：2026-05-30  
> 范围：`backend/app/`（FastAPI 后端，约 20 万行）  
> 状态：只读审查，未修改任何源码

---

## 概览

`apaas-builder-ai` 后端是得帆云低代码平台（aPaaS）的 AI 搭建助手服务。核心职责：

1. 管理 AI 对话、生成管线，驱动 apaas 应用从文档到上线全链路
2. 通过内嵌 MCP Server 向外部 agent 平台（Dolphin）暴露 111 个工具
3. 反向代理得帆云平台（iframe SSO）
4. 提供 Vibe Coding（自开发工作区）的全套 workspace 管理

框架：FastAPI + SQLAlchemy (async MySQL) + FastMCP  
进程：单进程，uvicorn 启动，MCP server 以 ASGI mount 内嵌（不是独立进程）

---

## 一、API 路由能力地图

路由总数：**177 个端点**（含代理路由），注册于 `backend/app/routes/` 下 40+ 子模块。

### 1.1 认证与多租户（`/api/auth`, `/api/apaas`, `/api/mcp-platform`）

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/auth/register` | POST | 本地账号注册 |
| `/api/auth/login` | POST | JWT 登录，返回 access token（HS256，默认 24h） |
| `/api/auth/me` | GET | 当前用户信息 + 租户角色 |
| `/api/auth/select-tenant` | POST | 多租户切换，换发 tenant-scoped token |
| `/api/auth/users` | GET | 租户用户列表（管理员权限） |
| `/api/apaas/login` | POST | 用用户名密码登录 aPaaS 平台换 xdaptoken |
| `/api/apaas/connect` | POST | 用已有 xdaptoken 直接接入 aPaaS |
| `/api/apaas/status` | GET | 查询 aPaaS 平台连接状态 |
| `/api/mcp-platform/*` | CRUD | 管理 aPaaS 平台管理员账号（RSA 加密密码，自动获取/刷新 token） |

**租户隔离**：JWT payload 带 `sub`（user_id）+ `tid`（tenant_id）+ `apaas_sub` + `apaas_tid`，全部路由通过 `AuthContext` 依赖注入强制校验。

---

### 1.2 对话管理（`/api/conversations`）

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/conversations` | GET | 列对话（按租户隔离） |
| `/api/conversations` | POST | 新建对话，支持 `agent_type`：builder / requirements / coding |
| `/api/conversations/{id}` | GET | 获取对话详情 |
| `/api/conversations/{id}/messages` | GET | 获取消息列表 |
| `/api/conversations/{id}/agent-type` | PATCH | 切换 agent 类型 |
| `/api/conversations/{id}/model` | PATCH | 切换 LLM 配置 |
| `/api/conversations/with-apps/list` | GET | 带关联应用信息的对话列表 |

---

### 1.3 聊天与生成（`/api/chat`, `/api/sse`, `/api/ai-chat`）

#### 主对话（ChatPage `/api/chat`）

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/chat/send` | POST | 发消息，SSE 流式返回，触发 SpecAgent 或 ConfigAgent |
| `/api/chat/send-with-file` | POST | 带附件发消息（上传 PDF/Word/Excel 等，自动解析） |
| `/api/chat/generate-config` | POST | 从对话内容生成应用配置 |

#### AI Chat（独立 agent 对话 `/api/ai-chat`）

新型 agentic 对话模式，工具调用自主循环：

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/ai-chat/sessions` | GET/POST | 列会话 / 创建（支持 mode: chat/cowork） |
| `/api/ai-chat/sessions/{id}` | GET/PATCH | 详情 / 更新标题 |
| `/api/ai-chat/sessions/{id}/upload` | POST | 上传附件（PDF/Word/Excel/图片，自动解析） |
| `/api/ai-chat/sessions/{id}/send` | POST | 发消息，SSE 流式 agent loop（含 tool_calls） |
| `/api/ai-chat/sessions/{id}/abort` | POST | 中断当前 agent loop |
| `/api/ai-chat/sessions/{id}/artifacts` | GET | 列产出物（设计文档 md） |
| `/api/ai-chat/sessions/{id}/artifacts/{filename}` | GET | 获取产出物内容 |

AI Chat 内置 6 个工具：`read_attachment` / `run_python` / `write_artifact` / `create_artifact_from_attachment` / `ask_clarifying_question` / `export_apaas_app_design_doc`

#### SSE 事件流（`/api/sse`）

| 端点 | 方法 | 作用 |
|------|------|------|
| `/api/sse/conversation/{id}` | GET | SSE 订阅（agent 事件实时推送，断线重连支持 last_seen_seq） |

---

### 1.4 应用管理（`/api/applications`）

核心业务域，子路由文件 14 个：

| 端点分组 | 关键端点 | 作用 |
|----------|----------|------|
| 基本 CRUD | `GET/POST /api/applications` | 列应用 / 新建（按租户隔离，RBAC） |
| | `GET/PUT/DELETE /api/applications/{id}` | 详情 / 更新 / 删除 |
| | `/api/applications/auto-create` | 根据对话自动创建应用（防重试 dedup） |
| | `/api/applications/import-from-platform` | 从 aPaaS 平台导入已有应用 |
| | `/api/applications/upload-doc` | 上传设计文档（md/docx/pdf）→ 解析配置 |
| | `/api/applications/upload-doc-with-conversation` | 带对话 ID 上传设计文档 |
| 生成与发布 | `GET /api/applications/{id}/generate` | 触发 SSE 全量生成到 aPaaS（同步进度推送） |
| | `POST /api/applications/{id}/publish` | 发布应用到 aPaaS 平台 |
| | `GET /api/applications/{id}/steps/status` | 查询分步生成状态（各步骤进度） |
| | `POST /api/applications/{id}/steps/execute` | 执行单个生成步骤 |
| | `POST /api/applications/{id}/steps/reset` | 重置步骤状态 |
| 文档版本 | `GET /api/applications/{id}/doc-versions` | 列设计文档历史版本 |
| | `DELETE /api/applications/{id}/doc-versions/{vid}` | 删除版本 |
| | `POST /api/applications/{id}/upload-doc-version` | 上传新版本文档 |
| 增量更新 | `GET/PUT /api/applications/{id}/change-plans/{pid}` | 变更计划详情 / 执行 / 选择 |
| | `POST /api/applications/{id}/resolve-conflict` | 解决配置冲突 |
| 配置助手 | `POST /api/applications/{id}/config-chat-stream` | 配置助手 SSE 流（ConfigAssistant） |
| 日志 | `GET /api/applications/{id}/api-logs` | aPaaS API 调用日志（调试用） |
| 部署历史 | `GET /api/applications/{id}/deploy-records` | 分页部署记录 |
| | `POST /api/applications/{id}/rollback` | 回滚到历史版本 |
| 业务事件 | `GET/POST /api/applications/{id}/business-events` | 列 / 创建业务事件 |
| 工作状态 | `GET /api/applications/{id}/work-state` | 聚合 BFF（Spec+Git+成员+操作模式） |
| 平台代码 | `PATCH /api/applications/{id}/code` | 修改应用编码 |
| | `PATCH /api/applications/{id}/platform-config` | 更新平台配置映射 |

---

### 1.5 智能开发 Vibe Coding（`/api/coding`）

工作区全生命周期管理，约 50 个端点：

| 功能分组 | 关键端点 | 作用 |
|----------|----------|------|
| 生成 | `POST /api/coding/generate-stream` | SSE 流式代码生成 |
| | `POST /api/coding/auto-pipeline` | 自动检测场景并运行生成管线 |
| | `POST /api/coding/detect-scene` | 检测代码场景（Spring/Vue/React 等） |
| 工作区 | `POST /api/coding/workspace/create` | 创建工作区（host 模式或 docker/k8s） |
| | `GET /api/coding/workspaces` | 列全部工作区 |
| | `GET /api/coding/workspace/{id}` | 工作区详情 |
| | `DELETE /api/coding/workspace/{id}` | 删除工作区 |
| 文件操作 | `GET/POST /api/coding/workspace/{id}/file` | 读写单文件 |
| | `GET /api/coding/workspace/{id}/files` | 列文件 |
| 构建与运行 | `POST /api/coding/workspace/{id}/build` | 构建（npm/mvn） |
| | `POST /api/coding/workspace/{id}/serve` | 启动 dev server |
| | `POST /api/coding/workspace/{id}/install` | 安装依赖 |
| | `POST /api/coding/workspace/{id}/preview` | 触发预览 |
| 浏览器控制 | `GET /api/coding/workspace/{id}/browser/screenshot` | 截图 |
| | `POST /api/coding/workspace/{id}/browser/click` | 点击 |
| | `POST /api/coding/workspace/{id}/browser/navigate` | 导航 |
| | `POST /api/coding/workspace/{id}/browser/type` | 键入文本 |
| | `GET /api/coding/workspace/{id}/browser/status` | 浏览器状态 |
| IDE 集成 | `GET /api/coding/workspace/{id}/ide-url` | 获取 code-server URL（JWT 保护） |
| | `POST /api/coding/workspace/{id}/ide/chat/completions` | IDE 内 AI 补全流 |
| | `POST /api/coding/workspace/{id}/ide/pipeline` | IDE 触发 coding pipeline |
| 发布 | `POST /api/coding/workspace/{id}/upload-to-platform` | 上传到 aPaaS 自开发包 |
| | `POST /api/coding/workspace/{id}/publish` | 发布到平台 |
| 下载 | `GET /api/coding/workspace/{id}/download` | 打包下载 zip |
| 模型/场景 | `GET /api/coding/models` | 可用 LLM 模型列表 |
| | `GET /api/coding/scenes` | 可用开发场景 |
| | `GET /api/coding/skills` | 可用技能 |

---

### 1.6 Coding V2 Orchestrator（`/api/coding/v2`）

基于状态机的新代编 pipeline，分离 HTTP 和 agent 运行：

| 端点 | 作用 |
|------|------|
| `POST /api/coding/v2/conversations` | 发消息（202 立返，agent 后台运行，SSE 订事件） |
| `GET/PUT/DELETE /api/coding/v2/conversations` | 对话 CRUD |
| `GET /api/coding/v2/specs/{id}` | 获取 Spec envelope |
| `POST /api/coding/v2/specs/{id}/confirm` | 用户确认 Spec，触发 SCAFFOLD/GENERATE |
| `POST /api/coding/v2/specs/{id}/refine` | Spec 再优化 |
| `POST /api/coding/v2/specs/{id}/rollback` | 回滚 Spec 版本 |

---

### 1.7 项目管理与协作（`/api/projects`）

| 端点 | 作用 |
|------|------|
| `GET/POST /api/projects` | 列 / 创建项目 |
| `GET/PUT/DELETE /api/projects/{id}` | 项目详情 / 编辑 / 删除 |
| `POST /api/projects/{id}/connect` | 连接到 aPaaS 平台 |
| `GET/POST /api/projects/{id}/members` | 成员管理 |
| `GET /api/projects/{id}/platform-apps` | 列该项目关联的 aPaaS 应用 |
| `GET /api/projects/{id}/workspaces` | 列工作区 |
| `POST/DELETE /api/projects/{id}/git-connection` | 绑定 Git（PAT 模式，支持 GitHub/GitLab） |
| `POST /api/webhooks/git/{provider}` | 接收 Git webhook 推送 |

---

### 1.8 平台环境与代理（`/api/platform-envs`, 反代路由）

| 端点 / 路径 | 作用 |
|-------------|------|
| `GET/POST /api/platform-envs` | 管理 aPaaS 平台环境（多环境支持） |
| `POST /api/platform-envs/{id}/login` | 环境级别登录（换 token） |
| `GET /api/platform-envs/{id}/remote-apps` | 列远端 aPaaS 应用 |
| `POST /api/platform-envs/{id}/test` | 测试连通性 |
| `/api/platform-proxy/init` | 初始化 iframe 代理状态 |
| `/api/platform-proxy/entry` | iframe 入口（SSO token 注入） |
| `/xdap-admin/{path}` | 全量透传 aPaaS xdap-admin API |
| `/xdap-app/{path}` | 全量透传 aPaaS xdap-app API |
| `/xdap-open/{path}` | 全量透传 aPaaS open API |
| `/xdap-plugin/{path}` | 全量透传 aPaaS plugin API |
| `/backend/{path}` | 全量透传 aPaaS backend API（注入 auth headers） |
| `/platform/{path}` | 透传平台静态资源（HTML/JS/CSS，支持 token 注入） |
| `/smartbi/{path}` | 透传 SmartBI 报表平台 |
| `/apaas/{path}` | aPaaS 直通代理 |

---

### 1.9 MCP 服务端点（`/api/mcp`, `/api/mcp-legacy`）

| 路径 | 传输 | 作用 |
|------|------|------|
| `/api/mcp/mcp` | Streamable HTTP (POST) | MCP 工具调用主入口（现代 agent 用） |
| `/api/mcp-legacy/sse` | HTTP+SSE | 老 MCP 客户端兼容 |

认证：`Authorization: Bearer <MCP_API_KEY>` 或 `?api_key=xxx`

---

### 1.10 LLM 配置管理（`/api/llm-configs`）

支持多模型、多 provider（MiniMax / 阿里通义 / DeepSeek / 智谱 / 月之暗面 / OpenAI / Anthropic / Dolphin omnigate）：

| 端点 | 作用 |
|------|------|
| `GET/POST /api/llm-configs` | 列 / 新建模型配置 |
| `PUT/DELETE /api/llm-configs/{id}` | 编辑 / 删除 |
| `POST /api/llm-configs/{id}/test` | 测试连通性 |
| `POST /api/llm-configs/{id}/set-default` | 设为默认 |
| `GET /api/llm-configs/presets` | 预设 provider 列表 |
| `GET /api/llm-configs/options` | 可选模型枚举 |

---

### 1.11 需求分析助手（`/api/requirements`）

外部 agent 通过 MCP 推送设计文档后，前端 ChatPage 通过此域取文档：

| 端点 | 作用 |
|------|------|
| `GET /api/requirements/latest-doc` | 取当前用户最新缓存的设计文档 |
| `POST /api/requirements/sessions` | 新建需求分析会话 |
| `POST /api/requirements/sessions/{id}/chat` | 需求分析对话 |
| `POST /api/requirements/sessions/{id}/generate-doc` | 从需求生成设计文档 |
| `POST /api/requirements/export-md` | 导出 Markdown |

---

### 1.12 其他功能域

| 域 | 关键端点 | 作用 |
|----|----------|------|
| **Harness**（`/api/harness`） | `POST /api/harness/threads` | 统一 thread 抽象，支持 coding profile，对接 BrainstormAgent + CodingAgent |
| | `POST /api/harness/threads/{id}/turns` | 发消息轮次 |
| | `GET /api/harness/threads/{id}/events` | 取事件流 |
| **Spec V2**（`/api/specs-v2`） | `GET /api/specs-v2` | 列设计文档（从 ai_chat_artifacts 表聚合） |
| **快速 DB 导入**（`/api/quick-db`） | `POST /api/quick-db/test-connection` | 测试外部 DB 连接 |
| | `POST /api/quick-db/build-spec` | 从 DB schema 自动生成设计文档 md |
| **DB 连接管理**（`/api/db-connections`） | CRUD | 管理外部数据库连接（当前支持 MySQL） |
| **模板市场**（`/api/templates`, `/api/marketplace`） | CRUD | 应用模板 + 组件市场管理 |
| **行业知识库**（`/api/industry`） | `GET /api/industry/packs` | 行业本体包（制造/HR/供应链等） |
| **语音转文字**（`/api/voice`） | `POST /api/voice/transcribe` | 复用 LLMConfig Whisper API 中转 |
| **配置助手会话**（`/api/applications/{id}/config-chat-sessions`） | CRUD | ConfigAssistant 历史会话持久化 |
| **运行时 V2**（`/api/runtime`） | `GET /api/runtime/pipelines` | Pipeline 运行历史 |
| | `GET /api/runtime/deployments` | 部署历史（含 lazy seed 演示数据） |
| **帮助助手**（`/api/help`） | `POST /api/help/chat` | 内置产品助手（加载 docs/help/*.md 知识库） |
| **Admin MCP 视图**（`/api/admin/mcp`） | `GET /api/admin/mcp/tools` | 代理 v2 MCP Server 工具列表（admin 页面用） |
| **Builder MCP 试调**（`/api/builder/mcp/call`） | `POST` | 代理调用 v2 MCP 工具（admin 试调用） |
| **当前应用状态**（`/api/builder/set-current-app`） | POST | MCP 外部 agent 调用时登记当前用户操作的应用 |

---

## 二、智能体（Agents）

后端运行 3 个核心 Agent + 1 个 SpecAgent，共享 `BaseAgent` 抽象基类（`agents/base.py`）：

| Agent | 文件 | AgentType | 作用 | LLM |
|-------|------|-----------|------|-----|
| **BrainstormAgent** | `agents/brainstorm/agent.py` | `BRAINSTORM` | 从用户需求→反问→产出 Spec 草案；场景识别、多轮澄清、Spec 状态机（UNDERSTAND→CONFIRM） | 租户默认 LLM（通过 `harness/llm_resolver` 动态解析） |
| **CodingAgent** | `agents/coding/agent.py` | `CODING` | 驱动代码生成（Vibe Coding 工作区）：读写文件/运行命令/调 aPaaS 工具；最大 30 轮 | 租户指定 LLM（DeepSeek/Qwen/GPT/Claude，可通过 llm-configs 配置） |
| **VerificationAgent** | `agents/verification/agent.py` | `VERIFICATION` | 对生成结果跑验收标准（AC）检查；读文件/grep 代码/emit_report；最大 20 轮 | 租户默认 LLM |
| **SpecAgent** | `builder_spec/agent.py` | 无 AgentType | 在 ChatPage 对话中驱动 Spec 对象变更（工具调用模式，不走 BaseAgent）；3 个 prompt phase：GATHERING/DRAFTING/REVISION | 租户默认 LLM（per-conversation 可切换） |

### 状态机（Orchestrator Phases）

`orchestrator/coordinator.py` 管理对话 Phase 转移：

```
IDLE → UNDERSTAND → CONFIRM → SCAFFOLD → GENERATE → VERIFY → DONE
                                                              ↓
                                                    ITERATE（用户继续）
```

`orchestrator/driver.py` 驱动每个 phase 的 agent 运行，含自动修复循环（VERIFY 失败→重试 GENERATE，最多 2 次）。

### BrainstormAgent 工具（5 个）

`ask_user` / `detect_scene` / `emit_spec` / `query_marketplace` / `read_workspace_context`

### CodingAgent 工具（按 tool_registry.yaml 分类，约 38 个）

由 `agents/coding/tools.py` 从 tool_registry 动态构建，主要覆盖：工作区文件操作 / aPaaS 平台 CRUD / workspace 命令执行

### VerificationAgent 工具（4 个）

`check_ac` / `emit_report` / `grep_code` / `read_file`

---

## 三、MCP 服务器与工具

### MCP Server 部署方式

内嵌于 FastAPI 进程（`backend/app/mcp_server.py`，8007 行），以 `FastMCP` 实例 mount：

| 路径 | 传输 | 说明 |
|------|------|------|
| `/api/mcp/mcp` | Streamable HTTP | 主入口（现代 MCP 客户端/Dolphin 使用） |
| `/api/mcp-legacy/sse` | HTTP + SSE | 老客户端兼容（Claude Desktop 等） |

认证：`MCP_API_KEYS` 环境变量（逗号分隔，支持多 key）

### 工具总览

**本机 mcp_server.py 注册：111 个 `@mcp.tool()`**  
**tool_registry.yaml 登记：107 个**（4 个差异为新增未同步）

按 category 分类：

| 类别 | 数量 | 代表工具 |
|------|------|----------|
| `introspection`（平台读取） | 17 | `list_apaas_app_models`, `list_apaas_app_dicts`, `get_apaas_app_overview`, `list_apaas_app_menus`, `list_apaas_form_views` |
| `dev_workspace`（Vibe 工作区） | 14 | `create_dev_workspace`, `read_workspace_file`, `write_workspace_files`, `run_workspace_command`, `publish_dev_workspace` |
| `business_event`（业务事件） | 11 | `create_form_event_with_python_code`, `create_time_event_with_python_code`, `save_apaas_business_event`, `list_apaas_business_events` |
| `browser_control`（浏览器操控） | 11 | `browser_snapshot`, `browser_click`, `browser_type`, `browser_navigate`, `browser_screenshot` |
| `doc_pipeline`（文档→应用） | 9 | `parse_design_doc`, `generate_app_from_doc`, `update_app_from_doc`, `validate_apaas_builder_doc`, `submit_design_doc` |
| `update`（平台更新） | 9 | `update_apaas_app_model`, `add_apaas_model_field`, `update_apaas_form_component`, `set_apaas_app_process` |
| `lifecycle`（应用生命周期） | 6 | `deploy_application`, `publish_application`, `rollback_application`, `list_deploy_records` |
| `delete` | 6 | `delete_apaas_app_form`, `delete_apaas_app_menu`, `delete_apaas_business_event` |
| `create`（平台创建） | 5 | `create_apaas_app_roles`, `create_apaas_app_dict`, `create_apaas_form_menu` |
| `skill_learning` | 4 | `save_config_skill`, `list_config_skills`, `get_config_skill`, `delete_config_skill` |
| `other` | 8 | `build_apaas_feature_from_spec`, `set_role_resource_permission`, `set_apaas_form_permissions`, `query_apaas_business_data` |
| `configure` | 3 | `enable_apaas_self_dev_config`, `list_apaas_app_dev_kits`, `attach_dev_packages_to_apaas_app` |
| `dev_scene` | 3 | `list_dev_scenes`, `get_dev_scene_spec`, `get_dev_scene_full_workflow` |
| `process`（流程） | 1 | `set_apaas_app_process` |

按 agent 白名单分配：

| Agent | 可用工具数 |
|-------|-----------|
| `config`（ConfigAssistant） | 78 |
| `builder`（Dolphin Builder Agent） | 47 |
| `coding`（Dolphin Coding Agent） | 38 |
| `vibe`（Vibe Agent，暂未分配） | 0 |

---

## 四、核心生成管线

### 4.1 主链路：对话→设计文档→aPaaS 应用

```
用户上传设计文档 (md/docx/pdf)
         ↓
   doc_parser.py / doc_pipeline.py
   (文档解析 + 章节识别 + 标准化)
         ↓
   Application.config (JSON，存 MySQL)
         ↓
   generator_v2.py::run_complete_generation()
   Phase 0: 解析配置
   Phase 1: 创建角色 + 数据字典 (step_executor.execute_create_roles_dicts)
   Phase 2: 创建数据模型 (step_executor.execute_create_model)
   Phase 3: 创建表单 + 绑定字典 (step_executor.execute_create_form)
   Phase 4: 配置权限 (step_executor.execute_configure_permissions)
         ↓
   apaas_client.py (httpx → aPaaS REST API)
         ↓
   aPaaS 平台应用上线
```

### 4.2 分步执行（`generation_steps.py` 路由）

- `GET /steps/status`：渲染每个步骤的状态（pending / running / completed / failed），含进度百分比
- `POST /steps/execute`：用户点某步骤→触发 `step_executor.py` 对应 `execute_*` 函数
- 步骤幂等：已完成步骤可跳过；失败步骤支持单独重试

### 4.3 增量更新（`incremental_executor.py`）

```
config_diff.compute_config_diff()  → ConfigDiff（新增/修改/删除项）
         ↓
IncrementalExecutor.run()          → 按变更类型调 aPaaS API
         ↓  ← 从平台拉当前状态对比 (fetch_remote_data)
ExecutionJournal                   → 每步写日志（成功/跳过/失败）
         ↓
platform_sync.sync_from_platform() → 回写最新平台状态到本地 config
```

### 4.4 Coding V2 Orchestrator 管线

```
POST /api/coding/v2/conversations (用户消息)
         ↓
orchestrator.route_user_message()  → RouteDecision（起 brainstorm / 继续 coding / 迭代）
         ↓
[UNDERSTAND phase] driver.drive_brainstorm()
    BrainstormAgent (工具：ask_user / emit_spec)
    → 产出 Spec 对象（存 DB spec_applied_versions 表）
         ↓
[CONFIRM] 前端展示 Spec，用户确认
         ↓
POST /api/coding/v2/specs/{id}/confirm
    orchestrator.on_spec_confirmed()
         ↓
[SCAFFOLD/GENERATE phase] driver.drive_coding_from_spec()
    CodingAgent (工具：文件操作 + aPaaS CRUD)
         ↓
[VERIFY phase] driver.drive_verification()
    VerificationAgent (工具：check_ac / grep_code)
    → 失败最多重试 2 次
         ↓
[DONE] 完成，用户可继续 ITERATE
```

### 4.5 AI Chat 设计文档管线

```
用户上传附件（PDF/Word/Excel）
         ↓
ai_chat.tools.execute_read_attachment()  → 解析内容（复用 doc_parser）
         ↓
ai_chat.agent.run_agent()               → LLM tool calling loop
    工具: read_attachment / run_python / write_artifact
         ↓
write_artifact()                        → 写 ai_chat_artifacts 表（格式=md）
         ↓
用户选"从此设计文档生成应用"
    ↓
create_artifact_from_attachment() / submit_design_doc (MCP)
    ↓
主生成管线（generator_v2）
```

---

## 五、外部依赖清单（部署必备）

### 5.1 必须（无法启动或核心功能失效）

| 服务 | 用途 | 配置项 | 备注 |
|------|------|--------|------|
| **MySQL 8.x** | 本系统主数据库（用户/应用/对话/MCP 工具调用日志等 30+ 张表） | `DATABASE_URL=mysql+aiomysql://...` | 必须；SQLite 仅开发用 |
| **aPaaS 平台（得帆云）** | 生成应用的目标平台；所有 create/update/deploy 均调其 REST API | `APAAS_BASE_URL` | 每个租户需独立的 xdaptoken；租户来自平台登录响应和用户上下文；需开通 API 权限 |
| **LLM Gateway（主模型）** | 驱动 BrainstormAgent / SpecAgent / ChatPage / AI Chat 的 LLM | `LLM_API_KEY`, `LLM_API_BASE`, `LLM_MODEL`（默认 MiniMax-M2.7） | 也支持 Anthropic SDK（`ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`） |
| **JWT 密钥** | 所有 API 认证 + ide_access token 签发 | `JWT_SECRET_KEY` | 多实例部署须共享同一 key |
| **Fernet 加密密钥** | aPaaS 平台密码、PAT、DB 密码等 at-rest 加密 | `ENCRYPTION_KEY`（32 字节 Fernet key） | 丢失则所有加密凭据不可解密 |
| **MCP API Keys** | MCP Server 认证，外部 agent 必须持有 | `MCP_API_KEYS`（逗号分隔，多 key 兼容） | 空则 MCP 端点全 401 |

### 5.2 按功能选配

| 服务 | 用途 | 配置项 | 缺失影响 |
|------|------|--------|----------|
| **Dolphin omnigate LLM 网关** | 提供 GPT-5.5 / Claude Sonnet 等模型（OpenAI 兼容） | `DOLPHIN_BASE_URL`, `DOLPHIN_API_KEY`, `DOLPHIN_MODEL` | 缺失则无法使用 Dolphin 模型，不影响其他 provider |
| **CodingAgent LLM（多模型）** | Vibe Coding CodingAgent 可选 6 个模型 | `CODING_MODEL_{DEEPSEEK/QWEN/GPT54/CODEX/SONNET/OPUS}_BASE_URL/API_KEY/MODEL` | 缺失则对应模型不可选 |
| **Code-Server（Web IDE）** | 工作区内嵌 VS Code 界面 | `CODE_SERVER_BASE_URL` | 缺失则 "在 IDE 中打开" 按钮无效 |
| **Vibe Coding 沙箱** | 代码工作区容器运行时 | `VIBE_CODING_RUNTIME=auto/docker/host`，`APAAS_WORKSPACE_ROOT` | 缺失或 fallback=host 则工作区文件直接在宿主机 /workspaces/ |
| **apaas-builder-mcp-server（v2 独立服务）** | admin 页面显示 v2 工具列表；Builder/Coding MCP 试调中转 | `MCP_V2_INTERNAL_BASE=http://apaas-builder-mcp-server:8004`, `MCP_V2_HOST` | 缺失则 admin/mcp 页面降级为空，不影响本机 MCP 工具实际可用性 |
| **GitHub / GitLab** | 项目 Git 连接（PAT 模式） | 用户侧配置 PAT | 缺失则 Git 功能不可用 |
| **SmartBI 报表平台** | `/smartbi/*` 透传代理 | 内嵌在 platform_proxy，无独立配置 | 缺失则报表 tab 404 |
| **Browser（Playwright/Chrome Extension）** | Vibe Coding 工作区 headless 浏览器预览；Config 助手 browser 控制工具 | 需宿主机有 Chromium 或 Chrome Extension 连接 | 缺失则 browser_* MCP 工具降级失败 |
| **AI Builder 深链 URL** | 外部 agent 把设计文档推送到 ChatPage 的跳转 URL | `AI_BUILDER_CHAT_DEEPLINK_BASE` | 缺失则 submit_design_doc 工具不下发 deeplink |

### 5.3 完整环境变量参考

```bash
# 必填
DATABASE_URL=mysql+aiomysql://user:pass@host:3306/apaas_builder
JWT_SECRET_KEY=<随机 32+ 字节>
ENCRYPTION_KEY=<Fernet key，32 字节 base64>
LLM_API_KEY=<主 LLM provider key>
LLM_API_BASE=https://api.minimaxi.com/anthropic   # 或其他兼容 Anthropic SDK 的网关
LLM_MODEL=MiniMax-M2.7
MCP_API_KEYS=<key1>,<key2>

# aPaaS 平台（必填）
APAAS_BASE_URL=https://your-apaas.definesys.cn/backend

# 按功能选填
CODE_SERVER_BASE_URL=https://your-ide.example.com
AI_BUILDER_CHAT_DEEPLINK_BASE=https://your-ai-builder.example.com
DOLPHIN_BASE_URL=http://dolphin-omnigate/...
DOLPHIN_API_KEY=<dolphin key>
VIBE_CODING_RUNTIME=auto   # auto / docker / host
APAAS_WORKSPACE_ROOT=/path/to/workspaces
MCP_V2_INTERNAL_BASE=http://apaas-builder-mcp-server:8004
MCP_V2_HOST=agent.dfy.definesys.cn
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_API_KEY=<key>
```

---

## 六、数据库表概览

| 表 | 用途 |
|----|------|
| `users` | 本地账号 |
| `tenants`, `user_tenants`, `roles` | 多租户、角色 |
| `platform_envs` | aPaaS 平台环境（多环境） |
| `apaas_platform_credentials` | 平台管理员账号（加密） |
| `applications` | AI 搭建的应用 |
| `conversations`, `messages` | 对话历史 |
| `document_versions` | 设计文档历史版本 |
| `change_plans` | 增量变更计划 |
| `config_snapshots` | 应用配置快照 |
| `llm_configs` | 租户 LLM 配置 |
| `api_call_logs` | aPaaS API 调用日志 |
| `mcp_call_logs` | MCP 工具调用日志 |
| `ai_chat_sessions`, `ai_chat_messages`, `ai_chat_tool_calls`, `ai_chat_attachments`, `ai_chat_artifacts` | AI Chat 会话 |
| `deploy_records` | 部署历史 + 回滚记录 |
| `projects`, `project_members` | 项目协作 |
| `application_members`, `change_proposals` | 应用级协作 |
| `git_connections` | Git 平台连接（PAT 加密） |
| `db_connections` | 外部数据库连接 |
| `marketplace_components` | 组件市场 |
| `industry_packs` | 行业知识包 |
| `pipeline_runs`, `deployment_history` | 运行时演示数据 |
| `config_chat_sessions`, `config_chat_messages` | 配置助手会话 |
| `spec_applied_versions`, `spec_documents` | Coding V2 Spec 版本 |

---

*文档生成时间：2026-05-30*
