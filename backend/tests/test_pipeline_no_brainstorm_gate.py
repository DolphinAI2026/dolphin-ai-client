"""B3: 去掉强制 brainstorm 确认门 — 行为测试

断言：首条消息命中 BRAINSTORM_SCENES 时，pipeline **不**在 brainstorm 步骤
提前 return（waiting_confirmation=True），而是继续到 create_workspace 步骤。

策略：
- mock `_generate_brainstorm_proposal` 返回假提案（跳过 LLM 调用）
- mock `_detect_scene_llm_call` 返回命中 BRAINSTORM_SCENES 的场景
- mock `resolve_effective_coding_model` 避免 DB 依赖
- mock `WorkspaceManager.create_workspace` 避免文件系统写入
- mock `CodingAgentStreamAdapter` 返回一个空异步生成器（跳过代码生成）
- 收集所有 yield 的事件，断言：
    1. 没有任何事件的 waiting_confirmation == True
    2. 存在 step=create_workspace 事件（证明流程过了门）
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.coding.pipeline import (
    BRAINSTORM_SCENES,
    PipelineParams,
    SceneType,
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

    # execute → result.scalar_one_or_none() → None  (no existing conversation)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class _EmptyAgentStream:
    """Async-iterable that yields nothing (simulates agent finishing instantly)."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


# ---------- the test ----------

# Pick one scene that's in BRAINSTORM_SCENES
_BRAINSTORM_SCENE = next(iter(BRAINSTORM_SCENES))


@pytest.mark.asyncio
async def test_first_message_brainstorm_scene_does_not_gate():
    """首条 brainstorm-scene 消息不应 emit waiting_confirmation=True 然后 return。

    去门前：流程在 brainstorm 步骤后 emit done{waiting_confirmation:True} 并 return，
            create_workspace 永远不会被触发。
    去门后：流程继续，create_workspace 被触发（即使 brainstorm inline 提示已输出）。
    """
    params = PipelineParams(
        message="帮我做一个请假申请表单组件",
        user_id=1,
        tenant_id=1,
        workspace_id=None,   # 首条消息，非迭代
        conversation_id=None,
    )
    db = _fake_db()

    fake_proposal = "## 开发 SPEC\n**组件名称**：请假申请（`leave-request`）"

    with (
        patch(
            "app.coding.pipeline._detect_scene_llm_call",
            new=AsyncMock(return_value=_BRAINSTORM_SCENE),
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
        # Skip actual agent / codegen entirely
        patch(
            "app.agents.coding.CodingAgentStreamAdapter",
            return_value=_EmptyAgentStream(),
        ),
        patch(
            "app.agents.coding.CodingAgent",
            return_value=MagicMock(),
        ),
        patch(
            "app.agents.coding.llm_config.load_coding_llm_config",
            new=AsyncMock(return_value=("http://fake", "fake-key", "gpt-4o")),
        ),
        patch(
            "app.services.prompt_resolver.resolve_prompt",
            new=AsyncMock(return_value="system prompt"),
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

    # ── Assert 1: no waiting_confirmation=True anywhere ──
    gating_events = [e for e in events if e.get("waiting_confirmation") is True]
    assert gating_events == [], (
        f"Pipeline emitted waiting_confirmation=True — brainstorm gate still active.\n"
        f"Gating events: {gating_events}"
    )

    # ── Assert 2: create_workspace was triggered (flow passed the gate) ──
    ws_steps = [
        e for e in events
        if e.get("type") == "step" and e.get("step") == "create_workspace"
    ]
    assert ws_steps, (
        "Pipeline did not reach create_workspace step — flow may still be gated.\n"
        f"All events: {events}"
    )
