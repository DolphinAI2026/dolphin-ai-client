# 代码会话 git — P1:工作区指示 + 本地分支 Implementation Plan

> **For agentic workers:** subagent-driven-development。后端 TDD(临时 git 仓 fixture);前端验证 = build:nocheck + preview 实测。

**Goal:** 代码会话输入框上方加 Codex 那行 `[📁 工作区 ▾][⎇ 当前分支 ▾]`:显当前工作区(可切=开新会话)、列/切/建**本地**分支。纯本地、不碰远程。

**Architecture:** 后端新 `app/git/workspace_git.py`(async git CLI 薄封装)+ 3 个工作区级端点(status/branches/checkout);前端新 `CodeSessionGitBar.vue` 挂进 AIChatPage 代码会话的输入框上方。工作区本就是 git 仓(`main`),P1 只读/切本地分支。

**Tech Stack:** FastAPI + asyncio.create_subprocess_exec(git);Vue 3 + Element Plus;pytest + 临时 git 仓 fixture;Element Plus el-dropdown。

**Spec:** [docs/superpowers/specs/2026-06-25-code-session-git-workspace-design.md](../specs/2026-06-25-code-session-git-workspace-design.md)(本计划 = 其 §6 的 P1)

## Global Constraints
- 工作目录 `/Users/mars/Vibe Coding/ai-builder`;后端 `cd backend && .venv/bin/python -m pytest`(.venv py3.13,改后端重启 run.py);前端 `cd frontend && npm run build:nocheck`。
- git 调用统一 `asyncio.create_subprocess_exec("git", "-C", str(ws_path), ...)` + `await proc.communicate()`(对齐 workspace.py 既有 async 子进程模式)。**不打印/不回传任何凭证**(P1 无远程,天然无 PAT)。
- 端点鉴权 + 工作区归属:复用 coding 既有 `workspace_mgr.get_workspace_path(ws_id)` + auth context 模式(见 coding.py 的 `/workspace/{ws_id}/files`)。
- **每 Task 只 commit 本 Task 文件**(精确 `git add`)。工作树有大量无关未提交改动(Codex/PTY)——绝不 `git add -A`/`.`;提交前 `git diff --cached --stat` 自查。
- 不破坏现有 Builder(chat/cowork):git bar 只在 `isCodeSession` 显示,纯增量。
- commit message 中文 + 结尾 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。

---

### Task 1: 后端 `workspace_git.py` 核心(current_branch / is_dirty / list_local_branches / checkout / status)
**Files:**
- Create: `backend/app/git/workspace_git.py`
- Test: `backend/tests/test_workspace_git_p1.py`

**Interfaces:**
- Produces:
  - `async def current_branch(ws_path: Path) -> str`
  - `async def is_dirty(ws_path: Path) -> bool`
  - `async def list_local_branches(ws_path: Path) -> list[str]`
  - `async def checkout(ws_path: Path, name: str, create: bool = False) -> None`(失败抛 `GitError`)
  - `async def status(ws_path: Path) -> dict`(返回 `{"branch": str, "dirty": bool, "has_remote": False}`)
  - `class GitError(Exception)`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_workspace_git_p1.py`:
```python
import asyncio
import subprocess
from pathlib import Path

import pytest

from app.git.workspace_git import (
    current_branch, is_dirty, list_local_branches, checkout, status, GitError,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """一个有 1 次提交、分支=main 的临时 git 仓。"""
    def run(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True,
                       capture_output=True)
    run("init", "-b", "main")
    run("config", "user.email", "t@t.com")
    run("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("hi")
    run("add", "a.txt")
    run("commit", "-m", "init")
    return tmp_path


@pytest.mark.asyncio
async def test_current_branch(git_repo):
    assert await current_branch(git_repo) == "main"


@pytest.mark.asyncio
async def test_is_dirty(git_repo):
    assert await is_dirty(git_repo) is False
    (git_repo / "a.txt").write_text("changed")
    assert await is_dirty(git_repo) is True


@pytest.mark.asyncio
async def test_list_and_checkout_create(git_repo):
    assert await list_local_branches(git_repo) == ["main"]
    await checkout(git_repo, "feature/x", create=True)
    assert await current_branch(git_repo) == "feature/x"
    assert set(await list_local_branches(git_repo)) == {"main", "feature/x"}
    # 切回已存在分支(create=False)
    await checkout(git_repo, "main", create=False)
    assert await current_branch(git_repo) == "main"


@pytest.mark.asyncio
async def test_checkout_missing_branch_raises(git_repo):
    with pytest.raises(GitError):
        await checkout(git_repo, "nope", create=False)


@pytest.mark.asyncio
async def test_status(git_repo):
    s = await status(git_repo)
    assert s == {"branch": "main", "dirty": False, "has_remote": False}
```

- [ ] **Step 2: 跑确认 RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_p1.py -q`
Expected: FAIL(`ModuleNotFoundError: app.git.workspace_git` 或函数未定义)。

- [ ] **Step 3: 实现**

`backend/app/git/workspace_git.py`:
```python
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
```

- [ ] **Step 4: 跑确认 GREEN**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_p1.py -q`
Expected: PASS(5 测)。

- [ ] **Step 5: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/git/workspace_git.py backend/tests/test_workspace_git_p1.py
git commit -m "feat(git): workspace_git.py 本地分支核心(current_branch/list/checkout/status) — 代码会话 git P1

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 后端 3 端点(status / branches / checkout)
**Files:**
- Modify: `backend/app/routes/coding.py`(新增 3 路由,挂在既有 `/workspace/{ws_id}/...` 同组)
- Test: `backend/tests/test_workspace_git_endpoints_p1.py`

**Interfaces:**
- Consumes: Task 1 的 `workspace_git`(status/list_local_branches/checkout);coding.py 既有 `workspace_mgr.get_workspace_path(ws_id)` + auth context（参考同文件 `/workspace/{ws_id}/files` 端点签名)。
- Produces:
  - `GET  /coding/workspace/{ws_id}/git/status` → `{branch, dirty, has_remote}`
  - `GET  /coding/workspace/{ws_id}/git/branches` → `{local: [...]}`
  - `POST /coding/workspace/{ws_id}/git/checkout`,body `{name: str, create: bool=False}` → `{ok: true, branch}`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_workspace_git_endpoints_p1.py`(镜像 coding 端点测的 auth/ws 模式;读 coding.py 里 `/workspace/{ws_id}/files` 端点的实际函数名与依赖,直接调路由函数):
```python
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.deps import AuthContext
from app.models import User
from app.models.tenant import Tenant
from app.routes.coding import (
    git_status_endpoint, git_branches_endpoint, git_checkout_endpoint,
    GitCheckoutRequest,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    def run(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    run("init", "-b", "main")
    run("config", "user.email", "t@t.com"); run("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("hi"); run("add", "a.txt"); run("commit", "-m", "init")
    return tmp_path


def _ctx(user, tenant_id):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


@pytest.mark.asyncio
async def test_status_and_branches_and_checkout(db_session, git_repo):
    tenant = Tenant(tenant_name="t", tenant_code="t_git_p1"); db_session.add(tenant); await db_session.flush()
    user = User(username="git_p1", hashed_password="x"); db_session.add(user); await db_session.flush()
    ctx = _ctx(user, tenant.id)
    with patch("app.routes.coding.workspace_mgr.get_workspace_path", return_value=git_repo):
        s = await git_status_endpoint("ws-x", ctx, db_session)
        assert s["branch"] == "main"
        b = await git_branches_endpoint("ws-x", ctx, db_session)
        assert b["local"] == ["main"]
        out = await git_checkout_endpoint("ws-x", GitCheckoutRequest(name="feat/y", create=True), ctx, db_session)
        assert out["ok"] is True and out["branch"] == "feat/y"
```

- [ ] **Step 2: 跑确认 RED**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_endpoints_p1.py -q`
Expected: FAIL(`ImportError: cannot import name 'git_status_endpoint'`)。

- [ ] **Step 3: 实现 — 在 `backend/app/routes/coding.py` 加路由**

先读 coding.py 里 `@router.get("/workspace/{ws_id}/files")` 那个端点(约 933 行)抄它的**签名/依赖注入/ws 解析**写法(auth ctx + db + workspace_mgr.get_workspace_path)。然后加(放在该端点附近):
```python
from pydantic import BaseModel
from app.git import workspace_git

class GitCheckoutRequest(BaseModel):
    name: str
    create: bool = False

@router.get("/workspace/{ws_id}/git/status")
async def git_status_endpoint(ws_id: str, ctx: ...=Depends(...), db: ...=Depends(...)):
    ws_path = workspace_mgr.get_workspace_path(ws_id)  # 同 /files 的 ws 解析+归属校验
    return await workspace_git.status(ws_path)

@router.get("/workspace/{ws_id}/git/branches")
async def git_branches_endpoint(ws_id: str, ctx: ...=Depends(...), db: ...=Depends(...)):
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    return {"local": await workspace_git.list_local_branches(ws_path)}

@router.post("/workspace/{ws_id}/git/checkout")
async def git_checkout_endpoint(ws_id: str, body: GitCheckoutRequest, ctx: ...=Depends(...), db: ...=Depends(...)):
    ws_path = workspace_mgr.get_workspace_path(ws_id)
    try:
        await workspace_git.checkout(ws_path, body.name, body.create)
    except workspace_git.GitError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "branch": await workspace_git.current_branch(ws_path)}
```
(把 `Depends(...)` 换成 `/files` 端点用的真实 auth/db 依赖;`ctx`/`db` 形参名与签名顺序对齐测试调用 `(ws_id, ctx, db)` / `(ws_id, body, ctx, db)`。)

- [ ] **Step 4: 跑确认 GREEN + 全量不退化**

Run: `cd backend && .venv/bin/python -m pytest tests/test_workspace_git_endpoints_p1.py -q && .venv/bin/python -m pytest -q`
Expected: 新测 PASS;全量与基线一致(无新增失败)。

- [ ] **Step 5: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/routes/coding.py backend/tests/test_workspace_git_endpoints_p1.py
git commit -m "feat(git): /coding/workspace/{ws}/git status/branches/checkout 端点 — 代码会话 git P1

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 前端 API + `CodeSessionGitBar.vue` 组件
**Files:**
- Modify: `frontend/src/api/coding.ts`(加 git 方法)
- Create: `frontend/src/views/coding/CodeSessionGitBar.vue`
- Test: `frontend/src/views/coding/CodeSessionGitBar.spec.ts`

**Interfaces:**
- Consumes: Task 2 端点。codingApi 新方法:`gitStatus(wsId)`、`gitBranches(wsId)`、`gitCheckout(wsId, {name, create})`。
- Produces: `<CodeSessionGitBar :ws-id="..." :workspace-name="..." @switch-workspace="..." />` —— 显 `📁 {workspaceName} ▾`(emit `switch-workspace`)+ `⎇ {branch} ▾`(下拉列 branches、切、建)。

- [ ] **Step 1: 加 codingApi 方法**(`frontend/src/api/coding.ts`,镜像同文件既有 `request.get/post` 写法):
```ts
gitStatus(wsId: string) {
  return request.get<any, { branch: string; dirty: boolean; has_remote: boolean }>(`/coding/workspace/${wsId}/git/status`)
},
gitBranches(wsId: string) {
  return request.get<any, { local: string[] }>(`/coding/workspace/${wsId}/git/branches`)
},
gitCheckout(wsId: string, body: { name: string; create?: boolean }) {
  return request.post<any, { ok: boolean; branch: string }>(`/coding/workspace/${wsId}/git/checkout`, body)
},
```

- [ ] **Step 2: 写组件 + 测试(失败先)**

`CodeSessionGitBar.spec.ts`(source-grep + 浅挂载,镜像仓库现有 ?raw 组件测风格):
```ts
import { describe, expect, it } from 'vitest'
import src from './CodeSessionGitBar.vue?raw'

describe('CodeSessionGitBar', () => {
  it('renders 📁 workspace name + ⎇ branch + emits switch-workspace', () => {
    expect(src).toContain('switch-workspace')          // 切工作区 emit
    expect(src).toContain('gitStatus')                 // 拉当前分支
    expect(src).toContain('gitBranches')               // 列分支
    expect(src).toContain('gitCheckout')               // 切/建分支
  })
})
```
Run: `cd frontend && npx vitest run src/views/coding/CodeSessionGitBar.spec.ts` → FAIL(组件不存在)。

- [ ] **Step 3: 实现 `CodeSessionGitBar.vue`**

```vue
<template>
  <div class="git-bar">
    <!-- 📁 工作区:显当前 + 切(切=开新会话,由父处理) -->
    <el-dropdown trigger="click" @command="onSwitchWorkspace">
      <button class="git-chip" title="切换工作区">
        <AppIcon name="folder" :size="13" /> {{ workspaceName || wsId }} <span class="caret">▾</span>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="w in workspaces" :key="w.ws_id || w.id" :command="w.ws_id || w.id">
            {{ w.project_name || w.name || (w.ws_id || w.id) }}
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
    <!-- ⎇ 分支:显当前 + 列/切/建 -->
    <el-dropdown trigger="click" @command="onPickBranch">
      <button class="git-chip" title="切换分支">
        <AppIcon name="git-branch" :size="13" /> {{ branch || '—' }}<span v-if="dirty" class="dot" title="有未提交改动">●</span> <span class="caret">▾</span>
      </button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-for="b in branches" :key="b" :command="b">{{ b }}</el-dropdown-item>
          <el-dropdown-item divided command="__new__">+ 新建分支…</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { codingApi } from '@/api/coding'
import AppIcon from '@/components/common/AppIcon.vue'  // 按仓库 AppIcon 真实路径调整

const props = defineProps<{ wsId: string; workspaceName?: string; workspaces?: any[] }>()
const emit = defineEmits<{ (e: 'switch-workspace', wsId: string): void }>()

const branch = ref(''); const dirty = ref(false); const branches = ref<string[]>([])

async function refresh() {
  if (!props.wsId) return
  try {
    const s = await codingApi.gitStatus(props.wsId)
    branch.value = s.branch; dirty.value = s.dirty
    branches.value = (await codingApi.gitBranches(props.wsId)).local
  } catch { /* 工作区可能非 git 仓 → 静默 */ }
}
watch(() => props.wsId, refresh, { immediate: true })

function onSwitchWorkspace(wsId: string) { if (wsId && wsId !== props.wsId) emit('switch-workspace', wsId) }

async function onPickBranch(cmd: string) {
  if (cmd === '__new__') {
    try {
      const { value } = await ElMessageBox.prompt('新分支名', '新建分支', { inputPattern: /\S+/, inputErrorMessage: '不能为空' })
      await codingApi.gitCheckout(props.wsId, { name: value.trim(), create: true })
      ElMessage.success(`已切到新分支 ${value.trim()}`); await refresh()
    } catch (e: any) { if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '建分支失败') }
    return
  }
  if (cmd === branch.value) return
  try { await codingApi.gitCheckout(props.wsId, { name: cmd, create: false }); ElMessage.success(`已切到 ${cmd}`); await refresh() }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '切分支失败') }
}
</script>

<style scoped>
.git-bar { display: flex; gap: 8px; align-items: center; padding: 4px 0; }
.git-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; padding: 3px 8px;
  border: 1px solid var(--ac-border, #cbd5e1); border-radius: 6px; background: var(--ac-btn, #fff);
  color: var(--ac-text-mute, #475569); cursor: pointer; }
.git-chip:hover { background: var(--ac-input, #f8fafc); }
.caret { opacity: .6; }
.dot { color: #f59e0b; margin-left: 2px; }
</style>
```
(`AppIcon` 路径 / `folder`/`git-branch` icon 名按仓库 `utils/icons.ts` 实际有的调整;无对应 icon 就用内联 SVG。)

- [ ] **Step 4: 跑测试 + build:nocheck**

Run: `cd frontend && npx vitest run src/views/coding/CodeSessionGitBar.spec.ts && npm run build:nocheck`
Expected: 测 PASS;build 绿。

- [ ] **Step 5: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add frontend/src/api/coding.ts frontend/src/views/coding/CodeSessionGitBar.vue frontend/src/views/coding/CodeSessionGitBar.spec.ts
git commit -m "feat(git): CodeSessionGitBar 组件 + codingApi git 方法 — 代码会话 git P1

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: 把 git bar 挂进 AIChatPage 代码会话(输入框上方)+ 接 📁 切工作区
**Files:**
- Modify: `frontend/src/views/AIChatPage.vue`

**Interfaces:**
- Consumes: Task 3 的 `<CodeSessionGitBar>`;AIChatPage 既有 `isCodeSession`/`codexPanelWsId`/`currentSession`;工作区列表(`codingApi` 既有 list 方法,读 coding.ts 取真实名)。
- Produces: 代码会话输入框上方显 git bar;`switch-workspace` → `router.push('/ai-chat?workspace_id=X&mode=code')`(复用 SP2b 入口)。

- [ ] **Step 1: 引入 + 挂载**

在 `<UnifiedChatComposer>`(AIChatPage.vue:260)**之前**,代码会话时插:
```vue
<CodeSessionGitBar
  v-if="isCodeSession && codexPanelWsId"
  :ws-id="codexPanelWsId"
  :workspace-name="currentSession?.title"
  :workspaces="codeWorkspaceList"
  @switch-workspace="onSwitchCodeWorkspace"
/>
```
script:加 import + `codeWorkspaceList`(onMounted/进 code 会话时 `codingApi.list...()` 拉一次,容错空)+:
```ts
function onSwitchCodeWorkspace(wsId: string) {
  router.push({ path: '/ai-chat', query: { workspace_id: String(wsId), mode: 'code' } }).catch(() => {})
}
```
(`workspaceName` 用 session.title 先顶着;真工作区名 P2/后续可换成 status 带回。)

- [ ] **Step 2: build:nocheck**

Run: `cd frontend && npm run build:nocheck`
Expected: 绿。

- [ ] **Step 3: preview 真机验证**(控制器做)
- 进一个 code 会话(真 git 仓工作区)→ 输入框上方出现 `📁 工作区 ▾  ⎇ main ▾`。
- 点 ⎇ → 列出 `main` + 「新建分支」;建 `feat/x` → chip 变 `feat/x`;切回 `main`。
- 点 📁 → 列工作区,选一个 → 跳到那个工作区的代码会话。
- 非 code 会话(Builder chat):无 git bar,无回归。

- [ ] **Step 4: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add frontend/src/views/AIChatPage.vue
git commit -m "feat(git): AIChatPage 代码会话输入框上方挂 CodeSessionGitBar — 代码会话 git P1 收口

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review
**1. Spec 覆盖(P1 部分):** §6 P1「📁 工作区(+切)、⎇ 列/切/建本地分支」→ Task 1(核心)+2(端点)+3(组件)+4(挂载) ✓。§4 端点(status/branches/checkout)→ Task 2 ✓。§5 组件 CodeSessionGitBar → Task 3 ✓。P1 不含远程/clone(P2/P3),本计划无,符合。
**2. Placeholder:** 端点 `Depends(...)` 标注「换成 /files 端点真实依赖」是 grounding 指引非占位(实现者读 coding.py 取真实签名);AppIcon/icon 名标注「按仓库实际调整」。其余均完整代码。
**3. Type 一致:** `gitStatus/gitBranches/gitCheckout` 三处一致;端点函数名 `git_status_endpoint/git_branches_endpoint/git_checkout_endpoint` + `GitCheckoutRequest` 测试与实现一致;`workspace_git.status` 返回 `{branch,dirty,has_remote}` 与端点/前端一致。
