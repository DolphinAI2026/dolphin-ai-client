# AI Builder 架构加固主计划(统一版)

> **唯一事实源。** 本文合并并取代以下两份:
> - `docs/plans/2026-06-13-bigfile-split-codex-plan.md`(大文件拆分工单 → 已并入本文 Phase 4 / Phase 7,原文件作废)
> - 本文件 2026-06-14 旧版(Codex 加固计划初稿 → 已吸收 + 按下方审计修正)
>
> **依据审计**(证据均带 file:line):
> - `docs/audit-2026-06-13-deadcode-bigfile.md`(死代码 + 大文件)
> - `docs/analysis-2026-06-12-modules-agents-knowledge.md`(模块/agent/知识)
> - 2026-06-14 架构深挖(6 套 agent 循环 + 0-1 生成数据流 + MCP 分发 + 持久化,13 agent 追踪 + 对抗核验全部成立)
>
> **执行方式(给 agent worker):** 必用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans` 逐 Task 实现,一次只做一个 Task。

**目标:** 让 AI Builder 的 应用生成 / 配置 / 自开发 / coding 四条流可靠——先锁域契约,再在不改用户可见行为的前提下收敛重复实现、拆分热点文件。

**架构原则:** aPaaS 持有 租户/应用/权限 数据的唯一真相;AI Builder 持有 助手运行态 / 草稿 / patch / 工作区绑定 / 交付产物 / 部署观测。每步重构先保 API 不破,再引入更严的契约与测试。

**技术栈:** FastAPI, SQLAlchemy, Pydantic, SSE, Vue 3, TypeScript, Vite, Element Plus, pytest, Vitest。

---

## 范围决策(2026-06-14,用户拍板)

- ✅ **纳入主计划**:契约锁定、边界服务、**执行器收敛(H1)**、后端+前端大文件拆分、patch 守卫、事件协议、回归。
- ⏸️ **延后 Phase X(单独多轮会话)**:**6 套 agent 循环 → run_agent 底座收敛(H2)**,含上下文压缩、持久化抽象层、统一 ToolContext、统一 ask_user 语义、agent_run 运行语义统一。原因:工程量最大、风险最高、前端事件契约牵连深,需要主计划先把边界和观测打稳。

---

## 当前问题(Codex 6 条 + 审计补 4 条)

1. **域 ID 未锁定。** `app_id` / `apaas_app_id` / `workspace_id` / `project_id` / `coding_app_id` 在应用/自开发/工作区/会话间混用,历史 bug 多源于把一个当另一个。
2. **agent run 是隐式的。** planning / 调工具 / 等用户 / patch / 生成 / 上传 / 发布 这些态没有建成单一 run 状态机。
3. **工具能力非契约优先。** 工具能 read/write/upload/deploy/republish,但 registry 没把副作用、确认要求、幂等、失败语义讲清。
4. **配置应用与自开发应用流程混杂。** 配置改动 / 应用生成 / 自开发 patch / 工作区上传 / 应用 republish 约束不同。
5. **大文件藏责任。** `ChatPage.vue`(14180) / `CodingPage.vue` / `workspace.py`(4624) / 部分 route 模块太大。
6. **运行真相碎片化。** push 的 commit / 本地 build / 生成的包 / 上传的资产 / 已发布的 aPaaS 应用,是各自独立的真相,无单一状态契约。
7. **★H1 三套生成执行器漂移(审计新增,最高 ROI)。** `generator_v2`(一把梭)/ `step_executor`(分步)/ `incremental_executor`(增量)各有一份 `create_*` 实现(角色/字典/模型/表单/权限),`operations/` 共享层只收口了辅助函数([operations/__init__.py:1-10](backend/app/operations/__init__.py) 自述未收 create_*)。**对抗核验成立**:同一份 config_preview 从 ChatPage(step_executor)还是 AIChatPage(generator_v2)进,结果会不同;`b14a434d` 下拉绑字典 bug 当年只修了 generator_v2 一侧。
8. **★M1 三套回放层并写(审计新增)。** coding 路径同一事件落 2-3 份:`ConversationReplay`(大 JSON blob)+ `ConversationEvent`(db_publisher)+ `HarnessItem`(EventBus),各有独立 seq。
9. **★M4 coding_sessions 半删(审计新增)。** ORM 模型已删,但 [startup_recovery.py](backend/app/startup_recovery.py) + main.py 仍用 raw SQL 读写,schema 无 ORM 真相来源。
10. **★H2 6 套 agent 循环各写各的(审计新增,延后 Phase X)。** run_agent / CodingAgent / SpecAgent / read_query / grounded / (config-chat 已死) 在 MAX_TURNS(25/30/12/8/4)、abort(四套)、retry(只 BaseAgent 有)、观测(只 1/6 接 recorder)上严重漂移。

## Non-Goals

- 不在一个 commit 里重写 `ChatPage.vue` / `CodingPage.vue`。
- 不改 aPaaS 平台 schema。
- 不整体替换 agent prompt。
- 不删 `admin-spa`。
- 不引入新数据库或事件总线。
- 不让 AI Builder 成为低代码 租户/应用/权限 数据的真相源。
- **不在本主计划做 H2 六循环收敛**(留 Phase X)——但本计划的边界服务/事件协议/观测要为它铺路。
- 不要求生成工作区用 Git origin;工作区同步仍走 API。

## 目标域模型

| 对象 | Owner | 含义 |
| --- | --- | --- |
| `Tenant` | aPaaS / AI Builder 影子 | 组织边界 |
| `User` | AI Builder auth | 会话/工作区/管理动作的执行者 |
| `Application` | AI Builder | 本地/影子应用记录 |
| `APaaSApp` | aPaaS | 平台真实低代码应用 |
| `Conversation` | AI Builder | 聊天/coding 讨论历史 |
| `Artifact` | AI Builder | 需求/设计文档/UI 草稿/源码包/生成文件 |
| `Workspace` | AI Builder 本地 FS | 可编辑自开发工作区(带本地 diff 态) |
| `DevAsset` | AI Builder catalog | 自开发页面/组件/后端包资产 |
| `Deployment` | AI Builder 观测 + aPaaS 动作 | 上传/发布/republish 尝试及当前已知结果 |

ID 规则:
- `app_id`:AI Builder 应用主键。
- `apaas_app_id`:aPaaS 平台应用 ID。
- `workspace_id`:AI Builder 可编辑工作区 ID,常映射本地目录。
- `project_id`:**禁止当统一概念**,每条路径里要标明它指 app 绑定还是协作 project。
- `coding_app_id`:coding/自开发绑定的兼容句柄;先在 `workspace_binding_service` 后面归一,再扩大使用。

**审计对 Reviewer Questions 的结论(已并入设计):**
- **DevAsset 一等公民**,app 绑定可选(WorkspaceCatalogPage 同时处理已绑/未绑资产);`Application→…→DevAsset` 链只对"已绑定"成立,DevAsset 不强依赖 Application。
- `coding_app_id` 本计划**只收口不迁 schema**(schema 迁移是 Non-Goal),归一在 workspace_binding_service 后。
- **写 aPaaS 的工具**:`create_*/update_*/configure_permissions` 写 aPaaS;deploy/publish/republish **必须确认**,细粒度字段 update 可不确认(由 tool_contract 编码)。
- **"大改写"阈值**:整包/整文件替换、或单文件改动行占比 >50%、或触及 >N 文件 → 触发确认(用 harness 现有红绿 diff 的改动行比做主信号)。
- **发布状态**:AI Builder 自己的观测(build/upload)可缓存;aPaaS publish 态 live 拉或短 TTL,**绝不信缓存的"已发布"**。
- **事件协议稳定性**:replay 格式(chat-replay)是 IDE 侧契约,锁成稳定 API;live SSE 事件名前端内部,typed 但可演进。

## 后端边界服务(小服务,不长 route 文件)

- `services/application_context_service.py` — **由现有 [ai_chat/app_context.py](backend/app/ai_chat/app_context.py) 提升扩展,非新建**(H3)。解析 app/tenant/aPaaS app/当前用户/活动环境,"我在改哪个应用"的唯一来源。
- `services/workspace_binding_service.py` — **吸收 Codex 已建的 [workspace_access.py](backend/app/coding/workspace_access.py)**。解析 `app_id↔workspace_id↔dev_asset_id↔project_id/coding_app_id`,app 绑定工作区访问检查的唯一处。
- `services/deployment_status_service.py` — build/upload/deploy/republish 真相分离,"是否真发布了"的唯一检查。
- `services/tool_contract_service.py` — **只读 yaml 派生,副作用字段进 [tool_registry.yaml](backend/tool_registry.yaml)**(M2),不另立事实源。

> Phase X 才建 `agent_run_service`(运行语义统一,与六循环收敛同期)。本计划只在 deployment/run 状态上够用即可。

## 前端边界(后端契约稳了再做)

- `ChatPage.vue` / `CodingPage.vue` 保持页面壳;面板/对话/diff/进度移到 components/composables。
- `components/chat/*`、`components/workspace/*` 继续抽。
- `types/agent-events.ts`:后端事件契约(M1 收敛后)稳定再引入 typed 协议。

---

# Phases

## Phase 0 — 清场建基线 ✅(大部分已完成)

- [x] 死代码删除:前端孤儿 ~2900 + incremental 链 + 后端孤儿 ~570 + 后端死符号 ~1430(净删 5908 行,5 commit 已落 dev,见 audit doc)。
- [ ] **落定 Codex 在途重构**:`mcp_tools/` 拆包 + `deploy_service.py` + `workspace_access.py` 当前仍未提交(`git status`:`M mcp_server.py` / `?? mcp_tools/` / `?? deploy_service.py` / `?? workspace_access.py`)。需 Codex 收尾自验后提交,或我方代提交。
- **基线(2026-06-14 实测)**:`pytest -q` = **731 passed, 7 skipped, 0 failed**;`vue-tsc -b` exit 0;`test_tool_registry` 30 passed;工具 114=114 无 drift。之后所有 Phase 的门槛 = **不新增失败**。

**验证:**
```bash
cd backend && ./.venv/bin/python -c "import app.main"
./.venv/bin/python -m pytest -q          # 期望 731 passed / 7 skipped
cd ../frontend && npx vue-tsc -b && npx vite build
```

## Phase 1 — 锁契约(原 Task 1-2)

**新建:** `docs/architecture/{domain-model,agent-run-state,tool-contracts,deployment-truth}.md` + `backend/tests/test_architecture_domain_contracts.py` / `test_agent_run_state_contract.py` / `test_tool_contracts_schema.py`

- [ ] `domain-model.md`:上面的域表 + ID 规则 + Reviewer 结论。
- [ ] `agent-run-state.md`:状态机 `created/planning/running_tools/waiting_user/applying/verifying/completed/failed/cancelled` 及合法转移。
- [ ] `tool-contracts.md`:契约字段 `name/category/read_only/writes_workspace/writes_apaas/deploys_or_publishes/requires_confirmation/idempotency/failure_codes`。**M2:这些副作用字段最终落 tool_registry.yaml**,本文档定义其语义。
- [ ] `deployment-truth.md`:区分 本地改动 / build 过 / 包存在 / 上传资产库 / 绑定 app / 部署 aPaaS / republish 可见 七态。
- [ ] 契约测试:绑定用例经单一 service API 解析;非法状态转移被拒;write/deploy 工具暴露副作用元数据。实现前应红(缺 service/字段),实现后绿。

**验证:** `pytest tests/test_architecture_domain_contracts.py tests/test_agent_run_state_contract.py tests/test_tool_contracts_schema.py -q`

## Phase 2 — 边界服务(原 Task 3,4,6,7,带审计修正)

### 2A workspace_binding_service(原 Task 3)
**吸收** `workspace_access.py`,不平地新建。解析全部绑定路径 + 集中 app 绑定访问检查 + 返回 typed 结果。验收:无 route 手猜 `project_id` 是 project 还是 application;现有 open/list/source/download 不破。
**验证:** `pytest tests/test_coding_app_binding_persistence.py tests/test_custom_page_workspace_binding.py tests/test_dev_workspace_listing.py tests/test_workspace_sync.py -q`

### 2B application_context_service(原 Task 4)— ✅ 已被现有架构满足,跳过
**执行时核验结论(2026-06-14):** 不做。`app_context.py`(185行)+ `AIChatSession.app_id`(session→app 锁,agent.py:581 读)已集中"当前 app 上下文"解析与 prompt 注入(`build_app_context_block`),app_id/apaas_app_id 已进 prompt。无散落逻辑可收口;跨会话/租户隔离靠 per-session `app_id` 天然成立(test_session_app_lock/test_app_context_prompt 已覆盖)。新建 service = 纯 rename-churn(计划自身 Reviewer Q 警告项),不做。
> coding 侧的 `coding_app_id` 解析已在 2A 收口;ai_chat 的 session.app_id 与 coding 的 conversation.coding_app_id 是两个域,强行统一会触发 Stop Condition「一个 Task 改多个域」,留 Phase X。

### 2C tool_contract_service(原 Task 6,M2 修正)
**副作用字段(read_only/writes_workspace/writes_apaas/requires_confirmation/idempotency)加进 tool_registry.yaml**(现有 `category` 14 值是域分类,无副作用语义);service 只读 yaml 派生;**drift check 扩展覆盖新字段**。验收:`deploy_dev_workspace_to_app`/`upload_dev_workspace_to_asset_library`/`get_current_workspace_app_status`/`republish_apaas_app` 要么有正确契约、要么明确不可用且给原因;CodingAgent 能查能力而非幻觉。
**验证:** `pytest tests/test_tool_registry.py tests/test_mcp_envelope.py tests/test_coding_app_context_tools.py tests/test_coding_deploy_to_app.py -q`

### 2D deployment_status_service(原 Task 7)
build/package/upload/publish/republish 真相分离;给 UI 和 agent 一个状态 payload;agent 没有该服务的观测就不能答"已发布"。验收:"build 过"不显示成"已发布";"上传资产库"不显示成"已 republish";agent 回答能引用其核实的状态阶段。
**验证:** `pytest tests/test_coding_deploy_to_app.py tests/test_publish_status_gate.py tests/test_application_delivery_assets.py -q`

## Phase 3 — ★执行器收敛(H1,新增,最高 ROI)

**目标:** `operations/` 收口三执行器的原子 `create_*` 操作(角色/字典/模型/表单/权限),`generator_v2` / `step_executor` / `incremental_executor` 复用单一实现。

**文件:** `backend/app/operations/{roles,dicts,models,forms,permissions}.py`(新增)+ 改 `generator_v2.py` / `step_executor.py` / `incremental_executor.py` 改为调 operations。

**步骤(逐个原子操作,一个一个搬,每个一 commit):**
- [ ] 先建对比测试:同一份 config_preview 分别喂 generator_v2 与 step_executor,断言对 aPaaS 的写调用序列等价(用 mock client 录调用)。这是收口的安全网。
- [ ] 逐个把 `create_role/create_dict/create_model/create_form/configure_permissions` 的本体收进 operations/,两/三执行器改为薄封装调它。优先收 **权限 payload**(`_build_permission_groups_for_form_config`/`_parse_permission_ops`,这俩是 bug 级漂移,权限修复只落了 step_executor 侧)和 **下拉绑字典**(b14a434d 漂移源)。
- [ ] 收口后 `generator_v2.py` 退化为"一把梭编排壳 + generator 特有的模型复用判定";step_executor 退化为"分步编排壳"。

**验收:** 同份文档从 ChatPage(分步)和 AIChatPage(一把梭)生成,aPaaS 写序列一致;单边修 bug 不再可能(改 operations 一处即全覆盖)。
**验证:** `pytest tests/test_generation_workflow_status.py tests/test_dropdown_dict_reconcile.py tests/test_form_detail_dropdown_options.py -q`(+ 新建的执行器等价对比测试)

**执行进度(2026-06-14,逐函数亲核 canonical,每刀独立 commit,全程 781 passed/0 failed):**
- ✅ 3-1 `_parse_permission_ops` → operations/permissions.py(canonical=step_exec 超集,修 gen_v2 对 list 丢 ops)
- ✅ 3-2 表单标识固化(`_force_form_identity`/`_apply_form_identity_to_form_config`)→ form_config.py(AST diff 证两侧 mutation 等价,canonical=step_exec bool 版)
- ✅ 3-3 `_ensure_canvas_form_components` → form_config.py(canonical=step_exec bool 版,顺带修 gen_v2 `updated=...` 恒 None 潜在 bug)
- ✅ 3-4 `_save_form_config_with_retry` + 冲突检测 → form_config.py(**冲突标记取两侧并集**:gen_v2 多"无法保存"/step_exec 多乐观锁·版本·stale,各自漏对方→并集双向增强覆盖)
- ✅ 3-5 `_finalize_created_form_config` → form_config.py(依赖收口后两侧仅日志差,form_id 位置参兼容两侧调用)
- ⏸️ **3-6 `_build_permission_groups_for_form_config` / 3-7 `_sync_form_permissions_to_form_config`:不盲合,需平台确认。**
  - **澄清:分析 agent 称"gen_v2 权限 payload 错(ALL_USER 写成值)"= 误报。** gen_v2 `_permission_object_for_form_config` 对 ALL_USER 也返回 `permissionObjectValue=""`,与 step_exec 等价,无此 bug。
  - 真实差异仅:① advanced_groups 字段集 gen_v2 发 9 个(多 comment/export/print/log/share/queryApprovalInfo)vs step_exec 发 3 个(query/update/delete,注释称平台只保留 3 个);② step_exec 给 operation permissionObjects 多 `permissionRange`;③ role_name 回退(cosmetic)。
  - **#① 取决于 apaas 平台是否 honor 那 6 个额外字段——代码层无法验证。** 若平台其实 honor export/print,收口成 step_exec 3 字段版会悄删生产路径的导出/打印权限控制。触及 Stop Condition「写序列不一致先确认哪侧对,别盲合」。
  - **待办**:有 apaas API 访问 / xhh 确认平台对 advanced 权限字段的实际处理后再收口(若平台确实只保留 3 个→收口成 step_exec 版;若 honor→收口成 gen_v2 superset + step_exec 的 permissionRange)。无紧急性(无 bug)。

## Phase 4 — 拆后端大文件(并入原拆分工单 Wave 1A/3/4)

### 4A workspace.py 模板落盘(4624 → ~2900)
内联脚手架模板字符串落盘 `backend/templates/`(机制现成:`_scaffold_from_template`)。⚠️带插值的字符串改占位符,硬编码 `/Users/mars/.nvm/...`(生成 JS 的运行时 fallback)**原样保留**。验收:同 project_type 落盘前后生成的工作区 `diff -r` 全等。

### 4B applications/__init__.py 拆子模块(3098 → <600)
沿 `:2094` 既有 include 模式拆 `crud.py`/`lifecycle.py`/`apaas_menus.py`。⚠️include 顺序敏感(`/{app_id}` 通配在具体路径后),用路由全表 diff 证等价。

### 4C auth.py 三件套纯搬移(2748 → 3×~900)
拆 `auth/{login,tenants_admin,tenant_members}.py` + façade re-export,路由全表 diff 全等。⚠️apaas_client 本计划不拆(连接池/typed errors 是行为改动)。

**验证(每子项):** `import app.main` 通过;`pytest -q` 不新增失败;路由全表(`python -c "from app.main import app; ..."`)拆前后 diff 全等。

## Phase 5 — 自开发 patch 守卫(原 Task 8)

默认 patch 现有文件;整包重写需显式确认;大 diff 触发澄清/警告(阈值见域模型结论:单文件改动比 >50% 或整文件替换)。验收:"把接口调用改一下"默认不能重写整页;"重新生成这个页面"确认后才整改写;prompt 写明默认 source-preserving。
**验证:** `pytest tests/test_coding_iteration_patch_guard.py tests/test_harness_coding_edit_diff.py -q`

## Phase 6 — 事件协议 + 观测(原 Task 9,M1 修正)

- [ ] **M1 先盘点三套回放层**:`ConversationReplay` / `ConversationEvent` / `HarnessItem` 职责与去留,决定收敛到几套,**再**定义统一事件名。不要在不承认三套现状的情况下加"第四套规范"。
- [ ] 新建 `services/agent_event_service.py` + `frontend/src/types/agent-events.ts`:事件名/payload 字段定义一次;replay 含足够字段重建 message/tool/diff/attachment;前端不再猜缺字段。
- [ ] 观测补齐(力所能及范围):把 recorder 接到 deployment/生成链路(coding/builder 链路的完整 recorder 接入与 token 采集,因与 run 语义耦合,主体留 Phase X)。
**验证:** `pytest tests/test_conversation_replay_store.py tests/test_coding_replay_attachments.py tests/test_coding_conversation_delete.py -q` + `cd frontend && npm run test -- --run`

## Phase 7 — 拆前端大文件(原 Task 10/11 = 拆分工单 Wave 5,事件契约稳后)

### 7A ChatPage.vue(14180 → ~9000)
页面壳保留;部署进度 / 设计文档 / dialog / 配置 tab / 输入区 → components/composables。**先删已知死码残留再动刀**(incremental 已删);CSS 随组件走。⚠️SPEC 三件套 flag 冷藏,绕开别删。
### 7B CodingPage.vue
页面壳保留;文件树/code viewer/diff/工作区状态/会话 → 模块。不得重新引入 code-server 路径。
**验证(各):** `npm run build` + `npm run test -- --run` + 浏览器 smoke(切 6 个设计 tab 无 console 错 / 选文件看 diff / 发只读问题 / 刷新保会话)。

## Phase 8 — 回归(原 Task 12,L3 修正)

新建 `docs/architecture/regression-checklist.md`。**★必测两个生成引擎**:0-1 生成要分别测 ChatPage 分步路径 **和** AIChatPage 一把梭路径(它们是两套引擎,Phase 3 收口后更要验等价)。其余:配置改动锚定 apaas_app_id、自开发 patch 非整改写、发布状态不夸大、登录校验、附件可见、资产库绑定区分。
**验证:**
```bash
cd backend && ./.venv/bin/python -m pytest -q          # 不低于 731 passed
./.venv/bin/python -m py_compile app/main.py app/mcp_server.py
cd ../frontend && npm run build
cd ../admin-spa && npm run build
git diff --check
```

---

## Phase X — 引擎收敛(延后,单独多轮会话)

**不在本主计划执行。** 6 套 agent 循环 → run_agent 底座。前置(必须先于收敛):
- 给 run_agent 补 **上下文压缩**(现 `_build_initial_messages` 每轮全量回放无窗口,长会话必爆 context)。
- 给 run_agent 补 **持久化抽象层**(现直吃 db+session 硬编码 4 张 ai_chat 表,是收编其他循环的最大障碍)。
- **并行工具执行 + 只读循环检测 nudge**(从 BaseAgent/CodingAgent 反向吸收)。
- **统一 ToolContext**(三签名合一:`(args,session,db)` / `(args,workspace_path)` / `AgentContext`)。
- **统一 ask_user 语义**(现 4-5 份:伪 tool-result 退出 / PAUSED snapshot / 流内 yield / SPEC mutation / mock intent)。
- 建 `agent_run_service`(运行语义统一)+ 其余 3 链路接 recorder(观测从 1/6 → 全覆盖)。

迁移顺序:read_query(最干净)→ config-chat 死区清理 → SpecAgent(需加声明式 spec_patch 即时落库语义)→ codegen(风险最高,前端事件词表牵连)。详见 2026-06-14 架构深挖。

---

## 执行顺序

```
Phase 0(收尾在途重构)→ 1(契约)→ 2(边界服务)→ 3(执行器收敛)
→ 4(拆后端)→ 5(patch守卫)→ 6(事件+观测)→ 7(拆前端)→ 8(回归)
                                                          ⋯⋯ Phase X(引擎收敛,另立)
```
- Phase 1-2 不动行为,先行。
- Phase 3(执行器收敛)是结构治理核心,在边界服务后做。
- Phase 7(拆前端)必须等 Phase 6 事件契约稳。
- Phase 7 之前别碰 ChatPage/CodingPage 大重构。

## Stop Conditions(任一触发即暂停复审)

- 一个 Task 要同时改多个域。
- 一个 route 同 commit 里既依赖新 service 又改响应结构。
- 测试要大改 fixture 才能过。
- agent 会丢掉一个当前可用的工具。
- 浏览器 smoke 与后端测试给出不同的 app/runtime 真相。
- 重构导致生成的自开发资产与其源 app 脱钩。
- **Phase 3:执行器等价对比测试发现两引擎写序列本就不一致**——先记录差异、确认哪侧是对的,再收口(别盲合)。
