"""澄清门(2026-06)— 行为测试

需求:Coding 出 SPEC 前,若需求不清晰先问澄清问题(选项/自由输入),不一股脑直接写 SPEC/开发。

覆盖:
- _looks_like_clarification:`## 🤔` 开头 → 澄清;否则(含「## 开发 SPEC」)→ 非澄清(默认走 SPEC)
- _get_pending_clarification:最后一条 assistant 带 CLARIFY marker → (澄清文本, 首条用户消息);否则 (None,None)
- _count_clarify_rounds:统计历史中澄清轮数
- pipeline 集成:grounded 返回 `## 🤔` 澄清 → emit waiting_clarification、不建工作区、存 CLARIFY marker
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.coding.pipeline import (
    BRAINSTORM_SCENES,
    BRAINSTORM_PROPOSAL_MARKER,
    CLARIFY_PROPOSAL_MARKER,
    PipelineParams,
    _count_clarify_rounds,
    _get_pending_clarification,
    _looks_like_clarification,
    run_coding_pipeline,
)


# ---------- 单元:判定与状态恢复 ----------

def test_looks_like_clarification():
    assert _looks_like_clarification("## 🤔 开始前,先和你对齐几点\n1. ...") is True
    assert _looks_like_clarification("  \n## 🤔 对齐") is True   # 允许前导空白
    assert _looks_like_clarification("## 📋 开发 SPEC 确认\n...") is False
    assert _looks_like_clarification("## 开发 SPEC\n...") is False
    assert _looks_like_clarification("") is False
    assert _looks_like_clarification(None) is False  # type: ignore[arg-type]


def test_get_pending_clarification_recovers_state():
    history = [
        {"role": "user", "content": "给商机做一个看板"},          # 原始需求(首条)
        {"role": "assistant", "content": CLARIFY_PROPOSAL_MARKER + "## 🤔 按什么分列?A 阶段 B 负责人"},
    ]
    text, original = _get_pending_clarification(history)
    assert text == "## 🤔 按什么分列?A 阶段 B 负责人"
    assert original == "给商机做一个看板"   # 取首条用户消息,而非澄清那句


def test_get_pending_clarification_none_when_last_is_normal_or_spec():
    # 最后一条是普通 assistant → 非等待澄清态
    assert _get_pending_clarification(
        [{"role": "user", "content": "x"}, {"role": "assistant", "content": "普通回答"}]
    ) == (None, None)
    # 最后一条是 brainstorm SPEC(等待确认,不是等待澄清)→ 澄清态为 None
    assert _get_pending_clarification(
        [{"role": "user", "content": "x"},
         {"role": "assistant", "content": BRAINSTORM_PROPOSAL_MARKER + "## 开发 SPEC"}]
    ) == (None, None)
    assert _get_pending_clarification([]) == (None, None)


def test_count_clarify_rounds():
    history = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": CLARIFY_PROPOSAL_MARKER + "## 🤔 q1"},
        {"role": "user", "content": "答1"},
        {"role": "assistant", "content": CLARIFY_PROPOSAL_MARKER + "## 🤔 q2"},
        {"role": "user", "content": "答2"},
    ]
    assert _count_clarify_rounds(history) == 2
    assert _count_clarify_rounds([{"role": "assistant", "content": "普通"}]) == 0


# ---------- 集成:pipeline 澄清门 ----------

async def _collect(gen: AsyncIterator[dict]) -> list[dict]:
    events: list[dict] = []
    async for ev in gen:
        events.append(ev)
    return events


def _fake_db():
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


_BRAINSTORM_SCENE = next(iter(BRAINSTORM_SCENES))


@pytest.mark.asyncio
async def test_first_turn_clarification_gates_without_codegen():
    """首轮需求不清晰 → brainstorm 产出 `## 🤔` 澄清 → pipeline 应:
    1) emit done{waiting_clarification:True}
    2) 不 emit create_workspace(不建工作区、不 codegen)
    3) 把澄清以 CLARIFY_PROPOSAL_MARKER 存进历史(供续轮识别等待态)
    """
    params = PipelineParams(
        message="给商机做个看板",  # 含糊:没说按什么分列/拖拽规则
        user_id=1, tenant_id=1, workspace_id=None, conversation_id=None,
    )
    db = _fake_db()

    clarify_text = "## 🤔 开始前,先和你对齐几点\n1. 看板按什么分列?A 商机阶段 B 负责人 C 其他(请补充)"

    async def _ftb(*a, **k):
        yield {"type": "step", "step": "read_app_context", "status": "done", "data": {}}
        yield {"__spec__": clarify_text}

    saved: list = []

    async def _save(_db, _conv, role, content):
        saved.append((role, content))

    with (
        patch("app.coding.pipeline._detect_scene_llm_call", new=AsyncMock(return_value=_BRAINSTORM_SCENE)),
        patch("app.coding.pipeline.classify_coding_intent", new=AsyncMock(return_value="BUILD")),
        patch("app.coding.pipeline._first_turn_brainstorm", new=_ftb),
        patch("app.coding.pipeline.resolve_effective_coding_model", new=AsyncMock(return_value=("gpt-4o", 1))),
        patch("app.coding.pipeline.save_coding_message", new=_save),
        patch("app.coding.pipeline.get_conversation_history", new=AsyncMock(return_value=[])),
        patch("app.coding.pipeline.WorkspaceManager.create_workspace",
              return_value={"id": "ws-x", "project_name": "p", "display_name": "d", "ide_url": "u"}),
        patch("app.coding.pipeline.WorkspaceManager.get_workspace_info", return_value={}),
        patch("app.coding.pipeline.append_event_to_stream_replay"),
        patch("app.agents.coding.llm_config.load_coding_llm_config", new=AsyncMock(return_value=("http://fake/v1", "k", "gpt-x"))),
    ):
        events = await _collect(run_coding_pipeline(params, db))

    # 1) 澄清门生效
    assert [e for e in events if e.get("waiting_clarification") is True], (
        f"没有 waiting_clarification=True;events={events}"
    )
    # 2) 不应建工作区
    assert not [e for e in events if e.get("type") == "step" and e.get("step") == "create_workspace"], (
        f"澄清门不该建工作区;events={events}"
    )
    # 3) 澄清以 CLARIFY marker 存档
    assert any(role == "assistant" and content.startswith(CLARIFY_PROPOSAL_MARKER) for role, content in saved), (
        f"澄清未以 CLARIFY_PROPOSAL_MARKER 存档;saved={saved}"
    )
    # 没有把澄清误存成 brainstorm SPEC marker(否则会被当成等待确认)
    assert not any(content.startswith(BRAINSTORM_PROPOSAL_MARKER) for _r, content in saved)
    # 4) brainstorm done step 带 data.outcome="clarify" —— 前端据此显示「澄清问题待回答」而非「开发 SPEC 待确认」
    bs_done = [e for e in events
               if e.get("type") == "step" and e.get("step") == "brainstorm" and e.get("status") == "done"]
    assert bs_done and bs_done[-1].get("data", {}).get("outcome") == "clarify", (
        f"澄清分支的 brainstorm done 应带 outcome='clarify';bs_done={bs_done}"
    )


@pytest.mark.asyncio
async def test_first_turn_structured_clarify_emits_chips():
    """grounded brainstorm 调 ask_clarifying_question → pipeline 应 emit 结构化 clarify 事件
    (question + options,给前端渲染可点选项卡片),并以 CLARIFY marker + JSON 存档。"""
    import json as _json
    params = PipelineParams(
        message="给商机做个看板", user_id=1, tenant_id=1, workspace_id=None, conversation_id=None,
    )
    db = _fake_db()

    async def _ftb(*a, **k):
        yield {"__clarify__": {"question": "看板按什么分列?", "options": ["商机阶段", "负责人"]}}

    saved: list = []

    async def _save(_db, _conv, role, content):
        saved.append((role, content))

    with (
        patch("app.coding.pipeline._detect_scene_llm_call", new=AsyncMock(return_value=_BRAINSTORM_SCENE)),
        patch("app.coding.pipeline.classify_coding_intent", new=AsyncMock(return_value="BUILD")),
        patch("app.coding.pipeline._first_turn_brainstorm", new=_ftb),
        patch("app.coding.pipeline.resolve_effective_coding_model", new=AsyncMock(return_value=("m", 1))),
        patch("app.agents.coding.llm_config.load_coding_llm_config", new=AsyncMock(return_value=("u", "k", "m"))),
        patch("app.coding.pipeline.save_coding_message", new=_save),
        patch("app.coding.pipeline.get_conversation_history", new=AsyncMock(return_value=[])),
        patch("app.coding.pipeline.WorkspaceManager.create_workspace",
              return_value={"id": "w", "project_name": "p", "display_name": "d", "ide_url": "u"}),
        patch("app.coding.pipeline.WorkspaceManager.get_workspace_info", return_value={}),
        patch("app.coding.pipeline.append_event_to_stream_replay"),
    ):
        events = await _collect(run_coding_pipeline(params, db))

    # 结构化 clarify 事件
    clar = [e for e in events if e.get("type") == "clarify"]
    assert clar, f"应 emit clarify 事件;events={[e.get('type') for e in events]}"
    assert clar[0]["question"] == "看板按什么分列?"
    assert clar[0]["options"] == ["商机阶段", "负责人"]
    # 等澄清 + 不建工作区
    assert any(e.get("waiting_clarification") for e in events)
    assert not [e for e in events if e.get("type") == "step" and e.get("step") == "create_workspace"]
    # 存档:CLARIFY marker + JSON(可还原 chips)
    cm = [c for r, c in saved if c.startswith(CLARIFY_PROPOSAL_MARKER)]
    assert cm, f"应以 CLARIFY marker 存档;saved={saved}"
    payload = _json.loads(cm[0][len(CLARIFY_PROPOSAL_MARKER):])
    assert payload["options"] == ["商机阶段", "负责人"]
    # brainstorm done step 带 data.outcome="clarify"(结构化 chips 分支)
    bs_done = [e for e in events
               if e.get("type") == "step" and e.get("step") == "brainstorm" and e.get("status") == "done"]
    assert bs_done and bs_done[-1].get("data", {}).get("outcome") == "clarify", (
        f"结构化澄清分支的 brainstorm done 应带 outcome='clarify';bs_done={bs_done}"
    )
