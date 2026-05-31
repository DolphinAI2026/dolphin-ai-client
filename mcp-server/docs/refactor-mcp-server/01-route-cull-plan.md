# 01 · Route 拆解清单（保留 / 砍 / 半保留）

> 41 个 route 文件逐个判断。判断依据：grep mcp_server.py 里所有 `_api_call`/`_api_call_sse_collect` 实际调用的 internal endpoint，反向推导依赖。

## MCP 工具内部 endpoint 依赖（16 个）

```
POST /applications/auto-create
POST /applications/upload-doc
POST /applications/{...}/upload-doc-version
POST /applications/{...}/publish
POST /applications/{...}/grant-access
POST /applications/{...}/change-plans/{...}/execute
GET  /applications/page
GET  /applications/{...}
GET  /applications/{...}/spec-markdown
GET  /applications/{...}/generate
GET  /applications/{...}/change-plans/{...}
POST /coding/workspace/create
POST /coding/workspace/{...}/file
POST /coding/workspace/{...}/upload-to-platform
GET  /coding/workspace/{...}
POST /platform-envs/{...}/login
```

## 三类标签

- **✅ KEEP**：MCP 工具直接依赖，或 admin SPA 用，必须保留
- **❌ CULL**：纯 user-facing UI 后端，无 MCP 依赖，删除
- **⚠️ TRIM**：route 文件保留但内部砍掉 user-facing endpoint，只留 MCP / admin 需要的

## 41 个 route 文件分类表

| File | 标签 | 依赖来源 | 备注 |
|------|------|---------|------|
| `applications/` (整个目录) | ✅ KEEP | MCP 8 个工具调 | 含 auto-create / upload-doc / publish / generate SSE / change-plans 等所有 endpoint |
| `coding.py` | ✅ KEEP | MCP 4 个工具调 (publish_dev_workspace / create_dev_workspace / write_workspace_files / etc) | workspace CRUD + upload-to-platform 都在这 |
| `platform_envs.py` | ✅ KEEP | MCP `_refresh_platform_env_token` 调 `/platform-envs/{}/login` + admin SPA CRUD env | |
| `current_app.py` | ✅ KEEP | mcp slot 反查兜底 + `_resolve_identity` 链路 | set_current_app / get_current_app 内部用 |
| `tenant_dolphin_agents.py` | ✅ KEEP | admin SPA 配 dolphin agent 入口 | 本周新加的 CRUD |
| `auth.py` | ⚠️ TRIM | service token 签发 + admin SPA 登录 + tenant CRUD | **砍**：user register / dolphin SSO mirror / chain apaas 等 user-facing。**留**：admin login / `_sign_service_token` / tenant 管理 endpoint |
| `dolphin_sso.py` | ⚠️ TRIM | `init-app-context` 被 dolphin agent 启动时调？需确认 | **砍**：`/dolphin/config`（dolphin 不再调）+ `embed-auth-token`（前端 SDK 用了）+ `reload-env-config`（admin 可走 CLI）。**留**：`/dolphin/init-app-context` 待确认 dolphin agent 是否仍 trigger |
| `application_members.py` | ⚠️ TRIM | admin SPA 看应用成员可保留 | 看 admin SPA 是否要这个页面 |
| `sandboxes.py` | ✅ KEEP | admin SPA 沙箱监控 + Vibe Coding MCP 工具列沙箱 | |
| `git_connection.py` | ⚠️ TRIM | Vibe Coding MCP `vibe_create_sandbox(git_url)` 可能用 | 砍 user-facing chat 入口；留 Git 凭证 CRUD（Vibe MCP 工具 import git 时用） |
| `git_webhook.py` | ❌ CULL | Vibe Coding push 通知，纯 UI 不要 | dolphin agent 不需要 webhook |
| `platform_proxy.py` | ✅ KEEP | 透明代理 apaas（用户/admin SPA 看 apaas iframe 用） | 砍掉 user-facing 应用 iframe 后用得少，但 admin SPA 可能用 |
| `harness.py` | ⚠️ TRIM | LLM 解析 endpoint，admin SPA 测 LLM 配置可能用 | 砍 user-facing chat；留 admin "测试连接" 类 |
| `llm_configs.py` | ✅ KEEP | admin SPA LLM 配置 CRUD | 必留 |
| `ai_chat.py` | ❌ CULL | 老 AI-Chat 入口（早就废弃） | |
| `chat.py` | ❌ CULL | 老 ChatPage 后端 | |
| `coding_v2.py` | ❌ CULL | 老 CodingPage V2 入口 | |
| `coding_v2_spec.py` | ❌ CULL | 老 CodingPage V2 SPEC 入口 | |
| `app_adjust_chat.py` | ❌ CULL | 应用调整 chat（已并入 Builder agent） | |
| `apaas.py` | ❌ CULL | 老 /apaas/status user-facing 入口 | |
| `conversations.py` | ❌ CULL | 对话历史 user UI | |
| `dashboard.py` | ❌ CULL | 工作台首页 dashboard | |
| `generation_steps.py` | ❌ CULL | 应用生成步骤展示 UI | |
| `help_assistant.py` | ❌ CULL | 内置 AI 助手对话 | |
| `incremental_update.py` | ❌ CULL | 增量更新通知 SSE | |
| `marketplace.py` | ❌ CULL | 应用市场 UI | |
| `online_coding.py` | ❌ CULL | 在线 IDE 嵌入 user UI | |
| `online_coding_runtime.py` | ❌ CULL | IDE 后台 runtime 接入 | |
| `preferences.py` | ❌ CULL | 用户偏好（无 user 不需要） | |
| `projects.py` | ❌ CULL | 项目管理 UI | |
| `proposals.py` | ❌ CULL | 变更提案 UI | |
| `requirements.py` | ❌ CULL | 需求分析助手 user 入口 | |
| `spec.py` | ❌ CULL | SPEC 状态机 user UI | |
| `sse.py` | ❌ CULL | 通用 SSE user 路由 | |
| `templates.py` | ❌ CULL | 模板 UI | |
| `user_coding_session.py` | ❌ CULL | 用户 coding session 映射（dolphin agent 不用） | |
| `vibe_coding_chat.py` | ❌ CULL | Vibe Coding 对话（被 MCP 工具取代） | |
| `voice.py` | ❌ CULL | 语音输入 user 入口 | |
| `work_state.py` | ❌ CULL | 工作状态 user UI | |
| `browser.py` | ❌ CULL | Vibe Coding 浏览器嵌入 user UI | |

## 统计

- **✅ KEEP** (整个保留)：7 个文件
  `applications/` / `coding.py` / `platform_envs.py` / `current_app.py` / `tenant_dolphin_agents.py` / `sandboxes.py` / `llm_configs.py`

- **⚠️ TRIM** (砍内部 user-facing endpoint，保留 admin/MCP 部分)：5 个文件
  `auth.py` / `dolphin_sso.py` / `application_members.py` / `git_connection.py` / `harness.py` / `platform_proxy.py`

- **❌ CULL** (整个删除)：29 个文件

## Phase 2 砍 route 执行步骤

```bash
# 1. 备份：confirm git clean working tree
cd backend/app/routes/
git status

# 2. 整文件删（29 个）
rm -f ai_chat.py chat.py coding_v2.py coding_v2_spec.py app_adjust_chat.py \
      apaas.py conversations.py dashboard.py generation_steps.py help_assistant.py \
      incremental_update.py marketplace.py online_coding.py online_coding_runtime.py \
      preferences.py projects.py proposals.py requirements.py spec.py sse.py \
      templates.py user_coding_session.py vibe_coding_chat.py voice.py work_state.py \
      browser.py git_webhook.py

# 3. main.py 同步删 import + include_router 行
#    sed -i '/from app.routes import/,/^)/{/ai_chat,/d; /chat,/d; ...}' main.py
#    （手工编辑更稳）

# 4. 删 frontend 整个目录（用不上）
rm -rf frontend/
# admin SPA 是新建的 admin-spa/，不复用现有 frontend

# 5. TRIM 文件内部砍：auth.py / dolphin_sso.py / 等
#    需要逐文件 review，砍 user-facing endpoint，保留 admin / MCP service token 部分

# 6. 跑测试 + 起 backend 验证 49 MCP 工具能拉
#    curl -X POST http://localhost:8003/api/mcp/mcp -H "Authorization: Bearer $TOKEN" \
#      -H "Accept: application/json,text/event-stream" \
#      -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## TRIM 文件具体砍点

### `auth.py`

**留**：
- `_sign_service_token` 用于 MCP middleware
- `POST /api/auth/login` 改名 `POST /api/auth/admin-login`（仅 admin 用）
- `GET /api/auth/me` 改限 admin
- `/api/auth/tenants` 系列 CRUD（admin SPA 用）
- `/api/auth/tenant-roles` 角色查询（admin SPA 用）
- `/api/auth/tenant-users` 平台用户管理（admin SPA 用）
- `_McpAuthMiddleware` （JWT 解析中间件，MCP 入口用）

**砍**：
- `POST /api/auth/register` 用户注册
- `POST /api/auth/select-tenant` 切租户（多租户从 dolphin 透传）
- `POST /api/auth/exchange-apaas-token` apaas 身份链
- `POST /api/auth/chain-apaas` apaas 自动 chain
- `POST /api/auth/logout` 用户登出
- `POST /api/auth/change-password` 改密码
- `GET /api/auth/available-tenants` 我能进的租户（user-facing）

### `dolphin_sso.py`

**留**：
- `init-app-context` 如果 dolphin agent 启动时还要调
- `_resolve_dolphin_agent_db_id` / `_ensure_dolphin_project` / `_inject_ctx_and_get_session_id` 等 helper

**砍**：
- `GET /api/dolphin/config` — dolphin 不调
- `GET /api/dolphin/embed-auth-token` — 前端 SDK 用，前端没了
- `POST /api/dolphin/reload-env-config` — admin 可走 CLI

### `git_connection.py`

**留**：
- Git 凭证 CRUD（Vibe MCP 工具 import git 时用）

**砍**：
- Git 对话相关 endpoint

### `application_members.py`

**留**（admin SPA 可能要）：
- `GET /applications/{id}/members` 列成员
- `POST /applications/{id}/members` 加成员
- `DELETE /applications/{id}/members/{user_id}` 删

**砍**（user-facing）：
- 用户自己请求加入应用等流程

### `platform_proxy.py`

**留**：完整保留（admin SPA 看 apaas iframe + Vibe Coding 沙箱浏览器代理用）

**砍**：可不动，全保留

### `harness.py`

**留**：
- `POST /api/harness/test-llm-config` admin SPA 测 LLM 配置用
- LLM resolver 内部 helper

**砍**：
- user-facing chat completion endpoint

## main.py 同步改造

```python
# 原 main.py 30+ 个 include_router → 砍到 ~10 个
from app.routes import (
    applications,
    auth,                       # TRIM
    coding,
    current_app,
    dolphin_sso,                # TRIM
    git_connection,             # TRIM
    harness,                    # TRIM
    llm_configs,
    platform_envs,
    platform_proxy,
    sandboxes,
    tenant_dolphin_agents,
    application_members,        # TRIM
)
# 删 22+ 个 import
```

```python
# 路由注册同步删
app.include_router(applications.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(coding.router, prefix="/api")
# ... 14 个左右
```

## Phase 2 完成验收

- [ ] backend 起服务无 ImportError
- [ ] `/api/health` 返 ok
- [ ] `/api/mcp/mcp tools/list` 返 49 工具完整
- [ ] admin 账号 `/api/auth/admin-login` 能登
- [ ] pg 用户在 dolphin agent 实测：list_apaas_apps / deploy_application / publish_dev_workspace 全跑通
- [ ] 启动 health check 输出 4 个 tenant 1:1:1 状态正常
