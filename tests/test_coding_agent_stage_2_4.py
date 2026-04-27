"""CodingAgent Stage 2.4 单测：循环检测 + 状态序列化 + context 压缩 + 进度笔记。

覆盖：
- on_each_turn：连续 read 触发 nudge 消息注入
- after_tool_call：consecutive_reads 计数（read 族 +1，write 族清零）
- after_tool_call：tool result 按 context budget 截断
- after_tool_call：read_files_set 维护
- after_tool_call：发 agent_result 事件（含 tool_display / output_preview / is_error）
- before_tool_call：发 agent_tool 事件（含 tool_display / input_preview）
- on_llm_response：有 tool_call 但 content 空时自动推送 progress note
- on_llm_response：重复同样 note 不重推
- on_context_overflow：messages > 10 触发压缩
- Snapshot 完整 roundtrip（所有新字段）
"""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.agents.coding import CodingAgent
from app.agents.coding.agent import (
    MAX_CONTEXT_CHARS,
    NUDGE_CONSECUTIVE_READS_THRESHOLD,
    NUDGE_MESSAGE,
    TOOL_ICONS,
    _describe_tool_plan,
    _format_tool_input,
    _truncate,
)
from app.agents.publisher import InMemoryEventPublisher
from app.agents.trace_writer import InMemoryTraceWriter
from app.agents.types import AgentContext, LLMResponse, Tool, ToolCall, ToolResult


def _make_ctx(**kwargs):
    defaults = dict(
        session_id="test_s",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="test-model",
        workspace_id=None,
        input={"requirement": "t"},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
    )
    defaults.update(kwargs)
    return AgentContext(**defaults)


def _make_tool(name: str) -> Tool:
    async def noop(args, ctx): return ToolResult(success=True, content="ok")
    return Tool(name=name, description="x", parameters_schema={"type": "object"}, execute=noop)


# ══════════════════════════════════════════════════════════════
# 1. 辅助函数：_truncate / _format_tool_input / _describe_tool_plan
# ══════════════════════════════════════════════════════════════

def test_truncate_short_string_unchanged():
    assert _truncate("hello", 300) == "hello"


def test_truncate_long_string_cut():
    s = "x" * 500
    r = _truncate(s, 100)
    assert len(r) == 103
    assert r.endswith("...")


def test_format_tool_input_write_file_shows_lines():
    r = _format_tool_input("write_file", {"file_path": "a.vue", "content": "line1\nline2\nline3"})
    assert "a.vue" in r
    assert "3 lines" in r


def test_format_tool_input_edit_file_shows_old_truncated():
    r = _format_tool_input("edit_file", {"file_path": "x", "old_string": "y" * 200})
    assert "x:" in r
    assert "->" in r


def test_format_tool_input_grep_search_shows_pattern_path():
    r = _format_tool_input("grep_search", {"pattern": "foo", "path": "src"})
    assert "/foo/" in r
    assert "src" in r


def test_describe_tool_plan_empty_returns_empty():
    assert _describe_tool_plan([]) == ""


def test_describe_tool_plan_frontend_read_write():
    r = _describe_tool_plan(["read_file", "write_file"], project_type="form-component-dual")
    assert "读取" in r or "读" in r
    assert "批量写入组件文件" in r


def test_describe_tool_plan_backend_different_wording():
    r = _describe_tool_plan(["read_file", "write_file"], project_type="backend-api")
    assert "接口写法" in r
    assert "批量写入 Java 文件" in r


# ══════════════════════════════════════════════════════════════
# 2. after_tool_call：consecutive_reads + read_files_set + 截断 + agent_result
# ══════════════════════════════════════════════════════════════

def test_after_tool_call_read_increments_consecutive():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    assert agent._consecutive_reads == 0

    # 模拟 read 一次
    agent._tool_history.append({"name": "read_file", "args": {"file_path": "a.txt"}, "success": True})
    r = asyncio.run(agent.after_tool_call(_make_tool("read_file"), ToolResult(success=True, content="ok")))
    assert agent._consecutive_reads == 1

    # 再 read 一次
    agent._tool_history.append({"name": "read_file", "args": {"file_path": "b.txt"}, "success": True})
    asyncio.run(agent.after_tool_call(_make_tool("read_file"), ToolResult(success=True, content="ok")))
    assert agent._consecutive_reads == 2

    # read_files_set 正确累积
    assert "a.txt" in agent._read_files_set
    assert "b.txt" in agent._read_files_set


def test_after_tool_call_write_resets_consecutive():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    agent._consecutive_reads = 5

    agent._tool_history.append({"name": "write_file", "args": {}, "success": True})
    asyncio.run(agent.after_tool_call(_make_tool("write_file"), ToolResult(success=True, content="ok")))
    assert agent._consecutive_reads == 0


def test_after_tool_call_run_command_resets_consecutive():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    agent._consecutive_reads = 3

    asyncio.run(agent.after_tool_call(_make_tool("run_command"), ToolResult(success=True, content="ok")))
    assert agent._consecutive_reads == 0


def test_after_tool_call_large_result_truncated():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    # 接近 context budget 上限时触发截断
    agent._total_tool_result_chars = MAX_CONTEXT_CHARS - 5000  # 剩 5000 → max_result_len = 2500
    long_content = "x" * 20000
    r = asyncio.run(agent.after_tool_call(_make_tool("read_file"), ToolResult(success=True, content=long_content)))
    assert len(r.content) < 20000
    assert "[truncated" in r.content


def test_after_tool_call_small_result_not_truncated():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    r = asyncio.run(agent.after_tool_call(_make_tool("read_file"), ToolResult(success=True, content="short")))
    assert r.content == "short"
    assert "[truncated" not in r.content


def test_after_tool_call_emits_agent_result_event():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    asyncio.run(agent.after_tool_call(_make_tool("read_file"), ToolResult(success=True, content="result data")))
    events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_result"]
    assert len(events) == 1
    assert events[0]["data"]["tool"] == "read_file"
    assert events[0]["data"]["is_error"] is False
    assert "result data" in events[0]["data"]["output_preview"]


def test_after_tool_call_error_emits_is_error_true():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    asyncio.run(agent.after_tool_call(
        _make_tool("read_file"),
        ToolResult(success=False, content="Error: not found", error="not found"),
    ))
    events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_result"]
    assert events[0]["data"]["is_error"] is True


# ══════════════════════════════════════════════════════════════
# 3. before_tool_call：发 agent_tool 事件 + input_preview
# ══════════════════════════════════════════════════════════════

def test_before_tool_call_emits_agent_tool_event():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    args = {"file_path": "a.vue", "content": "line1\nline2"}
    asyncio.run(agent.before_tool_call(_make_tool("write_file"), args))

    events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_tool"]
    assert len(events) == 1
    # 与 VibeCodingAgent 原格式对齐：key 是 "tool"，不是 "name"
    assert events[0]["data"]["tool"] == "write_file"
    assert "a.vue" in events[0]["data"]["input_preview"]
    assert "2 lines" in events[0]["data"]["input_preview"]
    # write_file 透传 input 给前端展示代码
    assert events[0]["data"]["input"]["file_path"] == "a.vue"
    assert events[0]["data"]["input"]["content"] == "line1\nline2"


def test_before_tool_call_read_file_no_input_field():
    """read_file 不应该塞 input 字段（那是 write/edit 专用）"""
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    asyncio.run(agent.before_tool_call(_make_tool("read_file"), {"file_path": "x.txt"}))
    events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_tool"]
    assert "input" not in events[0]["data"]


# ══════════════════════════════════════════════════════════════
# 4. on_each_turn：nudge 注入
# ══════════════════════════════════════════════════════════════

def test_on_each_turn_triggers_nudge_after_threshold():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    agent._consecutive_reads = NUDGE_CONSECUTIVE_READS_THRESHOLD
    agent._messages = [{"role": "user", "content": "hi"}]

    asyncio.run(agent.on_each_turn(turn=3))

    # 应追加 nudge 消息
    assert len(agent._messages) == 2
    assert agent._messages[-1]["role"] == "user"
    assert agent._messages[-1]["content"] == NUDGE_MESSAGE
    # 触发后计数清零
    assert agent._consecutive_reads == 0

    # trace 里有 nudge 记录
    nudge_traces = [t for t in ctx.trace_writer.traces if t["event_type"] == "nudge"]
    assert len(nudge_traces) == 1


def test_on_each_turn_no_nudge_below_threshold():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    agent._consecutive_reads = 1  # 还没到阈值
    agent._messages = [{"role": "user", "content": "hi"}]

    asyncio.run(agent.on_each_turn(turn=1))

    assert len(agent._messages) == 1  # 没追加 nudge
    assert agent._consecutive_reads == 1


# ══════════════════════════════════════════════════════════════
# 5. on_llm_response：progress note 去重推送
# ══════════════════════════════════════════════════════════════

def test_on_llm_response_empty_content_with_tool_calls_emits_progress_note():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    agent._cached_project_type = "form-component-dual"

    resp = LLMResponse(
        content="",
        tool_calls=[ToolCall(id="c1", name="read_file", arguments_json='{"file_path": "x"}')],
    )
    asyncio.run(agent.on_llm_response(resp))

    # 应发 agent_thinking 聚合事件（note 是事后合成的完整文本，不是 delta 流）
    # 走 delta 会被前端拼到上一条未封口的 thinking 上 → 思考卡尾部突然多出
    # 一段和上下文无关的合成 note，造成视觉跳变。
    events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_thinking"]
    assert len(events) == 1
    assert "读取" in events[0]["data"]["content"] or "读" in events[0]["data"]["content"]


def test_on_llm_response_duplicate_note_not_repushed():
    """连续两轮相同 tool_names → 第二轮不重复推送 note"""
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    agent._cached_project_type = "form-component-dual"

    resp = LLMResponse(
        content="",
        tool_calls=[ToolCall(id="c1", name="read_file", arguments_json='{}')],
    )
    asyncio.run(agent.on_llm_response(resp))
    asyncio.run(agent.on_llm_response(resp))

    events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_thinking"]
    assert len(events) == 1  # 第二轮同 note 被去重


def test_on_llm_response_with_content_does_not_emit_note():
    """LLM 自己写了 content → 不自动补 note"""
    ctx = _make_ctx()
    agent = CodingAgent(ctx)

    resp = LLMResponse(
        content="我要开始写代码了",
        tool_calls=[ToolCall(id="c1", name="write_file", arguments_json='{}')],
    )
    asyncio.run(agent.on_llm_response(resp))

    events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_thinking_delta"]
    assert len(events) == 0


# ══════════════════════════════════════════════════════════════
# 6. on_context_overflow：messages 压缩
# ══════════════════════════════════════════════════════════════

def test_on_context_overflow_short_messages_unchanged():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    msgs = [{"role": "user", "content": "a"}] * 5
    result = asyncio.run(agent.on_context_overflow(msgs))
    assert result is msgs  # 未压缩，返回原对象


def test_on_context_overflow_long_messages_compresses_long_assistant():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    msgs = []
    # 旧的长 assistant 消息（应被压缩到 300）
    msgs.append({"role": "assistant", "content": "A" * 1000})
    msgs.append({"role": "user", "content": "hello"})
    # 中间填充到 > 10
    for i in range(15):
        msgs.append({"role": "tool", "tool_call_id": f"t{i}", "content": f"result {i}"})
    # 近期的完整消息（不应被压缩，cutoff = len(msgs)-8）
    msgs.append({"role": "assistant", "content": "B" * 1000})

    result = asyncio.run(agent.on_context_overflow(msgs))
    # 第一条（旧）assistant 应被压缩
    assert len(result[0]["content"]) <= 303
    assert result[0]["content"].endswith("...")
    # 最后一条（近期）assistant 不应被压缩
    assert len(result[-1]["content"]) == 1000


# ══════════════════════════════════════════════════════════════
# 7. Snapshot 完整 roundtrip（含所有新字段）
# ══════════════════════════════════════════════════════════════

def test_snapshot_full_custom_state_roundtrip():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)

    # 设置所有 custom 字段
    agent._final_result = {"ok": True}
    agent._llm_said_done = True
    agent._consecutive_reads = 2
    agent._read_files_set = {"a.txt", "b.vue"}
    agent._total_tool_result_chars = 12345
    agent._last_progress_note = "some note"
    agent._cached_project_type = "form-component-dual"

    snap = agent.to_snapshot()
    assert snap["custom"]["consecutive_reads"] == 2
    assert sorted(snap["custom"]["read_files"]) == ["a.txt", "b.vue"]
    assert snap["custom"]["total_tool_result_chars"] == 12345
    assert snap["custom"]["last_progress_note"] == "some note"
    assert snap["custom"]["cached_project_type"] == "form-component-dual"

    # 恢复
    ctx2 = _make_ctx()
    restored = CodingAgent.from_snapshot(ctx2, snap)
    assert restored._consecutive_reads == 2
    assert restored._read_files_set == {"a.txt", "b.vue"}
    assert restored._total_tool_result_chars == 12345
    assert restored._last_progress_note == "some note"
    assert restored._cached_project_type == "form-component-dual"


# ══════════════════════════════════════════════════════════════
# 8. BaseAgent 集成：on_context_overflow 每轮自动调用
# ══════════════════════════════════════════════════════════════

def test_on_context_overflow_invoked_each_turn():
    """BaseAgent 改动：每轮 LLM 调用前调用 on_context_overflow。"""

    class TrackedAgent(CodingAgent):
        def __init__(self, ctx):
            super().__init__(ctx)
            self.overflow_calls = 0

        async def on_context_overflow(self, messages):
            self.overflow_calls += 1
            return messages

    # 用 mock LLM 跑两轮
    class MockLLM:
        def __init__(self, scripts):
            self._s = list(scripts)
        async def chat_completion_stream(self, messages, *, max_tokens=8192, tools=None, tool_choice=None):
            if not self._s:
                raise RuntimeError("script empty")
            chunks = self._s.pop(0)
            for c in chunks:
                yield json.dumps(c)

    def _chunk(**kwargs):
        delta: dict = {}
        if "content" in kwargs:
            delta["content"] = kwargs["content"]
        if "tool_calls" in kwargs:
            delta["tool_calls"] = kwargs["tool_calls"]
        choice = {"index": 0, "delta": delta}
        if kwargs.get("finish_reason"):
            choice["finish_reason"] = kwargs["finish_reason"]
        return {"choices": [choice]}

    scripts = [
        # 轮 1：LLM 纯文本（无 tool_call）→ agent 终止
        [_chunk(content="done"), _chunk(finish_reason="stop")],
    ]
    ctx = _make_ctx(llm_client=MockLLM(scripts))
    agent = TrackedAgent(ctx)
    # 预置 messages → run() 走 is_resume 分支，跳过 build_initial_user_message。
    # 否则没 workspace_id 时 prompt dispatcher 的 project_type='' 会 raise
    # （这个测试只关心 on_context_overflow hook，不需要真实构造 prompt）。
    agent._messages = [{"role": "user", "content": "test"}]
    result = asyncio.run(agent.run())

    # 至少调一次 on_context_overflow（轮 1 前）
    assert agent.overflow_calls >= 1


if __name__ == "__main__":
    import inspect, traceback as _tb
    current = sys.modules[__name__]
    tests = [
        (n, f) for n, f in inspect.getmembers(current, inspect.isfunction)
        if n.startswith("test_")
    ]
    passed = failed = 0
    for name, func in tests:
        try:
            func()
            print(f"✓ {name}")
            passed += 1
        except Exception as e:
            print(f"✗ {name}: {type(e).__name__}: {e}")
            _tb.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
