# Handoff · 2026-05-24 晚 session — ConfigAssistant 重构 + 3 Agent 并行 + 整合

> 上接 [handoff-2026-05-24-session-end.md](handoff-2026-05-24-session-end.md) (HEAD `cce2aa8` 早 session).
> 本次 late session HEAD `802d23e` push origin/local/ui-redesign-2026-05-20.
> 11 commits / 27 files / +4134 / -1126.

## TL;DR

下次 session 接手 4 句话：

1. **ConfigAssistantPanel 1207 行单文件大重构** — 拆 5 子组件 + 4 composables (`8df3c83`), 学 super-agents-dev assistant-* 模式 + PointerEvent + setPointerCapture 拖宽 (比老 mousedown 稳, 兼容触屏).
2. **深扫 super-agents-dev (华润电力 Spring Boot AI agent) + 借 4 件能力** — 会话持久化 / 模型切换 / 部署历史回滚 / PointerEvent 拖宽. backend Java 重写 Python, frontend Vue 直接学组件模式.
3. **3 Agent 并行 dispatch + worktree 隔离** — Agent A (sessions+drawer) / Agent B (model dropdown) / Agent C (deploy history+rollback). 30-50 min 并行跑完, 我 cherry-pick 整合 + 解 conflicts (主要 backend `_config_chat_event_stream` + frontend `useConfigChat.ts` 两人各加字段).
4. **补 UX 入口 + MCP 工具** — Apps.vue 卡片菜单加 "📜 部署历史" + ConfigAssistantPanel 顶部加 "🕐 回滚" btn + mcp_server.py 加 `list_deploy_records` + `rollback_application` 让 agent 也能调.

---

## 关键架构 + 决策

### 1. ConfigAssistantPanel 重构 (commit `8df3c83`)

之前 1207 行单文件 (script 275 行 + template 200 行 + CSS 700 行) → 拆 11 文件:

```
frontend/src/components/v2/
├── ConfigAssistantPanel.vue (主容器, 153 → 后续整合后 232 行)
└── config-assistant/
    ├── ConfigAssistantHeader.vue       (35 行 → Agent B 后 223 行 含 model dropdown)
    ├── ConfigAssistantViewport.vue     (93 行)
    ├── ConfigAssistantMessages.vue     (573 行, CSS 大头)
    ├── ConfigAssistantInput.vue        (112 行)
    ├── ConfigAssistantSessionDrawer.vue (443 行, Agent A 新增)
    ├── types.ts (23 行)
    └── composables/
        ├── useConfigChat.ts (161 → 242 行, Agent A+B 后)
        ├── useDynamicExamples.ts (55 行)
        ├── useViewportStream.ts (32 行)
        └── usePanelResize.ts (80 行, PointerEvent)
└── DeployHistoryDrawer.vue (746 行, Agent C 新增)

frontend/src/utils/markdown.ts (26 行, marked + renderMd 抽到 utils)
```

兼容性: props/emit 接口完全保留 (`applicationId` / `appName` / `refresh-iframe`), localStorage key `apaas-config-assistant-width-v1` 不变, ChatPage.vue 不动.

### 2. 学 super-agents-dev 关键模式

**借鉴源**: `/Users/mars/super-agents-dev/` (华润电力 `com.crpower.aiagent` Spring Boot 3 + Java 17 + Spring AI 项目, frontend Vue 3 兼容).

**深扫 + 报告**: views/cui / app-detail/components/assistant-* / home/ai-assistant-sidebar / backend module/ai + module/deploy 等. 后端 Java 不能直接拿, 但**架构 + entity 设计 + UI 模式可借**.

**最终拿来的 4 件**:
| | super 实现 | 我们移植 |
|---|---|---|
| 1 | PointerEvent + setPointerCapture (ai-assistant-sidebar.vue:67-90) | usePanelResize.ts |
| 2 | ChatSession + ChatSessionContent 双表 + 5 CRUD | Agent A |
| 3 | sidebar 内 model selector + refreshModels | Agent B |
| 4 | DeployRecord + 19 deploy endpoints + rollback/application | Agent C |

**不拿的**: chatActJudge / RAG / form-design / wizard (我们 SPEC 对话式更优).

### 3. 3 Agent 并行 dispatch 策略 (重要)

用 `superpowers:dispatching-parallel-agents` skill 策略:

```
Agent A (worktree-agent-ab5c7fe642eb68b35) — base 8df3c83 ✓
Agent B (worktree-agent-acfc8dbdffb954e0b) — base 8df3c83 ✓
Agent C (worktree-agent-a038d3328e5845d95) — base 49230c3 (upstream main 不 8df3c83) ⚠️
```

**Worktree isolation**: 用 `isolation: "worktree"` 让各 agent 独立 git worktree, 不污染主分支. 完成后 cherry-pick.

**冲突管理 (重要经验)**:
- Agent A + B 都改 3 个文件 (routes/applications/__init__.py / api/configChat.ts / useConfigChat.ts) — 都是各加字段, 手 resolve 保留两边. 各加 session_id 和 model_id 字段不互斥.
- Agent C base 跟主分支差 1500+ 行 (Agent C 用了 upstream main 不是 8df3c83), 导致 cherry-pick 时 `applications/__init__.py` 撞 1500 行 conflict — 实际 C 只加 2 行 include_router. 手动找位置插入即可. Apps.vue 5 处冲突段太大, 直接 `git checkout --ours` 跳 C 改动, 后续我手动加 history entry.
- 整合后 vue-tsc + python import 全通过.

**Agent C 错误诊断 — 教训**: Agent C summary 说 "本仓 mcp_server.py 已抽走到 apaas-builder-mcp-server repo", 因此没加 rollback_application MCP 工具. 实际本仓 mcp_server.py 还在, 是 v2 抽到独立 repo, **mcp 双实例并存** (本仓供本机 ai-chat, v2 供 prod dolphin). 后续我手动补 MCP 工具.

### 4. 整合后主容器 ConfigAssistantPanel (commit `644a2f9` + `802d23e`)

顶部 actions 3 个 btn (绝对定位右上):
- ➕ 新对话 → clearMessages
- ☰ 历史对话 → 开 ConfigAssistantSessionDrawer
- 🕐 部署历史/回滚 → 开 DeployHistoryDrawer

useConfigChat 解构多拿:
- sessionId / clearMessages / loadHistory (Agent A)
- modelId opts (Agent B, 主容器 localStorage 持久化 key `apaas-config-assistant-model-v1`)

兼容性: 老用户无 modelId 时 send body 带 `model_id=null`, 后端走 `_resolve_builder_llm_cfg` 默认 (跟老行为完全一致).

### 5. 数据库 3 新表 + 7 endpoint + 2 MCP 工具

**新表**:
- `config_chat_sessions` (7 cols, id/app_id/tenant_id/user_id/title/created_at/updated_at)
- `config_chat_messages` (8 cols, +session_id/role/content/tool_trace_json/change_plan_json/actions_summary_json)
- `deploy_records` (14 cols, +version_label/status/deploy_type/snapshot_artifact_id (FK config_snapshots)/apaas_app_id_before/_after/error_message/event_log_json/completed_at)

**新 endpoints (`/api` 前缀)**:
| Method | Path | Note |
|---|---|---|
| GET | `/applications/{id}/config-chat-sessions` | 列 sessions |
| POST | `/applications/{id}/config-chat-sessions` | 新建 |
| GET | `/config-chat-sessions/{sid}/messages` | 拉历史 |
| DELETE | `/config-chat-sessions/{sid}` | 删 (cascade) |
| PATCH | `/config-chat-sessions/{sid}` | 改 title |
| GET | `/applications/{id}/deploy-records?page&page_size` | 部署历史分页 |
| GET | `/applications/{id}/deploy-records/{rid}` | 单条详情 (含 SPEC snapshot) |
| POST | `/applications/{id}/rollback` body `{to_record_id}` | 回滚 (回写 config_preview, 不直接 re-deploy) |

**新 MCP 工具**:
- `list_deploy_records(app_id, page, page_size)` → 调 `/deploy-records` endpoint
- `rollback_application(app_id, to_record_id)` → 调 `/rollback` endpoint

**改的现有 endpoint**:
- `_config_chat_event_stream` 加 `session_id`(A) + `model_id`(B) body 字段, started SSE event 回 `session_id` + `model` + `provider`, user/assistant message 实时落 `config_chat_messages` 表

---

## 本次 late session 完整 commit 列表 (11)

| # | Commit | 内容 |
|---|---|---|
| 1 | `8df3c83` | refactor(config-assistant): 1207 行单文件 → 5 组件 + 4 composables |
| 2 | `a7e6715` | feat(config-chat): backend 接收 model_id (Agent B) |
| 3 | `da4d65f` | feat(config-chat): Header model selector dropdown (Agent B) |
| 4 | `1eac04c` | feat(config-chat): backend 会话持久化 5 CRUD (Agent A) |
| 5 | `527d85d` | feat(config-chat): frontend session API + SessionDrawer (Agent A) |
| 6 | `9c96689` | feat(deploy-history): backend DeployRecord + 3 endpoint + 回滚 (Agent C) |
| 7 | `846e65a` | feat(deploy-history): publish/generate 落 DeployRecord 全周期 (Agent C) |
| 8 | `5cdff85` | feat(deploy-history): frontend API + DeployHistoryDrawer (Agent C) |
| 9 | `57a6a8c` | feat(deploy-history): Apps.vue/ChatPage 接入 (Agent C) |
| 10 | `644a2f9` | feat(config-assistant): 主容器整合 SessionDrawer + modelId v-model |
| 11 | `802d23e` | feat(deploy-history): 补 UX 入口 + MCP 工具 (list_deploy_records / rollback_application) |

---

## 实测产物 (chrome-devtools mcp 浏览器)

| 路径 | 产物 | 备注 |
|---|---|---|
| `/chat?app_id=13` | session_id=1 in `config_chat_sessions` | "列一下当前应用有哪些角色" → 真返 3 角色 (ops_admin_a/admin/reader) |
| `/chat?app_id=13` | `config_chat_messages` 2 rows | user + assistant 完整落表, preview "...共有 3 个角色..." |
| `/chat?app_id=13` 历史抽屉 | 显示 session 卡片 + 标题/时间/2条/改名/删除 btn | UX 完整 |
| `/chat?app_id=13` 模型 dropdown | 拉 `/llm-configs/options?purpose=builder` → 1 model (gpt-5.5 · 默认) | Header 渲染 OK |
| `/chat?app_id=13` 部署历史 drawer | total=0, "尚无部署记录" 空态 | app 13 在 deploy-history 上线前部署, 表通但无数据 |
| MCP tools/list | `list_deploy_records` + `rollback_application` 注册 | 都 required app_id |

---

## 留尾任务

### P1
- **mcp-server-v2 repo 同步加 `list_deploy_records` + `rollback_application` 2 工具**: 本 repo 已加, prod dolphin 走 v2 还没. 30min.
- **mcp-server-v2 repo 同样的 silent-fail bug audit** (create_apaas_app_roles / create_apaas_app_dict 漏 appId, 本 repo 已修). 30min.
- **触发一次真实 deploy 验 deploy_records 真落记录**: 当前 app 13 deploy-history 上线前部署, deploy_records 空. 新建一个简单应用真 deploy 一次看 record 是否完整 (含 snapshot_artifact_id / event_log_json). 30-60min.
- **update_app_from_doc 也加 artifact_id 强制 schema**: 跟 validate/submit/generate 一致 (本 session 早段已经统一 schema). 30-40min.

### P2
- **回滚后自动 re-deploy 选项**: 当前 rollback endpoint 只回写 config_preview 不直接 re-deploy (避免长 SSE 阻塞). 可加 `auto_redeploy: bool` 参数让前端拿到回滚成功后自动调 deploy_application.
- **config-chat sessions 加 search / pin / tag**: 用户多会话后会找不到, 加搜索 + 置顶常用.
- **DeployHistoryDrawer diff view**: 两条 record 选中后展示 snapshot SPEC diff (要看是不是必要 — 当前 expand 看单条 content 已经够).
- **53 处 .vue 硬编码 hex 改 token**: 老留尾, 没动.

### P3
- **老目录清理** (`dist/` 4/12 老 vite 产物 / `output/` 临时 / `marketplace_store/` 空 / `examples/` 历史 / `docker/` 几乎空). 15-30min.
- **wizard 模式入门入口** (super-agents 借鉴的 4-step app-creator, 我们 Builder 对话已足, 但 wizard 给入门用户可选).

---

## 关键文件路径

### Backend
- `backend/app/models/config_chat.py` — ConfigChatSession + Message (新)
- `backend/app/models/deploy_history.py` — DeployRecord (新)
- `backend/app/routes/config_chat_sessions.py` — sessions 5 CRUD (新)
- `backend/app/routes/applications/deploy_history.py` — deploy-records + rollback (新)
- `backend/app/routes/applications/__init__.py:2218-2226` — ConfigChatReq.model_id + session_id 字段
- `backend/app/routes/applications/__init__.py:2780-2792` — started SSE event 含 model+provider+session_id
- `backend/app/routes/applications/generate.py` — 部署流程加 DeployRecord lifecycle (Agent C 完整改造)
- `backend/app/mcp_server.py:1364-1455` — `list_deploy_records` + `rollback_application` 2 新 MCP 工具
- `backend/app/database.py:42-58` — init_db 加 config_chat + deploy_history import
- `backend/app/main.py` — include_router config_chat_sessions
- `backend/app/ai_chat/agent.py` — 早 session 改的 prompt (Phase 1 删 submit_design_doc)

### Frontend
- `frontend/src/components/v2/ConfigAssistantPanel.vue` (232 行主容器, 整合 3 抽屉 + modelId v-model + 顶部 3 btn)
- `frontend/src/components/v2/config-assistant/` (7 文件子组件 + composables)
- `frontend/src/components/v2/DeployHistoryDrawer.vue` (Agent C, 746 行)
- `frontend/src/api/configChat.ts` (加 sessions CRUD + model_id + session_id 字段)
- `frontend/src/api/application.ts` (加 listDeployRecords + getDeployRecord + rollbackApplication)
- `frontend/src/views/Apps.vue` (卡片菜单加 history entry + DeployHistoryDrawer mount)
- `frontend/src/views/ChatPage.vue` (Agent C 改 builder-md-viewer 加 "部署历史" btn)
- `frontend/src/utils/markdown.ts` (marked + renderMd 抽到 utils)

### Docs
- `docs/handoff-2026-05-24-session-end.md` — 早 session handoff (HEAD cce2aa8)
- `docs/handoff-2026-05-24-late-session.md` — **本文档** (HEAD 802d23e)

---

## ⚠️ 提示下次接手

1. **3 个 worktree branch 还在本地** (`worktree-agent-ab5c7fe642eb68b35` / `acfc8dbdffb954e0b` / `a038d3328e5845d95`) — cherry-pick 已落主分支, 可以删:
   ```bash
   git branch -D worktree-agent-ab5c7fe642eb68b35 worktree-agent-acfc8dbdffb954e0b worktree-agent-a038d3328e5845d95
   git worktree prune
   ```

2. **mcp-server-v2 repo 待同步**: 本 repo 落了 (a) silent-fail bug 修 (roles + dict 加 appId) + (b) 2 个新 MCP 工具 (list_deploy_records / rollback_application). v2 还没. prod dolphin 走 v2 — 这两条不到 v2 不算真上线给 prod 用户.

3. **app_id=13 图书借阅管理系统 不要删** — 含 session_id=1 持久化测试数据 (user 决策保留).

4. **deploy_records 表 empty for app 13** — 它在 deploy-history 上线前部署, 没记录正常. 下次创建新应用部署一次就能验完整 lifecycle.

5. **config-chat agent 现支持模型切换** — 当前只 1 个 LlmConfig (gpt-5.5 · 默认). admin 加更多 LlmConfig (e.g. Claude/DeepSeek/qwen) 后 dropdown 自动拉.

6. **新 7 endpoint + 2 MCP 工具实测 200 OK**, 但 prod deploy 还没跑 — 真在新应用 deploy_application 时建议 SSE log + DB 双查确认 deploy_records 含正确 snapshot_artifact_id.

7. **MCP server 双实例的事实**: 本 repo `backend/app/mcp_server.py` (本机 ai-chat 用) + v2 (k8s prod dolphin 用). 改 MCP 工具时**两边都改才算上线 prod**. Agent C 误以为本仓 mcp 已抽走 — 实际只是 v2 独立, 本仓 mcp 还在.

8. **整合策略 (有用经验)**:
   - 用 worktree 隔离让 agent 独立干活
   - cherry-pick 而非 merge — history 线性
   - 冲突时优先看是不是"各加字段"模式 — 多数情况手保留两边即可
   - Agent base 跟主分支差太多时 cherry-pick 会撞大段 conflict, `git checkout --ours` 跳过那个文件后人工补
   - dispatching skill 强调 "shared state 时不能并行" — 实测本 session 共 2 文件 shared (各加字段), 仍然可并行 + cherry-pick auto-merge 多数 + 少量手 resolve

详 commits: `git log cce2aa8..802d23e --oneline` 看 11 commits 全貌.

[← 早 session handoff](handoff-2026-05-24-session-end.md) | [总 session 21 commits 从 62f7f57 起]
