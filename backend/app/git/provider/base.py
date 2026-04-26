"""Git provider 抽象 — 让 GitLab / GitHub 暴露统一接口"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass
class GitFile:
    path: str       # 相对 repo 根 路径
    content: str    # utf-8 文本（二进制留 v2）


@dataclass
class CommitInfo:
    sha: str
    url: str


@dataclass
class PullRequestInfo:
    id: str          # provider 内部 id
    number: int      # PR/MR number
    url: str
    state: str       # open / merged / closed


class GitProvider(Protocol):
    """所有 git 平台必须实现的接口（最小集）"""
    name: str  # 'gitlab' | 'github'

    async def create_repo(self, *, group_or_org: str, name: str, description: str) -> str:
        """创建 repo，返回 repo full path（如 group/repo-name）"""
        ...

    async def get_repo(self, repo_full_path: str) -> dict | None:
        """查 repo 是否存在；返回 metadata 或 None"""
        ...

    async def commit_files(
        self, *, repo_full_path: str, branch: str, message: str, files: list[GitFile],
    ) -> CommitInfo:
        """commit + push 一组文件到 branch（branch 不存在则建）"""
        ...

    async def create_pull_request(
        self, *, repo_full_path: str, source_branch: str, target_branch: str,
        title: str, description: str,
    ) -> PullRequestInfo:
        ...

    async def merge_pull_request(self, *, repo_full_path: str, pr_number: int) -> CommitInfo:
        ...

    async def add_tag(self, *, repo_full_path: str, tag: str, ref: str, message: str = "") -> str:
        ...

    async def add_pr_comment(self, *, repo_full_path: str, pr_number: int, body: str) -> None:
        ...

    async def read_file(self, *, repo_full_path: str, path: str, ref: str) -> str:
        """读 repo 中指定 ref（branch/tag/sha）的文件内容（utf-8 文本）"""
        ...

    async def revert_commit(self, *, repo_full_path: str, branch: str, commit_sha: str) -> None:
        """Revert merge commit on given branch（GitLab native API；GitHub force-push parent）"""
        ...

    async def get_branch_head(self, *, repo_full_path: str, branch: str) -> str:
        """返回指定 branch HEAD 的 commit sha（drift 检测用）"""
        ...
