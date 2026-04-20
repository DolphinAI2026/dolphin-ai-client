"""迭代服务 —— SpecPatch 应用 + 落盘为新版本 Spec。

职责：
- 给定 base Spec + SpecPatch → apply → save as new version
- 验证 patch 后的 envelope 仍是合法 Spec（Pydantic + 业务规则）
- 维护 specs 表的版本链（parent_version 指向 base.version）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.iteration import IterationLevel, PatchApplyError, SpecPatch, apply_patch
from app.models import agent_models
from app.services import spec_service

logger = logging.getLogger(__name__)


async def apply_patch_as_new_spec(
    db: AsyncSession,
    *,
    base_spec_id: str,
    patch: SpecPatch,
) -> agent_models.Spec:
    """把 SpecPatch 应用到 base Spec，产出并持久化为新版本 Spec。

    返回新 Spec ORM 行。调用方负责 commit。

    Raises:
        ValueError：base spec 不存在
        PatchApplyError：patch 不合法
        SpecValidationError：patch 后的 envelope 不合法
    """
    if patch.iteration_level not in (IterationLevel.TRIVIAL, IterationLevel.MINOR):
        raise PatchApplyError(
            f"iteration_level={patch.iteration_level.value} 不能走 patch 路径，"
            "必须通过 BrainstormAgent 产生新 Spec"
        )

    base = await spec_service.get_spec(db, base_spec_id)
    if not base:
        raise ValueError(f"base spec {base_spec_id} not found")

    base_envelope = base.content or {}
    new_envelope = apply_patch(base_envelope, patch, bump_version=True)

    # save_spec 会做 Pydantic + 业务规则校验
    new_row = await spec_service.save_spec(
        db,
        brainstorm_session_id=base.brainstorm_session_id,
        envelope=new_envelope,
        parent_version=base.version,
    )
    logger.info(
        "iteration: base spec %s (v%d) + patch (level=%s, %d ops) → new spec %s (v%d)",
        base_spec_id, base.version, patch.iteration_level.value,
        len(patch.operations), new_row.id, new_row.version,
    )
    return new_row
