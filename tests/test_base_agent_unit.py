"""BaseAgent 单元测试。

覆盖：
- 基础主循环（LLM 调用 → tool 执行 → 终止）
- Hook 触发
- 中断 / 暂停 / 恢复
- 错误处理
- Suspend / Resume（snapshot 往返）
- Tool 不存在的情况
- max_turns 耗尽
"""
import asyncio
import json
import os
import sys
from typing import Any

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.agents.base import BaseAgent
from app.agents.publisher import InMemoryEventPublisher
from app.agents.trace_writer import InMemoryTraceWriter
from app.agents.types import (
    AgentContext,
    AgentStatus,
    AgentType,
    StopReason,
    Tool,
    ToolResult,
)


# ══════════════════════════════════════════════════════════════
# Mock LLM Client
# ══════════════════════════════════════════════════════════════

class MockLLMClient:
    """按脚本返回预设响应的 mock"""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.call_log: list[dict[str, Any]] = []

    async def chat_completion(
        self,
        messages,
        *,
        max_tokens=8192,
        timeout=120.0,
        temperature=0.3,
        model=None,
        tools=None,
        tool_choice=None,
    ):
        self.call_log.append({
            "messages": messages,
            "tools_count": len(tools or []),
        })
        if not self._responses:
            raise RuntimeError("MockLLMClient: no more scripted responses")
        return self._responses.pop(0)


def _make_llm_response(content: str = "", tool_calls: list[dict] | None = None,
                      finish_reason: str = "stop"):
    """构造 OpenAI 风格响应"""
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
        finish_reason = "tool_calls"
    return {
        "id": "msg_test",
        "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def _make_tool_call(id: str, name: str, arguments: dict):
    return {
        "id": id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


# ══════════════════════════════════════════════════════════════
# Mock Agent 子类
# ══════════════════════════════════════════════════════════════

class MockAgent(BaseAgent[dict]):
    """最简 agent 实现 — 两个 tool：echo / complete"""

    agent_type = AgentType.SYSTEM

    def __init__(self, context: AgentContext, max_turns: int = 5) -> None:
        super().__init__(context)
        self._max_turns = max_turns
        self._terminate_requested = False
        self._finalize_result: dict[str, Any] = {}
        self.hook_log: list[str] = []   # 记录 hook 触发

    def get_system_prompt(self) -> str:
        return "You are a test agent."

    def get_tools(self) -> list[Tool]:
        async def echo_exec(args, ctx):
            return ToolResult(success=True, content=f"echo: {args.get('text', '')}")

        async def complete_exec(args, ctx):
            self._terminate_requested = True
            self._finalize_result = args
            return ToolResult(success=True, content="completed")

        return [
            Tool(
                name="echo",
                description="Echo a message",
                parameters_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                execute=echo_exec,
            ),
            Tool(
                name="complete",
                description="Mark the task done",
                parameters_schema={
                    "type": "object",
                    "properties": {"result": {"type": "object"}},
                },
                execute=complete_exec,
            ),
        ]

    def get_max_turns(self) -> int:
        return self._max_turns

    def build_initial_user_message(self) -> str:
        return self.ctx.input.get("prompt", "do something")

    def should_terminate(self) -> tuple[bool, str]:
        if self._terminate_requested:
            return True, "complete tool called"
        return False, ""

    async def finalize(self) -> dict:
        return self._finalize_result

    # hooks
    async def before_run(self) -> None:
        self.hook_log.append("before_run")

    async def after_run(self, result) -> None:
        self.hook_log.append(f"after_run:{result.status.value}")

    async def on_each_turn(self, turn) -> None:
        self.hook_log.append(f"on_each_turn:{turn}")

    async def before_tool_call(self, tool, args):
        self.hook_log.append(f"before_tool:{tool.name}")
        return args

    async def after_tool_call(self, tool, result):
        self.hook_log.append(f"after_tool:{tool.name}")
        return result

    async def on_llm_response(self, response) -> None:
        self.hook_log.append("on_llm_response")


def _make_ctx(publisher, trace_writer, llm, *, input_data=None, session_id="test_session"):
    return AgentContext(
        session_id=session_id,
        conversation_id=1,
        user_id=100,
        tenant_id=1,
        model="test-model",
        input=input_data or {},
        publisher=publisher,
        trace_writer=trace_writer,
        llm_client=llm,
    )


# ══════════════════════════════════════════════════════════════
# 1. 基础主循环
# ══════════════════════════════════════════════════════════════

def test_basic_loop_single_tool_then_complete():
    """LLM 调 complete tool → 一轮结束"""
    llm = MockLLMClient([
        _make_llm_response(tool_calls=[_make_tool_call("t1", "complete", {"result": {"ok": True}})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm, input_data={"prompt": "do it"})
    agent = MockAgent(ctx)

    result = asyncio.run(agent.run())

    assert result.status == AgentStatus.COMPLETED
    assert result.product == {"result": {"ok": True}}
    # turn 语义：每次完整的 "LLM 调用 + tool 执行" 后 turn++
    # 场景：turn=0 调 LLM → complete tool → turn++=1 → 下一轮 should_terminate True → break
    assert result.turns_used == 1


def test_multi_turn_tool_loop():
    """两轮：第一轮 echo，第二轮 complete"""
    llm = MockLLMClient([
        _make_llm_response(tool_calls=[_make_tool_call("t1", "echo", {"text": "hi"})]),
        _make_llm_response(tool_calls=[_make_tool_call("t2", "complete", {"result": {"n": 42}})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx)

    result = asyncio.run(agent.run())

    assert result.status == AgentStatus.COMPLETED
    assert result.product == {"result": {"n": 42}}
    # 验证 tool_history
    assert len(agent._tool_history) == 2
    assert agent._tool_history[0]["name"] == "echo"
    assert agent._tool_history[1]["name"] == "complete"


def test_llm_no_tool_call_terminates():
    """LLM 返回纯文本（无 tool_calls）→ 循环结束，status=COMPLETED"""
    llm = MockLLMClient([_make_llm_response(content="All done.")])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx)

    result = asyncio.run(agent.run())

    assert result.status == AgentStatus.COMPLETED
    assert result.stop_reason == StopReason.LLM_NO_TOOL_CALL


# ══════════════════════════════════════════════════════════════
# 2. Hook 触发顺序
# ══════════════════════════════════════════════════════════════

def test_hooks_triggered_in_order():
    llm = MockLLMClient([
        _make_llm_response(tool_calls=[_make_tool_call("t1", "complete", {"result": {}})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx)

    asyncio.run(agent.run())

    # 期望序列：before_run → on_each_turn:0 → on_llm_response → before_tool:complete → after_tool:complete → after_run:completed
    assert agent.hook_log[0] == "before_run"
    assert "on_each_turn:0" in agent.hook_log
    assert "on_llm_response" in agent.hook_log
    assert "before_tool:complete" in agent.hook_log
    assert "after_tool:complete" in agent.hook_log
    assert agent.hook_log[-1].startswith("after_run:completed")


# ══════════════════════════════════════════════════════════════
# 3. max_turns 耗尽
# ══════════════════════════════════════════════════════════════

def test_max_turns_exceeded():
    """无限调 echo，永不 complete → 应该达到 max_turns 退出"""
    # 预设足够多的响应
    responses = [
        _make_llm_response(tool_calls=[_make_tool_call(f"t{i}", "echo", {"text": f"msg{i}"})])
        for i in range(20)
    ]
    llm = MockLLMClient(responses)
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx, max_turns=3)

    result = asyncio.run(agent.run())

    assert result.stop_reason == StopReason.MAX_TURNS_EXCEEDED
    assert result.turns_used == 3


# ══════════════════════════════════════════════════════════════
# 4. 中断（cancel）
# ══════════════════════════════════════════════════════════════

def test_cancel_before_run():
    """cancel 后启动 run → 第一轮就退出"""
    llm = MockLLMClient([
        _make_llm_response(tool_calls=[_make_tool_call("t1", "echo", {"text": "hi"})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx)

    agent.cancel()
    result = asyncio.run(agent.run())

    assert result.status == AgentStatus.ABORTED
    assert result.stop_reason == StopReason.CANCELLED


# ══════════════════════════════════════════════════════════════
# 5. 错误处理（LLM 抛异常）
# ══════════════════════════════════════════════════════════════

def test_llm_error_non_retryable():
    """LLM 抛非可重试异常 → status=FAILED"""

    class BrokenLLM:
        async def chat_completion(self, messages, **kwargs):
            raise ValueError("broken")

    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, BrokenLLM())
    agent = MockAgent(ctx)

    result = asyncio.run(agent.run())

    assert result.status == AgentStatus.FAILED
    assert result.stop_reason == StopReason.ERROR
    assert "broken" in (result.error_message or "")


# ══════════════════════════════════════════════════════════════
# 6. Tool 不存在
# ══════════════════════════════════════════════════════════════

def test_unknown_tool_name():
    """LLM 调用了未注册的 tool → tool result 报错，LLM 下一轮继续（脚本里下一轮 complete）"""
    llm = MockLLMClient([
        _make_llm_response(tool_calls=[_make_tool_call("t1", "nonexistent_tool", {})]),
        _make_llm_response(tool_calls=[_make_tool_call("t2", "complete", {"result": {"final": True}})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx)

    result = asyncio.run(agent.run())

    assert result.status == AgentStatus.COMPLETED
    # 第一轮应该有 tool 错误的消息
    tool_msgs = [m for m in agent._messages if m.get("role") == "tool"]
    assert any("not found" in (m.get("content") or "") for m in tool_msgs)


# ══════════════════════════════════════════════════════════════
# 7. 事件发布 + Trace 记录
# ══════════════════════════════════════════════════════════════

def test_events_and_traces_published():
    llm = MockLLMClient([
        _make_llm_response(tool_calls=[_make_tool_call("t1", "complete", {"result": {}})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx)

    asyncio.run(agent.run())

    # 事件：start + tool_call + tool_result + done
    event_types = [e["type"] for e in pub.events]
    assert "system.start" in event_types
    assert "system.tool_call" in event_types
    assert "system.tool_result" in event_types
    assert "system.done" in event_types

    # Trace：llm_request + llm_response + tool_call + tool_result + state_change
    trace_types = [t["event_type"] for t in tw.traces]
    assert "llm_request" in trace_types
    assert "llm_response" in trace_types
    assert "tool_call" in trace_types
    assert "tool_result" in trace_types

    # Seq 单调
    seqs = [e["seq"] for e in pub.events]
    assert seqs == sorted(seqs) == list(range(1, len(seqs) + 1))


# ══════════════════════════════════════════════════════════════
# 8. Suspend / Resume（snapshot 往返）
# ══════════════════════════════════════════════════════════════

def test_snapshot_roundtrip():
    """Agent 跑到一半 snapshot → 再从 snapshot 恢复 → 状态应一致"""
    llm = MockLLMClient([
        _make_llm_response(tool_calls=[_make_tool_call("t1", "echo", {"text": "hi"})]),
        _make_llm_response(tool_calls=[_make_tool_call("t2", "complete", {"result": {"v": 1}})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx)

    # 跑完整流程
    result = asyncio.run(agent.run())
    snapshot = result.snapshot

    assert snapshot is not None
    assert snapshot["status"] == "completed"
    # 两轮 LLM 调用（echo, complete）完成后，turn == 2
    assert snapshot["turn"] == 2
    assert len(snapshot["messages"]) > 0

    # 从 snapshot 恢复一个新 agent
    restored = MockAgent.from_snapshot(ctx, snapshot)
    assert restored.status == AgentStatus.COMPLETED
    assert restored._turn == 2
    assert len(restored._messages) == len(agent._messages)


# ══════════════════════════════════════════════════════════════
# 9. ask_user / pause 场景（should_pause=True）
# ══════════════════════════════════════════════════════════════

def test_pause_on_ask_user_like_tool():
    """Tool 返回 should_pause=True → agent 进入 PAUSED"""

    class PauseAgent(MockAgent):
        def get_tools(self):
            async def ask_exec(args, ctx):
                return ToolResult(
                    success=True,
                    content="Waiting for user reply...",
                    should_pause=True,
                )

            return [
                Tool(
                    name="ask",
                    description="Ask user",
                    parameters_schema={"type": "object"},
                    execute=ask_exec,
                ),
            ]

    llm = MockLLMClient([
        _make_llm_response(tool_calls=[_make_tool_call("t1", "ask", {})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = PauseAgent(ctx)

    # 启动后 pause，我们用另一个 task 在外面 cancel 它
    async def run_and_cancel():
        task = asyncio.create_task(agent.run())
        # 给点时间让 agent 到 pause 状态
        await asyncio.sleep(0.1)
        agent.cancel()  # 退出 pause 并退出循环
        return await task

    result = asyncio.run(run_and_cancel())

    # 被 cancel，status=ABORTED
    assert result.status == AgentStatus.ABORTED
    # 应产生 paused 事件
    assert any(e["type"] == "system.paused" for e in pub.events)


# ══════════════════════════════════════════════════════════════
# 10. 并行 tool calls
# ══════════════════════════════════════════════════════════════

def test_parallel_tool_calls():
    """一轮中多个 tool_calls 并行执行"""
    llm = MockLLMClient([
        _make_llm_response(tool_calls=[
            _make_tool_call("t1", "echo", {"text": "a"}),
            _make_tool_call("t2", "echo", {"text": "b"}),
            _make_tool_call("t3", "echo", {"text": "c"}),
        ]),
        _make_llm_response(tool_calls=[_make_tool_call("t4", "complete", {"result": {}})]),
    ])
    pub = InMemoryEventPublisher()
    tw = InMemoryTraceWriter()
    ctx = _make_ctx(pub, tw, llm)
    agent = MockAgent(ctx)

    result = asyncio.run(agent.run())

    assert result.status == AgentStatus.COMPLETED
    # tool_history 应有 4 条（3 echo + 1 complete）
    assert len(agent._tool_history) == 4
    # tool result messages 在 agent._messages 中应有正确的 tool_call_id
    tool_msgs = [m for m in agent._messages if m.get("role") == "tool"]
    assert sorted(m["tool_call_id"] for m in tool_msgs) == ["t1", "t2", "t3", "t4"]


if __name__ == "__main__":
    import inspect
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
            import traceback
            print(f"✗ {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
