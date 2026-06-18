"""上下文爆炸修复测试（两件事）。

背景: 大应用生成期间, agent 反复轮询 get_application, 每次返回都带整篇 6 章节
spec_markdown(被截到 2 万字符), 6+ 次几乎一模一样堆进上下文 → 400 context_too_large。

任务 A: get_application 在应用「生成中」(status=generating/in_progress)时不再拉取/返回
        整篇 spec_markdown, 只给 status/generation_progress + 一条提示。其它状态保持原样。
任务 B: 统一 agent 循环 _run_agent_inner 每轮 LLM 调用前用 ContextCompactor.clean_tool_results
        压缩累积的老 tool 结果(保留最近 4 条完整, 更老压到 200 字, 不删消息/不破坏配对)。
"""
import inspect

import pytest


# ─────────────────────────── 任务 A ───────────────────────────

@pytest.mark.asyncio
async def test_get_application_omits_spec_while_generating(monkeypatch):
    """生成中: 不发起 spec-markdown 请求, spec_markdown 为空且 source 标记 omitted,
    generation_progress 仍在。"""
    from app import mcp_server as m

    calls = []

    async def fake_api_call(method, path, **kw):
        calls.append(path)
        if path == "/applications/8":
            return {"id": 8, "app_name": "x", "app_code": "x", "status": "generating", "apaas_app_id": "a"}
        if path.endswith("/spec-markdown"):
            # 生成中绝不应被调用; 若被调用返回一份"伪整篇文档"以便断言它没漏出去
            return {"markdown": "# 整篇设计文档" * 1000, "source": "doc_version", "version": 7}
        if path.endswith("/steps/status"):
            return {"app_status": "generating", "steps": [
                {"key": "create_model:0", "status": "completed"},
                {"key": "create_form:0", "status": "pending"},
            ]}
        return {}

    monkeypatch.setattr(m, "_api_call", fake_api_call)
    monkeypatch.setattr(m, "_resolve_identity", lambda t, u: (1, 1))
    monkeypatch.setattr(m, "_resolve_app_id", lambda a, u: (8, None))
    monkeypatch.setattr(m, "_build_app_view_url", lambda a: "url")

    res = await m.get_application(app_id=8)

    # 没有发起 spec-markdown 请求
    assert not any(p.endswith("/spec-markdown") for p in calls), calls
    # 整篇文档没有漏出
    assert res["spec_markdown"] == ""
    assert res["spec_markdown_source"] == "omitted_during_generation"
    assert res["spec_markdown_version"] is None
    # generation_progress 仍然在(轮询需要)
    assert res["generation_progress"] is not None
    assert res["generation_progress"]["app_status"] == "generating"
    # agent 能看到一条清晰提示(放进 hint 末尾即可)
    assert "completed" in res["generation_progress"]["hint"]


@pytest.mark.asyncio
async def test_get_application_omits_spec_while_in_progress(monkeypatch):
    """in_progress 同样视作生成中。"""
    from app import mcp_server as m

    calls = []

    async def fake_api_call(method, path, **kw):
        calls.append(path)
        if path == "/applications/8":
            return {"id": 8, "app_name": "x", "app_code": "x", "status": "in_progress", "apaas_app_id": "a"}
        if path.endswith("/spec-markdown"):
            return {"markdown": "# 文档", "source": "doc_version", "version": 3}
        if path.endswith("/steps/status"):
            return {"app_status": "in_progress", "steps": [{"key": "create_model:0", "status": "pending"}]}
        return {}

    monkeypatch.setattr(m, "_api_call", fake_api_call)
    monkeypatch.setattr(m, "_resolve_identity", lambda t, u: (1, 1))
    monkeypatch.setattr(m, "_resolve_app_id", lambda a, u: (8, None))
    monkeypatch.setattr(m, "_build_app_view_url", lambda a: "url")

    res = await m.get_application(app_id=8)
    assert not any(p.endswith("/spec-markdown") for p in calls)
    assert res["spec_markdown"] == ""
    assert res["spec_markdown_source"] == "omitted_during_generation"


@pytest.mark.asyncio
async def test_get_application_returns_full_spec_when_completed(monkeypatch):
    """completed: 照常拉取并返回整篇 spec_markdown(增量改字段仍需整篇文档)。"""
    from app import mcp_server as m

    calls = []
    full_md = "# 完整设计文档\n## 1. 应用信息\n...内容..."

    async def fake_api_call(method, path, **kw):
        calls.append(path)
        if path == "/applications/8":
            return {"id": 8, "app_name": "x", "app_code": "x", "status": "completed", "apaas_app_id": "a"}
        if path.endswith("/spec-markdown"):
            return {"markdown": full_md, "source": "doc_version", "version": 9}
        return {}

    monkeypatch.setattr(m, "_api_call", fake_api_call)
    monkeypatch.setattr(m, "_resolve_identity", lambda t, u: (1, 1))
    monkeypatch.setattr(m, "_resolve_app_id", lambda a, u: (8, None))
    monkeypatch.setattr(m, "_build_app_view_url", lambda a: "url")

    res = await m.get_application(app_id=8)
    # completed 必须真发起 spec-markdown 请求并返回整篇
    assert any(p.endswith("/spec-markdown") for p in calls), calls
    assert res["spec_markdown"] == full_md
    assert res["spec_markdown_source"] == "doc_version"
    assert res["spec_markdown_version"] == 9


@pytest.mark.asyncio
async def test_get_application_returns_full_spec_when_draft(monkeypatch):
    """draft(空白草稿)同样返回 spec(可能为空), 不被生成中分支拦截。"""
    from app import mcp_server as m

    calls = []

    async def fake_api_call(method, path, **kw):
        calls.append(path)
        if path == "/applications/8":
            return {"id": 8, "app_name": "x", "app_code": "x", "status": "draft"}
        if path.endswith("/spec-markdown"):
            return {"markdown": "", "source": "empty", "version": None}
        if path.endswith("/steps/status"):
            return {"app_status": "draft", "steps": []}
        return {}

    monkeypatch.setattr(m, "_api_call", fake_api_call)
    monkeypatch.setattr(m, "_resolve_identity", lambda t, u: (1, 1))
    monkeypatch.setattr(m, "_resolve_app_id", lambda a, u: (8, None))
    monkeypatch.setattr(m, "_build_app_view_url", lambda a: "url")

    res = await m.get_application(app_id=8)
    assert any(p.endswith("/spec-markdown") for p in calls), calls
    assert res["spec_markdown_source"] == "empty"


# ─────────────────────────── 任务 B ───────────────────────────

def test_clean_tool_results_keeps_recent_and_compresses_old():
    """clean_tool_results: 保留最近 keep_recent 条 tool 完整, 更老的压到 200 字,
    消息条数不变, tool_call_id 配对不变, 非 tool 消息不动。"""
    from app.context_compact import ContextCompactor

    long_old = "OLD" * 500   # 1500 字, 应被压缩
    long_recent = "NEW" * 500  # 1500 字, 应保留完整

    messages = [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "建个应用"},
        # 第 1 组: assistant.tool_calls + tool 配对(老, 应压缩)
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "type": "function"}]},
        {"role": "tool", "tool_call_id": "call_1", "content": long_old},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_2", "type": "function"}]},
        {"role": "tool", "tool_call_id": "call_2", "content": long_old},
        # 最近 4 条 tool(应保留完整)
        {"role": "tool", "tool_call_id": "call_3", "content": long_recent},
        {"role": "tool", "tool_call_id": "call_4", "content": long_recent},
        {"role": "tool", "tool_call_id": "call_5", "content": long_recent},
        {"role": "tool", "tool_call_id": "call_6", "content": long_recent},
    ]
    n_before = len(messages)

    result = ContextCompactor.clean_tool_results(messages, keep_recent=4)

    # 不删消息
    assert len(result) == n_before
    # 非 tool 消息不动
    assert result[0] == {"role": "system", "content": "你是助手"}
    assert result[1] == {"role": "user", "content": "建个应用"}
    assert result[2]["tool_calls"] == [{"id": "call_1", "type": "function"}]
    # 老 tool 被压缩到 ~200 字, tool_call_id 配对保留
    old1 = result[3]
    assert old1["role"] == "tool"
    assert old1["tool_call_id"] == "call_1"
    assert len(old1["content"]) < len(long_old)
    assert "已压缩" in old1["content"]
    old2 = result[5]
    assert old2["tool_call_id"] == "call_2"
    assert "已压缩" in old2["content"]
    # 最近 4 条 tool 完整保留
    for idx, cid in [(6, "call_3"), (7, "call_4"), (8, "call_5"), (9, "call_6")]:
        assert result[idx]["tool_call_id"] == cid
        assert result[idx]["content"] == long_recent

    # tool_call_id 集合不变(配对未被破坏)
    ids_before = [m["tool_call_id"] for m in messages if m.get("role") == "tool"]
    ids_after = [m["tool_call_id"] for m in result if m.get("role") == "tool"]
    assert ids_before == ids_after


def test_clean_tool_results_noop_when_few_tools():
    """tool 数 <= keep_recent 时原样返回。"""
    from app.context_compact import ContextCompactor

    messages = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "call_1", "content": "x" * 1000},
    ]
    result = ContextCompactor.clean_tool_results(messages, keep_recent=4)
    assert result == messages


def test_unified_agent_loop_calls_clean_tool_results():
    """断言压缩这步确实被接进了统一 agent 主循环 _run_agent_inner。

    直接跑整个 async 生成器不现实(要 LLM/DB), 所以核验源码: _run_agent_inner 内
    确实在主循环里调用了 ContextCompactor.clean_tool_results(messages, keep_recent=4)。
    """
    from app.ai_chat import agent as agent_mod

    src = inspect.getsource(agent_mod._run_agent_inner)
    assert "clean_tool_results" in src, "统一循环未接入 clean_tool_results"
    assert "keep_recent=4" in src
    # 必须在主循环内(for turn ... 之后)调用, 而不是循环外只调一次
    loop_pos = src.index("for turn in range(MAX_TURNS):")
    compact_pos = src.index("clean_tool_results")
    assert compact_pos > loop_pos, "clean_tool_results 应在主循环内每轮调用"
