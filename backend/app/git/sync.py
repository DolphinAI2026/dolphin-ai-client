"""ChangeProposal git 同步：promote / apply 时 push 到 git"""
from __future__ import annotations
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application
from app.models.collaboration import ChangeProposal, GitConnection
from app.spec.persistence import load_spec
from app.spec.converter import spec_to_config
from app.git.connection import make_provider
from app.git.provider.base import GitFile


async def push_proposal_branch(
    db: AsyncSession, *, proposal: ChangeProposal, application: Application,
) -> tuple[str, str] | None:
    """promote 时：把 draft 推到 spec/proposal-<id> 分支 + open MR/PR

    返回 (branch_name, pr_url)。如 application 没绑 git 或 connection 不存在，返回 None（noop）。
    """
    if not application.git_repo_url:
        return None

    git_conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == application.project_id)
    )).scalar_one_or_none()
    if not git_conn:
        return None

    provider = make_provider(git_conn)
    repo_full_path = _extract_repo_path(application.git_repo_url, git_conn.host)

    draft = await load_spec(db, proposal.draft_spec_id, tenant_id=application.tenant_id)
    if not draft:
        return None

    branch_name = f"spec/proposal-{proposal.id[-8:]}"
    files = [
        GitFile(
            path="spec/canonical.json",
            content=json.dumps(draft.model_dump(mode="json"), indent=2, ensure_ascii=False),
        ),
        GitFile(
            path="spec/canonical.md",
            content=_render_md(draft, proposal),
        ),
    ]
    await provider.commit_files(
        repo_full_path=repo_full_path, branch=branch_name,
        message=f"proposal: {proposal.title}",
        files=files,
    )
    pr = await provider.create_pull_request(
        repo_full_path=repo_full_path,
        source_branch=branch_name,
        target_branch=application.git_default_branch or "main",
        title=proposal.title,
        description=proposal.description or "（无描述）",
    )
    return (branch_name, pr.url)


def _extract_repo_path(git_repo_url: str, host: str) -> str:
    """从 git_repo_url（含 host）拆出 group/repo 形式"""
    # git_repo_url 形如 'https://github.com/org/repo' 或 'https://gitlab.com/group/repo'
    host_stripped = host.rstrip("/")
    if git_repo_url.startswith(host_stripped):
        return git_repo_url[len(host_stripped):].lstrip("/")
    # fallback：取 host 后的两段
    parts = git_repo_url.rstrip("/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else git_repo_url


def _render_md(draft, proposal) -> str:
    return (
        f"# {draft.goal.title if draft.goal else 'untitled'}\n\n"
        f"## 提案\n{proposal.title}\n\n"
        f"## 描述\n{proposal.description or '（无）'}\n\n"
        f"## SPEC\n```json\n{json.dumps(spec_to_config(draft), indent=2, ensure_ascii=False)}\n```\n"
    )
