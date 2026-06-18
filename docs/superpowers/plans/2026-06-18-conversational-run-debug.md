# 对话驱动「运行/调试」实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「运行/调试」从手动 tab+按钮改成对话驱动——coding agent 在对话里起 dev server+抓错并以「运行结果」卡 + 对话驱动预览位呈现;顺带删掉手动 capture 路径(登录跳转 bug 的根源)。

**Architecture:** 新增 coding agent 工具 `run_workspace_preview`(进程内调 WorkspaceManager/BrowserService,经 `ToolResult.emit_event` 发 `coding.run_result` 事件);默认开启 C5 自愈(改完一轮自动验证,沿用 `drive_coding_with_autofix` 的 `autofix_round` 事件);前端把 `run_result` 与 `autofix_round` 两类事件归一成一张卡 + 写进 coding store 的 `activePreview`,RunDebugPanel 改成读 `activePreview` 的对话驱动预览位。删除 `/browser/capture/*` 路由与前端 capture endpoints(死码)。

**Tech Stack:** 后端 Python 3.13 / FastAPI / asyncio / Playwright(进程内,打包排除则降级);前端 Vue 3 + TS + Pinia + vitest。

## Global Constraints

- 后端 `reload=False`:改后端必须重启 sidecar/backend 进程才生效(pytest 是 fresh app,不受影响)。
- 本地 DB = SQLite;`.venv` = Python 3.13;后端测试从 `backend/` 跑 `.venv/bin/python -m pytest`;前端从 `frontend/` 跑 `npx vitest run`。
- 复用 SP1 引擎:C1 `WorkspaceManager.start_serve(ws_id, kind="web")→{status,port,message}` / `_serve_processes[ws_id]["log_ring"]`;C2 `BrowserService.get_instance().launch_capture(url,headless=True)→session_id` / `.get_console_logs(sid,after)` / `.get_network_requests(sid,after)` / `.close_capture(sid)`;C5 `drive_coding_with_autofix`;signals `collect_runtime_errors(console,network)→list[str]`。
- 打包 sidecar 排除 playwright(`ruijing-sidecar.spec` excludes,无法冻结)→ 包内 CDP 抓取降级:`capture_available=false` 贯穿前后端,卡片/预览位标「运行时抓取不可用(需 dev 模式)」。
- 新 agent 工具**必须**加 `backend/tool_registry.yaml` entry 且 `agents:` 含 `coding`(否则 agent 不可见,见项目记忆)。
- `ToolResult.content` 是给 LLM 看的:失败必须以 `Error: ` 前缀;`ToolResult.data` 不进 LLM;自定义 SSE 走 `ToolResult.emit_event`(BaseAgent 会发布,adapter 把 `coding.X` 拍平成 `{type:"X", ...data}`)。
- 频繁提交:每个 Task 末尾 commit,message 末尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

### run_result 契约(前端归一后的统一形状,所有 task 引用)

```ts
interface RunResult {
  source: 'manual' | 'autofix'
  dev_url: string            // '' 表示没起来
  status: 'running' | 'ok' | 'error'  // ok=编译通过/无错; error=有 build/运行时报错
  log_tail: string[]         // serve 日志尾(manual 带, autofix 可空)
  errors: string[]           // build + 运行时报错合并
  capture_available: boolean // 包内 playwright 排除时 false
  round: number | null       // autofix 轮次; manual 为 null
}
```

后端两个来源:
- on-request 工具发 `coding.run_result` → adapter 拍平成 `{type:'run_result', source:'manual', dev_url, status, log_tail, errors, capture_available}`。
- C5 发 `autofix_round`(已存在)`{type:'autofix_round', round, status:'verifying'|'clean'|'fixing'|'repeated'|'exhausted', errors, dev_url, tokens_input, tokens_output}`(本计划给它补 `dev_url`)。

前端 `normalizeRunResult(ev)` 把两者归一成上面的 `RunResult`。

---

## Task 1: 后端 — `run_workspace_preview` agent 工具

**Files:**
- Modify: `backend/app/agents/coding/tools.py`（加模块级 executor `_run_workspace_preview` + 在 `build_coding_tools()` 注册）
- Modify: `backend/tool_registry.yaml`（加 entry）
- Modify: `backend/app/agents/coding/agent.py:26-35`（TOOL_ICONS 加一项）
- Test: `backend/tests/test_run_workspace_preview_tool.py`（Create）

**Interfaces:**
- Consumes: `WorkspaceManager.start_serve(ws_id, kind)`、`WorkspaceManager._serve_processes[ws_id]["log_ring"]`、`BrowserService.get_instance().launch_capture/get_console_logs/get_network_requests/close_capture`、`collect_runtime_errors`（C5 signals）、`ToolResult`（`app.agents.types`）、`AgentContext`。
- Produces: 工具 `run_workspace_preview`（agent 可调）；`coding.run_result` emit_event（data 形状见契约 source='manual'）；模块级 `async def _run_workspace_preview(args: dict, ctx) -> ToolResult` 供单测直调。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_run_workspace_preview_tool.py
"""C(对话化) run_workspace_preview 工具单测：不起真实进程/浏览器。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.agents.coding.tools as tmod
from app.agents.coding.tools import _run_workspace_preview


def _ctx(ws_id="ws1"):
    return SimpleNamespace(workspace_id=ws_id, publisher=None, db=None,
                           conversation_id="c1", user_id=1, tenant_id=1, extra={})


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
    monkeypatch.setattr(tmod, "WorkspaceManager", lambda: _WS({"status": "ok", "port": 8081, "message": ""}))
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
    monkeypatch.setattr(tmod, "WorkspaceManager", lambda: _WS({"status": "ok", "port": 8081, "message": ""}))
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
    monkeypatch.setattr(tmod, "WorkspaceManager", lambda: _WS({"status": "error", "message": "无 Node"}))
    res = await _run_workspace_preview({}, _ctx())
    assert res.success is False
    assert "无 Node" in res.content
    assert res.emit_event["data"]["status"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_run_workspace_preview_tool.py -q`
Expected: `ImportError: cannot import name '_run_workspace_preview'`（模块尚无该函数）。

- [ ] **Step 3: Write minimal implementation**

在 `backend/app/agents/coding/tools.py` 顶部 import 区确认有 `from app.agents.types import ToolResult`（无则加）。加一个间接取 BrowserService 的壳(便于测试 monkeypatch)和工具 executor（放在 `build_coding_tools` 定义之前的模块级）：

```python
def _get_browser_service_for_preview():
    """间接取 BrowserService，CDP 不可用时由调用方 try/except 降级。"""
    from app.coding.browser_service import BrowserService
    return BrowserService.get_instance()


async def _run_workspace_preview(args, ctx) -> ToolResult:
    """起 dev server + (有 CDP 时) 抓运行时报错，发 coding.run_result 事件供对话卡/预览位用。"""
    import asyncio
    from app.coding.workspace import WorkspaceManager
    from app.agents.coding.autofix_signals import collect_runtime_errors

    ws_id = getattr(ctx, "workspace_id", None)
    if not ws_id:
        return ToolResult(success=False, content="Error: 当前没有工作区，无法运行预览", error="NO_WORKSPACE_ID")

    kind = (args or {}).get("kind", "web")
    ws_mgr = WorkspaceManager()
    serve = await ws_mgr.start_serve(ws_id, kind=kind)
    if serve.get("status") == "error":
        msg = serve.get("message", "启动失败")
        return ToolResult(
            success=False, content=f"Error: dev server 启动失败: {msg}", error="SERVE_FAILED",
            emit_event={"type": "coding.run_result", "data": {
                "source": "manual", "dev_url": "", "status": "error",
                "log_tail": [], "errors": [msg], "capture_available": False}},
        )

    port = serve.get("port")
    dev_url = f"http://127.0.0.1:{port}/" if port else ""
    info = ws_mgr._serve_processes.get(ws_id, {}) or {}
    log_tail = [r["line"] for r in (info.get("log_ring") or [])][-30:]

    errors: list[str] = []
    capture_available = False
    if dev_url:
        try:
            svc = _get_browser_service_for_preview()
            session_id = await svc.launch_capture(dev_url)
            capture_available = True
            await asyncio.sleep(1.5)  # 让首屏 console/network 报错冒出来
            console = svc.get_console_logs(session_id, 0) or []
            network = svc.get_network_requests(session_id, 0) or []
            errors = collect_runtime_errors(console, network)
            await svc.close_capture(session_id)
        except Exception:
            capture_available = False  # 包内 playwright 排除 → 降级为仅预览

    status = "error" if errors else "ok"
    note = f"{len(errors)} 个运行时报错" if errors else ("无报错" if capture_available else "运行时抓取不可用(需 dev 模式)")
    return ToolResult(
        success=True,
        content=f"dev server 运行在 {dev_url}；{note}。",
        data={"dev_url": dev_url, "errors": errors},
        emit_event={"type": "coding.run_result", "data": {
            "source": "manual", "dev_url": dev_url, "status": status,
            "log_tail": log_tail, "errors": errors, "capture_available": capture_available}},
    )
```

在 `build_coding_tools()` 里把它注册进工具列表（紧跟其它 platform/workspace 工具的注册处，照 `_make_platform_executor` 的登记方式——把 `run_workspace_preview` 名字映射到 `_run_workspace_preview` executor；执行器签名已是 `(args, ctx)`，直接登记即可，不要走 `_make_base_executor`）。最小登记（在该函数返回 tools 列表前）：

```python
    tools.append({
        "type": "function",
        "function": {
            "name": "run_workspace_preview",
            "description": "起当前工作区的 dev server 并(可用时)抓运行时 console/network 报错；用于在对话里『跑一下/调一下』。返回 dev 预览地址与报错。",
            "parameters": {
                "type": "object",
                "properties": {"kind": {"type": "string", "enum": ["web", "mobile", "h5"], "description": "serve 类型，默认 web"}},
            },
        },
        "executor": _run_workspace_preview,
    })
```

> 注：若 `build_coding_tools` 的工具项结构不是 `{type,function,executor}` 这种内联 executor 形态，而是分离的「定义 + executor 注册表」，则按该文件现有 platform 工具的登记方式登记同一对 (name, _run_workspace_preview)——实现时对照 `_make_platform_executor` 的实际登记代码套用，保持与既有 platform 工具一致。

在 `backend/tool_registry.yaml` 加 entry（对齐现有 coding 工具项格式）：

```yaml
  run_workspace_preview:
    sections: [extension]
    agents: [coding]
    category: dev_workspace
    description: 起 dev server 并抓运行时报错，用于对话里运行/调试预览
    writes_workspace: false
```

在 `backend/app/agents/coding/agent.py` 的 `TOOL_ICONS`（26-35 行）加一项：

```python
    "run_workspace_preview": "🐞 运行/调试",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_run_workspace_preview_tool.py -q`
Expected: `4 passed`。
再跑注册表漂移自检不报新错：`.venv/bin/python -c "import app.agents.coding.tools; import app.mcp_server; print('ok')"` 打印 `ok`。

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/agents/coding/tools.py backend/tool_registry.yaml backend/app/agents/coding/agent.py backend/tests/test_run_workspace_preview_tool.py
git commit -m "feat(coding): add run_workspace_preview agent tool (起 serve+抓错, 发 run_result)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: 后端 — 默认开 C5 自愈 + 给 autofix_round 补 dev_url

**Files:**
- Modify: `backend/app/coding/pipeline.py`（`_autofix_enabled` 默认改开）
- Modify: `backend/app/agents/coding/autofix_driver.py`（每个 `autofix_round` 事件加 `dev_url`）
- Test: `backend/tests/test_autofix_pipeline_wiring.py`（改默认断言）、`backend/tests/test_autofix_driver.py`（加 dev_url 断言）

**Interfaces:**
- Consumes: 现有 `_autofix_enabled()`、`drive_coding_with_autofix(... preview_url=...)`。
- Produces: 默认开启的自愈;`autofix_round` 事件新增字段 `dev_url`（= driver 的 `preview_url or ""`）。

- [ ] **Step 1: Write the failing test**

改 `backend/tests/test_autofix_pipeline_wiring.py` 里默认关的两个用例为默认开：

```python
def test_autofix_enabled_flag_default_on(monkeypatch):
    monkeypatch.delenv("CODING_AUTOFIX_ENABLED", raising=False)
    assert pipeline_mod._autofix_enabled() is True


def test_autofix_enabled_flag_off_when_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("CODING_AUTOFIX_ENABLED", "0")
    assert pipeline_mod._autofix_enabled() is False
```

（删除原 `test_autofix_enabled_flag_default_off` 与 `test_autofix_enabled_flag_on`，由上面两个取代。）

在 `backend/tests/test_autofix_driver.py` 的 `test_clean_first_round_no_retry` 末尾加一句，断言 autofix_round 事件带 dev_url：

```python
    assert all(
        e.get("dev_url") == "http://127.0.0.1:8080/"
        for e in events if e.get("type") == "autofix_round"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_autofix_pipeline_wiring.py tests/test_autofix_driver.py -q`
Expected: `test_autofix_enabled_flag_default_on` 失败（当前默认 False）；driver 的 dev_url 断言失败（事件无 dev_url 字段）。

- [ ] **Step 3: Write minimal implementation**

在 `backend/app/coding/pipeline.py` 把 `_autofix_enabled` 默认改开（未显式设为 0/false 即开）：

```python
def _autofix_enabled() -> bool:
    """C5 自愈：默认开启;设 CODING_AUTOFIX_ENABLED=0/false 关闭。"""
    import os
    return os.getenv("CODING_AUTOFIX_ENABLED", "1").strip() not in ("0", "false", "False", "")
```

在 `backend/app/agents/coding/autofix_driver.py`，给每个 yield 的 `autofix_round` dict 加 `"dev_url": preview_url or ""`。共 5 处（verifying/clean/repeated/fixing/exhausted），每处的 dict 里加该键。例如 verifying：

```python
        yield {
            "type": "autofix_round", "round": round_index, "status": "verifying",
            "errors": [], "tokens_input": tokens_in, "tokens_output": tokens_out,
            "dev_url": preview_url or "",
        }
```

（其余 clean/repeated/fixing/exhausted 四处同样加 `"dev_url": preview_url or ""`。）

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_autofix_pipeline_wiring.py tests/test_autofix_driver.py -q`
Expected: 全绿（pipeline wiring 5 个 + driver 5 个）。

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/coding/pipeline.py backend/app/agents/coding/autofix_driver.py backend/tests/test_autofix_pipeline_wiring.py backend/tests/test_autofix_driver.py
git commit -m "feat(coding): C5 自愈默认开启 + autofix_round 事件带 dev_url

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 前端 — run_result 归一器 + coding store activePreview + SSE handler

**Files:**
- Create: `frontend/src/views/coding/runResult.ts`（纯归一函数）
- Create: `frontend/src/views/coding/runResult.spec.ts`
- Modify: `frontend/src/stores/coding.ts`（加 `activePreview` ref + export）
- Modify: `frontend/src/views/coding/useStreamMessages.ts:16-46`（StreamMessage 加 `'run_result'` 类型 + 字段）
- Modify: `frontend/src/views/coding/useCodingPipeline.ts:191-346`（sseHandlers 加 `run_result` 与 `autofix_round`）

**Interfaces:**
- Consumes: 契约里的后端两类事件。
- Produces: `normalizeRunResult(ev: any): RunResult`（纯函数）;`RunResult` 类型;coding store 的 `activePreview` ref;StreamMessage 新类型 `'run_result'`（字段 `run?: RunResult`）。

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/views/coding/runResult.spec.ts
import { describe, expect, it } from 'vitest'
import { normalizeRunResult } from './runResult'

describe('normalizeRunResult', () => {
  it('maps a manual run_result event', () => {
    const r = normalizeRunResult({
      type: 'run_result', source: 'manual', dev_url: 'http://127.0.0.1:8081/',
      status: 'error', log_tail: ['App running'], errors: ['[console.error] boom'],
      capture_available: true,
    })
    expect(r.source).toBe('manual')
    expect(r.dev_url).toBe('http://127.0.0.1:8081/')
    expect(r.status).toBe('error')
    expect(r.errors).toEqual(['[console.error] boom'])
    expect(r.capture_available).toBe(true)
    expect(r.round).toBeNull()
  })

  it('maps a C5 autofix_round event (verifying → running)', () => {
    const r = normalizeRunResult({
      type: 'autofix_round', round: 0, status: 'verifying', errors: [],
      dev_url: 'http://127.0.0.1:8080/',
    })
    expect(r.source).toBe('autofix')
    expect(r.status).toBe('running')
    expect(r.round).toBe(0)
    expect(r.dev_url).toBe('http://127.0.0.1:8080/')
  })

  it('maps autofix clean → ok and fixing/exhausted/repeated → error', () => {
    expect(normalizeRunResult({ type: 'autofix_round', round: 1, status: 'clean', errors: [] }).status).toBe('ok')
    expect(normalizeRunResult({ type: 'autofix_round', round: 1, status: 'fixing', errors: ['e'] }).status).toBe('error')
    expect(normalizeRunResult({ type: 'autofix_round', round: 2, status: 'exhausted', errors: ['e'] }).status).toBe('error')
    expect(normalizeRunResult({ type: 'autofix_round', round: 2, status: 'repeated', errors: ['e'] }).status).toBe('error')
  })

  it('defaults missing fields safely', () => {
    const r = normalizeRunResult({ type: 'run_result', source: 'manual' })
    expect(r.dev_url).toBe('')
    expect(r.errors).toEqual([])
    expect(r.log_tail).toEqual([])
    expect(r.capture_available).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/mars/Vibe Coding/ai-builder/frontend" && npx vitest run src/views/coding/runResult.spec.ts`
Expected: `Failed to load url ./runResult`（模块不存在）。

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/views/coding/runResult.ts
// 把后端两类事件(manual run_result / C5 autofix_round)归一成统一 RunResult。
export interface RunResult {
  source: 'manual' | 'autofix'
  dev_url: string
  status: 'running' | 'ok' | 'error'
  log_tail: string[]
  errors: string[]
  capture_available: boolean
  round: number | null
}

const AUTOFIX_STATUS: Record<string, RunResult['status']> = {
  verifying: 'running', clean: 'ok', fixing: 'error', repeated: 'error', exhausted: 'error',
}

export function normalizeRunResult(ev: any): RunResult {
  const errors: string[] = Array.isArray(ev?.errors) ? ev.errors : []
  if (ev?.type === 'autofix_round') {
    return {
      source: 'autofix',
      dev_url: String(ev.dev_url || ''),
      status: AUTOFIX_STATUS[ev.status] || 'running',
      log_tail: [],
      errors,
      capture_available: ev.capture_available ?? false,
      round: typeof ev.round === 'number' ? ev.round : null,
    }
  }
  // manual run_result
  return {
    source: 'manual',
    dev_url: String(ev?.dev_url || ''),
    status: (ev?.status === 'ok' || ev?.status === 'error' || ev?.status === 'running') ? ev.status : 'running',
    log_tail: Array.isArray(ev?.log_tail) ? ev.log_tail : [],
    errors,
    capture_available: ev?.capture_available ?? false,
    round: null,
  }
}
```

在 `frontend/src/stores/coding.ts` 的 reactive 区（约 43-68 行）加 activePreview，并在 store 的 `return {...}` 里导出：

```ts
  const activePreview = ref<{
    dev_url: string; status: string; errors: string[]; capture_available: boolean; round: number | null
  } | null>(null)
```

（`return { ... }` 末尾补 `activePreview`。）

在 `frontend/src/views/coding/useStreamMessages.ts` 的 `StreamMessage` 接口（16-46 行）：`type` 联合加 `'run_result'`，并加字段 `run?: import('./runResult').RunResult`。

在 `frontend/src/views/coding/useCodingPipeline.ts` 的 `sseHandlers`（191-346 行）加两个 handler（顶部 import `normalizeRunResult` 与 coding store）。两者都归一→加一条 `run_result` 流消息 + 写 store.activePreview：

```ts
  run_result: (parsed: any) => {
    const r = normalizeRunResult(parsed)
    addStreamMsg({ type: 'run_result', content: '', run: r })
    codingStore.activePreview = { dev_url: r.dev_url, status: r.status, errors: r.errors, capture_available: r.capture_available, round: r.round }
  },
  autofix_round: (parsed: any) => {
    const r = normalizeRunResult(parsed)
    addStreamMsg({ type: 'run_result', content: '', run: r })
    if (r.dev_url) codingStore.activePreview = { dev_url: r.dev_url, status: r.status, errors: r.errors, capture_available: r.capture_available, round: r.round }
    else if (codingStore.activePreview) codingStore.activePreview = { ...codingStore.activePreview, status: r.status, errors: r.errors, round: r.round }
  },
```

（`codingStore` 用现有 store 实例;若该文件已 `const codingStore = useCodingStore()` 则复用,否则在 setup 区引入。）

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/mars/Vibe Coding/ai-builder/frontend" && npx vitest run src/views/coding/runResult.spec.ts`
Expected: `Tests 4 passed`。
类型检查触及文件不报新错：`npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep -E "runResult\.ts|stores/coding\.ts|useCodingPipeline\.ts|useStreamMessages\.ts" || echo "no new type errors"`，预期打印 `no new type errors`。

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add frontend/src/views/coding/runResult.ts frontend/src/views/coding/runResult.spec.ts frontend/src/stores/coding.ts frontend/src/views/coding/useStreamMessages.ts frontend/src/views/coding/useCodingPipeline.ts
git commit -m "feat(coding): run_result 归一器 + activePreview store + SSE handler

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 前端 — 对话流「运行结果」卡

**Files:**
- Modify: `frontend/src/views/CodingPage.vue`（`agentMessages` computed ~960-1010 加 `run_result` 分支;`#custom` slot ~182-209 加渲染;replay 路径加分支跳过/还原）
- Test: 无前端 SFC 单测 runner —— 走 build:nocheck + preview 验证（见 Step 1）

**Interfaces:**
- Consumes: StreamMessage `type:'run_result'` + `run: RunResult`（Task 3）。
- Produces: 消息流里一张「运行结果」卡（状态/dev_url/报错条数/自愈轮次/「查看预览」）。

- [ ] **Step 1: 基线（无 unit runner，记录改前行为）**

本仓库 vitest 只覆盖纯 `.ts`，SFC 不在内。改前先确认基线：`cd "/Users/mars/Vibe Coding/ai-builder/frontend" && npm run build:nocheck` 成功;`grep -n "run_result" src/views/CodingPage.vue` 无输出（卡尚不存在）。

- [ ] **Step 2: 确认缺口**

`grep -n "msg.type === 'run_result'\|kind: 'run'" src/views/CodingPage.vue` 无输出 —— 确认 agentMessages 尚未处理 run_result。

- [ ] **Step 3: Write minimal implementation**

在 `CodingPage.vue` 的 `agentMessages` computed（约 960-1010）里,仿现有 `file_write`/`command` 走 `custom` kind 的写法,加分支：

```ts
      } else if (msg.type === 'run_result') {
        out.push({ id: 'sm' + i, role: 'assistant', kind: 'custom', content: '', meta: { streamMsg: msg } })
```

在 `#custom`/`streamCustom` slot（约 182-209，从 `meta.streamMsg` 取原始消息）加 run_result 渲染分支（沿用现有卡片类名风格）：

```vue
          <div v-else-if="m.meta?.streamMsg?.type === 'run_result'" class="coding-run-card">
            <div class="rc-head">
              <span class="rc-dot" :class="m.meta.streamMsg.run.status" />
              <span class="rc-title">
                {{ m.meta.streamMsg.run.source === 'autofix' ? `自愈第 ${m.meta.streamMsg.run.round + 1} 轮` : '运行预览' }}
                · {{ rcStatusText(m.meta.streamMsg.run) }}
              </span>
              <button v-if="m.meta.streamMsg.run.dev_url" class="rc-link" @click="focusPreview(m.meta.streamMsg.run)">查看预览</button>
            </div>
            <div v-if="m.meta.streamMsg.run.dev_url" class="rc-url">{{ m.meta.streamMsg.run.dev_url }}</div>
            <ul v-if="m.meta.streamMsg.run.errors.length" class="rc-errs">
              <li v-for="(e, ei) in m.meta.streamMsg.run.errors.slice(0, 5)" :key="ei">{{ e }}</li>
            </ul>
            <div v-if="!m.meta.streamMsg.run.capture_available" class="rc-degrade">运行时抓取不可用(需 dev 模式)</div>
          </div>
```

在 `<script setup>` 加两个小帮手 + 切到预览 tab：

```ts
function rcStatusText(r: any): string {
  if (r.status === 'running') return '运行中…'
  if (r.status === 'ok') return r.capture_available ? '通过，无报错' : '已启动'
  return `${r.errors.length} 个报错`
}
function focusPreview(r: any) {
  if (r.dev_url) codingStore.activePreview = { dev_url: r.dev_url, status: r.status, errors: r.errors, capture_available: r.capture_available, round: r.round }
  wsPaneTab.value = 'run'   // Task 5 后该 tab 即「预览」
}
```

补 `.coding-run-card` 等样式（放 `CodingPage.global.css`，沿用既有卡片 token；`.rc-dot.running{background:var(--text-3)} .rc-dot.ok{background:var(--ok,#3ba55d)} .rc-dot.error{background:var(--err,#e54d42)}` 等）。

replay 还原：在 `restoreReplayStreamMessages`/`parseAssistantHistory` 等按 `msg.type` 分发处，给 `'run_result'` 加一个「原样保留/跳过不崩」的分支（不强制持久化,旧会话无此卡即可）。

- [ ] **Step 4: Verify（build + preview）**

`cd "/Users/mars/Vibe Coding/ai-builder/frontend" && npm run build:nocheck` 成功;`grep -n "coding-run-card" src/views/CodingPage.vue` 有输出。
preview 验证留到 Task 5 一起（卡 + 预览位联动）。

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add frontend/src/views/CodingPage.vue frontend/src/views/CodingPage.global.css
git commit -m "feat(coding): 对话流运行结果卡(状态/URL/报错/查看预览)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 前端 — RunDebugPanel 改成对话驱动「预览位」

**Files:**
- Modify: `frontend/src/views/coding/RunDebugPanel.vue`（删运行/停止按钮+capture 轮询/UI;改读 `codingStore.activePreview`;保留「停止」收 serve;控制台/网络改读 activePreview.errors）
- Modify: `frontend/src/views/CodingPage.vue`（右栏 tab「运行/调试」→「预览」文案）

**Interfaces:**
- Consumes: `codingStore.activePreview`（Task 3）、`codingApi.stopServe`（保留）。
- Produces: 对话驱动的只读预览位（iframe→activePreview.dev_url + 报错列表 + 停止）。

- [ ] **Step 1: 基线**

`grep -nE "captureStart|pollCapture|startServe\(" src/views/coding/RunDebugPanel.vue` —— 记录当前还在调 capture/start（待删）。

- [ ] **Step 2: 确认缺口**

`grep -n "activePreview" src/views/coding/RunDebugPanel.vue` 无输出 —— 确认面板还没接 store。

- [ ] **Step 3: Write minimal implementation**

把 `RunDebugPanel.vue` `<script setup>` 重写为读 store（删 EventSource 日志流由对话承载？——保留 serve-logs 日志流仍可用，但运行/捕获改对话驱动）。最小形态：

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useCodingStore } from '@/stores/coding'
import { codingApi } from '@/api/coding'

const props = defineProps<{ wsId: string; dark?: boolean }>()
const codingStore = useCodingStore()

const preview = computed(() => codingStore.activePreview)
const devUrl = computed(() => preview.value?.dev_url || '')
const errors = computed(() => preview.value?.errors || [])
const captureAvailable = computed(() => preview.value?.capture_available ?? false)

async function stop() {
  if (props.wsId) await codingApi.stopServe(props.wsId).catch(() => {})
  codingStore.activePreview = null
}
</script>
```

模板改为：有 `devUrl` 则 iframe 预览 + 报错列表 + 「停止」;无则空态「在对话里说『跑一下』即可在此预览」。删掉运行按钮、控制台/网络轮询 tab（改成展示 `errors` 列表 + `captureAvailable` 提示）、`captureStart/captureConsole/captureNetwork/captureDevtools` 全部调用与相关 state（`consoleLogs/netLogs/obsTab/pollTimer/es/lastSeq...`）。保留「在 DevTools 打开」可选——但它依赖 capture session（已删）,本版去掉该按钮（DevTools 走 dev 模式）。

```vue
<template>
  <div class="run-debug-panel" :class="{ dark }">
    <div class="rd-toolbar">
      <span class="rd-title">预览</span>
      <span v-if="devUrl" class="rd-url">{{ devUrl }}</span>
      <span class="rd-spacer" />
      <button v-if="devUrl" class="rd-btn" @click="stop">停止</button>
    </div>
    <div class="rd-body">
      <iframe v-if="devUrl" :src="devUrl" class="rd-iframe" />
      <div v-else class="rd-empty">在对话里说「跑一下 / 调一下」，结果会在这里预览</div>
      <div v-if="errors.length" class="rd-errs">
        <div v-for="(e, i) in errors" :key="i" class="rd-err">{{ e }}</div>
      </div>
      <div v-if="devUrl && !captureAvailable" class="rd-degrade">运行时抓取不可用(需 dev 模式)</div>
    </div>
  </div>
</template>
```

（样式可大幅精简;保留 `.rd-iframe{flex:1;width:100%;border:0}` 等必要项。）

在 `CodingPage.vue` 右栏 tab 文案：把「运行/调试」改「预览」（`wsPaneTab === 'run'` 的按钮文案）。`focusPreview`（Task 4）里 `wsPaneTab.value='run'` 仍切到这块,无需改 key。

- [ ] **Step 4: Verify（build + preview 端到端）**

`cd "/Users/mars/Vibe Coding/ai-builder/frontend" && npm run build:nocheck` 成功;`grep -nE "captureStart|pollCapture" src/views/coding/RunDebugPanel.vue` **无输出**（capture 调用已删净）。
preview 验证(dev 模式,后端重启后)：preview_start → 打开一个二次开发组件工作区 → 在对话里发「跑一下」→ 期望:① 不跳登录(captureStart 已无);② 对话出「运行结果」卡;③「预览」tab 的 iframe 加载 dev_url;④ preview_console_logs 无 RunDebugPanel 报错。

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add frontend/src/views/coding/RunDebugPanel.vue frontend/src/views/CodingPage.vue
git commit -m "feat(coding): RunDebugPanel 改对话驱动预览位(删运行按钮+capture, 接 activePreview)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 清理 — 删死掉的 capture HTTP 路由与前端 endpoints

**Files:**
- Modify: `frontend/src/api/coding.ts`（删 `captureStart/captureConsole/captureNetwork/captureDevtools/captureStop`）
- Modify: `backend/app/routes/browser.py`（删 `/capture/*` 5 路由 + `CaptureStartRequest`/`CaptureSessionRequest`）
- Delete: `backend/tests/test_capture_routes.py`
- Test: import + 全量后端/前端测试

**Interfaces:**
- Consumes: 无（删除项）。
- Produces: 更小的 API 面;`BrowserService.launch_capture/...` 保留（Task 1 工具 + C5 进程内调用）。

- [ ] **Step 1: 确认无活引用**

`cd "/Users/mars/Vibe Coding/ai-builder"`：
`grep -rnE "capture(Start|Console|Network|Devtools|Stop)\b" frontend/src` —— 改完 Task 5 后应**只**剩 `coding.ts` 里的定义本身（无调用方）。
`grep -rnE "/capture/(start|console|network|devtools|stop)" frontend backend --include=*.ts --include=*.py --include=*.vue | grep -v test_capture_routes` —— 应只剩 browser.py 的路由定义。

- [ ] **Step 2: 基线测试**

`cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -m pytest tests/test_capture_routes.py -q` —— 当前应 4 passed（删前基线）。

- [ ] **Step 3: 删除**

- `frontend/src/api/coding.ts`：删 `captureStart/captureConsole/captureNetwork/captureDevtools/captureStop` 五个方法（保留 `serveLogsUrl`、`startServe`、`stopServe`、`customPageDevTarget`、`getServeStatus`）。
- `backend/app/routes/browser.py`：删 `CaptureStartRequest`、`CaptureSessionRequest` 两个 model，删 `@router.post("/capture/start")`、`@router.get("/capture/console")`、`@router.get("/capture/network")`、`@router.post("/capture/devtools")`、`@router.post("/capture/stop")` 五个路由函数。保留 `BrowserService` import 与其余 `/browser/*` 路由不动。
- `rm backend/tests/test_capture_routes.py`。

- [ ] **Step 4: Verify**

`cd "/Users/mars/Vibe Coding/ai-builder/backend" && .venv/bin/python -c "import app.routes.browser; import app.main; print('ok')"` 打印 `ok`。
`.venv/bin/python -m pytest -q` —— 全绿（test_capture_routes 已删,其余不破;`test_browser_capture.py`/`test_autofix_*` 仍在,因为 BrowserService 方法保留）。
`cd ../frontend && npx vitest run && npm run build:nocheck` —— 全绿 + 构建成功。

- [ ] **Step 5: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add frontend/src/api/coding.ts backend/app/routes/browser.py
git rm backend/tests/test_capture_routes.py
git commit -m "chore(coding): 删手动 capture HTTP 路由+前端 endpoints(对话驱动后死码, 登录 403 根除)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## 实现顺序

T1(工具) → T2(开 C5 + dev_url) → T3(归一器+store+handler) → T4(运行结果卡) → T5(预览位改造) → T6(清理)。

T1–T3 可独立测;T4/T5 走 build + dev 模式 preview 验证;T6 收尾删死码。登录 bug 在 T5(删 captureStart 调用) + T6(删路由)后根除。
