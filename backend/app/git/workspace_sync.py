"""Workspace ↔ repo workspaces/<id>/ 子目录同步（v1 单向 push）

Phase D Task 5。

push_workspace_to_repo：把 workspace_data/<workspace_id>/ 下的所有 utf-8
文本文件收集起来，commit 到 repo 的 code/workspace-<id> 分支，路径前缀
workspaces/<id>/。跳过 node_modules/dist/__pycache__/.git/.cache 等目录。

反向同步（repo push → workspace 文件）留 v2，靠 webhook 触发。
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application
from app.models.collaboration import GitConnection
from app.git.connection import make_provider
from app.git.provider.base import GitFile

logger = logging.getLogger(__name__)


# 默认 workspace 根：复用 app.coding.workspace 的 WORKSPACE_ROOT（项目根/workspaces）
def _default_workspace_root() -> Path:
    try:
        from app.coding.workspace import WORKSPACE_ROOT
        return Path(WORKSPACE_ROOT)
    except Exception:
        # 回退：repo_root/workspaces（与 LEGACY_WORKSPACE_ROOT 同等）
        return Path(__file__).resolve().parents[2] / "workspaces"


SKIP_DIRS = {"node_modules", "dist", ".git", "__pycache__", ".cache"}


def _repo_full_path_from_url(git_repo_url: str) -> str:
    parts = git_repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"无法从 git_repo_url 解析 owner/repo: {git_repo_url}")
    return f"{parts[-2]}/{parts[-1]}"


async def push_workspace_to_repo(
    db: AsyncSession,
    *,
    application: Application,
    workspace_id: str,
    workspace_root: Optional[Path] = None,
) -> dict:
    """把 workspace 文件推到 repo 的 workspaces/<id>/ 子目录。

    返回 {status, branch, commit_sha, file_count} 或 {status: noop, reason}。
    """
    if not application.git_repo_url:
        raise RuntimeError("应用未绑定 git repo")
    if not getattr(application, "project_id", None):
        raise RuntimeError("应用未关联 project，无法找 GitConnection")

    conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == application.project_id)
    )).scalar_one_or_none()
    if not conn:
        raise RuntimeError("project 未连接 git")

    root = workspace_root if workspace_root is not None else _default_workspace_root()
    ws_dir = Path(root) / workspace_id
    if not ws_dir.exists() or not ws_dir.is_dir():
        raise RuntimeError(f"workspace {workspace_id} 不存在于 {ws_dir}")

    # 收集文件（仅 utf-8 文本；跳过 SKIP_DIRS）
    files: list[GitFile] = []
    for current_root, dirs, fnames in os.walk(ws_dir):
        # in-place 修剪以避免下钻
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in fnames:
            full = Path(current_root) / fn
            try:
                content = full.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # 二进制或读不到 → 跳
            rel = full.relative_to(ws_dir)
            files.append(GitFile(
                path=f"workspaces/{workspace_id}/{rel.as_posix()}",
                content=content,
            ))

    if not files:
        return {"status": "noop", "reason": "no text files found"}

    provider = make_provider(conn)
    repo_full_path = _repo_full_path_from_url(application.git_repo_url)
    branch = f"code/workspace-{workspace_id}"
    commit = await provider.commit_files(
        repo_full_path=repo_full_path,
        branch=branch,
        message=f"workspace {workspace_id} sync from Builder",
        files=files,
    )
    return {
        "status": "ok",
        "branch": branch,
        "commit_sha": commit.sha,
        "file_count": len(files),
    }
