"""Harness Core — Artifact 持久化

记录 turn 产出的关键结果（workspace、构建结果、Agent 摘要等），
供后续查询、审计、评估使用。
"""
import json
import logging
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.harness.models import HarnessArtifact

logger = logging.getLogger(__name__)


async def save_artifact(
    db: AsyncSession,
    *,
    thread_id: int,
    turn_id: int,
    artifact_type: str,
    artifact_key: str,
    content: Any,
) -> int:
    """保存一个 artifact，返回 artifact id。"""
    artifact = HarnessArtifact(
        thread_id=thread_id,
        turn_id=turn_id,
        artifact_type=artifact_type,
        artifact_key=artifact_key,
        content_json=json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content,
    )
    db.add(artifact)
    await db.flush()
    return artifact.id


async def save_artifacts_batch(
    db: AsyncSession,
    *,
    thread_id: int,
    turn_id: int,
    artifacts: list[dict[str, Any]],
):
    """批量保存 artifacts。每个 dict 应包含 artifact_type, artifact_key, content。"""
    for item in artifacts:
        try:
            await save_artifact(
                db,
                thread_id=thread_id,
                turn_id=turn_id,
                artifact_type=item["artifact_type"],
                artifact_key=item["artifact_key"],
                content=item.get("content", {}),
            )
        except Exception:
            logger.warning("Failed to save artifact %s/%s", item.get("artifact_type"), item.get("artifact_key"), exc_info=True)
    await db.commit()


async def get_artifacts(
    db: AsyncSession,
    thread_id: int,
    *,
    turn_id: Optional[int] = None,
    artifact_type: Optional[str] = None,
) -> list[dict]:
    """查询 artifacts。"""
    stmt = select(HarnessArtifact).where(HarnessArtifact.thread_id == thread_id)
    if turn_id is not None:
        stmt = stmt.where(HarnessArtifact.turn_id == turn_id)
    if artifact_type is not None:
        stmt = stmt.where(HarnessArtifact.artifact_type == artifact_type)
    stmt = stmt.order_by(HarnessArtifact.created_at.asc())

    result = await db.execute(stmt)
    items = result.scalars().all()
    return [
        {
            "id": a.id,
            "thread_id": a.thread_id,
            "turn_id": a.turn_id,
            "artifact_type": a.artifact_type,
            "artifact_key": a.artifact_key,
            "content": json.loads(a.content_json) if a.content_json else {},
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in items
    ]
