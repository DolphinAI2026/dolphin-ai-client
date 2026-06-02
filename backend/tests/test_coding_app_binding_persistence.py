"""「在应用上定制」绑定应用持久化 —— 回归测试

线上 bug:用户绑了应用「通用B2B CRM」,但刷新/侧栏点开会话后前端 app_id ref 丢失,
后续轮请求 app_id=null → grounding 退回通用 SPEC,SPEC 全是「待确认」,不知道是哪个应用。

修复:把绑定的 app_id 持久化到 Conversation.coding_app_id;请求没带 app_id 时从会话回读,
让 grounding 始终记得是哪个应用。本测试断言:请求 app_id 为空、但会话已存 coding_app_id 时,
pipeline 把 params.app_id 回读成持久化的值,再交给 brainstorm(grounding 能据此读应用上下文)。
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


async def _collect(gen: AsyncIterator[dict]) -> list[dict]:
    out: list[dict] = []
    async for ev in gen:
        out.append(ev)
    return out


def _fake_db(conv):
    db = MagicMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = conv
    db.execute = AsyncMock(return_value=res)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock(return_value=conv)
    return db


_BRAINSTORM_SCENE = next(iter(BRAINSTORM_SCENES))


@pytest.mark.asyncio
async def test_app_id_read_back_from_conversation_when_request_missing():
    """请求未带 app_id,但会话持久化了 coding_app_id=5 → 回读,brainstorm 收到 app_id='5'。"""
    conv = MagicMock()
    conv.id = 200
    conv.coding_app_id = 5          # 之前已持久化的绑定
    conv.selected_llm_config_id = 1
    conv.workspace_id = None
    conv.user_id = 1
    conv.tenant_id = 1

    params = PipelineParams(
        message="给商机做个拖拽看板",
        user_id=1, tenant_id=1, workspace_id=None, conversation_id=200,
        app_id=None,               # ★ 本轮请求没带 app_id(前端 ref 丢了)
    )
    db = _fake_db(conv)

    captured = {}

    async def _ftb(p, scene_type, _db, effective_model, **_kw):
        captured["app_id"] = getattr(p, "app_id", None)
        # 直接抛个澄清让 pipeline 干净停住(不必跑建工作区/codegen)
        yield {"__spec__": "## 🤔 先对齐几点\n1. 看板按什么分列?"}

    with (
        patch("app.coding.pipeline._detect_scene_llm_call", new=AsyncMock(return_value=_BRAINSTORM_SCENE)),
        patch("app.coding.pipeline.classify_coding_intent", new=AsyncMock(return_value="BUILD")),
        patch("app.coding.pipeline._first_turn_brainstorm", new=_ftb),
        patch("app.coding.pipeline.resolve_effective_coding_model", new=AsyncMock(return_value=("gpt-4o", 1))),
        patch("app.coding.pipeline.save_coding_message", new=AsyncMock()),
        patch("app.coding.pipeline.get_conversation_history", new=AsyncMock(return_value=[])),
        patch("app.coding.pipeline.append_event_to_stream_replay"),
    ):
        await _collect(run_coding_pipeline(params, db))

    assert captured.get("app_id") == "5", (
        f"应从会话回读 coding_app_id=5 补回 params.app_id,实际={captured.get('app_id')!r}"
    )


@pytest.mark.asyncio
async def test_app_id_persisted_to_conversation_when_request_has_it():
    """请求带 app_id=7、会话尚未绑定 → 回填到 conversation.coding_app_id。"""
    conv = MagicMock()
    conv.id = 201
    conv.coding_app_id = None       # 还没绑
    conv.selected_llm_config_id = 1
    conv.workspace_id = None
    conv.user_id = 1
    conv.tenant_id = 1

    params = PipelineParams(
        message="给商机做个看板",
        user_id=1, tenant_id=1, workspace_id=None, conversation_id=201,
        app_id="7",                # ★ 本轮带了 app_id
    )
    db = _fake_db(conv)

    async def _ftb(p, scene_type, _db, effective_model, **_kw):
        yield {"__spec__": "## 🤔 q"}

    with (
        patch("app.coding.pipeline._detect_scene_llm_call", new=AsyncMock(return_value=_BRAINSTORM_SCENE)),
        patch("app.coding.pipeline.classify_coding_intent", new=AsyncMock(return_value="BUILD")),
        patch("app.coding.pipeline._first_turn_brainstorm", new=_ftb),
        patch("app.coding.pipeline.resolve_effective_coding_model", new=AsyncMock(return_value=("gpt-4o", 1))),
        patch("app.coding.pipeline.save_coding_message", new=AsyncMock()),
        patch("app.coding.pipeline.get_conversation_history", new=AsyncMock(return_value=[])),
        patch("app.coding.pipeline.append_event_to_stream_replay"),
    ):
        await _collect(run_coding_pipeline(params, db))

    assert conv.coding_app_id == 7, f"应把 app_id=7 回填到会话,实际={conv.coding_app_id!r}"
