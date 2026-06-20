# coding 思维链(reasoning)单独可折叠展示

> 2026-06-20 · live 验真机发现的对话 UX bug 修复。用户选 B(思考过程单独可折叠,非 A「不显示」)。

## 背景与问题

coding 对话里 agent 的回复**重复两遍** + 偶发**英文推理泄漏**(同一根因):

- 模型流式返回 `content`(答案)+ `reasoning_content`(思维链 CoT)。`CodingAgent._call_llm`(`agent.py:504-513`)把两者**都**经 `_emit_stream_delta` 发成 `agent_thinking_delta`(reasoning 带 `reasoning:True` 标志,`agent.py:609-612`)。
- 末尾 `agent.py:596` `combined_thinking = reasoning_content + full_content` —— **把 reasoning 和答案拼一起**发 `agent_thinking` aggregate。
- gpt-5.5 的 `reasoning_content` 常是用中文把答案先「想」一遍 → 拼接后答案出现两次(= 用户看到的重复);reasoning 是英文 meta 时就是「英文推理泄漏」。
- 前端 `useCodingPipeline` 的 `agent_thinking_delta` 处理器(`:322`)`appendToLastThinking` **忽略 `reasoning` 标志**,全堆进同一张 thinking 卡。
- **🔑 harness profile 把标志丢了**:`profiles/coding.py:99-103` 转发 `agent_thinking_delta` 时只取 `event.get("content")`,`reasoning` 标志没透出 → 前端就算想分流也拿不到信号。

agent 真正的输出是 `content`(`agent.py:270` `final_text = response.content`),reasoning 只是辅助。

## 目标

把 reasoning(CoT)从答案里拆出来,渲染成**默认收起的「思考过程」可折叠卡**(和答案分开),消除重复 + 英文泄漏,同时保留思考可查看。content(答案/narration)展示不变。

**非目标**:不改读路径(run_read_query 无 reasoning);不动 token/trace(reasoning 仍内部留存);不做 reasoning 的 markdown 高亮等额外样式。

## 架构 — 全栈分流

### 1. 后端 agent.py:拆 aggregate(不再拼接)
`_call_llm` 末尾(`:596-598`)改为**分别**发 content 与 reasoning 两个 aggregate(不拼接):
```python
if full_content:
    await self._publish("agent_thinking", {"content": full_content})
if reasoning_content:
    await self._publish("agent_thinking", {"content": reasoning_content, "reasoning": True})
```
(seal 机制仍成立:content aggregate 封 thinking 卡,reasoning aggregate 封 reasoning 卡。)
delta 侧(`_emit_stream_delta` `:607-613`)已带 `reasoning:True`,不动。

### 2. 后端 profiles/coding.py:透 reasoning 标志(关键)
`agent_thinking_delta`(`:99-103`)+ `agent_thinking`(`:106-110`)转发时把 `reasoning` 标志带上:
```python
{"kind": "thinking", "text": event.get("content", ""), "reasoning": bool(event.get("reasoning"))}
```
(`item_kind` 仍 "thinking";SSEAdapter passthrough 原样带 data,不改。)

### 3. 前端 useCodingPipeline.ts:按标志分流
- `agent_thinking_delta`(`:322`):`if (parsed.reasoning)` → 累积到 **reasoning streamMessage**(type `'reasoning'`);否则走原 thinking 卡。新增 `appendToLastReasoning(delta)`(镜像 `appendToLastThinking`,但找/建 type==='reasoning' 的卡)。
- `agent_thinking`(`:300`):`if (parsed.reasoning)` → 用全文补齐 reasoning 卡(长度兜底覆盖,同 thinking);否则补齐 thinking 卡(原逻辑)。

### 4. 前端 CodingPage.vue:映射 reasoning → 折叠卡
- `:1049` streamCustom 映射:`msg.type === 'reasoning'` → AgentConversation 的 custom kind(`{ kind: 'custom', custom: { kind: 'reasoning', text, collapsed } }`),默认 `collapsed: true`。
- 复用现有 custom slot 渲染(`:192-194` 已有 `streamCustom(message).sm.collapsed` + `@toggle`),不新造组件。

### 5. 前端 AgentConversation.vue / CodingPage custom slot:折叠卡渲染
在 CodingPage 的 `#custom` slot(渲染 streamCustom)里加 reasoning 分支:折叠头「💭 思考过程 ▶/▼」点击 toggle `sm.collapsed`,展开体 `v-html renderMd(text)`(斜体淡色)。默认收起。

## 数据流

模型流 → agent 分发 content delta(→thinking 卡)/ reasoning delta(reasoning:True →reasoning 卡)→ profile 带 reasoning 标志 → SSEAdapter → 前端按标志分流 → reasoning 进默认收起的「思考过程」折叠卡、content 进答案。aggregate 同理分流补齐。

## 错误处理

- 老路径/无 reasoning 的模型:`reasoning_content` 空 → 不发 reasoning aggregate、无 reasoning delta → 无 reasoning 卡,行为同今(只有 thinking/答案)。
- profile `reasoning` 标志缺省 `False`,前端 `parsed.reasoning` falsy → 走 thinking 卡(向后兼容)。
- reasoning 卡 toggle 不影响答案渲染。

## 测试

- 后端 `test_coding_reasoning_split.py`:`_call_llm` 给定 mock 流(content+reasoning_content)→ 断言发了**两个** agent_thinking(一个 content 无 reasoning 标志、一个 reasoning 带标志),**不再拼接**;只有 content 无 reasoning 时只发一个。
- 后端 profile:`agent_thinking_delta`/`agent_thinking` 转发保留 `reasoning` 标志(扩 `test_harness_coding_*` 或新增)。
- 前端 `useCodingPipeline` 单测:`agent_thinking_delta` reasoning:true → 进 reasoning 卡、false → thinking 卡;两者不混。
- 前端 CodingPage 源码串:reasoning 映射成 custom collapsed + 折叠头「思考过程」。
- 全量 backend + 前端相关回归。

## 风险

1. **reasoning 标志透传链**:agent→profile→SSEAdapter→前端任一环丢标志则分流失效(profile 已确认是丢失点,SSEAdapter passthrough 安全)。Task 必须端到端验标志到前端(单测断言 profile 输出含 reasoning)。
2. **seal 机制**:拆成两个 aggregate 后,content/reasoning 各自 seal 各自的卡;若前端 seal 逻辑按「最后一条 thinking」会错封。前端分流后 thinking/reasoning 是不同 type 的卡,各自找各自,规避。
3. **重复回归**:本就是修重复的,测试要正面断言「content 不含 reasoning、两卡不混」,防再拼接。
4. 读路径 run_read_query 无 reasoning,不受影响(只 codegen 路径有)。
