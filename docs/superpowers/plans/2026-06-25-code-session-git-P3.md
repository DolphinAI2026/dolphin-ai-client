# 代码会话 git — P3:从远程仓 clone 起工作区 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐任务实现。后端 TDD(本地 bare 仓当「远程」验 clone 机制);前端 build:nocheck + preview。**真·公司 GitLab clone e2e = 用户真机**(本环境无真远程)。Steps 用 `- [ ]` 勾选跟踪。

**Goal:** 「我的开发」能从公司自建 GitLab/GitHub 远程仓 clone 起一个新工作区,落地后立刻绑定远程(push/pull 即用)并进代码会话。

**Architecture:** 工作区级 git(模型 B)。新增 `POST /coding/workspaces/git/clone` 端点(无 ws_id,创建新工作区):校验 GitConnection → 解密 PAT 注入临时 URL → `git clone` → **关键:clone 后 `git remote set-url origin <clean_url>` 抹掉 .git/config 里的 token** → 写 `.workspace.json` → 落 `WorkspaceGitRemote` 绑定 → 返回 meta。前端 catalog 加「从 git 仓打开」入口 + 弹窗 → clone → `router.push('/ai-chat?workspace_id=X&mode=code')` 建/进 code 会话。复用 P1/P2 的 `workspace_git.py`、`_load_git_connection`、`WorkspaceGitRemote`、`build_authed_url`、catalog 导航范式。

**Tech Stack:** FastAPI;asyncio git CLI;`GitConnection`(collaboration.py)+ `app.crypto.decrypt_password`;`WorkspaceManager`(coding/workspace.py);Vue 3 + Element Plus 弹窗;pytest + 本地 bare 仓 fixture。

**Spec:** [2026-06-25-code-session-git-workspace-design.md](../specs/2026-06-25-code-session-git-workspace-design.md) §4(clone 端点)+ §6 P3。前置:P1+P2 已落(`workspace_git.py` 有 `build_authed_url`/`fetch`/`ls_remote`/`current_branch`;coding.py 有 `_load_git_connection`/`GitConnectRequest`/git 端点;`WorkspaceGitRemote` 表已建;catalog 有 import-zip/open-local 入口范式)。

## Global Constraints
- 工作目录 `/Users/mars/Vibe Coding/ai-builder`;后端 `cd backend && .venv/bin/python -m pytest`(改后端**必重启 run.py**,reload=False);前端 `cd frontend && npm run build:nocheck`。本地 DB 实为 SQLite。.venv 是 py3.13。
- **PAT 安全(P3 新增风险点)**:`git clone <https-with-token-url>` 会把 token 写进 `.git/config` 的 `remote.origin.url` → **clone 成功后必须立刻 `git remote set-url origin <clean_url>`(不含 token 的原始 remote_url)**。解密只在内存、用完 `del`;**绝不落 .git/config、不进日志、不回前端**。
- git remote URL 注入(复用 P2 `build_authed_url`):GitLab `https://oauth2:{token}@{host}/{path}.git`;GitHub `https://{token}@{host}/{path}.git`;非 https(本地 bare 路径,测试用)原样返回。
- clone 失败 → 清理半成品工作区目录(避免孤儿 dir),抛 400。
- 新工作区落 `WORKSPACE_ROOT`,`.workspace.json` 必含 `tenant_id` + `user_id`(否则 `list_accessible_workspaces` 严格过滤会把它隐藏)。`project_type` 用 `"git-clone"` 哨兵串(列表/展示从不构造 `ProjectType()`,前端 `groupMap` 兜底「其他」,安全)。
- cloned repo 自带 `.git` + 历史 → 不重新 init/baseline(`ensure_baseline` 见 HEAD 已存在即跳过);「本轮改动」= 工作树 vs clone HEAD,符合预期。
- 迁移:无新表(复用 P2 `WorkspaceGitRemote`)。
- **每 Task 只 commit 本 Task 文件**,精确 `git add`,绝不 `-A`/`.`,提交前 `git diff --cached --stat`。coding.py / workspace.py 若有无关未提交改动用 `git add -p` 只挑本 Task 的 hunks。
- commit message 中文 + `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

## File Structure
- `backend/app/git/workspace_git.py` — 扩 P1/P2 模块:加 `clone()`(git clone + PAT 抹除)。本地 git CLI 薄封装的归属地。
- `backend/app/coding/workspace.py` — `WorkspaceManager` 加两个纯/同步辅助:`prepare_clone_target()`(分配 ws_id + 目标路径,**不建目录**)+ `register_cloned_workspace()`(写 `.workspace.json` + 缓存路径,返回 meta)。工作区目录/元信息的归属地。
- `backend/app/routes/coding.py` — 加 `POST /workspaces/git/clone` 端点 + `CloneRepoRequest`,编排上面三件 + 落 `WorkspaceGitRemote`。git 端点的归属地。
- `frontend/src/api/coding.ts` — `codingApi.gitCloneWorkspace()`(镜像 P2 git 方法)。
- `frontend/src/views/WorkspaceCatalogPage.vue` — header 加「从 git 仓打开」按钮 + clone 弹窗 + clone 成功导航到 code 会话。
- 测试:`backend/tests/test_workspace_git_clone.py`(Task 1)、`backend/tests/test_workspace_clone_manager.py`(Task 2)、`backend/tests/test_workspace_git_clone_endpoint.py`(Task 3)、`frontend/src/views/WorkspaceCatalogPageClone.spec.ts`(Task 4)。

---

### Task 1: `workspace_git.clone()` — git clone + PAT 抹除(TDD,本地 bare 仓)

**Files:**
- Modify: `backend/app/git/workspace_git.py`(扩 P1/P2 模块,文件尾追加)
- Test: `backend/tests/test_workspace_git_clone.py`

**Interfaces:**
- Consumes: P1/P2 的 `_git`/`_git_checked`/`current_branch`/`GitError`(同文件)。
- Produces:
  - `async def clone(target_dir: Path, authed_url: str, clean_url: str) -> str`
    —— `git clone authed_url target_dir` → `git -C target_dir remote set-url origin clean_url` → 返回 clone 出来的默认分支名(`current_branch(target_dir)`)。`target_dir` clone 前**不存在**(git 自己建)。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workspace_git_clone.py
"""P3 Task 1 TDD — workspace_git.clone():git clone + 抹除 .git/config 里的 PAT。

本地 bare 仓当「远程」;authed_url 用带假 token 的本地路径形式无意义,
故直接用 bare 路径当 authed_url、另传一个 clean_url 验证 set-url 真的改了 origin。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.git.workspace_git import clone, current_branch


def _run(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """带一笔初始提交的 bare 仓(默认分支 main)。"""
    src = tmp_path / "src"
    src.mkdir()
    _run(src, "init", "-b", "main")
    _run(src, "config", "user.email", "t@t.com")
    _run(src, "config", "user.name", "t")
    (src / "README.md").write_text("hello clone")
    _run(src, "add", ".")
    _run(src, "commit", "-m", "init")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True)
    return bare


@pytest.mark.asyncio
async def test_clone_pulls_files_and_returns_branch(bare_remote: Path, tmp_path: Path):
    target = tmp_path / "ws_clone"
    branch = await clone(target, str(bare_remote), str(bare_remote))
    assert (target / "README.md").read_text() == "hello clone"
    assert branch == "main"
    assert await current_branch(target) == "main"


@pytest.mark.asyncio
async def test_clone_scrubs_token_resets_origin_to_clean_url(bare_remote: Path, tmp_path: Path):
    target = tmp_path / "ws_clone2"
    clean = "https://oauth2:NOPE@git.example.com/grp/proj.git"  # 模拟「不含真 token 的对外 URL」
    # authed_url = 真能 clone 的 bare 路径;clean_url = 落 .git/config 的对外 URL
    await clone(target, str(bare_remote), clean)
    origin = _run(target, "remote", "get-url", "origin").strip()
    assert origin == clean
    config_text = (target / ".git" / "config").read_text()
    assert str(bare_remote) not in config_text  # clone 用的 authed_url(本测里是 bare 路径)已被抹掉
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_clone.py -q`
Expected: FAIL —— `ImportError: cannot import name 'clone'`。

- [ ] **Step 3: 实现 `clone()`**(追加到 `backend/app/git/workspace_git.py` 文件尾)

```python
async def clone(target_dir: Path, authed_url: str, clean_url: str) -> str:
    """从 authed_url clone 到 target_dir,然后把 origin 改成 clean_url(抹掉 PAT)。

    git clone 会把 authed_url(含注入的 PAT)写进 .git/config 的 remote.origin.url。
    clone 成功后立刻 set-url origin clean_url,使 token 不落盘。返回默认分支名。
    """
    await _git_checked(target_dir.parent, "clone", authed_url, str(target_dir))
    await _git_checked(target_dir, "remote", "set-url", "origin", clean_url)
    return await current_branch(target_dir)
```

(注:`git clone <url> <target>` 在 target **不存在**时由 git 创建;`-C target_dir.parent` 让 clone 在父目录下运行。)

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_clone.py -q`
Expected: PASS(2 passed)。

- [ ] **Step 5: 提交**

```bash
git add backend/app/git/workspace_git.py backend/tests/test_workspace_git_clone.py
git diff --cached --stat
git commit -m "feat(git): workspace_git.clone() — git clone + 抹除 .git/config 的 PAT — 代码会话 git P3

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `WorkspaceManager` clone 工作区辅助(分配目标 + 写 meta)

**Files:**
- Modify: `backend/app/coding/workspace.py`(`WorkspaceManager` 加两方法,放在 `create_workspace` 之后即可)
- Test: `backend/tests/test_workspace_clone_manager.py`

**Interfaces:**
- Consumes: 现有 `_build_workspace_folder_name`、`_slugify_project_token`、`_normalize_display_name`、`WORKSPACE_ROOT`、`_workspace_path_cache`、`get_workspace_info`、`list_accessible_workspaces`。
- Produces:
  - `def prepare_clone_target(self, project_name: str, user_id: int) -> tuple[str, Path]`
    —— 返回 `(ws_id, ws_path)`;`ws_id = f"{user_id}_{uuid4().hex[:8]}"`;`ws_path = WORKSPACE_ROOT / folder_name`;**不创建目录**(留给 clone)。
  - `def register_cloned_workspace(self, ws_id: str, ws_path: Path, *, project_name: str, display_name: str | None, user_id: int, tenant_id: int | None, project_id: int | None, remote_url: str) -> dict`
    —— 写 `.workspace.json`(`project_type="git-clone"`, `status="ready"`, `cloned_from=remote_url`)+ `_workspace_path_cache[ws_id]=ws_path` → 返回 `get_workspace_info(ws_id)`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workspace_clone_manager.py
"""P3 Task 2 — WorkspaceManager clone 辅助:分配目标路径 + 写 meta。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.coding import workspace as ws_mod
from app.coding.workspace import WorkspaceManager


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


def test_prepare_then_register_clone_workspace(tmp_path: Path, monkeypatch):
    # 把 WORKSPACE_ROOT 指到 tmp,避免污染真实工作区根
    monkeypatch.setattr(ws_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACE_SEARCH_ROOTS", [tmp_path / "workspaces"])

    mgr = WorkspaceManager()
    ws_id, ws_path = mgr.prepare_clone_target(project_name="acme-crm", user_id=7)
    assert ws_id.startswith("7_")
    assert not ws_path.exists()  # 还没建,留给 clone

    # 模拟 clone 出一个真 git 仓(register 前 ws_path 必须已是带 .workspace 内容的目录)
    ws_path.mkdir(parents=True)
    _git(ws_path, "init", "-b", "main")
    _git(ws_path, "config", "user.email", "t@t.com")
    _git(ws_path, "config", "user.name", "t")
    (ws_path / "app.js").write_text("x")
    _git(ws_path, "add", ".")
    _git(ws_path, "commit", "-m", "c1")

    meta = mgr.register_cloned_workspace(
        ws_id, ws_path, project_name="acme-crm", display_name="Acme CRM",
        user_id=7, tenant_id=3, project_id=None, remote_url="https://git.co/g/acme.git",
    )
    assert meta["id"] == ws_id
    assert meta["project_type"] == "git-clone"
    assert meta["display_name"] == "Acme CRM"
    # .workspace.json 落盘且含 tenant_id/user_id(否则 list_accessible_workspaces 会隐藏)
    import json
    saved = json.loads((ws_path / ".workspace.json").read_text())
    assert saved["tenant_id"] == 3 and saved["user_id"] == 7
    assert saved["cloned_from"] == "https://git.co/g/acme.git"
    # 能被可访问工作区列表查到
    listed = mgr.list_accessible_workspaces(user_id=7, tenant_id=3)
    assert any(w["id"] == ws_id for w in listed)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_clone_manager.py -q`
Expected: FAIL —— `AttributeError: 'WorkspaceManager' object has no attribute 'prepare_clone_target'`。

- [ ] **Step 3: 实现两方法**(加到 `backend/app/coding/workspace.py` 的 `WorkspaceManager` 类内,`create_workspace` 之后)

```python
    def prepare_clone_target(self, project_name: str, user_id: int) -> tuple[str, "Path"]:
        """为 clone 分配 ws_id + 目标路径(不建目录,git clone 会自己建)。"""
        safe_name = self._slugify_project_token(project_name) or "cloned-repo"
        ws_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
        folder_name = self._build_workspace_folder_name(ws_id, safe_name)
        ws_path = WORKSPACE_ROOT / folder_name
        return ws_id, ws_path

    def register_cloned_workspace(
        self,
        ws_id: str,
        ws_path: "Path",
        *,
        project_name: str,
        display_name: Optional[str],
        user_id: int,
        tenant_id: Optional[int],
        project_id: Optional[int],
        remote_url: str,
    ) -> dict:
        """clone 完成后写 .workspace.json 元信息 + 缓存路径,返回 get_workspace_info。"""
        resolved_display = display_name or project_name or ws_path.name
        meta = {
            "id": ws_id,
            "folder_name": ws_path.name,
            "project_id": project_id,
            "project_type": "git-clone",   # 哨兵:非 apaas 模板类型,列表/展示从不构造 ProjectType()
            "project_name": project_name or ws_path.name,
            "display_name": resolved_display,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "status": WorkspaceStatus.READY.value,
            "cloned_from": remote_url,
        }
        (ws_path / ".workspace.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )
        self._workspace_path_cache[ws_id] = ws_path
        return self.get_workspace_info(ws_id)
```

(`uuid` / `json` / `Optional` / `WorkspaceStatus` / `WORKSPACE_ROOT` 在 workspace.py 顶部已 import;若 `Path` 未在类型注解作用域,用字符串注解 `"Path"` 即可——Path 已在文件 import。)

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_clone_manager.py -q`
Expected: PASS(1 passed)。

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/workspace.py backend/tests/test_workspace_clone_manager.py
git diff --cached --stat
git commit -m "feat(git): WorkspaceManager clone 工作区辅助(分配目标+写 meta)— 代码会话 git P3

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `POST /coding/workspaces/git/clone` 端点(编排 + 绑 WorkspaceGitRemote)

**Files:**
- Modify: `backend/app/routes/coding.py`(加 `CloneRepoRequest` + `git_clone_workspace_endpoint`,放在 P2 git 端点 `git_pull_endpoint` 之后)
- Test: `backend/tests/test_workspace_git_clone_endpoint.py`

**Interfaces:**
- Consumes: Task 1 `workspace_git.clone`;Task 2 `workspace_mgr.prepare_clone_target`/`register_cloned_workspace`;P2 `_load_git_connection`/`build_authed_url`/`decrypt_password`/`WorkspaceGitRemote`/`current_branch`;`get_auth_context`/`get_db`/`_decorate_workspace_access`。
- Produces:
  - `POST /coding/workspaces/git/clone` body `CloneRepoRequest(provider, remote_url, git_connection_id, name?, project_id?)`
    → 校验 GitConnection 归属 → 解密 token → `build_authed_url` → `prepare_clone_target` → `workspace_git.clone(ws_path, authed_url, remote_url)` → `register_cloned_workspace` → 落 `WorkspaceGitRemote(ws_id, tenant_id, user_id, provider, remote_url, default_branch, git_connection_id)` → 返回 `_decorate_workspace_access(meta, "owner")`。
  - 失败:GitError → 清理 `ws_path` + 抛 400。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_workspace_git_clone_endpoint.py
"""P3 Task 3 — clone 端点:bare 仓当远端,本地路径走 build_authed_url 非-https 分支免 PAT。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.coding import workspace as ws_mod
from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import User, Project
from app.models.collaboration import GitConnection
from app.models.tenant import Tenant
from app.models.workspace_git import WorkspaceGitRemote
from app.routes.coding import CloneRepoRequest, git_clone_workspace_endpoint


def _run(cwd: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    src = tmp_path / "src"; src.mkdir()
    _run(src, "init", "-b", "main")
    _run(src, "config", "user.email", "t@t.com"); _run(src, "config", "user.name", "t")
    (src / "main.py").write_text("print('hi')")
    _run(src, "add", "."); _run(src, "commit", "-m", "init")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "--bare", str(src), str(bare)], check=True, capture_output=True)
    return bare


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


@pytest.mark.asyncio
async def test_clone_endpoint_creates_workspace_and_binds_remote(db_session, bare_remote, tmp_path, monkeypatch):
    # WORKSPACE_ROOT → tmp,避免污染真实工作区
    monkeypatch.setattr(ws_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACE_SEARCH_ROOTS", [tmp_path / "workspaces"])

    tenant = Tenant(tenant_name="t_cl", tenant_code="t_cl"); db_session.add(tenant); await db_session.flush()
    user = User(username="cl_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    proj = Project(name="p", user_id=user.id, tenant_id=tenant.id); db_session.add(proj); await db_session.flush()
    conn = GitConnection(project_id=proj.id, provider="gitlab", host="git.example.com",
                         access_token_enc=encrypt_password("x"))
    db_session.add(conn); await db_session.flush()
    ctx = _ctx(user, tenant.id)

    body = CloneRepoRequest(provider="gitlab", remote_url=str(bare_remote),
                            git_connection_id=conn.id, name="Acme CRM")
    result = await git_clone_workspace_endpoint(body, ctx, db_session)

    ws_id = result["id"]
    # 工作区文件 clone 下来了
    from app.coding.workspace import WorkspaceManager
    ws_path = WorkspaceManager().get_workspace_path(ws_id)
    assert (ws_path / "main.py").exists()
    # .git/config 的 origin 已被改成 clean remote_url(本测 remote_url==bare 路径,断言无 token 形式即可)
    cfg = (ws_path / ".git" / "config").read_text()
    assert "@" not in cfg.split("url = ")[1].splitlines()[0]  # 无 user:token@ 形式
    # WorkspaceGitRemote 落库
    from sqlalchemy import select
    row = (await db_session.execute(
        select(WorkspaceGitRemote).where(WorkspaceGitRemote.ws_id == ws_id)
    )).scalar_one()
    assert row.provider == "gitlab"
    assert row.remote_url == str(bare_remote)
    assert row.git_connection_id == conn.id
    assert row.tenant_id == tenant.id and row.user_id == user.id


@pytest.mark.asyncio
async def test_clone_endpoint_bad_remote_cleans_up_and_400(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(ws_mod, "WORKSPACE_ROOT", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir()
    monkeypatch.setattr(ws_mod, "WORKSPACE_SEARCH_ROOTS", [tmp_path / "workspaces"])

    tenant = Tenant(tenant_name="t_bad", tenant_code="t_bad"); db_session.add(tenant); await db_session.flush()
    user = User(username="bad_user", hashed_password="x"); db_session.add(user); await db_session.flush()
    proj = Project(name="p", user_id=user.id, tenant_id=tenant.id); db_session.add(proj); await db_session.flush()
    conn = GitConnection(project_id=proj.id, provider="gitlab", host="git.example.com",
                         access_token_enc=encrypt_password("x"))
    db_session.add(conn); await db_session.flush()
    ctx = _ctx(user, tenant.id)

    from fastapi import HTTPException
    body = CloneRepoRequest(provider="gitlab", remote_url=str(tmp_path / "does-not-exist.git"),
                            git_connection_id=conn.id, name="x")
    with pytest.raises(HTTPException) as ei:
        await git_clone_workspace_endpoint(body, ctx, db_session)
    assert ei.value.status_code == 400
    # 没留下半成品工作区(clone 失败的目录被清理 → workspaces 根下无新 dir)
    leftover = [p for p in (tmp_path / "workspaces").iterdir() if p.is_dir()]
    assert leftover == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_clone_endpoint.py -q`
Expected: FAIL —— `ImportError: cannot import name 'CloneRepoRequest'`。

- [ ] **Step 3: 实现端点**(加到 `backend/app/routes/coding.py` 的 P2 git 端点之后,`git_pull_endpoint` 下面;`shutil` 已在文件内可用,若无则函数内 `import shutil`)

```python
class CloneRepoRequest(BaseModel):
    provider: str          # "github" | "gitlab"
    remote_url: str        # https://… 或本地路径(测试用)
    git_connection_id: int
    name: Optional[str] = None        # 工作区展示名,默认从 remote_url 推
    project_id: Optional[int] = None  # 可选:绑定应用


def _repo_name_from_url(remote_url: str) -> str:
    """从 remote_url 末段推一个项目名:.../grp/proj.git → proj。"""
    tail = remote_url.rstrip("/").rsplit("/", 1)[-1]
    return tail[:-4] if tail.endswith(".git") else tail or "cloned-repo"


@router.post("/workspaces/git/clone")
async def git_clone_workspace_endpoint(
    body: CloneRepoRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """从远程仓 clone 起一个新工作区,并立刻绑定远程(push/pull 即用)。"""
    import shutil

    if body.project_id:
        await require_project_access(
            db, project_id=body.project_id, user_id=ctx.user.id,
            tenant_id=ctx.tenant_id, minimum_role="member",
        )

    conn = await _load_git_connection(db, body.git_connection_id, ctx)
    project_name = (body.name or "").strip() or _repo_name_from_url(body.remote_url)
    ws_id, ws_path = workspace_mgr.prepare_clone_target(project_name=project_name, user_id=ctx.user.id)

    token = decrypt_password(conn.access_token_enc)  # 仅内存
    authed_url = workspace_git.build_authed_url(body.provider, body.remote_url, token)
    try:
        default_branch = await workspace_git.clone(ws_path, authed_url, body.remote_url)
    except workspace_git.GitError as e:
        shutil.rmtree(ws_path, ignore_errors=True)   # 清理半成品
        raise HTTPException(status_code=400, detail=f"clone 失败: {e}")
    finally:
        del token, authed_url   # PAT 即时丢弃

    meta = workspace_mgr.register_cloned_workspace(
        ws_id, ws_path,
        project_name=project_name, display_name=body.name,
        user_id=ctx.user.id, tenant_id=ctx.tenant_id, project_id=body.project_id,
        remote_url=body.remote_url,
    )

    db.add(WorkspaceGitRemote(
        ws_id=ws_id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
        provider=body.provider, remote_url=body.remote_url,
        default_branch=default_branch, git_connection_id=body.git_connection_id,
    ))
    await db.flush()

    return _decorate_workspace_access(meta, "owner")
```

确认 `_decorate_workspace_access`/`require_project_access` 已在 coding.py import(P1/P2 已用;`_decorate_workspace_access` 来自 `from app.coding.workspace_access import ...`,见文件顶部 import 块;若没有则补 import)。

- [ ] **Step 4: 跑测试确认通过 + 全量不退化**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_clone_endpoint.py -q`
Expected: PASS(2 passed)。
再跑 git 相关全量确认无退化:`cd backend && .venv/bin/python -m pytest tests/test_workspace_git_remote_endpoints.py tests/test_workspace_git_p1.py tests/test_workspace_git_clone.py tests/test_workspace_clone_manager.py -q` → all PASS。

- [ ] **Step 5: 提交**(`coding.py` 用 `git add -p` 只挑 clone 端点 hunks + 测试文件)

```bash
git add -p backend/app/routes/coding.py
git add backend/tests/test_workspace_git_clone_endpoint.py
git diff --cached --stat
git commit -m "feat(git): /coding/workspaces/git/clone 端点(clone 起工作区+绑远程)— 代码会话 git P3

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 前端「从 git 仓打开」入口 + clone 弹窗 + 建会话导航

**Files:**
- Modify: `frontend/src/api/coding.ts`(加 `gitCloneWorkspace`)
- Modify: `frontend/src/views/WorkspaceCatalogPage.vue`(header 按钮 + clone 弹窗 + clone 成功导航)
- Test: `frontend/src/views/WorkspaceCatalogPageClone.spec.ts`(source-grep 契约测,镜像 `WorkspaceCatalogPageImport.spec.ts` 风格)

**Interfaces:**
- Consumes: Task 3 端点;现有 `WorkspaceInfo` 类型;catalog 导航范式 `router.push({ path: '/ai-chat', query: { workspace_id, mode: 'code' } })`。
- Produces:
  - `codingApi.gitCloneWorkspace(body: { provider: string; remote_url: string; git_connection_id: number; name?: string; project_id?: number }) → Promise<WorkspaceInfo>`
  - catalog header「从 git 仓打开」按钮 → `el-dialog`(provider el-select + remote_url el-input + 凭证 id el-input + 展示名 el-input)→ clone → push `/ai-chat?workspace_id=<id>&mode=code`。

- [ ] **Step 1: `coding.ts` 加 `gitCloneWorkspace`**(放在 P2 `gitPull` 之后、`codingApi` 对象内)

```ts
  /** 从远程仓 clone 起一个新工作区,并绑定远程。返回工作区 meta。 */
  gitCloneWorkspace(body: { provider: string; remote_url: string; git_connection_id: number; name?: string; project_id?: number }) {
    return request.post<any, WorkspaceInfo>(`/coding/workspaces/git/clone`, body)
  },
```

(`WorkspaceInfo` 已在 coding.ts 顶部 export interface;`codingApi` 对象内直接引用类型即可。)

- [ ] **Step 2: `WorkspaceCatalogPage.vue` —— header 加按钮**(在「打开本地文件夹」按钮后,line ~18 附近)

```vue
          <button class="catalog-import-action catalog-import-action--secondary" type="button" @click="openCloneDialog">
            <AppIcon name="git-branch" :size="14" />
            <span>从 git 仓打开</span>
          </button>
```

(`git-branch` 若不在 AppIcon ICON_PATHS 里,改用已存在的 `inbox`/`folder` 之一,或复用 CodeSessionGitBar 的内联 svg。为稳妥用 `name="inbox"`。)

- [ ] **Step 3: `WorkspaceCatalogPage.vue` —— clone 弹窗**(放在 import 弹窗 `</el-dialog>` 之后,line ~249)

```vue
  <el-dialog v-model="cloneDialogOpen" title="从 git 仓 clone 工作区" width="480px" :append-to-body="true">
    <el-form label-width="90px">
      <el-form-item label="平台">
        <el-select v-model="cloneForm.provider" style="width: 100%">
          <el-option label="GitLab" value="gitlab" />
          <el-option label="GitHub" value="github" />
        </el-select>
      </el-form-item>
      <el-form-item label="仓库 URL">
        <el-input v-model="cloneForm.remote_url" placeholder="https://gitlab.example.com/group/repo.git" clearable />
      </el-form-item>
      <el-form-item label="凭证 ID">
        <el-input v-model="cloneForm.git_connection_id_str" placeholder="git_connections 表的 id（整数）" clearable />
      </el-form-item>
      <el-form-item label="展示名">
        <el-input v-model="cloneForm.name" placeholder="可选,默认取仓库名" clearable />
      </el-form-item>
      <div class="connect-hint" style="font-size:12px;color:var(--ac-text-mute,#94a3b8);line-height:1.5;">
        凭证 ID 在「项目设置 → git 连接」里查看。clone 用的 Token 不会落盘。
      </div>
    </el-form>
    <template #footer>
      <el-button @click="cloneDialogOpen = false">取消</el-button>
      <el-button type="primary" :loading="cloning" @click="confirmClone">clone 并打开</el-button>
    </template>
  </el-dialog>
```

- [ ] **Step 4: `WorkspaceCatalogPage.vue` —— script 状态 + 方法**(`<script setup>` 内,`confirmImportSource` 附近)

```ts
const cloneDialogOpen = ref(false)
const cloning = ref(false)
const cloneForm = ref({
  provider: 'gitlab' as 'gitlab' | 'github',
  remote_url: '',
  git_connection_id_str: '' as string | number,
  name: '',
})

function openCloneDialog() {
  cloneForm.value = { provider: 'gitlab', remote_url: '', git_connection_id_str: '', name: '' }
  cloneDialogOpen.value = true
}

async function confirmClone() {
  const remote_url = String(cloneForm.value.remote_url).trim()
  const git_connection_id = Number(cloneForm.value.git_connection_id_str)
  if (!remote_url) { ElMessage.warning('请填写仓库 URL'); return }
  if (!git_connection_id || isNaN(git_connection_id)) { ElMessage.warning('请填写有效的凭证 ID（整数）'); return }
  cloning.value = true
  try {
    const ws = await codingApi.gitCloneWorkspace({
      provider: cloneForm.value.provider,
      remote_url,
      git_connection_id,
      name: String(cloneForm.value.name).trim() || undefined,
      project_id: routeAppId() || undefined,
    })
    cloneDialogOpen.value = false
    ElMessage.success('clone 完成,正在打开代码会话')
    router.push({ path: '/ai-chat', query: { workspace_id: String((ws as any).id), mode: 'code' } }).catch(() => {})
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || 'clone 失败')
  } finally {
    cloning.value = false
  }
}
```

(`routeAppId` 已在 import 流程里用过,复用。`ElMessage`/`codingApi`/`router` 均已 import。)

- [ ] **Step 5: 写契约测试**(source-grep,镜像 `WorkspaceCatalogPageImport.spec.ts`)

```ts
// frontend/src/views/WorkspaceCatalogPageClone.spec.ts
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const page = fs.readFileSync(path.resolve(__dirname, 'WorkspaceCatalogPage.vue'), 'utf-8')
const api = fs.readFileSync(path.resolve(__dirname, '../api/coding.ts'), 'utf-8')

describe('P3 clone 入口契约', () => {
  it('catalog 有「从 git 仓打开」按钮 + clone 弹窗 + confirmClone', () => {
    expect(page).toContain('从 git 仓打开')
    expect(page).toContain('openCloneDialog')
    expect(page).toContain('cloneDialogOpen')
    expect(page).toContain('confirmClone')
    expect(page).toContain('gitCloneWorkspace')
    // clone 成功导航到统一外壳 code 会话
    expect(page).toContain("mode: 'code'")
  })
  it('codingApi 暴露 gitCloneWorkspace 打到 /coding/workspaces/git/clone', () => {
    expect(api).toContain('gitCloneWorkspace')
    expect(api).toContain('/coding/workspaces/git/clone')
  })
})
```

- [ ] **Step 6: 跑测试 + build**

Run: `cd frontend && npx vitest run src/views/WorkspaceCatalogPageClone.spec.ts`
Expected: PASS(2 passed)。
Run: `cd frontend && npm run build:nocheck`
Expected: 构建成功(无新报错;`npm run build`/vue-tsc 预存坏,只看 build:nocheck)。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/api/coding.ts frontend/src/views/WorkspaceCatalogPage.vue frontend/src/views/WorkspaceCatalogPageClone.spec.ts
git diff --cached --stat
git commit -m "feat(git): 我的开发「从 git 仓打开」入口 + clone 弹窗 + 建会话 — 代码会话 git P3

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 8: 控制器 preview 验**(本地造一条 GitConnection + 一个 bare 仓当 remote,或真公司 GitLab 由用户真机):header 点「从 git 仓打开」→ 填 provider/URL/凭证 → clone → 落到 `/ai-chat` code 会话,文件树能看到 clone 下来的文件。**真公司 GitLab clone = 用户真机。**

---

## Self-Review

**1. Spec 覆盖(P3):** spec §4 `clone(provider, remote_url, git_connection_id, ...)` + `POST /coding/workspaces/git/clone` → Task 1(clone 机制)+ Task 3(端点);§6 P3「clone 进 workspaces + 建 code 会话绑它」→ Task 2(落工作区)+ Task 4(catalog 入口 + 导航 + 建会话);§8 PAT 不落 config/日志/前端 → Task 1 set-url 抹除 + Task 3 `del token` + Global Constraints;「立刻绑定远程 push/pull 即用」→ Task 3 落 `WorkspaceGitRemote`(复用 P2 表)。

**2. Placeholder 扫描:** 无 TBD/TODO;每 Task 有可跑命令 + 完整代码。Task 2「`Path` 字符串注解」、Task 3「`shutil` 函数内 import」、Task 4「`git-branch` icon 兜底用 inbox」均为实现期可解析的真实指引(grounding),非占位。凭证列表 API:沿用 P2 决策(手填整数 id),不新建——与现网 CodeSessionGitBar 连接弹窗一致。

**3. Type 一致:** `clone(target_dir, authed_url, clean_url) -> str`(Task 1)被 Task 3 按此签名调用;`prepare_clone_target(project_name, user_id) -> (ws_id, ws_path)` + `register_cloned_workspace(ws_id, ws_path, *, project_name, display_name, user_id, tenant_id, project_id, remote_url) -> dict`(Task 2)被 Task 3 按此调用;`CloneRepoRequest(provider, remote_url, git_connection_id, name?, project_id?)` + `git_clone_workspace_endpoint(body, ctx, db)`(Task 3)被 Task 3 测试 + Task 4 `gitCloneWorkspace` 按此调用;前端 `gitCloneWorkspace({provider, remote_url, git_connection_id, name?, project_id?})`(Task 4)与端点 body 一致。返回 meta 含 `id`(catalog 导航用 `ws.id`)。

## ⚠️ 验证边界(诚实声明)
- 本环境**无真公司 GitLab/GitHub** → clone 机制用**本地 bare 仓**验(免 PAT 走 `build_authed_url` 非-https 分支);PAT 抹除靠 set-url + 断言 .git/config 不含 token URL。
- **真·从公司自建 GitLab clone = 用户真机**(装包后或本地配真 GitConnection)。
- **已知交互(非 P3 范围,记录备查)**:cloned repo 上 agent 跑代码前 `git_changes.checkpoint` 会在 clone 出来的当前分支上叠 ai-builder「checkpoint」提交,用户 push 时会带上去。这与 P1/P2 既有「工作区=git 改动数据库」模型一致,P3 不改;若要避免污染公司仓,另开议题(如 checkpoint 走影子 ref)。
