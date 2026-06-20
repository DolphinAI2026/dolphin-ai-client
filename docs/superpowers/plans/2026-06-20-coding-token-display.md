# coding token 用量显示 + 换 session 提醒 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** coding 会话在输入框 footer 常驻显示「上下文 X% · 累计 N tok」,占用逼近预算时弹一次「建议新建会话」告警 + 一键换 session。

**Architecture:** 后端只在两处 codegen `done` 事件 spread `CodingAgent.token_usage_snapshot()`(中间层已透传,零改);前端纯函数 util 算占用%/级别,store 存 tokenUsage,done handler 写入,CodingPage footer 显示 + 告警 banner(调现成 `createWorkspaceConversation`)。

**Tech Stack:** Python 3.13 / pytest(asyncio_mode=auto,**不写 `@pytest.mark.asyncio`**);Vue 3 `<script setup>` / vitest(`environment: node`,组件靠 `?raw` 源码串断言、纯函数直接单测)。

## Global Constraints

- 后端 token 字段**只加到两处 codegen `done` 事件**(`pipeline.py` 约 `:2301` 迭代/热重载分支 + `:2304` 普通分支,即 `_coding_agent` 已存在的 done);其余早退/brainstorm 的 `done` 不动(那时无 agent、无 token)。
- **不新增 SSE 事件类型**——复用现有 `done`(profile `:233-244` 已 `{"kind":"system", **event}` 整体 spread,加字段即透传)。不改 `profiles/coding.py` / SSEAdapter。
- 阈值固定:`contextLevel` = `ratio>=1 ? 'danger' : ratio>=0.8 ? 'warn' : 'ok'`(占用≥80% 黄、≥100%(超 90k 预算)红)。
- 一键换 session = 调现成 `createWorkspaceConversation()`(`CodingPage.vue:969`),**不带上一会话摘要**(干净重置)。
- `contextWarnDismissed` 必须随会话切换/新建**重置**(随 store reset),实现「本会话提醒一次」。
- **不碰** `CodingConversation` 模型 / DB / 会话列表用量(本期非目标)。
- `tokenUsage` 为 null(未跑过/老 done)时 footer 不显示、不报错;`context_budget==0` 时 ratio 取 0(除零安全)。
- 测试命令:后端 `cd backend && ./.venv/bin/python -m pytest <path> -v`;前端 `cd frontend && npx vitest run <path>`。

---

## Task 1: 后端 done 事件带 token

**Files:**
- Modify: `backend/app/agents/coding/agent.py`(加 `token_usage_snapshot` 方法)
- Modify: `backend/app/coding/pipeline.py`(两处 codegen done 事件 spread)
- Test: `backend/tests/test_coding_token_usage_snapshot.py`

**Interfaces:**
- Produces: `CodingAgent.token_usage_snapshot(self) -> dict` 返回 `{"tokens_input": int, "tokens_output": int, "context_tokens": int, "context_budget": int}`;两处 done 事件 data 含这 4 键。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_coding_token_usage_snapshot.py`(构造方式取自 `test_coding_context_overflow.py:_agent()`):

```python
from app.agents.coding.agent import CodingAgent
from app.agents.types import AgentContext


def _make_agent():
    ctx = AgentContext(
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        session_id="s",
        model="gpt-4o",   # required field
        input={},
    )
    return CodingAgent(ctx)


def test_token_usage_snapshot_shape_and_values():
    agent = _make_agent()
    agent._messages = [
        {"role": "system", "content": "x" * 100},
        {"role": "user", "content": "帮我加个字段" * 50},
    ]
    agent._tokens_input = 1234
    agent._tokens_output = 567

    snap = agent.token_usage_snapshot()

    assert set(snap) == {"tokens_input", "tokens_output", "context_tokens", "context_budget"}
    assert snap["tokens_input"] == 1234
    assert snap["tokens_output"] == 567
    assert snap["context_budget"] == 90000  # CODING_CONTEXT_TOKEN_BUDGET
    assert snap["context_tokens"] > 0       # estimate_tokens(_messages) 非空


def test_token_usage_snapshot_empty_messages():
    agent = _make_agent()
    agent._messages = []
    agent._tokens_input = 0
    agent._tokens_output = 0
    snap = agent.token_usage_snapshot()
    assert snap["context_tokens"] == 0
    assert snap["context_budget"] == 90000
```

`_make_agent()` 用 `test_coding_context_overflow.py` 里已验证的 `CodingAgent` 构造方式补全(AgentContext 的必填字段照搬)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_token_usage_snapshot.py -v`
Expected: FAIL(`AttributeError: 'CodingAgent' object has no attribute 'token_usage_snapshot'`)。

- [ ] **Step 3: 写方法**

在 `backend/app/agents/coding/agent.py` 的 `CodingAgent` 类里(靠近 `on_context_overflow`,它已用 `estimate_tokens` + `_context_token_budget`)新增:

```python
    def token_usage_snapshot(self) -> dict:
        """当前 token 用量快照:累计 LLM 消耗 + 当前上下文占用 + 预算。供 done 事件透前端(#2)。"""
        from app.agents.token_estimate import estimate_tokens
        return {
            "tokens_input": self._tokens_input,
            "tokens_output": self._tokens_output,
            "context_tokens": estimate_tokens(self._messages),
            "context_budget": self._context_token_budget,
        }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_token_usage_snapshot.py -v`
Expected: 2 passed。

- [ ] **Step 5: 两处 done 事件 spread token**

在 `backend/app/coding/pipeline.py` 找到 codegen 段尾的两处 done 事件(约 `:2301` 迭代/热重载分支 + `:2304` 普通分支,形如 `yield _record_event({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id})`)。**确认两处的上文都有 `_coding_agent` 在 scope**(它在该生成函数体内创建)。把每处改成:

```python
            yield _record_event({"type": "done", "workspace_id": ws_id, "conversation_id": conversation_id,
                                 **_coding_agent.token_usage_snapshot()})
```

(保持各自原有缩进。**只改这两处 done**;`pipeline.py` 里其它 `{"type": "done", ...}`(早退/brainstorm,约 L1613/1817/1974/1990/2044…)**不动**——那时无 `_coding_agent`。)

- [ ] **Step 6: 确认 done 透传未被中间层丢(读一遍,不改)**

读 `backend/app/harness/profiles/coding.py` 的 done 分支(约 `:233-244`):应是 `await event_bus.publish(ITEM_COMPLETED, ..., {"kind": "system", **event}, item_kind="system")` —— `**event` 把新 token 字段整体带上。确认无字段白名单过滤(若发现 done 被重构成固定子集,需在此把 token 字段补上并在报告里说明)。**预期:无需改,只确认。**

- [ ] **Step 7: 后端相关回归**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_token_usage_snapshot.py tests/test_coding_context_overflow.py tests/test_coding_pipeline_persist_state.py -v`
Expected: 全 passed(token 快照不破坏 #1 的压缩/持久化)。

- [ ] **Step 8: Commit**

```bash
git add backend/app/agents/coding/agent.py backend/app/coding/pipeline.py backend/tests/test_coding_token_usage_snapshot.py
git commit -m "feat(coding): done 事件带 token 用量快照(累计消耗+上下文占用+预算)"
```

---

## Task 2: 前端 contextUsage 纯函数 util

**Files:**
- Create: `frontend/src/views/coding/contextUsage.ts`
- Test: `frontend/src/views/coding/contextUsage.spec.ts`

**Interfaces:**
- Produces: `formatTokenCount(n: number): string`、`contextRatio(contextTokens: number, budget: number): number`、`contextLevel(ratio: number): 'ok' | 'warn' | 'danger'`。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/views/coding/contextUsage.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { formatTokenCount, contextRatio, contextLevel } from './contextUsage'

describe('formatTokenCount', () => {
  it('小于 1000 原样', () => { expect(formatTokenCount(0)).toBe('0'); expect(formatTokenCount(999)).toBe('999') })
  it('千位带 k 一位小数、去 .0', () => {
    expect(formatTokenCount(1234)).toBe('1.2k')
    expect(formatTokenCount(128000)).toBe('128k')
    expect(formatTokenCount(12345)).toBe('12.3k')
  })
})

describe('contextRatio', () => {
  it('正常比值', () => { expect(contextRatio(45000, 90000)).toBeCloseTo(0.5) })
  it('除零安全', () => { expect(contextRatio(100, 0)).toBe(0) })
})

describe('contextLevel', () => {
  it('分档边界', () => {
    expect(contextLevel(0.5)).toBe('ok')
    expect(contextLevel(0.79)).toBe('ok')
    expect(contextLevel(0.8)).toBe('warn')
    expect(contextLevel(0.99)).toBe('warn')
    expect(contextLevel(1.0)).toBe('danger')
    expect(contextLevel(1.5)).toBe('danger')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/coding/contextUsage.spec.ts`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 写 util**

创建 `frontend/src/views/coding/contextUsage.ts`:

```ts
// coding 上下文用量纯函数(token 显示 + 换 session 告警,#2)。

/** 格式化 token 数:<1000 原样;否则千位带 k(一位小数、去尾 .0)。 */
export function formatTokenCount(n: number): string {
  if (n < 1000) return `${n}`
  return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`
}

/** 当前上下文占用比 = contextTokens / budget;budget<=0 时返 0(除零安全)。 */
export function contextRatio(contextTokens: number, budget: number): number {
  return budget > 0 ? contextTokens / budget : 0
}

/** 占用级别:>=1 危险(超预算/压缩线) / >=0.8 警告 / 否则正常。 */
export function contextLevel(ratio: number): 'ok' | 'warn' | 'danger' {
  if (ratio >= 1) return 'danger'
  if (ratio >= 0.8) return 'warn'
  return 'ok'
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/views/coding/contextUsage.spec.ts`
Expected: 全 passed。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/coding/contextUsage.ts frontend/src/views/coding/contextUsage.spec.ts
git commit -m "feat(coding): contextUsage 纯函数(token 格式化/占用比/级别)"
```

---

## Task 3: 前端 store + done handler + footer 显示

**Files:**
- Modify: `frontend/src/stores/coding.ts`(加 `tokenUsage` + `contextWarnDismissed` + reset + 导出)
- Modify: `frontend/src/views/coding/useCodingPipeline.ts`(done handler 写 tokenUsage)
- Modify: `frontend/src/views/CodingPage.vue`(footer 显示 + 计算属性 + import util)
- Test: `frontend/src/views/CodingPage.token.spec.ts`

**Interfaces:**
- Consumes: Task 2 的 `formatTokenCount`/`contextRatio`/`contextLevel`;Task 1 透出的 `parsed.tokens_input/tokens_output/context_tokens/context_budget`。
- Produces: `codingStore.tokenUsage`(`{input,output,contextTokens,contextBudget} | null`)+ `codingStore.contextWarnDismissed`(bool);CodingPage footer 显示「上下文 X% · 累计 N tok」+ 计算属性 `ctxRatio`/`ctxPct`/`ctxLevel`/`cumTokenText`(供 Task 4 复用)。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/views/CodingPage.token.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'
import storeSrc from '../stores/coding?raw'
import pipeSrc from './coding/useCodingPipeline.ts?raw'

describe('CodingPage token 显示接线', () => {
  it('store 有 tokenUsage + contextWarnDismissed', () => {
    expect(storeSrc).toMatch(/tokenUsage/)
    expect(storeSrc).toMatch(/contextWarnDismissed/)
  })
  it('done handler 写 tokenUsage(读 context_budget)', () => {
    expect(pipeSrc).toContain('context_budget')
    expect(pipeSrc).toMatch(/tokenUsage/)
  })
  it('CodingPage import util + footer 显示上下文/累计', () => {
    expect(src).toContain("from './coding/contextUsage'")
    expect(src).toContain('上下文')
    expect(src).toContain('累计')
    expect(src).toMatch(/formatTokenCount/)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/CodingPage.token.spec.ts`
Expected: FAIL。

- [ ] **Step 3: store 加状态**

在 `frontend/src/stores/coding.ts`:
(a) 在 ref 声明区(约 `:49-76`)加:
```ts
  const tokenUsage = ref<{ input: number; output: number; contextTokens: number; contextBudget: number } | null>(null)
  const contextWarnDismissed = ref(false)
```
(b) 在 reset 函数(约 `:162`,把状态清零的那个)里加:
```ts
    tokenUsage.value = null
    contextWarnDismissed.value = false
```
(c) 在 store `return { ... }`(约 `:178`)里把 `tokenUsage, contextWarnDismissed` 加入导出。

- [ ] **Step 4: done handler 写 tokenUsage**

在 `frontend/src/views/coding/useCodingPipeline.ts` 的 `done` handler(约 `:338`)体内加(在现有 done 逻辑里,任意靠前位置):
```ts
      if (parsed.context_budget != null) {
        codingStore.tokenUsage = {
          input: parsed.tokens_input ?? 0,
          output: parsed.tokens_output ?? 0,
          contextTokens: parsed.context_tokens ?? 0,
          contextBudget: parsed.context_budget,
        }
      }
```
(`codingStore` 在该文件已可用——它消费 store;若变量名不同,用文件里现有的 store 引用名。)

- [ ] **Step 5: CodingPage 计算属性 + footer 显示**

在 `frontend/src/views/CodingPage.vue` `<script setup>`:
(a) import:
```ts
import { formatTokenCount, contextRatio, contextLevel } from './coding/contextUsage'
```
(b) 计算属性(放在其它 computed 附近;`codingStore` 已在文件中):
```ts
const ctxRatio = computed(() => {
  const u = codingStore.tokenUsage
  return u ? contextRatio(u.contextTokens, u.contextBudget) : 0
})
const ctxPct = computed(() => Math.round(ctxRatio.value * 100))
const ctxLevel = computed(() => contextLevel(ctxRatio.value))
const cumTokenText = computed(() => {
  const u = codingStore.tokenUsage
  return u ? formatTokenCount(u.input + u.output) : ''
})
```
(c) 模板 footer-left(约 `:282`,model picker 同一 slot 内)加(放 model picker 之后):
```html
                <span
                  v-if="codingStore.tokenUsage"
                  class="coding-token-usage"
                  :class="`lvl-${ctxLevel}`"
                  :title="`当前上下文占用 ${ctxPct}%(预算 ${codingStore.tokenUsage.contextBudget} tok)· 本会话累计 ${cumTokenText} tok`"
                >上下文 {{ ctxPct }}% · 累计 {{ cumTokenText }} tok</span>
```
(d) `<style scoped>` 加:
```css
.coding-token-usage { margin-left: 10px; font-size: 12px; color: var(--text-3, #888); white-space: nowrap; }
.coding-token-usage.lvl-warn { color: #d48806; }
.coding-token-usage.lvl-danger { color: #cf1322; }
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/views/CodingPage.token.spec.ts src/views/coding/contextUsage.spec.ts`
Expected: 全 passed。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/coding.ts frontend/src/views/coding/useCodingPipeline.ts frontend/src/views/CodingPage.vue frontend/src/views/CodingPage.token.spec.ts
git commit -m "feat(coding): footer 显示 token 用量(上下文占用% + 累计 tok)"
```

---

## Task 4: 换 session 告警 banner + 一键换 session

**Files:**
- Modify: `frontend/src/views/CodingPage.vue`(告警 banner + showContextWarning + dismiss)
- Test: `frontend/src/views/CodingPage.contextwarn.spec.ts`

**Interfaces:**
- Consumes: Task 3 的 `ctxLevel`/`ctxPct` 计算属性、`codingStore.tokenUsage`/`contextWarnDismissed`、现成 `createWorkspaceConversation()`(`:969`)。
- Produces: `showContextWarning` 计算属性 + `dismissContextWarn()` + chat-input-bar 区的告警 banner。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/views/CodingPage.contextwarn.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'

describe('CodingPage 换 session 告警', () => {
  it('有 showContextWarning 计算 + 依赖 contextWarnDismissed/ctxLevel', () => {
    expect(src).toMatch(/showContextWarning/)
    expect(src).toContain('contextWarnDismissed')
    expect(src).toMatch(/ctxLevel/)
  })
  it('banner 文案 + 一键新建会话按钮调 createWorkspaceConversation', () => {
    expect(src).toContain('建议新建会话')
    expect(src).toContain('一键新建会话')
    expect(src).toMatch(/createWorkspaceConversation/)
  })
  it('有关闭告警的处理', () => {
    expect(src).toMatch(/dismissContextWarn/)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/CodingPage.contextwarn.spec.ts`
Expected: FAIL。

- [ ] **Step 3: computed + dismiss**

在 `frontend/src/views/CodingPage.vue` `<script setup>`(Task 3 的 computed 之后)加:
```ts
const showContextWarning = computed(
  () => !!codingStore.tokenUsage && ctxLevel.value !== 'ok' && !codingStore.contextWarnDismissed,
)
function dismissContextWarn() {
  codingStore.contextWarnDismissed = true
}
```

- [ ] **Step 4: banner 模板**

在 `frontend/src/views/CodingPage.vue` 的 chat-input-bar 区(约 `:257-258`,队列提示卡附近、输入框上方)加:
```html
            <div v-if="showContextWarning" class="ctx-warn-banner" :class="`lvl-${ctxLevel}`">
              <span class="ctx-warn-text">上下文较长({{ ctxPct }}%),建议新建会话以保持流畅</span>
              <button class="ctx-warn-new" @click="createWorkspaceConversation">一键新建会话</button>
              <button class="ctx-warn-close" title="本会话不再提醒" @click="dismissContextWarn">
                <AppIcon name="x" :size="14" />
              </button>
            </div>
```
(`AppIcon` 在 CodingPage 已 import——队列卡的清空按钮已用 `<AppIcon name="x">`。)

- [ ] **Step 5: banner 样式**

`<style scoped>` 加:
```css
.ctx-warn-banner { display: flex; align-items: center; gap: 10px; padding: 6px 12px; margin-bottom: 8px;
  border-radius: 8px; font-size: 12px; background: #fffbe6; border: 1px solid #ffe58f; color: #d48806; }
.ctx-warn-banner.lvl-danger { background: #fff1f0; border-color: #ffccc7; color: #cf1322; }
.ctx-warn-text { flex: 1; }
.ctx-warn-new { font-size: 12px; padding: 3px 10px; border-radius: 6px; cursor: pointer;
  border: 1px solid currentColor; background: transparent; color: inherit; }
.ctx-warn-close { display: inline-flex; padding: 2px; border: 0; background: transparent; cursor: pointer; color: inherit; opacity: .7; }
.ctx-warn-close:hover { opacity: 1; }
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/views/CodingPage.contextwarn.spec.ts`
Expected: 全 passed。

- [ ] **Step 7: 类型检查(不阻断,仅看本文件无新错)**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep -E "CodingPage|contextUsage|coding.ts" || echo "no new type error"`
Expected: 不新增本功能相关类型错(仓库 `npm run build` 预存类型错,无关本任务)。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/CodingPage.vue frontend/src/views/CodingPage.contextwarn.spec.ts
git commit -m "feat(coding): 上下文过长告警 banner + 一键新建会话(本会话提醒一次)"
```

---

## Final Verification(全部 task 后)

- [ ] 后端:`cd backend && ./.venv/bin/python -m pytest -q` → passed 数 = 改前(1189)+ 新增(test_coding_token_usage_snapshot 2),0 failed。
- [ ] 前端:`cd frontend && npx vitest run src/views/coding/contextUsage.spec.ts src/views/CodingPage.token.spec.ts src/views/CodingPage.contextwarn.spec.ts` → 全 passed。
- [ ] (人工/真机,与 #1/#3 一并)/coding 跑一轮 → footer 出现「上下文 X% · 累计 N tok」;多轮堆到 ≥80% → 弹告警 banner → 点「一键新建会话」→ 上下文清零、告警消失、footer 归位。

## Self-Review(已对 spec 核查)

- **Spec 覆盖**:后端透 token(Task 1)/ 纯函数(Task 2)/ store+display(Task 3)/ 告警 banner+一键换 session(Task 4)/ 阈值(Task 2 contextLevel)/ 本会话一次(Task 3 reset + Task 4 dismiss)全有任务。
- **Placeholder 扫描**:无 TBD;每步含完整代码(Task 1 `_make_agent()` 已内联自 `test_coding_context_overflow.py:_agent()`)。
- **类型一致**:`tokenUsage` 形状 `{input,output,contextTokens,contextBudget}` 在 Task 1(后端键名 tokens_input/tokens_output/context_tokens/context_budget)→ Task 3 done handler 映射 → store → CodingPage 一致;`ctxRatio/ctxPct/ctxLevel`(Task 3)被 Task 4 `showContextWarning` 复用,名字一致。
