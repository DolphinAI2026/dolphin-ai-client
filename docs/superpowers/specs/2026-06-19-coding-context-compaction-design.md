# 代码工作区上下文管理 — 滑动窗口压缩(Claude Code 式 compaction,适配无状态请求)

> 2026-06-19 · 子项目 #1(共 4:#1 上下文管理 / #2 token 显示+换 session 提醒 / #3 @skill 接入 / #4 handoff 结构化)。本 spec 只覆盖 #1。

## 背景与问题

代码工作区(/coding)的 coding agent **每轮请求都新建一个 CodingAgent**(`pipeline.py:2108`),跨轮**只带一段有损摘要**:DB 最近 6 条消息、每条砍到 200 字(`pipeline.py:~1854`,渲染进系统提示 `prompts.py:~842`)。后果:

- agent **跨轮失忆** —— 不记得上一轮读过哪些文件、改过什么 → **反复 read 同一文件**、重复劳动(用户反馈"有点笨"的根因)。
- 轮内只有**字符级**粗截断(`MAX_CONTEXT_CHARS=60000` 按字符不是 token;`on_context_overflow` 仅 `clean_tool_results(keep_recent=4)`,`agent.py:297`),**无真实 token 计数**,大块 `write_file` 代码留在历史不压缩。
- **413 / context_length_exceeded 不可重试** → 整轮直接失败(`_is_retryable` base.py:476 只认 429/5xx/timeout)。

对比 Claude Code:一条**连续增长的消息历史**(含每条工具结果),按 token 预算到阈值就**自动 compaction**(旧段模型摘要 + 最近原样保留),不每轮重建。本方案把同样的压缩策略落到 coding agent;差别在于 ai-builder 的 coding 是**无状态 HTTP 请求**(每条用户消息=新请求=新 agent),没有内存里的连续历史可继承,所以**多一步「持久化 + 跨请求恢复」**。

## 目标

让 coding agent 跨轮**恢复真实消息**(含 tool_calls + 工具结果,尤其读过的文件),用滑动窗口压缩保持上下文有界:**最近 N 轮原样 + 旧轮 LLM 摘要**,token 预算触发压缩,413 兜底重压重试。不再每轮失忆、反复读文件。

**非目标(留给后续子项目)**:token 用量 UI 显示 + 换 session 提醒(#2,但本 spec 产出 token 计数供其消费)、@skill 接入(#3)、handoff 结构化(#4)。读路径(`run_read_query` 一次性问答)不在本 spec 改造范围,仍用持久化摘要。

## 复用现成件(不重造)

- `app/context_compact.py` `ContextCompactor`:已实现三层压缩。本方案用 `compact_with_summary(messages, mode="coding_with_workspace", existing_summary)` → `(compacted_messages, new_summary)`(超 8 轮触发 LLM 摘要旧轮、保留最近 4 轮、去代码块、清旧工具结果)。coding 此前从不调用它。
- `app/agents/base.py` `to_snapshot()` / `from_snapshot(ctx, snapshot)`:已能序列化/恢复 `_messages` + `_tool_history` + tokens(此前仅 ask_user 暂停内用)。本方案用它做**跨轮**恢复。

## 架构 — 每轮流程

```
进轮  →  load 压缩态(Conversation.coding_agent_state)  →  有则 CodingAgent.from_snapshot(ctx, snapshot)
                                                              无则 CodingAgent(ctx)(首轮)
      →  append 新用户消息  →  run(轮内 overflow 按 token 预算 compact;413 兜底重压重试)
出轮  →  compact_with_summary(agent._messages, mode="coding_with_workspace", existing_summary=旧 summary)
      →  得 (bounded_messages, new_summary)  →  写回 to_snapshot 风格的 state  →  落库
```

### 1. 持久化:`Conversation.coding_agent_state`

`app/models/__init__.py:140` Conversation 加一列(JSON-as-Text,`Text().with_variant(LONGTEXT,"mysql")`,nullable):

```python
coding_agent_state: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
```

存 JSON:`{"messages": [...压缩后的结构化消息...], "summary": "<最新摘要>", "updated_at": iso, "version": 1}`。**存的是压缩态**(出轮已 compact),因此有界(摘要 + 最近窗口 + 清过的工具结果),不会无限涨。无 conversation_id 的临时会话不持久化(行为同今)。

### 2. 进轮恢复(pipeline 写路径,`pipeline.py` codegen 段 ~2095-2110)

- 读 `conversation.coding_agent_state`;为空 → `CodingAgent(ctx)`(首轮,行为同今)。
- 非空 → 解析出 `{messages, summary}`,构造 snapshot 字典喂 `CodingAgent.from_snapshot(ctx, snapshot)`,agent 起始 `_messages` = 上一轮压缩态(含最近几轮真实 tool_calls/结果)。
- **不再把 6×200 字摘要拼进系统提示**(系统提示回归纯指令)。恢复的 `messages` 在出轮压缩时已由 `compact_with_summary` 把旧轮摘要嵌成**开头的 `[对话摘要]` 消息**(`SUMMARY_MARKER` 约定),所以 from_snapshot 直接带上即可,**不需再单独拼**。单独存的 `summary` 字段只为出轮 compact 时作 `existing_summary` 传入,让摘要在原有基础上**增量更新**(而非每次从头摘)。
- 新用户消息照常 append 后 run。

### 3. 轮内 overflow(token 预算触发,`agent.py:297` on_context_overflow)

现状只 `clean_tool_results(keep_recent=4)`。增强为:
- 先估算当前 `_messages` token(见 §5);**超过软预算**(如 `CODING_CONTEXT_TOKEN_BUDGET` 默认按模型上下文窗口的 ~70% 折算)→ 调 `compact_with_summary(... existing_summary=self._summary)`(同步包装/或在 hook 里 await),把旧轮摘要、最近原样;并把 `new_summary` 暂存到 agent(出轮落库)。
- 仍保留 `clean_tool_results` 作为第一道(便宜)。

### 4. 413 / context_length 兜底(`base.py` LLM 调用路径)

- `_call_llm_with_retry`:捕获 **context-length / 413 / "context_length_exceeded"** 类错误(按 message/code 识别,httpx 400/413 + 关键词),**不走通用重试**(重发同样上下文必再失败),而是:触发一次 `on_context_overflow`(强制 compact)→ 用压缩后的 `_messages` 重试一次。仍失败才抛。
- 通用 `_is_retryable` 不动(429/5xx/timeout 照旧)。新增的是「压缩后重试」专用分支。

### 5. token 计数(供本方案预算判断 + #2 消费)

- 真实用量:LLM `usage.prompt_tokens/completion_tokens` 已累加到 `_tokens_input/_tokens_output`(base.py:537)。
- 发送前估算:加一个轻量估算 `estimate_tokens(messages)`(优先 tiktoken 若已装,否则 `总字符/3.5` 中英文混合粗算)。用于 §3 预算判断。估算函数放 `context_compact.py` 或新 `app/agents/token_estimate.py`,**纯函数、可单测**。
- 出轮把 `_tokens_input+_tokens_output` 随 `coding.run_result`/`done` 事件透出(给 #2 显示;本 spec 只产出,不做 UI)。

### 6. 出轮落库

run 结束(成功/异常均落):`compact_with_summary(agent._messages, mode="coding_with_workspace", existing_summary)` → `(bounded, summary)` → 存 `{"messages": bounded, "summary": summary}` 到 `coding_agent_state`。复用现有出口持久化时机(`_persist_output` 附近,pipeline.py)。

## 数据流要点

- 摘要是**模型生成**(ContextCompactor `_generate_summary` 用当前 coding llm_cfg),不是截断。
- 「最近 N 轮原样」**含 tool 消息**(读文件结果) → agent 不再反复读。N 由 `KEEP_RECENT_ROUNDS=4`(可调)。
- 状态**每会话一份**,删会话即清(连带 coding_agent_state 一起删,无新增清理逻辑)。

## 错误处理

- `coding_agent_state` 解析失败(脏数据/旧版本)→ 当首轮处理(`CodingAgent(ctx)`),日志 warning,不报错给用户。
- `compact_with_summary` 的 LLM 摘要失败 → 回退本地压缩(ContextCompactor 已有此回退),不阻塞落库。
- 413 重压后仍失败 → 抛原错误(用户看到失败,但已尽力),并建议换 session(#2 接)。

## 测试

- `ContextCompactor.compact_with_summary` 对 coding_with_workspace 模式的窗口/摘要行为(纯逻辑,扩现有/新增)。
- `estimate_tokens` 纯函数单测(中英文混合、代码块)。
- `to_snapshot`/`from_snapshot` 往返:构造带 tool 消息的 _messages,snapshot→from_snapshot→_messages 一致。
- pipeline 进轮:有 coding_agent_state → from_snapshot 起始 _messages 带历史;无 → 首轮空(mock pipeline/agent,类似 test_harness_coding_run_result_forwarding 的假 bus 套路)。
- 413 兜底:mock LLM 首次抛 context_length 错 → 触发 compact → 第二次成功(断言 compact 被调一次、最终返回)。
- on_context_overflow:_messages 超软预算 → compact_with_summary 被调;未超 → 仅 clean_tool_results。
- 全量 backend 回归(pipeline/harness/coding 相关面不破)。

## 风险

- 动 agent 核心循环(进轮恢复 + overflow + 413)→ 必须全量 backend 测试 + 真机 live 验(多轮迭代:让它改一处、再让它基于上一轮继续,看它是否记得、不再重读)。
- 桌面冻结 sidecar:改后端要重打包验证(读 jwt_secret 铸 token 抓 SSE 即可,不必 UI 登录 —— 见 [[miniprogram_preview_onehit_2026_06_19]] 调试法)。
- `coding_agent_state` 体积:压缩态有界,但极端长文件的最近窗口仍可能偏大 → token 预算 + clean_tool_results 双重兜底;必要时给 state 加硬上限(超则强摘要)。
