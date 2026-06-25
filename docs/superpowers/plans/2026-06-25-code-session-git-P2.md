# 代码会话 git — P2:连公司 GitLab/GitHub + push/pull Implementation Plan

> **For agentic workers:** subagent-driven-development。后端 TDD(本地 bare 仓当「远程」验 push/pull 机制);前端 build:nocheck + preview。**真·公司 GitLab e2e = 用户真机**(本环境无真远程)。

**Goal:** 代码会话工作区能连公司自建 GitLab/GitHub 远程仓、push/pull、看 ahead/behind。git bar 加「连接 git」+ push/pull。

**Architecture:** 工作区级 git(模型 B)。新表 `workspace_git_remote`(ws_id→remote_url+provider+git_connection_id)。push/pull 用 **git CLI + 临时 PAT 注入 URL**(PAT 不落 .git/config)。凭证复用 `GitConnection`(加密 PAT)。扩展 P1 的 `workspace_git.py` + 端点 + git bar。

**Tech Stack:** FastAPI;asyncio git CLI;`GitConnection`(collaboration.py)+ `app.crypto` 解密;Vue 3 + Element Plus 弹窗;pytest + 本地 bare 仓 fixture。

**Spec:** [2026-06-25-code-session-git-workspace-design.md](../specs/2026-06-25-code-session-git-workspace-design.md) §6 P2。前置:P1 已落(workspace_git.py 有 status/current_branch/checkout;git bar 在 AIChatPage)。

## Global Constraints
- 工作目录 `/Users/mars/Vibe Coding/ai-builder`;后端 `cd backend && .venv/bin/python -m pytest`(改后端重启 run.py);前端 `npm run build:nocheck`。
- **PAT 安全**:解密只在内存、注入临时 URL 用完即弃;**绝不落 .git/config、不进日志、不回前端**。push/pull 用 `git push <ephemeral-pat-url> ...`(不 `git remote add` 存 token)。
- git remote URL 注入:GitLab `https://oauth2:{token}@{host}/{path}.git`;GitHub `https://{token}@{host}/{path}.git`。
- push 只当前分支、**不 --force**、需用户点。
- 迁移:既有库靠 `database.py` `init_db` 建表(对齐 SP2a:create_all 建新表 + 幂等;新表 create_all 直接建)。
- **每 Task 只 commit 本 Task 文件**,精确 `git add`,绝不 `-A`/`.`,提交前 `git diff --cached --stat`。
- commit message 中文 + `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

---

### Task 1: `workspace_git_remote` 表(模型 + init_db 建表 + 迁移 sql)
**Files:**
- Create: `backend/app/models/workspace_git.py`(新 model 文件)
- Modify: `backend/app/database.py`(init_db:import 新 model;create_all 自动建表;无需 ADD COLUMN)
- Create: `backend/scripts/migrate_workspace_git_remote.sql`(prod 操作员用,幂等建表)
- Test: `backend/tests/test_workspace_git_remote_model.py`

**Interfaces:**
- Produces: `WorkspaceGitRemote`(ws_id unique, tenant_id, user_id, provider, remote_url, default_branch, git_connection_id, created_at, updated_at)。

- [ ] **Step 1: 失败测试**
```python
# backend/tests/test_workspace_git_remote_model.py
import pytest
from app.models.workspace_git import WorkspaceGitRemote

@pytest.mark.asyncio
async def test_workspace_git_remote_persists(db_session):
    r = WorkspaceGitRemote(ws_id="1_abc", tenant_id=1, user_id=2,
        provider="gitlab", remote_url="https://git.co/g/p.git",
        default_branch="main", git_connection_id=5)
    db_session.add(r); await db_session.flush()
    from sqlalchemy import select
    got = (await db_session.execute(select(WorkspaceGitRemote).where(WorkspaceGitRemote.ws_id=="1_abc"))).scalar_one()
    assert got.provider == "gitlab" and got.git_connection_id == 5
```
Run RED: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_remote_model.py -q` → ModuleNotFoundError。

- [ ] **Step 2: 实现 model**
```python
# backend/app/models/workspace_git.py
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class WorkspaceGitRemote(Base):
    """代码会话工作区 ↔ git 远程仓绑定(模型 B,工作区级)。凭证引用 GitConnection。"""
    __tablename__ = "workspace_git_remote"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ws_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)   # github / gitlab
    remote_url: Mapped[str] = mapped_column(String(500), nullable=False)
    default_branch: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    git_connection_id: Mapped[int] = mapped_column(Integer, nullable=False)  # → git_connections.id(复用加密 PAT)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```
`database.py` init_db:在其它 `import app.models.xxx` 旁加 `import app.models.workspace_git  # noqa: F401`(让 create_all 建表)。
`scripts/migrate_workspace_git_remote.sql`:幂等 `CREATE TABLE IF NOT EXISTS workspace_git_remote (...)`(镜像列;注释说明)。

- [ ] **Step 3: GREEN** — `pytest tests/test_workspace_git_remote_model.py -q` PASS。
- [ ] **Step 4: 提交**
```bash
git add backend/app/models/workspace_git.py backend/app/database.py backend/scripts/migrate_workspace_git_remote.sql backend/tests/test_workspace_git_remote_model.py
git commit -m "feat(git): workspace_git_remote 表(工作区↔远程仓绑定)— 代码会话 git P2

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
(⚠️ database.py 若有无关未提交改动用 `git add -p`;本 Task 起它应是干净的。)

---

### Task 2: `workspace_git.py` 远程操作(PAT 注入 URL + connect/push/pull/remote_status)
**Files:**
- Modify: `backend/app/git/workspace_git.py`(扩展 P1 的模块)
- Test: `backend/tests/test_workspace_git_remote_ops.py`

**Interfaces:**
- Consumes: P1 的 `_git`/`_git_checked`/`current_branch`;`GitConnection`(collaboration.py:provider/host/access_token_enc);`app.crypto` 解密(读真实函数名,见下)。
- Produces:
  - `def build_authed_url(provider: str, remote_url: str, token: str) -> str`(纯函数)
  - `async def fetch(ws_path, authed_url)` / `async def push(ws_path, authed_url, branch)` / `async def pull(ws_path, authed_url, branch)`
  - `async def remote_status(ws_path) -> dict`(`{ahead, behind}`,基于已 fetch 的 upstream;无 upstream → {0,0})

- [ ] **Step 1: 失败测试**(用本地 bare 仓当「远程」验 push/pull 机制;PAT 注入是纯函数单测):
```python
# backend/tests/test_workspace_git_remote_ops.py
import subprocess
from pathlib import Path
import pytest
from app.git.workspace_git import build_authed_url, push, pull, current_branch

def _run(cwd, *a): subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True)

def test_build_authed_url_gitlab():
    u = build_authed_url("gitlab", "https://git.co/g/p.git", "TOK")
    assert u == "https://oauth2:TOK@git.co/g/p.git"
def test_build_authed_url_github():
    u = build_authed_url("github", "https://gh.co/o/r.git", "TOK")
    assert u == "https://TOK@gh.co/o/r.git"

@pytest.fixture
def repo_and_remote(tmp_path):
    remote = tmp_path / "remote.git"; subprocess.run(["git","init","--bare","-b","main",str(remote)],check=True,capture_output=True)
    ws = tmp_path / "ws"; ws.mkdir()
    _run(ws,"init","-b","main"); _run(ws,"config","user.email","t@t"); _run(ws,"config","user.name","t")
    (ws/"a.txt").write_text("1"); _run(ws,"add","."); _run(ws,"commit","-m","c1")
    return ws, remote

@pytest.mark.asyncio
async def test_push_then_pull_roundtrip(repo_and_remote):
    ws, remote = repo_and_remote
    await push(ws, str(remote), "main")                 # 本地 bare 路径当 authed_url
    # 另一个 clone 改一笔推回,验证 pull
    import subprocess as sp
    clone = ws.parent / "clone"; sp.run(["git","clone",str(remote),str(clone)],check=True,capture_output=True)
    _run(clone,"config","user.email","t@t"); _run(clone,"config","user.name","t")
    (clone/"b.txt").write_text("2"); _run(clone,"add","."); _run(clone,"commit","-m","c2"); _run(clone,"push","origin","main")
    await pull(ws, str(remote), "main")
    assert (ws/"b.txt").exists()
    assert await current_branch(ws) == "main"
```
Run RED → 函数未定义。

- [ ] **Step 2: 实现**(加到 workspace_git.py;先 grep `app/crypto.py` 取真实解密函数名,常见 `decrypt_password`/`decrypt`):
```python
def build_authed_url(provider: str, remote_url: str, token: str) -> str:
    """把 PAT 注入 https remote URL。仅内存用,绝不持久化。"""
    if not remote_url.startswith("https://"):
        return remote_url  # ssh/本地路径直接用(测试本地 bare 仓走这条)
    rest = remote_url[len("https://"):]
    if provider == "gitlab":
        return f"https://oauth2:{token}@{rest}"
    return f"https://{token}@{rest}"  # github 及默认

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
```
- [ ] **Step 3: GREEN** — `pytest tests/test_workspace_git_remote_ops.py -q` PASS(4 测)。
- [ ] **Step 4: 提交**(只 `backend/app/git/workspace_git.py` + 测试)。
```
feat(git): workspace_git 远程操作(PAT 注入 URL + push/pull/fetch/remote_status)— 代码会话 git P2
```

---

### Task 3: 端点(connect / push / pull;status 扩 ahead/behind+has_remote)
**Files:**
- Modify: `backend/app/routes/coding.py`(加 4 路由 + 扩 status)
- Test: `backend/tests/test_workspace_git_remote_endpoints.py`

**Interfaces:**
- Consumes: Task 1 `WorkspaceGitRemote`;Task 2 ops;`GitConnection`;P1 端点的 auth/ws 依赖(`_ensure_workspace_access` + `workspace_mgr.get_workspace_path`,见 coding.py P1 端点)。
- Produces:
  - `POST /workspace/{ws_id}/git/connect`  {provider, remote_url, git_connection_id} → 落 WorkspaceGitRemote + 用 PAT 注入 URL `fetch` 验证可达 → `{ok, default_branch}`
  - `POST /workspace/{ws_id}/git/push` / `…/pull` → 取绑定 + GitConnection 解密 token → build_authed_url → push/pull 当前分支 → `{ok, ...remote_status}`
  - `GET …/git/status` 扩:有绑定时 `has_remote=true` + `ahead/behind`(remote_status)

- [ ] **Step 1: 失败测试**(本地 bare 仓 + 真插一条 GitConnection[access_token_enc=encrypt("x")]+ WorkspaceGitRemote;mock `get_workspace_path` 指 ws、connect 用本地 bare 路径当 remote_url 走非-https 分支免 PAT)。断言:connect 落库 + push/pull 往返 + status 含 has_remote/ahead/behind。**(代码完整写,镜像 P1 端点测;函数名 `git_connect_endpoint`/`git_push_endpoint`/`git_pull_endpoint`,参数序与测试调用一致。)**
- [ ] **Step 2: RED → 实现**(coding.py 加 4 路由 + `GitConnectRequest`;push/pull 里:`select(WorkspaceGitRemote).where(ws_id==)` → `select(GitConnection).where(id==git_connection_id)` → `token=decrypt(conn.access_token_enc)` → `build_authed_url(remote.provider, remote.remote_url, token)` → ops;GitError → 400)→ GREEN + 全量不退化。
- [ ] **Step 3: 提交**(`backend/app/routes/coding.py` 用 `git add -p` 只挑 git-remote 路由 hunks + 测试文件)。
```
feat(git): /coding/workspace/{ws}/git connect/push/pull 端点 + status 扩 ahead/behind — 代码会话 git P2
```

---

### Task 4: 前端「连接 git」弹窗 + push/pull(扩 `CodeSessionGitBar.vue`)
**Files:**
- Modify: `frontend/src/api/coding.ts`(加 gitConnect/gitPush/gitPull)
- Modify: `frontend/src/views/coding/CodeSessionGitBar.vue`
- Modify: `frontend/src/api/coding.ts` 或既有 git 连接 API(读 `frontend/src/api/` 找 GitConnection 列表 API,弹窗里选凭证)

**Interfaces:**
- Consumes: Task 3 端点;P1 的 CodeSessionGitBar(已有 status/branches/checkout)。
- Produces:git bar 右段:未连 → `[连接 git]`(弹窗:provider 下拉 + 仓库 URL 输入 + 选/新增 GitConnection 凭证)→ `gitConnect`;已连 → `clean / ↑n↓n` + `[push]` `[pull]`。

- [ ] **Step 1: codingApi 加 `gitConnect(wsId,{provider,remote_url,git_connection_id})`/`gitPush(wsId)`/`gitPull(wsId)`(镜像 P1 git 方法)。**
- [ ] **Step 2: 扩组件**:status 现含 `has_remote/ahead/behind`;`has_remote=false` 显「连接 git」按钮 → `el-dialog`(provider el-select + remote_url el-input + 凭证 el-select[拉现有 GitConnection,「+ 新增」走现有 git 连接流程或留 TODO 提示去平台连])→ `gitConnect` → refresh;`has_remote=true` 显 `↑{ahead}↓{behind}` + push/pull 按钮(调 API + ElMessage + refresh)。读 `frontend/src/api/` 找列 GitConnection 的真实 API;没有就弹窗里填 host+token 直连(但 token 进后端加密存,前端不留)。
- [ ] **Step 3: build:nocheck 绿 + 组件 spec 更新(source-grep gitConnect/gitPush/gitPull/连接 git)。**
- [ ] **Step 4: 提交**(coding.ts + CodeSessionGitBar.vue + spec)。
- [ ] **Step 5: 控制器 preview 验**:本地造一条 GitConnection + 一个 bare 仓当 remote(或真公司 GitLab 由用户真机),连 → push/pull → 看 ahead/behind。**真公司 GitLab 往返 = 用户真机。**

---

## Self-Review
**1. Spec 覆盖(P2):** §3 表 workspace_git_remote → Task 1;§4 connect/push/pull/status+ahead-behind + PAT 复用 GitConnection → Task 2+3;§5 连接弹窗+push/pull → Task 4;§8 PAT 不落 config/日志/前端 → Task 2 build_authed_url 仅内存 + Global Constraints。
**2. Placeholder:** Task 3 测试/实现标「代码完整写,镜像 P1 端点测」+「git add -p 只挑 hunks」是 grounding 指引;`app.crypto` 解密函数名标「先 grep 取真实名」;凭证列表 API 标「读 api/ 找真实/没有就直填」——均为实现期可解析的真实指引,非 TBD。每 Task 有可跑命令 + 关键代码。
**3. Type 一致:** `build_authed_url(provider,remote_url,token)`、`push/pull(ws_path,authed_url,branch)`、`remote_status→{ahead,behind}`、端点 `git_connect/push/pull_endpoint` + `GitConnectRequest`、前端 `gitConnect/gitPush/gitPull` 三处一致;status 返回 `{branch,dirty,has_remote,ahead?,behind?}` 贯穿后端/前端。

## ⚠️ 验证边界(诚实声明)
- 本环境**无真公司 GitLab/GitHub** → push/pull 机制用**本地 bare 仓**验(免 PAT 走非-https 分支);PAT 注入是纯函数单测。
- **真·连公司自建 GitLab + 往返 = 用户真机**(装包后或本地配真 GitConnection)。
