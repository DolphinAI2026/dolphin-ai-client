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


def build_authed_url(provider: str, remote_url: str, token: str) -> str:
    """把 PAT 注入 https remote URL。仅内存用,绝不持久化。"""
    if not remote_url.startswith("https://"):
        return remote_url  # ssh/本地路径直接用(测试本地 bare 仓走这条)
    rest = remote_url[len("https://") :]
    if provider == "gitlab":
        return f"https://oauth2:{token}@{rest}"
    return f"https://{token}@{rest}"  # github 及默认


async def ls_remote(ws_path: Path, authed_url: str) -> None:
    """验证远程仓可达(git ls-remote 即使空仓也成功,比 fetch 更安全)。"""
    await _git_checked(ws_path, "ls-remote", authed_url)


async def fetch(ws_path: Path, authed_url: str) -> None:
    await _git_checked(ws_path, "fetch", authed_url)


async def push(ws_path: Path, authed_url: str, branch: str) -> None:
    await _git_checked(ws_path, "push", authed_url, f"HEAD:{branch}")


async def pull(ws_path: Path, authed_url: str, branch: str) -> None:
    await _git_checked(ws_path, "pull", "--no-rebase", authed_url, branch)


async def remote_status(ws_path: Path) -> dict:
    code, out, _ = await _git(ws_path, "rev-list", "--left-right", "--count", "@{upstream}...HEAD")
    if code != 0:  # 无 upstream
        return {"ahead": 0, "behind": 0}
    parts = out.split()
    return {"behind": int(parts[0]), "ahead": int(parts[1])} if len(parts) == 2 else {"ahead": 0, "behind": 0}
