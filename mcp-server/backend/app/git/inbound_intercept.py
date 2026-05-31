"""拦截直连 merge — apply 必须经 Builder

策略：
- pr_merged event 触达
- 找对应 ChangeProposal
- 如 ChangeProposal.status != 'applied'（即 Builder 还没 apply）：
  ⇒ 直连绕过了 Builder 第二道门
  ⇒ revert merge commit + comment 提示 + 写 drift log
"""
from __future__ import annotations
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application
from app.models.collaboration import GitConnection, ChangeProposal, PlatformDriftLog
from app.git.webhook import WebhookEvent
from app.git.connection import make_provider

logger = logging.getLogger(__name__)


async def handle_direct_merge(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    app = (await db.execute(
        select(Application).where(Application.git_repo_url.like(f"%{event.repo_full_path}%"))
    )).scalar_one_or_none()
    if not app:
        return

    # 找对应 proposal
    pr_url_pattern = f"%/{event.pr_number}"
    proposal = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.git_pr_url.like(pr_url_pattern),
        )
    )).scalar_one_or_none()

    if proposal and proposal.status == "applied":
        # 这是 Builder 自己 apply 触发的 merge —— 正常完成路径
        logger.info(f"merge of PR #{event.pr_number} matches applied proposal {proposal.id}; OK")
        return

    # 直连 merge：拦截
    logger.warning(f"direct merge detected for PR #{event.pr_number} on {event.repo_full_path}; reverting")
    provider = make_provider(conn)
    raw = event.raw_payload or {}
    merge_commit = (raw.get("pull_request") or raw.get("object_attributes") or {}).get("merge_commit_sha", "")
    try:
        if merge_commit:
            await provider.revert_commit(
                repo_full_path=event.repo_full_path,
                branch=event.pr_target_branch or "main",
                commit_sha=merge_commit,
            )
        else:
            logger.warning(f"PR #{event.pr_number} merged event missing merge_commit_sha; skip revert step")

        if event.pr_number is not None:
            await provider.add_pr_comment(
                repo_full_path=event.repo_full_path, pr_number=event.pr_number,
                body="⚠️ 此 MR/PR 被 aPaaS Builder 自动 revert：直连 merge 绕过了 Builder 的不可逆操作确认。请回到 Builder 中通过 ChangeProposal 流程 apply。",
            )

        # 始终记录漂移（不依赖 proposal 是否存在）
        db.add(PlatformDriftLog(
            application_id=app.id,
            kind="direct_merge_reverted",
            git_sha=merge_commit or None,
            builder_canonical_sha=app.canonical_spec_id,
        ))
        await db.commit()
    except Exception as e:
        logger.exception(f"revert failed for PR #{event.pr_number}: {e}")
