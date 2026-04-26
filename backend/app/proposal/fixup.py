"""Phase E Task 4 — partial apply 失败时自动开 fix-up ChangeProposal。

满足 spec D7 决策：之前 Phase B v1 仅记 status=apply_failed；现在 fork 当前
draft + create 新 ChangeProposal 让用户能继续 fix。

逻辑：
1. 失败的 proposal.status = 'apply_failed'，draft Spec 已经部分应用（e.g. 创建
   了 model A，但 model B 失败）。draft 仍是"目标状态"，但 canonical 应该已经
   被部分推进（如果 IncrementalExecutor 实现了部分提交）。
2. fix-up proposal：fork 当前 draft → 新 draft（避免共享行），创建新 ChangeProposal
   引用同一 application，title=\"fix-up: <原 title>\"，description 含
   ExecutionResult.errors 摘要 + 失败 ops 列表。
3. 不自动 promote — 用户人工查看后决定（safer）。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.incremental_executor import ExecutionResult
from app.models.collaboration import ChangeProposal
from app.proposal.persistence import create_proposal
from app.spec.persistence import fork_canonical_to_draft, load_spec


async def create_fixup_proposal(
    db: AsyncSession,
    *,
    failed_proposal: ChangeProposal,
    exec_result: ExecutionResult,
    tenant_id: int,
) -> Optional[str]:
    """为失败的 apply 自动创建 fix-up proposal。

    返回新 proposal.id，或 None（如无法 fork — e.g. draft 已被删除）。
    """
    failed_draft = await load_spec(db, failed_proposal.draft_spec_id, tenant_id=tenant_id)
    if not failed_draft:
        return None

    # fork 一份新 draft（避免共享同一 Spec.id 行）
    new_draft = await fork_canonical_to_draft(
        db,
        canonical=failed_draft,
        user_id=failed_proposal.created_by,
        tenant_id=tenant_id,
    )

    # 失败摘要
    errors_list = list(exec_result.errors or [])
    errors_summary = "\n".join(f"- {e}" for e in errors_list[:10])

    journal_lines: list[str] = []
    for entry in (exec_result.journal.entries or []):
        marker = "✓" if entry.platform_id else "✗"
        journal_lines.append(
            f"{marker} {entry.operation} {entry.resource_type}:{entry.resource_code}"
        )
    journal_block = "\n".join(journal_lines) if journal_lines else "（无 journal entries）"

    description = (
        f"⚠ 自动创建的 fix-up proposal，源自失败的 apply：[{failed_proposal.id}] "
        f"{failed_proposal.title}\n\n"
        f"### 失败原因\n{errors_summary or '（无 errors，但 success=False）'}\n\n"
        f"### 已执行的操作（部分成功 ✓ / 失败 ✗）\n{journal_block}\n\n"
        f"---\n请人工评审：哪些 ops 已完成（不需重做）、哪些需要重试 / 调整后重新 apply。"
    )

    fixup = await create_proposal(
        db,
        application_id=failed_proposal.application_id,
        draft_spec_id=new_draft.id,
        base_canonical_spec_id=failed_proposal.base_canonical_spec_id,
        title=f"fix-up: {failed_proposal.title}",
        description=description,
        created_by=failed_proposal.created_by,
        status="draft",  # 不自动 promote — 等人工检查
    )
    return fixup.id
