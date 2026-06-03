# Handoff — AI Coding 入口下线 + 大规模死代码清理 + start-dev 并入 AI Builder

> 日期: 2026-06-03
> 分支: `dev`(已 push 到 `origin/dev`,顶 `0018c1c`;本会话从 `93a6ec6` 之后接手)
> 范围: 前端 UED 收敛(去独立 Coding 入口、自开发资产库直开 IDE、文案收敛、start-dev 并入 AI Builder)+ 后端/前端死代码清理。
> 依据 spec: `docs/ued-optimization-audit-2026-06-03.md` + `docs/code-audit-current-2026-06-03.md`(均为本轮输入,未在本会话改动)。

## TL;DR

两条线:**① 死代码清理**(后端 ~15.7K 行 + 前端 ~158 行)、**② 产品方向落地**——取消独立「AI Coding」产品心智,二次开发并入 AI Builder,自开发资产库点击直接开 IDE。

本会话 9 个 commit(均已 push):

| commit | 内容 | 规模 |
|---|---|---|
| `784c13f` | 删 v2 orchestrator 死栈(brainstorm/verification/iteration + app/spec + coding_v2 路由) | −10,226 |
| `9528d13` | 删 3 孤儿 service + mcp_server 残留 Vibe 死码(import_zip 工具 / 断 online_coding import) | −1,004 |
| `68a37d1` | reachability 死岛(skills/ · preview_runtime/ · 旧 app-executor · 断桥) | −3,284 |
| `e4bd34d` | intra-file 死函数 52 个(dead-symbol + 3 轮传递闭包) | −1,189 |
| `3eafcdd` | 去 AI Coding 一级导航 + 自开发资产库直开 IDE + Coding 文案收敛 + 输入区一致性 | 16 文件 |
| `7d4d436` | 抽共享 `WorkspaceIdeDrawer.vue`,catalog + ProjectOverview.openWorkspace 就地开 IDE | — |
| `be2ef0f` | start-dev 接入 AI Builder 应用上下文(结构化 dispatch,先跑通 1 个) | — |
| `5beb353` | 再接 2 个(ExtensionSectionPanel + ChatPage handoff) | — |
| `0018c1c` | 删 ChatPage 死的 dispatchCodingTask 链 | −158 |

---

## Part 1 — 死代码清理(后端 ~15.7K 行)

方法:**AST reachability**(从 `app.main` + `app.mcp_server` 走导入图;backend/app **零动态 import**,故图完备)+ **dead-symbol**(top-level 未装饰、全仓+tests 零引用)+ **传递闭包**(删→重扫→删新孤儿,直到收敛)。

- `784c13f`: UI 零引用的 v2 编排栈整体退役 —— `coding_v2`/`coding_v2_spec` 路由、`orchestrator/`、`brainstorm/` `verification/` `iteration/` 三 agent、`app/spec/` 包、4 service、`/coding/skills` 死端点(它 import 的 `app.coding.skills_v2` 根本不存在)、2 张孤儿表(`agent_messages`/`verification_reports`)。顺手修 `models/__init__` 补导出 `SpecSection`(治 `test_spec_section_o1` 自 deb75bf 起的 collect 失败)。
- `9528d13`: 孤儿 service `agent_seed`/`design_doc_preflight`(+其唯一测试)/`error_recorder`;mcp_server 删整体死的 `import_zip_to_workspace`(建 `oc_` workspace 走**已删**的 `/online-coding/` 路由 + import 不存在的 `_find_workspace_dir`,运行时必崩)+ `save_dev_spec` 摘 `oc_` Vibe 分支 + 同步 `tool_registry.yaml`/`admin_mcp`。
- `68a37d1`: 死岛 `app/skills/`(旧「原子能力」直建)、`app/coding/preview_runtime/`(Vibe workspace 本地预览)、`app_executor`+`app_config_schema`(旧 config-executor)、`agents/coding/spec_bridge`(桥已删 BrainstormAgent)、`agents/db_trace_writer`、`harness/session_bridge`、`migrate_multi_tenant`。
- `e4bd34d`: 52 个 intra-file 死函数 —— `validate_generated_code` 整子系统(validator.py)、form_component_editor `normalize_widget_config_*` 死簇、step_executor keyword-safe+form-permission 死簇、platform_sync、mcp_server bpmn、schemas 等。

**核验**:全程 `import app.main`+`app.mcp_server` OK;`pytest` 全量 **471 过 / 6 败**,这 6 败在改动前(`68a37d1`)就**完全一致**(stash 对比确认),是本地 SQLite 态预存坏,**非本次引入**。

> ⚠️ 纠正旧记忆口误:`error_recorder`(`AgentErrorRecorder`)**从未被实例化**,`agents/coding/agent.py:390` 那个 `ctx.extra.get("error_recorder")` 恒拿 None → `agent_error_events` 实际无人写。但 `AgentErrorEvent` 模型+FK 仍在,ORM 层照样锁住 `brainstorm_sessions`/`specs`/`coding_sessions` 3 张表,真删表需先做去-FK 的迁移轮。

---

## Part 2 — 去 AI Coding 入口 + 自开发资产库直开 IDE + 文案收敛(`3eafcdd` / `7d4d436`)

产品方向(spec 两文档):**无独立 Coding 导航入口**;二次开发在 AI Builder 内做;自开发资产库点击直接开 IDE。

- **删一级导航**:`RailSidebar` / `GlobalNavRail` / `BuilderCommandPalette` / `ShellTopBar` 标题映射里的 AI Coding 项全删。
- **保留 `/coding` 路由 + `CodingPage`** 作**内部 IDE 宿主**(被 `WorkspaceShell` 内嵌复用),不在导航暴露。
- **共享 IDE 抽屉**:新增 `frontend/src/components/common/WorkspaceIdeDrawer.vue`(全屏 `el-drawer` + `useIdeManager` + `codingApi.getIdeUrl`,命令式 `openWorkspace(wsId)`)。`WorkspaceCatalogPage`(自开发资产库)与 `ProjectOverview.openWorkspace` 都改用它 —— 点工作区**就地全屏开 code-server IDE**(live 实测真打开 `:8080/?folder=…workspaces/…`,顶窗不跳转,关掉回原页),动作文案「进入开发」→「打开 IDE」。
- **文案收敛**(仅可见文案,API/store/路由标识符与 agent prompt 不动):「AI Coding / Vibe Coding / Coding 工作区」→「二次开发 / IDE 工作区 / 自开发资产」,覆盖 ChatPage(tooltip)/CodingPage(标题)/ExtensionSectionPanel/SpecDesignPanel/OnboardingTour/CodingSceneEntry/PlatformTenants/PlatformEnvs/McpHubPage。全局可见仅剩 1 处 JSDoc 注释。
- **输入区一致性**:AIChatPage 模型 chip 边框 `--ac-border-strong→--ac-border`、工具栏 padding `16/24/20→10/16/14` 对齐共享 composer;CodingPage 模型选择器去「·默认」。

---

## Part 3 — start-dev 并入 AI Builder 应用上下文(`be2ef0f` / `5beb353`)

**关键认知**:`AIChatPage`(`/ai-chat`,统一「AI Builder」)的 agent = `builder ∪ coding` 工具,**已能做应用上下文二次开发**(live 实证它调 `get_application` + `list_dev_scenes` + `get_dev_scene_full_workflow` + `create_dev_workspace`)。所以 start-dev 入口应接它,**不是**跳 `/coding`。

**机制 = 结构化 dispatch**(契约,后续铺开沿用):
- **Producer**:`sessionStorage.setItem('ai_builder_pending_app_dev', JSON.stringify({ message, app_id, app_name, ... }))` + `router.push({ path: '/ai-chat', query: { app_dev: '1' } })`。
- **Consumer**:`AIChatPage.vue` onMounted —— `?app_dev=1` 时读该 key → 建会话 + 把 `.message` 当首条消息发出 + 清 sessionStorage(镜像 `CodingPage.maybeConsumeAiBuilderDispatch`)。

**已接 3 个**:`CustomPagePreviewPanel`「去 IDE 改源码」、`ExtensionSectionPanel`「开发自开发包」、`ChatPage` handoff(`handoffToCodingForAppDev` —— 它打包的 app 结构 rich message 原样作为 `.message`)。live 联调验证:触发 → AIChatPage 新建会话、消息发出、agent 真走应用上下文二次开发链路,全程不碰 `/coding`。

- `0018c1c`: handoff 改走 /ai-chat 后,旧 `dispatchCodingTask` 派发链彻底孤儿,连带 6 个只服务它的 helper 全删(−158)。

---

## 仍未做 / 下一步

1. **project 级 start-dev**:`ProjectOverview`「开始开发 / 页面开发」+ `RuntimePage` 仍 `push('/coding')`(文案已收敛)。它们没有具体 app 上下文(project 级 / 泛跳),映射不干净,**需单独定**该去哪(给 project 造 app 上下文?还是进资产库?)。
2. **TabStrip 残留 tab**:老会话 localStorage(`ai-builder-tabs-v1`)里可能留着旧「AI Coding」tab —— 新用户无,可加一次性迁移剪掉。
3. **大 UED 路线(Phase 级,各自单独 spec)**:一级 IA 改名「新建应用 / 应用 / 管理」、`ChatPage` 阶段化拆分、token 单源收敛、首页模板下线、暗色逐页截图验收。

## 🚩 顺手挖出、未处理的(留给后续)

- **`is_valid_api_key`(`backend/app/mcp_server.py:65`)**:docstring 说供 main.py SSE handshake 中间件鉴权,但**全仓零调用** → SSE 握手鉴权疑似没接线 = 潜在安全缺口(呼应 deploy-readiness 的无鉴权阻断)。**建议尽快核实**。
- **`spec_sections.py`(`backend/app/routes/applications/`)**:前端 `SpecDesignPanel.vue` 在调 `/applications/{id}/spec-sections/…`,但该路由**没注册**进 `applications/__init__` —— 要么是注册回退的坏功能,要么连前端那段一起死。design-v4 时(5-27)曾被 wire 过。
- 后端另有零散疑似未接线符号:`resolve_apaas_user_alias` / `append_mcp_call_log` / `DeployRecordDetail`(近期加、零引用)。

## 工程门禁 / 环境 gotchas

- **前端 `npm run build`(vue-tsc)预存坏**:ChatPage 一堆既有类型错,只能 `npm run build:nocheck` 过。本会话所有前端改动均以 build:nocheck 验证(不引入语法/导入错),但**修全量类型门禁是独立大活**(主战场 14k 行 ChatPage)。
- **后端 6 测试败 = 预存**:`test_auth_switch_tenant`(JWT aud)/`test_platform_admin_tenant_context`(create_access_token 旧签名 + 误走真实 aPaaS)/`test_step_executor_model_merge`(query_models fake 契约)—— 都是测试契约问题,非业务回归。
- 本地 DB 是 **SQLite**;改后端必重启 preview backend;`.venv` 是 py3.13。
- preview 中途若浏览器停在 `:8000`(后端)origin,navigate 用**显式 `http://localhost:5173`**,别用 `location.origin`(会落到后端 404)。

## 关键文件 / 机制速查

- 共享 IDE 抽屉:`frontend/src/components/common/WorkspaceIdeDrawer.vue`(命令式 `openWorkspace(wsId)`)。
- start-dev dispatch 契约:key `'ai_builder_pending_app_dev'` + `/ai-chat?app_dev=1`,消费端在 `AIChatPage.vue` onMounted。
- IDE URL:`codingApi.getIdeUrl(wsId)` → `{ ide_url }`(code-server,`:8080`)。
- `/coding` 仍是内部 IDE 宿主路由(CodingPage),被 `WorkspaceShell` 内嵌;`maybeConsumeAiBuilderDispatch`(读旧 key `ai_builder_pending_coding`)现已无 producer,留着无害。
