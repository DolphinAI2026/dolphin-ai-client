"""不再兜底内置模型:没配模型就提示去平台管理添加 —— 回归测试

产品决定:AI Builder / AI Coding 都不要兜底模型。没配可用模型时,Coding pipeline 应在
开工前就 emit 一条明确「去平台管理配置模型」的 error + done,而不是静默兜底到内置 minimax
再半路 401/报错。
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.coding.llm_config import NoLLMConfigError, NO_MODEL_HINT
from app.coding.pipeline import PipelineParams, run_coding_pipeline


async def _collect(gen: AsyncIterator[dict]) -> list[dict]:
    out: list[dict] = []
    async for ev in gen:
        out.append(ev)
    return out


def _fake_db():
    db = MagicMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=r)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_pipeline_prompts_when_no_model_configured():
    params = PipelineParams(
        message="做一个设备台账页面", user_id=1, tenant_id=99,
        workspace_id=None, conversation_id=None,
    )
    db = _fake_db()

    with (
        patch("app.coding.pipeline.resolve_effective_coding_model", new=AsyncMock(return_value=("", None))),
        # 预检里 import 的是 app.agents.coding.llm_config.load_coding_llm_config
        patch("app.agents.coding.llm_config.load_coding_llm_config", new=AsyncMock(side_effect=NoLLMConfigError())),
        patch("app.coding.pipeline.append_event_to_stream_replay"),
    ):
        events = await _collect(run_coding_pipeline(params, db))

    # 1) 有明确的「去平台管理配置模型」error
    errs = [e for e in events if e.get("type") == "error"]
    assert errs and NO_MODEL_HINT in errs[0].get("content", ""), f"应提示去平台管理配模型;events={events}"
    assert "平台管理" in errs[0]["content"]
    # 2) 早返:没有进入场景识别 / 建工作区 / codegen
    assert not [e for e in events if e.get("type") == "step" and e.get("step") in ("detect_scene", "create_workspace", "generate")], (
        f"无模型应早返,不该跑场景识别/建工作区/codegen;events={events}"
    )
    # 3) 收尾有 done
    assert any(e.get("type") == "done" for e in events)


def test_no_model_hint_mentions_platform_admin():
    # 文案锚点:必须引导到平台管理
    assert "平台管理" in NO_MODEL_HINT and "模型" in NO_MODEL_HINT
