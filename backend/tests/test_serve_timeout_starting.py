"""档2: start_serve 端口在上限内仍没就绪时，返回 status="starting"(而非误报 ok)。

旧行为(2026-06-18 起): 30s 仍没起好也返回 status="ok" + dev_url → 前端 iframe 立刻指向
尚未就绪的地址 → 白屏。现在超时返回 starting，前端据此提示「正在启动」+ 自动重试加载。
"""
from __future__ import annotations

import socket as socket_mod

import pytest

import app.coding.workspace as wsmod
from app.coding.workspace import WorkspaceManager


class _FakeSock:
    """connect_ex 永远非 0 = 端口空闲(选端口用) / 未就绪(等待用)。"""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def connect_ex(self, addr):
        return 1


class _FakeProc:
    returncode = None  # 进程一直活着(没崩) → 不会走 error 分支


@pytest.mark.asyncio
async def test_start_serve_timeout_returns_starting(monkeypatch, tmp_path):
    mgr = WorkspaceManager.__new__(WorkspaceManager)  # 跳过 __init__ 的文件系统副作用
    ws_id = "ws-timeout-starting-test"
    WorkspaceManager._serve_processes.pop(ws_id, None)

    monkeypatch.setattr(mgr, "get_workspace_path", lambda w: tmp_path)
    monkeypatch.setattr(mgr, "_read_meta", lambda p: {})
    monkeypatch.setattr(mgr, "_project_requires_npm_install", lambda t: False)
    monkeypatch.setattr(mgr, "_build_npm_env", lambda: {})
    monkeypatch.setattr(mgr, "_spawn_serve_log_reader", lambda w, p: None)
    monkeypatch.setattr(WorkspaceManager, "_SERVE_READY_WAIT_SEC", 0.05)

    async def _fake_exec(*a, **k):
        return _FakeProc()

    async def _fast_sleep(_):
        return None

    monkeypatch.setattr(wsmod.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(wsmod.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: _FakeSock())

    try:
        res = await mgr.start_serve(ws_id)
        assert res["status"] == "starting"
        assert res.get("port")
        # starting 也带 url(前端按钮据此渲染 iframe + 自动重试)，不再是空头支票
        assert res.get("url") == f"http://127.0.0.1:{res['port']}/"
    finally:
        WorkspaceManager._serve_processes.pop(ws_id, None)


@pytest.mark.asyncio
async def test_serve_status_running_returns_url(monkeypatch):
    """serve-status 在运行中也返回 url(而非只 port)，修好 startServe/getServeStatus 的 url? 空头支票。"""
    mgr = WorkspaceManager.__new__(WorkspaceManager)
    ws_id = "ws-status-url-test"

    class _AliveProc:
        returncode = None

    WorkspaceManager._serve_processes[ws_id] = {"process": _AliveProc(), "port": 8137, "kind": "web"}
    try:
        res = mgr.is_serve_running(ws_id)
        assert res["running"] is True
        assert res["url"] == "http://127.0.0.1:8137/"
    finally:
        WorkspaceManager._serve_processes.pop(ws_id, None)
