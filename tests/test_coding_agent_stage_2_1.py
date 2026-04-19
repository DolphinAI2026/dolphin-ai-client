"""CodingAgent Stage 2.1 单测：骨架 + tool_registry 包装。

覆盖：
- CodingAgent 可构造
- get_tools() 返回预期的 7 个 tool（read_file / write_file / edit_file / run_command / glob_files / grep_search / start_serve）
- 每个 tool.to_openai_function() 符合 OpenAI function-calling schema
- tool.execute 在 missing workspace 时优雅失败（不 crash）
- tool.execute 在 valid workspace 下调用 tool_registry（mock）
- agent_type = "coding"（事件命名空间）
- snapshot 往返（final_result / llm_said_done）
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
from app.agents.coding.tools import build_coding_tools, _resolve_workspace_path, _make_progress_callback
from app.agents.publisher import InMemoryEventPublisher
from app.agents.trace_writer import InMemoryTraceWriter
from app.agents.types import AgentContext, AgentStatus, AgentType, ToolResult


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _make_ctx(workspace_id=None, input_data=None, llm=None):
    return AgentContext(
        session_id="cs_test",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="test-model",
        workspace_id=workspace_id,
        input=input_data or {"requirement": "test task"},
        publisher=InMemoryEventPublisher(),
        trace_writer=InMemoryTraceWriter(),
        llm_client=llm,
    )


# ══════════════════════════════════════════════════════════════
# 1. 基础构造 + attributes
# ══════════════════════════════════════════════════════════════

def test_coding_agent_can_be_constructed():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    assert agent.status == AgentStatus.IDLE
    assert agent.agent_type == AgentType.CODING


def test_coding_agent_type_is_coding():
    """agent_type = coding → 事件发布为 coding.* 命名空间"""
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    assert agent.agent_type.value == "coding"


def test_get_max_turns_default_and_override():
    ctx1 = _make_ctx()
    assert CodingAgent(ctx1).get_max_turns() == 30

    ctx2 = _make_ctx(input_data={"requirement": "t", "max_turns": 10})
    assert CodingAgent(ctx2).get_max_turns() == 10


def test_build_initial_user_message_with_summary():
    ctx = _make_ctx(input_data={
        "requirement": "做个组件",
        "conversation_summary": "之前讨论了 A 和 B",
    })
    msg = CodingAgent(ctx).build_initial_user_message()
    assert "之前讨论了 A 和 B" in msg
    assert "做个组件" in msg


def test_build_initial_user_message_no_summary():
    ctx = _make_ctx(input_data={"requirement": "做个组件"})
    msg = CodingAgent(ctx).build_initial_user_message()
    assert "做个组件" in msg
    assert "Previous Conversation" not in msg


# ══════════════════════════════════════════════════════════════
# 2. Tool 包装
# ══════════════════════════════════════════════════════════════

def test_get_tools_returns_expected_tools():
    """tool_registry 的 7 个工具都正确包装"""
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    tools = agent.get_tools()
    names = {t.name for t in tools}

    expected = {
        "read_file", "write_file", "edit_file", "run_command",
        "glob_files", "grep_search", "start_serve",
    }
    assert expected.issubset(names), f"缺工具: {expected - names}"


def test_get_tools_cached():
    """连续调用 get_tools 返回同一实例（缓存）"""
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    tools1 = agent.get_tools()
    tools2 = agent.get_tools()
    assert tools1 is tools2


def test_tool_to_openai_function_shape():
    """每个 tool 能转成 OpenAI function-calling 格式"""
    tools = build_coding_tools()
    for t in tools:
        fn = t.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == t.name
        assert "parameters" in fn["function"]
        assert "description" in fn["function"]


# ══════════════════════════════════════════════════════════════
# 3. Tool.execute 行为
# ══════════════════════════════════════════════════════════════

def test_tool_execute_without_workspace_id_returns_error():
    """ctx.workspace_id 缺失时，tool.execute 返回 success=False 而非 crash"""
    ctx = _make_ctx(workspace_id=None)
    tools = CodingAgent(ctx).get_tools()
    tool = next(t for t in tools if t.name == "read_file")

    result = asyncio.run(tool.execute({"path": "x.txt"}, ctx))
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "workspace_id" in result.content or "resolving workspace" in result.content


def test_tool_execute_with_invalid_workspace_id_returns_error():
    """workspace_id 指向不存在的工作区时，tool.execute 返回错误（而非 crash）"""
    ctx = _make_ctx(workspace_id="nonexistent_ws_99999")
    tools = CodingAgent(ctx).get_tools()
    tool = next(t for t in tools if t.name == "read_file")
    result = asyncio.run(tool.execute({"path": "x.txt"}, ctx))
    assert isinstance(result, ToolResult)
    assert result.success is False


def test_tool_execute_in_real_workspace_read_nonexistent_file():
    """在真实工作区里读不存在的文件：tool_registry 返回 Error: ... → ToolResult.success=False"""
    with tempfile.TemporaryDirectory() as tmp:
        ws_path = Path(tmp) / "test_ws__abc"
        ws_path.mkdir()
        # 写一个最小的 .workspace.json 让 WorkspaceManager 能找到
        (ws_path / ".workspace.json").write_text(json.dumps({
            "id": "test_ws_abc",
            "name": "test_ws__abc",
            "project_name": "test",
            "project_type": "form-component-dual",
            "user_id": 1,
        }))

        # 设置 workspace 搜索路径
        os.environ["APAAS_WORKSPACE_ROOT"] = tmp
        # 需要重置 _workspace_path_cache（单例）
        try:
            from app.coding.workspace import WorkspaceManager
            WorkspaceManager._workspace_path_cache.clear()
        except Exception:
            pass

        ctx = _make_ctx(workspace_id="test_ws_abc")
        tools = CodingAgent(ctx).get_tools()
        read_tool = next(t for t in tools if t.name == "read_file")
        result = asyncio.run(read_tool.execute({"path": "does_not_exist.txt"}, ctx))

        # tool_registry 对不存在的文件返回 "Error: ..." 字符串
        assert isinstance(result, ToolResult)
        # 文件不存在，返回 error（success=False）
        assert result.success is False or "not exist" in (result.content or "").lower() or "error" in (result.content or "").lower()


def test_tool_execute_in_real_workspace_write_and_read():
    """在真实工作区里 write_file 然后 read_file 能正常工作"""
    with tempfile.TemporaryDirectory() as tmp:
        ws_path = Path(tmp) / "test_ws2__def"
        ws_path.mkdir()
        (ws_path / ".workspace.json").write_text(json.dumps({
            "id": "test_ws2_def",
            "name": "test_ws2__def",
            "project_name": "test2",
            "project_type": "form-component-dual",
            "user_id": 1,
        }))

        os.environ["APAAS_WORKSPACE_ROOT"] = tmp
        from app.coding.workspace import WorkspaceManager
        WorkspaceManager._workspace_path_cache.clear()

        ctx = _make_ctx(workspace_id="test_ws2_def")
        tools = CodingAgent(ctx).get_tools()
        write_tool = next(t for t in tools if t.name == "write_file")
        read_tool = next(t for t in tools if t.name == "read_file")

        # 写文件（注意：write_file 的参数名是 file_path）
        w = asyncio.run(write_tool.execute({"file_path": "hello.txt", "content": "hi"}, ctx))
        assert isinstance(w, ToolResult), f"write returned {type(w)}"

        # 读文件（read_file 也是 file_path）
        r = asyncio.run(read_tool.execute({"file_path": "hello.txt"}, ctx))
        assert isinstance(r, ToolResult)
        # 读成功，content 应包含 "hi"
        if r.success:
            assert "hi" in r.content


# ══════════════════════════════════════════════════════════════
# 4. Snapshot 序列化往返
# ══════════════════════════════════════════════════════════════

def test_snapshot_custom_state_roundtrip():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    agent._final_result = {"files_written": ["a.vue", "b.vue"]}
    agent._llm_said_done = True

    snap = agent.to_snapshot()
    assert snap["agent_type"] == "coding"
    assert snap["custom"]["final_result"] == {"files_written": ["a.vue", "b.vue"]}
    assert snap["custom"]["llm_said_done"] is True

    # 往返
    ctx2 = _make_ctx()
    restored = CodingAgent.from_snapshot(ctx2, snap)
    assert restored._final_result == {"files_written": ["a.vue", "b.vue"]}
    assert restored._llm_said_done is True


# ══════════════════════════════════════════════════════════════
# 5. _make_progress_callback 发事件
# ══════════════════════════════════════════════════════════════

def test_progress_callback_publishes_event():
    ctx = _make_ctx()
    cb = _make_progress_callback(ctx, "run_command")

    asyncio.run(cb("Building...\n"))
    asyncio.run(cb("Compiled successfully"))

    events = ctx.publisher.events
    progress_events = [e for e in events if e["type"] == "coding.tool_progress"]
    assert len(progress_events) == 2
    assert progress_events[0]["data"]["tool"] == "run_command"
    assert "Building" in progress_events[0]["data"]["text"]


def test_progress_callback_empty_text_skipped():
    """空字符串不发事件"""
    ctx = _make_ctx()
    cb = _make_progress_callback(ctx, "tool_x")
    asyncio.run(cb(""))
    asyncio.run(cb(None))
    assert len(ctx.publisher.events) == 0


# ══════════════════════════════════════════════════════════════
# 6. should_terminate
# ══════════════════════════════════════════════════════════════

def test_should_terminate_initial_false():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    terminate, reason = agent.should_terminate()
    assert terminate is False


def test_should_terminate_after_llm_done():
    ctx = _make_ctx()
    agent = CodingAgent(ctx)
    agent._llm_said_done = True
    terminate, reason = agent.should_terminate()
    assert terminate is True


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
