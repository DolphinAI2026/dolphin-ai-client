"""代码会话工作区的本地 git 操作(P1:无远程,纯本地分支)。

薄封装 async git CLI。工作区本就是 git 仓(改动对比的 baseline 用它)。
设计见 docs/superpowers/specs/2026-06-25-code-session-git-workspace-design.md。
"""
from __future__ import annotations

import asyncio
from pathlib import Path


class GitError(Exception):
    """git 命令非零退出。"""


async def _git(ws_path: Path, *args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(ws_path), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def _git_checked(ws_path: Path, *args: str) -> str:
    code, out, err = await _git(ws_path, *args)
    if code != 0:
        raise GitError(f"git {' '.join(args)} 失败:{(err or out).strip()[:300]}")
    return out


async def current_branch(ws_path: Path) -> str:
    return (await _git_checked(ws_path, "rev-parse", "--abbrev-ref", "HEAD")).strip()


async def is_dirty(ws_path: Path) -> bool:
    out = await _git_checked(ws_path, "status", "--porcelain")
    return bool(out.strip())


async def list_local_branches(ws_path: Path) -> list[str]:
    out = await _git_checked(ws_path, "branch", "--format=%(refname:short)")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


async def checkout(ws_path: Path, name: str, create: bool = False) -> None:
    args = ["checkout"] + (["-b"] if create else []) + [name]
    await _git_checked(ws_path, *args)


async def status(ws_path: Path) -> dict:
    return {
        "branch": await current_branch(ws_path),
        "dirty": await is_dirty(ws_path),
        "has_remote": False,  # P1 无远程;P2 接 workspace_git_remote 后改真值
    }
