# 桌面产品登录模块 MVP（SP-A+B+C）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「管理员在公网开桌面账号 → 桌面用独立产品登录页登录（经 sidecar 联邦到公网认账号）→ 进入应用（本地镜像 user+独立 tenant）→ 现有 platform_envs 配 aPaaS 能用」这条最小链路跑通，且与 aPaaS 登录链路完全隔离。

**Architecture:** 同一份 ai-builder 后端代码按运行角色分两态：**公网态(authority)** 校验桌面账号密码、管理员开号；**桌面 sidecar 态(federation, DESKTOP_MODE + public_account_base_url)** 把登录转发到公网，公网认证通过后在本地 SQLite 镜像 user+独立 tenant 并签发本地 JWT 给 WebView。桌面登录走独立 `/api/desktop-auth/*` 路由，绝不碰现有 `/api/auth/login` 的 aPaaS 链路。前端用编译期 `__DESKTOP__` flag 让 `/login` 指向新建的 `DesktopLogin.vue`，在线版 `Login.vue` 不动。

**Tech Stack:** FastAPI + SQLAlchemy(aiosqlite/aiomysql) + python-jose(HS256) + httpx；Vue3 + Vite + Pinia；沿用现有 sha256 密码哈希、`create_access_token`、`UserTenant` 多租户、`platform_envs`。

---

## 前置说明（实现者必读）

- **本机**：repo 根 `/Users/mars/Vibe Coding/ai-builder`，后端 venv `backend/.venv`(py3.13)，pytest 从 backend 跑：`cd backend && .venv/bin/python -m pytest ...`。前端在 `frontend/`。
- **分支**：本 MVP **依赖 Phase 0 的产物**（Task 4 改 `desktop_sidecar.py`、要用 `build:desktop` 与 DESKTOP_MODE 同源挂载），而 Phase 0 尚未并入 dev（在 `feat/desktop-phase0-spike`）。因此**从 `feat/desktop-phase0-spike` 切新分支 `feat/desktop-login-mvp`**（不要从 dev 切，dev 上没有 desktop_sidecar.py / build:desktop）。设计 spec + 本计划也在 phase0 分支上, 切出来即带上。
- **测试联邦不需要真连 agent.dfy**：用「第二个本地实例」当公网 authority，或在单测里 monkeypatch httpx 转发。真连 agent.dfy 是部署后的人工验收，不在本计划。
- **关键事实锚点（已核实）**：
  - `User` 模型 `backend/app/models/__init__.py:37-51`（username unique / hashed_password / is_active / is_platform_admin / apaas_* 全 nullable；**无 account_source**）。
  - 密码哈希 sha256：`backend/app/auth.py:48-54`（`get_password_hash` / `verify_password`）。
  - JWT：`create_access_token(user, tenant_id=...)` `backend/app/auth.py:81`；`decode_token` `auth.py:68`。
  - 建「用户+独立租户」五步范本：`backend/scripts/create_admin.py:35-101`；`seed_default_roles(db, tenant_id)` `backend/app/seed_data.py:13-76`（产 R_tenant_admin 等）。
  - `Tenant` `backend/app/models/tenant.py:10-34`（tenant_code unique）；`UserTenant` `tenant.py:37-50`。
  - 新 router 模板 `backend/app/routes/preferences.py`；注册点 `backend/app/main.py:14`(导入) / `:136-167`(include_router, 均 prefix=/api)。
  - `require_tenant_admin` `backend/app/deps.py:303-312`；`get_auth_context` 对非平台管理员强制要 UserTenant 成员行 `deps.py:191-209`。
  - 出站 httpx 范式 `backend/app/apaas_client.py:445-446`、`backend/app/llm_client.py:271-278`。
  - config 字段写法 `backend/app/config.py:26`；sidecar 注入 env `backend/desktop_sidecar.py:33-42`；DESKTOP_MODE 块 `backend/app/main.py:419`；init_db 幂等 ALTER 区 `backend/app/database.py:45-191`。
  - 前端登录页 `frontend/src/views/Login.vue`；路由 `frontend/src/router/index.ts:10-13`；user store `frontend/src/stores/user.ts:52-69`；authApi `frontend/src/api/auth.ts:127-129`；request 拦截器 `frontend/src/utils/request.ts:26-37`；守卫 `router/index.ts:187-193`；vite base `frontend/vite.config.ts:8`；`build:desktop` `frontend/package.json:12`。

---

## File Structure

新增：
- `backend/app/desktop_accounts.py` — 纯业务函数：`provision_desktop_account(db, username, password)`（建 User(account_source='desktop')+独立 Tenant+角色+UserTenant 管理员）、`verify_desktop_account(db, username, password)`。单一职责：桌面账号的建/验，不含路由/HTTP。
- `backend/app/routes/desktop_auth.py` — `APIRouter(prefix='/desktop-auth')`：`POST /login`（authority 校验 or federation 转发）、`POST /admin/accounts`（平台管理员开号）。
- `backend/tests/test_desktop_accounts.py`、`backend/tests/test_desktop_auth_routes.py`
- `frontend/src/views/DesktopLogin.vue` — 桌面产品登录页（账号+密码）。
- `frontend/src/api/desktopAuth.ts` — `desktopLogin({username,password})` → `POST /desktop-auth/login`。

修改：
- `backend/app/models/__init__.py` — User 加 `account_source` 列。
- `backend/app/database.py` — init_db 加一条幂等 `ALTER TABLE users ADD COLUMN account_source`。
- `backend/app/config.py` — 加 `public_account_base_url: str = ""`。
- `backend/desktop_sidecar.py` — build_env 注入 `PUBLIC_ACCOUNT_BASE_URL`。
- `backend/app/main.py` — 顶部 import + `include_router(desktop_auth.router, prefix='/api')`。
- `frontend/vite.config.ts` — `define: { __DESKTOP__: ... }`。
- `frontend/package.json` — `build:desktop` 加 `VITE_DESKTOP=1`。
- `frontend/src/router/index.ts` — `/login` 按 `__DESKTOP__` 分支组件。
- `frontend/env.d.ts`（或 `src/vite-env.d.ts`） — `declare const __DESKTOP__: boolean`。

---

## Task 1: User 加 account_source + 桌面账号建/验业务函数

**Files:**
- Modify: `backend/app/models/__init__.py`（User 内, apaas_* 字段附近）
- Modify: `backend/app/database.py`（init_db 幂等 ALTER 区）
- Create: `backend/app/desktop_accounts.py`
- Test: `backend/tests/test_desktop_accounts.py`

- [ ] **Step 1: 开分支（从 phase0 切, 因依赖其 desktop_sidecar.py/build:desktop）**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git checkout feat/desktop-phase0-spike && git checkout -b feat/desktop-login-mvp
```
> 不要从 dev 切——dev 上还没有 Phase 0 的 desktop_sidecar.py / build:desktop / DESKTOP_MODE 挂载。

- [ ] **Step 2: 写失败测试**

Create `backend/tests/test_desktop_accounts.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import desktop_accounts as da
from app.models import User
from app.models.tenant import Tenant, UserTenant


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest.mark.asyncio
async def test_provision_creates_user_tenant_membership(session):
    user = await da.provision_desktop_account(session, "alice", "pw123456")
    await session.commit()
    assert user.id and user.account_source == "desktop"
    assert user.is_platform_admin is False  # 桌面用户只是自己租户的管理员
    # 自带一个独立租户 + tenant_admin membership(is_default)
    ut = (await session.execute(
        UserTenant.__table__.select().where(UserTenant.user_id == user.id)
    )).first()
    assert ut is not None and ut.is_default is True
    t = await session.get(Tenant, ut.tenant_id)
    assert t is not None and t.tenant_code  # 有唯一 code


@pytest.mark.asyncio
async def test_provision_rejects_duplicate_username(session):
    await da.provision_desktop_account(session, "bob", "pw123456")
    await session.commit()
    with pytest.raises(da.AccountExistsError):
        await da.provision_desktop_account(session, "bob", "other")


@pytest.mark.asyncio
async def test_verify_desktop_account(session):
    await da.provision_desktop_account(session, "carol", "pw123456")
    await session.commit()
    u = await da.verify_desktop_account(session, "carol", "pw123456")
    assert u is not None and u.username == "carol"
    assert await da.verify_desktop_account(session, "carol", "wrong") is None
    assert await da.verify_desktop_account(session, "nope", "pw123456") is None
```

- [ ] **Step 3: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_accounts.py -v`
Expected: FAIL（`account_source` 不存在 / `desktop_accounts` 模块不存在）。

- [ ] **Step 4: 给 User 加列**

在 `backend/app/models/__init__.py` 的 User 类里、`apaas_tenant_id` 之后加：

```python
    # 账号来源: 'apaas'(aPaaS 同步/默认) | 'desktop'(桌面产品账号)。
    # 用于把桌面登录与 aPaaS 登录链路隔离, 避免 username 撞名被 aPaaS 抢先认证。
    account_source: Mapped[str] = mapped_column(String(20), default="apaas", nullable=False, server_default="apaas")
```
（确认顶部已 import `String`、`mapped_column`、`Mapped`——同文件其它字段在用。）

- [ ] **Step 5: init_db 加幂等 ALTER（兼容已存在的 MySQL 库, 如 agent.dfy）**

在 `backend/app/database.py` 的 init_db 幂等 ALTER 区（`45-191` 那批 try/except 里）追加一段，照该区现有写法：

```python
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN account_source VARCHAR(20) NOT NULL DEFAULT 'apaas'"
            )
    except Exception:
        pass  # 列已存在 / SQLite 新库已由 create_all 建好 — 幂等忽略
```

- [ ] **Step 6: 实现 desktop_accounts.py**

Create `backend/app/desktop_accounts.py`:

```python
"""桌面产品账号: 建号(带独立租户) + 校验。与 aPaaS 登录链路完全无关。"""
import secrets
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_password_hash, verify_password
from app.models import User
from app.models.tenant import Tenant, UserTenant, Role
from app.seed_data import seed_default_roles


class AccountExistsError(Exception):
    pass


async def _unique_tenant_code(db: AsyncSession, base: str) -> str:
    code = base
    n = 1
    while (await db.execute(select(Tenant).where(Tenant.tenant_code == code))).scalar_one_or_none():
        n += 1
        code = f"{base}-{n}"
    return code


async def provision_desktop_account(db: AsyncSession, username: str, password: str) -> User:
    """建一个桌面账号 + 它专属的独立租户(该用户是租户管理员)。照 create_admin.py 五步。"""
    existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if existing:
        raise AccountExistsError(username)

    # 1) 建独立租户
    code = await _unique_tenant_code(db, f"desktop-{username}")
    tenant = Tenant(tenant_name=f"{username} 的工作空间", tenant_code=code, status=1, max_applications=100)
    db.add(tenant)
    await db.flush()  # 拿 tenant.id

    # 2) 种系统角色
    await seed_default_roles(db, tenant.id, commit=False)

    # 3) 建用户(桌面来源, 非平台超管)
    user = User(
        username=username,
        display_name=username,
        hashed_password=get_password_hash(password),
        is_active=True,
        is_platform_admin=False,
        account_source="desktop",
    )
    db.add(user)
    await db.flush()  # 拿 user.id

    # 4) 取该租户的 tenant_admin 角色
    admin_role = (await db.execute(
        select(Role).where(Role.tenant_id == tenant.id, Role.role_code == "R_tenant_admin")
    )).scalar_one_or_none()

    # 5) 建 membership(默认租户, 管理员角色)
    db.add(UserTenant(
        user_id=user.id, tenant_id=tenant.id,
        role_id=admin_role.id if admin_role else None,
        is_default=True, status=1,
    ))
    await db.flush()
    return user


async def verify_desktop_account(db: AsyncSession, username: str, password: str) -> Optional[User]:
    """校验桌面账号密码。只认 account_source='desktop' 的账号, 不碰 aPaaS。"""
    user = (await db.execute(
        select(User).where(User.username == username, User.account_source == "desktop")
    )).scalar_one_or_none()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
```
> 注：`seed_default_roles` 的签名以 `seed_data.py:13` 实测为准；若它不接受 `commit=` 参数，则去掉该 kwarg（它内部不 commit 时本就在同一事务）。`Role` 的字段名(role_code)以 `models/tenant.py` 实测为准，若不同请对齐（实现者用 grep 确认 `R_tenant_admin` 的查询字段）。

- [ ] **Step 7: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_accounts.py -v`
Expected: PASS（3 个测试）。若 `seed_default_roles`/`Role` 字段名不符，按实测修正再过。

- [ ] **Step 8: 回归 import**

Run: `cd backend && .venv/bin/python -c "import app.main; print('OK')"`
Expected: `OK`。

- [ ] **Step 9: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/models/__init__.py backend/app/database.py backend/app/desktop_accounts.py backend/tests/test_desktop_accounts.py
git commit -m "feat(desktop-auth): User.account_source + 桌面账号建号(独立租户)/校验业务函数

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: desktop-auth 路由 — authority 登录（校验桌面账号, 绕开 aPaaS, 签 JWT）

**Files:**
- Create: `backend/app/routes/desktop_auth.py`
- Modify: `backend/app/main.py`（import + include_router）
- Test: `backend/tests/test_desktop_auth_routes.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_desktop_auth_routes.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base
from app import desktop_accounts as da


@pytest_asyncio.fixture
async def client(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    # 预置一个桌面账号
    async with Session() as s:
        await da.provision_desktop_account(s, "dave", "pw123456")
        await s.commit()
    from app.main import app
    async def _get_db():
        async with Session() as s:
            yield s
    from app.deps import get_db
    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_desktop_login_success(client):
    r = await client.post("/api/desktop-auth/login", json={"username": "dave", "password": "pw123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_desktop_login_wrong_password(client):
    r = await client.post("/api/desktop-auth/login", json={"username": "dave", "password": "nope"})
    assert r.status_code == 401
```
> 注：`get_db` 的实际位置以 `backend/app/deps.py` 为准（grep `def get_db`）。若依赖注入 fixture 写法与现有测试不同，参照 `backend/tests/` 里已有的 route 测试 fixture 对齐。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_routes.py -v`
Expected: FAIL（404，路由不存在）。

- [ ] **Step 3: 实现 desktop_auth.py（authority 模式）**

Create `backend/app/routes/desktop_auth.py`:

```python
"""桌面产品登录路由。与 /api/auth/login 的 aPaaS 链路完全分开。

- authority 模式(公网, 未配 public_account_base_url): 校验本地桌面账号密码, 签本地 JWT。
- federation 模式(桌面 sidecar, 配了 public_account_base_url): 见 Task 4。
"""
import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.config import settings
from app.deps import get_db, resolve_default_tenant_id_for_user
from app import desktop_accounts as da

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/desktop-auth", tags=["desktop-auth"])


class DesktopLoginIn(BaseModel):
    username: str
    password: str


class DesktopLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


async def _authority_login(db: AsyncSession, data: DesktopLoginIn) -> DesktopLoginOut:
    user = await da.verify_desktop_account(db, data.username, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    tenant_id = await resolve_default_tenant_id_for_user(db, user.id)
    token = create_access_token(user, tenant_id=tenant_id)
    return DesktopLoginOut(access_token=token, username=user.username)


@router.post("/login", response_model=DesktopLoginOut)
async def desktop_login(data: DesktopLoginIn, db: AsyncSession = Depends(get_db)):
    # federation 模式在 Task 4 接入; 默认 authority
    return await _authority_login(db, data)
```
> 注：`resolve_default_tenant_id_for_user` 在 `deps.py:34-45`（按 is_default 取默认租户）。`create_access_token(user, tenant_id=...)` 签名以 `auth.py:81` 为准。

- [ ] **Step 4: 注册路由**

`backend/app/main.py`：顶部 `from app.routes import (...)` 块（:14 起）加入 `desktop_auth`；在 include_router 区（:136-167）加：
```python
app.include_router(desktop_auth.router, prefix="/api")
```

- [ ] **Step 5: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_routes.py -v`
Expected: PASS（登录成功 200 + 错误密码 401）。

- [ ] **Step 6: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/routes/desktop_auth.py backend/app/main.py backend/tests/test_desktop_auth_routes.py
git commit -m "feat(desktop-auth): /api/desktop-auth/login authority 模式(校验桌面账号签JWT, 绕开aPaaS)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: 管理员开号端点（平台管理员建桌面账号）

**Files:**
- Modify: `backend/app/routes/desktop_auth.py`（加 admin 端点）
- Test: `backend/tests/test_desktop_auth_routes.py`（加用例）

- [ ] **Step 1: 加失败测试**（追加到 test_desktop_auth_routes.py）

```python
@pytest.mark.asyncio
async def test_admin_create_account_requires_platform_admin(client, monkeypatch):
    # 无平台管理员身份 → 403/401
    r = await client.post("/api/desktop-auth/admin/accounts",
                          json={"username": "eve", "password": "pw123456"})
    assert r.status_code in (401, 403)
```
> 完整「平台管理员成功建号」用例依赖构造 platform-admin JWT；可在实现后补一个带 `Authorization: Bearer <platform_admin_token>` 的成功用例（用 `create_access_token` 给一个 is_platform_admin=True 的 user 签票）。MVP 至少先卡住「未授权拒绝」。

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_routes.py::test_admin_create_account_requires_platform_admin -v`
Expected: FAIL（404）。

- [ ] **Step 3: 实现 admin 端点**（追加到 desktop_auth.py）

```python
from app.deps import get_auth_context, AuthContext


class CreateAccountIn(BaseModel):
    username: str
    password: str


class CreateAccountOut(BaseModel):
    username: str
    tenant_id: int


@router.post("/admin/accounts", response_model=CreateAccountOut)
async def admin_create_account(
    data: CreateAccountIn,
    db: AsyncSession = Depends(get_db),
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="仅平台管理员可开桌面账号")
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    try:
        user = await da.provision_desktop_account(db, data.username, data.password)
    except da.AccountExistsError:
        raise HTTPException(status_code=409, detail="账号已存在")
    await db.commit()
    tid = await resolve_default_tenant_id_for_user(db, user.id)
    return CreateAccountOut(username=user.username, tenant_id=tid)
```
> 注：`get_auth_context`/`AuthContext` 在 `deps.py:101`/`:18-31`。`ctx.user` 是否直接可用以实测为准（AuthContext 有 `user` 字段，deps.py:19-31）。

- [ ] **Step 4: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_routes.py -v`
Expected: PASS（含未授权拒绝；若加了平台管理员成功用例也应过）。

- [ ] **Step 5: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/routes/desktop_auth.py backend/tests/test_desktop_auth_routes.py
git commit -m "feat(desktop-auth): 平台管理员开桌面账号端点 POST /admin/accounts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: federation 模式 — sidecar 转发公网认证 + 本地镜像 + 签本地 JWT

**Files:**
- Modify: `backend/app/config.py`（加 `public_account_base_url`）
- Modify: `backend/desktop_sidecar.py`（注入 `PUBLIC_ACCOUNT_BASE_URL`）
- Modify: `backend/app/routes/desktop_auth.py`（login 加 federation 分支 + 本地镜像）
- Test: `backend/tests/test_desktop_auth_federation.py`

- [ ] **Step 1: config 加字段**

`backend/app/config.py` 在 `apaas_base_url`(:26) 附近加：
```python
    # 桌面 sidecar: 公网账号权威地址(authority)。空=本实例自身就是 authority。
    public_account_base_url: str = ""
```

- [ ] **Step 2: sidecar 注入 env**

`backend/desktop_sidecar.py` 的 build_env `written` dict（:33-42）加一行（允许进程环境覆盖, 便于测试切换）：
```python
        "PUBLIC_ACCOUNT_BASE_URL": os.environ.get("PUBLIC_ACCOUNT_BASE_URL", "https://agent.dfy.definesys.cn"),
```

- [ ] **Step 3: 写失败测试（monkeypatch 转发, 不真联网）**

Create `backend/tests/test_desktop_auth_federation.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base


@pytest_asyncio.fixture
async def client(monkeypatch):
    monkeypatch.setattr("app.config.settings.public_account_base_url", "https://public.test")
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    from app.main import app
    from app.deps import get_db
    async def _get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_federation_login_mirrors_user_and_signs_local_jwt(client, monkeypatch):
    # 假装公网认证通过, 返回用户名
    async def fake_remote(base_url, username, password):
        return {"username": username} if password == "pw123456" else None
    monkeypatch.setattr("app.routes.desktop_auth._remote_authenticate", fake_remote)

    ok = await client.post("/api/desktop-auth/login", json={"username": "frank", "password": "pw123456"})
    assert ok.status_code == 200 and ok.json()["access_token"]

    bad = await client.post("/api/desktop-auth/login", json={"username": "frank", "password": "wrong"})
    assert bad.status_code == 401
```

- [ ] **Step 4: 运行确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_federation.py -v`
Expected: FAIL（`_remote_authenticate` 不存在 / 仍走 authority）。

- [ ] **Step 5: 实现 federation 分支**

在 `desktop_auth.py` 加远端认证 + 本地镜像，并改 `desktop_login` 分流：

```python
import httpx


async def _remote_authenticate(base_url: str, username: str, password: str) -> Optional[dict]:
    """转发到公网 authority 校验; 通过返回 {username,...}, 否则 None。公网不可达抛 HTTPException(503)。"""
    url = base_url.rstrip("/") + "/api/desktop-auth/login"
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            resp = await c.post(url, json={"username": username, "password": password})
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="公网账号服务不可达")
    if resp.status_code == 401:
        return None
    resp.raise_for_status()
    body = resp.json()
    return {"username": body.get("username", username)}


async def _federation_login(db: AsyncSession, data: DesktopLoginIn, base_url: str) -> DesktopLoginOut:
    remote = await _remote_authenticate(base_url, data.username, data.password)
    if not remote:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    # 本地镜像该用户(+独立租户); 已存在则复用。本地密码随机(从不本地校验, 认证由公网做)。
    user = await da.verify_desktop_account(db, remote["username"], "")  # 仅探测是否已镜像
    existing = (await db.execute(
        __import__("sqlalchemy").select(User).where(User.username == remote["username"])
    )).scalar_one_or_none() if False else None  # 见下用更直接的查询
    from sqlalchemy import select as _select
    user = (await db.execute(_select(User).where(User.username == remote["username"]))).scalar_one_or_none()
    if user is None:
        import secrets as _secrets
        user = await da.provision_desktop_account(db, remote["username"], _secrets.token_urlsafe(32))
        await db.commit()
    tenant_id = await resolve_default_tenant_id_for_user(db, user.id)
    token = create_access_token(user, tenant_id=tenant_id)
    return DesktopLoginOut(access_token=token, username=user.username)
```
然后改 `desktop_login`：
```python
@router.post("/login", response_model=DesktopLoginOut)
async def desktop_login(data: DesktopLoginIn, db: AsyncSession = Depends(get_db)):
    base_url = settings.public_account_base_url
    if base_url:  # federation 模式(桌面 sidecar)
        return await _federation_login(db, data, base_url)
    return await _authority_login(db, data)  # authority 模式(公网)
```
> 清理：上面 `_federation_login` 里那段 `if False` 的探测是占位说明，实现时删掉, 直接用 `select(User).where(User.username==...)` 查镜像。需 `from app.models import User`。

- [ ] **Step 6: 运行确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_desktop_auth_federation.py tests/test_desktop_auth_routes.py -v`
Expected: 全 PASS（federation 镜像签票 + authority 仍工作）。

- [ ] **Step 7: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/config.py backend/desktop_sidecar.py backend/app/routes/desktop_auth.py backend/tests/test_desktop_auth_federation.py
git commit -m "feat(desktop-auth): federation 模式(sidecar 转发公网认证+本地镜像user/tenant+签本地JWT)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 前端编译期 __DESKTOP__ flag

**Files:**
- Modify: `frontend/vite.config.ts`、`frontend/package.json`、`frontend/env.d.ts`(或 `src/vite-env.d.ts`)

- [ ] **Step 1: vite define**

`frontend/vite.config.ts`：在 defineConfig 里加（与 `base` 同级）：
```ts
  define: {
    __DESKTOP__: JSON.stringify(process.env.VITE_DESKTOP === '1'),
  },
```

- [ ] **Step 2: build:desktop 传 flag**

`frontend/package.json` 的 `build:desktop` 改为：
```json
"build:desktop": "VITE_DESKTOP=1 VITE_BASE_URL=/ vite build --outDir dist-desktop --emptyOutDir",
```

- [ ] **Step 3: TS 声明**

在 `frontend/env.d.ts`（若无则 `frontend/src/vite-env.d.ts`）加：
```ts
declare const __DESKTOP__: boolean
```

- [ ] **Step 4: 验证**

Run: `cd frontend && VITE_DESKTOP=1 VITE_BASE_URL=/ npx vite build --outDir dist-desktop --emptyOutDir 2>&1 | tail -5`
Expected: 构建成功（此步还没用到 __DESKTOP__，仅验证 define 不报错）。

- [ ] **Step 5: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add frontend/vite.config.ts frontend/package.json frontend/env.d.ts frontend/src/vite-env.d.ts
git commit -m "build(desktop): 前端编译期 __DESKTOP__ flag (build:desktop 注入)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: 前端桌面登录页 + 路由分支 + API

**Files:**
- Create: `frontend/src/views/DesktopLogin.vue`、`frontend/src/api/desktopAuth.ts`
- Modify: `frontend/src/router/index.ts`（/login 按 __DESKTOP__ 分支）、`frontend/src/stores/user.ts`（加 desktopLogin action）

- [ ] **Step 1: API**

Create `frontend/src/api/desktopAuth.ts`:
```ts
import request from '@/utils/request'

export function desktopLogin(data: { username: string; password: string }) {
  return request.post('/desktop-auth/login', data)
}
```

- [ ] **Step 2: store action**

`frontend/src/stores/user.ts` 仿现有 `login`（:52-69）加：
```ts
  const desktopLogin = async (username: string, password: string) => {
    const { desktopLogin: api } = await import('@/api/desktopAuth')
    const res: any = await api({ username, password })
    setToken(res.access_token)
    await fetchUser()
    return { ok: true }
  }
```
并在 store return 里导出 `desktopLogin`。

- [ ] **Step 3: DesktopLogin.vue**

Create `frontend/src/views/DesktopLogin.vue`（账号+密码极简版, 视觉可后续对齐 Login.vue）：
```vue
<template>
  <div class="desktop-login">
    <div class="card">
      <h1>睿鲸 Builder</h1>
      <p class="sub">登录以打开桌面工作台</p>
      <el-input v-model="form.username" placeholder="账号" size="large" />
      <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password
                @keyup.enter="onSubmit" style="margin-top:12px" />
      <el-button type="primary" size="large" :loading="loading" style="width:100%;margin-top:16px" @click="onSubmit">登录</el-button>
      <p v-if="err" class="err">{{ err }}</p>
    </div>
  </div>
</template>
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = useRouter(); const route = useRoute(); const store = useUserStore()
const form = reactive({ username: '', password: '' })
const loading = ref(false); const err = ref('')

async function onSubmit() {
  if (!form.username || !form.password) { err.value = '请输入账号和密码'; return }
  loading.value = true; err.value = ''
  try {
    await store.desktopLogin(form.username, form.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.replace(redirect && !redirect.startsWith('/login') ? redirect : '/')
  } catch (e: any) {
    err.value = e?.response?.data?.detail || '登录失败'
  } finally { loading.value = false }
}
</script>
<style scoped>
.desktop-login{height:100vh;display:flex;align-items:center;justify-content:center;background:#f5f6fa}
.card{width:360px;padding:40px;background:#fff;border-radius:12px;box-shadow:0 8px 32px rgba(0,0,0,.08)}
.card h1{margin:0 0 4px;font-size:24px}
.sub{color:#888;margin:0 0 24px;font-size:14px}
.err{color:#f56c6c;font-size:13px;margin-top:12px}
</style>
```

- [ ] **Step 4: 路由分支**

`frontend/src/router/index.ts` 的 `/login`（:10-13）改为：
```ts
  { path: '/login', name: 'Login',
    component: () => (__DESKTOP__ ? import('@/views/DesktopLogin.vue') : import('@/views/Login.vue')) },
```

- [ ] **Step 5: 桌面构建 + 验证产物含新登录页**

Run: `cd frontend && npm run build:desktop && grep -rl "登录以打开桌面工作台" dist-desktop/assets/ | head`
Expected: 构建成功；产物里能搜到桌面登录页文案（证明 __DESKTOP__ 分支生效）。
> 同时 `grep -rl "请输入 aPaaS 账号" dist-desktop/assets/` 应为空（aPaaS 登录页未进桌面构建）。

- [ ] **Step 6: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add frontend/src/views/DesktopLogin.vue frontend/src/api/desktopAuth.ts frontend/src/router/index.ts frontend/src/stores/user.ts
git commit -m "feat(desktop): 桌面产品登录页 DesktopLogin.vue + /login 按 __DESKTOP__ 分支(在线版 Login.vue 不动)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: 端到端本地验证（两实例联邦）+ 验收记录

**Files:** Create `docs/handoff-2026-06-16-desktop-login-mvp-result.md`

目标：不依赖真 agent.dfy，用「第二个本地实例」当公网 authority，验证完整链路。

- [ ] **Step 1: 起一个本地 authority 实例（扮演公网）+ 开个桌面账号**

```bash
cd backend
# authority: 不配 public_account_base_url, 监听 9100
PORT=9100 DATABASE_URL="sqlite+aiosqlite:////tmp/ruijing-authority.db" JWT_SECRET_KEY=shared-mvp-secret \
  ALLOW_DEFAULT_ENCRYPTION_KEY=1 .venv/bin/python -c "
import os,asyncio
from app.database import init_db, AsyncSessionLocal
from app import desktop_accounts as da
async def m():
    await init_db()
    async with AsyncSessionLocal() as s:
        try:
            await da.provision_desktop_account(s,'mars','pw123456'); await s.commit(); print('account mars created')
        except da.AccountExistsError: print('exists')
asyncio.run(m())"
PORT=9100 DATABASE_URL="sqlite+aiosqlite:////tmp/ruijing-authority.db" JWT_SECRET_KEY=shared-mvp-secret \
  ALLOW_DEFAULT_ENCRYPTION_KEY=1 .venv/bin/python run.py &
AUTH_PID=$!; sleep 8
curl -s -X POST http://127.0.0.1:9100/api/desktop-auth/login -H 'content-type: application/json' \
  -d '{"username":"mars","password":"pw123456"}'; echo
```
Expected: authority 直接登录返回 access_token（authority 模式 OK）。

- [ ] **Step 2: 起 sidecar 态实例（federation → 指向 authority）**

```bash
cd backend
PORT=9200 DESKTOP_MODE=1 PUBLIC_ACCOUNT_BASE_URL="http://127.0.0.1:9100" \
  DATABASE_URL="sqlite+aiosqlite:////tmp/ruijing-sidecar.db" JWT_SECRET_KEY=shared-mvp-secret \
  ALLOW_DEFAULT_ENCRYPTION_KEY=1 DESKTOP_FRONTEND_DIR="$(cd ../frontend/dist-desktop && pwd)" \
  .venv/bin/python run.py &
SIDE_PID=$!; sleep 8
echo "--- federation login(经 sidecar 转发到 authority) ---"
curl -s -X POST http://127.0.0.1:9200/api/desktop-auth/login -H 'content-type: application/json' \
  -d '{"username":"mars","password":"pw123456"}'; echo
echo "--- 错误密码应 401 ---"
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:9200/api/desktop-auth/login \
  -H 'content-type: application/json' -d '{"username":"mars","password":"wrong"}'
```
Expected: federation 登录返回本地签发的 access_token；错误密码 401。`/tmp/ruijing-sidecar.db` 里镜像出了 user `mars` + 独立 tenant。

- [ ] **Step 3: 用 federation token 验证本地业务路由可用（不 403）**

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:9200/api/desktop-auth/login -H 'content-type: application/json' -d '{"username":"mars","password":"pw123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "--- 用 token 调 platform_envs 列表(应 200, 证明 tenant_admin 上下文有效) ---"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9200/api/platform-envs -H "Authorization: Bearer $TOKEN"
kill $AUTH_PID $SIDE_PID 2>/dev/null
```
Expected: `/api/platform-envs` 返回 200（不是 403）——证明镜像出的 user 带 tenant_admin membership、`require_tenant_admin` 通过。

- [ ] **Step 4: 整壳人工验证（可选, 控制器/用户做）**

`./scripts/build-desktop.sh` 重新出 .app（带新桌面登录页 + desktop-auth）；为让壳连本地 authority，临时把 `PUBLIC_ACCOUNT_BASE_URL` 指向 `http://127.0.0.1:9100`（或真 agent.dfy 部署后指它）。打开 .app → 看到**新的产品登录页**（不是 aPaaS 账密页）→ 用 mars/pw123456 登录 → 进入应用 → platform_envs 能配。

- [ ] **Step 5: 写验收记录**

Create `docs/handoff-2026-06-16-desktop-login-mvp-result.md`：记录两实例联邦验证结果、token 桥接是否用同密钥、镜像行为、platform_envs 200、遗留（密码 sha256→bcrypt、离线 TTL、SP-D 配置公网同步、真 agent.dfy 部署 + 管理员开号入口 UI、SSO provider）。

- [ ] **Step 6: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add docs/handoff-2026-06-16-desktop-login-mvp-result.md
git commit -m "docs(desktop-auth): 桌面产品登录 MVP 端到端(两实例联邦)验收记录

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec 覆盖**（对 `2026-06-16-desktop-login-hybrid-design.md`）：
- SP-A 公网账号体系 + 管理员开号 + login API → Task 1（建/验+account_source）、Task 2（authority login）、Task 3（admin 开号）。
- SP-B sidecar 联邦 → Task 4（federation 转发+本地镜像+本地 JWT）+ config/sidecar env。
- SP-C 桌面新登录页替旧页 → Task 5（__DESKTOP__ flag）、Task 6（DesktopLogin.vue + 路由分支, Login.vue 不动）。
- 两层身份分离（产品登录≠aPaaS）→ 独立 `/api/desktop-auth/*` + `account_source` 隔离 + 绕开 `_try_apaas_login_flow`（Task 1/2 核心）。
- 每人独立 tenant → `provision_desktop_account`（Task 1）。
- 登录后配 aPaaS（platform_envs 不变）→ Task 7 Step 3 验证其可用。
- 覆盖完整。SP-D（配置公网同步）/SP-E（离线 TTL、SSO）按设计是次步/后续，不在 MVP。

**2. Placeholder scan**：Task 4 `_federation_login` 里 `if False` 的占位探测已在注释明确要求实现时删除并用直接 select；其余步骤均给完整代码/命令。无 TBD/TODO 式空洞要求。`seed_default_roles`/`Role` 字段名标注「以实测为准」是因不同分支可能微差——属必要的实测校准提示，非偷懒。

**3. 类型/命名一致**：`account_source`（模型/查询/provision 一致）、`provision_desktop_account`/`verify_desktop_account`（Task1 定义→Task2/4 调用一致）、`/api/desktop-auth/login`（后端路由→前端 desktopAuth.ts→联邦转发 URL 一致）、`public_account_base_url`（config↔sidecar env `PUBLIC_ACCOUNT_BASE_URL`↔settings 读取一致）、`__DESKTOP__`（vite define↔d.ts↔router 一致）、token 存 `localStorage('token')`（复用现有）一致。无不一致。
