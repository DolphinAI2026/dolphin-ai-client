"""brainstorm 确认门 — 行为测试(2026-06:B3 去门已被产品决定反转,重新加回门)

历史:B3 曾去掉强制 brainstorm 确认门(首条消息直接 codegen)。
现状:用户明确要求「输出 SPEC 之后,也得确认一下再去开发,而不是一股脑直接开发」,
      门重新加回。本测试断言**新**行为:

断言:首条消息命中 BRAINSTORM_SCENES 且输出的是 SPEC(非澄清)时,pipeline 在 brainstorm
      步骤后 emit done{waiting_confirmation:True} 并 return,**不**继续到 create_workspace。

策略:
- mock `_generate_brainstorm_proposal` 返回假 SPEC(以「## 开发 SPEC」开头,非澄清 `## 🤔`)
- mock `_detect_scene_llm_call` 返回命中 BRAINSTORM_SCENES 的场景
- mock `classify_coding_intent` 返回 BUILD(走 codegen 意图,不被读路径截走)
- mock `resolve_effective_coding_model` 避免 DB 依赖
- 收集所有 yield 事件,断言:
    1. 存在 waiting_confirmation == True 的 done 事件(确认门生效)
    2. **不存在** step=create_workspace 事件(流程停在门前,没建工作区)
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.coding.pipeline import (
    BRAINSTORM_SCENES,
    PipelineParams,
    run_coding_pipeline,
)


# ---------- helpers ----------

async def _collect(gen: AsyncIterator[dict]) -> list[dict]:
    """Drain async generator into a list."""
    events: list[dict] = []
    async for ev in gen:
        events.append(ev)
    return events


def _fake_db():
    """Minimal async DB mock that satisfies the pipeline's DB calls."""
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # no existing conversation
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------- the test ----------

# Pick one scene that's in BRAINSTORM_SCENES
_BRAINSTORM_SCENE = next(iter(BRAINSTORM_SCENES))


@pytest.mark.asyncio
async def test_first_message_brainstorm_scene_gates_on_confirmation():
    """首条 brainstorm-scene 消息出 SPEC 后应 emit waiting_confirmation=True 并停住(确认门)。

    门生效:流程在 brainstorm 步骤后 emit done{waiting_confirmation:True} 并 return,
            create_workspace 不被触发(等用户确认后的续轮才建工作区 + codegen)。
    """
    params = PipelineParams(
        message="帮我做一个请假申请表单组件",
        user_id=1,
        tenant_id=1,
        workspace_id=None,   # 首条消息，非迭代
        conversation_id=None,
    )
    db = _fake_db()

    # 以「## 开发 SPEC」开头 → _looks_like_clarification=False → 走 SPEC + 确认门(非澄清门)
    fake_proposal = "## 开发 SPEC\n**组件名称**：请假申请（`leave-request`）"

    with (
        patch(
            "app.coding.pipeline._detect_scene_llm_call",
            new=AsyncMock(return_value=_BRAINSTORM_SCENE),
        ),
        patch(
            "app.coding.pipeline.classify_coding_intent",
            new=AsyncMock(return_value="BUILD"),
        ),
        patch(
            "app.coding.pipeline._generate_brainstorm_proposal",
            new=AsyncMock(return_value=fake_proposal),
        ),
        patch(
            "app.coding.pipeline.resolve_effective_coding_model",
            new=AsyncMock(return_value=("gpt-4o", 1)),
        ),
        patch(
            "app.coding.pipeline.save_coding_message",
            new=AsyncMock(),
        ),
        patch(
            "app.coding.pipeline.get_conversation_history",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.coding.pipeline.WorkspaceManager.create_workspace",
            return_value={
                "id": "ws-test-001",
                "project_name": "leave-request",
                "display_name": "请假申请",
                "ide_url": "http://localhost:8080",
            },
        ),
        patch(
            "app.coding.pipeline.WorkspaceManager.get_workspace_info",
            return_value={},
        ),
        patch(
            "app.coding.pipeline.extract_project_name",
            new=AsyncMock(return_value="leave-request"),
        ),
        patch(
            "app.coding.pipeline.append_event_to_stream_replay",
        ),
    ):
        events = await _collect(run_coding_pipeline(params, db))

    # ── Assert 1: 确认门生效 —— 有 waiting_confirmation=True 的 done 事件 ──
    gating_events = [e for e in events if e.get("waiting_confirmation") is True]
    assert gating_events, (
        "Pipeline 没有 emit waiting_confirmation=True —— 确认门未生效(SPEC 后应停住等确认)。\n"
        f"All events: {events}"
    )

    # ── Assert 2: 没有 create_workspace —— 流程停在门前,没建工作区 ──
    ws_steps = [
        e for e in events
        if e.get("type") == "step" and e.get("step") == "create_workspace"
    ]
    assert not ws_steps, (
        "Pipeline 触发了 create_workspace —— 确认门应在建工作区前就 return。\n"
        f"All events: {events}"
    )
