"""C1 — serve 进程 stdout/stderr 逐行流入 per-ws ring buffer（带递增 seq）。"""
from __future__ import annotations

import asyncio

import pytest

from app.coding import workspace as ws_mod


def _bare_manager():
    # 跳过 __init__（不在仓库里建 workspaces 目录）
    return ws_mod.WorkspaceManager.__new__(ws_mod.WorkspaceManager)


class _FakeStream:
    """模拟 asyncio.StreamReader：按预置行逐行 readline，读完返回 b''。"""
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if self._lines:
            return self._lines.pop(0)
        return b""


class _FakeProc:
    def __init__(self, stdout_lines, stderr_lines):
        self.stdout = _FakeStream(stdout_lines)
        self.stderr = _FakeStream(stderr_lines)
        self.returncode = None


async def test_log_reader_fills_ring_with_incrementing_seq_and_stream_tag():
    mgr = _bare_manager()
    ws_id = "w-log"
    # start_serve 会建 entry；这里直接放一个最小 entry，单测 reader
    mgr._serve_processes = {}
    proc = _FakeProc(
        stdout_lines=[b"App running at\n", b"  Local: http://localhost:8080/\n"],
        stderr_lines=[b"\x1b[33mwarning in ./src\x1b[39m\n"],  # 带 ANSI 颜色码
    )
    mgr._serve_processes[ws_id] = {
        "process": proc, "port": 8080, "kind": "web", "log_ring": [], "log_seq": 0,
    }

    mgr._spawn_serve_log_reader(ws_id, proc)
    # 让 reader task 把所有行抽干
    await asyncio.sleep(0.05)

    ring = mgr._serve_processes[ws_id]["log_ring"]
    seqs = [r["seq"] for r in ring]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # 严格递增唯一
    assert seqs[0] == 1  # seq 从 1 开始
    streams = {r["stream"] for r in ring}
    assert streams == {"stdout", "stderr"}
    # ANSI 被剥掉、换行被去掉
    err_line = next(r["line"] for r in ring if r["stream"] == "stderr")
    assert err_line == "warning in ./src"


async def test_ring_buffer_caps_at_max_keeping_latest():
    mgr = _bare_manager()
    ws_id = "w-cap"
    mgr._serve_processes = {}
    lines = [f"line-{i}\n".encode() for i in range(ws_mod.WorkspaceManager._SERVE_LOG_RING_MAX + 50)]
    proc = _FakeProc(stdout_lines=lines, stderr_lines=[])
    mgr._serve_processes[ws_id] = {
        "process": proc, "port": 1, "kind": "web", "log_ring": [], "log_seq": 0,
    }

    mgr._spawn_serve_log_reader(ws_id, proc)
    await asyncio.sleep(0.2)

    ring = mgr._serve_processes[ws_id]["log_ring"]
    assert len(ring) == ws_mod.WorkspaceManager._SERVE_LOG_RING_MAX
    # 末尾是最新的几行（seq 单调，最后一行 seq 最大）
    assert ring[-1]["line"].startswith("line-")
    assert ring[-1]["seq"] > ring[0]["seq"]
