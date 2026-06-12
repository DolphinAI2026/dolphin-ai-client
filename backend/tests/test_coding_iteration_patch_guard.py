"""Coding iteration guardrails: existing workspaces must be patched, not regenerated."""
from __future__ import annotations

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
