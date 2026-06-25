# 把 Code 并进 Builder — SP1:堵住 Code 会话漏进 Builder(止血)

日期:2026-06-25
状态:设计待用户确认 → writing-plans
作者:大明哥 + Claude(brainstorming)
关联:[2026-06-24-unified-agent-engine-design.md](2026-06-24-unified-agent-engine-design.md)(引擎层,已确认;本 SP1 是它的**会话层止血**)

> 注:本 spec 在 writing-plans 阶段读码后**收紧过**——原稿把「行为由会话推导/单 registry/Code 侧会话归位」都放进 SP1,读码发现它们要么是 SP1 里的死代码、要么纠缠在 SP2 会删掉的 CodingPage 历史机制上。SP1 收敛为**两处 chokepoint 的服务端 kind 收口**,把用户报的「漏进 Builder」当场止住;其余三项移到 SP2(见 §3.4,附原因)。

---

## 0. 这是一个大目标的第 1 块

用户决定:**删掉 Code 标签,只留 Builder;一切收到 Builder/run_agent 一个引擎;把 Code 的 Codex 风 UED 融进 Builder;一套结构、按需加载。** 拆三块,各自 spec→plan→实现:

- **SP1(本文)— 服务端 kind 收口(止血)**:Builder 的会话列表与 per-session 路由不再列出/接受 `mode='code'` 会话。两处 chokepoint 改动,纯后端,前端零改。**做完用户报的「Code 会话漏进 Builder / 在 Builder 里被打开发送」当场消失**,且 Builder 现有体验零回归。
- **SP2 — 前端统一外壳(UED)+ 会话模型收口**:把 Codex 面板(审查/文件/终端/浏览器)+ apaas 内嵌编辑器融进 Builder 一个页面,内容驱动点亮 + 按工作区默认聚焦;删 Code 的 rail 入口与 CodingPage;**统一外壳直接读 `AIChatSession`(list+messages)→ Code 会话天然归位**(不再走 CodingPage 的错表历史机制);**行为由会话推导**(单一 run 路径,run_agent 据 `session.mode` 选 profile);**单一 run registry**(单路径自然收口);一份按工作区分组的会话侧栏;「我的开发」入口。依赖 SP1。
- **SP3 — 退役旧 Code 路径**:删旧 coding 流水线、harness 第二个 registry、`Conversation(agent_type='coding')` 路径、`/coding` 路由,迁移历史会话。对齐引擎 doc 的 Phase 2。依赖 SP2。

**明确边界(整个三块都不动)**:`/chat/:id` 那个「进某个具体应用后的配置助手」(ChatPage,最近改成内嵌 apaas 编辑器)。它是「打开某个 app 去配」的独立入口,与「我的开发」是两个进法,不在本轮。

---

## 1. 背景与问题(精确根因)

「Code cutover」(`CODING_USE_RUNAGENT=1`,桌面包已开)让 Code 模式**不再有自己的会话存储**:它直接往 `AIChatSession` 表写 `mode='code'` 的行——这正是 Builder 首页(AIChatPage,`/` 与 `/ai-chat`)列会话的同一张表、同一个自增 id 空间。`mode` 这个列**没有任何地方在过滤**。一个架构决定,两个症状:

**(1) 会话混淆(主症状,高置信)**
- `GET /ai-chat/sessions` 只按 user+tenant 过滤,无 `mode` 谓词 → `mode='code'` 行混进 Builder 侧栏。[ai_chat.py:452-465](../../../backend/app/routes/ai_chat.py)
- `_load_session_or_404` 也无 `mode` 守卫 → 这个 Code 会话在 Builder 里能 open/send/attach/abort/delete(13 个 per-session 路由全经它)。[ai_chat.py:427-440](../../../backend/app/routes/ai_chat.py)
- 前端 `filteredSessions = computed(() => sessions.value)` 零过滤;`listSessions` 的消费者(AIChatPage、RailSidebar、useAiChatSession)全是 Builder 面。[AIChatPage.vue:531/1683](../../../frontend/src/views/AIChatPage.vue)
- 反向:Code 自己的列表 `GET /coding/conversations` 查的是**另一张表**(`Conversation`,agent_type='coding')→ cutover 写的新 Code 会话在 Code 侧栏**根本不显示**(作者自注 [coding.py:342](../../../backend/app/harness/profiles/coding.py))。
- 结论:**会话既漏进 Builder,又从 Code 消失。**

**(2) 功能混淆(次生,条件触发)**
- 引擎本身不知道在跑 Code 还是 Builder,区别**只由调用方是否传 override 决定**:Code 路径在 harness 调用点传 `system_prompt_override`+`tool_names_override`+`session._locked_ws_id`;Builder 路径 `run_agent(...)` 不传。[coding.py:420-424](../../../backend/app/harness/profiles/coding.py) vs [ai_chat.py:771](../../../backend/app/routes/ai_chat.py)
- 所以一个 Code 会话一旦在 Builder UI 里发送,**拿到 Builder 的提示词 + 全套工具**。

**SP1 关键洞察**:症状 (2) 的触发前提是「Code 会话能在 Builder 里被发送」。**SP1 的 kind 收口让 Builder per-session 路由对 `mode='code'` 直接 404 → Code 会话再也到不了 override-less 的 Builder 路径 → 症状 (2) 随症状 (1) 一并消失。** 不需要在 SP1 动引擎。

那 4 个加固 commit(cd8bf6f1/3e839dd3/b38ed5f4/c8d77d4d)只硬化了 harness 那条 Code 路径,没给共享存储和 Builder 路由加 `mode` 判别,所以堵不住。

---

## 2. 目标与非目标

### 目标(SP1)
1. Builder 的会话**列表**不再返回 `mode='code'` 会话(`list_sessions` 服务端收口)。
2. Builder 的**所有 per-session 路由**(send/abort/run-status/attach/get/delete/messages…共 13 个,全经 `_load_session_or_404`)对 `mode='code'` 会话返回 404。→ 同时根除症状 (1) 与 (2)。
3. Builder 现有 `mode IN ('chat','cowork')` 会话行为**零回归**。

### 非目标(SP1)
- 不做前端统一外壳 / 不删 Code rail 入口 / 不动 CodingPage / `/coding` 路由(→ SP2)。
- 不让 Code 侧栏显示 cutover 会话(→ SP2,见 §3.4)。
- 不动引擎 `run_agent`、不改「行为由会话推导」(→ SP2,见 §3.4)。
- 不合并两个 run registry(→ SP2,见 §3.4)。
- 不退役旧 coding 流水线 / 不删 `Conversation(agent_type='coding')`(→ SP3)。
- 不动 ChatPage(`/chat/:id`)配置助手。

---

## 3. 设计

### 3.1 收口点 A:会话列表排除 code
`list_sessions`([ai_chat.py:452-465](../../../backend/app/routes/ai_chat.py))的查询加一条 `AIChatSession.mode != "code"`。所有 Builder 列表消费者(AIChatPage `/`、RailSidebar builder/agent 态、useAiChatSession 按 app_id)随之不再看到 code 会话。**前端零改**(`_session_to_dict` 已暴露 `mode`,但收口在服务端,前端无需依赖它)。

### 3.2 收口点 B:per-session 加载拒绝 code
`_load_session_or_404`([ai_chat.py:427-440](../../../backend/app/routes/ai_chat.py))的查询加 `AIChatSession.mode != "code"`。这是 13 个 per-session 路由(send/abort/run-status/attach/get/delete/messages/...)的唯一 chokepoint,一处改动全覆盖。**在 where 子句里过滤**(而非 load 后判)→「不存在」与「是 code」返回同一个 404,不泄露存在性(与现有 [test_delete_non_coding_conv_returns_404] 风格一致)。
- `_load_session_or_404` 经核实**只被 ai-chat(Builder)路由调用**;cutover Code 路径用 `db.get(AIChatSession, cid)` 直取([coding.py:348](../../../backend/app/harness/profiles/coding.py)),不经此函数。故此改动**不影响 Code 路径**。

### 3.3 为什么这就够修 bug
- 症状 (1):列表 + 加载双收口 → code 会话在 Builder 既不可见、也不可加载/操作。
- 症状 (2):code 会话到不了 Builder 的 override-less `run_agent` 路径 → 不会拿到 Builder 提示词/全量工具。
- Code 端不受影响:Code 走 `/harness/coding/*` 与 `/coding/*`,与 ai-chat 路由不相干;cutover 取会话用 `db.get`,绕过收口。

### 3.4 移到 SP2 的三项(及原因)
| 项 | 为什么不在 SP1 | 在 SP2 自然解决 |
|---|---|---|
| **Code 侧栏显示 cutover 会话 / 历史归位** | cutover 会话在 `AIChatSession`/`AIChatMessage`,但 CodingPage 的 list + replay + messages + workspace 端点全 key 在 `Conversation` 表([coding.py:350-378](../../../backend/app/routes/coding.py));要让 Code 侧栏可用得把整条历史机制改读对表——而这页 SP2 整体删掉 = 纯废工。SP1 也**未使其更糟**:cutover 会话本就不在 Code 列表(作者「留作后续」),SP1 只移除「误漏进 Builder」。 | 统一外壳直接读 `AIChatSession`(list+messages),Code 会话天然归位,无错表问题。 |
| **行为由会话推导(run_agent 据 mode 选 profile)** | SP1 里是死代码:harness 路径必须继续传 `_cutover_tool_names(ws_id)`(收窄要 ws_id,run_agent 拿不到);唯一 override-less 的 Builder 路径已被 §3.2 收口挡住 code 会话 → 推导分支永不触发。 | SP2 把两条 run 路径并成一条,无 caller 传 override → 必须据 `session.mode` 选 profile,这时才有意义。 |
| **合并两个 run registry** | 需动**共享的** `harness/manager.py` 注册逻辑(legacy+cutover 通吃),加「是否 cutover」条件分支,风险高;且 §3.2 收口后,跨模式 attach/stop 的触发场景(同一会话两 UI 操作)已不可达。 | SP2 单路径 → 单 registry 自然成立,无需在共享 manager 里开分支。 |

### 3.5 数据/迁移
- **无**。不改表结构、不加列、不迁移。仅给两条已有查询加 `mode != 'code'` 谓词。

---

## 4. 组件与接口(隔离单元)

| 单元 | 改动 | 文件 | 测试 |
|---|---|---|---|
| `list_sessions` | 查询加 `AIChatSession.mode != "code"` | [routes/ai_chat.py:452-465](../../../backend/app/routes/ai_chat.py) | 集成:seed chat+code 两会话 → 只返回 chat |
| `_load_session_or_404` | 查询加 `AIChatSession.mode != "code"` | [routes/ai_chat.py:427-440](../../../backend/app/routes/ai_chat.py) | 集成:code 会话 → 404;chat 会话 → 返回;跨 user/tenant 仍 404(回归) |

两处都是单语句 where 子句新增,改动集中、可独立测、零数据迁移。

## 5. 错误处理
- 收口在 where 子句:命中即「查无」,统一 404,不区分「不存在」与「是 code」(不泄露存在性)。
- 对 `mode IN ('chat','cowork')`(及历史空值默认 'chat')会话:谓词 `mode != 'code'` 放行,行为不变。

## 6. 测试策略
镜像现有 [tests/test_coding_conversation_delete.py](../../../backend/tests/test_coding_conversation_delete.py) 的 `db_session` fixture + `_ctx_for(user, tenant_id)` 构造 AuthContext 的写法:
- **`_load_session_or_404`**:① `mode='code'` → `HTTPException(404)`;② `mode='chat'` → 正常返回该会话;③ 他人/他租户的 chat 会话 → 仍 404(回归不破)。
- **`list_sessions`**:seed 同一 user 的 `chat` + `code` 两会话 → 返回里只含 chat,无 code。
- **回归**:`mode='cowork'` 会话照常出现在列表、照常可加载。
- 全量后端测试保持绿(`cd backend && .venv/bin/python -m pytest`)。

## 7. 风险与回滚
- 改面极小:两条 where 子句。对 Builder 默认链路(chat/cowork)是 no-op。
- `_load_session_or_404` 仅 Builder 路由用、Code 路径用 `db.get` 绕过 → 不波及 Code。
- 收口是 SP2 前的过渡:SP2 合并会话列表为分组视图后,「排除 code」演化为「按 kind 分组」——预期演进,非债。
- **桌面打包**:后端改动需重建 sidecar 才进桌面 app;本地 `:8000` 仅 web 验证。
- **reload=False**:改后端必重启 `cd backend && .venv/bin/python run.py`。

## 8. 验收标准
- `mode='code'` 会话**不再**出现在 Builder 会话侧栏(`/ai-chat/sessions` 不返回)。
- Builder 任一 per-session 路由对 `mode='code'` 会话返回 404(不可 open/send/attach/abort/delete)。
- Builder 现有 chat/cowork 会话列表与操作**零回归**(集成测试绿)。
- 后端全量测试绿;桌面 cutover 真机手验:新建 code 会话不再出现在 Builder 侧栏。
