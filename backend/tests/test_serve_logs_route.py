"""C1 — GET /coding/workspace/{ws_id}/serve-logs SSE 路由：event=log, 心跳, last_seen_seq 补发。"""
from __future__ import annotations

import asyncio

import pytest

from app.routes import coding as coding_routes


async def test_serve_logs_route_emits_log_events_with_seq(monkeypatch):
    """直接驱动路由的 event_stream 生成器：断言 SSE 帧含 event: log + seq。"""

    async def _fake_iter(self, ws_id, after_seq):
        for ev in (
            {"seq": 5, "stream": "stdout", "line": "App running"},
            {"seq": 6, "stream": "stderr", "line": "warn x"},
        ):
            if ev["seq"] > after_seq:
                yield ev

    monkeypatch.setattr(
        coding_routes.WorkspaceManager, "iter_serve_logs", _fake_iter, raising=False
    )

    # _event_stream_response 包成 EventSourceResponse；取出底层 generator 逐帧检查
    captured = {}

    def _capture(generator, *, ping=None):
        captured["gen"] = generator
        captured["ping"] = ping
        return "SENTINEL"

    monkeypatch.setattr(coding_routes, "_event_stream_response", _capture)
    monkeypatch.setattr(coding_routes, "_ensure_workspace_access",
                        _async_noop)

    class _Ctx:
        pass

    resp = await coding_routes.serve_logs_stream(
        ws_id="w1", ctx=_Ctx(), last_seen_seq=4, heartbeat_seconds=15,
    )
    assert resp == "SENTINEL"
    assert captured["ping"] == 15

    frames = []
    async for frame in captured["gen"]:
        frames.append(frame)

    text = "".join(
        f if isinstance(f, str) else f.get("data", "") if isinstance(f, dict) else str(f)
        for f in frames
    )
    # sse_starlette dict 模式：event/data 在 dict 里
    events = [f for f in frames if isinstance(f, dict)]
    log_events = [f for f in events if f.get("event") == "log"]
    assert len(log_events) == 2
    assert '"seq": 5' in log_events[0]["data"] or '"seq":5' in log_events[0]["data"]
    assert '"seq": 6' in log_events[1]["data"] or '"seq":6' in log_events[1]["data"]


async def _async_noop(*args, **kwargs):
    return {}
