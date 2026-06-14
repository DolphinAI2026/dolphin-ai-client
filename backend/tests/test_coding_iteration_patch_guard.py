"""Coding iteration guardrails: existing workspaces must be patched, not regenerated.

Phase 5 扩展：
- _compute_changed_line_ratio / _check_big_rewrite_warning 阈值守卫单元测试
- prompt 含"补丁优先"语义验证
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.agents.coding.agent import CodingAgent, NUDGE_CONSECUTIVE_READS_THRESHOLD
from app.agents.coding.tools import build_coding_tools
from app.agents.coding.prompts import build_user_prompt
from app.agents.types import AgentContext, TraceEventType


def test_form_page_iteration_prompt_requires_patch_first_edits():
    prompt = build_user_prompt(
        requirement="接口调用写错了，帮我改成 this.$request 的 asyncThen 写法",
        conversation_summary="User: 首次生成门户展示页\nAssistant: 已完成门户展示页",
        workspace_info={
            "project_type": "form-page",
            "project_name": "form-page-portal-showcase-page",
        },
        workspace_path=Path("/tmp/form-page-portal-showcase-page__1_abc"),
        is_iteration=True,
    )

    assert "迭代修改模式" in prompt
    assert "保留现有页面" in prompt
    assert "edit_file" in prompt
    assert "不要 write_file 整份重写" in prompt
    assert "只有新增文件或用户明确要求重写" in prompt


@pytest.mark.asyncio
async def test_iteration_nudge_prefers_edit_file_not_full_rewrite():
    ctx = AgentContext(
        session_id="s",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="gpt-5.5",
        workspace_id="ws-1",
        input={"is_iteration": True},
    )
    agent = CodingAgent(ctx)
    agent._consecutive_reads = NUDGE_CONSECUTIVE_READS_THRESHOLD

    traces: list[tuple[TraceEventType, dict]] = []

    async def fake_trace(event_type: TraceEventType, data: dict):
        traces.append((event_type, data))

    agent._trace = fake_trace  # type: ignore[method-assign]

    await agent.on_each_turn(3)

    nudge = agent._messages[-1]["content"]
    assert "edit_file" in nudge
    assert "write_file to create/update ALL component files" not in nudge
    assert "只修改必要片段" in nudge
    assert traces and traces[0][0] == TraceEventType.NUDGE


@pytest.mark.asyncio
async def test_iteration_write_file_rejects_existing_file_overwrite(tmp_path, monkeypatch):
    existing = tmp_path / "src" / "form-page" / "portal.vue"
    existing.parent.mkdir(parents=True)
    existing.write_text("<template><div>old</div></template>\n", encoding="utf-8")

    monkeypatch.setattr("app.agents.coding.tools._resolve_workspace_path", lambda ctx: tmp_path)

    ctx = AgentContext(
        session_id="s",
        conversation_id=1,
        user_id=1,
        tenant_id=1,
        model="gpt-5.5",
        workspace_id="ws-1",
        input={
            "is_iteration": True,
            "requirement": "接口调用写错了，帮我改成 this.$request 的 asyncThen 写法",
        },
    )
    write_tool = next(t for t in build_coding_tools() if t.name == "write_file")

    result = await write_tool.execute({
        "file_path": "src/form-page/portal.vue",
        "content": "<template><div>new layout</div></template>\n",
    }, ctx)

    assert not result.success
    assert "edit_file" in result.content
    assert "不要 write_file 整份重写" in result.content
    assert existing.read_text(encoding="utf-8") == "<template><div>old</div></template>\n"


# ────────────────────────────────────────────────────────────────
# Phase 5 新增：prompt 含"补丁优先"语义验证
# ────────────────────────────────────────────────────────────────

def test_coding_system_prompt_contains_patch_first():
    """app/coding/prompts.py AGENT_SYSTEM_PROMPT 含补丁优先关键词。"""
    from app.coding.prompts import AGENT_SYSTEM_PROMPT

    assert "edit_file" in AGENT_SYSTEM_PROMPT
    assert "补丁" in AGENT_SYSTEM_PROMPT
    assert "write_file" in AGENT_SYSTEM_PROMPT
    assert "征得用户确认" in AGENT_SYSTEM_PROMPT


def test_agents_coding_patch_first_section_exists():
    """app/agents/coding/prompts._PATCH_FIRST_SECTION 含核心语义。"""
    from app.agents.coding import prompts as p

    section = p._PATCH_FIRST_SECTION
    assert "edit_file" in section
    assert "补丁" in section
    assert "write_file" in section
    assert "征得用户确认" in section


def test_build_user_prompt_includes_patch_first():
    """build_user_prompt 输出含补丁优先段。"""
    prompt = build_user_prompt(
        requirement="给组件加个时间选择器",
        conversation_summary="",
        workspace_info={"project_type": "form-component-dual", "files": []},
        workspace_path=Path("/tmp/fake_ws"),
    )
    assert "补丁" in prompt
    assert "edit_file" in prompt
    assert "write_file" in prompt


# ────────────────────────────────────────────────────────────────
# Phase 5 新增：_compute_changed_line_ratio 单元测试
# ────────────────────────────────────────────────────────────────

def test_compute_changed_line_ratio_identical():
    from app.agents.coding.tools import _compute_changed_line_ratio

    text = "line1\nline2\nline3\n"
    assert _compute_changed_line_ratio(text, text) == 0.0


def test_compute_changed_line_ratio_completely_different():
    from app.agents.coding.tools import _compute_changed_line_ratio

    existing = "\n".join(f"old_{i}" for i in range(20)) + "\n"
    new = "\n".join(f"new_{i}" for i in range(20)) + "\n"
    ratio = _compute_changed_line_ratio(existing, new)
    assert ratio > 0.90


def test_compute_changed_line_ratio_small_change():
    from app.agents.coding.tools import _compute_changed_line_ratio

    lines = [f"line_{i}" for i in range(20)]
    existing = "\n".join(lines) + "\n"
    lines[0] = "changed_line_0"
    new = "\n".join(lines) + "\n"
    ratio = _compute_changed_line_ratio(existing, new)
    assert ratio < 0.20


def test_compute_changed_line_ratio_both_empty():
    from app.agents.coding.tools import _compute_changed_line_ratio

    assert _compute_changed_line_ratio("", "") == 0.0


# ────────────────────────────────────────────────────────────────
# Phase 5 新增：_check_big_rewrite_warning 阈值守卫
# ────────────────────────────────────────────────────────────────

def _make_file(ws: Path, rel: str, lines: int = 20, prefix: str = "existing") -> str:
    target = ws / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(f"{prefix}_{i}" for i in range(lines)) + "\n", encoding="utf-8")
    return rel


def test_big_rewrite_warning_triggers_over_threshold():
    """write_file + 已有文件(≥10行) + >50% 差异 → 触发软警告。"""
    from app.agents.coding.tools import _check_big_rewrite_warning

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        rel = _make_file(ws, "src/Component.vue", lines=20)
        new_content = "\n".join(f"completely_different_{i}" for i in range(20)) + "\n"

        warning = _check_big_rewrite_warning("write_file", {"file_path": rel, "content": new_content}, ws)

        assert warning is not None, "大幅重写应触发软警告"
        assert "补丁守卫" in warning
        assert rel in warning
        assert "已完成" in warning   # 说明是软警告，写入已完成


def test_big_rewrite_warning_not_triggered_under_threshold():
    """write_file + 已有文件 + <50% 差异 → 不触发。"""
    from app.agents.coding.tools import _check_big_rewrite_warning

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        lines = [f"line_{i}" for i in range(20)]
        rel = "src/Component.vue"
        (ws / "src").mkdir()
        (ws / rel).write_text("\n".join(lines) + "\n", encoding="utf-8")
        lines[0] = "slightly_changed"
        new_content = "\n".join(lines) + "\n"

        warning = _check_big_rewrite_warning("write_file", {"file_path": rel, "content": new_content}, ws)
        assert warning is None


def test_big_rewrite_warning_not_triggered_new_file():
    """write_file + 文件不存在（新建）→ 不触发。"""
    from app.agents.coding.tools import _check_big_rewrite_warning

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        new_content = "\n".join(f"line_{i}" for i in range(30)) + "\n"

        warning = _check_big_rewrite_warning("write_file", {"file_path": "src/New.vue", "content": new_content}, ws)
        assert warning is None


def test_big_rewrite_warning_not_triggered_edit_file():
    """edit_file 工具 → 不触发守卫。"""
    from app.agents.coding.tools import _check_big_rewrite_warning

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        rel = _make_file(ws, "src/Component.vue", lines=20)
        new_content = "\n".join(f"new_{i}" for i in range(20)) + "\n"

        warning = _check_big_rewrite_warning("edit_file", {"file_path": rel, "content": new_content}, ws)
        assert warning is None


def test_big_rewrite_warning_not_triggered_short_file():
    """write_file + 已有文件但行数 < 10 → 不触发。"""
    from app.agents.coding.tools import _check_big_rewrite_warning

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        rel = _make_file(ws, "src/tiny.json", lines=5)
        new_content = "\n".join(f"diff_{i}" for i in range(5)) + "\n"

        warning = _check_big_rewrite_warning("write_file", {"file_path": rel, "content": new_content}, ws)
        assert warning is None


def test_big_rewrite_warning_robustness_empty_args():
    """参数为空/None → 不抛异常，返回 None。"""
    from app.agents.coding.tools import _check_big_rewrite_warning

    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        assert _check_big_rewrite_warning("write_file", {}, ws) is None
        assert _check_big_rewrite_warning("write_file", {"file_path": None}, ws) is None
