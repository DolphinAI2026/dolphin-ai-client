"""运行时报错回流闭环(第 2 件，模式 B：呈现给用户+agent，agent 按需读取，不自动改)。

链路：预览 harness 注入 JS 采集 window 报错/console.error/网络失败 → postMessage 回宿主
→ 前端 POST /coding/workspace/{ws}/runtime-errors → WorkspaceManager 类级环形缓冲存储
→ agent 用 get_runtime_errors 工具按需读取（用户说「修一下」时）。

这里测后端三段：harness 采集脚本存在 / 存储读写+封顶 / agent 读取工具。
"""
from __future__ import annotations

import types

import pytest

import app.agents.coding.tools as tools_mod
from app.coding.workspace import WorkspaceManager, _PREVIEW_INDEX_HTML


def test_preview_harness_injects_runtime_capture_script():
    html = _PREVIEW_INDEX_HTML
    # 必须在页面里挂错误钩子并 postMessage 回宿主
    assert "addEventListener('error'" in html or "window.onerror" in html
    assert "unhandledrejection" in html
    assert "console.error" in html
    assert "postMessage" in html
    # 带唯一来源标识，宿主据此过滤
    assert "ruijing-preview" in html


def test_record_and_get_runtime_errors():
    wm = WorkspaceManager()
    wm.clear_runtime_errors("ws-rt-1")
    n = wm.record_runtime_errors("ws-rt-1", [
        {"type": "console.error", "message": "boom"},
        {"type": "network", "message": "GET /api 500"},
    ])
    assert n == 2
    got = wm.get_runtime_errors("ws-rt-1")
    assert len(got) == 2
    assert got[0]["message"] == "boom"
    assert "seq" in got[0]                      # 存储补了单调序号


def test_record_runtime_errors_ignores_non_dict_and_caps_ring():
    wm = WorkspaceManager()
    wm.clear_runtime_errors("ws-rt-2")
    # 混入坏数据不应炸
    wm.record_runtime_errors("ws-rt-2", [{"message": "ok"}, "garbage", None, 123])
    wm.record_runtime_errors("ws-rt-2", [{"message": f"e{i}"} for i in range(80)])
    got = wm.get_runtime_errors("ws-rt-2", limit=1000)
    assert len(got) <= 50                       # 环形缓冲封顶，不无限增长
    assert all(isinstance(e, dict) for e in got)


def test_get_runtime_errors_isolated_per_workspace():
    wm = WorkspaceManager()
    wm.clear_runtime_errors("ws-a")
    wm.clear_runtime_errors("ws-b")
    wm.record_runtime_errors("ws-a", [{"message": "a-err"}])
    assert wm.get_runtime_errors("ws-b") == []
    assert wm.get_runtime_errors("ws-a")[0]["message"] == "a-err"


@pytest.mark.asyncio
async def test_get_runtime_errors_tool_returns_captured():
    wm = WorkspaceManager()
    wm.clear_runtime_errors("ws-rt-3")
    wm.record_runtime_errors("ws-rt-3", [
        {"type": "console.error", "message": "TypeError: x is undefined"},
    ])
    ctx = types.SimpleNamespace(workspace_id="ws-rt-3")
    res = await tools_mod._get_runtime_errors({}, ctx)
    assert res.success
    assert "TypeError: x is undefined" in res.content


@pytest.mark.asyncio
async def test_get_runtime_errors_tool_when_empty():
    wm = WorkspaceManager()
    wm.clear_runtime_errors("ws-rt-4")
    ctx = types.SimpleNamespace(workspace_id="ws-rt-4")
    res = await tools_mod._get_runtime_errors({}, ctx)
    assert res.success
    # 没有捕获到报错时给明确空态，别让 agent 误以为出错
    assert "没有" in res.content or "无" in res.content


@pytest.mark.asyncio
async def test_get_runtime_errors_tool_no_workspace():
    ctx = types.SimpleNamespace(workspace_id=None)
    res = await tools_mod._get_runtime_errors({}, ctx)
    assert res.success is False


def test_get_runtime_errors_tool_registered():
    from app.agents.coding.tools import build_coding_tools
    names = {t.name for t in build_coding_tools()}
    assert "get_runtime_errors" in names
