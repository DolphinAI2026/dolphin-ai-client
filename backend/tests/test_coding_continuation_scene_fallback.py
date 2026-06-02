"""续轮场景识别兜底 —— 回归测试

线上 bug:用户在 SPEC 上点「确认」后,pipeline 用「确认/澄清回答」那句话**重新识别场景**,
偶发判成 unsupported_script → 直接 bail,把用户刚确认的 SPEC 丢掉、不生成代码。

修复:brainstorm/澄清 续轮(_awaiting_followup)
  ① 用历史**首条** user 消息(真正的原始需求)识别场景,不用「确认/选A」那句;
  ② 即便仍判 unsupported,也**不 bail** —— 降级兜底场景继续 codegen(SPEC 已确认,不能丢)。

断言:确认续轮 + 场景识别抛 UnsupportedSceneError 时:
  1. 不出现 done{scene_type:unsupported_script} 的早退
  2. 仍走到 create_workspace(证明没把已确认的 SPEC 丢掉)
"""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.coding.pipeline import (
    BRAINSTORM_PROPOSAL_MARKER,
    PipelineParams,
    UnsupportedSceneError,
    run_coding_pipeline,
)


async def _collect(gen: AsyncIterator[dict]) -> list[dict]:
    events: list[dict] = []
    async for ev in gen:
        events.append(ev)
    return events


def _fake_db():
    db = MagicMock()
    # 返回一个已存在的 coding 会话(否则 pipeline 查不到会把 conversation_id 置空、跳过历史加载)
    conv = MagicMock()
    conv.id = 123
    conv.selected_llm_config_id = 1
    conv.workspace_id = None
    conv.user_id = 1
    conv.tenant_id = 1
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = conv
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock(return_value=conv)
    return db


class _EmptyAgentStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_confirm_continuation_survives_unsupported_scene():
    """确认续轮 + 场景再判 unsupported → 不 bail,降级兜底继续到 create_workspace。"""
    # 历史:原始需求「设计个首页」+ 已出的 SPEC(带 brainstorm marker)→ 处于「等确认」态
    history = [
        {"role": "user", "content": "设计个首页"},
        {"role": "assistant", "content": BRAINSTORM_PROPOSAL_MARKER + "## 📋 开发 SPEC 确认\n首页布局..."},
    ]
    params = PipelineParams(
        message="确认,按这份开发 SPEC 开始生成代码",  # 用户点确认发的话
        user_id=1, tenant_id=1, workspace_id=None, conversation_id=123,
    )
    db = _fake_db()

    with (
        # 续轮意图分类为「确认」
        patch("app.coding.pipeline._classify_brainstorm_response", new=AsyncMock(return_value="confirm")),
        # 场景识别**抛 unsupported**(模拟线上抖动 / 拿错识别文本)
        patch("app.coding.pipeline._detect_scene_llm_call", new=AsyncMock(side_effect=UnsupportedSceneError("不支持的脚本场景"))),
        patch("app.coding.pipeline.get_conversation_history", new=AsyncMock(return_value=history)),
        patch("app.coding.pipeline.resolve_effective_coding_model", new=AsyncMock(return_value=("gpt-4o", 1))),
        patch("app.coding.pipeline.save_coding_message", new=AsyncMock()),
        patch("app.coding.pipeline.extract_project_name", new=AsyncMock(return_value="home")),
        patch("app.coding.pipeline.WorkspaceManager.create_workspace",
              return_value={"id": "ws-1", "project_name": "home", "display_name": "首页", "ide_url": "u"}),
        patch("app.coding.pipeline.WorkspaceManager.get_workspace_info", return_value={}),
        patch("app.coding.pipeline.append_event_to_stream_replay"),
        patch("app.agents.coding.CodingAgent", return_value=MagicMock()),
        patch("app.agents.coding.CodingAgentStreamAdapter", return_value=_EmptyAgentStream()),
        patch("app.agents.coding.llm_config.load_coding_llm_config",
              new=AsyncMock(return_value=("http://fake", "k", "gpt-4o"))),
        patch("app.services.prompt_resolver.resolve_prompt", new=AsyncMock(return_value="sys")),
    ):
        events = await _collect(run_coding_pipeline(params, db))

    # 1) 不该把场景判成 unsupported 后早退
    assert not [e for e in events if (e.get("data") or {}).get("scene_type") == "unsupported_script"], (
        f"续轮不该再因 unsupported 早退;events={[e.get('type') for e in events]}"
    )
    # 2) 仍走到 create_workspace(证明确认的 SPEC 没被丢)
    assert [e for e in events if e.get("type") == "step" and e.get("step") == "create_workspace"], (
        f"确认续轮应继续建工作区 + codegen,而不是丢掉 SPEC;events={events}"
    )
