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
        self.ctx = SimpleNamespace(input={}, extra={}, workspace_id="ws1")
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
    assert all(
        e.get("dev_url") == "http://127.0.0.1:8080/"
        for e in events if e.get("type") == "autofix_round"
    )


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
