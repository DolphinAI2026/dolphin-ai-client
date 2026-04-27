"""AgentErrorRecorder — 记录 CodingAgent 错误事件，用于提示词优化分析。

使用方式：
    recorder = AgentErrorRecorder(coding_session_id=..., project_type=..., ...)
    await recorder.record(error_type="tool_fail", error_message=..., tool_name=...)
    await recorder.mark_resolved(round_index=0)   # 验收通过后调用

所有写入静默失败，不影响主流程。
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class AgentErrorRecorder:
    """CodingAgent 错误记录器。

    error_type 取值：
    - tool_fail       : tool 调用返回 success=False
    - tool_not_found  : LLM 调用了未定义的 tool
    - verify_fail     : 验收轮 overall_status=failed
    """

    def __init__(
        self,
        coding_session_id: str,
        spec_id: str = "",
        workspace_id: str = "",
        project_type: str = "",
        scene_type: str = "",
    ) -> None:
        self.coding_session_id = coding_session_id
        self.spec_id = spec_id or None
        self.workspace_id = workspace_id or None
        self.project_type = project_type or None
        self.scene_type = scene_type or None

    async def record(
        self,
        error_type: str,
        error_message: str,
        *,
        round_index: int = 0,
        turn: int = 0,
        tool_name: str = "",
    ) -> None:
        """写入一条错误记录（静默失败，5 秒超时）。"""
        from app.database import AsyncSessionLocal
        from app.models.agent_models import AgentErrorEvent
        try:
            async def _write() -> None:
                async with AsyncSessionLocal() as db:
                    row = AgentErrorEvent(
                        id=f"err_{secrets.token_hex(8)}",
                        coding_session_id=self.coding_session_id,
                        spec_id=self.spec_id,
                        workspace_id=self.workspace_id,
                        project_type=self.project_type,
                        scene_type=self.scene_type,
                        round_index=round_index,
                        turn=turn,
                        error_type=error_type,
                        tool_name=tool_name or None,
                        error_message=error_message[:2000],
                        resolved=False,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(row)
                    await db.commit()
            await asyncio.wait_for(_write(), timeout=5.0)
        except Exception as e:
            logger.warning("AgentErrorRecorder.record 失败（忽略）: %s", e)

    async def mark_resolved(self, round_index: int) -> None:
        """将某轮所有错误标记为 resolved（验收通过后调用，5 秒超时）。"""
        from sqlalchemy import update
        from app.database import AsyncSessionLocal
        from app.models.agent_models import AgentErrorEvent
        try:
            async def _update() -> None:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(AgentErrorEvent)
                        .where(
                            AgentErrorEvent.coding_session_id == self.coding_session_id,
                            AgentErrorEvent.round_index == round_index,
                        )
                        .values(resolved=True)
                    )
                    await db.commit()
            await asyncio.wait_for(_update(), timeout=5.0)
        except Exception as e:
            logger.warning("AgentErrorRecorder.mark_resolved 失败（忽略）: %s", e)
