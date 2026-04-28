"""漂移检测：git main HEAD vs Builder canonical commit_sha

Phase D Task 4。

check_drift：对比 git default branch HEAD 和 Builder canonical Spec.commit_sha；
detected 时写 PlatformDriftLog。

resolve_drift：v1 仅记录解决意图（PlatformDriftLog），实际数据迁移留 v2。
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application
from app.models.collaboration import GitConnection, PlatformDriftLog
from app.git.connection import make_provider

logger = logging.getLogger(__name__)


def _repo_full_path_from_url(git_repo_url: str) -> str:
    """从 https://host/owner/repo 形式 URL 抽出 owner/repo 段。"""
    parts = git_repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"无法从 git_repo_url 解析 owner/repo: {git_repo_url}")
    return f"{parts[-2]}/{parts[-1]}"


async def check_drift(
    db: AsyncSession, *, application: Application,
) -> dict:
    """对比 git 默认分支 HEAD 和 Builder canonical Spec.commit_sha。

    返回：
      - {"drift": False, "reason": "..."} — 无漂移或无法对比
      - {"drift": True, "git_sha": ..., "builder_sha": ...} — 检测到漂移（已写日志）
      - {"drift": False, "git_sha": ..., "builder_sha": ...} — 一致
    """
    if not application.git_repo_url:
        return {"drift": False, "reason": "no git binding"}
    if not getattr(application, "project_id", None):
        return {"drift": False, "reason": "no project"}
    if not application.canonical_spec_id:
        return {"drift": False, "reason": "no canonical"}

    # 取 builder canonical Spec 的 commit_sha
    from app.models.spec import Spec as SpecORM
    canonical_row = (await db.execute(
        select(SpecORM).where(SpecORM.id == application.canonical_spec_id)
    )).scalar_one_or_none()
    builder_sha = canonical_row.commit_sha if canonical_row else None
    if not builder_sha:
        # canonical 还未走过 git push（Phase C 之前的旧应用）— 没法比，不算 drift
        return {"drift": False, "reason": "canonical without commit_sha"}

    conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == application.project_id)
    )).scalar_one_or_none()
    if not conn:
        return {"drift": False, "reason": "no git connection"}

    # 取 git 默认分支 HEAD
    try:
        repo_full_path = _repo_full_path_from_url(application.git_repo_url)
        provider = make_provider(conn)
        git_sha = await provider.get_branch_head(
            repo_full_path=repo_full_path,
            branch=application.git_default_branch or "main",
        )
    except Exception as e:
        logger.warning(f"check_drift: failed to read git HEAD for app {application.id}: {e}")
        return {"drift": False, "reason": f"git read failed: {e}"}

    drift = git_sha != builder_sha
    if drift:
        db.add(PlatformDriftLog(
            application_id=application.id,
            kind="drift_detected",
            git_sha=git_sha,
            builder_canonical_sha=builder_sha,
        ))
        await db.commit()

    return {"drift": drift, "git_sha": git_sha, "builder_sha": builder_sha}


async def resolve_drift(
    db: AsyncSession, *, application: Application, direction: str, resolved_by: int,
) -> dict:
    """记录漂移解决意图。

    direction:
      - 'git_to_builder' — 拉 git 内容覆盖 Builder canonical（v1 仅记录）
      - 'builder_to_git' — 强推 Builder canonical 到 git（v1 仅记录）

    v1 简化：实际数据迁移留 v2，本调用仅写 PlatformDriftLog 标记意图。
    """
    if direction not in ("git_to_builder", "builder_to_git"):
        raise ValueError("direction 必须是 git_to_builder 或 builder_to_git")

    db.add(PlatformDriftLog(
        application_id=application.id,
        kind="drift_resolved",
        resolution_direction=direction,
        resolved_by=resolved_by,
        resolved_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    await db.commit()
    return {
        "status": "logged",
        "direction": direction,
        "note": "v1 仅记录解决意图，实际数据迁移留 v2",
    }
