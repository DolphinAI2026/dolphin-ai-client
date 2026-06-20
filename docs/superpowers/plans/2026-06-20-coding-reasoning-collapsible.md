# coding 思维链(reasoning)单独可折叠 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 coding agent 的 reasoning_content(思维链)从答案里拆出来,渲染成默认收起的「💭 思考过程」可折叠卡,消除「对话重复 + 英文推理泄漏」(根因 = reasoning 与 content 被拼在一起当答案显示)。

**Architecture:** 后端不再拼接 reasoning+content(`agent.py` 拆成两个 agent_thinking aggregate)、harness profile 透传 `reasoning` 标志;前端按标志把 reasoning 路由到独立的 reasoning streamMessage,CodingPage 映射成 custom kind,custom slot 渲染默认收起的折叠卡。

**Tech Stack:** Python 3.13 / pytest(asyncio_mode=auto,**不写 `@pytest.mark.asyncio`**);Vue 3 `<script setup>` / vitest(`environment: node`,源码串/纯函数断言)。

## Global Constraints

- 只影响 codegen 路径(`CodingAgent._call_llm` 有 reasoning_content);读路径 `run_read_query` 无 reasoning,不动。
- **后端不再拼接 reasoning+content**:aggregate 拆成 content 一个、reasoning 一个(带 `reasoning` 标志)。delta 侧 `_emit_stream_delta` 已带 `reasoning:True`(`agent.py:609-612`),不改。
- **harness profile 必须透传 `reasoning` 标志**(`profiles/coding.py:99-110` 当前只取 content、丢标志 = 前端分流的前置阻塞点)。
- 前端 reasoning 卡**默认收起**(collapsed=true);content/答案展示不变。
- 向后兼容:无 reasoning 的模型 → 无 reasoning 卡,行为同今(profile `reasoning` 缺省 False、前端 falsy 走 thinking)。
- 测试命令:后端 `cd backend && ./.venv/bin/python -m pytest <path> -v`;前端 `cd frontend && npx vitest run <path>`。

---

## Task 1: 后端拆 aggregate(不再拼接 reasoning+content)

**Files:**
- Modify: `backend/app/agents/coding/agent.py`(`_call_llm` 末尾 `:596-598`)
- Test: `backend/tests/test_coding_reasoning_split.py`

**Interfaces:**
- Produces: `_call_llm` 流式结束时,有 reasoning_content 则**分别** publish 两个 `agent_thinking`:一个 `{content: full_content}`(无 reasoning 标志)、一个 `{content: reasoning_content, reasoning: True}`;只有 content 时只 publish 一个(无标志);只有 reasoning 时只 publish reasoning 那个。**不再 `reasoning_content + full_content` 拼接。**

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_coding_reasoning_split.py`。构造一个最小 `CodingAgent`(同 `test_coding_context_overflow.py:_agent()`),mock `ctx.llm_client.chat_completion_stream` 产出 content + reasoning_content 两类 delta,捕获 `_publish` 的调用,断言拆分:

```python
from app.agents.coding.agent import CodingAgent
from app.agents.types import AgentContext


def _agent():
    ctx = AgentContext(conversation_id=1, user_id=1, tenant_id=1, session_id="s", model="gpt-4o", input={})
    return CodingAgent(ctx)


class _FakeLLM:
    def __init__(self, chunks):
        self._chunks = chunks
    async def chat_completion_stream(self, *a, **k):
        for c in self._chunks:
            yield c


async def _collect_thinking(agent):
    """跑 _call_llm,收集所有 agent_thinking publish 的 (content, reasoning?) 。"""
    seen = []
    orig = agent._publish
    async def _spy(event_type, data):
        if event_type == "agent_thinking":
            seen.append((data.get("content"), bool(data.get("reasoning"))))
        return await orig(event_type, data) if False else None  # 不真正发布
    agent._publish = _spy
    await agent._call_llm()
    return seen


async def test_reasoning_and_content_split_into_two_aggregates():
    agent = _agent()
    agent.ctx.llm_client = _FakeLLM([
        {"choices": [{"delta": {"reasoning_content": "我先想想"}}]},
        {"choices": [{"delta": {"content": "这是答案"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    seen = await _collect_thinking(agent)
    # 两个独立 aggregate:content(无标志)+ reasoning(带标志);内容不拼接
    assert ("这是答案", False) in seen
    assert ("我先想想", True) in seen
    assert all(c != "我先想想这是答案" and c != "这是答案我先想想" for c, _ in seen)


async def test_only_content_emits_single_aggregate_no_reasoning_flag():
    agent = _agent()
    agent.ctx.llm_client = _FakeLLM([
        {"choices": [{"delta": {"content": "纯答案"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])
    seen = await _collect_thinking(agent)
    assert seen == [("纯答案", False)]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_reasoning_split.py -v`
Expected: FAIL(当前拼接成一个 aggregate,断言不满足)。

- [ ] **Step 3: 改 aggregate(拆分)**

`backend/app/agents/coding/agent.py` 把 `:596-598`(`combined_thinking = (reasoning_content or "") + (full_content or "")` + `if combined_thinking: await self._publish("agent_thinking", {"content": combined_thinking})`)替换为:

```python
        # 拆分: content(答案/narration)与 reasoning(思维链)各发一个 aggregate, 不再拼接。
        # 前端按 reasoning 标志分流: content → thinking 卡, reasoning → 折叠「思考过程」卡。
        if full_content:
            await self._publish("agent_thinking", {"content": full_content})
        if reasoning_content:
            await self._publish("agent_thinking", {"content": reasoning_content, "reasoning": True})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_reasoning_split.py -v`
Expected: 2 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/coding/agent.py backend/tests/test_coding_reasoning_split.py
git commit -m "fix(coding): reasoning 与 content 各发独立 agent_thinking(不再拼接=修对话重复根因)"
```

---

## Task 2: harness profile 透传 reasoning 标志

**Files:**
- Modify: `backend/app/harness/profiles/coding.py`(`:99-110` agent_thinking_delta + agent_thinking 转发)
- Test: `backend/tests/test_harness_coding_reasoning_flag.py`

**Interfaces:**
- Produces: profile 转发 `agent_thinking_delta` / `agent_thinking` 时,publish 的 data 含 `reasoning: bool(event.get("reasoning"))`(供前端分流)。

- [ ] **Step 1: 写失败测试**

参考已有 `backend/tests/test_harness_coding_*.py` 的假 EventBus 套路(找一个现成的 `test_harness_coding_run_result_forwarding.py` 之类镜像)。新建 `backend/tests/test_harness_coding_reasoning_flag.py`:断言 profile 处理带 `reasoning:True` 的 `agent_thinking_delta` 事件时,publish 出去的 data 含 `reasoning: True`;不带 reasoning 的事件 publish 出 `reasoning: False`。

```python
# 镜像现有 harness profile 测试的假 bus 构造(读 test_harness_coding_run_result_forwarding.py)。
# 核心断言(伪代码,按现有测试的 bus 捕获方式落实):
#   feed CodingProfile 一个 {"type":"agent_thinking_delta","content":"x","reasoning":True}
#   → 捕获 event_bus.publish 的 payload, 断言 payload 含 "reasoning": True
#   feed {"type":"agent_thinking_delta","content":"y"} → payload["reasoning"] is False
```
(实现时按该目录现有 harness 测试的真实 fixture 写全;断言点 = publish 的 ITEM_DELTA payload 含 `reasoning`。)

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_harness_coding_reasoning_flag.py -v`
Expected: FAIL(当前 payload 不含 reasoning)。

- [ ] **Step 3: 改 profile 透标志**

`backend/app/harness/profiles/coding.py` `:99-110`,两处 publish 的 payload 加 `reasoning`:
```python
                if event_type == "agent_thinking_delta":
                    await event_bus.publish(
                        ITEM_DELTA, turn_ctx.turn_id,
                        {"kind": "thinking", "text": event.get("content", ""), "reasoning": bool(event.get("reasoning"))},
                        item_kind="thinking", persist=False,
                    )
                elif event_type == "agent_thinking":
                    await event_bus.publish(
                        ITEM_COMPLETED if False else ITEM_DELTA, turn_ctx.turn_id,  # 保持原 ITEM_* 不变
                        {"kind": "thinking", "text": event.get("content", ""), "reasoning": bool(event.get("reasoning"))},
                        item_kind="thinking",
                    )
```
⚠️ 保持原有的 ITEM_* 常量与 `persist` 参数不变(只在 payload dict 里加 `reasoning` 字段)。读现有代码确认 agent_thinking 用的是哪个 ITEM_*,照旧。

- [ ] **Step 4: 跑测试确认通过 + 确认 SSEAdapter 透传**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_harness_coding_reasoning_flag.py -v`
Expected: passed。
读 `backend/app/harness/sse_adapter.py` 确认 thinking item 的 payload 原样透传到前端(含新加的 `reasoning` 字段),不被字段白名单过滤;若被过滤则在此补上并在报告说明。

- [ ] **Step 5: Commit**

```bash
git add backend/app/harness/profiles/coding.py backend/tests/test_harness_coding_reasoning_flag.py
git commit -m "feat(coding): harness profile 透传 reasoning 标志(供前端分流思维链)"
```

---

## Task 3: 前端按 reasoning 标志分流

**Files:**
- Modify: `frontend/src/views/coding/useStreamMessages.ts`(加 `appendToLastReasoning`,镜像 `appendToLastThinking`)
- Modify: `frontend/src/views/coding/useCodingPipeline.ts`(`agent_thinking` / `agent_thinking_delta` 按 `parsed.reasoning` 分流)
- Test: `frontend/src/views/coding/useCodingPipeline.reasoning.spec.ts`

**Interfaces:**
- Consumes: `parsed.reasoning`(Task 2 透出);`appendToLastThinking`(现有)。
- Produces: `appendToLastReasoning(delta)`(找/建 `type==='reasoning'` 的 streamMessage);`agent_thinking_delta`/`agent_thinking` 处理器按 reasoning 标志路由到 reasoning 卡 vs thinking 卡。

- [ ] **Step 1: 写失败测试(源码串)**

创建 `frontend/src/views/coding/useCodingPipeline.reasoning.spec.ts`:断言 useCodingPipeline 源码里 `agent_thinking_delta`/`agent_thinking` 处理器引用 `parsed.reasoning` 并调用 `appendToLastReasoning`;useStreamMessages 源码含 `appendToLastReasoning` 且找 `'reasoning'` 类型。

```ts
import { describe, it, expect } from 'vitest'
import pipeSrc from './useCodingPipeline.ts?raw'
import streamSrc from './useStreamMessages.ts?raw'

describe('reasoning 分流', () => {
  it('useStreamMessages 有 appendToLastReasoning(找/建 reasoning 卡)', () => {
    expect(streamSrc).toMatch(/appendToLastReasoning/)
    expect(streamSrc).toContain("'reasoning'")
  })
  it('useCodingPipeline 按 parsed.reasoning 分流', () => {
    expect(pipeSrc).toMatch(/parsed\.reasoning/)
    expect(pipeSrc).toMatch(/appendToLastReasoning/)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/coding/useCodingPipeline.reasoning.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 加 appendToLastReasoning**

`frontend/src/views/coding/useStreamMessages.ts`:照 `appendToLastThinking` 写一个 `appendToLastReasoning(delta: string)`——若最后一条 `type === 'reasoning'` 则追加,否则 `addStreamMsg({ type: 'reasoning', content: delta, collapsed: true })`。导出它(与 appendToLastThinking 同处导出)。

- [ ] **Step 4: useCodingPipeline 分流**

`frontend/src/views/coding/useCodingPipeline.ts`:
(a) import 区把 `appendToLastReasoning` 加进从 useStreamMessages 解构的列表(`:71` 附近)。
(b) `agent_thinking_delta`(`:322`):
```ts
    agent_thinking_delta: (parsed) => {
      const delta = (parsed.content || '') as string
      if (!delta) return
      if (parsed.reasoning) appendToLastReasoning(delta)
      else appendToLastThinking(delta)
    },
```
(c) `agent_thinking`(`:300`):开头按标志分流——`reasoning` 走 reasoning 卡的「长度兜底补齐」,否则走原 thinking 逻辑:
```ts
    agent_thinking: (parsed) => {
      const text = (parsed.content || '') as string
      if (!text.trim()) return
      if (parsed.reasoning) {
        const last = streamMessages.value[streamMessages.value.length - 1]
        if (last?.type === 'reasoning') { if (last.content.length < text.length) last.content = text; return }
        addStreamMsg({ type: 'reasoning', content: text, collapsed: true })
        return
      }
      // ... 原有 content thinking 逻辑(last?.type==='thinking' 长度兜底 / fallback 新建 thinking)不变
    },
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/views/coding/useCodingPipeline.reasoning.spec.ts`
Expected: passed。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/coding/useStreamMessages.ts frontend/src/views/coding/useCodingPipeline.ts frontend/src/views/coding/useCodingPipeline.reasoning.spec.ts
git commit -m "feat(coding): 前端按 reasoning 标志把思维链分流到独立卡"
```

---

## Task 4: CodingPage 映射 + 折叠卡渲染

**Files:**
- Modify: `frontend/src/views/CodingPage.vue`(streamCustom 映射加 reasoning → custom kind;custom slot 加 reasoning 折叠分支)
- Test: `frontend/src/views/CodingPage.reasoning.spec.ts`

**Interfaces:**
- Consumes: `type === 'reasoning'` 的 streamMessage(Task 3 产出,带 `collapsed`)。
- Produces: reasoning 渲染成默认收起的「💭 思考过程」折叠卡(点击头切换 collapsed)。

- [ ] **Step 1: 写失败测试(源码串)**

创建 `frontend/src/views/CodingPage.reasoning.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import src from './CodingPage.vue?raw'

describe('CodingPage 思维链折叠卡', () => {
  it('reasoning 类型映射成 custom kind', () => {
    expect(src).toMatch(/msg\.type === 'reasoning'/)
    expect(src).toContain("kind: 'custom'")
  })
  it('custom slot 有 reasoning 折叠分支 + 思考过程 文案', () => {
    expect(src).toMatch(/streamCustom\(message\)\.sm\.type === 'reasoning'/)
    expect(src).toContain('思考过程')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/CodingPage.reasoning.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 映射 reasoning → custom**

`frontend/src/views/CodingPage.vue` 的 streamMessage→native 映射(`:1049` thinking 分支附近),在 thinking 分支前/后加:
```ts
    } else if (msg.type === 'reasoning') {
      // 思维链 → custom kind, 走 #custom slot 的折叠卡
      out.push({ id: 'sm' + i, kind: 'custom', custom: { sm: msg } })
```
(确认 `streamCustom(message)` 能从该 custom item 取回 `sm`——与 file_write/command 同款,它们也是这么进 custom 的;读现有 file_write 的映射确保结构一致。)

- [ ] **Step 4: custom slot 渲染折叠卡**

`frontend/src/views/CodingPage.vue` 的 `#custom` slot(`:186` 起的 `streamCustom(message).sm.type` 分支链),在 `command` 分支(`:199`)后加 reasoning 分支:
```html
                <template v-else-if="streamCustom(message).sm.type === 'reasoning'">
                  <div class="msg-reasoning-card">
                    <button type="button" class="mrc-head" @click="streamCustom(message).sm.collapsed = !streamCustom(message).sm.collapsed">
                      <span class="mrc-caret">{{ streamCustom(message).sm.collapsed ? '▶' : '▼' }}</span>
                      <span>💭 思考过程</span>
                    </button>
                    <div v-if="!streamCustom(message).sm.collapsed" class="mrc-body" v-html="renderMarkdown(streamCustom(message).sm.content)"></div>
                  </div>
                </template>
```
(`renderMarkdown` 用 CodingPage 现有的 md 渲染函数名——读文件确认实际名,如 `renderMd`/`md.render`;没有就用纯文本 `{{ ... }}`。)

- [ ] **Step 5: 折叠卡样式**

`frontend/src/views/CodingPage.styles.css` 加(淡色、克制):
```css
.msg-reasoning-card { margin: 4px 0; font-size: 12px; }
.mrc-head { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; cursor: pointer; color: var(--text-3, #888); padding: 2px 0; font-size: 12px; }
.mrc-caret { font-size: 10px; }
.mrc-body { margin-top: 4px; padding: 8px 10px; border-left: 2px solid var(--line, #e5e7eb); color: var(--text-3, #888); font-style: italic; white-space: pre-wrap; }
html[data-theme="dark"] .mrc-body { border-left-color: #3a3a3a; color: #9aa0a6; }
```

- [ ] **Step 6: 跑测试 + 类型检查**

Run: `cd frontend && npx vitest run src/views/CodingPage.reasoning.spec.ts`
Expected: passed。
Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep -E "CodingPage|useStreamMessages|useCodingPipeline" || echo "no new type error"`(非阻塞,仓库预存类型错)。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/views/CodingPage.vue frontend/src/views/CodingPage.styles.css frontend/src/views/CodingPage.reasoning.spec.ts
git commit -m "feat(coding): 思维链渲染为默认收起的「思考过程」折叠卡"
```

---

## Final Verification

- [ ] 后端:`cd backend && ./.venv/bin/python -m pytest -q` → 1206 + 新增,0 failed。
- [ ] 前端:`cd frontend && npx vitest run src/views/coding src/views/CodingPage.reasoning.spec.ts` → 全 passed。
- [ ] (真机,desktop 打包)真 gpt-5.5 coding 一轮 → 答案只出现一次、reasoning 收进「💭 思考过程」折叠卡、展开能看推理、英文推理不再混进答案。**这步要打包(真 LLM 只认 desktop)。**

## Self-Review(已对 spec 核查)

- Spec 覆盖:拆 aggregate(T1)/ profile 透标志(T2)/ 前端分流(T3)/ 折叠卡(T4)全有任务。
- Placeholder:T2 测试指向「镜像现有 harness 测试 fixture」+ T4 `renderMarkdown` 指向「读文件确认实际名」——因这两处依赖现有代码的真实命名,给了明确定位而非臆造;其余步骤含完整代码。
- 类型一致:`type:'reasoning'` streamMessage(T3 产出,带 collapsed)→ T4 映射 custom + 渲染,字段一致;`reasoning` 标志 agent.py→profile→前端 parsed.reasoning 链路一致。
