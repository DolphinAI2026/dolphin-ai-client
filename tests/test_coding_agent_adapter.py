"""CodingAgentStreamAdapter 单测（Stage 3）。

覆盖：
- translate_event 事件格式映射（全部事件类型）
- Adapter.run 返回 async iterator
- 事件序列：模拟完整 agent 跑通 → 事件按 VibeCodingAgent 兼容格式 yield
- Adapter 调用后 publisher 恢复原值
- 下游 pipeline 消费方式兼容（type 是 top-level key，不是嵌套 data）
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

from app.agents.coding import CodingAgent, CodingAgentStreamAdapter
from app.agents.coding.adapter import translate_event
from app.agents.publisher import InMemoryEventPublisher
from app.agents.trace_writer import InMemoryTraceWriter
from app.agents.types import AgentContext


# ══════════════════════════════════════════════════════════════
# 1. translate_event 事件翻译
# ══════════════════════════════════════════════════════════════

def test_translate_agent_tool():
    raw = {
        "type": "coding.agent_tool",
        "agent": "coding",
        "session_id": "s1",
        "data": {"tool": "read_file", "tool_display": "📂 Read", "input_preview": "a.txt"},
    }
    out = translate_event(raw)
    assert out == {
        "type": "agent_tool",
        "tool": "read_file",
        "tool_display": "📂 Read",
        "input_preview": "a.txt",
    }


def test_translate_agent_result():
    raw = {
        "type": "coding.agent_result",
        "data": {"tool": "read_file", "tool_display": "📂 Read", "output_preview": "content...", "is_error": False},
    }
    out = translate_event(raw)
    assert out["type"] == "agent_result"
    assert out["tool"] == "read_file"
    assert out["is_error"] is False


def test_translate_agent_thinking():
    raw = {"type": "coding.agent_thinking", "data": {"content": "分析完成"}}
    out = translate_event(raw)
    assert out == {"type": "agent_thinking", "content": "分析完成"}


def test_translate_agent_thinking_delta():
    raw = {"type": "coding.agent_thinking_delta", "data": {"content": "Let me "}}
    out = translate_event(raw)
    assert out == {"type": "agent_thinking_delta", "content": "Let me "}


def test_translate_tool_progress_to_command_output():
    raw = {"type": "coding.tool_progress", "data": {"tool": "run_command", "text": "Compiled"}}
    out = translate_event(raw)
    assert out["type"] == "agent_command_output"
    assert out["text"] == "Compiled"


def test_translate_done():
    raw = {"type": "coding.done", "data": {"session_id": "s", "status": "completed", "turns_used": 3}}
    out = translate_event(raw)
    # done 事件固定转成 agent_done + result="completed"（除非 data.result 存在）
    assert out == {"type": "agent_done", "result": "completed"}


def test_translate_failed_to_agent_error():
    raw = {"type": "coding.failed", "data": {"error": "LLM 超时"}}
    out = translate_event(raw)
    assert out == {"type": "agent_error", "message": "LLM 超时"}


def test_translate_ignores_base_agent_tool_call_tool_result():
    """BaseAgent 通用 tool_call/tool_result 被 CodingAgent agent_tool/agent_result 覆盖，应忽略"""
    assert translate_event({"type": "coding.tool_call", "data": {}}) is None
    assert translate_event({"type": "coding.tool_result", "data": {}}) is None


def test_translate_ignores_start_paused_aborted():
    for action in ["start", "paused", "aborted"]:
        assert translate_event({"type": f"coding.{action}", "data": {}}) is None


def test_translate_ignores_non_coding_namespace():
    assert translate_event({"type": "brainstorm.ask_user", "data": {}}) is None
    assert translate_event({"type": "system.ping", "data": {}}) is None


# ══════════════════════════════════════════════════════════════
# 2. Adapter.run 端到端（mock LLM）
# ══════════════════════════════════════════════════════════════

class MockStreamLLM:
    def __init__(self, scripts):
        self._s = list(scripts)

    async def chat_completion_stream(self, messages, *, max_tokens=8192, tools=None, tool_choice=None):
        if not self._s:
            raise RuntimeError("MockStreamLLM: script exhausted")
        chunks = self._s.pop(0)
        for c in chunks:
            yield json.dumps(c)


def _chunk(*, content=None, reasoning=None, tool_calls=None, finish_reason=None):
    delta = {}
    if content is not None:
        delta["content"] = content
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    choice = {"index": 0, "delta": delta}
    if finish_reason:
        choice["finish_reason"] = finish_reason
    return {"choices": [choice]}


def _make_ctx(llm, workspace_id=None):
    return AgentContext(
        session_id="stream_adapter_test",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="test-model",
        workspace_id=workspace_id,
        input={},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
        llm_client=llm,
    )


def test_adapter_yields_pipeline_compatible_events_end_to_end():
    """完整模拟：LLM 调 write_file（真实 workspace）→ LLM 纯文本结束"""
    with tempfile.TemporaryDirectory() as tmp:
        ws_path = Path(tmp) / "ws__aa"
        ws_path.mkdir()
        (ws_path / ".workspace.json").write_text(json.dumps({
            "id": "ws_aa", "name": "ws__aa", "project_name": "t",
            "project_type": "form-component-dual", "user_id": 1,
        }))
        os.environ["APAAS_WORKSPACE_ROOT"] = tmp
        from app.coding.workspace import WorkspaceManager
        WorkspaceManager._workspace_path_cache.clear()

        llm = MockStreamLLM([
            # 轮 1：调 write_file
            [
                _chunk(tool_calls=[{
                    "index": 0, "id": "c1",
                    "function": {"name": "write_file",
                                 "arguments": '{"file_path": "x.txt", "content": "hi"}'},
                }]),
                _chunk(finish_reason="tool_calls"),
            ],
            # 轮 2：纯文本结束
            [_chunk(content="任务完成"), _chunk(finish_reason="stop")],
        ])
        ctx = _make_ctx(llm, workspace_id="ws_aa")
        agent = CodingAgent(ctx)
        # 预置 messages → base run() 走 is_resume 分支，跳过 build_initial_user_message。
        # build_initial 会读 WorkspaceManager；但 WorkspaceManager 的 WORKSPACE_ROOT
        # 在模块 import 时就已固定（见 workspace.py 顶部 `_resolve_workspace_root`），
        # 环境变量 APAAS_WORKSPACE_ROOT 晚设无效 —— 测试并发跑时 workspace 会读不到。
        # 这个 adapter 测试只关心事件流 shape，不需要真实 prompt 构造，直接跳过。
        agent._messages = [
            {"role": "system", "content": "test"},
            {"role": "user", "content": "写个文件"},
        ]
        adapter = CodingAgentStreamAdapter(agent)

        async def collect():
            events = []
            async for event in adapter.run(requirement="写个文件", max_turns=5):
                events.append(event)
            return events

        events = asyncio.run(collect())

        # 每个事件都必须有顶层 type 字段（VibeCodingAgent 兼容）
        for e in events:
            assert "type" in e, f"event missing type: {e}"

        types = [e["type"] for e in events]
        # 至少要有 agent_tool, agent_result, 最后 agent_thinking 或 agent_done
        assert "agent_tool" in types
        assert "agent_result" in types
        # 无 "coding." 前缀的事件
        assert not any(t.startswith("coding.") for t in types)


def test_adapter_handles_agent_error():
    """LLM 总失败 → adapter yield agent_error 而非抛异常"""

    class BrokenLLM:
        async def chat_completion_stream(self, messages, **kw):
            raise ValueError("broken LLM")
            yield  # make it a generator

    ctx = _make_ctx(BrokenLLM())
    agent = CodingAgent(ctx)
    adapter = CodingAgentStreamAdapter(agent)

    async def collect():
        events = []
        async for event in adapter.run(requirement="x", max_turns=3):
            events.append(event)
        return events

    events = asyncio.run(collect())
    # 应该看到 agent_error
    types = [e["type"] for e in events]
    assert "agent_error" in types


def test_adapter_restores_publisher_after_run():
    """Adapter 执行后应恢复原 publisher"""
    llm = MockStreamLLM([[_chunk(content="done"), _chunk(finish_reason="stop")]])
    orig_pub = InMemoryEventPublisher()
    ctx = AgentContext(
        session_id="s", conversation_id=1, user_id=1, tenant_id=1, model="m",
        input={}, publisher=orig_pub, llm_client=llm,
    )
    agent = CodingAgent(ctx)
    adapter = CodingAgentStreamAdapter(agent)

    async def run():
        async for _ in adapter.run(requirement="x"):
            pass

    asyncio.run(run())

    # 原 publisher 被恢复
    assert agent.ctx.publisher is orig_pub


def test_adapter_passes_through_conversation_summary_and_max_turns():
    """Adapter 把 requirement / summary / max_turns 注入到 agent.ctx.input"""
    llm = MockStreamLLM([[_chunk(content="done"), _chunk(finish_reason="stop")]])
    ctx = _make_ctx(llm)
    agent = CodingAgent(ctx)
    adapter = CodingAgentStreamAdapter(agent)

    captured_input = {}

    class SpyAgent(CodingAgent):
        def build_initial_user_message(self):
            captured_input.update(self.ctx.input)
            return super().build_initial_user_message()

    agent = SpyAgent(ctx)
    adapter = CodingAgentStreamAdapter(agent)

    async def run():
        async for _ in adapter.run(
            requirement="需求",
            conversation_summary="过往",
            max_turns=7,
        ):
            pass

    asyncio.run(run())
    assert captured_input.get("requirement") == "需求"
    assert captured_input.get("conversation_summary") == "过往"
    assert captured_input.get("max_turns") == 7


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
