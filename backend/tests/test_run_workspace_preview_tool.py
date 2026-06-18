"""对话化 run_workspace_preview 工具单测：不起真实进程/浏览器。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.agents.coding.tools as tmod
from app.agents.coding.tools import _run_workspace_preview


def _ctx(ws_id="ws1"):
    return SimpleNamespace(workspace_id=ws_id, publisher=None, db=None,
                           conversation_id=1, user_id=1, tenant_id=1, extra={})


class _WS:
    def __init__(self, serve):
        self._serve = serve
        self._serve_processes = {"ws1": {"log_ring": [
            {"seq": 1, "stream": "stdout", "line": "App running at http://127.0.0.1:8081/"},
        ]}}

    async def start_serve(self, ws_id, kind="web"):
        return self._serve


class _Browser:
    def __init__(self, console, network):
        self._c, self._n = console, network
        self.closed = []

    async def launch_capture(self, url, headless=True):
        return "cap-1"

    def get_console_logs(self, sid, after):
        return self._c

    def get_network_requests(self, sid, after):
        return self._n

    async def close_capture(self, sid):
        self.closed.append(sid)


@pytest.mark.asyncio
async def test_no_workspace_returns_error():
    res = await _run_workspace_preview({}, _ctx(ws_id=None))
    assert res.success is False
    assert res.content.startswith("Error:")


@pytest.mark.asyncio
async def test_serve_started_with_runtime_errors(monkeypatch):
    monkeypatch.setattr(tmod, "_get_workspace_manager", lambda: _WS({"status": "ok", "port": 8081, "message": ""}))
    browser = _Browser(
        console=[{"seq": 1, "level": "error", "text": "boom", "location": "edit.vue:10"}],
        network=[{"seq": 1, "url": "http://x/api", "status": 500, "method": "GET", "failed": False}],
    )
    monkeypatch.setattr(tmod, "_get_browser_service_for_preview", lambda: browser)

    res = await _run_workspace_preview({"kind": "web"}, _ctx())
    assert res.success is True
    ev = res.emit_event
    assert ev["type"] == "coding.run_result"
    d = ev["data"]
    assert d["source"] == "manual"
    assert d["dev_url"] == "http://127.0.0.1:8081/"
    assert d["status"] == "error"           # 有运行时报错
    assert d["capture_available"] is True
    assert any("boom" in e for e in d["errors"])
    assert any("500" in e for e in d["errors"])
    assert d["log_tail"] and "App running" in d["log_tail"][0]
    assert browser.closed == ["cap-1"]


@pytest.mark.asyncio
async def test_cdp_unavailable_degrades(monkeypatch):
    monkeypatch.setattr(tmod, "_get_workspace_manager", lambda: _WS({"status": "ok", "port": 8081, "message": ""}))

    def _boom():
        raise RuntimeError("playwright excluded")
    monkeypatch.setattr(tmod, "_get_browser_service_for_preview", _boom)

    res = await _run_workspace_preview({}, _ctx())
    assert res.success is True
    d = res.emit_event["data"]
    assert d["capture_available"] is False
    assert d["status"] == "ok"               # 无法抓运行时 → 不判 error
    assert d["dev_url"] == "http://127.0.0.1:8081/"


@pytest.mark.asyncio
async def test_serve_failed(monkeypatch):
    monkeypatch.setattr(tmod, "_get_workspace_manager", lambda: _WS({"status": "error", "message": "无 Node"}))
    res = await _run_workspace_preview({}, _ctx())
    assert res.success is False
    assert "无 Node" in res.content
    assert res.emit_event["data"]["status"] == "error"
