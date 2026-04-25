"""Webhook 事件 → Builder 状态变更"""
from __future__ import annotations
import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, User
from app.models.collaboration import (
    GitConnection, ChangeProposal, ProposalReview,
)
from app.git.webhook import WebhookEvent
from app.git.connection import make_provider

logger = logging.getLogger(__name__)


async def dispatch_webhook_event(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """根据 event_type 路由到对应 handler"""
    if event.event_type == "push":
        return await handle_push(db, conn=conn, event=event)
    if event.event_type in ("pr_opened", "pr_synchronized"):
        return await handle_pr_open_or_update(db, conn=conn, event=event)
    if event.event_type == "pr_review":
        return await handle_pr_review(db, conn=conn, event=event)
    if event.event_type == "pr_merged":
        # Task 3 处理（拦截）
        from app.git.inbound_intercept import handle_direct_merge
        return await handle_direct_merge(db, conn=conn, event=event)
    logger.info(f"webhook event {event.event_type} ignored (no handler)")


async def _resolve_application(
    db: AsyncSession, *, conn: GitConnection, repo_full_path: str,
) -> Optional[Application]:
    """根据 repo_full_path 找对应 Application"""
    return (await db.execute(
        select(Application).where(
            Application.git_repo_url.like(f"%{repo_full_path}%"),
        )
    )).scalar_one_or_none()


async def handle_push(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """push 事件：

    - main 分支 push：仅记日志（应该来自 Builder 自身的 apply→merge；外部 push 由 drift detection 抓）
    - feature 分支（spec/proposal-*）push：找对应 ChangeProposal，更新 draft_spec_id 指向的 Spec（重新 parse repo 的 spec/canonical.json）

    简化版：v1 只处理 spec/proposal-* 分支的 push（其他分支 noop）。
    """
    if not (event.branch and event.branch.startswith("spec/proposal-")):
        logger.info(f"push to {event.branch} ignored (not a proposal branch)")
        return

    app = await _resolve_application(db, conn=conn, repo_full_path=event.repo_full_path)
    if not app:
        logger.warning(f"no Application bound to {event.repo_full_path}")
        return

    # 找对应 proposal（git_branch 匹配）
    proposal = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.git_branch == event.branch,
        )
    )).scalar_one_or_none()
    if not proposal:
        logger.info(f"push to {event.branch} but no matching proposal; skip")
        return

    # 拉 spec/canonical.json from repo
    provider = make_provider(conn)
    try:
        content = await provider.read_file(
            repo_full_path=event.repo_full_path,
            path="spec/canonical.json",
            ref=event.branch,
        )
        spec_dict = json.loads(content)
    except Exception as e:
        logger.error(f"failed to read spec/canonical.json from {event.branch}: {e}")
        return

    # 用 spec_dict 替换 proposal.draft_spec_id 指向的 Spec.payload
    from app.spec.persistence import load_spec, save_spec
    from app.spec.schema import Spec
    draft = await load_spec(db, proposal.draft_spec_id, tenant_id=app.tenant_id)
    if not draft:
        logger.warning(f"draft spec {proposal.draft_spec_id} not found")
        return

    # spec_dict 是 SPEC 的 model_dump 形式
    new_draft = Spec.model_validate(spec_dict)
    new_draft.id = draft.id          # 保持原 id
    new_draft.version = draft.version  # 让 save_spec 走 CAS
    new_draft.parent_spec_id = draft.parent_spec_id
    new_draft.created_by = draft.created_by
    new_draft.application_id = draft.application_id
    await save_spec(db, new_draft, tenant_id=app.tenant_id)

    # 重跑第一道门 → 更新 proposal.validation_report
    from app.proposal.validation import validate as validate_spec
    report = validate_spec(new_draft)
    proposal.validation_report = report.to_dict()
    if proposal.status == "draft" and report.ok:
        proposal.status = "open"
    elif proposal.status == "open" and not report.ok:
        proposal.status = "draft"
    await db.commit()

    logger.info(f"synced push to proposal {proposal.id} (status={proposal.status})")


async def handle_pr_open_or_update(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """PR 创建/更新：

    - 如来自 Builder 自身的 promote（git_pr_url 已设到某 ChangeProposal）：noop
    - 否则（外部新建 PR）：自动创建 ChangeProposal 关联到现有 application
    """
    app = await _resolve_application(db, conn=conn, repo_full_path=event.repo_full_path)
    if not app:
        logger.warning(f"no Application bound to {event.repo_full_path}")
        return

    # 检查是否已有 proposal 关联此 PR
    pr_url_pattern = f"%{event.repo_full_path}%/{event.pr_number}"  # 粗匹配
    existing = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.git_pr_url.like(pr_url_pattern),
        )
    )).scalar_one_or_none()

    if existing:
        # Builder 已知此 PR；更新 title/description（如有改）
        existing.title = event.pr_title or existing.title
        existing.description = event.pr_description or existing.description
        await db.commit()
        return

    # 外部新建 PR — 创建新 ChangeProposal
    # 找 actor 对应的 builder user（按 username 匹配，简化）
    actor_user = None
    if event.actor_username:
        actor_user = (await db.execute(
            select(User).where(User.username == event.actor_username)
        )).scalar_one_or_none()
    creator_id = actor_user.id if actor_user else app.created_by

    # 拉 source_branch 的 spec/canonical.json 作为 draft 内容
    provider = make_provider(conn)
    try:
        content = await provider.read_file(
            repo_full_path=event.repo_full_path,
            path="spec/canonical.json",
            ref=event.pr_source_branch,
        )
        spec_dict = json.loads(content)
    except Exception as e:
        logger.error(f"cannot read spec from {event.pr_source_branch}: {e}")
        return

    # 创建 draft Spec + proposal
    from app.spec.schema import Spec
    from app.spec.persistence import save_spec, new_spec_id, load_spec
    from datetime import datetime, timezone

    canonical = await load_spec(db, app.canonical_spec_id, tenant_id=app.tenant_id) if app.canonical_spec_id else None
    new_draft = Spec.model_validate(spec_dict)
    new_draft.id = new_spec_id()
    new_draft.parent_spec_id = canonical.id if canonical else None
    new_draft.version = 1
    new_draft.created_by = creator_id
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    new_draft.created_at = now
    new_draft.updated_at = now
    new_draft.application_id = app.id
    await save_spec(db, new_draft, tenant_id=app.tenant_id)

    from app.proposal.persistence import create_proposal
    proposal = await create_proposal(
        db,
        application_id=app.id,
        draft_spec_id=new_draft.id,
        base_canonical_spec_id=app.canonical_spec_id,
        title=event.pr_title or f"External PR #{event.pr_number}",
        description=event.pr_description or "（来自 git 平台外部创建）",
        created_by=creator_id,
        status="open",
    )
    proposal.git_branch = event.pr_source_branch
    raw = event.raw_payload or {}
    proposal.git_pr_url = (raw.get("pull_request") or raw.get("object_attributes") or {}).get("html_url") or \
                         (raw.get("object_attributes") or {}).get("url", "")

    # 第一道门
    from app.proposal.validation import validate as validate_spec
    report = validate_spec(new_draft)
    proposal.validation_report = report.to_dict()
    if not report.ok:
        proposal.status = "draft"
    await db.commit()

    logger.info(f"created proposal {proposal.id} from external PR #{event.pr_number}")


async def handle_pr_review(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """PR review (comment / approve / request_changes) → 同步到 ProposalReview"""
    app = await _resolve_application(db, conn=conn, repo_full_path=event.repo_full_path)
    if not app:
        return

    pr_url_pattern = f"%/{event.pr_number}"
    proposal = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.git_pr_url.like(pr_url_pattern),
        )
    )).scalar_one_or_none()
    if not proposal:
        return

    actor_user = None
    if event.actor_username:
        actor_user = (await db.execute(
            select(User).where(User.username == event.actor_username)
        )).scalar_one_or_none()

    review = ProposalReview(
        proposal_id=proposal.id,
        reviewer_id=actor_user.id if actor_user else app.created_by,
        action=event.review_action or "comment",
        body=event.review_body,
    )
    db.add(review)

    if event.review_action == "approve":
        proposal.status = "approved"
    elif event.review_action == "request_changes":
        proposal.status = "changes_requested"
    await db.commit()
