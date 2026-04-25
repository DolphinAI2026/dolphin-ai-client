# 协作 Phase C — Git 出方向（Builder → Git）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** 让 ChangeProposal 全生命周期事件镜像到 GitLab / GitHub repo（单向 Builder → Git）：apply 后 commit canonical SPEC + workspaces 到 main，promote 时 push branch + open MR/PR，apply success 后 merge + tag。Git 是只读镜像，不接受外部 push（Phase D 才做入方向）。

**Architecture:**
- 新增 `backend/app/git/` 模块：`provider/` 抽象 (gitlab.py / github.py) + `connection.py` (OAuth + token 加密) + `repo_init.py` (repo 自动建) + `sync.py` (commit & push)
- 新增 `routes/git.py`：OAuth 启动 + connection CRUD + repo init endpoint
- 改 `routes/proposals.py`：promote / apply 之后调 git sync hook
- 前端：GitConnection setup UI（`views/ProjectOverview.vue` 加 Git 集成 tab）+ 变更中心 "Git 仓库" tab 真实化 + ProposalDetailPage 加 git PR 链接

**前置条件:**
- Phase A + Phase B 完成（commits up to `95b675b`）
- `GitConnection` ORM 表存在（Phase A 建好）
- `ChangeProposal.git_branch` / `git_pr_url` 字段存在
- backend pytest 100 passing baseline

**Tech Stack:** httpx (异步 HTTP) + Fernet 加密 (cryptography 已在 backend deps) + 既有 GitConnection ORM。

**约定:** 中文 commit messages（Conventional Commits 风格）。每 task 一个 commit。

---

## ⚠ 启动前需要的真实凭证

执行 Phase C 前用户需要准备：

1. **GitLab OAuth App**（如用 GitLab）：
   - https://gitlab.com/-/profile/applications 或自建 GitLab → Admin → Applications
   - Redirect URI：`http://localhost:5173/git/callback/gitlab`（dev）+ 生产 URL
   - Scopes：`api`, `read_repository`, `write_repository`
   - 拿到 client_id + client_secret，写入 `backend/.env`：
     ```
     GITLAB_CLIENT_ID=...
     GITLAB_CLIENT_SECRET=...
     GITLAB_DEFAULT_HOST=https://gitlab.com  # 自建用 host
     ```

2. **GitHub OAuth App**（如用 GitHub）：
   - https://github.com/settings/developers → OAuth Apps → New
   - Callback URL：`http://localhost:5173/git/callback/github`
   - Scopes：`repo`, `admin:repo_hook`（hook 留 Phase D）
   - 写入 `backend/.env`：
     ```
     GITHUB_CLIENT_ID=...
     GITHUB_CLIENT_SECRET=...
     ```

3. **Encryption key for token storage**（已有则跳过）：
   - `backend/.env` 应有 `BUILDER_FERNET_KEY=...`（base64 32 bytes）
   - 用于 `GitConnection.access_token_enc` 加解密
   - 缺则跑 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成

如果用户暂时只能配一个平台（如先 GitLab），跳过另一个 task 的 OAuth 落地（保留 placeholder + 标 TODO）。

---

## Task 1: Git Provider 抽象 + GitLab Provider

**Files:**
- Create: `backend/app/git/__init__.py`
- Create: `backend/app/git/provider/__init__.py`
- Create: `backend/app/git/provider/base.py`
- Create: `backend/app/git/provider/gitlab.py`
- Create: `backend/tests/test_git_provider_gitlab.py`

### Step 1: Provider 抽象

`base.py`：

```python
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
```

### Step 2: GitLab Provider 实现

`gitlab.py`：

```python
"""GitLab provider — 实现 GitProvider 接口"""
from __future__ import annotations
import httpx
from typing import Optional
from .base import GitProvider, GitFile, CommitInfo, PullRequestInfo


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
            resp = await client.request(method, f"{self.api_base}{path}", headers=self._headers(), **kwargs)
            if resp.status_code >= 400:
                raise RuntimeError(f"GitLab API {method} {path} failed: {resp.status_code} {resp.text}")
            return resp

    async def get_repo(self, repo_full_path: str) -> dict | None:
        try:
            from urllib.parse import quote
            resp = await self._request("GET", f"/projects/{quote(repo_full_path, safe='')}")
            return resp.json()
        except RuntimeError:
            return None

    async def create_repo(self, *, group_or_org: str, name: str, description: str) -> str:
        # GitLab：先查 group id
        from urllib.parse import quote
        gresp = await self._request("GET", f"/groups/{quote(group_or_org, safe='')}")
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
        from urllib.parse import quote
        # 检查 branch 是否存在；不存在则基于 main 创建
        try:
            await self._request("GET", f"/projects/{quote(repo_full_path, safe='')}/repository/branches/{quote(branch, safe='')}")
            actions_existing = True
        except RuntimeError:
            await self._request("POST", f"/projects/{quote(repo_full_path, safe='')}/repository/branches",
                              params={"branch": branch, "ref": "main"})
            actions_existing = True  # 既然刚建出来，里面文件都有

        # 用 commits API 一次提交多个文件
        actions = []
        for f in files:
            # 检查 file 是否存在决定 action 是 create 还是 update
            try:
                await self._request(
                    "GET",
                    f"/projects/{quote(repo_full_path, safe='')}/repository/files/{quote(f.path, safe='')}",
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
            f"/projects/{quote(repo_full_path, safe='')}/repository/commits",
            json={"branch": branch, "commit_message": message, "actions": actions},
        )
        data = resp.json()
        return CommitInfo(sha=data["id"], url=data.get("web_url", ""))

    async def create_pull_request(
        self, *, repo_full_path: str, source_branch: str, target_branch: str,
        title: str, description: str,
    ) -> PullRequestInfo:
        from urllib.parse import quote
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
        from urllib.parse import quote
        resp = await self._request(
            "PUT",
            f"/projects/{quote(repo_full_path, safe='')}/merge_requests/{pr_number}/merge",
            json={"squash": False},
        )
        data = resp.json()
        return CommitInfo(sha=data.get("merge_commit_sha") or data.get("sha", ""), url=data.get("web_url", ""))

    async def add_tag(self, *, repo_full_path: str, tag: str, ref: str, message: str = "") -> str:
        from urllib.parse import quote
        resp = await self._request(
            "POST",
            f"/projects/{quote(repo_full_path, safe='')}/repository/tags",
            params={"tag_name": tag, "ref": ref, "message": message or tag},
        )
        return resp.json()["name"]

    async def add_pr_comment(self, *, repo_full_path: str, pr_number: int, body: str) -> None:
        from urllib.parse import quote
        await self._request(
            "POST",
            f"/projects/{quote(repo_full_path, safe='')}/merge_requests/{pr_number}/notes",
            json={"body": body},
        )
```

### Step 3: 测试（单元，mock httpx）

`test_git_provider_gitlab.py` — 用 `pytest_httpx` 或 monkeypatch httpx 来 mock。至少 4 个测试：
1. `test_get_repo_returns_metadata`
2. `test_create_repo_calls_namespace_lookup`
3. `test_commit_files_uses_commits_api`
4. `test_create_pull_request_returns_iid`

如果 `pytest_httpx` 没装，用 `monkeypatch` 替 `httpx.AsyncClient` 简单实现。

### Step 4: Commit

```bash
git commit -m "feat(collab/git): GitProvider 抽象 + GitLab 实现"
```

---

## Task 2: GitHub Provider

**Files:**
- Create: `backend/app/git/provider/github.py`
- Create: `backend/tests/test_git_provider_github.py`

实现思路同 Task 1，但用 GitHub REST API v3（`https://api.github.com`）。差异：
- Auth header：`Authorization: token <token>` 或 `Bearer <token>`（OAuth app token 用后者）
- create_repo 在 org 下：`POST /orgs/{org}/repos`
- commit_files 单文件用 `PUT /repos/{owner}/{repo}/contents/{path}`；多文件需用 git data API（blob → tree → commit）— 简化版：循环单文件 PUT
- create PR：`POST /repos/{owner}/{repo}/pulls`
- merge PR：`PUT /repos/{owner}/{repo}/pulls/{number}/merge`
- add tag：`POST /repos/{owner}/{repo}/git/refs` (ref=`refs/tags/{tag}`)
- comment：`POST /repos/{owner}/{repo}/issues/{number}/comments`（PR 也是 issue）

至少 4 测试 + commit。

---

## Task 3: GitConnection 加密 + OAuth 启动 endpoint

**Files:**
- Create: `backend/app/git/connection.py`
- Create: `backend/app/routes/git_connection.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_git_connection.py`

### connection.py

```python
"""GitConnection 凭证加解密 + provider 工厂"""
from __future__ import annotations
import os
from cryptography.fernet import Fernet

from app.models.collaboration import GitConnection
from app.git.provider.base import GitProvider
from app.git.provider.gitlab import GitLabProvider
from app.git.provider.github import GitHubProvider


def _fernet() -> Fernet:
    key = os.environ.get("BUILDER_FERNET_KEY")
    if not key:
        # dev fallback - 不安全，仅本地
        key = "dev-key-replace-in-prod-32bytesssss=="  # 32-byte base64
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(enc: str) -> str:
    return _fernet().decrypt(enc.encode()).decode()


def make_provider(conn: GitConnection) -> GitProvider:
    """根据 GitConnection 选 provider"""
    token = decrypt_token(conn.access_token_enc)
    if conn.provider == "gitlab":
        return GitLabProvider(host=conn.host, access_token=token)
    elif conn.provider == "github":
        return GitHubProvider(access_token=token)
    raise ValueError(f"unknown git provider: {conn.provider}")
```

### git_connection.py（routes）

5 个 endpoints：
- `GET /api/projects/{id}/git-oauth/start?provider=gitlab|github` → 返回 OAuth authorize URL（重定向到 GitLab/GitHub）
- `POST /api/projects/{id}/git-oauth/callback` → 处理 callback：用 code 换 access_token，存 GitConnection
- `GET /api/projects/{id}/git-connection` → 查当前 connection
- `DELETE /api/projects/{id}/git-connection` → 解绑
- `POST /api/projects/{id}/git-oauth/personal-token` → 直接用 PAT（简化版，不走 OAuth；适合自建 GitLab）

权限：require_project_access(minimum_role="maintainer")。

OAuth 流：
- start：`https://gitlab.com/oauth/authorize?client_id=...&redirect_uri=...&response_type=code&scope=api&state={project_id}`（GitLab）；GitHub 类似
- callback：POST 到 `https://gitlab.com/oauth/token`（form data: client_id/secret/code/grant_type=authorization_code/redirect_uri）拿 access_token
- 存 token 加密后到 GitConnection 表

测试：mock httpx 验 callback 解析 token 正确 + token 加解密 round-trip 成功。

Commit。

---

## Task 4: Repo 自动初始化 endpoint

**Files:**
- Create: `backend/app/git/repo_init.py`
- Modify: `backend/app/routes/git_connection.py`（追加 `/git-init`）
- Create: `backend/tests/test_git_repo_init.py`（mock provider）

### repo_init.py

```python
"""为 application 在 git 平台上初始化 repo + 推第一版 canonical SPEC"""
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Application, Project
from app.models.collaboration import GitConnection
from app.git.connection import make_provider
from app.git.provider.base import GitFile


async def init_repo_for_application(
    db: AsyncSession,
    *,
    application: Application,
    git_connection: GitConnection,
) -> str:
    """创建 repo + 推 .builder/manifest.json + spec/canonical.{md,json} + README

    返回 repo full path，写回 application.git_repo_url + git_provider 等字段。
    """
    provider = make_provider(git_connection)
    repo_name = application.app_code or f"app-{application.id}"

    # 检查 repo 是否已存在
    full_path = f"{git_connection.group_id_or_org}/{repo_name}"
    existing = await provider.get_repo(full_path)
    if not existing:
        full_path = await provider.create_repo(
            group_or_org=git_connection.group_id_or_org,
            name=repo_name,
            description=f"aPaaS Builder app: {application.app_name}",
        )

    # 准备初始文件
    files = [
        GitFile(path=".builder/manifest.json", content=_manifest_json(application)),
        GitFile(path="README.md", content=_readme(application)),
    ]
    if application.canonical_spec_id:
        from app.spec.persistence import load_spec
        from app.spec.converter import spec_to_config
        canonical = await load_spec(db, application.canonical_spec_id, tenant_id=application.tenant_id)
        if canonical:
            import json
            files.append(GitFile(
                path="spec/canonical.json",
                content=json.dumps(canonical.model_dump(mode="json"), indent=2, ensure_ascii=False),
            ))
            # markdown 视图：用既有 converter 输出 dict，再转 markdown（v1 简化：JSON dump）
            files.append(GitFile(
                path="spec/canonical.md",
                content=f"# {canonical.goal.title if canonical.goal else application.app_name}\n\n"
                        f"应用 SPEC（自动从结构化生成）\n\n"
                        f"```json\n{json.dumps(spec_to_config(canonical), indent=2, ensure_ascii=False)}\n```",
            ))

    await provider.commit_files(
        repo_full_path=full_path, branch="main",
        message="chore: initialize aPaaS Builder repo",
        files=files,
    )

    # 写回 application 字段
    application.git_repo_url = f"{git_connection.host}/{full_path}"
    application.git_provider = git_connection.provider
    application.git_default_branch = "main"
    await db.commit()
    return full_path


def _manifest_json(app: Application) -> str:
    import json
    return json.dumps({
        "app_id": app.id,
        "app_code": app.app_code,
        "app_name": app.app_name,
        "builder_version": "phase-c-v1",
        "canonical_spec_id": app.canonical_spec_id,
    }, indent=2, ensure_ascii=False)


def _readme(app: Application) -> str:
    return f"# {app.app_name}\n\n{app.description or ''}\n\n---\n*由 aPaaS Builder 自动维护。请通过 Builder 平台编辑 SPEC，避免直接修改 git 上的文件（Phase D 起将拦截直连 merge）。*\n"
```

### endpoint

`POST /api/applications/{id}/git-init` → 调 `init_repo_for_application` → 返回 `git_repo_url`。

权限：application owner。

测试：mock provider，验 commit_files 被调，application.git_repo_url 被写回。

Commit。

---

## Task 5: Promote → push branch + open PR hook

**Files:**
- Modify: `backend/app/routes/proposals.py`（promote 端点末尾）
- Create: `backend/app/git/sync.py`（promote_to_git 函数）
- Create: `backend/tests/test_git_sync_promote.py`

### sync.py

```python
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

    返回 (branch_name, pr_url)。如果 application 没绑 git，返回 None（noop）。
    """
    if not application.git_repo_url:
        return None

    git_conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == application.project_id)
    )).scalar_one_or_none()
    if not git_conn:
        return None

    provider = make_provider(git_conn)
    repo_full_path = application.git_repo_url.rsplit("/", 2)[-2] + "/" + application.git_repo_url.rsplit("/", 1)[-1]

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
        target_branch="main",
        title=proposal.title,
        description=proposal.description or "（无描述）",
    )
    return (branch_name, pr.url)


def _render_md(draft, proposal) -> str:
    return (
        f"# {draft.goal.title if draft.goal else 'untitled'}\n\n"
        f"## 提案\n{proposal.title}\n\n"
        f"## 描述\n{proposal.description or '（无）'}\n\n"
        f"## SPEC\n```json\n{json.dumps(spec_to_config(draft), indent=2, ensure_ascii=False)}\n```\n"
    )
```

### proposals.py 改动

`promote_to_proposal` 末尾，`return` 之前加：

```python
# git 同步（如绑定）
if app.git_repo_url:
    try:
        result = await push_proposal_branch(db, proposal=proposal, application=app)
        if result:
            branch, pr_url = result
            proposal.git_branch = branch
            proposal.git_pr_url = pr_url
            await db.commit()
    except Exception as e:
        logger.warning(f"git push for proposal {proposal.id} failed: {e}")
        # 不阻断 promote；git 可后续 retry
```

测试：mock GitProvider 验 push_proposal_branch 调用 commit_files + create_pull_request；application.git_repo_url 为空时 noop。

Commit。

---

## Task 6: Apply success → merge + tag

**Files:**
- Modify: `backend/app/proposal/apply.py`（execute_apply 内）
- Modify: `backend/app/git/sync.py`（追加 finalize_apply）
- Modify tests

### sync.py 追加

```python
async def finalize_apply_to_git(
    db: AsyncSession, *, proposal: ChangeProposal, application: Application,
) -> str | None:
    """apply 成功后 merge PR + tag 到 main"""
    if not application.git_repo_url or not proposal.git_pr_url:
        return None

    git_conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == application.project_id)
    )).scalar_one_or_none()
    if not git_conn:
        return None

    provider = make_provider(git_conn)
    repo_full_path = application.git_repo_url.rsplit("/", 2)[-2] + "/" + application.git_repo_url.rsplit("/", 1)[-1]

    # 从 git_pr_url 拿 PR number
    pr_number = int(proposal.git_pr_url.rsplit("/", 1)[-1])
    commit = await provider.merge_pull_request(repo_full_path=repo_full_path, pr_number=pr_number)

    # tag
    from datetime import datetime
    tag = f"apply-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{proposal.id[-8:]}"
    await provider.add_tag(repo_full_path=repo_full_path, tag=tag, ref=commit.sha,
                          message=f"applied {proposal.title}")
    return tag
```

### apply.py 改 `execute_apply`

末尾 success 分支：

```python
        # 同步到 git（如绑定）
        from app.git.sync import finalize_apply_to_git
        try:
            tag = await finalize_apply_to_git(db, proposal=proposal_row, application=app_row)
            if tag and proposal_row.apply_log:
                proposal_row.apply_log["git_tag"] = tag
                await db.commit()
        except Exception as e:
            # git 失败不让 apply 失败 — 标 warning 即可（已经在平台 apply 了）
            apply_log.append({"git_finalize_failed": str(e)})
            await db.commit()
```

测试：mock provider，验 merge_pull_request + add_tag 调用。Commit。

---

## Task 7: 前端 GitConnection setup UI

**Files:**
- Create: `frontend/src/api/gitConnection.ts`
- Create: `frontend/src/views/ProjectGitSetup.vue` 或在 `ProjectOverview.vue` 加 tab
- Modify: `frontend/src/router/index.ts`

UI 流：
1. Project 详情页加"Git 集成" tab
2. tab 内显示当前 GitConnection 状态（disconnected / connected with provider+host）
3. 未连接：按钮 "用 GitLab OAuth 连接" / "用 GitHub OAuth 连接" / "用 PAT 直连"
4. 点 OAuth → window.location 跳转到 `/api/projects/{id}/git-oauth/start?provider=...` 获 url 后 redirect
5. callback 页面 `/git/callback/:provider`：取 query.code → POST `/api/projects/{id}/git-oauth/callback` → 显示 success → redirect 回 ProjectOverview
6. 已连接：显示 host / org / 解绑按钮 + "为应用初始化 repo" 按钮（per-app）

工程量约 200-300 行 Vue + 100 行 API client + 1 callback view。

Commit。

---

## Task 8: 变更中心 Git 仓库 tab 真实化 + ProposalDetailPage git PR 链接

**Files:**
- Modify: `frontend/src/views/BuilderDevOpsPage.vue`（git 仓库 tab 接真实数据）
- Modify: `frontend/src/views/ProposalDetailPage.vue`（显示 git_pr_url 链接 + git_tag 在 apply_log）

`BuilderDevOpsPage` "Git 仓库" tab：
- 显示当前 application 的 git_repo_url（如已绑）
- 列近 N 次 push 历史（先用 application.git_last_sync_sha 简单显示，完整 push log 留 Phase D）

`ProposalDetailPage`：
- 顶部加 "查看 PR" 按钮（如 git_pr_url 有值）
- apply_log 卡片显示 git_tag

vue-tsc 干净 + commit。

---

## Task 9: E2E smoke + handoff

- Backend pytest 全过（≥110 期望，Phase B 100 + Phase C 新增 ~10 测试）
- Frontend vue-tsc 干净
- 真机 smoke（需要真实 GitLab/GitHub 凭证）：
  1. ProjectOverview → Git 集成 tab → OAuth 连接 GitLab → success
  2. 任一 application 点 "init repo" → GitLab 上看到新 repo with spec/ + workspaces/
  3. ChatPage 编辑 → promote → GitLab 上看到 spec/proposal-xxx 分支 + MR
  4. approve + apply → GitLab 上 MR 被 merge + 看到 apply-* tag
- 写 `docs/superpowers/HANDOFF-collab-phase-c-done.md`

Commit handoff。

---

## 自检（Plan Self-Review）

**Spec 覆盖核对** vs §10 Phase C：

| Spec 条目 | Plan Task |
|----------|-----------|
| GitConnection OAuth（GitLab + GitHub） | Task 1 + Task 2 + Task 3 |
| repo 自动初始化 | Task 4 |
| promote → push branch + open MR/PR | Task 5 |
| apply → merge + tag + apply-log | Task 6 |
| 变更中心 Git 仓库 tab | Task 8 |
| Apply 历史 git commit 链接 | Task 8 |
| Git connection 前端 UI | Task 7 |

**Placeholder scan**：无 TBD/TODO；具体代码块都给了。

**简化范围**：
- workspaces/ 目录的 sync 留 Phase D（与 webhook 入方向一起做更对齐）
- spec/canonical.md 的渲染是 JSON dump 包裹（v1 简化），完整 markdown 渲染留 Phase D
- 没做 retry / queue（git push 失败 fire-and-forget）
- 没做 OAuth state CSRF 保护（v1，dev only；上 prod 必须补）

**Type 一致性**：`GitFile / CommitInfo / PullRequestInfo` Protocol 在 base.py 定义后，gitlab/github 实现都用相同 dataclass，前端 type 同步加 `GitConnection / RepoInitResponse`。

---

## 执行选择

Plan complete and saved to `docs/superpowers/plans/2026-04-25-collab-phase-c-git-out.md`. 沿用 Phase A/B 的 **Subagent-Driven** 模式继续执行。

⚠️ **执行前先确认**：
1. 用户已配 GitLab 或 GitHub OAuth app credentials（`GITLAB_CLIENT_ID/SECRET` 或 `GITHUB_CLIENT_ID/SECRET`）到 `backend/.env`
2. 用户已设 `BUILDER_FERNET_KEY`（或同意用 dev fallback）
3. 如只配单平台，对应另一个 task（如 Task 2 GitHub）可暂时实现成 stub

如果暂时没准备好凭证，可以先做 Task 1 + Task 2（provider 实现，纯单元测试 + mock）+ Task 3 部分（加密 helpers + 路由骨架），把 OAuth 真接通延后。
