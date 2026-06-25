# 把 Code 并进 Builder — SP1:会话层统一(修串台 bug)

日期:2026-06-25
状态:设计待用户确认 → writing-plans
作者:大明哥 + Claude(brainstorming)
关联:[2026-06-24-unified-agent-engine-design.md](2026-06-24-unified-agent-engine-design.md)(引擎层,已确认;本 SP1 是它的**会话层补全**)

---

## 0. 这是一个大目标的第 1 块

用户决定:**删掉 Code 标签,只留 Builder;一切收到 Builder/run_agent 一个引擎上;把 Code 的 Codex 风 UED 融进 Builder;一套结构、按需加载。** 因为太大,拆成三块,各自 spec→plan→实现:

- **SP1(本文)— 会话层统一 + 行为由会话推导**:单一会话存储、`mode` 一等公民、引擎从会话推导行为(不再靠调用方传 override)、单一 run registry、list/load 服务端按 kind 收口。**做完最初报的「session 会话混淆」bug 从根上消失**,两个现有 UI 仍各自能跑。纯后端 + 极少前端读取改动,可独立测。
- **SP2 — 前端统一外壳(UED)**:把 Codex 面板(审查/文件/终端/浏览器)+ apaas 内嵌编辑器融进 Builder 一个页面,内容驱动点亮 + 按工作区默认聚焦;删 Code 的 rail 入口;一份按工作区分组的会话侧栏;「我的开发」入口。依赖 SP1。
- **SP3 — 退役旧 Code 路径**:删旧 coding 流水线、第二个 registry、`Conversation(agent_type='coding')` 路径、`/coding` 路由,迁移历史会话。对齐引擎 doc 的 Phase 2。依赖 SP2。

**明确边界(整个三块都不动)**:`/chat/:id` 那个「进某个具体应用后的配置助手」(ChatPage,最近改成内嵌 apaas 编辑器)。它是「打开某个 app 去配」的独立入口,与「我的开发」是两个进法,不在本轮。

---

## 1. 背景与问题(精确根因)

「Code cutover」(`CODING_USE_RUNAGENT=1`,桌面包已开)让 Code 模式**不再有自己的会话存储**:它直接往 `AIChatSession` 表写 `mode='code'` 的行——这正是 Builder 首页(AIChatPage,`/` 与 `/ai-chat`)列会话的同一张表、同一个自增 id 空间。`mode` 这个列**没有任何地方在过滤**。一个架构决定,两个症状:

**(1) 会话混淆(主症状,高置信)**
- `GET /ai-chat/sessions` 只按 user+tenant 过滤,无 `mode` 谓词 → `mode='code'` 行混进 Builder 侧栏。[ai_chat.py:452-465](../../../backend/app/routes/ai_chat.py)
- `_load_session_or_404` 也无 `mode` 守卫 → 这个 Code 会话在 Builder 里能 open/send/attach/abort/delete。[ai_chat.py:427-440](../../../backend/app/routes/ai_chat.py)
- 前端 `filteredSessions = computed(() => sessions.value)` 零过滤。[AIChatPage.vue:531](../../../frontend/src/views/AIChatPage.vue)、[1683-1684](../../../frontend/src/views/AIChatPage.vue)
- 反向:Code 自己的列表 `GET /coding/conversations` 查的是**另一张表**(`Conversation`,agent_type='coding')→ cutover 写的新 Code 会话在 Code 侧栏**根本不显示**(作者自注 [coding.py:342](../../../backend/app/harness/profiles/coding.py))。
- 结论:**会话既漏进 Builder,又从 Code 消失。**

**(2) 功能混淆(次生,条件触发)**
- 引擎本身不知道自己在跑 Code 还是 Builder。区别**只由调用方是否传 override 决定**:Code 路径在 harness 调用点传 `system_prompt_override`(dev-apaas 提示词)+ `tool_names_override`(收窄工具)+ `session._locked_ws_id`(锁工作区);Builder 路径 `run_agent(...)` 不传任何 override。[coding.py:420-424](../../../backend/app/harness/profiles/coding.py) vs [ai_chat.py:771](../../../backend/app/routes/ai_chat.py)、[agent.py:854-861](../../../backend/app/ai_chat/agent.py)
- 所以一个 Code 会话一旦在 Builder UI 里发送,**拿到 Builder 的提示词 + 全套工具,且 dev-apaas 的 ws-lock / 工具收窄 / view_context 全失效**。

**(3) run 状态跨模式互盲(中置信)**
- 两个独立 `RunRegistry` 单例,键空间相同:Builder 用 `ai_chat_run_registry` 按 `session_id` 持有;Code 用 harness `run_registry` 按 `conversation_id`(cutover 下 == `AIChatSession.id`)。[run_bus.py:93](../../../backend/app/ai_chat/run_bus.py)、[run_registry.py:40](../../../backend/app/harness/run_registry.py)
- 各自的 409 单跑守卫 / attach / run-status / stop 只查自己那本字典 → 一个会话在 Code 里「在跑」,在 Builder 里读成「没在跑」;stop/attach 打到错的 registry。

那 4 个加固 commit(cd8bf6f1/3e839dd3/b38ed5f4/c8d77d4d)只硬化了 harness 那条 Code 路径,**没给共享存储和 Builder 路由加 `mode` 判别**,所以堵不住。

### 已有资产(SP1 复用,不重造)
- `AgentProfile` 抽象 + `resolve_profile("dev-apaas")` 已存在。[profile.py](../../../backend/app/agents/profile.py)
- `run_agent(db, session, msg, abort, section, view_context, system_prompt_override, tool_names_override)` 已支持 profile 化 override。[agent.py:764-810](../../../backend/app/ai_chat/agent.py)
- `RunRegistry` 类(`dict[int, RunHandle]`)可直接复用为单例。[run_registry.py:22-37](../../../backend/app/harness/run_registry.py)

---

## 2. 目标与非目标

### 目标(SP1)
1. **行为由会话推导**:`run_agent` 跑某会话时,提示词/工具/ws-lock 由 `session.mode` 决定,而非调用方临时传 override。`mode='code'` 永远按 dev-apaas 跑,无论从哪条路由进。→ 根除功能混淆(症状 2)。
2. **单一 run registry**:cutover Code run 与 Builder run 进同一本 registry、按 `AIChatSession.id` 单键空间。→ 根除跨模式互盲(症状 3)。
3. **服务端按 kind 收口(过渡期)**:两个 UI 仍并存的窗口期内,Builder 列表/路由不再看见 Code 会话;Code 侧栏能看见自己的 cutover 会话。→ 根除会话混淆(症状 1)。
4. 全程不改 Builder 现有「读→写→build」行为(回归保护)。

### 非目标(SP1)
- 不做前端统一外壳 / 不删 Code rail 入口 / 不动 `/coding` 路由(→ SP2)。
- 不退役旧 coding 流水线 / 不删 `Conversation(agent_type='coding')`(→ SP3 / 引擎 doc Phase 2)。
- 不动 ChatPage(`/chat/:id`)配置助手。
- 不引入新的 `app`/`doc` 工作区 kind(SP2 引入工作区 kind 时再加;SP1 只让 mode→profile 机制就位,便于扩展)。
- 不重写 LLM 网关 / 不改 aPaaS 协议。

---

## 3. 设计

### 3.1 mode → profile:行为由会话推导(目标 1)

**核心改动:把「决定这是 Code 还是 Builder 行为」从调用点,挪到由会话自身决定。**

新增纯函数(在 `agents/profile.py`):

```
SESSION_MODE_TO_PROFILE = {"code": "dev-apaas"}   # chat/cowork/未知 → None(= 通用 Builder)

def resolve_overrides_for_session(session) -> tuple[str | None, set[str] | None, str | None]:
    """返回 (system_prompt_override, tool_names_override, locked_ws_id)。
    None/None/None = 通用 Builder 行为(今天的默认,零回归)。"""
    name = SESSION_MODE_TO_PROFILE.get(getattr(session, "mode", None))
    if not name:
        return None, None, None
    p = resolve_profile(name)
    ws_id = _resolve_ws_id_for_session(session)          # 见 3.1.1
    tools = set(_cutover_tool_names(p.tool_names, ws_id)) # 复用现有收窄
    return p.system_prompt, tools, ws_id
```

`run_agent`(或紧贴它的一层薄封装)在**调用方未显式传 override 时**,调用上面这个函数从 `session` 推导。改法二选一,plan 阶段定:
- **A(推荐,改动最小)**:`run_agent` 内,当 `system_prompt_override is None and tool_names_override is None` 时,调 `resolve_overrides_for_session(session)` 补齐,并据 `locked_ws_id` 设 `session._locked_ws_id`。显式传 override 的老调用(harness 当前写法)行为不变。
- **B**:新增 `run_session_turn(db, session, ...)` 单一入口,内部解析 profile 再调 `run_agent`;两条路由都改调它,harness 不再手传 override。

两种都达到「行为锚定在会话上」。推荐 A:Builder 路由([ai_chat.py:771](../../../backend/app/routes/ai_chat.py))一行不改、自动对 `mode='code'` 会话生效;harness 路径的显式 override 变冗余(SP3 清理)。

#### 3.1.1 ws-lock 由会话推导
当前 ws-lock 只在 harness 调用点挂(`session._locked_ws_id = ws_id`,[coding.py:415-416](../../../backend/app/harness/profiles/coding.py)),Builder 路由进来的同一会话拿不到锁。SP1 让锁**从会话推导**:`_resolve_ws_id_for_session(session)` 从 `session.workspace_dir` 反解 ws_id(经 `WorkspaceManager`,与 [coding.py:356-361](../../../backend/app/harness/profiles/coding.py) 对称),或读会话上已存的 ws 绑定。这样**任何路由**跑 `mode='code'` 会话都自动锁工作区。
- 决策点(plan 阶段):`workspace_dir`→`ws_id` 反解是否够稳?若不稳,SP1 给 `AIChatSession` 加一个可空 `workspace_id`(String)列直接存 ws_id,建会话时写入(cutover 写点已有 ws_id,[coding.py:369-376](../../../backend/app/harness/profiles/coding.py))。倾向加列,确定性最高。

### 3.2 单一 run registry(目标 2)

- 让 cutover Code 路径 **register/lookup 进 `ai_chat_run_registry`、按 `AIChatSession.id` 为键**(它已经是 cutover 下 harness registry 的实际键值);harness 侧的 attach/run-status/stop 对 cutover 会话改查这同一本 registry。
- 结果:Builder 与 Code 对同一 `session.id` 看到同一个 `RunHandle`;409 守卫、attach、stop、run-status 跨模式一致。
- **旧(非 cutover)coding 流水线**仍用 harness `run_registry`(按 `Conversation.id`),不动 —— 它在 SP3 随整条流水线退役。两本 registry 在 SP1 期间并存但**键空间不再交叉**(cutover→ai_chat registry by AIChatSession.id;legacy→harness registry by Conversation.id),互盲问题消失。
- 边界:`attach_stream` 当前收 `tenant_id` 却不用于校验([manager.py:265-279](../../../backend/app/harness/manager.py))。SP1 顺手让 attach 用 `tenant_id` 校验 ownership(防数字键复用跨租户串流),小且同源。

### 3.3 服务端按 kind 收口(目标 3,过渡期措施)

两个 UI 在 SP2 前并存,这段窗口必须靠服务端把两边隔开。SP2 把列表合并成一份分组列表后,这里的「排除」退化为「分组」。

- `list_sessions` 增 `modes: list[str] | None`(或 `exclude_modes`)参数;Builder 调用默认**排除 `code`**。无 mode 谓词的裸查询不再可能漏 Code 行。[ai_chat.py:445-465](../../../backend/app/routes/ai_chat.py)
- `_load_session_or_404` 增 `allowed_modes: set[str] | None`;Builder 的 per-session 路由(send/abort/run-status/attach/delete)传 `allowed_modes={'chat','cowork'}`,遇 `mode='code'` 返回 404/403。[ai_chat.py:427-440](../../../backend/app/routes/ai_chat.py)
- Code 侧栏的数据缺口(cutover 会话不显示):提供 Code 用的列表来源 —— 返回该用户 `AIChatSession where mode='code'` 的行(新 `GET /coding/sessions` 或扩展现端点)。这补回「从 Code 消失」那一半。
- 前端最小改动:Builder 列表请求带排除参数;Code 侧栏改读上面的来源。**不做更多前端**(那是 SP2)。

### 3.4 数据/迁移
- 不改 `AIChatSession.mode` 现有取值;只让它被**当真**(过滤 + 推导都认它)。
- 若 3.1.1 选「加 `workspace_id` 列」:一条加列迁移 + 回填(cutover 会话从 `workspace_dir` 反解一次性回填,失败的留空、运行时再反解)。
- 性能:`AIChatSession` 加 `(user_id, tenant_id, mode)` 复合索引(列表查询路径)。

---

## 4. 组件与接口(隔离单元)

| 单元 | 职责 | 依赖 | 测试 |
|---|---|---|---|
| `resolve_overrides_for_session(session)` | mode→(prompt, tools, ws_id);未知 mode→全 None | `resolve_profile`、`_cutover_tool_names`、`_resolve_ws_id_for_session` | 纯函数单测:code→dev-apaas 三元组;chat/cowork/None→全 None |
| `_resolve_ws_id_for_session(session)` | 会话→ws_id(反解或读列) | `WorkspaceManager` 或新列 | 单测:有/无 workspace_dir、坏路径 |
| `run_agent` 推导接线(改法 A) | 无显式 override 时从 session 补齐 + 设 `_locked_ws_id` | 上两者 | 集成:code 会话经 Builder 路由 → 走 dev-apaas 行为 |
| `list_sessions(modes=)` | 服务端 mode 过滤 | — | 集成:默认排除 code;显式要 code 能拿到 |
| `_load_session_or_404(allowed_modes=)` | 服务端 mode 守卫 | — | 集成:Builder 路由对 code 会话 404 |
| Code 会话列表来源 | 返回 mode='code' 行 | — | 集成:cutover 会话出现在 Code 侧栏 |
| 单 registry 接线 | cutover→ai_chat registry by session.id;attach 用 tenant 校验 | `ai_chat_run_registry` | 集成:Code run 在 Builder run-status 可见;attach 跨租户被拒 |

每个单元能独立理解/测试;改动集中在 `agents/profile.py`、`ai_chat/agent.py`、`routes/ai_chat.py`、`harness/profiles/coding.py`、`harness/manager.py`、`routes/coding.py`。

---

## 5. 控制流(目标态)

```
任一路由(Builder send / harness coding pipeline)
  → 载入 AIChatSession(带 mode)
  → run_agent(db, session, msg, ...)
       → 无显式 override 时 resolve_overrides_for_session(session)
            mode='code' → dev-apaas 提示词 + 收窄工具 + 锁 ws_id
            其它        → 通用 Builder(全量工具 / 默认提示词)
       → 注册到唯一 registry(by session.id)
  → 列表/加载按 kind 服务端收口(过渡期:Builder 不见 code,Code 见 code)
```

行为不再取决于「哪条路由发起」,而取决于「这是什么会话」。

## 6. 错误处理
- 未知 `mode` → 全 None → 安全退回通用 Builder 行为(不抛)。
- `resolve_profile` KeyError 已有守卫;`resolve_overrides_for_session` 只对已知映射调它。
- ws_id 反解失败 → 不设锁(降级为不锁,等同今天 Builder 路由现状,不更差),记 warning。
- registry 接线对 legacy 路径无影响(键空间不交叉)。

## 7. 测试策略
- **单元**:`resolve_overrides_for_session` 全分支;`_resolve_ws_id_for_session` 边角;dev-apaas 工具集快照不变(复用现有期望)。
- **集成(核心回归门)**:
  1. Builder 现有「读→写→build」链路:`mode='chat'` 会话经 Builder 路由,override 仍为 None,行为逐字节不变(防回归)。
  2. 功能混淆消失:`mode='code'` 会话经 Builder send → 实际走 dev-apaas(提示词 + 收窄工具 + ws-lock 生效)。
  3. 会话隔离:Builder list 默认不含 code;Builder per-session 路由对 code 会话 404;Code 列表来源含 cutover 会话。
  4. registry 一致:起一个 code run,Builder run-status 读到「在跑」;stop 从任一侧都命中。
- **真机**:桌面 cutover 路径手验一轮 code 会话不再串进 Builder 侧栏(后端改需重建 sidecar)。

## 8. 风险与回滚
- **主链路**:`run_agent`、`list_sessions`、`_load_session_or_404` 都是 load-bearing。改法 A 对 Builder 默认路径是 no-op(override 仍 None),回归面小。
- **过渡期措施会被 SP2 取代**:3.3 的「Builder 排除 code」在 SP2 合并为分组列表后移除——这是预期演进,不是债。
- **桌面打包**:后端改动需重建 sidecar 才进桌面 app;本地 `:8000` 仅 web 验证。
- **reload=False**:改后端必重启 `cd backend && .venv/bin/python run.py`。
- 每个目标(1/2/3)独立可上、独立可回滚;3 先上即止血。

## 9. 验收标准
- `mode='code'` 会话**不再**出现在 Builder 会话侧栏;cutover Code 会话**出现在** Code 侧栏。
- `mode='code'` 会话无论从哪条路由发送,都走 dev-apaas(提示词/工具/ws-lock),不再变成 Builder 全量行为。
- 同一会话的 run 状态在 Code 与 Builder 两侧一致(attach/stop/run-status 不互盲)。
- Builder 现有读→写→build 体验零回归(集成测试 1 绿)。
- 后端测试全绿;真机 cutover 手验通过。
