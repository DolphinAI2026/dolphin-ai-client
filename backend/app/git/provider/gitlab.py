"""GitLab provider — 实现 GitProvider 接口"""
from __future__ import annotations
from urllib.parse import quote

import httpx

from .base import CommitInfo, GitFile, PullRequestInfo


class GitLabProvider:
    """GitLab REST API v4 client.

    用法:
        provider = GitLabProvider(host='https://gitlab.com', access_token='glpat-...')
    """
    name = "gitlab"

    def __init__(self, host: str, access_token: str):
        self.host = host.rstrip("/")
        self.token = access_token
        self.api_base = f"{self.host}/api/v4"

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self.token, "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method, f"{self.api_base}{path}", headers=self._headers(), **kwargs,
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"GitLab API {method} {path} failed: {resp.status_code} {resp.text}"
                )
            return resp

    async def get_repo(self, repo_full_path: str) -> dict | None:
        try:
            resp = await self._request(
                "GET", f"/projects/{quote(repo_full_path, safe='')}",
            )
            return resp.json()
        except RuntimeError:
            return None

    async def create_repo(self, *, group_or_org: str, name: str, description: str) -> str:
        # GitLab：先查 group id
        gresp = await self._request(
            "GET", f"/groups/{quote(group_or_org, safe='')}",
        )
        group_id = gresp.json()["id"]
        body = {
            "name": name,
            "namespace_id": group_id,
            "description": description,
            "visibility": "private",
            "initialize_with_readme": True,
            "default_branch": "main",
        }
        resp = await self._request("POST", "/projects", json=body)
        return resp.json()["path_with_namespace"]

    async def commit_files(
        self, *, repo_full_path: str, branch: str, message: str, files: list[GitFile],
    ) -> CommitInfo:
        encoded_repo = quote(repo_full_path, safe='')
        # 检查 branch 是否存在；不存在则基于 main 创建
        try:
            await self._request(
                "GET",
                f"/projects/{encoded_repo}/repository/branches/{quote(branch, safe='')}",
            )
        except RuntimeError:
            await self._request(
                "POST",
                f"/projects/{encoded_repo}/repository/branches",
                params={"branch": branch, "ref": "main"},
            )

        # 用 commits API 一次提交多个文件
        actions = []
        for f in files:
            # 检查 file 是否存在决定 action 是 create 还是 update
            try:
                await self._request(
                    "GET",
                    f"/projects/{encoded_repo}/repository/files/{quote(f.path, safe='')}",
                    params={"ref": branch},
                )
                action = "update"
            except RuntimeError:
                action = "create"
            actions.append({
                "action": action,
                "file_path": f.path,
                "content": f.content,
            })

        resp = await self._request(
            "POST",
            f"/projects/{encoded_repo}/repository/commits",
            json={"branch": branch, "commit_message": message, "actions": actions},
        )
        data = resp.json()
        return CommitInfo(sha=data["id"], url=data.get("web_url", ""))

    async def create_pull_request(
        self, *, repo_full_path: str, source_branch: str, target_branch: str,
        title: str, description: str,
    ) -> PullRequestInfo:
        resp = await self._request(
            "POST",
            f"/projects/{quote(repo_full_path, safe='')}/merge_requests",
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
            },
        )
        data = resp.json()
        return PullRequestInfo(
            id=str(data["id"]), number=data["iid"], url=data["web_url"],
            state=data.get("state", "opened"),
        )

    async def merge_pull_request(self, *, repo_full_path: str, pr_number: int) -> CommitInfo:
        resp = await self._request(
            "PUT",
            f"/projects/{quote(repo_full_path, safe='')}/merge_requests/{pr_number}/merge",
            json={"squash": False},
        )
        data = resp.json()
        return CommitInfo(
            sha=data.get("merge_commit_sha") or data.get("sha", ""),
            url=data.get("web_url", ""),
        )

    async def add_tag(self, *, repo_full_path: str, tag: str, ref: str, message: str = "") -> str:
        resp = await self._request(
            "POST",
            f"/projects/{quote(repo_full_path, safe='')}/repository/tags",
            params={"tag_name": tag, "ref": ref, "message": message or tag},
        )
        return resp.json()["name"]

    async def add_pr_comment(self, *, repo_full_path: str, pr_number: int, body: str) -> None:
        await self._request(
            "POST",
            f"/projects/{quote(repo_full_path, safe='')}/merge_requests/{pr_number}/notes",
            json={"body": body},
        )

    async def read_file(self, *, repo_full_path: str, path: str, ref: str) -> str:
        import base64
        resp = await self._request(
            "GET",
            f"/projects/{quote(repo_full_path, safe='')}/repository/files/{quote(path, safe='')}",
            params={"ref": ref},
        )
        data = resp.json()
        return base64.b64decode(data["content"]).decode("utf-8")

    async def revert_commit(self, *, repo_full_path: str, branch: str, commit_sha: str) -> None:
        """GitLab 原生 revert API：POST /projects/{id}/repository/commits/{sha}/revert"""
        await self._request(
            "POST",
            f"/projects/{quote(repo_full_path, safe='')}/repository/commits/{commit_sha}/revert",
            json={"branch": branch},
        )

    async def get_branch_head(self, *, repo_full_path: str, branch: str) -> str:
        """返回 branch HEAD commit id：GET /projects/{id}/repository/branches/{branch}"""
        resp = await self._request(
            "GET",
            f"/projects/{quote(repo_full_path, safe='')}/repository/branches/{quote(branch, safe='')}",
        )
        return resp.json()["commit"]["id"]
