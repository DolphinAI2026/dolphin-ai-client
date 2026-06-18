# 桌面端「运行/调试」闭环底座（SP1）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在桌面端 app 内为二次开发页面/组件做出可用的运行/调试闭环（起服务→实时日志→HMR 预览→console/network→devtools），并让 AI 改完代码能「看到」运行时报错自愈重试；底座给 SP2 小程序复用。

**Architecture:** 后端 sidecar 扩 `start_serve` 把进程输出逐行流入 per-ws 环形缓冲并经 SSE 推出（C1）；扩 `BrowserService` 用 Playwright 自带 Chromium 加载 dev server URL 抓 console/network（C2）；前端预览在 serve 运行时直连带 shim 的 dev server（HMR）而非 UMD 包（C3）；CodingPage 右栏加「运行/调试」tab 消费上述能力（C4）；外层 `drive_coding_with_autofix` 把运行时报错回灌 agent 循环（C5）。

**Tech Stack:** Tauri v2 + Python sidecar（FastAPI/uvicorn）；后端 Python 3.13 / asyncio / Playwright / sse_starlette；前端 Vue 3 + TypeScript + EventSource。

## Global Constraints

- 后端 `reload=False`：改后端代码必须重启 sidecar/backend 进程才生效（pytest 导入是 fresh app，不受影响；live/preview 验证需重启）。
- 本地 DB = SQLite；`.venv` = Python 3.13；后端测试从 `backend/` 跑：`.venv/bin/python -m pytest`（或 `python -m pytest`）。
- 不破坏现有 `start_serve`/`stop_serve` 与 deploy/preview 路径；`start_serve(ws_id, kind="web")` 新增 `kind` 参数向后兼容。
- CDP 抓取用 Playwright 自带 Chromium，不依赖私有 `@x-apaas` 源。
- 预览呈现：嵌入 iframe（人看，在 app 内）+ 独立 CDP Chromium（抓 console/network + devtools），两者同一 dev server URL（双面同源）。
- node/npm 找不到时明确报人话错误，不静默失败（SP3 内置 node 的前置）。
- shim 注入默认走 dev 工作区模板 index.html；若 HMR 被破坏再退「薄 proxy 注入」。
- 频繁提交：每个 Task 末尾 commit；commit message 末尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。
- 任务按全局编号 1–14 顺序执行；下方按组件 C1–C5 分组，组内 Task 号即全局号。

---


## C1 · 运行会话编排 + 流式日志（Task 1–3）

### Task 1: Stream serve stdout/stderr into a per-workspace ring buffer with incrementing seq

**Files:**
- Modify: `backend/app/coding/workspace.py:1753-1808` (the `_serve_processes` declaration + `start_serve`)
- Test: `backend/tests/test_serve_log_streaming.py` (Create)

**Interfaces:**
- Consumes: `WorkspaceManager._serve_processes` (existing class dict `{ws_id: {"process": Process, "port": int}}`), `WorkspaceManager.start_serve(ws_id)` (existing), `asyncio.create_subprocess_exec`, `self._build_npm_env()`, `self._strip_ansi`-equivalent (uses a new local helper since `_strip_ansi` lives in `tools.py`).
- Produces: `WorkspaceManager.start_serve(ws_id: str, kind: str = "web") -> dict {status, port, message}` (extended with `kind`); per-ws ring-buffer state stored under `_serve_processes[ws_id]` as keys `log_ring: list[dict {seq, stream, line}]`, `log_seq: int`, `kind: str`, plus a class-level `_SERVE_LOG_RING_MAX = 2000`; a private method `WorkspaceManager._spawn_serve_log_reader(ws_id, proc)` that later tasks (`iter_serve_logs`) rely on to populate the ring.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_serve_log_streaming.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Command: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && python -m pytest tests/test_serve_log_streaming.py -x -q`
Expected: failure with `AttributeError: type object 'WorkspaceManager' has no attribute '_SERVE_LOG_RING_MAX'` (and `_spawn_serve_log_reader` not found). Collection succeeds; both tests error out.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/coding/workspace.py`, replace the class-attr block at lines 1753-1756:

```python
    # ======== Serve & Debug 进程管理 ========
    _serve_processes: dict = {}   # {ws_id: {"process": Process, "port": int, "kind": str, "log_ring": list, "log_seq": int}}
    _debug_processes: dict = {}   # {ws_id: {"process": Process}}
    _next_port: int = 8080
    _SERVE_LOG_RING_MAX: int = 2000   # 环形缓冲上限（行）

    @staticmethod
    def _strip_serve_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)

    def _append_serve_log(self, ws_id: str, stream: str, line: str) -> None:
        info = self._serve_processes.get(ws_id)
        if not info:
            return
        info["log_seq"] = int(info.get("log_seq", 0)) + 1
        ring = info.setdefault("log_ring", [])
        ring.append({"seq": info["log_seq"], "stream": stream, "line": line})
        if len(ring) > self._SERVE_LOG_RING_MAX:
            del ring[: len(ring) - self._SERVE_LOG_RING_MAX]

    def _spawn_serve_log_reader(self, ws_id: str, proc) -> None:
        """异步逐行读 proc 的 stdout/stderr，写入该 ws 的 log_ring。"""
        async def _read(stream_reader, stream_name: str) -> None:
            if stream_reader is None:
                return
            while True:
                try:
                    raw = await stream_reader.readline()
                except Exception:
                    break
                if not raw:
                    break
                line = self._strip_serve_ansi(
                    raw.decode("utf-8", errors="replace")
                ).rstrip("\n")
                self._append_serve_log(ws_id, stream_name, line)

        asyncio.ensure_future(_read(getattr(proc, "stdout", None), "stdout"))
        asyncio.ensure_future(_read(getattr(proc, "stderr", None), "stderr"))
```

Then update `start_serve` — change the signature (line 1758) and seed the ring + start the reader where the process entry is stored (line 1793). Signature:

```python
    async def start_serve(self, ws_id: str, kind: str = "web") -> dict:
```

Replace line 1793 (`self._serve_processes[ws_id] = {"process": proc, "port": port}`) with:

```python
        self._serve_processes[ws_id] = {
            "process": proc, "port": port, "kind": kind,
            "log_ring": [], "log_seq": 0,
        }
        self._spawn_serve_log_reader(ws_id, proc)
```

Note: keep the `proc.communicate()` call inside the 30s startup wait loop (line 1804) UNCHANGED for now — it only runs on the early-exit failure branch; Task 3 handles the conflict. The reader handles the normal long-running path.

- [ ] **Step 4: Run test to verify it passes**

Command: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && python -m pytest tests/test_serve_log_streaming.py -x -q`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder/backend"
git add app/coding/workspace.py tests/test_serve_log_streaming.py
git commit -m "feat(coding): stream serve stdout/stderr into per-ws ring buffer with seq

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Add `iter_serve_logs` async iterator and tighten the startup failure path

**Files:**
- Modify: `backend/app/coding/workspace.py:1786-1808` (`start_serve` failure branch) and add `iter_serve_logs` after `is_serve_running` (after line 1867)
- Test: `backend/tests/test_serve_log_streaming.py` (Modify — append tests)

**Interfaces:**
- Consumes: `WorkspaceManager._serve_processes[ws_id]` ring state (`log_ring`, keys `seq`/`stream`/`line`) and `_append_serve_log` from Task 1; `info["process"].returncode` for liveness.
- Produces: `WorkspaceManager.iter_serve_logs(ws_id: str, after_seq: int) -> AsyncIterator[dict {seq:int, stream:str, line:str}]` (the FIXED contract name) — backfills ring rows with `seq > after_seq` then polls for new rows until the process exits and the ring is drained.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_serve_log_streaming.py`:

```python
async def test_iter_serve_logs_backfills_after_seq_then_streams_new():
    mgr = _bare_manager()
    ws_id = "w-iter"
    mgr._serve_processes = {}

    class _DoneProc:
        returncode = None  # 先存活，便于流式；测试中手动停

    proc = _DoneProc()
    mgr._serve_processes[ws_id] = {
        "process": proc, "port": 1, "kind": "web", "log_ring": [], "log_seq": 0,
    }
    # 预置 3 行历史
    for s, ln in (("stdout", "a"), ("stdout", "b"), ("stderr", "c")):
        mgr._append_serve_log(ws_id, s, ln)

    collected: list[dict] = []

    async def _consume():
        async for ev in mgr.iter_serve_logs(ws_id, after_seq=1):
            collected.append(ev)
            if len(collected) >= 4:
                break

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.05)
    # 再追加一行新的
    mgr._append_serve_log(ws_id, "stdout", "d")
    await asyncio.wait_for(task, timeout=2)

    # after_seq=1 → 跳过 seq 1，补发 seq 2,3，再实时收到 seq 4
    assert [e["seq"] for e in collected] == [2, 3, 4]
    assert collected[-1] == {"seq": 4, "stream": "stdout", "line": "d"}


async def test_iter_serve_logs_unknown_ws_yields_nothing():
    mgr = _bare_manager()
    mgr._serve_processes = {}
    got = [ev async for ev in mgr.iter_serve_logs("nope", after_seq=0)]
    assert got == []
```

- [ ] **Step 2: Run test to verify it fails**

Command: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && python -m pytest tests/test_serve_log_streaming.py -q -k iter_serve_logs`
Expected: failure `AttributeError: 'WorkspaceManager' object has no attribute 'iter_serve_logs'`.

- [ ] **Step 3: Write minimal implementation**

First fix the failure branch so the early-exit `communicate()` (line 1804) doesn't fight the reader: the reader already owns `proc.stdout`/`proc.stderr`, so calling `communicate()` again would raise. Replace lines 1803-1806:

```python
            if proc.returncode is not None:
                tail = [r["line"] for r in self._serve_processes.get(ws_id, {}).get("log_ring", [])][-10:]
                return {"status": "error", "port": port,
                        "message": "serve 启动失败: " + ("\n".join(tail) or "进程已退出")[:300]}
```

Then add `iter_serve_logs` immediately after `is_serve_running` (after line 1867):

```python
    async def iter_serve_logs(self, ws_id: str, after_seq: int):
        """逐条产出该 ws 的 serve 日志行：先补发 seq > after_seq 的历史，再实时跟随。

        每条：{"seq": int, "stream": "stdout"|"stderr", "line": str}
        进程退出且 ring 全部发完后结束迭代。
        """
        if ws_id not in self._serve_processes:
            return
        cursor = int(after_seq or 0)
        idle_after_exit = 0
        while True:
            info = self._serve_processes.get(ws_id)
            if info is None:
                return
            ring = info.get("log_ring", [])
            new_rows = [r for r in ring if r["seq"] > cursor]
            if new_rows:
                for row in new_rows:
                    cursor = row["seq"]
                    yield {"seq": row["seq"], "stream": row["stream"], "line": row["line"]}
                idle_after_exit = 0
                continue
            proc = info.get("process")
            exited = proc is None or getattr(proc, "returncode", None) is not None
            if exited:
                idle_after_exit += 1
                if idle_after_exit >= 2:  # 退出后再确认一轮无新行
                    return
            await asyncio.sleep(0.5)
```

- [ ] **Step 4: Run test to verify it passes**

Command: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && python -m pytest tests/test_serve_log_streaming.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder/backend"
git add app/coding/workspace.py tests/test_serve_log_streaming.py
git commit -m "feat(coding): add iter_serve_logs backfill+follow iterator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Add GET /serve-logs SSE route (heartbeat + last_seen_seq backfill) and thread `kind` through the serve endpoint

**Files:**
- Modify: `backend/app/routes/coding.py:1434-1462` (add SSE route after `get_serve_status`; pass `kind` into `start_serve` from `manage_serve`)
- Modify: `backend/app/routes/coding.py:14-34` (add `auth_from_header_or_query` + `AsyncSessionLocal` imports)
- Test: `backend/tests/test_serve_logs_route.py` (Create)

**Interfaces:**
- Consumes: `WorkspaceManager.iter_serve_logs(ws_id, after_seq)` (Task 2), `_event_stream_response(generator, *, ping=...)` (existing, `coding.py:103`), `auth_from_header_or_query` (`app.deps:303` — EventSource can't send headers, so query-token auth like `sse.py:79`), `_ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")` (existing), `AsyncSessionLocal` (`app.database`).
- Produces: Route `GET /coding/workspace/{ws_id}/serve-logs?last_seen_seq=N` → SSE, event name `"log"`, data `{seq, stream, line}`, with heartbeat; and `POST /coding/workspace/{ws_id}/serve?action=start&kind=web` now forwarding `kind` to `start_serve`. (Router prefix is `/coding`, confirmed by sibling routes; the full path is `/coding/workspace/{ws_id}/serve-logs`.)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_serve_logs_route.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Command: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && python -m pytest tests/test_serve_logs_route.py -x -q`
Expected: failure `AttributeError: module 'app.routes.coding' has no attribute 'serve_logs_stream'`.

- [ ] **Step 3: Write minimal implementation**

Add imports. Change `coding.py:25` (`from app.database import get_db`) to:

```python
from app.database import get_db, AsyncSessionLocal
```

Change `coding.py:27` (`from app.deps import get_auth_context, AuthContext`) to:

```python
from app.deps import get_auth_context, AuthContext, auth_from_header_or_query
```

Pass `kind` through `manage_serve`. Replace lines 1439-1445:

```python
    action: str = Query(default="start", description="start 或 stop"),
    kind: str = Query(default="web", description="serve 类型：web/mobile/h5"),
):
    """启动或停止工作区的 serve 进程"""
    await _ensure_workspace_access(ws_id, ctx, db, minimum_project_role="member")
    ws_mgr = WorkspaceManager()
    if action == "start":
        result = await ws_mgr.start_serve(ws_id, kind=kind)
```

Add the SSE route immediately after `get_serve_status` (after line 1462). EventSource can't send the `Authorization` header, so auth comes from `?token=` via `auth_from_header_or_query` (same as `sse.py`); the long-lived connection uses its own `AsyncSessionLocal` rather than the request-scoped `get_db`:

```python
@router.get("/workspace/{ws_id}/serve-logs")
async def serve_logs_stream(
    ws_id: str,
    ctx: Annotated[AuthContext, Depends(auth_from_header_or_query)],
    last_seen_seq: int = Query(0, ge=0, description="上次收到的 seq；断线重连补发 > N 的历史"),
    heartbeat_seconds: int = Query(15, ge=5, le=120, description="心跳间隔（秒）"),
):
    """订阅 serve 进程的实时日志（SSE）。

    event 名 "log"，data = {seq, stream, line}；先补发 seq > last_seen_seq 的历史再实时跟随。
    EventSource 无法带 header → 走 ?token= 鉴权（auth_from_header_or_query）。
    """
    async with AsyncSessionLocal() as check_db:
        await _ensure_workspace_access(ws_id, ctx, check_db, minimum_project_role="member")

    ws_mgr = WorkspaceManager()

    async def event_stream() -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=512)

        async def _pump_logs():
            try:
                async for ev in ws_mgr.iter_serve_logs(ws_id, last_seen_seq):
                    await queue.put(("log", ev))
            except Exception as e:
                logger.warning("serve-logs pump err: %s", e)
            finally:
                await queue.put(None)

        async def _pump_heartbeat():
            while True:
                await asyncio.sleep(heartbeat_seconds)
                await queue.put(("heartbeat", {"seq": 0}))

        pump_task = asyncio.create_task(_pump_logs())
        hb_task = asyncio.create_task(_pump_heartbeat())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event_name, payload = item
                yield {
                    "event": event_name,
                    "id": str(payload.get("seq", 0)),
                    "data": json.dumps(payload, ensure_ascii=False),
                }
        finally:
            pump_task.cancel()
            hb_task.cancel()
            for t in (pump_task, hb_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

    return _event_stream_response(event_stream(), ping=heartbeat_seconds)
```

Note: `logger` already exists in this module. `_event_stream_response` returns `EventSourceResponse`, which consumes dicts with `event`/`id`/`data` keys (sse_starlette wire format) — that is why the test asserts on dict frames.

- [ ] **Step 4: Run test to verify it passes**

Command: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && python -m pytest tests/test_serve_logs_route.py tests/test_serve_log_streaming.py -q`
Expected: `5 passed` (the 4 from Tasks 1-2 plus this route test). Then confirm no import regressions: `python -c "import app.routes.coding; import app.coding.workspace; print('ok')"` prints `ok`.

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder/backend"
git add app/routes/coding.py tests/test_serve_logs_route.py
git commit -m "feat(coding): add GET serve-logs SSE route with heartbeat + last_seen_seq backfill

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

> **Manual restart note (applies to all three tasks):** the backend/sidecar runs with `reload=False` (`backend/run.py`). After landing each backend change, restart the preview backend / `ruijing-sidecar` process before exercising the route from the UI or `curl` — pytest runs in-process and does not need a restart, but a live `curl "http://127.0.0.1:<port>/coding/workspace/<ws>/serve-logs?token=<jwt>&last_seen_seq=0"` will keep serving the old code until the process is restarted. None of these changes alter the existing `start_serve`/`stop_serve` return contract, the dual-端 (`web`/`mobile`) entry shape consumed by `is_serve_running`/`stop_serve`, or the deploy/preview paths.

Relevant files (absolute):
- `/Users/mars/Vibe Coding/ai-builder/backend/app/coding/workspace.py`
- `/Users/mars/Vibe Coding/ai-builder/backend/app/routes/coding.py`
- `/Users/mars/Vibe Coding/ai-builder/backend/tests/test_serve_log_streaming.py` (new)
- `/Users/mars/Vibe Coding/ai-builder/backend/tests/test_serve_logs_route.py` (new)


## C2 · CDP 抓取引擎（Task 4–5）

### Task 4: BrowserService CDP capture — console/network ring buffers + lifecycle

**Files:**
- Modify: `backend/app/coding/browser_service.py` (add `RING_LIMIT` const near line 26; extend `BrowserSession.__init__` ~line 31-36 and add capture listener/getter methods after `close` ~line 162; add `BrowserService.launch_capture`/`get_console_logs`/`get_network_requests`/`open_devtools`/`close_capture` after `list_sessions` ~line 299)
- Test: `backend/tests/test_browser_capture.py`

**Interfaces:**
- Consumes: existing `BrowserService.get_instance()`, `BrowserService.start()` (lazy playwright launch ~line 181), `self._browser.new_context(...)` pattern (~line 251), `self._sessions` dict, `BrowserSession(ws_id, context, page)`.
- Produces (FIXED contract, verbatim):
  - `BrowserService.launch_capture(url: str, headless: bool = True) -> str` (returns `session_id`)
  - `BrowserService.get_console_logs(session_id: str, after_seq: int) -> list[dict]` items `{seq:int, level:str, text:str, location:str}`
  - `BrowserService.get_network_requests(session_id: str, after_seq: int) -> list[dict]` items `{seq:int, url:str, status:int, method:str, failed:bool}` (only status>=400 or failed)
  - `BrowserService.open_devtools(session_id: str) -> None`
  - `BrowserService.close_capture(session_id: str) -> None`
  - `BrowserSession.attach_capture()`, `BrowserSession.url` (capture session id stored under `self._sessions` keyed by `session_id`)

- [ ] **Step 1: Write the failing test** — capture ring-buffer logic is unit-tested against a fake Page (no real Chromium needed) by exercising the listener callbacks directly.

```python
# backend/tests/test_browser_capture.py
"""C2 CDP 抓取引擎 — console/network ring buffer + getters (after_seq 增量)。

不启动真实 Chromium：用 FakePage 捕获 page.on(...) 注册的回调，再手动 fire
console/response/requestfailed 事件，验证 ring buffer 落库 + seq 递增 + after_seq 增量。
"""
import pytest

from app.coding.browser_service import BrowserService, BrowserSession


class FakeError:
    def __init__(self, message):
        self.message = message


class FakeRequest:
    def __init__(self, method):
        self.method = method
        self.failure = None


class FakeResponse:
    def __init__(self, url, status, method):
        self.url = url
        self.status = status
        self.request = FakeRequest(method)


class FakeFailedRequest:
    def __init__(self, url, method, failure_text):
        self.url = url
        self.method = method
        self.failure = failure_text


class FakeConsoleMessage:
    def __init__(self, type_, text, location):
        self.type = type_
        self.text = text
        self.location = location


class FakePage:
    """记录 page.on(event, cb) 注册，提供 fire() 手动触发。"""
    def __init__(self):
        self.url = "http://127.0.0.1:5174/"
        self._handlers = {}

    def on(self, event, cb):
        self._handlers[event] = cb

    def fire(self, event, payload):
        self._handlers[event](payload)


def _make_session():
    page = FakePage()
    sess = BrowserSession("cap-1", context=None, page=page)
    sess.attach_capture()
    return sess, page


def test_console_ring_buffer_records_seq_and_increment():
    sess, page = _make_session()
    page.fire("console", FakeConsoleMessage(
        "error", "boom is not a function",
        {"url": "http://127.0.0.1:5174/app.js", "lineNumber": 12, "columnNumber": 3},
    ))
    page.fire("console", FakeConsoleMessage("log", "hello", {}))

    logs = sess.read_console(0)
    assert [l["seq"] for l in logs] == [1, 2]
    assert logs[0]["level"] == "error"
    assert logs[0]["text"] == "boom is not a function"
    assert "app.js" in logs[0]["location"]
    # 增量：after_seq=1 只拿第 2 条
    assert [l["seq"] for l in sess.read_console(1)] == [2]


def test_network_only_records_errors_and_failures():
    sess, page = _make_session()
    page.fire("response", FakeResponse("http://x/ok", 200, "GET"))      # 忽略
    page.fire("response", FakeResponse("http://x/boom", 500, "POST"))   # 记录
    page.fire("requestfailed", FakeFailedRequest("http://x/dead", "GET", "net::ERR"))  # 记录

    net = sess.read_network(0)
    assert [n["seq"] for n in net] == [1, 2]
    assert net[0] == {"seq": 1, "url": "http://x/boom", "status": 500, "method": "POST", "failed": False}
    assert net[1]["failed"] is True
    assert net[1]["status"] == 0
    assert [n["seq"] for n in sess.read_network(1)] == [2]


def test_ring_buffer_caps_at_limit():
    from app.coding.browser_service import RING_LIMIT
    sess, page = _make_session()
    for i in range(RING_LIMIT + 10):
        page.fire("console", FakeConsoleMessage("log", f"m{i}", {}))
    logs = sess.read_console(0)
    assert len(logs) == RING_LIMIT
    # seq 仍单调递增，最后一条 seq == 总数
    assert logs[-1]["seq"] == RING_LIMIT + 10


def test_service_getters_delegate_to_session(monkeypatch):
    svc = BrowserService()
    sess, page = _make_session()
    svc._sessions["cap-1"] = sess
    page.fire("console", FakeConsoleMessage("warning", "w", {}))
    assert svc.get_console_logs("cap-1", 0)[0]["level"] == "warning"
    assert svc.get_console_logs("missing", 0) == []
    assert svc.get_network_requests("missing", 0) == []
```

- [ ] **Step 2: Run test to verify it fails**

```
cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_browser_capture.py -q
```
Expected: collection/attribute errors — `AttributeError: 'BrowserSession' object has no attribute 'attach_capture'` (and `read_console`/`read_network`), plus `ImportError: cannot import name 'RING_LIMIT'`. All 4 tests fail/error.

- [ ] **Step 3: Write minimal implementation** — add the `RING_LIMIT` constant and the capture buffers/methods on `BrowserSession`, then the service-level capture lifecycle methods. Faithful to the existing `__init__` signature and `new_context` pattern already in the file.

Add constant after `JPEG_QUALITY = 60` (line 25):

```python
JPEG_QUALITY = 60
RING_LIMIT = 2000  # console/network 环形缓冲上限（每会话每类）
```

Extend `BrowserSession.__init__` (currently lines 31-36) to seed capture state:

```python
    def __init__(self, ws_id: str, context: "BrowserContext", page: "Page"):
        self.ws_id = ws_id
        self.context = context
        self.page = page
        self.last_active = time.time()
        self.created_at = time.time()
        # C2 抓取状态（capture 会话才用；普通截图会话不调 attach_capture）
        self.capture_url: str = ""
        self.capture_headless: bool = True
        self._console: list[dict] = []
        self._network: list[dict] = []
        self._console_seq: int = 0
        self._network_seq: int = 0
```

Insert capture methods on `BrowserSession` immediately before `async def close` (currently line 156):

```python
    def attach_capture(self) -> None:
        """挂载 console/network/pageerror 监听，写入环形缓冲。"""
        self.page.on("console", self._on_console)
        self.page.on("pageerror", self._on_pageerror)
        self.page.on("response", self._on_response)
        self.page.on("requestfailed", self._on_requestfailed)

    def _push_console(self, level: str, text: str, location: str) -> None:
        self._console_seq += 1
        self._console.append({
            "seq": self._console_seq, "level": level,
            "text": text, "location": location,
        })
        if len(self._console) > RING_LIMIT:
            del self._console[: len(self._console) - RING_LIMIT]

    def _push_network(self, url: str, status: int, method: str, failed: bool) -> None:
        # 只记 status>=400 或失败，避免噪音
        if not failed and status < 400:
            return
        self._network_seq += 1
        self._network.append({
            "seq": self._network_seq, "url": url,
            "status": status, "method": method, "failed": failed,
        })
        if len(self._network) > RING_LIMIT:
            del self._network[: len(self._network) - RING_LIMIT]

    def _fmt_location(self, loc) -> str:
        if not loc:
            return ""
        if isinstance(loc, dict):
            url = loc.get("url", "")
            line = loc.get("lineNumber")
            col = loc.get("columnNumber")
            if line is not None:
                return f"{url}:{line}:{col}" if col is not None else f"{url}:{line}"
            return url
        return str(loc)

    def _on_console(self, msg) -> None:
        try:
            self._push_console(msg.type, msg.text, self._fmt_location(msg.location))
        except Exception as e:
            logger.warning(f"console capture error: {e}")

    def _on_pageerror(self, err) -> None:
        try:
            self._push_console("error", getattr(err, "message", str(err)), "pageerror")
        except Exception as e:
            logger.warning(f"pageerror capture error: {e}")

    def _on_response(self, resp) -> None:
        try:
            self._push_network(resp.url, resp.status, resp.request.method, False)
        except Exception as e:
            logger.warning(f"response capture error: {e}")

    def _on_requestfailed(self, req) -> None:
        try:
            self._push_network(req.url, 0, req.method, True)
        except Exception as e:
            logger.warning(f"requestfailed capture error: {e}")

    def read_console(self, after_seq: int) -> list[dict]:
        return [r for r in self._console if r["seq"] > after_seq]

    def read_network(self, after_seq: int) -> list[dict]:
        return [r for r in self._network if r["seq"] > after_seq]

```

Insert service-level capture lifecycle after `list_sessions` (currently ends line 299). Note: capture sessions are keyed by a generated `session_id` in the same `self._sessions` dict, so the existing idle-cleanup loop, `MAX_SESSIONS`, and `stop()` already cover them.

```python
    async def launch_capture(self, url: str, headless: bool = True) -> str:
        """启动一个 CDP 抓取会话，加载 url 并挂监听，返回 session_id。"""
        import uuid
        if not self._browser:
            await self.start()
        if len(self._sessions) >= MAX_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda s: s.last_active)
            logger.info(f"Max sessions reached, closing oldest: {oldest.ws_id}")
            await self.close_session(oldest.ws_id)

        session_id = f"cap-{uuid.uuid4().hex[:12]}"
        context = await self._browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            ignore_https_errors=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = await context.new_page()
        session = BrowserSession(session_id, context, page)
        session.capture_url = url
        session.capture_headless = headless
        session.attach_capture()
        self._sessions[session_id] = session
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning(f"capture goto error ({url}): {e}")
        return session_id

    def get_console_logs(self, session_id: str, after_seq: int) -> list[dict]:
        session = self._sessions.get(session_id)
        if not session:
            return []
        session.touch()
        return session.read_console(after_seq)

    def get_network_requests(self, session_id: str, after_seq: int) -> list[dict]:
        session = self._sessions.get(session_id)
        if not session:
            return []
        session.touch()
        return session.read_network(after_seq)

    async def open_devtools(self, session_id: str) -> None:
        """以非 headless + 自动开 DevTools 重启该 capture 会话（同 URL，独立窗口）。"""
        session = self._sessions.get(session_id)
        if not session:
            return
        url = session.capture_url
        await self.close_session(session_id)
        from playwright.async_api import async_playwright  # 惰性 import
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        browser = await self._playwright.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--ignore-certificate-errors",
                "--auto-open-devtools-for-tabs",
            ],
        )
        context = await browser.new_context(ignore_https_errors=True, locale="zh-CN")
        page = await context.new_page()
        devtools_session = BrowserSession(session_id, context, page)
        devtools_session.capture_url = url
        devtools_session.capture_headless = False
        devtools_session.attach_capture()
        self._sessions[session_id] = devtools_session
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning(f"devtools goto error ({url}): {e}")

    async def close_capture(self, session_id: str) -> None:
        await self.close_session(session_id)
```

- [ ] **Step 4: Run test to verify it passes**

```
cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_browser_capture.py tests/test_browser_service_import.py -q
```
Expected: `5 passed` (4 new + the existing import test still green, confirming top-level import stays playwright-free).

- [ ] **Step 5: Commit**

```
cd "/Users/mars/Vibe Coding/ai-builder/backend" && git add app/coding/browser_service.py tests/test_browser_capture.py && git commit -m "feat(coding): CDP 抓取引擎 — BrowserService.launch_capture + console/network 环形缓冲

新增 launch_capture/get_console_logs/get_network_requests/open_devtools/close_capture，
console/pageerror 与 status>=400/失败的 network 落环形缓冲（seq 递增、after_seq 增量），
用 Playwright 自带 Chromium，不依赖私有 @x-apaas。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: /capture/* routes (start / console / network / devtools / stop)

**Files:**
- Modify: `backend/app/routes/browser.py` (add `CaptureStartRequest` model near the other request models ~line 98-101; add 5 endpoints after the `/status` endpoint ~line 405). No change to `main.py` — `browser.router` is already mounted at line 169.
- Test: `backend/tests/test_capture_routes.py`

**Interfaces:**
- Consumes: `BrowserService.get_instance()`, the new `launch_capture/get_console_logs/get_network_requests/open_devtools/close_capture` from Task 4; existing `_verify_token`, `_get_token`, `router` (`prefix="/coding/workspace/{ws_id}/browser"`), `LaunchRequest` pattern.
- Produces (FIXED contract — routes under `/coding/workspace/{ws_id}/capture/`, full mounted path `/api/coding/workspace/{ws_id}/browser/capture/...` since they hang off the existing browser router):
  - `POST .../capture/start` body `{url}` → `{session_id}`
  - `GET .../capture/console?after_seq=N` → `{logs: [...]}`
  - `GET .../capture/network?after_seq=N` → `{requests: [...]}`
  - `POST .../capture/devtools` body `{session_id}` → `{status:"ok"}`
  - `POST .../capture/stop` body `{session_id}` → `{status:"closed"}`

Note: capture session_ids are global (not per-ws), so console/network/devtools/stop take `session_id` (from query or body). The `{ws_id}` segment stays for auth/token-scope consistency with the surrounding browser router.

- [ ] **Step 1: Write the failing test** — drives the routes through FastAPI's `TestClient`, monkeypatching `BrowserService.get_instance()` to a fake so no real Chromium launches. Token auth is satisfied by minting an `ide_access` JWT exactly like `_verify_token` expects.

```python
# backend/tests/test_capture_routes.py
"""C2 /capture/* 路由 — start/console/network/devtools/stop。

不启动真实 Chromium：monkeypatch BrowserService.get_instance() 为 FakeService。
token 用 _verify_token 期望的 ide_access JWT 现铸。
"""
import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.main import app
from app.config import settings
from app.routes import browser as browser_routes


def _token(ws_id: str) -> str:
    return jwt.encode(
        {"type": "ide_access", "ws": ws_id, "sub": "1", "tid": "1"},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )


class FakeService:
    def __init__(self):
        self.launched = []
        self.devtools_calls = []
        self.closed = []

    async def launch_capture(self, url, headless=True):
        self.launched.append((url, headless))
        return "cap-deadbeef0001"

    def get_console_logs(self, session_id, after_seq):
        return [{"seq": 1, "level": "error", "text": "boom", "location": "app.js:1:1"}]

    def get_network_requests(self, session_id, after_seq):
        return [{"seq": 1, "url": "http://x/boom", "status": 500, "method": "POST", "failed": False}]

    async def open_devtools(self, session_id):
        self.devtools_calls.append(session_id)

    async def close_capture(self, session_id):
        self.closed.append(session_id)


@pytest.fixture
def fake_service(monkeypatch):
    svc = FakeService()
    monkeypatch.setattr(browser_routes.BrowserService, "get_instance", classmethod(lambda cls: svc))
    return svc


@pytest.fixture
def client():
    return TestClient(app)


def test_capture_start_returns_session_id(client, fake_service):
    ws = "ws1"
    r = client.post(
        f"/api/coding/workspace/{ws}/browser/capture/start",
        params={"token": _token(ws)},
        json={"url": "http://127.0.0.1:5174/"},
    )
    assert r.status_code == 200
    assert r.json() == {"session_id": "cap-deadbeef0001"}
    assert fake_service.launched == [("http://127.0.0.1:5174/", True)]


def test_capture_console_and_network(client, fake_service):
    ws = "ws1"
    rc = client.get(
        f"/api/coding/workspace/{ws}/browser/capture/console",
        params={"token": _token(ws), "after_seq": 0, "session_id": "cap-x"},
    )
    assert rc.status_code == 200
    assert rc.json()["logs"][0]["level"] == "error"

    rn = client.get(
        f"/api/coding/workspace/{ws}/browser/capture/network",
        params={"token": _token(ws), "after_seq": 0, "session_id": "cap-x"},
    )
    assert rn.status_code == 200
    assert rn.json()["requests"][0]["status"] == 500


def test_capture_devtools_and_stop(client, fake_service):
    ws = "ws1"
    rd = client.post(
        f"/api/coding/workspace/{ws}/browser/capture/devtools",
        params={"token": _token(ws)},
        json={"session_id": "cap-x"},
    )
    assert rd.status_code == 200 and rd.json()["status"] == "ok"
    assert fake_service.devtools_calls == ["cap-x"]

    rs = client.post(
        f"/api/coding/workspace/{ws}/browser/capture/stop",
        params={"token": _token(ws)},
        json={"session_id": "cap-x"},
    )
    assert rs.status_code == 200 and rs.json()["status"] == "closed"
    assert fake_service.closed == ["cap-x"]


def test_capture_start_rejects_bad_token(client, fake_service):
    r = client.post(
        "/api/coding/workspace/ws1/browser/capture/start",
        params={"token": _token("OTHER_WS")},
        json={"url": "http://127.0.0.1:5174/"},
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

```
cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_capture_routes.py -q
```
Expected: the start/console/network/devtools/stop calls return `404 Not Found` (routes not registered yet) → `test_capture_start_returns_session_id`, `test_capture_console_and_network`, `test_capture_devtools_and_stop` fail on status assertions; `test_capture_start_rejects_bad_token` also fails (404 ≠ 403). 4 failed.

- [ ] **Step 3: Write minimal implementation** — add the request models and 5 endpoints. Match the existing per-endpoint auth pattern (`_verify_token(ws_id, _get_token(authorization, token))`) verbatim.

Add to the request models block (after `InjectRequest`, line 101):

```python
class CaptureStartRequest(BaseModel):
    url: str

class CaptureSessionRequest(BaseModel):
    session_id: str
```

Append after the `/status` endpoint (line 405):

```python
# ---------- C2 CDP 抓取 (capture) ----------

@router.post("/capture/start")
async def capture_start(
    ws_id: str,
    req: CaptureStartRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """启动一个 CDP 抓取会话（headless），加载 url 并挂 console/network 监听。"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    try:
        session_id = await service.launch_capture(req.url)
        return {"session_id": session_id}
    except Exception as e:
        logger.error(f"Failed to launch capture for {ws_id}: {e}")
        raise HTTPException(status_code=500, detail=f"启动抓取会话失败: {str(e)}")


@router.get("/capture/console")
async def capture_console(
    ws_id: str,
    session_id: str = Query(...),
    after_seq: int = Query(0),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """拉取 console 日志（after_seq 增量）。"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    return {"logs": service.get_console_logs(session_id, after_seq)}


@router.get("/capture/network")
async def capture_network(
    ws_id: str,
    session_id: str = Query(...),
    after_seq: int = Query(0),
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """拉取 network 失败/≥400 请求（after_seq 增量）。"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    return {"requests": service.get_network_requests(session_id, after_seq)}


@router.post("/capture/devtools")
async def capture_devtools(
    ws_id: str,
    req: CaptureSessionRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """以非 headless + DevTools 重开该抓取会话（独立 Chromium 窗口）。"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    await service.open_devtools(req.session_id)
    return {"status": "ok"}


@router.post("/capture/stop")
async def capture_stop(
    ws_id: str,
    req: CaptureSessionRequest,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    """关闭该抓取会话。"""
    _verify_token(ws_id, _get_token(authorization, token))
    service = BrowserService.get_instance()
    await service.close_capture(req.session_id)
    return {"status": "closed"}
```

- [ ] **Step 4: Run test to verify it passes**

```
cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_capture_routes.py tests/test_browser_capture.py -q
```
Expected: `9 passed` (4 route tests + 5 from Task 4). Because the sidecar runs with `reload=False`, this code only takes effect in a live app after the Python sidecar/backend process is restarted — note this for any manual/preview verification, but the pytest run above imports the app fresh so no restart is needed for the test.

- [ ] **Step 5: Commit**

```
cd "/Users/mars/Vibe Coding/ai-builder/backend" && git add app/routes/browser.py tests/test_capture_routes.py && git commit -m "feat(coding): /capture/* 路由 — start/console/network/devtools/stop

挂在既有 browser router (prefix /coding/workspace/{ws_id}/browser) 下，复用 _verify_token，
暴露 C2 CDP 抓取引擎给 C4 面板与 C5 自愈循环；main.py 已挂载该 router 无需改。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```


## C3 · serve↔preview 接通（Task 6–8）

### Task 6: Backend — resolve app+menu → bound workspace serve target for preview

**Files:**
- Modify: `backend/app/routes/applications/section_content.py` (add a helper near `_auto_bind_custom_page_workspace`:44-120, and a new route after `get_custom_page_host`:1224-1342)
- Test: `backend/tests/test_custom_page_dev_preview_target.py` (Create)

**Interfaces:**
- Consumes: `_auto_bind_custom_page_workspace(db, *, app_id, tenant_id, user_id, bundle_dir, component_tag) -> str | None` (existing, 44-120); `WorkspaceManager().is_serve_running(ws_id) -> dict {running, port?}` (existing, `workspace.py:1837`); `_load_app_and_check_view(app_id, ctx, db)` (existing, 229-245)
- Produces: `GET /api/applications/{app_id}/custom-page-dev-target?menu_id=...` returning `{"dev_running": bool, "port": int | None, "ws_id": str | None}`. The frontend C3 panel calls this to decide: `dev_running` true → preview src = `http://127.0.0.1:{port}/`; else → existing UMD `custom-page-host`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/test_custom_page_dev_preview_target.py
from unittest.mock import patch

import pytest

from app.models import Application, Conversation, Tenant, User, UserTenant
from app.routes.applications.section_content import resolve_custom_page_dev_target


@pytest.mark.asyncio
async def test_dev_target_returns_running_serve_port_for_bound_workspace(db_session):
    tenant = Tenant(tenant_name="dev-tenant", tenant_code="dev-tenant")
    owner = User(username="dev_owner", hashed_password="x")
    db_session.add_all([tenant, owner])
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))
    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="门户管理后台",
        app_code="portal-mgmt",
        apaas_app_id="853249733408325632",
    )
    conv = Conversation(
        user_id=owner.id,
        tenant_id=tenant.id,
        title="[迁移] 门户展示页",
        agent_type="coding",
        workspace_id="1_devws",
        coding_app_id=None,
    )
    db_session.add_all([app, conv])
    await db_session.commit()

    fake_rows = [
        {
            "id": "1_devws",
            "tenant_id": tenant.id,
            "project_id": None,
            "project_type": "form-page",
            "project_name": "form-page-portal-showcase-page",
            "display_name": "门户展示页",
        }
    ]

    with (
        patch("app.coding.workspace.WorkspaceManager.list_accessible_workspaces", return_value=fake_rows),
        patch("app.coding.workspace.WorkspaceManager.stamp_project_id", return_value=True),
        patch("app.coding.workspace.WorkspaceManager.is_serve_running", return_value={"running": True, "port": 8081}),
    ):
        result = await resolve_custom_page_dev_target(
            db_session,
            app_id=app.id,
            tenant_id=tenant.id,
            user_id=owner.id,
            bundle_dir="form-page-portal-showcase-page",
            component_tag="apaas-custom-portal-showcase-page",
        )

    assert result == {"dev_running": True, "port": 8081, "ws_id": "1_devws"}


@pytest.mark.asyncio
async def test_dev_target_reports_not_running_when_serve_down(db_session):
    tenant = Tenant(tenant_name="dev-tenant-2", tenant_code="dev-tenant-2")
    owner = User(username="dev_owner_2", hashed_password="x")
    db_session.add_all([tenant, owner])
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))
    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="门户管理后台",
        app_code="portal-mgmt-2",
        apaas_app_id="853249733408325999",
    )
    conv = Conversation(
        user_id=owner.id,
        tenant_id=tenant.id,
        title="门户展示页",
        agent_type="coding",
        workspace_id="1_devws2",
        coding_app_id=app.id,
    )
    db_session.add_all([app, conv])
    await db_session.commit()

    fake_rows = [
        {
            "id": "1_devws2",
            "tenant_id": tenant.id,
            "project_id": app.id,
            "project_type": "form-page",
            "project_name": "form-page-portal-showcase-page",
            "display_name": "门户展示页",
        }
    ]

    with (
        patch("app.coding.workspace.WorkspaceManager.list_accessible_workspaces", return_value=fake_rows),
        patch("app.coding.workspace.WorkspaceManager.stamp_project_id", return_value=True),
        patch("app.coding.workspace.WorkspaceManager.is_serve_running", return_value={"running": False}),
    ):
        result = await resolve_custom_page_dev_target(
            db_session,
            app_id=app.id,
            tenant_id=tenant.id,
            user_id=owner.id,
            bundle_dir="form-page-portal-showcase-page",
            component_tag="apaas-custom-portal-showcase-page",
        )

    assert result == {"dev_running": False, "port": None, "ws_id": "1_devws2"}
```

- [ ] **Step 2: Run test to verify it fails**
  Command: `cd backend && .venv/bin/python -m pytest tests/test_custom_page_dev_preview_target.py -q`
  Expected: collection/import fails with `ImportError: cannot import name 'resolve_custom_page_dev_target' from 'app.routes.applications.section_content'` (2 errors).

- [ ] **Step 3: Write minimal implementation**
  In `backend/app/routes/applications/section_content.py`, add this helper immediately after `_auto_bind_custom_page_workspace` (ends at line 120):
```python
async def resolve_custom_page_dev_target(
    db: AsyncSession,
    *,
    app_id: int,
    tenant_id: int,
    user_id: int,
    bundle_dir: str,
    component_tag: str,
) -> dict:
    """Resolve whether a dev server (npm run serve) is live for the workspace bound
    to this custom page, so the preview panel can switch src dev-URL ⇄ UMD host.

    Returns {"dev_running": bool, "port": int | None, "ws_id": str | None}.
    Reuses _auto_bind_custom_page_workspace for the same app→workspace resolution
    the UMD host uses, then queries WorkspaceManager.is_serve_running.
    """
    from app.coding.workspace import WorkspaceManager

    ws_id = await _auto_bind_custom_page_workspace(
        db,
        app_id=app_id,
        tenant_id=tenant_id,
        user_id=user_id,
        bundle_dir=bundle_dir,
        component_tag=component_tag,
    )
    if not ws_id:
        return {"dev_running": False, "port": None, "ws_id": None}

    status = WorkspaceManager().is_serve_running(ws_id)
    if status.get("running") and status.get("port"):
        return {"dev_running": True, "port": int(status["port"]), "ws_id": ws_id}
    return {"dev_running": False, "port": None, "ws_id": ws_id}
```
  Then add this route immediately after `get_custom_page_host` (ends at line 1342). It reuses the same `menu_id → link_url → bundle_dir` resolution as the host route:
```python
@router.get("/{app_id}/custom-page-dev-target")
async def get_custom_page_dev_target(
    app_id: int,
    menu_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _auth: str = "",
) -> dict:
    """前端预览面板查询: 该自开发页面绑定的工作区是否正在 npm run serve.

    dev_running=True → 预览 src 切 dev server http://127.0.0.1:{port}/ (HMR);
    否则 → 走既有 custom-page-host UMD 宿主 (已部署/只读回退)。
    """
    from app.coding.apaas_tools import call_apaas_with_relogin

    token = _extract_custom_page_auth_token(request, _auth)
    try:
        ctx = await _auth_context_from_custom_page_request(request, token)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="未认证 — 请重新登录后重试")

    app = await _load_app_and_check_view(app_id, ctx, db)
    if not app.platform_env_id or not app.apaas_app_id:
        return {"dev_running": False, "port": None, "ws_id": None}

    try:
        raw_menus_nested = await call_apaas_with_relogin(
            app.platform_env_id, db,
            lambda c: c.query_menus(str(app.apaas_app_id)),
        )
    except Exception:  # noqa: BLE001
        return {"dev_running": False, "port": None, "ws_id": None}

    def _find_link_url(nodes: Any, target: str) -> str:
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            nid = str(n.get("id") or n.get("menuId") or n.get("menu_id") or "")
            if nid == str(target):
                return str(n.get("linkUrl") or n.get("link_url") or "")
            found = _find_link_url(n.get("submenus") or n.get("children") or [], target)
            if found:
                return found
        return ""

    link_url = _find_link_url(raw_menus_nested or [], str(menu_id))
    if not link_url:
        return {"dev_running": False, "port": None, "ws_id": None}

    component_tag = link_url
    if link_url.startswith("apaas-custom-"):
        bundle_dir = "form-page-" + link_url[len("apaas-custom-"):]
    else:
        bundle_dir = link_url

    return await resolve_custom_page_dev_target(
        db,
        app_id=app.id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        bundle_dir=bundle_dir,
        component_tag=component_tag,
    )
```

- [ ] **Step 4: Run test to verify it passes**
  Command: `cd backend && .venv/bin/python -m pytest tests/test_custom_page_dev_preview_target.py -q`
  Expected: `2 passed`. (Note: the running backend has `reload=False` — restart the sidecar/backend process before the new route serves live requests; the unit test runs in-process so it does not need a restart.)

- [ ] **Step 5: Commit**
  Command: `cd backend && git add app/routes/applications/section_content.py tests/test_custom_page_dev_preview_target.py`
  Message: `feat(preview): resolve dev serve target for custom-page preview (C3-a)\n\nNew GET /applications/{app_id}/custom-page-dev-target reuses the host\nroute's menu→bundle resolution + is_serve_running so the preview panel\ncan pick dev-server URL over the UMD host when serve is live.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 7: Backend — inject `$request`/`window.df` shim into the dev workspace template

**Files:**
- Create: `backend/templates/cli-generated/form-page-web/public/index.html`
- Modify: `backend/templates/vibe-serve.js:1-36` (note: shared file; no edit to logic needed — see Step 3 note)
- Test: `backend/tests/test_dev_template_shim.py` (Create)

**Interfaces:**
- Consumes: the existing `/apaas/backend/{tenantCode}/{appCode}` runtime proxy (`runtime_proxy.py:264-266`, `proxy_apaas`, injects platform auth). The dev page's `$request` routes all relative data calls through it. The shim mirrors the UMD host's `apaasRequest`/`window.df` semantics built in `_build_custom_page_host_html` (`section_content.py:1062-1089`).
- Produces: a vue-cli dev `public/index.html` whose `<head>` defines `window.$request`, `Vue.prototype.$request`, and `window.df` before the app mounts. vue-cli serve auto-uses `public/index.html` as the HTML template (no `vue.config.js` change needed; `form-page-web/vue.config.js` does not override `indexPath`/`template`).

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/test_dev_template_shim.py
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "templates" / "cli-generated" / "form-page-web" / "public" / "index.html"
)


def test_dev_index_html_exists():
    assert TEMPLATE.is_file(), f"missing dev shim template: {TEMPLATE}"


def test_dev_index_html_injects_request_and_df_shim():
    html = TEMPLATE.read_text(encoding="utf-8")
    # $request shim present and exposed both globally and on the Vue prototype
    assert "window.$request" in html
    assert "Vue.prototype.$request" in html
    assert "window.df" in html
    # data calls route through the existing /apaas/backend runtime proxy
    assert "/apaas/backend" in html
    # vue-cli mount point preserved
    assert 'id="app"' in html
    assert "<%= " in html  # keeps vue-cli htmlWebpackPlugin template tokens
```

- [ ] **Step 2: Run test to verify it fails**
  Command: `cd backend && .venv/bin/python -m pytest tests/test_dev_template_shim.py -q`
  Expected: `test_dev_index_html_exists` fails with `AssertionError: missing dev shim template: .../form-page-web/public/index.html` (file does not exist yet; the other test errors on the same missing file).

- [ ] **Step 3: Write minimal implementation**
  Create `backend/templates/cli-generated/form-page-web/public/index.html`. The shim base URL is taken from `window.__APAAS_API_BASE__` if the iframe parent sets it, else falls back to `/apaas/backend` (the runtime proxy mount). It is a faithful port of the UMD host's `apaasRequest`/`window.df` (`section_content.py:1062-1089`), adapted to run inside the dev server page:
```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="viewport" content="width=device-width,initial-scale=1.0" />
    <title><%= htmlWebpackPlugin.options.title %></title>
    <!-- SP1 C3: dev-server preview shim — 数据调用经 /apaas/backend 运行态代理 (后端注入平台 token).
         apiBase 默认 /apaas/backend; 宿主 iframe 可在 mount 前 set window.__APAAS_API_BASE__ 指向带 tenant/app 的前缀. -->
    <script>
      (function () {
        var apiBase = (window.__APAAS_API_BASE__ || '/apaas/backend');
        function apaasRequest(cfg) {
          if (typeof cfg === 'string') cfg = { url: cfg };
          cfg = cfg || {};
          var url = cfg.url || '';
          if (url.indexOf('http') !== 0) {
            if (url.charAt(0) !== '/') url = apiBase + '/' + url;
            else if (url.indexOf('/apaas') !== 0) url = apiBase + url;
          }
          var method = (cfg.method || 'get').toUpperCase();
          var params = cfg.params || cfg.data;
          var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
          if (params && method === 'GET') {
            var qs = Object.keys(params)
              .map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); })
              .join('&');
            if (qs) url += (url.indexOf('?') < 0 ? '?' : '&') + qs;
          } else if (params) {
            opts.body = typeof params === 'string' ? params : JSON.stringify(params);
          }
          return fetch(url, opts)
            .then(function (r) { return r.json().catch(function () { return null; }); })
            .then(function (j) { return (j && typeof j === 'object' && 'data' in j) ? j : { data: j, success: true }; })
            .catch(function (e) { console.warn('[dev-shim] $request fail', url, e); return { data: null, success: false }; });
        }
        window.$request = apaasRequest;
        var dfBase = {
          request: apaasRequest, http: apaasRequest,
          get: function (u, p) { return apaasRequest({ url: u, method: 'get', params: p }); },
          post: function (u, p) { return apaasRequest({ url: u, method: 'post', params: p }); },
          getToken: function () { return ''; }, t: function (k) { return k; }, i18n: { t: function (k) { return k; } },
          user: {}, store: {}, env: (window.GLOBAL_ENV || {}),
        };
        window.df = new Proxy(dfBase, {
          get: function (t, k) { if (k in t) return t[k]; return function () { return Promise.resolve(null); }; },
        });
        // Make $request available on Vue 2 prototype as soon as Vue global appears.
        function bindVue() {
          if (window.Vue && window.Vue.prototype && !window.Vue.prototype.$request) {
            window.Vue.prototype.$request = apaasRequest;
            window.Vue.prototype.$df = window.df;
          }
        }
        bindVue();
        document.addEventListener('DOMContentLoaded', bindVue);
      })();
    </script>
  </head>
  <body>
    <noscript>
      <strong>需要启用 JavaScript 才能运行此自开发页面预览。</strong>
    </noscript>
    <div id="app"></div>
    <!-- vue-cli serve 自动注入 chunk 脚本 -->
  </body>
</html>
```
  Note: `vibe-serve.js` needs no logic change for the shim — vue-cli's html-webpack-plugin picks up `public/index.html` automatically. The Modify entry is listed only so reviewers confirm the serve path (`workspace.py:1787` runs `vue-cli-service serve src/index.js` from the workspace root, which copies this `public/`); no byte changes are made to `vibe-serve.js` in this task.

- [ ] **Step 4: Run test to verify it passes**
  Command: `cd backend && .venv/bin/python -m pytest tests/test_dev_template_shim.py -q`
  Expected: `2 passed`.

- [ ] **Step 5: Commit**
  Command: `cd backend && git add templates/cli-generated/form-page-web/public/index.html tests/test_dev_template_shim.py`
  Message: `feat(preview): inject $request/window.df shim into dev workspace template (C3 default)\n\nform-page-web public/index.html now defines $request + window.df that\nroute data calls through the existing /apaas/backend runtime proxy with\nplatform auth — the default per-contract shim path (薄 proxy fallback\nnot implemented; see spec §9.1).\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 8: Frontend — CustomPagePreviewPanel chooses dev-server src when serve is running

**Files:**
- Modify: `frontend/src/components/v3/CustomPagePreviewPanel.vue:50-95` (script: add `onMounted` query of dev target + computed `previewSrc`) and `:24-32` (template: bind iframe to `previewSrc`)
- Modify: `frontend/src/api/coding.ts:239-242` (add `customPageDevTarget`)
- Test: manual/preview verification (no frontend unit-test runner — see Step 1)

**Interfaces:**
- Consumes: `GET /api/applications/{app_id}/custom-page-dev-target?menu_id=...&_auth=<token>` → `{dev_running, port, ws_id}` (Task 6); existing `hostUrl` computed (UMD fallback, `CustomPagePreviewPanel.vue:71-77`).
- Produces: `previewSrc` computed — `http://127.0.0.1:{port}/` when `dev_running`, else existing `hostUrl`. UMD path preserved verbatim as deployed/read-only fallback.

- [ ] **Step 1: Write the failing test** — No frontend unit-test runner exists in this repo (only `npm run build` / `build:nocheck` and manual preview per project memory). This task uses an explicit manual/preview verification instead of a fake unit test. The "failing" baseline to capture before implementing: with a workspace serving (`npm run serve` running for the app's bound workspace), open the 自开发 preview panel — the iframe currently loads the UMD `custom-page-host` (no HMR). Record this as the pre-change behavior.

- [ ] **Step 2: Run test to verify it fails** — Build the current (unchanged) frontend to confirm a clean baseline:
  Command: `cd frontend && npm run build:nocheck`
  Expected: build succeeds; `grep -n "custom-page-dev-target" src/api/coding.ts` returns nothing (the new path is absent), confirming the dev-target wiring does not yet exist.

- [ ] **Step 3: Write minimal implementation**
  In `frontend/src/api/coding.ts`, add after `getServeStatus` (line 242, inside the api object):
```typescript
  /** 查询自开发页面绑定工作区是否在 npm run serve(预览面板 dev⇄UMD 切换) */
  customPageDevTarget(appId: number, menuId: string, authToken: string) {
    return request.get<any, { dev_running: boolean; port: number | null; ws_id: string | null }>(
      `/applications/${appId}/custom-page-dev-target`,
      { params: { menu_id: menuId, _auth: authToken } },
    )
  },
```
  In `frontend/src/components/v3/CustomPagePreviewPanel.vue`, change the script imports and add dev-target state. Replace line 51:
```typescript
import { ref, computed, onMounted, watch } from 'vue'
```
  Add after `const iframeKey = ref(0)` (line 67):
```typescript
import { codingApi } from '@/api/coding'

// SP1 C3: 若该应用绑定的工作区正在 npm run serve, 预览直吃 dev server(带 HMR);
// 否则回退到既有 UMD custom-page-host(已部署/只读态)。
const devServerPort = ref<number | null>(null)

async function refreshDevTarget() {
  devServerPort.value = null
  if (!props.appId || !props.menuId) return
  const tok = userStore.token || localStorage.getItem('token') || ''
  try {
    const r = await codingApi.customPageDevTarget(props.appId, props.menuId, tok)
    if (r.dev_running && r.port) devServerPort.value = r.port
  } catch {
    devServerPort.value = null
  }
}

onMounted(refreshDevTarget)
watch(() => [props.appId, props.menuId], refreshDevTarget)
```
  Add a `previewSrc` computed immediately after the existing `hostUrl` computed (after line 77):
```typescript
// dev server 运行中 → 直连 dev URL(HMR);否则 → UMD host(保留作部署/只读回退)。
const previewSrc = computed(() => {
  if (devServerPort.value) return `http://127.0.0.1:${devServerPort.value}/`
  return hostUrl.value
})
```
  In the template, change the `v-if` guard and the iframe `:src` (lines 24 and 28):
  - Line 24: `<div v-if="hostUrl" class="cpp-frame-wrap">` → `<div v-if="previewSrc" class="cpp-frame-wrap">`
  - Line 28: `:src="hostUrl"` → `:src="previewSrc"`

- [ ] **Step 4: Run test to verify it passes**
  Command: `cd frontend && npm run build:nocheck && grep -n "custom-page-dev-target" src/api/coding.ts`
  Expected: build succeeds; grep prints the new endpoint line. Then manual preview verification: (a) with the app's bound workspace NOT serving, open the 自开发 preview panel → iframe `src` resolves to `/api/applications/{id}/custom-page-host?...` (UMD fallback, unchanged); (b) start serve for that workspace (运行/调试 面板 or `codingApi.startServe`), reopen the panel → iframe `src` resolves to `http://127.0.0.1:{port}/`, dev page renders with the injected `$request`/`window.df` shim (Task 7) and data calls hit `/apaas/backend`. Confirm editing a `.vue` source line triggers HMR in the iframe. (Backend `reload=False`: restart the sidecar/backend once after Task 6 so `custom-page-dev-target` is live before this manual check.)

- [ ] **Step 5: Commit**
  Command: `cd frontend && git add src/components/v3/CustomPagePreviewPanel.vue src/api/coding.ts`
  Message: `feat(preview): use dev-server src when serve running, UMD host as fallback (C3)\n\nCustomPagePreviewPanel queries custom-page-dev-target; when the bound\nworkspace is serving it loads http://127.0.0.1:{port}/ (HMR + shim),\notherwise keeps the existing UMD custom-page-host as the deployed/\nread-only fallback.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`


## C4 · 运行/调试面板（前端，Task 9–11）

### Task 9: 前端 API — serve-logs URL 构造器 + capture endpoints

**Files:**
- Create: `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/coding/serveLogsUrl.ts`
- Create: `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/coding/serveLogsUrl.spec.ts`
- Modify: `/Users/mars/Vibe Coding/ai-builder/frontend/src/api/coding.ts:229-242`

**Interfaces:**
- Consumes: `API_PREFIX` (from `@/utils/request`, `/api` in dev / `${BASE_URL}api` in prod); `localStorage.getItem('token')` (token convention used by `downloadZip`/`publish`/`uploadFile`); backend routes from C1/C2: `GET /coding/workspace/{ws_id}/serve-logs?last_seen_seq=N` (SSE), `POST /coding/workspace/{ws_id}/capture/start {url}`, `GET /coding/workspace/{ws_id}/capture/console?after_seq=N`, `GET /coding/workspace/{ws_id}/capture/network?after_seq=N`, `POST /coding/workspace/{ws_id}/capture/devtools`, `POST /coding/workspace/{ws_id}/capture/stop`.
- Produces (FIXED names later tasks rely on): `buildServeLogsUrl(prefix, wsId, lastSeenSeq, token)` pure fn; `codingApi.serveLogsUrl(wsId, lastSeenSeq) -> string`, `codingApi.captureStart(wsId, url) -> Promise<{session_id: string}>`, `codingApi.captureConsole(wsId, afterSeq) -> Promise<{seq:number,level:string,text:string,location:string}[]>`, `codingApi.captureNetwork(wsId, afterSeq) -> Promise<{seq:number,url:string,status:number,method:string,failed:boolean}[]>`, `codingApi.captureDevtools(wsId) -> Promise<{status:string}>`, `codingApi.captureStop(wsId) -> Promise<{status:string}>`.

- [ ] **Step 1: Write the failing test** — real test code, mirroring the `codingLayout.spec.ts` pure-fn convention (vitest, node env, no DOM):

```ts
// frontend/src/views/coding/serveLogsUrl.spec.ts
import { describe, expect, it } from 'vitest'
import { buildServeLogsUrl } from './serveLogsUrl'

describe('buildServeLogsUrl', () => {
  it('appends last_seen_seq and token to the serve-logs SSE path', () => {
    expect(buildServeLogsUrl('/api', '1_8ae94ab4', 0, 'tok123')).toBe(
      '/api/coding/workspace/1_8ae94ab4/serve-logs?last_seen_seq=0&token=tok123',
    )
  })

  it('uses the provided after-seq cursor for reconnect', () => {
    expect(buildServeLogsUrl('/api', 'ws1', 42, 'tok123')).toBe(
      '/api/coding/workspace/ws1/serve-logs?last_seen_seq=42&token=tok123',
    )
  })

  it('omits the token param when no token is present', () => {
    expect(buildServeLogsUrl('/ai-builder/api', 'ws1', 7, '')).toBe(
      '/ai-builder/api/coding/workspace/ws1/serve-logs?last_seen_seq=7',
    )
  })

  it('url-encodes the token', () => {
    expect(buildServeLogsUrl('/api', 'ws1', 0, 'a b/c')).toBe(
      '/api/coding/workspace/ws1/serve-logs?last_seen_seq=0&token=a%20b%2Fc',
    )
  })
})
```

- [ ] **Step 2: Run test to verify it fails** — exact command from `frontend/`:
  ```
  npx vitest run src/views/coding/serveLogsUrl.spec.ts
  ```
  Expected: fails to collect / resolve — `Failed to load url ./serveLogsUrl` (module does not exist yet).

- [ ] **Step 3: Write minimal implementation** — create the pure helper (no `@/utils/request` import so it stays node-pure for vitest):

```ts
// frontend/src/views/coding/serveLogsUrl.ts
/**
 * 拼装 serve-logs SSE 的完整 URL。EventSource 不能带自定义 header，
 * 故 token 走 query（对齐 extension.ts 的 extension-update-events 用法）。
 * 断线重连靠 last_seen_seq（后端补发 > last_seen_seq 的历史行）。
 */
export function buildServeLogsUrl(
  prefix: string,
  wsId: string,
  lastSeenSeq: number,
  token: string,
): string {
  const base = `${prefix}/coding/workspace/${wsId}/serve-logs?last_seen_seq=${lastSeenSeq}`
  return token ? `${base}&token=${encodeURIComponent(token)}` : base
}
```

- [ ] **Step 4: Run test to verify it passes** — same command:
  ```
  npx vitest run src/views/coding/serveLogsUrl.spec.ts
  ```
  Expected: `Test Files  1 passed (1)` / `Tests  4 passed (4)`.

- [ ] **Step 4b: Add the API functions to `codingApi`** — insert after the existing `getServeStatus` (`coding.ts:239-242`), before `uploadToPlatform`. The `serveLogsUrl` method wires the pure helper to live `API_PREFIX` + token; the capture calls use `request` (its response interceptor returns `.data`, like every other `codingApi.*`):

```ts
  /** serve-logs SSE 的完整 URL（给 EventSource 用，token 走 query） */
  serveLogsUrl(wsId: string, lastSeenSeq: number): string {
    return buildServeLogsUrl(API_PREFIX, wsId, lastSeenSeq, localStorage.getItem('token') || '')
  },

  /** 启动 CDP 抓取实例，加载同一 dev server URL */
  captureStart(wsId: string, url: string) {
    return request.post<any, { session_id: string }>(`/coding/workspace/${wsId}/browser/capture/start`, { url }, { timeout: 120000 })
  },

  /** 拉控制台日志（after_seq 之后的增量） */
  captureConsole(wsId: string, afterSeq: number) {
    return request.get<any, { seq: number; level: string; text: string; location: string }[]>(`/coding/workspace/${wsId}/browser/capture/console`, { params: { after_seq: afterSeq } })
  },

  /** 拉网络请求（只含 status>=400 与失败） */
  captureNetwork(wsId: string, afterSeq: number) {
    return request.get<any, { seq: number; url: string; status: number; method: string; failed: boolean }[]>(`/coding/workspace/${wsId}/browser/capture/network`, { params: { after_seq: afterSeq } })
  },

  /** 在独立 Chromium 窗口打开 DevTools（同一抓取会话非 headless 重开） */
  captureDevtools(wsId: string) {
    return request.post<any, { status: string }>(`/coding/workspace/${wsId}/browser/capture/devtools`, {})
  },

  /** 停止并清理 CDP 抓取实例 */
  captureStop(wsId: string) {
    return request.post<any, { status: string }>(`/coding/workspace/${wsId}/browser/capture/stop`, {})
  },
```
  Then add the import at the top of `coding.ts` (after the existing `import { API_PREFIX } from '@/utils/request'` on line 2):
```ts
import { buildServeLogsUrl } from '@/views/coding/serveLogsUrl'
```

- [ ] **Step 4c: Typecheck the edited API file** — from `frontend/`:
  ```
  npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep -E "api/coding\.ts|serveLogsUrl\.ts" || echo "no new type errors in coding.ts / serveLogsUrl.ts"
  ```
  Expected: `no new type errors in coding.ts / serveLogsUrl.ts`. (Note: this project's `vue-tsc -p tsconfig.app.json` has ~388 pre-existing errors elsewhere — only assert that the two files we touched are clean.)

- [ ] **Step 5: Commit**
  ```
  git add "frontend/src/views/coding/serveLogsUrl.ts" "frontend/src/views/coding/serveLogsUrl.spec.ts" "frontend/src/api/coding.ts"
  git commit -m "feat(coding): add serve-logs URL builder + capture API to codingApi (C4)"
  ```

---

### Task 10: 运行/调试面板纯状态模块（log ring / capture 游标 / 网络过滤）

**Files:**
- Create: `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/coding/runDebugState.ts`
- Create: `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/coding/runDebugState.spec.ts`

**Interfaces:**
- Consumes: SSE log shape `{seq:number, stream:'stdout'|'stderr', line:string}` (C1 `iter_serve_logs`); console shape `{seq,level,text,location}` and network shape `{seq,url,status,method,failed}` (C2 capture endpoints).
- Produces (FIXED names the Vue panel in Task 11 relies on): `LogLine`, `ConsoleEntry`, `NetEntry` types; `appendLogLine(ring, line, maxLines=2000) -> LogLine[]` (ring-trims, dedupes by seq, keeps order); `nextAfterSeq(entries, current) -> number` (max seq seen, for polling cursor); `mergeBySeq<T extends {seq:number}>(existing, incoming) -> T[]`; `isErrorLog(line) -> boolean` (stderr or text matching `/error|fail|exception/i`, for highlight).

- [ ] **Step 1: Write the failing test** — real vitest pure-fn test:

```ts
// frontend/src/views/coding/runDebugState.spec.ts
import { describe, expect, it } from 'vitest'
import {
  appendLogLine,
  nextAfterSeq,
  mergeBySeq,
  isErrorLog,
  type LogLine,
} from './runDebugState'

describe('appendLogLine', () => {
  it('appends in order and dedupes by seq', () => {
    let ring: LogLine[] = []
    ring = appendLogLine(ring, { seq: 1, stream: 'stdout', line: 'a' })
    ring = appendLogLine(ring, { seq: 2, stream: 'stderr', line: 'b' })
    ring = appendLogLine(ring, { seq: 2, stream: 'stderr', line: 'b' }) // dup seq ignored
    expect(ring.map(l => l.seq)).toEqual([1, 2])
  })

  it('trims to the most recent maxLines', () => {
    let ring: LogLine[] = []
    for (let i = 1; i <= 5; i++) ring = appendLogLine(ring, { seq: i, stream: 'stdout', line: `l${i}` }, 3)
    expect(ring.map(l => l.seq)).toEqual([3, 4, 5])
  })
})

describe('nextAfterSeq', () => {
  it('returns the max seq seen, else the current cursor', () => {
    expect(nextAfterSeq([{ seq: 3 }, { seq: 7 }, { seq: 5 }], 0)).toBe(7)
    expect(nextAfterSeq([], 4)).toBe(4)
  })
})

describe('mergeBySeq', () => {
  it('concatenates only strictly-newer entries by seq', () => {
    const existing = [{ seq: 1 }, { seq: 2 }]
    const incoming = [{ seq: 2 }, { seq: 3 }]
    expect(mergeBySeq(existing, incoming).map(e => e.seq)).toEqual([1, 2, 3])
  })
})

describe('isErrorLog', () => {
  it('flags stderr and error-like text', () => {
    expect(isErrorLog({ seq: 1, stream: 'stderr', line: 'whatever' })).toBe(true)
    expect(isErrorLog({ seq: 2, stream: 'stdout', line: 'Module build failed' })).toBe(true)
    expect(isErrorLog({ seq: 3, stream: 'stdout', line: 'Compiled successfully' })).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails** — from `frontend/`:
  ```
  npx vitest run src/views/coding/runDebugState.spec.ts
  ```
  Expected: fails — `Failed to load url ./runDebugState` (module missing).

- [ ] **Step 3: Write minimal implementation**:

```ts
// frontend/src/views/coding/runDebugState.ts
// 运行/调试面板的纯状态工具（无 Vue/DOM 依赖，方便 vitest 单测）。

export interface LogLine {
  seq: number
  stream: 'stdout' | 'stderr'
  line: string
}

export interface ConsoleEntry {
  seq: number
  level: string
  text: string
  location: string
}

export interface NetEntry {
  seq: number
  url: string
  status: number
  method: string
  failed: boolean
}

/** 追加一行日志：按 seq 去重、保序、环形裁剪到 maxLines。 */
export function appendLogLine(ring: LogLine[], line: LogLine, maxLines = 2000): LogLine[] {
  if (ring.length && ring[ring.length - 1].seq >= line.seq) {
    if (ring.some(l => l.seq === line.seq)) return ring
  }
  const next = [...ring, line]
  return next.length > maxLines ? next.slice(next.length - maxLines) : next
}

/** 下一次轮询的游标 = 见过的最大 seq，没有新行则保持当前游标。 */
export function nextAfterSeq(entries: { seq: number }[], current: number): number {
  return entries.reduce((m, e) => (e.seq > m ? e.seq : m), current)
}

/** 把严格更新（seq 更大）的条目并到已有列表后面。 */
export function mergeBySeq<T extends { seq: number }>(existing: T[], incoming: T[]): T[] {
  const maxExisting = existing.reduce((m, e) => (e.seq > m ? e.seq : m), -Infinity)
  const fresh = incoming.filter(e => e.seq > maxExisting)
  return fresh.length ? [...existing, ...fresh] : existing
}

const ERROR_RE = /error|fail|exception/i

/** stderr 行或包含 error/fail/exception 的行 → 高亮为错误。 */
export function isErrorLog(line: LogLine): boolean {
  return line.stream === 'stderr' || ERROR_RE.test(line.line)
}
```

- [ ] **Step 4: Run test to verify it passes** — same command:
  ```
  npx vitest run src/views/coding/runDebugState.spec.ts
  ```
  Expected: `Test Files  1 passed (1)` / `Tests  6 passed (6)`.

- [ ] **Step 4b: Run the full coding spec suite to confirm no regression** — from `frontend/`:
  ```
  npx vitest run src/views/coding
  ```
  Expected: all existing `src/views/coding/*.spec.ts` plus the two new files pass (no failures).

- [ ] **Step 5: Commit**
  ```
  git add "frontend/src/views/coding/runDebugState.ts" "frontend/src/views/coding/runDebugState.spec.ts"
  git commit -m "feat(coding): add run/debug panel pure state helpers (log ring, capture cursors) (C4)"
  ```

---

### Task 11: 在 CodingPage 右栏挂「运行/调试」tab（Vue 组件 + 接线）

> No Vue-component unit-test runner exists here — vitest is configured for pure `.ts` modules only (`vitest.config.ts` → `include: ['src/**/*.spec.ts']`, `environment: 'node'`, no jsdom/@vue/test-utils). The logic this task depends on is already unit-tested in Tasks 7–8. This task is therefore verified via the **preview workflow** (`preview_start` / `preview_snapshot` / `preview_console_logs`) and explicit manual steps, NOT a fake unit test.

**Files:**
- Create: `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/coding/RunDebugPanel.vue`
- Modify: `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/CodingPage.vue:311-340` (add a tab switch over the `ws-pane` block)
- Test: (manual / preview — see steps below; no `.spec.ts` because SFCs aren't covered by the runner)

**Interfaces:**
- Consumes: `codingApi.startServe(wsId)`, `codingApi.stopServe(wsId)`, `codingApi.getServeStatus(wsId)` (existing, `coding.ts:230-242`); `codingApi.serveLogsUrl/captureStart/captureConsole/captureNetwork/captureDevtools/captureStop` (Task 9); `appendLogLine/nextAfterSeq/mergeBySeq/isErrorLog` + types (Task 10); `openExternal` (`@/utils/openExternal`) as a fallback if devtools window can't open in-app; `codingStore.workspace?.id` and `themeStore.isDark` (already in `CodingPage.vue:610,616`).
- Produces: `<RunDebugPanel :ws-id="..." :dark="..." />` mounted in the right pane under a new "运行/调试" tab.

- [ ] **Step 1: Write the panel component** — create `RunDebugPanel.vue`. EventSource is created directly (browser API) using `codingApi.serveLogsUrl`; capture panels poll on a 2s interval using the cursor helpers; cleanup on stop/unmount:

```vue
<!-- frontend/src/views/coding/RunDebugPanel.vue -->
<template>
  <div class="run-debug-panel" :class="{ dark }">
    <div class="rd-toolbar">
      <button class="rd-btn" :disabled="busy" @click="running ? stop() : start()">
        {{ running ? '停止' : '运行' }}
      </button>
      <span v-if="devUrl" class="rd-url">{{ devUrl }}</span>
      <span class="rd-spacer" />
      <button class="rd-btn" :disabled="!captureSession" @click="openDevtools">在 DevTools 打开</button>
    </div>

    <div class="rd-body">
      <div class="rd-col rd-preview">
        <div class="rd-col-title">预览</div>
        <iframe v-if="devUrl" :src="devUrl" class="rd-iframe" />
        <div v-else class="rd-empty">点「运行」启动开发服务器后在此预览</div>
      </div>

      <div class="rd-col rd-logs">
        <div class="rd-col-title">实时日志</div>
        <div ref="logBox" class="rd-logbox">
          <div
            v-for="l in logs"
            :key="l.seq"
            class="rd-logline"
            :class="{ 'is-error': isErrorLog(l) }"
          >{{ l.line }}</div>
        </div>
      </div>

      <div class="rd-col rd-obs">
        <div class="rd-tabs">
          <button :class="{ active: obsTab === 'console' }" @click="obsTab = 'console'">控制台 ({{ consoleLogs.length }})</button>
          <button :class="{ active: obsTab === 'network' }" @click="obsTab = 'network'">网络 ({{ netLogs.length }})</button>
        </div>
        <div v-show="obsTab === 'console'" class="rd-obs-list">
          <div v-for="c in consoleLogs" :key="c.seq" class="rd-obs-row" :class="{ 'is-error': c.level === 'error' }">
            <span class="rd-lvl">{{ c.level }}</span> {{ c.text }}
            <span v-if="c.location" class="rd-loc">{{ c.location }}</span>
          </div>
        </div>
        <div v-show="obsTab === 'network'" class="rd-obs-list">
          <div v-for="n in netLogs" :key="n.seq" class="rd-obs-row" :class="{ 'is-error': n.failed || n.status >= 400 }">
            <span class="rd-status">{{ n.failed ? 'ERR' : n.status }}</span>
            <span class="rd-method">{{ n.method }}</span> {{ n.url }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onBeforeUnmount } from 'vue'
import { codingApi } from '@/api/coding'
import { openExternal } from '@/utils/openExternal'
import {
  appendLogLine,
  nextAfterSeq,
  mergeBySeq,
  isErrorLog,
  type LogLine,
  type ConsoleEntry,
  type NetEntry,
} from './runDebugState'

const props = defineProps<{ wsId: string; dark?: boolean }>()

const running = ref(false)
const busy = ref(false)
const devUrl = ref('')
const logs = ref<LogLine[]>([])
const consoleLogs = ref<ConsoleEntry[]>([])
const netLogs = ref<NetEntry[]>([])
const obsTab = ref<'console' | 'network'>('console')
const captureSession = ref('')
const logBox = ref<HTMLElement | null>(null)

let es: EventSource | null = null
let pollTimer: number | null = null
let lastSeq = 0
let consoleSeq = 0
let netSeq = 0

function teardown() {
  if (es) { try { es.close() } catch { /* ignore */ } es = null }
  if (pollTimer != null) { clearInterval(pollTimer); pollTimer = null }
}

async function scrollLogs() {
  await nextTick()
  if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
}

function openLogStream() {
  es = new EventSource(codingApi.serveLogsUrl(props.wsId, lastSeq))
  es.addEventListener('log', (ev: MessageEvent) => {
    try {
      const data = JSON.parse(ev.data) as LogLine
      logs.value = appendLogLine(logs.value, data)
      lastSeq = nextAfterSeq([data], lastSeq)
      void scrollLogs()
    } catch { /* ignore malformed line */ }
  })
}

async function pollCapture() {
  if (!captureSession.value) return
  try {
    const [c, n] = await Promise.all([
      codingApi.captureConsole(props.wsId, consoleSeq),
      codingApi.captureNetwork(props.wsId, netSeq),
    ])
    consoleLogs.value = mergeBySeq(consoleLogs.value, c)
    netLogs.value = mergeBySeq(netLogs.value, n)
    consoleSeq = nextAfterSeq(c, consoleSeq)
    netSeq = nextAfterSeq(n, netSeq)
  } catch { /* transient; next tick retries */ }
}

async function start() {
  if (!props.wsId) return
  busy.value = true
  try {
    const res = await codingApi.startServe(props.wsId)
    devUrl.value = res.url || ''
    running.value = true
    lastSeq = 0
    openLogStream()
    if (devUrl.value) {
      try {
        const cap = await codingApi.captureStart(props.wsId, devUrl.value)
        captureSession.value = cap.session_id
        consoleSeq = 0
        netSeq = 0
        pollTimer = window.setInterval(pollCapture, 2000)
      } catch { /* CDP 缺失时降级为仅日志 + iframe 预览（spec §6） */ }
    }
  } finally {
    busy.value = false
  }
}

async function stop() {
  busy.value = true
  try {
    if (captureSession.value) { await codingApi.captureStop(props.wsId).catch(() => {}) }
    await codingApi.stopServe(props.wsId).catch(() => {})
  } finally {
    teardown()
    running.value = false
    devUrl.value = ''
    captureSession.value = ''
    busy.value = false
  }
}

async function openDevtools() {
  if (!captureSession.value) {
    if (devUrl.value) await openExternal(devUrl.value)
    return
  }
  await codingApi.captureDevtools(props.wsId).catch(() => {})
}

// 切工作区：停掉旧会话，重置面板。
watch(() => props.wsId, () => { void stop() })
onBeforeUnmount(teardown)
</script>

<style scoped>
.run-debug-panel { display: flex; flex-direction: column; height: 100%; min-width: 0; }
.rd-toolbar { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--border-1, #e5e7eb); }
.rd-btn { font-size: 13px; padding: 4px 12px; border: 1px solid var(--border-1, #e5e7eb); border-radius: 6px; background: var(--bg-1, #fff); cursor: pointer; }
.rd-btn:disabled { opacity: .5; cursor: default; }
.rd-url { font-size: 12px; color: var(--text-3, #888); }
.rd-spacer { flex: 1; }
.rd-body { flex: 1; display: flex; min-height: 0; }
.rd-col { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--border-1, #e5e7eb); }
.rd-preview { flex: 2; }
.rd-logs { flex: 1.2; }
.rd-obs { flex: 1.2; border-right: none; }
.rd-col-title { font-size: 12px; color: var(--text-3, #888); padding: 6px 10px; }
.rd-iframe { flex: 1; width: 100%; border: 0; }
.rd-empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-3, #888); font-size: 13px; }
.rd-logbox { flex: 1; overflow: auto; font-family: ui-monospace, monospace; font-size: 12px; padding: 6px 10px; }
.rd-logline { white-space: pre-wrap; word-break: break-all; }
.rd-logline.is-error { color: var(--err, #e54d42); }
.rd-tabs { display: flex; gap: 6px; padding: 6px 10px; }
.rd-tabs button { font-size: 12px; border: none; background: none; cursor: pointer; color: var(--text-3, #888); }
.rd-tabs button.active { color: var(--text-1, #222); font-weight: 600; }
.rd-obs-list { flex: 1; overflow: auto; font-family: ui-monospace, monospace; font-size: 12px; padding: 4px 10px; }
.rd-obs-row { padding: 2px 0; word-break: break-all; }
.rd-obs-row.is-error { color: var(--err, #e54d42); }
.rd-lvl, .rd-status, .rd-method { font-weight: 600; margin-right: 6px; }
.rd-loc { color: var(--text-3, #888); margin-left: 6px; }
.run-debug-panel.dark { color: var(--text-1, #ddd); }
</style>
```

- [ ] **Step 2: Wire the tab into CodingPage** — in `CodingPage.vue` replace the `ws-pane` block (`311-340`). First add the import alongside the existing `FileTree`/`CodeViewer` imports (after `CodingPage.vue:601`):
```ts
import RunDebugPanel from './coding/RunDebugPanel.vue'
```
  Add reactive state near the other `ref`s (after `const codeFirst = ...` at `CodingPage.vue:840`):
```ts
const wsPaneTab = ref<'files' | 'run'>('files')
```
  Then wrap the existing pane content with a tab header + conditional render (the existing FileTree+resizer+CodeViewer become the `files` tab; the new panel is the `run` tab):
```vue
      <!-- Task 9-9: 文件树/代码 + 运行/调试 双 tab 右栏 -->
      <div
        v-if="showWorkspacePane"
        class="ws-pane"
      >
        <div class="ws-pane-tabs">
          <button :class="{ active: wsPaneTab === 'files' }" @click="wsPaneTab = 'files'">文件 / 代码</button>
          <button :class="{ active: wsPaneTab === 'run' }" @click="wsPaneTab = 'run'">运行/调试</button>
        </div>
        <div v-show="wsPaneTab === 'files'" class="ws-pane-files">
          <FileTree
            class="ws-pane-tree"
            :style="{ width: treePaneWidth + 'px' }"
            :tree="wsFileTree"
            :changed="changedPaths"
            :changes="wsGitChanges"
            :selected="selectedFile"
            :ws-id="codingStore.workspace?.id || ''"
            @select="onTreeSelect"
            @select-line="onTreeSelectLine"
            @accept-all="acceptAllWorkspaceChanges"
          />
          <div class="tree-resizer" title="拖拽调整文件树宽度" @pointerdown="onTreeResizeStart" />
          <CodeViewer
            class="ws-pane-viewer"
            :ws-id="codingStore.workspace?.id || ''"
            :file-path="selectedFile"
            :diff="selectedGitChange ? null : selectedDiff"
            :change="selectedGitChange"
            :focus-line="viewerFocusLine"
            :dark="themeStore.isDark"
            @quote="onViewerQuote"
            @accept-change="acceptWorkspaceChange"
          />
        </div>
        <RunDebugPanel
          v-show="wsPaneTab === 'run'"
          :ws-id="codingStore.workspace?.id || ''"
          :dark="themeStore.isDark"
        />
      </div>
```
  Add the tab-header CSS near the existing `.ws-pane` rule in the same file's `<style>` (use existing token vars; the `.ws-pane-files` keeps the original flex-row layout of tree+resizer+viewer):
```css
.ws-pane { display: flex; flex-direction: column; min-width: 0; }
.ws-pane-tabs { display: flex; gap: 4px; padding: 6px 10px; border-bottom: 1px solid var(--border-1, #e5e7eb); flex: 0 0 auto; }
.ws-pane-tabs button { font-size: 12px; border: none; background: none; cursor: pointer; color: var(--text-3, #888); padding: 2px 8px; border-radius: 6px; }
.ws-pane-tabs button.active { color: var(--text-1, #222); font-weight: 600; background: var(--bg-2, #f3f4f6); }
.ws-pane-files { display: flex; flex: 1; min-height: 0; }
```
  > If the existing `.ws-pane` rule already sets `display: flex` as a row, change only that one declaration to `column` as shown — the row layout now lives on `.ws-pane-files`. Confirm by grepping `grep -n "\.ws-pane" frontend/src/views/CodingPage.vue` before editing so you replace (not duplicate) the rule.

- [ ] **Step 3: Typecheck the touched frontend files** — from `frontend/`:
  ```
  npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep -E "RunDebugPanel\.vue|CodingPage\.vue" | grep -v "169\| pre-exist" || echo "no NEW type errors in RunDebugPanel.vue (CodingPage.vue has ~169 pre-existing)"
  ```
  Expected: no errors that reference `RunDebugPanel.vue`; `CodingPage.vue` only shows the same pre-existing ~169 errors noted in project memory (compare against `git stash` baseline if unsure). Build sanity: `npm run build:nocheck` succeeds.

- [ ] **Step 4: Verify via the preview workflow + manual steps** (no unit test for the SFC — stated above). Backend gotcha: the C1/C2 routes run in the PyInstaller sidecar / `backend/run.py` with `reload=False`, so **restart the sidecar/backend process** after C1–C3 land before this UI can talk to them.
  1. `preview_start` the frontend (Vite dev or the desktop app) and `preview_snapshot` the CodingPage with a workspace open. Expect the right pane to show two tabs: "文件 / 代码" and "运行/调试".
  2. Click "运行/调试", then click "运行". Expect: button flips to "停止", a dev-server URL appears, the preview `<iframe>` loads it, and the 实时日志 box streams lines (driven by the C1 `serve-logs` SSE via `codingApi.serveLogsUrl`).
  3. `preview_console_logs` — confirm no uncaught errors from `RunDebugPanel` (e.g. EventSource URL malformed). The serve-logs EventSource request should appear going to `/api/coding/workspace/{ws_id}/serve-logs?last_seen_seq=0&token=...`.
  4. Switch to the 网络 / 控制台 sub-tabs — confirm rows populate from the 2s capture poll once a CDP session exists; if CDP is unavailable the panel degrades to logs+iframe only (no crash), matching spec §6.
  5. Click "在 DevTools 打开" — confirm it triggers `captureDevtools` (independent Chromium window) or, with no session, falls back to `openExternal(devUrl)`.
  6. Click "停止" — confirm `stopServe` + `captureStop` fire, the iframe clears, the SSE closes (no further log lines), and the poll interval stops. Switch workspaces and confirm the panel resets (the `watch(() => props.wsId)` calls `stop()`).
  7. Regression: confirm existing FileTree/CodeViewer still work under the "文件 / 代码" tab (select a file, see content/diff) — i.e. the deploy/preview and existing serve paths are untouched.

- [ ] **Step 5: Commit**
  ```
  git add "frontend/src/views/coding/RunDebugPanel.vue" "frontend/src/views/CodingPage.vue"
  git commit -m "feat(coding): add 运行/调试 tab to CodingPage right pane (logs/preview/console/network/devtools) (C4)"
  ```


## C5 · AI 自愈循环（SP1-b，Task 12–14）

### Task 12: AutoFix signal collector — build + runtime error aggregation

**Files:**
- Create: `backend/app/agents/coding/autofix_signals.py`
- Test: `backend/tests/test_autofix_signals.py`

**Interfaces:**
- Consumes (C1, existing): `WorkspaceManager.build_project(ws_id: str) -> dict {status, message}` (`backend/app/coding/workspace.py:1616`)
- Consumes (C2 contract, FIXED): `BrowserService.get_instance()`, `launch_capture(url: str, headless: bool = True) -> str`, `get_console_logs(session_id: str, after_seq: int) -> list[dict {seq, level, text, location}]`, `get_network_requests(session_id: str, after_seq: int) -> list[dict {seq, url, status, method, failed}]`, `close_capture(session_id: str) -> None`
- Produces (later tasks rely on these names verbatim):
  - `collect_build_errors(build_result: dict) -> list[str]`
  - `collect_runtime_errors(console_logs: list[dict], network_requests: list[dict]) -> list[str]`
  - `build_fix_hint(build_errors: list[str], runtime_errors: list[str]) -> str`
  - `signals_signature(build_errors: list[str], runtime_errors: list[str]) -> str`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_autofix_signals.py
"""C5 AutoFix 信号收集器 —— 纯函数单测（不起进程、不连 LLM）。"""
from __future__ import annotations

from app.agents.coding.autofix_signals import (
    build_fix_hint,
    collect_build_errors,
    collect_runtime_errors,
    signals_signature,
)


def test_collect_build_errors_extracts_message_on_error():
    result = {"status": "error", "message": "web/ 构建失败: Module not found: ./foo.vue"}
    errs = collect_build_errors(result)
    assert errs == ["web/ 构建失败: Module not found: ./foo.vue"]


def test_collect_build_errors_empty_on_ok():
    assert collect_build_errors({"status": "ok", "message": "构建成功"}) == []


def test_collect_runtime_errors_filters_console_error_and_pageerror():
    console = [
        {"seq": 1, "level": "log", "text": "hello", "location": ""},
        {"seq": 2, "level": "error", "text": "x is not a function", "location": "edit.vue:10"},
        {"seq": 3, "level": "pageerror", "text": "Uncaught TypeError: y", "location": ""},
        {"seq": 4, "level": "warning", "text": "deprecated", "location": ""},
    ]
    errs = collect_runtime_errors(console, [])
    assert errs == [
        "[console.error] x is not a function (edit.vue:10)",
        "[pageerror] Uncaught TypeError: y",
    ]


def test_collect_runtime_errors_includes_network_failures():
    network = [
        {"seq": 1, "url": "http://127.0.0.1:8080/api/x", "status": 500, "method": "GET", "failed": False},
        {"seq": 2, "url": "http://127.0.0.1:8080/api/y", "status": 0, "method": "POST", "failed": True},
    ]
    errs = collect_runtime_errors([], network)
    assert errs == [
        "[network 500] GET http://127.0.0.1:8080/api/x",
        "[network failed] POST http://127.0.0.1:8080/api/y",
    ]


def test_build_fix_hint_renders_sections():
    hint = build_fix_hint(["build boom"], ["[console.error] runtime boom"])
    assert "构建报错" in hint
    assert "build boom" in hint
    assert "运行时报错" in hint
    assert "runtime boom" in hint


def test_build_fix_hint_empty_when_no_signals():
    assert build_fix_hint([], []) == ""


def test_signals_signature_stable_and_order_independent():
    sig_a = signals_signature(["e1", "e2"], ["r1"])
    sig_b = signals_signature(["e2", "e1"], ["r1"])
    sig_c = signals_signature(["e1"], ["r1"])
    assert sig_a == sig_b
    assert sig_a != sig_c
```

- [ ] **Step 2: Run test to verify it fails**

Command (from repo root):
```
.venv/bin/python -m pytest backend/tests/test_autofix_signals.py -q
```
Expected: collection/run fails with `ModuleNotFoundError: No module named 'app.agents.coding.autofix_signals'` (module does not exist yet).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/coding/autofix_signals.py
"""C5 AutoFix 信号收集器（纯函数，无副作用）。

把三类失败信号归一成字符串列表，再渲染成喂给 CodingAgent 的 fix_hint。
- build：WorkspaceManager.build_project 返回 dict（status/message）
- console：BrowserService.get_console_logs（level/text/location）
- network：BrowserService.get_network_requests（status>=400 或 failed，C2 已过滤）

signals_signature 用于「同一报错重复出现即停」的判定（顺序无关、稳定 hash）。
"""
from __future__ import annotations

import hashlib

# 视为运行时错误的 console level（pageerror 由 C2 以 level="pageerror" 投递）
_ERROR_CONSOLE_LEVELS = {"error", "pageerror"}


def collect_build_errors(build_result: dict) -> list[str]:
    """从 build_project 返回 dict 抠错误信息。status != 'ok' 即视为失败。"""
    if not build_result:
        return []
    if build_result.get("status") == "ok":
        return []
    msg = str(build_result.get("message") or "").strip()
    return [msg] if msg else ["构建失败（无错误信息）"]


def collect_runtime_errors(
    console_logs: list[dict],
    network_requests: list[dict],
) -> list[str]:
    """从 C2 抓到的 console / network 列表里挑出失败信号。

    - console.error / pageerror → 文本（带 location）
    - network：C2 已只投递 status>=400 与 failed，这里全部计入
    """
    errors: list[str] = []
    for entry in console_logs or []:
        level = str(entry.get("level") or "").lower()
        if level not in _ERROR_CONSOLE_LEVELS:
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        location = str(entry.get("location") or "").strip()
        tag = "pageerror" if level == "pageerror" else "console.error"
        errors.append(f"[{tag}] {text}" + (f" ({location})" if location else ""))

    for req in network_requests or []:
        method = str(req.get("method") or "").strip() or "GET"
        url = str(req.get("url") or "").strip()
        if req.get("failed"):
            errors.append(f"[network failed] {method} {url}")
        else:
            status = int(req.get("status") or 0)
            errors.append(f"[network {status}] {method} {url}")
    return errors


def build_fix_hint(build_errors: list[str], runtime_errors: list[str]) -> str:
    """渲染成 CodingAgent build_initial_user_message 期望的 fix_hint markdown。

    返回空字符串表示「没有任何失败信号」（driver 据此判定本轮干净、停止）。
    """
    if not build_errors and not runtime_errors:
        return ""
    parts: list[str] = ["**本轮验收发现以下问题，请针对性修复：**\n"]
    if build_errors:
        parts.append("### 构建报错")
        parts.extend(f"- {e}" for e in build_errors)
    if runtime_errors:
        parts.append("### 运行时报错（console.error / pageerror / network）")
        parts.extend(f"- {e}" for e in runtime_errors)
    return "\n".join(parts)


def signals_signature(build_errors: list[str], runtime_errors: list[str]) -> str:
    """顺序无关的稳定指纹，用于「同一报错重复出现」判定。"""
    payload = "\n".join(sorted(build_errors) + ["::"] + sorted(runtime_errors))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Command (from repo root):
```
.venv/bin/python -m pytest backend/tests/test_autofix_signals.py -q
```
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```
git add backend/app/agents/coding/autofix_signals.py backend/tests/test_autofix_signals.py
git commit -m "feat(coding): add C5 autofix signal collector (build+runtime error aggregation)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: `drive_coding_with_autofix` driver loop (build/serve → CDP capture → fix_hint re-round)

**Files:**
- Create: `backend/app/agents/coding/autofix_driver.py`
- Test: `backend/tests/test_autofix_driver.py`

**Interfaces:**
- Consumes (Task 12): `collect_build_errors`, `collect_runtime_errors`, `build_fix_hint`, `signals_signature`
- Consumes (existing): `CodingAgent` + `CodingAgentStreamAdapter.run(*, requirement, conversation_summary, max_turns, model) -> AsyncIterator[dict]` (`backend/app/agents/coding/adapter.py:114`); `CodingAgent.ctx.input` / `CodingAgent.ctx.extra` (the agent already reads `fix_hint` from `ctx.input` and `round_index` from `ctx.extra` in `build_initial_user_message`, `agent.py:204-205`); `CodingAgent._tokens_input` / `._tokens_output` (`agent.py:556-557`); `WorkspaceManager.build_project(ws_id)`, `WorkspaceManager.start_serve(ws_id, kind="web")`, `WorkspaceManager.is_serve_running(ws_id)` (`workspace.py:1616/1758/1837`)
- Consumes (C2 contract, FIXED): `BrowserService.get_instance().launch_capture(url, headless=True)`, `.get_console_logs(session_id, after_seq)`, `.get_network_requests(session_id, after_seq)`, `.close_capture(session_id)`
- Produces (Task 14 relies on these names):
  - `drive_coding_with_autofix(*, agent: CodingAgent, adapter: CodingAgentStreamAdapter, requirement: str, conversation_summary: str, model: str, max_turns: int, ws_mgr, preview_url: str | None, max_autofix_rounds: int = 3) -> AsyncIterator[dict]`
  - Each yielded dict is a pipeline-compatible SSE event; the driver additionally yields `{"type": "autofix_round", "round": int, "status": "verifying"|"clean"|"fixing"|"exhausted"|"repeated", "errors": list[str], "tokens_input": int, "tokens_output": int}` markers between rounds.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_autofix_driver.py
"""C5 drive_coding_with_autofix —— 驱动循环单测。

用假 agent/adapter/ws_mgr/BrowserService 验证：
- 干净时不重试
- 有信号时注入 fix_hint+round_index 再跑一轮
- max_autofix_rounds 上限
- 同一报错重复即停
- token 计入预算
不起真实进程、不连 LLM、不依赖 DB。
"""
from __future__ import annotations

import pytest

from app.agents.coding.autofix_driver import drive_coding_with_autofix


class _FakeAgent:
    def __init__(self):
        from types import SimpleNamespace
        self.ctx = SimpleNamespace(input={}, extra={})
        self._tokens_input = 0
        self._tokens_output = 0


class _FakeAdapter:
    """每次 run 记一次 fix_hint/round_index 快照，并把 token 累加到 agent。"""
    def __init__(self, agent):
        self._agent = agent
        self.calls = []

    async def run(self, *, requirement, conversation_summary, max_turns, model=None):
        self.calls.append({
            "fix_hint": self._agent.ctx.input.get("fix_hint"),
            "round_index": self._agent.ctx.extra.get("round_index"),
        })
        self._agent._tokens_input += 100
        self._agent._tokens_output += 50
        yield {"type": "agent_tool", "tool": "write_file"}


class _FakeWsMgr:
    def __init__(self, build_results):
        self._build_results = list(build_results)
        self.build_calls = 0

    async def build_project(self, ws_id):
        self.build_calls += 1
        return self._build_results.pop(0)

    async def start_serve(self, ws_id, kind="web"):
        return {"status": "ok", "port": 8080, "message": ""}

    def is_serve_running(self, ws_id):
        return {"running": True, "port": 8080}


class _FakeBrowser:
    def __init__(self, console_per_round, network_per_round):
        self._console = list(console_per_round)
        self._network = list(network_per_round)
        self._round = -1
        self.closed = []

    def launch_capture(self, url, headless=True):
        self._round += 1
        return f"sess_{self._round}"

    def get_console_logs(self, session_id, after_seq):
        idx = int(session_id.split("_")[1])
        return self._console[idx] if idx < len(self._console) else []

    def get_network_requests(self, session_id, after_seq):
        idx = int(session_id.split("_")[1])
        return self._network[idx] if idx < len(self._network) else []

    def close_capture(self, session_id):
        self.closed.append(session_id)


async def _drain(gen):
    return [ev async for ev in gen]


@pytest.mark.asyncio
async def test_clean_first_round_no_retry(monkeypatch):
    agent = _FakeAgent()
    adapter = _FakeAdapter(agent)
    ws_mgr = _FakeWsMgr([{"status": "ok", "message": "构建成功"}])
    browser = _FakeBrowser([[]], [[]])
    monkeypatch.setattr(
        "app.agents.coding.autofix_driver._get_browser_service", lambda: browser
    )
    events = await _drain(drive_coding_with_autofix(
        agent=agent, adapter=adapter, requirement="r", conversation_summary="",
        model="m", max_turns=30, ws_mgr=ws_mgr, preview_url="http://127.0.0.1:8080/",
        max_autofix_rounds=3,
    ))
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["round_index"] in (0, None)
    clean = [e for e in events if e.get("type") == "autofix_round" and e.get("status") == "clean"]
    assert len(clean) == 1
    assert browser.closed == ["sess_0"]


@pytest.mark.asyncio
async def test_build_error_then_clean(monkeypatch):
    agent = _FakeAgent()
    adapter = _FakeAdapter(agent)
    ws_mgr = _FakeWsMgr([
        {"status": "error", "message": "Module not found: ./a.vue"},
        {"status": "ok", "message": "构建成功"},
    ])
    browser = _FakeBrowser([[], []], [[], []])
    monkeypatch.setattr(
        "app.agents.coding.autofix_driver._get_browser_service", lambda: browser
    )
    events = await _drain(drive_coding_with_autofix(
        agent=agent, adapter=adapter, requirement="r", conversation_summary="",
        model="m", max_turns=30, ws_mgr=ws_mgr, preview_url="http://127.0.0.1:8080/",
        max_autofix_rounds=3,
    ))
    assert len(adapter.calls) == 2
    assert "Module not found" in (adapter.calls[1]["fix_hint"] or "")
    assert adapter.calls[1]["round_index"] == 1
    assert agent.ctx.input.get("fix_hint") is None  # 干净后清理
    assert agent._tokens_input == 200 and agent._tokens_output == 100


@pytest.mark.asyncio
async def test_repeated_same_error_stops(monkeypatch):
    agent = _FakeAgent()
    adapter = _FakeAdapter(agent)
    ws_mgr = _FakeWsMgr([
        {"status": "error", "message": "same boom"},
        {"status": "error", "message": "same boom"},
    ])
    browser = _FakeBrowser([[], []], [[], []])
    monkeypatch.setattr(
        "app.agents.coding.autofix_driver._get_browser_service", lambda: browser
    )
    events = await _drain(drive_coding_with_autofix(
        agent=agent, adapter=adapter, requirement="r", conversation_summary="",
        model="m", max_turns=30, ws_mgr=ws_mgr, preview_url="http://127.0.0.1:8080/",
        max_autofix_rounds=3,
    ))
    assert len(adapter.calls) == 2  # 第2轮跑完发现同样的错 → 停
    repeated = [e for e in events if e.get("type") == "autofix_round" and e.get("status") == "repeated"]
    assert len(repeated) == 1


@pytest.mark.asyncio
async def test_rounds_exhausted(monkeypatch):
    agent = _FakeAgent()
    adapter = _FakeAdapter(agent)
    ws_mgr = _FakeWsMgr([
        {"status": "error", "message": "e1"},
        {"status": "error", "message": "e2"},
        {"status": "error", "message": "e3"},
    ])
    browser = _FakeBrowser([[], [], []], [[], [], []])
    monkeypatch.setattr(
        "app.agents.coding.autofix_driver._get_browser_service", lambda: browser
    )
    events = await _drain(drive_coding_with_autofix(
        agent=agent, adapter=adapter, requirement="r", conversation_summary="",
        model="m", max_turns=30, ws_mgr=ws_mgr, preview_url="http://127.0.0.1:8080/",
        max_autofix_rounds=3,
    ))
    assert len(adapter.calls) == 3  # 初轮 + 2 次重试 = max_autofix_rounds
    exhausted = [e for e in events if e.get("type") == "autofix_round" and e.get("status") == "exhausted"]
    assert len(exhausted) == 1


@pytest.mark.asyncio
async def test_no_preview_url_skips_runtime_capture(monkeypatch):
    """preview_url=None（拿不到 dev server）→ 只 build 校验，不起 CDP。"""
    agent = _FakeAgent()
    adapter = _FakeAdapter(agent)
    ws_mgr = _FakeWsMgr([{"status": "ok", "message": "构建成功"}])
    browser = _FakeBrowser([[]], [[]])
    monkeypatch.setattr(
        "app.agents.coding.autofix_driver._get_browser_service", lambda: browser
    )
    await _drain(drive_coding_with_autofix(
        agent=agent, adapter=adapter, requirement="r", conversation_summary="",
        model="m", max_turns=30, ws_mgr=ws_mgr, preview_url=None,
        max_autofix_rounds=3,
    ))
    assert browser.closed == []  # 没起 capture
```

- [ ] **Step 2: Run test to verify it fails**

Command (from repo root):
```
.venv/bin/python -m pytest backend/tests/test_autofix_driver.py -q
```
Expected: fails with `ModuleNotFoundError: No module named 'app.agents.coding.autofix_driver'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/coding/autofix_driver.py
"""C5 · AI 自愈循环 drive_coding_with_autofix（SP1-b）。

包在 CodingAgentStreamAdapter.run 外层：每轮 agent 改完代码后
build/serve + CDP launch_capture 抓 console/network，收集失败信号，
有信号则把 fix_hint 塞回 ctx.input、round_index 塞回 ctx.extra，再跑一轮。

停止条件（任一）：本轮无新信号 / 同一报错重复 / 达 max_autofix_rounds。
token 计入 agent._tokens_input/_output（adapter.run 内已累加，driver 只读出做 budget marker）。

不破坏现有 pipeline SSE 事件流：agent 事件原样 yield；driver 仅在每轮之间
额外 yield {"type": "autofix_round", ...} marker（pipeline append 进 replay 即可，
前端不识别也无副作用）。
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional

from app.agents.coding.adapter import CodingAgentStreamAdapter
from app.agents.coding.agent import CodingAgent
from app.agents.coding.autofix_signals import (
    build_fix_hint,
    collect_build_errors,
    collect_runtime_errors,
    signals_signature,
)

logger = logging.getLogger(__name__)


def _get_browser_service():
    """间接拿 BrowserService 单例，便于测试 monkeypatch。"""
    from app.coding.browser_service import BrowserService
    return BrowserService.get_instance()


async def _capture_runtime_errors(preview_url: str) -> list[str]:
    """起一个 CDP 抓取会话加载 preview_url，收 console/network 失败信号后关闭。

    CDP 缺失/启动失败按 spec §6 降级为「仅日志，无运行时抓取」——不阻断自愈。
    """
    browser = _get_browser_service()
    session_id: Optional[str] = None
    try:
        session_id = browser.launch_capture(preview_url, headless=True)
        console_logs = browser.get_console_logs(session_id, 0) or []
        network = browser.get_network_requests(session_id, 0) or []
        return collect_runtime_errors(console_logs, network)
    except Exception:
        logger.warning("autofix: CDP 抓取失败，降级为仅 build 校验", exc_info=True)
        return []
    finally:
        if session_id is not None:
            try:
                browser.close_capture(session_id)
            except Exception:
                logger.warning("autofix: close_capture 失败（忽略）", exc_info=True)


async def drive_coding_with_autofix(
    *,
    agent: CodingAgent,
    adapter: CodingAgentStreamAdapter,
    requirement: str,
    conversation_summary: str,
    model: str,
    max_turns: int,
    ws_mgr: Any,
    preview_url: Optional[str],
    max_autofix_rounds: int = 3,
) -> AsyncIterator[dict[str, Any]]:
    """驱动 CodingAgent 跑 ≤ max_autofix_rounds 轮，每轮后验收并按需注入 fix_hint。"""
    ws_id = agent.ctx.workspace_id
    prev_signature: Optional[str] = None

    for round_index in range(max_autofix_rounds):
        # round_index>0 时，本轮 fix_hint 已在上一轮末尾写进 ctx.input（见下方）
        agent.ctx.extra = dict(agent.ctx.extra or {})
        agent.ctx.extra["round_index"] = round_index

        # 跑一轮 agent（事件原样透传给 pipeline）
        async for event in adapter.run(
            requirement=requirement,
            conversation_summary=conversation_summary,
            max_turns=max_turns,
            model=model,
        ):
            yield event

        tokens_in = getattr(agent, "_tokens_input", 0)
        tokens_out = getattr(agent, "_tokens_output", 0)

        yield {
            "type": "autofix_round", "round": round_index, "status": "verifying",
            "errors": [], "tokens_input": tokens_in, "tokens_output": tokens_out,
        }

        # 1. build 校验
        build_errors: list[str] = []
        if ws_id:
            try:
                build_result = await ws_mgr.build_project(ws_id)
                build_errors = collect_build_errors(build_result)
            except Exception as e:
                build_errors = [f"构建过程异常: {e}"]

        # 2. 运行时抓取（仅在 build 通过且有 preview_url 时；build 已失败无需起服务）
        runtime_errors: list[str] = []
        if not build_errors and preview_url:
            runtime_errors = await _capture_runtime_errors(preview_url)

        all_errors = build_errors + runtime_errors

        # 3. 无信号 → 干净，停
        if not all_errors:
            yield {
                "type": "autofix_round", "round": round_index, "status": "clean",
                "errors": [], "tokens_input": tokens_in, "tokens_output": tokens_out,
            }
            agent.ctx.input.pop("fix_hint", None)
            return

        # 4. 同一报错重复 → 如实上报并停
        signature = signals_signature(build_errors, runtime_errors)
        if signature == prev_signature:
            yield {
                "type": "autofix_round", "round": round_index, "status": "repeated",
                "errors": all_errors, "tokens_input": tokens_in, "tokens_output": tokens_out,
            }
            agent.ctx.input.pop("fix_hint", None)
            return
        prev_signature = signature

        # 5. 还有重试名额 → 注入 fix_hint，下一轮重跑；否则上限耗尽，停
        if round_index + 1 < max_autofix_rounds:
            agent.ctx.input = dict(agent.ctx.input or {})
            agent.ctx.input["fix_hint"] = build_fix_hint(build_errors, runtime_errors)
            yield {
                "type": "autofix_round", "round": round_index, "status": "fixing",
                "errors": all_errors, "tokens_input": tokens_in, "tokens_output": tokens_out,
            }
        else:
            yield {
                "type": "autofix_round", "round": round_index, "status": "exhausted",
                "errors": all_errors, "tokens_input": tokens_in, "tokens_output": tokens_out,
            }
            agent.ctx.input.pop("fix_hint", None)
            return
```

- [ ] **Step 4: Run test to verify it passes**

Command (from repo root):
```
.venv/bin/python -m pytest backend/tests/test_autofix_driver.py -q
```
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```
git add backend/app/agents/coding/autofix_driver.py backend/tests/test_autofix_driver.py
git commit -m "feat(coding): add drive_coding_with_autofix loop (C5 SP1-b)

build/serve verify + CDP capture per round, inject fix_hint and re-run;
stop on clean / repeated error / rounds exhausted; tokens tracked via agent.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Wire `drive_coding_with_autofix` into `run_coding_pipeline` behind a flag (no SSE-flow regression)

**Files:**
- Modify: `backend/app/coding/pipeline.py:2086-2140` (replace the single `agent.run(...)` consumption block with a flag-gated driver path)
- Test: `backend/tests/test_autofix_pipeline_wiring.py`

**Interfaces:**
- Consumes (Task 13): `drive_coding_with_autofix(*, agent, adapter, requirement, conversation_summary, model, max_turns, ws_mgr, preview_url, max_autofix_rounds)`
- Consumes (existing in scope at pipeline.py:2085-2086): local vars `_coding_agent` (`CodingAgent`), `agent` (`CodingAgentStreamAdapter`), `ws_mgr` (`WorkspaceManager`), `ws_id`, `effective_requirement`, `conversation_summary`, `effective_model`; existing event-handling loop body (`append_event_to_stream_replay`, `yield event`, `append_agent_event_to_history`, `tool_events_for_summary`, `final_agent_summary` / `agent_result_text` accumulation, `agent_thinking`/`agent_done` handling) (`pipeline.py:2112-2140`)
- Consumes (C1, existing): `ws_mgr.is_serve_running(ws_id)` to derive `preview_url` (`workspace.py:1837`)
- Produces: a feature-flagged autofix code path; default behavior unchanged (flag off → identical single-run flow).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_autofix_pipeline_wiring.py
"""验证 pipeline 在 autofix flag 开启时把 agent 事件包进 driver，
且 autofix_round marker 进 replay；flag 关闭时走原单跑路径（行为不变）。"""
from __future__ import annotations

from app.coding import pipeline as pipeline_mod


def test_resolve_preview_url_from_serve_status_dual():
    # 双端 serve：优先取 web port
    status = {"running": True, "dual": True, "web": {"port": 8080}, "mobile": {"port": 8090}}
    assert pipeline_mod._autofix_preview_url(status) == "http://127.0.0.1:8080/"


def test_resolve_preview_url_from_serve_status_single():
    status = {"running": True, "port": 8081}
    assert pipeline_mod._autofix_preview_url(status) == "http://127.0.0.1:8081/"


def test_resolve_preview_url_none_when_not_running():
    assert pipeline_mod._autofix_preview_url({"running": False}) is None


def test_autofix_enabled_flag_default_off(monkeypatch):
    monkeypatch.delenv("CODING_AUTOFIX_ENABLED", raising=False)
    assert pipeline_mod._autofix_enabled() is False


def test_autofix_enabled_flag_on(monkeypatch):
    monkeypatch.setenv("CODING_AUTOFIX_ENABLED", "1")
    assert pipeline_mod._autofix_enabled() is True
```

- [ ] **Step 2: Run test to verify it fails**

Command (from repo root):
```
.venv/bin/python -m pytest backend/tests/test_autofix_pipeline_wiring.py -q
```
Expected: fails with `AttributeError: module 'app.coding.pipeline' has no attribute '_autofix_preview_url'` (and `_autofix_enabled`).

- [ ] **Step 3: Write minimal implementation**

First add the two helper functions near the top of `pipeline.py` (after the existing module imports / before `run_coding_pipeline`; place immediately above `async def run_coding_pipeline` at line 1510):

```python
def _autofix_enabled() -> bool:
    """C5 自愈循环默认关闭（gated rollout）。设 CODING_AUTOFIX_ENABLED=1 开启。"""
    import os
    return os.getenv("CODING_AUTOFIX_ENABLED", "").strip() in ("1", "true", "True")


def _autofix_preview_url(serve_status: dict) -> str | None:
    """从 is_serve_running 返回值推导 dev server 预览 URL（C1/C3）。

    双端取 web port；单端取 port；未运行返回 None（driver 跳过运行时抓取）。
    """
    if not serve_status or not serve_status.get("running"):
        return None
    if serve_status.get("dual"):
        web = serve_status.get("web") or {}
        port = web.get("port")
    else:
        port = serve_status.get("port")
    if not port:
        return None
    return f"http://127.0.0.1:{port}/"
```

Then replace the agent-run consumption block. Current code (`pipeline.py:2111-2117`):

```python
        try:
            async for event in agent.run(
                requirement=effective_requirement,
                conversation_summary=conversation_summary,
                model=effective_model,
                max_turns=30,
            ):
```

becomes:

```python
        # C5: 自愈循环（flag 开启 + 有 workspace 时）包一层 driver；
        # 否则走原单跑路径（行为字节级不变）。driver yield 的 autofix_round
        # marker 走与普通事件相同的处理（append replay + yield），前端不识别也无害。
        if _autofix_enabled() and ws_id:
            from app.agents.coding.autofix_driver import drive_coding_with_autofix
            _serve_status = ws_mgr.is_serve_running(ws_id)
            _preview_url = _autofix_preview_url(_serve_status)
            _agent_event_source = drive_coding_with_autofix(
                agent=_coding_agent,
                adapter=agent,
                requirement=effective_requirement,
                conversation_summary=conversation_summary,
                model=effective_model,
                max_turns=30,
                ws_mgr=ws_mgr,
                preview_url=_preview_url,
                max_autofix_rounds=3,
            )
        else:
            _agent_event_source = agent.run(
                requirement=effective_requirement,
                conversation_summary=conversation_summary,
                model=effective_model,
                max_turns=30,
            )

        try:
            async for event in _agent_event_source:
```

(The remainder of the loop body — `append_event_to_stream_replay(replay_stream_messages, event)`, `yield event`, `append_agent_event_to_history(...)`, the `agent_tool`/`agent_result`/`agent_thinking`/`agent_thinking_delta`/`agent_done` branches, and the `except (asyncio.CancelledError, Exception): await _persist_output(); raise` — stays unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Command (from repo root):
```
.venv/bin/python -m pytest backend/tests/test_autofix_pipeline_wiring.py -q
```
Expected: `5 passed`.

Then verify no regression in the broader coding pipeline import + existing tests:
```
.venv/bin/python -c "import app.coding.pipeline" && .venv/bin/python -m pytest backend/tests/test_autofix_signals.py backend/tests/test_autofix_driver.py backend/tests/test_autofix_pipeline_wiring.py -q
```
Expected: import succeeds (no syntax/name errors) and `17 passed`.

NOTE (runtime gotcha): `backend/run.py` uses `reload=False`, so this pipeline change does NOT take effect in a running dev/preview backend until the sidecar/backend process is restarted. After committing, restart the backend before any manual/preview verification (e.g. flipping `CODING_AUTOFIX_ENABLED=1` and running a real codegen round). The default (flag unset) keeps `start_serve`/`stop_serve`/deploy/preview paths byte-for-byte unchanged.

- [ ] **Step 5: Commit**

```
git add backend/app/coding/pipeline.py backend/tests/test_autofix_pipeline_wiring.py
git commit -m "feat(coding): wire drive_coding_with_autofix into run_coding_pipeline behind CODING_AUTOFIX_ENABLED flag

flag-gated; default off preserves the existing single-run SSE flow. autofix_round
markers ride the same replay/yield path. requires backend restart (reload=False).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
