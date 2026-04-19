"""CodingAgent Stage 2.2 单测：LLM 流式调用（_call_llm 覆盖）。

覆盖：
- content delta 累积成完整 content
- reasoning_content delta 累积
- tool_calls delta 按 index 累积 + JSON 合法性校验
- finish_reason 从最后一个 chunk 提取
- content delta 实时发送 coding.agent_thinking_delta 事件
- 无 tool_call 时发送一条 coding.agent_thinking 事件（兼容老格式）
- 非法 tool_call arguments JSON 降级为空 dict
- 完整 CodingAgent.run() 能调用 _call_llm 正常走 tool loop
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.agents.coding import CodingAgent
from app.agents.publisher import InMemoryEventPublisher
from app.agents.trace_writer import InMemoryTraceWriter
from app.agents.types import AgentContext, AgentStatus, AgentType, LLMResponse, ToolCall


# ══════════════════════════════════════════════════════════════
# Mock 流式 LLM
# ══════════════════════════════════════════════════════════════

class MockStreamLLMClient:
    """按脚本返回流式 chunks 的 mock"""

    def __init__(self, scripts: list[list[dict]]) -> None:
        """
        scripts: list of "chunk lists" —— 每次调用 chat_completion_stream
        消费一条 chunk list。
        """
        self._scripts = list(scripts)
        self.call_log: list[dict] = []

    async def chat_completion_stream(self, messages, *, max_tokens=8192, tools=None, tool_choice=None):
        self.call_log.append({"messages": messages, "tools_count": len(tools or [])})
        if not self._scripts:
            raise RuntimeError("MockStreamLLMClient: no more scripts")
        chunks = self._scripts.pop(0)
        for c in chunks:
            yield json.dumps(c, ensure_ascii=False)


def _delta_chunk(*, content=None, reasoning=None, tool_calls=None, finish_reason=None):
    """构造一个流式 chunk（OpenAI 格式）"""
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    choice: dict = {"index": 0, "delta": delta}
    if finish_reason:
        choice["finish_reason"] = finish_reason
    return {"choices": [choice]}


def _make_ctx(llm, workspace_id=None, input_data=None):
    return AgentContext(
        session_id="cs_stream_test",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="test-model",
        workspace_id=workspace_id,
        input=input_data or {"requirement": "test stream"},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
        llm_client=llm,
    )


# ══════════════════════════════════════════════════════════════
# 1. content delta 累积
# ══════════════════════════════════════════════════════════════

def test_stream_content_delta_accumulated():
    llm = MockStreamLLMClient([
        [
            _delta_chunk(content="Hello "),
            _delta_chunk(content="world"),
            _delta_chunk(finish_reason="stop"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "hi"}]

    resp = asyncio.run(agent._call_llm())
    assert isinstance(resp, LLMResponse)
    assert resp.content == "Hello world"
    assert resp.finish_reason == "stop"
    assert resp.tool_calls == []


def test_stream_reasoning_delta_accumulated():
    llm = MockStreamLLMClient([
        [
            _delta_chunk(reasoning="Let me think... "),
            _delta_chunk(reasoning="OK here's the plan."),
            _delta_chunk(content="Answer: 42"),
            _delta_chunk(finish_reason="stop"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "q"}]

    resp = asyncio.run(agent._call_llm())
    assert resp.content == "Answer: 42"
    # reasoning_content 累积到 trace 里（通过 trace_writer 观察）
    trace_resp = [t for t in ctx.trace_writer.traces if t["event_type"] == "llm_response"]
    assert len(trace_resp) == 1
    assert "Let me think" in trace_resp[0]["payload"]["reasoning_preview"]


# ══════════════════════════════════════════════════════════════
# 2. tool_calls 累积
# ══════════════════════════════════════════════════════════════

def test_stream_tool_calls_accumulated():
    """tool_calls delta 按 index 累积成完整 ToolCall"""
    llm = MockStreamLLMClient([
        [
            _delta_chunk(tool_calls=[{
                "index": 0, "id": "call_1",
                "function": {"name": "read_file", "arguments": ""},
            }]),
            _delta_chunk(tool_calls=[{
                "index": 0,
                "function": {"arguments": '{"path": '},
            }]),
            _delta_chunk(tool_calls=[{
                "index": 0,
                "function": {"arguments": '"a.txt"}'},
            }]),
            _delta_chunk(finish_reason="tool_calls"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "read"}]

    resp = asyncio.run(agent._call_llm())
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "a.txt"}
    assert resp.finish_reason == "tool_calls"


def test_stream_parallel_tool_calls():
    """一次响应多个并行 tool_calls（不同 index）"""
    llm = MockStreamLLMClient([
        [
            _delta_chunk(tool_calls=[{
                "index": 0, "id": "c1",
                "function": {"name": "read_file", "arguments": '{"path": "a.txt"}'},
            }]),
            _delta_chunk(tool_calls=[{
                "index": 1, "id": "c2",
                "function": {"name": "read_file", "arguments": '{"path": "b.txt"}'},
            }]),
            _delta_chunk(tool_calls=[{
                "index": 2, "id": "c3",
                "function": {"name": "write_file", "arguments": '{"path": "c.txt", "content": "x"}'},
            }]),
            _delta_chunk(finish_reason="tool_calls"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "p"}]

    resp = asyncio.run(agent._call_llm())
    assert len(resp.tool_calls) == 3
    assert [tc.name for tc in resp.tool_calls] == ["read_file", "read_file", "write_file"]
    assert resp.tool_calls[2].arguments == {"path": "c.txt", "content": "x"}


def test_stream_invalid_json_arguments_downgraded():
    """tool_call 里非法 JSON arguments 降级为空 dict"""
    llm = MockStreamLLMClient([
        [
            _delta_chunk(tool_calls=[{
                "index": 0, "id": "c1",
                "function": {"name": "read_file", "arguments": "not valid {{ json"},
            }]),
            _delta_chunk(finish_reason="tool_calls"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "x"}]

    resp = asyncio.run(agent._call_llm())
    assert len(resp.tool_calls) == 1
    # arguments 被降级为 "{}"
    assert resp.tool_calls[0].arguments == {}


# ══════════════════════════════════════════════════════════════
# 3. 实时事件推送（delta）
# ══════════════════════════════════════════════════════════════

def test_content_delta_emits_thinking_delta_events():
    llm = MockStreamLLMClient([
        [
            _delta_chunk(content="A"),
            _delta_chunk(content="B"),
            _delta_chunk(content="C"),
            _delta_chunk(finish_reason="stop"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "x"}]

    asyncio.run(agent._call_llm())
    delta_events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_thinking_delta"]
    assert len(delta_events) == 3
    assert [e["data"]["content"] for e in delta_events] == ["A", "B", "C"]


def test_reasoning_delta_emits_thinking_delta_with_reasoning_flag():
    llm = MockStreamLLMClient([
        [
            _delta_chunk(reasoning="thinking..."),
            _delta_chunk(finish_reason="stop"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "x"}]

    asyncio.run(agent._call_llm())
    delta_events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_thinking_delta"]
    assert len(delta_events) == 1
    assert delta_events[0]["data"]["reasoning"] is True


def test_no_tool_call_emits_single_thinking_event():
    """LLM 返回纯文本（无 tool_call）→ 触发一条 coding.agent_thinking 事件（兼容 VibeCodingAgent 格式）"""
    llm = MockStreamLLMClient([
        [
            _delta_chunk(content="Analysis: "),
            _delta_chunk(content="done."),
            _delta_chunk(finish_reason="stop"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "x"}]

    asyncio.run(agent._call_llm())
    thinking_events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_thinking"]
    assert len(thinking_events) == 1
    assert thinking_events[0]["data"]["content"] == "Analysis: done."


def test_tool_call_response_does_not_emit_thinking_event():
    """有 tool_call 时不发 agent_thinking 事件（只有 delta）"""
    llm = MockStreamLLMClient([
        [
            _delta_chunk(tool_calls=[{
                "index": 0, "id": "c1",
                "function": {"name": "read_file", "arguments": '{"path": "a"}'},
            }]),
            _delta_chunk(finish_reason="tool_calls"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "x"}]

    asyncio.run(agent._call_llm())
    thinking_events = [e for e in ctx.publisher.events if e["type"] == "coding.agent_thinking"]
    assert len(thinking_events) == 0


# ══════════════════════════════════════════════════════════════
# 4. Trace 记录
# ══════════════════════════════════════════════════════════════

def test_llm_request_and_response_traces_written():
    llm = MockStreamLLMClient([
        [
            _delta_chunk(content="ok"),
            _delta_chunk(finish_reason="stop"),
        ],
    ])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    agent._messages = [{"role": "user", "content": "hi"}]
    asyncio.run(agent._call_llm())

    trace_types = [t["event_type"] for t in ctx.trace_writer.traces]
    assert "llm_request" in trace_types
    assert "llm_response" in trace_types

    response_trace = next(t for t in ctx.trace_writer.traces if t["event_type"] == "llm_response")
    assert response_trace["payload"]["content_preview"].startswith("ok")


# ══════════════════════════════════════════════════════════════
# 5. 完整 agent.run() 流程（mock LLM + 模拟完整对话）
# ══════════════════════════════════════════════════════════════

def test_full_run_with_tool_then_complete():
    """
    两轮对话：
    轮 1：LLM 调 write_file → agent 执行（在真实 workspace 下）
    轮 2：LLM 返回纯文本 → agent 结束
    """
    with tempfile.TemporaryDirectory() as tmp:
        # 设置 workspace
        ws_path = Path(tmp) / "ws__abc"
        ws_path.mkdir()
        (ws_path / ".workspace.json").write_text(json.dumps({
            "id": "ws_abc", "name": "ws__abc", "project_name": "t",
            "project_type": "form-component-dual", "user_id": 1,
        }))
        os.environ["APAAS_WORKSPACE_ROOT"] = tmp
        from app.coding.workspace import WorkspaceManager
        WorkspaceManager._workspace_path_cache.clear()

        llm = MockStreamLLMClient([
            # 轮 1：调 write_file
            [
                _delta_chunk(tool_calls=[{
                    "index": 0, "id": "c1",
                    "function": {"name": "write_file",
                                 "arguments": '{"file_path": "hello.txt", "content": "hi"}'},
                }]),
                _delta_chunk(finish_reason="tool_calls"),
            ],
            # 轮 2：纯文本，结束
            [
                _delta_chunk(content="Done."),
                _delta_chunk(finish_reason="stop"),
            ],
        ])
        ctx = _make_ctx(llm, workspace_id="ws_abc")
        agent = CodingAgent(ctx)
        result = asyncio.run(agent.run())

        assert result.status == AgentStatus.COMPLETED
        assert result.turns_used == 1  # 轮 1 调了 tool，轮 2 无 tool 直接终止

        # 实际文件写入验证
        assert (ws_path / "hello.txt").exists()
        assert (ws_path / "hello.txt").read_text() == "hi"

        # 事件类型验证
        event_types = {e["type"] for e in ctx.publisher.events}
        assert "coding.start" in event_types
        assert "coding.tool_call" in event_types
        assert "coding.tool_result" in event_types
        assert "coding.done" in event_types
        assert "coding.agent_thinking" in event_types  # 轮 2 的纯文本


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
