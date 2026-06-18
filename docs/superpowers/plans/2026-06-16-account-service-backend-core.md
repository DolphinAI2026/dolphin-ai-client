# account-service 后端核心 Implementation Plan (Plan A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 account-service 作为独立公网进程跑起来（桌面账号认证 + 开号，独立库 + 独立 JWT 密钥），桌面 federation 连它即可登录；同时解决 desktop/aPaaS 撞名、把密码哈希升级到 bcrypt。

**Architecture:** 不重写——`desktop_auth.router` 在 `public_account_base_url` 为空时就是 authority 模式（本地校验账密 + 开号）。account-service = 一个独立 entry（注入自己的 `DATABASE_URL`/`JWT_SECRET_KEY`，仿 `desktop_sidecar.py` 的早注入 env 模式）+ 一个只挂 `desktop_auth.router` 的 minimal FastAPI app。桌面 sidecar 继续跑 federation（转发到 account-service）。ai-builder 主后端不动业务逻辑，只改两处共享点：User 唯一约束（撞名）和密码哈希。

**Tech Stack:** FastAPI、SQLAlchemy async、PyInstaller（沿用桌面打包）、passlib[bcrypt]（已在 requirements）、jose（JWT）。

参考 spec：`docs/superpowers/specs/2026-06-16-account-service-design.md`

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/app/auth.py` | 密码哈希 → bcrypt（验旧 sha256 回落） | 修改 `verify_password`/`get_password_hash` |
| `backend/app/models/__init__.py` | User 唯一约束改复合 `(username, account_source)` | 修改 `:41` + 加 `__table_args__` |
| `backend/app/database.py` | SQLite/MySQL 唯一约束迁移（幂等） | 加迁移语句 |
| `backend/app/routes/auth/login.py` | aPaaS by-username 查询加 `account_source='apaas'` 过滤 | 修改 `:589` |
| `backend/services/account_service/__init__.py` | package 标记 | 新建 |
| `backend/services/account_service/main.py` | minimal FastAPI app，只挂 `desktop_auth.router` | 新建 |
| `backend/services/account_service/__main__.py` | entry：注入 account env（独立库/密钥）后启动 uvicorn | 新建 |
| `backend/tests/test_account_service.py` | account-service 认证/开号 + 撞名 + bcrypt | 新建 |

> account-service 复用 `app.models` / `app.desktop_accounts` / `app.auth` / `app.routes.desktop_auth`（同仓共享，spec §3 已定）。它**不**挂任何业务路由。

---

## Task 1: 密码哈希升级到 bcrypt（验旧 sha256 回落）

**Files:**
- Modify: `backend/app/auth.py:48-54`
- Test: `backend/tests/test_account_service.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_account_service.py
import hashlib
from app.auth import get_password_hash, verify_password


def test_new_hash_is_bcrypt_and_verifies():
    h = get_password_hash("ruijing2026")
    assert h.startswith("$2")  # bcrypt 前缀
    assert verify_password("ruijing2026", h) is True
    assert verify_password("wrong", h) is False


def test_legacy_sha256_still_verifies():
    # 旧账号库里是裸 sha256 hexdigest
    legacy = hashlib.sha256("oldpw".encode()).hexdigest()
    assert verify_password("oldpw", legacy) is True
    assert verify_password("wrong", legacy) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service.py -v -k password`
Expected: FAIL（`get_password_hash` 现在返回 sha256，不以 `$2` 开头）

- [ ] **Step 3: 改 auth.py**

```python
# backend/app/auth.py  替换 48-54 行的密码两个函数
import hashlib
from passlib.context import CryptContext

# bcrypt 为主；旧账号是裸 sha256 hexdigest（非 passlib 格式），verify 时手动回落。
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password.startswith("$2"):
        return _pwd_ctx.verify(plain_password, hashed_password)
    # 旧裸 sha256 回落（迁移期）
    return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password


def get_password_hash(password: str) -> str:
    return _pwd_ctx.hash(password)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service.py -v -k password`
Expected: PASS（两个测试都过）

- [ ] **Step 5: 回归桌面账号测试（确保旧 desktop 账号链路不破）**

Run: `cd backend && .venv/bin/python -m pytest tests/ -k "desktop" -q`
Expected: 全过（provision 用 get_password_hash 出 bcrypt，verify 通过）

- [ ] **Step 6: Commit**

```bash
git add backend/app/auth.py backend/tests/test_account_service.py
git commit -m "feat(auth): 密码哈希升级 bcrypt, 验旧 sha256 回落"
```

---

## Task 2: User 唯一约束改复合 (username, account_source)

**Files:**
- Modify: `backend/app/models/__init__.py:38-41`
- Modify: `backend/app/database.py`（加幂等迁移）
- Test: `backend/tests/test_account_service.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_account_service.py
import pytest
from sqlalchemy import select
from app.models import User


@pytest.mark.asyncio
async def test_same_username_different_source_coexist(account_db):
    # account_db fixture: 见 Task 5 conftest;一个 async session
    account_db.add(User(username="zhangsan", hashed_password="x", account_source="desktop"))
    account_db.add(User(username="zhangsan", hashed_password="y", account_source="apaas"))
    await account_db.flush()  # 复合唯一下不该抛 IntegrityError
    rows = (await account_db.execute(select(User).where(User.username == "zhangsan"))).scalars().all()
    assert len(rows) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service.py -v -k coexist`
Expected: FAIL（`username` 全局 unique，第二行 IntegrityError）

- [ ] **Step 3: 改 models**

```python
# backend/app/models/__init__.py
# 1) 给 User 类加 __table_args__（在 __tablename__ 下方）：
from sqlalchemy import UniqueConstraint  # 确认已 import

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", "account_source", name="uq_user_username_source"),
    )
    ...
    # 2) 第 41 行去掉列级 unique=True（保留 index=True）：
    username: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
```

- [ ] **Step 4: 加幂等迁移到 database.py**

在 `backend/app/database.py` 的 ALTER 迁移列表（`init_db` 里那个 `for stmt in [...]`）末尾追加。SQLite 无法 DROP 列级 unique index 时，旧库的全局 unique 索引名通常是 `ix_users_username` 或自动名；用"建复合唯一索引 + 尽力删旧唯一索引"的幂等组合：

```python
            # account-service: username 全局唯一 → 复合 (username, account_source)
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_username_source ON users(username, account_source)",
            "DROP INDEX IF EXISTS ix_users_username",
            "CREATE INDEX IF NOT EXISTS ix_users_username ON users(username)",
```

> 注：每条 ALTER/INDEX 都已被 `init_db` 的 try/except 包住（幂等）。MySQL 旧库的列级 unique 若名字不同，迁移时人工核对一次（`SHOW INDEX FROM users`）。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service.py -v -k coexist`
Expected: PASS

- [ ] **Step 6: 回归全量桌面 + 登录测试**

Run: `cd backend && .venv/bin/python -m pytest tests/ -k "desktop or login or auth" -q`
Expected: 全过

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/__init__.py backend/app/database.py backend/tests/test_account_service.py
git commit -m "feat(models): User 唯一约束改复合 (username, account_source) 解 desktop/apaas 撞名"
```

---

## Task 3: aPaaS 登录 by-username 查询加 account_source 过滤

**Files:**
- Modify: `backend/app/routes/auth/login.py:589`
- Test: `backend/tests/test_account_service.py`

撞名复合唯一后，`_ensure_apaas_user` 若仍按裸 username 查（`:589`），会命中 desktop 同名行并覆盖它。必须限定只找 aPaaS 行。

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/test_account_service.py
@pytest.mark.asyncio
async def test_apaas_login_does_not_clobber_desktop_user(account_db):
    from app.routes.auth.login import _ensure_apaas_user
    desktop = User(username="li", hashed_password="desk", account_source="desktop", is_platform_admin=True)
    account_db.add(desktop)
    await account_db.flush()
    # aPaaS 登录同名 li → 应新建一行 apaas, 不动 desktop 行
    await _ensure_apaas_user(account_db, "li", "apaaspw", {"id": "999"}, is_platform_admin=False)
    await account_db.flush()
    rows = (await account_db.execute(select(User).where(User.username == "li"))).scalars().all()
    assert len(rows) == 2
    desk = [r for r in rows if r.account_source == "desktop"][0]
    assert desk.hashed_password == "desk"  # 没被覆盖
    assert desk.is_platform_admin is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service.py -v -k clobber`
Expected: FAIL（现状命中 desktop 行覆盖，只有 1 行 + hashed_password 被改）

- [ ] **Step 3: 改 login.py:589**

```python
# backend/app/routes/auth/login.py  第 589 行
    if not user:
        user = (await db.execute(
            select(User).where(User.username == username, User.account_source == "apaas")
        )).scalar_one_or_none()
```

新建分支也要显式标 source（第 591-598 的 `User(...)` 加 `account_source="apaas"`，虽然 server_default 已是 apaas，但显式更安全）：

```python
        user = User(
            username=username,
            display_name=display_name or None,
            hashed_password=get_password_hash(password),
            apaas_user_id=apaas_uid,
            account_source="apaas",
            is_platform_admin=is_platform_admin,
            is_active=True,
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service.py -v -k clobber`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/auth/login.py backend/tests/test_account_service.py
git commit -m "fix(login): aPaaS by-username 查询限定 account_source=apaas, 不覆盖 desktop 同名"
```

---

## Task 4: account-service package（minimal app + entry）

**Files:**
- Create: `backend/services/__init__.py`、`backend/services/account_service/__init__.py`
- Create: `backend/services/account_service/main.py`
- Create: `backend/services/account_service/__main__.py`

- [ ] **Step 1: 建 package 标记**

```bash
mkdir -p backend/services/account_service
touch backend/services/__init__.py backend/services/account_service/__init__.py
```

- [ ] **Step 2: 写 minimal app（main.py）**

```python
# backend/services/account_service/main.py
"""account-service: 桌面账号权威。只挂认证 + 开号路由(desktop_auth.router)。
public_account_base_url 必须为空 → desktop_auth 走 authority 分支(本地校验)。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routes import desktop_auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()  # 建表 + 幂等迁移(含复合唯一)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="account-service", lifespan=lifespan)
    app.include_router(desktop_auth.router, prefix="/api")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "account-service"}

    return app


app = create_app()
```

- [ ] **Step 3: 写 entry（__main__.py，注入独立 env 后启动）**

```python
# backend/services/account_service/__main__.py
"""account-service 启动入口。在 import app.* 之前注入独立的库 + JWT 密钥。

env(部署时设)：
  ACCOUNT_SERVICE_DATABASE_URL  独立账号库
  ACCOUNT_SERVICE_JWT_SECRET    account-service 自己的 JWT 密钥(必须与任何 sidecar 不同)
  ACCOUNT_SERVICE_PORT          监听端口(默认 8100)
注意：必须保证 PUBLIC_ACCOUNT_BASE_URL 为空(authority 模式)。
"""
import os


def main() -> None:
    db = os.environ.get("ACCOUNT_SERVICE_DATABASE_URL")
    if db:
        os.environ["DATABASE_URL"] = db
    secret = os.environ.get("ACCOUNT_SERVICE_JWT_SECRET")
    if secret:
        os.environ["JWT_SECRET_KEY"] = secret
    os.environ["PUBLIC_ACCOUNT_BASE_URL"] = ""  # 强制 authority
    port = int(os.environ.get("ACCOUNT_SERVICE_PORT", "8100"))

    import uvicorn
    from app.config import settings  # 触发用上面注入的 env 实例化 Settings

    if not settings.jwt_secret_key:
        raise SystemExit("account-service 需要 ACCOUNT_SERVICE_JWT_SECRET 或 JWT_SECRET_KEY")

    uvicorn.run("services.account_service.main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 冒烟启动（手动核验，不入自动测试）**

Run:
```bash
cd backend && ACCOUNT_SERVICE_DATABASE_URL="sqlite+aiosqlite:////tmp/acc.db" \
  ACCOUNT_SERVICE_JWT_SECRET="test-secret-not-for-prod" ACCOUNT_SERVICE_PORT=8100 \
  .venv/bin/python -m services.account_service &
sleep 3 && curl -s http://127.0.0.1:8100/api/health
```
Expected: `{"status":"ok","service":"account-service"}`，然后 `kill %1`

- [ ] **Step 5: Commit**

```bash
git add backend/services/
git commit -m "feat(account-service): minimal app + 独立 env entry(authority 模式)"
```

---

## Task 5: account-service 认证 + 开号集成测试

**Files:**
- Create/Modify: `backend/tests/test_account_service.py`（加 `account_db` fixture + httpx app 测试）

- [ ] **Step 1: 加 fixture + 端到端测试**

```python
# backend/tests/test_account_service.py 顶部加 fixtures
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from app.database import Base


@pytest_asyncio.fixture
async def account_db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


@pytest_asyncio.fixture
async def account_client(monkeypatch):
    # 用共享内存库 + monkeypatch AsyncSessionLocal, 让路由和测试看同一个库
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.AsyncSessionLocal", Session)
    monkeypatch.setattr("app.config.settings.public_account_base_url", "")  # authority
    from services.account_service.main import create_app
    app = create_app()
    # 跳过 lifespan 的 init_db(已 create_all)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c, Session


@pytest.mark.asyncio
async def test_account_service_login_authority(account_client):
    c, Session = account_client
    from app import desktop_accounts as da
    async with Session() as db:
        await da.provision_desktop_account(db, "mars", "ruijing2026", is_platform_admin=True)
        await db.commit()
    # authority 登录
    r = await c.post("/api/desktop-auth/login", json={"username": "mars", "password": "ruijing2026"})
    assert r.status_code == 200
    assert r.json()["username"] == "mars"
    # 错密码
    r2 = await c.post("/api/desktop-auth/login", json={"username": "mars", "password": "x"})
    assert r2.status_code == 401
```

- [ ] **Step 2: 跑测试**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service.py -v -k "authority"`
Expected: PASS

- [ ] **Step 3: 全量回归**

Run: `cd backend && .venv/bin/python -m pytest tests/ -q`
Expected: 与改前一致（无新增失败；预存的本地 SQLite 失败不算）

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_account_service.py
git commit -m "test(account-service): authority 登录 + 开号集成测试"
```

---

## Task 6: 桌面 federation 连 account-service（端到端，两实例）

**Files:**
- Create: `backend/tests/test_account_service_federation.py`

复用现有 `test_desktop_auth_federation.py` 的两实例模式：一个 account-service（authority）+ 一个 sidecar（federation，`public_account_base_url` 指向 account-service）。

- [ ] **Step 1: 写两实例 federation 测试**

```python
# backend/tests/test_account_service_federation.py
import pytest
# 参照现有 tests/test_desktop_auth_federation.py 的两实例搭法:
#   - 起 authority app(account-service main, public_account_base_url 空)
#   - 起 sidecar app(public_account_base_url 指向 authority 的 base_url)
#   - sidecar /login 转发到 authority, 返回 sidecar 本地签的 token
# 断言: 正确密码 200 + token; 错密码 401; federation token 调 /api/platform-envs 200(本地镜像带 tenant_admin)
# 复刻 test_desktop_auth_federation.py 现有 3 个用例, 把 authority app 换成 account-service create_app()
```

> 实现时直接读 `backend/tests/test_desktop_auth_federation.py`，把它的 authority 端换成 `services.account_service.main.create_app()`，其余照搬。这验证 account-service 抽出后 federation 闭环不变。

- [ ] **Step 2: 跑测试**

Run: `cd backend && .venv/bin/python -m pytest tests/test_account_service_federation.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_account_service_federation.py
git commit -m "test(account-service): 桌面 federation 连 account-service 两实例端到端"
```

---

## Task 7: 桌面 sidecar 接线 + 文档

**Files:**
- Modify: `backend/desktop_sidecar.py`（注释/默认说明，不改逻辑）
- Create: `docs/account-service-deploy.md`（部署 + 接线说明）

- [ ] **Step 1: 写接线文档**

```markdown
# account-service 部署 + 桌面接线

## 部署 account-service(公网, 如 agent.dfy 旁)
env:
  ACCOUNT_SERVICE_DATABASE_URL=<独立账号库>
  ACCOUNT_SERVICE_JWT_SECRET=<account-service 专属密钥, 与任何 sidecar 不同>
  ACCOUNT_SERVICE_PORT=8100
启动: python -m services.account_service
必须 HTTPS(federation 转发明文密码)。

## 开号
POST /api/desktop-auth/admin/accounts (需平台管理员 token)
或脚本: python scripts/seed_desktop_account.py(指向 account-service 库)

## 桌面接线
sidecar 的 PUBLIC_ACCOUNT_BASE_URL 指向 account-service 公网地址:
  desktop_sidecar.py build_env 注入, 或 Tauri 传 env。
指向后桌面自动走 federation, 新机器无需复制 app.db。
留空 = 本地 authority 兜底(离线)。
```

- [ ] **Step 2: 在 desktop_sidecar.py 注释里指明接线点**

`backend/desktop_sidecar.py` 的 `PUBLIC_ACCOUNT_BASE_URL` 行注释补一句：「指向 account-service 公网地址即切 federation（见 docs/account-service-deploy.md）」。逻辑不动。

- [ ] **Step 3: Commit**

```bash
git add docs/account-service-deploy.md backend/desktop_sidecar.py
git commit -m "docs(account-service): 部署 + 桌面 federation 接线说明"
```

---

## Self-Review

- **Spec 覆盖**：§3 认证/开号 → Task 4-5；§4 信任模型（federation 本地签）→ Task 6 验证；§6 独立库 → Task 4 entry；§7 撞名复合唯一 → Task 2-3；§8 revocation → **不在 Plan A**（Plan B）；§9 管理后台 → **不在 Plan A**（Plan C）；§14 密码 bcrypt → Task 1。Plan A 范围 = 认证闭环 + 撞名 + 密码，与"产出可独立测试软件"一致。
- **Placeholder**：Task 6 的测试以"复刻现有 federation 测试、替换 authority 端"描述而非贴全量代码——这是有意的（现有 `test_desktop_auth_federation.py` 是权威参照，照搬比重写更可靠），执行者读那个文件即可。其余 task 代码完整。
- **类型/命名一致**：`provision_desktop_account(db, username, password, is_platform_admin=...)` 签名贯穿（Task 5）；`create_app()` 在 Task 4 定义、Task 5/6 引用；`account_source` 列名一致。

## 不在本计划（后续）

- **Plan B**：管账号 net-new API（列/改密/停用/管租户）+ revocation（短 TTL ≤30min / 启动重校验 / 心跳 / 停用传播本地镜像 is_active）。
- **Plan C**：管理后台 UI（复用 admin-spa 骨架、data 层重写）。
- **Pre-req（独立小 commit，可随时做）**：收敛 `mcp_server.py:95-103` 第二签发器回 `auth.py`（与抽取正交，spec §11）。
