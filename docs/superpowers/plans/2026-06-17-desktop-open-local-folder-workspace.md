# 桌面「打开本地文件夹」工作区 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让桌面端能「打开用户自己的本地文件夹」当二次开发工作区（指针进 DB、文件留用户文件夹），与现有 app 托管目录双模并存。

**Architecture:** 新增 `registered_workspaces` DB 注册表存「external 工作区」指针（abs_path/owner/类型/可选绑 aPaaS 应用）；`WorkspaceManager` 加同步 `_external_paths` 缓存（注册时+启动时填充），`get_workspace_path` external 优先；文件读写复用已有路径牢笼 `_resolve_safe`；前端经 Tauri 原生文件夹选择器选目录 + 打开时风险确认。安全本轮 = 路径牢笼 + 敏感目录拦截 + 打开时确认；run_command 不约束、真沙箱后置 P2。

**Tech Stack:** FastAPI / SQLAlchemy(async, StaticPool 测试) / pytest / Tauri v2(Rust, tauri-plugin-dialog) / Vue 3 `<script setup>` / Element Plus / Vitest。

**关联 spec:** `docs/superpowers/specs/2026-06-17-desktop-open-local-folder-workspace-design.md`

**分支:** `feat/desktop-login-mvp`（桌面工作分支；工作树有并发未提交的 admin-spa/PlatformAdminEmbed 改动，**只动本计划相关文件、不 `git add -A`**）。

**测试命令:** 后端 `cd backend && .venv/bin/python -m pytest tests/<f>::<t> -v`；前端 `cd frontend && npx vitest run src/<p>.spec.ts` + `npm run build:nocheck`；Tauri `cd src-tauri && cargo check`。

**已核实事实（写代码依据）:**
- 工作区文件已是本地真实文件（`backend/app/coding/tools.py` 原生 fs），DB 只存指针。
- 工作区靠扫 `.workspace.json` 发现（`WorkspaceManager._iter_workspace_dirs`）；external 文件夹无此文件 → 必须 DB 注册表识别。
- `get_workspace_path`（`workspace.py:385`）先查同步 `_workspace_path_cache`（class 级 dict）→ 再扫盘。external 走同样的同步缓存即可，避开「同步方法查异步 DB」。
- 路径牢笼 `_resolve_safe(file_path, workspace_path)`（`tools.py:201`）逃出即 raise——external root=用户文件夹时自动生效，零新增。
- `create_workspace` ws_id 格式 = `f"{user_id}_{uuid.uuid4().hex[:8]}"`（`workspace.py`）。
- list 路由 `GET /coding/workspaces`（`coding.py:1033`）经 `list_accessible_workspaces` 返回 decorated meta dict 列表。
- coding 7 base 工具无 delete（删除只经 run_command）；`tools.py:358` unlink 是改名内部清理。故不做软删除。
- Tauri capability 现 `src-tauri/capabilities/default.json`，无 dialog；插件在 `Cargo.toml`（无 dialog）+ `lib.rs`。

---

## File Structure

- Create: `backend/app/models/__init__.py` 内新增 `RegisteredWorkspace`（同文件追加）
- Modify: `backend/app/coding/workspace.py`（`_external_paths` + `register_external` + `load_external` + `get_workspace_path` + `restore_external_workspaces`）
- Modify: `backend/app/routes/coding.py`（`_is_sensitive_dir` + `POST /coding/workspace/open-local` + list 合并 external）
- Modify: `backend/app/main.py`（lifespan 启动恢复 external）
- Modify: `backend/desktop_sidecar.py`（`APAAS_WORKSPACE_ROOT`）
- Modify: `src-tauri/Cargo.toml` + `src-tauri/src/lib.rs` + `src-tauri/capabilities/default.json`（dialog 插件）
- Modify: `frontend/src/api/coding.ts`（`openLocalFolder`）+ `frontend/src/views/WorkspaceCatalogPage.vue`（入口）
- Create: `backend/tests/test_registered_workspace.py`、`backend/tests/test_open_local_workspace.py`

---

## Task 1: `RegisteredWorkspace` 数据模型

**Files:**
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_registered_workspace.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_registered_workspace.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

from app.database import Base
from app.models import RegisteredWorkspace


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.mark.asyncio
async def test_insert_and_query(session):
    session.add(RegisteredWorkspace(
        ws_id="1_abc12345", abs_path="/Users/x/proj", user_id=1, tenant_id=1,
        workspace_type="external", display_name="proj",
    ))
    await session.commit()
    row = (await session.execute(select(RegisteredWorkspace).where(RegisteredWorkspace.ws_id == "1_abc12345"))).scalar_one()
    assert row.abs_path == "/Users/x/proj" and row.workspace_type == "external" and row.apaas_app_id is None


@pytest.mark.asyncio
async def test_unique_tenant_path(session):
    from sqlalchemy.exc import IntegrityError
    session.add(RegisteredWorkspace(ws_id="1_a", abs_path="/p", user_id=1, tenant_id=1, display_name="p"))
    await session.commit()
    session.add(RegisteredWorkspace(ws_id="1_b", abs_path="/p", user_id=1, tenant_id=1, display_name="p"))
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_registered_workspace.py -v`
Expected: FAIL（`RegisteredWorkspace` 不存在）

- [ ] **Step 3: 加模型**

在 `backend/app/models/__init__.py` 追加（先确认文件顶部已 import `Mapped, mapped_column, String, Integer, DateTime, UniqueConstraint` 与 `datetime`、`Optional`——缺则补 import）：

```python
class RegisteredWorkspace(Base):
    """桌面「打开本地文件夹」external 工作区注册表 (指针进 DB, 不写用户文件夹)。"""
    __tablename__ = "registered_workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "abs_path", name="uq_regws_tenant_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ws_id: Mapped[str] = mapped_column(String(60), unique=True, index=True, nullable=False)
    abs_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    workspace_type: Mapped[str] = mapped_column(String(40), nullable=False, default="external")
    apaas_app_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_opened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

表由 `init_db` 的 `Base.metadata.create_all`（checkfirst）建，无需 ALTER。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_registered_workspace.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/__init__.py backend/tests/test_registered_workspace.py
git commit -m "feat(desktop): RegisteredWorkspace 模型 — external 工作区 DB 注册表

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: WorkspaceManager 识别 external

**Files:**
- Modify: `backend/app/coding/workspace.py`
- Test: `backend/tests/test_registered_workspace.py`（追加）

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_registered_workspace.py`:

```python
def test_workspace_manager_external(tmp_path):
    from app.coding.workspace import WorkspaceManager
    WorkspaceManager._external_paths.clear()
    wm = WorkspaceManager()
    wm.register_external("ext_1", str(tmp_path))
    assert wm.get_workspace_path("ext_1") == tmp_path.resolve() or wm.get_workspace_path("ext_1") == tmp_path
    WorkspaceManager._external_paths.clear()


def test_workspace_manager_external_missing_folder(tmp_path):
    import pytest
    from app.coding.workspace import WorkspaceManager
    WorkspaceManager._external_paths.clear()
    missing = tmp_path / "gone"
    WorkspaceManager.load_external([("ext_2", str(missing))])
    wm = WorkspaceManager()
    with pytest.raises(FileNotFoundError):
        wm.get_workspace_path("ext_2")
    WorkspaceManager._external_paths.clear()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_registered_workspace.py -k external -v`
Expected: FAIL（`register_external`/`load_external`/`_external_paths` 不存在）

- [ ] **Step 3: 实现**

在 `backend/app/coding/workspace.py` 的 `WorkspaceManager` 类体，找到 class 级 `_workspace_path_cache: dict[str, Path] = {}` 那一行附近，加一个 class 级 dict：

```python
    _external_paths: dict[str, str] = {}   # ws_id -> 用户选的本地文件夹绝对路径 (external 工作区)
```

加两个方法（class 内）：

```python
    def register_external(self, ws_id: str, abs_path: str) -> None:
        """注册一个 external (打开本地文件夹) 工作区路径, 供 get_workspace_path 同步解析。"""
        WorkspaceManager._external_paths[ws_id] = abs_path

    @classmethod
    def load_external(cls, items: list[tuple[str, str]]) -> None:
        """启动时批量恢复 external 工作区路径 (从 DB registered_workspaces)。"""
        for ws_id, abs_path in items:
            cls._external_paths[ws_id] = abs_path
```

在 `get_workspace_path`（`workspace.py:385`）里，紧跟现有 `cached` 块（`if cached and cached.exists(): return cached`）之后、`for root in WORKSPACE_SEARCH_ROOTS:` 之前，插入 external 解析：

```python
        ext = self._external_paths.get(ws_id)
        if ext:
            ext_path = Path(ext)
            if ext_path.exists():
                self._workspace_path_cache[ws_id] = ext_path
                return ext_path
            raise FileNotFoundError(
                f"Workspace {ws_id} 关联的本地文件夹不存在(可能已移动/删除): {ext}"
            )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_registered_workspace.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/workspace.py backend/tests/test_registered_workspace.py
git commit -m "feat(desktop): WorkspaceManager 识别 external 工作区(同步缓存, external 优先)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `_is_sensitive_dir` + 打开本地文件夹端点

**Files:**
- Modify: `backend/app/routes/coding.py`
- Test: `backend/tests/test_open_local_workspace.py`

**背景:** 端点 `POST /coding/workspace/open-local`。校验目录存在/非敏感目录 → upsert `registered_workspaces`（按 (tenant_id, abs_path) 去重）→ `register_external` → 返回 ws_id。读 `coding.py` 顶部确认已 import：`uuid`、`select`、`get_auth_context`、`get_db`、`AuthContext`、`workspace_mgr`（模块级 `WorkspaceManager()` 实例）。`RegisteredWorkspace` 从 `app.models` import。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_open_local_workspace.py`:

```python
import pytest
import pytest_asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select

import app.database as database
from app.database import Base


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    from app.main import app
    from app.database import get_db
    from app.deps import get_auth_context, AuthContext
    async def _get_db():
        async with Session() as s:
            yield s
    # 注入一个最小 AuthContext (tenant 1 / user 1); 具体构造按 app.deps.AuthContext 实际字段
    async def _ctx():
        from app.models import User
        return AuthContext(user=User(id=1, username="t", tenant_id=1), tenant_id=1, tenant_role="tenant_admin", org_permissions={"*": True})
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_auth_context] = _ctx
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_open_local_creates_and_dedups(client, tmp_path):
    r1 = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    assert r1.status_code == 200
    ws_id = r1.json()["ws_id"]
    # 重复打开同路径 → 复用同 ws_id
    r2 = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    assert r2.status_code == 200 and r2.json()["ws_id"] == ws_id


@pytest.mark.asyncio
async def test_open_local_rejects_sensitive(client):
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(Path.home())})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_open_local_rejects_missing(client, tmp_path):
    r = await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path / "nope")})
    assert r.status_code == 400
```

（注：测试里 `AuthContext` 构造按 `app/deps.py` 的实际 `AuthContext` 字段对齐——实现 Step 前先读 `app/deps.py` 确认字段名，照实改这两行 fixture。前缀 `/api` 按 main.py 挂 coding 路由的实际前缀对齐——读 `app/main.py` include coding router 处确认是 `/api/coding` 还是 `/coding`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_local_workspace.py -v`
Expected: FAIL（端点不存在 404）

- [ ] **Step 3: 实现敏感目录助手 + 端点**

在 `backend/app/routes/coding.py` 加敏感目录助手（模块级）：

```python
def _is_sensitive_dir(p: Path) -> bool:
    """拒绝把系统/家目录根当工作区交给 agent。"""
    try:
        rp = p.resolve()
    except Exception:
        return True
    if not rp.exists() or not rp.is_dir():
        return True
    if rp == Path(rp.anchor):           # 文件系统根 /
        return True
    if rp == Path.home().resolve():     # 家目录根
        return True
    blacklist = {Path("/System"), Path("/Library"), Path("/Applications"), Path("/private"), Path("/usr"), Path("/bin"), Path("/etc"), Path("/var")}
    if rp in blacklist:
        return True
    if rp.parent == Path("/Volumes"):   # 卷根 /Volumes/<x>
        return True
    return False
```

加端点（放在现有 coding workspace 路由附近）：

```python
@router.post("/workspace/open-local")
async def open_local_workspace(
    body: dict,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """桌面: 打开用户本地文件夹当 external 工作区。指针进 DB, 不写用户文件夹。"""
    abs_path = (body.get("abs_path") or "").strip()
    apaas_app_id = body.get("apaas_app_id")
    if not abs_path:
        raise HTTPException(status_code=400, detail="abs_path 必填")
    p = Path(abs_path)
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=400, detail="文件夹不存在或不是目录")
    if _is_sensitive_dir(p):
        raise HTTPException(status_code=400, detail="该目录是系统/家目录根，过于宽泛，请选具体项目文件夹")
    resolved_abs = str(p.resolve())
    existing = (await db.execute(
        select(RegisteredWorkspace).where(
            RegisteredWorkspace.tenant_id == ctx.tenant_id,
            RegisteredWorkspace.abs_path == resolved_abs,
        )
    )).scalar_one_or_none()
    if existing:
        existing.last_opened_at = datetime.utcnow()
        if apaas_app_id is not None:
            existing.apaas_app_id = str(apaas_app_id)
        await db.commit()
        ws_id = existing.ws_id
        display_name = existing.display_name
    else:
        ws_id = f"{ctx.user.id}_{uuid.uuid4().hex[:8]}"
        display_name = p.name
        db.add(RegisteredWorkspace(
            ws_id=ws_id, abs_path=resolved_abs, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
            workspace_type="external", apaas_app_id=(str(apaas_app_id) if apaas_app_id is not None else None),
            display_name=display_name,
        ))
        await db.commit()
    workspace_mgr.register_external(ws_id, resolved_abs)
    return {
        "ws_id": ws_id, "disk_path": resolved_abs, "display_name": display_name,
        "workspace_type": "external", "apaas_app_id": (str(apaas_app_id) if apaas_app_id is not None else None),
    }
```

确认 `coding.py` 顶部已 import `datetime`、`uuid`、`Path`、`HTTPException`、`RegisteredWorkspace`（从 `app.models`）——缺则补。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_local_workspace.py -v`
Expected: PASS（3 passed）。若 `/api` 前缀或 AuthContext 字段不符导致 4xx/500，按 Step 1 注释对齐 fixture 后重跑。

- [ ] **Step 5: 提交**

```bash
git add backend/app/routes/coding.py backend/tests/test_open_local_workspace.py
git commit -m "feat(desktop): 打开本地文件夹端点 + 敏感目录拦截(指针进DB去重)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: list_workspaces 合并 external

**Files:**
- Modify: `backend/app/routes/coding.py`（`list_workspaces`，`coding.py:1033`）
- Test: `backend/tests/test_open_local_workspace.py`（追加）

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_open_local_workspace.py`:

```python
@pytest.mark.asyncio
async def test_list_includes_external(client, tmp_path):
    await client.post("/api/coding/workspace/open-local", json={"abs_path": str(tmp_path)})
    r = await client.get("/api/coding/workspaces")
    assert r.status_code == 200
    items = r.json()
    ext = [w for w in items if w.get("workspace_type") == "external"]
    assert len(ext) == 1 and ext[0]["disk_path"] == str(tmp_path.resolve())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_local_workspace.py::test_list_includes_external -v`
Expected: FAIL（列表无 external）

- [ ] **Step 3: 实现合并**

在 `list_workspaces`（`coding.py:1033`）的**最终 `return` 之前**（即所有 `.workspace.json` 导向的 legacy/app 绑定回填块之后，避免 external dict 被那些块处理），追加：

```python
    # external (打开本地文件夹) 工作区: 从 DB 注册表按租户合并进列表
    ext_rows = (await db.execute(
        select(RegisteredWorkspace).where(RegisteredWorkspace.tenant_id == ctx.tenant_id)
    )).scalars().all()
    for r in ext_rows:
        workspaces.append({
            "id": r.ws_id,
            "display_name": r.display_name or Path(r.abs_path).name,
            "folder_name": Path(r.abs_path).name,
            "disk_path": r.abs_path,
            "project_type": "external",
            "workspace_type": "external",
            "project_id": r.apaas_app_id,
            "apaas_app_id": r.apaas_app_id,
            "tenant_id": r.tenant_id,
            "user_id": r.user_id,
            "updated_at": r.last_opened_at.isoformat() if r.last_opened_at else None,
        })
```

（确认该函数最终是 `return workspaces` 或 `return <某处理后的列表>`——把 append 接在被 return 的那个列表变量上。app 托管项无 `workspace_type` 字段即视为非 external，前端据此区分。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_open_local_workspace.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/routes/coding.py backend/tests/test_open_local_workspace.py
git commit -m "feat(desktop): 工作区列表合并 external(DB注册表)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 启动从 DB 恢复 external 路径

**Files:**
- Modify: `backend/app/coding/workspace.py`（加 `restore_external_workspaces`）
- Modify: `backend/app/main.py`（lifespan 调用）
- Test: `backend/tests/test_registered_workspace.py`（追加）

**背景:** sidecar 重启后 `_external_paths`（内存）清空 → `get_workspace_path` 对 external 失效。启动从 DB 恢复。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_registered_workspace.py`:

```python
@pytest.mark.asyncio
async def test_restore_external_from_db(session):
    from app.coding.workspace import WorkspaceManager, restore_external_workspaces
    from app.models import RegisteredWorkspace
    WorkspaceManager._external_paths.clear()
    session.add(RegisteredWorkspace(ws_id="r_1", abs_path="/some/p", user_id=1, tenant_id=1, display_name="p"))
    await session.commit()
    await restore_external_workspaces(session)
    assert WorkspaceManager._external_paths.get("r_1") == "/some/p"
    WorkspaceManager._external_paths.clear()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_registered_workspace.py::test_restore_external_from_db -v`
Expected: FAIL（`restore_external_workspaces` 不存在）

- [ ] **Step 3: 实现 + lifespan 接线**

在 `backend/app/coding/workspace.py` 末尾（模块级，class 外）加：

```python
async def restore_external_workspaces(session) -> None:
    """启动时从 DB registered_workspaces 恢复 external 工作区路径到 WorkspaceManager 内存缓存。"""
    from sqlalchemy import select as _select
    from app.models import RegisteredWorkspace
    rows = (await session.execute(_select(RegisteredWorkspace))).scalars().all()
    WorkspaceManager.load_external([(r.ws_id, r.abs_path) for r in rows])
```

在 `backend/app/main.py` lifespan 里，在 `await init_db()` 和 seed 之后加（用 `AsyncSessionLocal`）：

```python
    # 桌面 external 工作区: 启动从 DB 注册表恢复路径缓存
    try:
        from app.database import AsyncSessionLocal
        from app.coding.workspace import restore_external_workspaces
        async with AsyncSessionLocal() as _ws_sess:
            await restore_external_workspaces(_ws_sess)
    except Exception as _e:
        import logging as _lg
        _lg.getLogger(__name__).warning("restore_external_workspaces 失败(非致命): %s", _e)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_registered_workspace.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/workspace.py backend/app/main.py backend/tests/test_registered_workspace.py
git commit -m "feat(desktop): 启动从 DB 恢复 external 工作区路径

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 桌面 sidecar 设 APAAS_WORKSPACE_ROOT（Part F）

**Files:**
- Modify: `backend/desktop_sidecar.py`
- Test: `backend/tests/test_desktop_sidecar.py`（追加）

**背景:** sidecar 不注入 `APAAS_WORKSPACE_ROOT` → app 托管工作区落到 `REPO_ROOT/workspaces`，冻结包里是相对二进制的诡异路径。指到 `data_dir/workspaces`。

- [ ] **Step 1: 写失败测试**

追加到 `backend/tests/test_desktop_sidecar.py`:

```python
def test_build_env_sets_workspace_root(tmp_path):
    env = desktop_sidecar.build_env(data_dir=tmp_path, port=9999)
    import os
    assert env["APAAS_WORKSPACE_ROOT"] == os.path.join(str(tmp_path), "workspaces")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_sidecar.py::test_build_env_sets_workspace_root -v`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `backend/desktop_sidecar.py` `build_env` 的 `written` 字典加（用 `os.path.join`，`os` 已 import）：

```python
        # app 托管工作区落 app_data_dir 下(稳定持久), 修冻结包相对二进制诡异路径
        "APAAS_WORKSPACE_ROOT": os.path.join(str(data_dir), "workspaces"),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_sidecar.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/desktop_sidecar.py backend/tests/test_desktop_sidecar.py
git commit -m "fix(desktop): sidecar 注入 APAAS_WORKSPACE_ROOT 指向 app_data_dir/workspaces

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Tauri 文件夹选择器插件

**Files:**
- Modify: `src-tauri/Cargo.toml`、`src-tauri/src/lib.rs`、`src-tauri/capabilities/default.json`

- [ ] **Step 1: 加依赖**

`src-tauri/Cargo.toml` 的 `[dependencies]` 加：

```toml
tauri-plugin-dialog = "2"
```

- [ ] **Step 2: 注册插件**

`src-tauri/src/lib.rs` 的 builder 链（现有 `.plugin(tauri_plugin_shell::init())` 等附近）加：

```rust
        .plugin(tauri_plugin_dialog::init())
```

- [ ] **Step 3: capability 放行**

`src-tauri/capabilities/default.json` 的 `permissions` 数组加一项：

```json
    "dialog:allow-open",
```

- [ ] **Step 4: 验证编译**

Run: `cd src-tauri && cargo check`
Expected: 编译通过（首次会拉取 tauri-plugin-dialog crate）。

- [ ] **Step 5: 提交**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/lib.rs src-tauri/capabilities/default.json
git commit -m "feat(desktop): 加 tauri-plugin-dialog — 原生文件夹选择器

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: 前端「打开本地文件夹」入口

**Files:**
- Modify: `frontend/src/api/coding.ts`
- Modify: `frontend/src/views/WorkspaceCatalogPage.vue`

**背景:** 仅 `__DESKTOP__`。流程: 点按钮 → Tauri `open({directory:true})` 选目录 → `ElMessageBox.confirm` 风险确认 → 调 `openLocalFolder` → 进 coding 工作区（复用 WorkspaceCatalogPage 现有「打开工作区」导航）。

- [ ] **Step 1: 加 API**

`frontend/src/api/coding.ts` 的 codingApi 对象里加（与现有 `createWorkspace` 同风格）：

```typescript
  openLocalFolder(abs_path: string, apaas_app_id?: number) {
    return request.post<any, { ws_id: string; disk_path: string; display_name: string; workspace_type: string; apaas_app_id: string | null }>(
      '/coding/workspace/open-local', { abs_path, apaas_app_id })
  },
```

- [ ] **Step 2: 加入口按钮 + 处理**

读 `frontend/src/views/WorkspaceCatalogPage.vue`，找到现有「新建工作区」按钮区与「打开/进入某工作区」的导航函数（记其函数名，如 `openWorkspace(ws)` / `goWorkspace`）。在按钮区加一个仅桌面可见的按钮：

```vue
<el-button v-if="isDesktop" @click="openLocalFolder">打开本地文件夹</el-button>
```

`<script setup>` 加（`isDesktop` 若未定义则 `const isDesktop = __DESKTOP__`）：

```typescript
import { ElMessage, ElMessageBox } from 'element-plus'
import { codingApi } from '@/api/coding'

async function openLocalFolder() {
  if (!__DESKTOP__) return
  const { open } = await import('@tauri-apps/plugin-dialog')
  const picked = await open({ directory: true, multiple: false, title: '选择要打开的项目文件夹' })
  if (!picked || typeof picked !== 'string') return
  try {
    await ElMessageBox.confirm(
      'AI 可在此文件夹内读写并运行命令（运行命令不受沙箱限制）。建议选用 git 管理或已备份的目录，以便误改可恢复。',
      '打开本地文件夹',
      { confirmButtonText: '我知道了，打开', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }  // 用户取消
  try {
    const ws = await codingApi.openLocalFolder(picked)
    // 复用现有「进入工作区」导航; 若现有函数签名不同, 按其实际入参传 ws.ws_id
    enterWorkspace(ws.ws_id)
  } catch (e: any) {
    ElMessage.error(`打开失败: ${e?.response?.data?.detail || e?.message || e}`)
  }
}
```

（`enterWorkspace(ws_id)` 用 WorkspaceCatalogPage 现有的进入工作区导航替换——读该文件找到现有点击工作区卡片时调的函数，复用它，把新 ws_id 传进去。若它需要完整 ws 对象，用返回的 `ws` 拼一个最小对象。）

- [ ] **Step 3: 桌面 build 通过**

Run: `cd frontend && npm run build:nocheck`
Expected: build 成功（`@tauri-apps/plugin-dialog` 动态 import，在线 build 不受影响——仅 `__DESKTOP__` 下走到）。
注: 若 `@tauri-apps/plugin-dialog` 未在 package.json，先 `cd frontend && npm i @tauri-apps/plugin-dialog@^2` 再 build，并把 package.json/package-lock.json 一并提交。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/coding.ts frontend/src/views/WorkspaceCatalogPage.vue frontend/package.json frontend/package-lock.json
git commit -m "feat(desktop): 资产库「打开本地文件夹」入口(原生选择器+风险确认)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Part A 数据模型 → Task 1 ✓
- Part B WorkspaceManager external + 列表合并 → Task 2(解析)+Task 4(列表)+Task 5(启动恢复) ✓
- Part C 打开流程(Tauri+端点+前端) → Task 3(端点)+Task 7(Tauri)+Task 8(前端) ✓
- Part D 安全(路径牢笼复用/敏感目录/打开确认) → 牢笼复用(无新任务, Task 2/3 用现有 `_resolve_safe`)+敏感目录(Task 3)+打开确认(Task 8) ✓；无软删除(spec 已定不做)
- Part E app 关联 → Task 3 存 apaas_app_id + Task 4 返回 + Task 8 前端可传(live 上下文复用现有 coding_app_id 机制, 见 [[coding_app_context_into_codegen]]) ✓
- Part F desktop APAAS_WORKSPACE_ROOT → Task 6 ✓

**类型/命名一致:** `RegisteredWorkspace` / `_external_paths` / `register_external` / `load_external` / `restore_external_workspaces` / `_is_sensitive_dir` / `open-local` / `openLocalFolder` / `workspace_type='external'` 跨任务一致 ✓

**执行期对账点(非占位, 以实际文件为准):**
- Task 3 测试 fixture 的 `AuthContext` 字段 + coding 路由前缀(`/api/coding` vs `/coding`) → 读 `app/deps.py` + `app/main.py` 对齐。
- Task 4 append 接到被 return 的列表变量。
- Task 8 `enterWorkspace` 复用 WorkspaceCatalogPage 现有进入工作区导航。
- Task 1 models/__init__.py 顶部 import 齐备(Mapped/mapped_column/String/Integer/DateTime/UniqueConstraint/Optional/datetime)。

**回归基线:** 后端全量 `pytest tests/ -q` 与改前一致(~1 预存 test_tool_registry, 零新增); 前端 `build:nocheck` 通过; `cargo check` 通过。

**Part E live 上下文说明:** apaas_app_id 已存 DB + 列表返回。把它喂进 agent 的「live 上下文」复用现有 `coding_app_id` 机制(coding 会话绑 app 时后端锁定+配读工具)——本计划做到「存+返回+前端可带」，真正喂入沿用既有链路，不在本计划新写 codegen 上下文逻辑(YAGNI)。
