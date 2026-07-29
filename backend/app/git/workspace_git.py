"""代码会话工作区的本地 git 操作(P1:无远程,纯本地分支)。

薄封装 async git CLI。工作区本就是 git 仓(改动对比的 baseline 用它)。
设计见 docs/superpowers/specs/2026-06-25-code-session-git-workspace-design.md。
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from app import runtime


class GitError(Exception):
    """git 命令非零退出。"""


# 形如 scheme://user:pass@host 或 scheme://token@host 的凭证段,脱敏成 ***。
_CREDS_IN_URL = re.compile(r"(\w+://)[^/@\s]+@")


def redact_credentials(text: str) -> str:
    """把字符串里 URL 内嵌的凭证(PAT/用户名密码)替换成 ***,防 token 进日志/错误响应。"""
    return _CREDS_IN_URL.sub(r"\1***@", text)


def assert_https_remote(remote_url: str) -> None:
    """生产环境只允许 https:// 远程,挡掉 file:// / 裸本地路径 / ext:: / `-` 开头等。

    非 https 会让 git 读服务器本地文件系统(跨租户/越权读任意可读 git 仓),
    或触发危险传输。本地 bare 仓测试需显式设 ALLOW_INSECURE_GIT_REMOTE=1 放行。
    """
    if os.environ.get("ALLOW_INSECURE_GIT_REMOTE"):
        return
    u = (remote_url or "").strip()
    if not u.lower().startswith("https://") or len(u) <= len("https://"):
        raise GitError("远程仓地址必须以 https:// 开头")


async def _git(ws_path: Path, *args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(ws_path), *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **runtime.subprocess_window_kwargs(),
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def _git_checked(ws_path: Path, *args: str) -> str:
    code, out, err = await _git(ws_path, *args)
    if code != 0:
        # args 可能含注入了 PAT 的 authed_url;err/out 个别 git 版本也回显含 token 的 URL → 一律脱敏。
        msg = redact_credentials(f"git {' '.join(args)} 失败:{(err or out).strip()[:300]}")
        raise GitError(msg)
    return out


async def current_branch(ws_path: Path) -> str:
    code, out, _ = await _git(ws_path, "rev-parse", "--abbrev-ref", "HEAD")
    name = out.strip()
    if code == 0 and name and name != "HEAD":
        return name
    # 空仓/unborn branch:rev-parse 给 "HEAD" 或失败 → 用 symbolic-ref 拿默认分支名(如 main)
    code2, out2, _ = await _git(ws_path, "symbolic-ref", "--short", "HEAD")
    if code2 == 0 and out2.strip():
        return out2.strip()
    return name or "main"


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


async def clone(target_dir: Path, authed_url: str, clean_url: str) -> str:
    """从 authed_url clone 到 target_dir,然后彻底抹掉 authed_url 里的 PAT。

    git clone 会把 authed_url(含注入的 PAT)写进两处:
      1) .git/config 的 remote.origin.url —— 用 `remote set-url origin clean_url` 改掉。
      2) reflog(.git/logs/*)的 `clone: from <authed_url>` 消息 —— set-url 不清这些,
         必须删掉整个 .git/logs(workspace 基线机制只用 commit/rev-parse,不依赖 reflog)。
    两处都处理后 token 不落盘。返回默认分支名。
    target_dir clone 前不存在(git 自己建);在父目录下运行 clone。
    """
    import shutil

    await _git_checked(target_dir.parent, "clone", authed_url, str(target_dir))
    await _git_checked(target_dir, "remote", "set-url", "origin", clean_url)
    shutil.rmtree(target_dir / ".git" / "logs", ignore_errors=True)  # 抹掉 reflog 里的 PAT
    return await current_branch(target_dir)
