# 代码工作区上下文管理(滑动窗口压缩)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 coding agent 跨轮恢复真实消息(含工具结果)+ 滑动窗口压缩,不再每轮失忆/反复读文件。

**Architecture:** 复用 `ContextCompactor`(app/context_compact.py)+ `BaseAgent.to_snapshot/from_snapshot`。每轮:进轮从 `Conversation.coding_agent_state` 读压缩态 → `CodingAgent.from_snapshot` 恢复 → 跑;出轮 `compact_with_summary` 压成有界态落库。轮内 overflow 走本地压缩(不调 LLM);跨轮 LLM 摘要放出轮(pipeline 里 llm 配置在 scope)。413/context_length → 强制 overflow 压缩后重试一次。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy async / pytest(asyncio_mode=auto)。后端 venv:`backend/.venv/bin/python`。

## Global Constraints

- 改后端必须重启进程(`backend/run.py` reload=False)才生效;桌面冻结 sidecar 改后端要 `bash scripts/build-desktop.sh` 重打。
- 测试用 `cd backend && ./.venv/bin/python -m pytest`;asyncio 测试直接 `async def test_*`(asyncio_mode=auto)。
- 复用现成件,不重造:`ContextCompactor`(context_compact.py)、`to_snapshot/from_snapshot`(base.py:410/436)、additive 迁移列表(database.py:67)。
- 读路径(`run_read_query`)不改;本计划只动 codegen/写路径(CodingAgent)。
- 无 conversation_id 的临时会话不持久化(行为同今)。
- **测试里构造 `AgentContext` / `LLMResponse` / `AgentType` 前,先读 `app/agents/types.py` 核对真实字段与构造签名** —— 本计划示例按常见形态写,实际以 types.py 为准(字段不符就按真实的改,别硬套)。
- pipeline.py 是大文件多分支:接入点(构造 agent / `_persist_output` / `load_coding_llm_config` 解析出的变量名 / `conversation_id` 变量名)实现前先 grep 确认,别盲改行号。
- 每步小提交;TDD 先红后绿。

---

### Task 1: token 估算纯函数

**Files:**
- Create: `backend/app/agents/token_estimate.py`
- Test: `backend/tests/test_token_estimate.py`

**Interfaces:**
- Produces: `estimate_tokens(messages: list[dict]) -> int` —— 估算一组 chat messages 的 token 数(轮内预算判断 + #2 显示用)。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_token_estimate.py
from app.agents.token_estimate import estimate_tokens


def test_empty_is_zero():
    assert estimate_tokens([]) == 0


def test_counts_string_content():
    # 纯 ASCII: ~ 字符数/3.5
    msgs = [{"role": "user", "content": "x" * 350}]
    n = estimate_tokens(msgs)
    assert 80 <= n <= 130


def test_counts_tool_calls_and_blocks():
    msgs = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": "{\"path\":\"a.vue\"}"}}]},
        {"role": "tool", "content": "file body " * 100},
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},  # 多模态块
    ]
    assert estimate_tokens(msgs) > 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_token_estimate.py -q`
Expected: FAIL（ModuleNotFoundError: app.agents.token_estimate）

- [ ] **Step 3: 写实现**

```python
# backend/app/agents/token_estimate.py
"""粗估 chat messages 的 token 数 —— 用于上下文预算判断 + token 用量显示。

不追求精确(gpt-5.5 经 dolphin 网关, 无官方 tokenizer): 按字符/3.5 估(中英文混合的
保守经验值)。tiktoken 若已装则用 cl100k_base 更准, 否则回退字符估算。"""
from __future__ import annotations

from typing import Any

_CHARS_PER_TOKEN = 3.5


def _message_text(m: dict[str, Any]) -> str:
    parts: list[str] = []
    c = m.get("content")
    if isinstance(c, str):
        parts.append(c)
    elif isinstance(c, list):  # 多模态 content blocks
        for b in c:
            if isinstance(b, dict):
                parts.append(str(b.get("text") or ""))
    for tc in (m.get("tool_calls") or []):
        parts.append(str(tc))
    return "".join(parts)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    text = "".join(_message_text(m) for m in (messages or []))
    if not text:
        return 0
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return int(len(text) / _CHARS_PER_TOKEN)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_token_estimate.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/token_estimate.py backend/tests/test_token_estimate.py
git commit -m "feat(coding): token 估算纯函数(上下文预算/用量显示用)"
```

---

### Task 2: Conversation.coding_agent_state 列 + 迁移

**Files:**
- Modify: `backend/app/models/__init__.py`（Conversation 类,~140 行;`BigText` 已在文件内定义并用于其他列)
- Modify: `backend/app/database.py`（init_db 的 ALTER 迁移列表,~67 行起)
- Test: `backend/tests/test_conversation_coding_state_column.py`

**Interfaces:**
- Produces: `Conversation.coding_agent_state: Optional[str]` —— 存 JSON 字符串 `{"messages": [...], "summary": str|None, "version": 1}`,后续 Task 5/6 读写。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_conversation_coding_state_column.py
from app.models import Conversation


def test_conversation_has_coding_agent_state_column():
    assert "coding_agent_state" in Conversation.__table__.columns
    col = Conversation.__table__.columns["coding_agent_state"]
    assert col.nullable is True


def test_migration_alter_present():
    import inspect as _inspect
    import app.database as db
    src = _inspect.getsource(db.init_db)
    assert "ALTER TABLE conversations ADD COLUMN coding_agent_state" in src
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_conversation_coding_state_column.py -q`
Expected: FAIL（KeyError coding_agent_state / assert 'ALTER...' in src）

- [ ] **Step 3: 加列 + 迁移**

在 `backend/app/models/__init__.py` 的 `class Conversation` 里(挨着 `workspace_id` / `coding_app_id` 等列)加:

```python
    # 滑动窗口压缩态(messages+summary 的 JSON), coding agent 跨轮 from_snapshot 恢复用。
    coding_agent_state: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
```

> `BigText = Text().with_variant(LONGTEXT, "mysql")` 已在该文件顶部定义(同 agent_prompt.py 用法);若 Conversation 所在文件未定义 BigText,用 `Mapped[Optional[str]] = mapped_column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)` 并确保 `LONGTEXT` 已 import(`from sqlalchemy.dialects.mysql import LONGTEXT`)。

在 `backend/app/database.py` 的 ALTER 迁移列表(line ~67 `for stmt in [`)里追加一行(放 conversations 相关 ALTER 附近):

```python
            "ALTER TABLE conversations ADD COLUMN coding_agent_state TEXT",
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_conversation_coding_state_column.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/__init__.py backend/app/database.py backend/tests/test_conversation_coding_state_column.py
git commit -m "feat(coding): Conversation.coding_agent_state 列 + 迁移(存压缩态)"
```

---

### Task 3: CodingAgent.on_context_overflow 按 token 预算本地压缩

**Files:**
- Modify: `backend/app/agents/coding/agent.py`（`on_context_overflow` ~297;类初始化处加 `_context_token_budget`)
- Test: `backend/tests/test_coding_context_overflow.py`

**Interfaces:**
- Consumes: `estimate_tokens`（Task 1）、`ContextCompactor.clean_tool_results` / `ContextCompactor.compact`（context_compact.py,已存在,均为同步本地、不调 LLM）。
- Produces: `CodingAgent.on_context_overflow(messages) -> list` —— 先清旧工具结果;仍超 `_context_token_budget` 则本地 `compact(mode="coding_with_workspace")`。轮内不调 LLM。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_coding_context_overflow.py
import pytest
from app.agents.coding.agent import CodingAgent
from app.agents.types import AgentContext


def _agent():
    ctx = AgentContext(conversation_id=1, user_id=1, tenant_id=1, session_id="s", input={})
    return CodingAgent(ctx)


@pytest.mark.asyncio
async def test_overflow_under_budget_only_cleans_tool_results():
    a = _agent()
    a._context_token_budget = 10_000_000  # 永不超预算
    msgs = [{"role": "tool", "content": "x" * 500} for _ in range(10)]
    out = await a.on_context_overflow(msgs)
    # clean_tool_results 压缩了旧 tool(保留最近 4 完整), 但没做 compact 丢消息
    assert len(out) == len(msgs)


@pytest.mark.asyncio
async def test_overflow_over_budget_compacts():
    a = _agent()
    a._context_token_budget = 50  # 极低预算 → 触发本地 compact
    rounds = []
    for i in range(12):
        rounds.append({"role": "user", "content": f"req {i} " * 50})
        rounds.append({"role": "assistant", "content": f"```js\ncode {i}\n``` done {i}"})
    out = await a.on_context_overflow(rounds)
    # 本地 compact 会去代码块 + 只保留最近若干轮 → 总量明显变小
    assert len(out) < len(rounds)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_context_overflow.py -q`
Expected: FAIL（`_context_token_budget` 未定义 / 现有 on_context_overflow 只 clean_tool_results,第二个用例 len 不变）

- [ ] **Step 3: 改实现**

先确认 `agent.py` 顶部 import(若无则加):

```python
from app.context_compact import ContextCompactor
from app.agents.token_estimate import estimate_tokens
```

在 CodingAgent 的 `__init__`（或类属性默认)加预算(放 `MAX_CONTEXT_CHARS = 60000` 附近作模块常量 + 实例默认):

```python
# 轮内上下文软预算(token); 超过则本地压缩。约取模型上下文窗口的 ~70% 折算的保守值。
CODING_CONTEXT_TOKEN_BUDGET = 90_000
```

在 `__init__` 里(super().__init__ 之后):

```python
        self._context_token_budget = CODING_CONTEXT_TOKEN_BUDGET
```

把 `on_context_overflow`（~297)改成:

```python
    async def on_context_overflow(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # 第一道(便宜): 压缩旧工具结果, 最近 4 条保留完整
        cleaned = ContextCompactor.clean_tool_results(messages, keep_recent=4)
        if estimate_tokens(cleaned) <= self._context_token_budget:
            return cleaned
        # 仍超预算: 本地压缩(去代码块 + 只保留最近几轮), 轮内不调 LLM(避免循环内递归请求)。
        # 跨轮的 LLM 摘要由 pipeline 出轮做(那里 llm 配置在 scope)。
        return ContextCompactor().compact(cleaned, mode="coding_with_workspace")
```

> `ContextCompactor().compact(...)` 不传 llm_cfg → 纯本地(去代码块 + 保留最近 max_rounds 轮),不发请求。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_context_overflow.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/coding/agent.py backend/tests/test_coding_context_overflow.py
git commit -m "feat(coding): on_context_overflow 按 token 预算本地压缩(轮内不调 LLM)"
```

---

### Task 4: 413 / context_length 压缩后重试一次

**Files:**
- Modify: `backend/app/agents/base.py`（`_call_llm_with_retry` ~455)
- Test: `backend/tests/test_agent_context_length_retry.py`

**Interfaces:**
- Consumes: `self.on_context_overflow`（Task 3 在 CodingAgent 覆盖)、`self._messages`。
- Produces: `_call_llm_with_retry` 在遇到 context-length 类错误时,调一次 `on_context_overflow(self._messages)` 重压 `_messages` 后重试一次(区别于通用 429/5xx 重试)。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_agent_context_length_retry.py
import pytest
from app.agents.base import BaseAgent
from app.agents.types import AgentContext, AgentType, LLMResponse


class _CtxLenError(Exception):
    pass


class _ProbeAgent(BaseAgent):
    agent_type = AgentType.CODING

    def __init__(self, ctx):
        super().__init__(ctx)
        self._calls = 0
        self.overflow_called = 0

    async def on_context_overflow(self, messages):
        self.overflow_called += 1
        return messages[-1:]  # 强压成一条

    async def _call_llm(self):
        self._calls += 1
        if self._calls == 1:
            raise _CtxLenError("This model's maximum context length is 128000 tokens")
        return LLMResponse(content="ok", tool_calls=[], tokens_input=1, tokens_output=1)


@pytest.mark.asyncio
async def test_context_length_triggers_compact_then_retry():
    ctx = AgentContext(conversation_id=1, user_id=1, tenant_id=1, session_id="s", input={})
    a = _ProbeAgent(ctx)
    a._messages = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
    resp = await a._call_llm_with_retry()
    assert resp.content == "ok"
    assert a.overflow_called == 1          # 压了一次
    assert a._calls == 2                   # 重试了一次
    assert a._messages == [{"role": "user", "content": "b"}]  # 用压缩后的 messages 重试
```

> 注:`AgentType.CODING`、`LLMResponse` 字段名按 app/agents/types.py 实际为准;实现前先读该文件核对(LLMResponse 至少有 content/tool_calls/tokens_input/tokens_output)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_agent_context_length_retry.py -q`
Expected: FAIL（首次 _CtxLenError 直接抛出,不会压缩重试)

- [ ] **Step 3: 改实现**

在 `base.py` 加一个识别函数(放 `_is_retryable` 附近):

```python
    @staticmethod
    def _is_context_length_error(error: Exception) -> bool:
        """识别上下文超限类错误(需压缩后重试, 而非原样重发)。"""
        import httpx
        msg = str(error).lower()
        if any(k in msg for k in ("context length", "context_length_exceeded",
                                  "maximum context", "too many tokens", "reduce the length")):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in {413}
        return False
```

把 `_call_llm_with_retry`（~455)的循环体改成(在通用重试判断之前先处理上下文超限):

```python
    async def _call_llm_with_retry(self, max_retries: int = 3) -> LLMResponse:
        last_error: Optional[Exception] = None
        compacted_once = False
        for attempt in range(max_retries):
            try:
                return await self._call_llm()
            except Exception as e:
                last_error = e
                # 上下文超限: 压缩一次再重试(不消耗通用重试预算的语义), 仅压一次防死循环
                if self._is_context_length_error(e) and not compacted_once:
                    compacted_once = True
                    try:
                        self._messages = await self.on_context_overflow(self._messages)
                        await self._trace(TraceEventType.RETRY, {"attempt": attempt + 1,
                                          "error": "context_length → compacted", "wait_seconds": 0})
                        continue
                    except Exception as ce:
                        logger.warning("context-length compact failed: %s", ce)
                        raise
                if not self._is_retryable(e) or attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                await self.on_retry(attempt + 1, e)
                await self._trace(TraceEventType.RETRY, {"attempt": attempt + 1,
                                  "error": str(e), "wait_seconds": wait})
                await asyncio.sleep(wait)
        raise last_error or RuntimeError("LLM retry exhausted")
```

> `continue` 不增 wait、不走通用分支;`compacted_once` 防反复压缩死循环。`TraceEventType` 已在 base.py import。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_agent_context_length_retry.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/base.py backend/tests/test_agent_context_length_retry.py
git commit -m "feat(agent): context_length/413 → 压缩后重试一次(不再整轮失败)"
```

---

### Task 5: pipeline 进轮 — 读压缩态 + from_snapshot 恢复

**Files:**
- Modify: `backend/app/coding/pipeline.py`（codegen 段构造 CodingAgent 处 ~2095-2110;以及构 conversation_summary / 注入系统提示处 ~1854 + prompts 渲染处)
- Test: `backend/tests/test_coding_pipeline_resume.py`

**Interfaces:**
- Consumes: `Conversation.coding_agent_state`（Task 2)、`CodingAgent.from_snapshot`（base.py:436)。
- Produces: 一个纯函数 `build_resume_snapshot(state_json: str | None) -> dict | None` —— 把存的 JSON 解析成 from_snapshot 可吃的 snapshot 字典(`{"messages":[...], "status":"idle", "turn":0}`);脏数据/None 返回 None。供 pipeline 在构造 agent 前调用。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_coding_pipeline_resume.py
import json
from app.coding.pipeline import build_resume_snapshot


def test_none_or_garbage_returns_none():
    assert build_resume_snapshot(None) is None
    assert build_resume_snapshot("not json") is None
    assert build_resume_snapshot(json.dumps({"summary": "x"})) is None  # 无 messages


def test_parses_messages_into_snapshot():
    state = json.dumps({"messages": [{"role": "user", "content": "hi"},
                                     {"role": "assistant", "content": "ok"}], "summary": "s", "version": 1})
    snap = build_resume_snapshot(state)
    assert snap is not None
    assert snap["messages"] == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
    # from_snapshot 需要的最小字段
    assert snap.get("status") in ("idle", None) or "status" in snap
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_pipeline_resume.py -q`
Expected: FAIL（ImportError: build_resume_snapshot）

- [ ] **Step 3: 加纯函数 + 接进 pipeline**

在 `pipeline.py` 加纯函数(模块级,靠近其他 helper):

```python
def build_resume_snapshot(state_json: str | None) -> dict | None:
    """把 Conversation.coding_agent_state(JSON)解析成 CodingAgent.from_snapshot 可用的 snapshot。

    脏数据 / 无 messages → None(调用方按首轮新建 agent 处理)。
    """
    if not state_json:
        return None
    try:
        import json
        data = json.loads(state_json)
    except Exception:
        return None
    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return None
    return {"messages": msgs, "status": "idle", "turn": 0}
```

在 codegen 段构造 agent 处(`_coding_agent = CodingAgent(_coding_ctx)`,~2108)改为:

```python
        _resume_state = None
        if conversation_id:  # 该轮所属会话
            _conv = await db.get(Conversation, conversation_id)
            _resume_state = build_resume_snapshot(getattr(_conv, "coding_agent_state", None)) if _conv else None
        if _resume_state:
            _coding_agent = CodingAgent.from_snapshot(_coding_ctx, _resume_state)
        else:
            _coding_agent = CodingAgent(_coding_ctx)
```

> `Conversation` 需在 pipeline.py 顶部已 import(`from app.models import Conversation`);若无则加。`conversation_id` 在该 scope 的变量名以实际为准(可能是 `conversation_id` 或 `params.conversation_id`,实现前 grep 确认)。

移除旧的 6×200 字摘要注入系统提示:把 `conversation_summary`(~1854 构建)从喂给 codegen 的系统提示里去掉(`prompts.py` 渲染「Previous Conversation Summary」处),系统提示回归纯指令 —— **因为恢复的 `_messages` 已带历史(含出轮压缩的 `[对话摘要]` 开头消息)**。读路径(run_read_query)若也用该摘要则保留其读路径用法,只去 codegen 写路径的注入。

- [ ] **Step 4: 跑测试确认通过 + 不破回归**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_pipeline_resume.py tests/test_harness_coding_run_result_forwarding.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/pipeline.py backend/app/agents/coding/prompts.py backend/tests/test_coding_pipeline_resume.py
git commit -m "feat(coding): 进轮读压缩态 + from_snapshot 恢复真实消息(去 6x200 摘要注入)"
```

---

### Task 6: pipeline 出轮 — compact_with_summary 压缩 + 落库

**Files:**
- Modify: `backend/app/coding/pipeline.py`（run 结束/`_persist_output` 附近 ~2160-2185)
- Test: `backend/tests/test_coding_pipeline_persist_state.py`

**Interfaces:**
- Consumes: `ContextCompactor.compact_with_summary`(context_compact.py)、出轮可拿到的 `agent._messages` / 已存 summary / pipeline 解析出的 llm_cfg(`base_url/api_key/llm_model`)。
- Produces: 纯函数 `serialize_coding_state(messages: list, summary: str | None) -> str` —— 把压缩后的 messages+summary 序列化成存库 JSON。pipeline 出轮调 compact_with_summary 后用它落 `coding_agent_state`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_coding_pipeline_persist_state.py
import json
from app.coding.pipeline import serialize_coding_state, build_resume_snapshot


def test_serialize_roundtrip():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "done"}]
    s = serialize_coding_state(msgs, "摘要文本")
    data = json.loads(s)
    assert data["messages"] == msgs
    assert data["summary"] == "摘要文本"
    assert data["version"] == 1
    # 与 Task 5 的 resume 闭环: 序列化的 state 能被 build_resume_snapshot 还原
    snap = build_resume_snapshot(s)
    assert snap["messages"] == msgs


def test_serialize_handles_none_summary():
    s = serialize_coding_state([{"role": "user", "content": "x"}], None)
    assert json.loads(s)["summary"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_pipeline_persist_state.py -q`
Expected: FAIL（ImportError: serialize_coding_state）

- [ ] **Step 3: 加纯函数 + 出轮压缩落库**

在 `pipeline.py` 加:

```python
def serialize_coding_state(messages: list, summary: str | None) -> str:
    import json
    return json.dumps({"messages": messages or [], "summary": summary, "version": 1}, ensure_ascii=False)
```

在 codegen 段 run 结束后(`_persist_output` 附近,出轮一定会走到的地方,放在 except 之外的 finally-ish 收尾;若已有 `await _persist_output()` 出口,挨着它加)插入:

```python
        # 出轮: 把跑完的真实消息压成有界态(旧轮 LLM 摘要 + 最近 N 轮原样)落库, 供下一轮 from_snapshot 恢复。
        if conversation_id:
            try:
                from app.context_compact import ContextCompactor
                _llm_cfg = {"api_key": api_key, "base_url": base_url, "model": llm_model}  # 该 scope 已解析(load_coding_llm_config)
                _prev_summary = None
                _conv2 = await db.get(Conversation, conversation_id)
                if _conv2 and _conv2.coding_agent_state:
                    try:
                        import json as _json
                        _prev_summary = _json.loads(_conv2.coding_agent_state).get("summary")
                    except Exception:
                        _prev_summary = None
                _bounded, _new_summary = await ContextCompactor(_llm_cfg).compact_with_summary(
                    list(_coding_agent._messages), mode="coding_with_workspace", existing_summary=_prev_summary,
                )
                if _conv2:
                    _conv2.coding_agent_state = serialize_coding_state(_bounded, _new_summary)
                    await db.commit()
            except Exception as _e:
                logger.warning("persist coding_agent_state failed (非致命): %s", _e)
```

> `api_key/base_url/llm_model` 在 codegen 段已由 `load_coding_llm_config` 解析(grep 确认变量名);若名字不同按实际。`_coding_agent` 是 Task 5 构造的 agent 实例。落库失败不致命(下一轮当首轮)。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `cd backend && ./.venv/bin/python -m pytest tests/test_coding_pipeline_persist_state.py -q`
Expected: PASS
Run: `cd backend && ./.venv/bin/python -m pytest tests/ -q`
Expected: 全绿(无新失败)

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/pipeline.py backend/tests/test_coding_pipeline_persist_state.py
git commit -m "feat(coding): 出轮 compact_with_summary 压缩 + 落 coding_agent_state(滑动窗口闭环)"
```

---

## 收尾验证(全部 task 后)

- [ ] 全量 backend:`cd backend && ./.venv/bin/python -m pytest tests/ -q` 全绿。
- [ ] 重打桌面包 `bash scripts/build-desktop.sh` → 重启 → 抓 SSE / live 验:同一会话**多轮迭代**(让它改一处 → 再让它"基于刚才继续改另一处"),看它**是否记得上一轮、不再重读同一文件**(对比修复前)。读 jwt_secret 铸 token 抓 SSE,不必 UI 登录。
- [ ] 确认 token 用量(`_tokens_input+_tokens_output`)能在出轮事件里透出(给子项目 #2 消费)。

## 风险/回滚

- 动 agent 核心循环(进轮恢复 + overflow + 413):任一步 backend 回归红 → 该步回滚重做。
- `coding_agent_state` 脏数据 → build_resume_snapshot 返回 None 当首轮,不报错(已测)。
- 出轮压缩 LLM 摘要失败 → ContextCompactor 内部回退本地压缩;落库整体失败也只是下一轮当首轮,不影响本轮结果。
