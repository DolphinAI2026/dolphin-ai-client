"""GitHub provider — 实现 GitProvider 接口（PAT + OAuth token 都兼容）"""
from __future__ import annotations
import base64

import httpx

from .base import CommitInfo, GitFile, PullRequestInfo


GITHUB_API_BASE = "https://api.github.com"


class GitHubProvider:
    """GitHub REST API v3 client.

    用法:
        provider = GitHubProvider(access_token='ghp_...')

    认证 header 用 `Authorization: token <token>` —— PAT 与 OAuth user token 通用。
    """
    name = "github"

    def __init__(self, access_token: str, api_base: str = GITHUB_API_BASE):
        self.token = access_token
        self.api_base = api_base.rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self, method: str, path: str, *, allow_404: bool = False, **kwargs,
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method, f"{self.api_base}{path}", headers=self._headers(), **kwargs,
            )
            if resp.status_code == 404 and allow_404:
                return resp
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"GitHub API {method} {path} failed: {resp.status_code} {resp.text}"
                )
            return resp

    async def get_repo(self, repo_full_path: str) -> dict | None:
        owner, repo = _split_repo(repo_full_path)
        try:
            resp = await self._request("GET", f"/repos/{owner}/{repo}")
            return resp.json()
        except RuntimeError:
            return None

    async def create_repo(self, *, group_or_org: str, name: str, description: str) -> str:
        """v1 简化：只支持 org-owned repo（user-owned 留 v2）。"""
        body = {
            "name": name,
            "description": description,
            "private": True,
            "auto_init": True,
        }
        resp = await self._request("POST", f"/orgs/{group_or_org}/repos", json=body)
        data = resp.json()
        return data.get("full_name", f"{group_or_org}/{name}")

    async def commit_files(
        self, *, repo_full_path: str, branch: str, message: str, files: list[GitFile],
    ) -> CommitInfo:
        """单文件循环 PUT /contents/{path}（v1 简化，每 file 一个 commit）。

        - 先 GET /contents/{path}?ref={branch} 拿 sha；404 即新建
        - 如果 branch 不存在，先基于 main 创建
        """
        owner, repo = _split_repo(repo_full_path)

        # 确保 branch 存在
        await self._ensure_branch(owner, repo, branch)

        last_commit_sha = ""
        last_commit_url = ""
        for f in files:
            # 拿现有 sha（如有）
            existing = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/contents/{f.path}",
                params={"ref": branch},
                allow_404=True,
            )
            put_body: dict = {
                "message": message,
                "content": base64.b64encode(f.content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            }
            if existing.status_code == 200:
                put_body["sha"] = existing.json().get("sha")
            resp = await self._request(
                "PUT",
                f"/repos/{owner}/{repo}/contents/{f.path}",
                json=put_body,
            )
            data = resp.json()
            commit = data.get("commit", {})
            last_commit_sha = commit.get("sha") or last_commit_sha
            last_commit_url = commit.get("html_url") or last_commit_url

        return CommitInfo(sha=last_commit_sha, url=last_commit_url)

    async def _ensure_branch(self, owner: str, repo: str, branch: str) -> None:
        ref_resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
            allow_404=True,
        )
        if ref_resp.status_code == 200:
            return
        # 不存在 — 基于 main 创建
        main_resp = await self._request(
            "GET", f"/repos/{owner}/{repo}/git/refs/heads/main",
        )
        main_sha = main_resp.json()["object"]["sha"]
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": main_sha},
        )

    async def create_pull_request(
        self, *, repo_full_path: str, source_branch: str, target_branch: str,
        title: str, description: str,
    ) -> PullRequestInfo:
        owner, repo = _split_repo(repo_full_path)
        resp = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={
                "title": title,
                "body": description,
                "head": source_branch,
                "base": target_branch,
            },
        )
        data = resp.json()
        return PullRequestInfo(
            id=str(data["id"]),
            number=data["number"],
            url=data["html_url"],
            state=data.get("state", "open"),
        )

    async def merge_pull_request(self, *, repo_full_path: str, pr_number: int) -> CommitInfo:
        owner, repo = _split_repo(repo_full_path)
        resp = await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/merge",
        )
        data = resp.json()
        return CommitInfo(sha=data.get("sha", ""), url="")

    async def add_tag(self, *, repo_full_path: str, tag: str, ref: str, message: str = "") -> str:
        owner, repo = _split_repo(repo_full_path)
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/tags/{tag}", "sha": ref},
        )
        return tag

    async def add_pr_comment(self, *, repo_full_path: str, pr_number: int, body: str) -> None:
        owner, repo = _split_repo(repo_full_path)
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            json={"body": body},
        )

    async def read_file(self, *, repo_full_path: str, path: str, ref: str) -> str:
        owner, repo = _split_repo(repo_full_path)
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )
        data = resp.json()
        return base64.b64decode(data["content"]).decode("utf-8")


def _split_repo(repo_full_path: str) -> tuple[str, str]:
    parts = repo_full_path.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"GitHub repo full path must be 'owner/repo', got: {repo_full_path}")
    return parts[0], parts[1]
