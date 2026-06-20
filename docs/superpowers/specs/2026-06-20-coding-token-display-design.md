# coding token 用量显示 + 换 session 提醒

> 2026-06-20 · 优化子项目 #2(共 4:#1 上下文管理[done] / **#2 token 显示+换 session 提醒** / #3 @skill 接入[done] / #4 handoff 结构化)。本 spec 只覆盖 #2。
> 用户拍板:① footer 小字「上下文 X% · 累计 N tok」(占用为主);② 一键换 session = 干净重置(调现成 createWorkspaceConversation,不带摘要);③ 占用 ≥80% 黄 / 超 90k(预算)红,本会话提醒一次。

## 背景与问题

coding agent 的 token 数据**已有但未透前端**:`BaseAgent._tokens_input/_tokens_output`(累计 LLM 消耗,`base.py:569-570` 累加,`from_snapshot` 恢复 `:441-442` → 会话级累计)+ `estimate_tokens(_messages)`(当前上下文占用,`token_estimate.py`)。`CodingAgent._context_token_budget = CODING_CONTEXT_TOKEN_BUDGET = 90_000`(`agent.py:43,164`,#1 的压缩触发线)。但 codegen 的 `done` 事件只 yield `{type, workspace_id, conversation_id}`,token 被丢(`pipeline.py:2301,2304`)→ 用户看不到用量、不知道该不该换 session。

「累计消耗」(只增)和「上下文占用」(压缩后回落)语义不同;判断「该换 session」用**占用**口径。换 session 机制已现成:`createWorkspaceConversation()`(`CodingPage.vue:969`,同工作区开新会话、上下文清零)。

## 目标

把 coding 当前会话的 token 用量透到前端常驻显示(footer),并在上下文占用逼近预算时弹一次「建议新建会话」告警 + 一键换 session。最小改动:后端只在 done 事件加字段(中间层透传),前端显示 + 告警。

**非目标**:会话列表/侧栏每会话用量(需扩 `CodingConversation` 模型 + 落库,留后续);给 coding 链路补 agent_run 观测埋点(那是更大工作,#2 走 SSE done 字段,不碰观测 API);read 路径不涉及。

## 复用现成件

- `CodingAgent`:`_tokens_input/_tokens_output`(base)、`_context_token_budget`(`agent.py:164`)、`estimate_tokens`(`agent.py:313` 已在 on_context_overflow lazy import)。
- done 事件透传链:`profiles/coding.py:233-244` done 分支 `{"kind":"system", **event}` 整个 event spread → ITEM_COMPLETED → `CodingSSEAdapter` passthrough → 前端 `useCodingPipeline.ts:338` `done` handler 收 `parsed.*`。**加字段即透传,中间层零改**(已核实)。
- `createWorkspaceConversation()`(`CodingPage.vue:969`)= 一键换 session 的动作。
- 文案视觉:可借 `AgentRunTraceDrawer.vue` 的「X tok / N in / M out」格式语言。

## 架构 — 四处接线

### 1. 后端:done 事件带 token(`backend/app/agents/coding/agent.py` + `backend/app/coding/pipeline.py`)
- `CodingAgent` 加方法:
  ```python
  def token_usage_snapshot(self) -> dict:
      from app.agents.token_estimate import estimate_tokens
      return {
          "tokens_input": self._tokens_input,
          "tokens_output": self._tokens_output,
          "context_tokens": estimate_tokens(self._messages),
          "context_budget": self._context_token_budget,
      }
  ```
- `pipeline.py` 两处 codegen done 事件(`:2301` 迭代/热重载分支、`:2304` 普通分支)把它 spread 进去:
  ```python
  yield _record_event({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id,
                       **_coding_agent.token_usage_snapshot()})
  ```
  (`_coding_agent` 在该 scope 可见;其余早退/brainstorm 的 done 事件无 agent、不动。)

### 2. 前端纯函数 util(`frontend/src/views/coding/contextUsage.ts`,新建)
- `formatTokenCount(n: number): string` —— <1000 原样;否则 `${(n/1000).toFixed(1).replace(/\.0$/, '')}k`(如 12345→"12.3k"、128000→"128k")。
- `contextRatio(contextTokens: number, budget: number): number` —— `budget > 0 ? contextTokens / budget : 0`。
- `contextLevel(ratio: number): 'ok' | 'warn' | 'danger'` —— `ratio >= 1 ? 'danger' : ratio >= 0.8 ? 'warn' : 'ok'`。
- 纯函数、可单测(vitest)。

### 3. 前端:store + done handler + footer 显示
- `stores/coding.ts`:加 `tokenUsage = ref<{ input: number; output: number; contextTokens: number; contextBudget: number } | null>(null)` + `contextWarnDismissed = ref(false)`;在已有 reset(`:162`)+ 切换会话处一并清零(换会话即重置告警「本会话一次」语义)。
- `useCodingPipeline.ts` `done` handler(`:338`):读 `parsed.context_budget != null` 时 `codingStore.tokenUsage = { input: parsed.tokens_input ?? 0, output: parsed.tokens_output ?? 0, contextTokens: parsed.context_tokens ?? 0, contextBudget: parsed.context_budget }`。
- `CodingPage.vue` footer-left(`:282`,model picker 那行)加小字:`上下文 {{pct}}% · 累计 {{formatTokenCount(input+output)}} tok`,`pct = Math.round(contextRatio(contextTokens, contextBudget) * 100)`;`tokenUsage` 为 null 时不显示;按 `contextLevel` 给文字颜色(ok 常规 / warn 橙 / danger 红)。

### 4. 前端:换 session 告警 banner(`CodingPage.vue`)
- 计算 `showContextWarning = tokenUsage && contextLevel(ratio) !== 'ok' && !contextWarnDismissed`。
- 在 chat-input-bar 区(`:257-258` 队列卡同款样式)条件渲染 ContextWarningBanner:文案「上下文较长({{pct}}%),建议新建会话以保持流畅」+「一键新建会话」按钮(`@click` → `createWorkspaceConversation()`)+ 关闭按钮(`@click` → `contextWarnDismissed = true`)。
- **本会话一次**:`contextWarnDismissed` 在切换/新建会话时重置(随 store reset),同会话内关一次后不再每轮重弹。

## 数据流

agent 跑完 → done 事件带 `tokens_input/output/context_tokens/context_budget` → profile `**event` → SSEAdapter → 前端 `done` handler 写 `codingStore.tokenUsage` → footer 实时显示占用% + 累计 tok;占用 ≥80% 且未关 → 弹 banner →「一键新建会话」调 `createWorkspaceConversation()` 上下文清零、store reset、告警消失。

## 错误处理

- done 事件缺 token 字段(老路径/早退 done)→ 前端 `parsed.context_budget == null` 不更新 tokenUsage(保持上次或 null),footer 不报错。
- `context_budget = 0`(不应发生)→ `contextRatio` 返 0 → level ok,无告警(除零安全)。
- `estimate_tokens` 失败 → 它内部已有字符兜底(#1),不抛。

## 测试

- `test_coding_token_usage_snapshot.py`:构造 CodingAgent(set `_messages`/`_tokens_input`/`_tokens_output`),`token_usage_snapshot()` 返 4 字段且 `context_tokens > 0`、`context_budget == 90000`。
- `contextUsage.spec.ts`:`formatTokenCount`(0/999/1234/128000/1.2M)、`contextRatio`(除零)、`contextLevel`(0.5→ok / 0.8→warn / 1.0→danger / 1.2→danger 边界)。
- `CodingPage.token.spec.ts`(源码串):footer 含「上下文」+「累计」+ `formatTokenCount`;banner 含「建议新建会话」+「一键新建会话」按钮 + `createWorkspaceConversation` + `contextWarnDismissed`。
- 全量 backend + 前端相关回归。

## 风险

1. **done 透传**:已核实 profile done 分支 `**event` 整体 spread + SSEAdapter passthrough,加字段即到前端(非 run_result 那种无 elif 被丢的情形)。Task 1 仍读一遍确认。
2. **footer 空间**:model picker 那行已有内容,token 小字要克制(单行省略、窄屏可隐藏次要的「累计」段,保留「占用%」)。
3. **「累计」口径**:`_tokens_input/output` 经 from_snapshot 恢复=会话级累计(跨轮),非单轮——这正是「累计消耗」想要的;footer 标注「累计」避免误解为单轮。
4. **告警频率**:`contextWarnDismissed` 必须随会话切换重置,否则换了会话还记得「已关」→ 新会话不再告警(应重新计)。
