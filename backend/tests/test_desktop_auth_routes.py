"""桌面产品登录路由 — authority 模式集成测试。

用 StaticPool 内存库 + monkeypatch app.database.AsyncSessionLocal 保证
provision_desktop_account 写的行和路由 get_db 看到的是同一个库。
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base
from app import desktop_accounts as da
from app.auth import create_access_token
from app.models import User
from app.auth import get_password_hash


@pytest_asyncio.fixture
async def db_session_factory(monkeypatch):
    """Shared in-memory DB factory. Yields (Session, monkeypatch)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    # patch AsyncSessionLocal so deps.py / get_auth_context_from_token also see the same DB
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    yield Session


@pytest_asyncio.fixture
async def client(db_session_factory):
    Session = db_session_factory

    async with Session() as s:
        await da.provision_desktop_account(s, "dave", "pw123456")
        await s.commit()

    from app.main import app
    from app.database import get_db

    async def _get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_client(db_session_factory):
    """Client with a platform-admin user already provisioned in the in-memory DB."""
    Session = db_session_factory

    # Create a platform-admin user directly (not via provision_desktop_account which forces is_platform_admin=False)
    async with Session() as s:
        admin = User(
            username="superadmin",
            display_name="Super Admin",
            hashed_password=get_password_hash("adminpass123"),
            is_active=True,
            is_platform_admin=True,
            account_source="desktop",
        )
        s.add(admin)
        await s.flush()
        admin_id = admin.id
        await s.commit()

    admin_token = create_access_token(admin_id, tenant_id=None)  # no tid → platform_admin path in get_auth_context

    from app.main import app
    from app.database import get_db

    async def _get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {admin_token}"}) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_desktop_login_success(client):
    r = await client.post("/api/desktop-auth/login", json={"username": "dave", "password": "pw123456"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert body["username"] == "dave"


@pytest.mark.asyncio
async def test_desktop_login_wrong_password(client):
    r = await client.post("/api/desktop-auth/login", json={"username": "dave", "password": "nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_desktop_login_unknown_user(client):
    r = await client.post("/api/desktop-auth/login", json={"username": "ghost", "password": "pw123456"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_create_account_requires_platform_admin(client):
    # 无任何身份(无 Authorization) → 401/403
    r = await client.post("/api/desktop-auth/admin/accounts",
                          json={"username": "eve", "password": "pw123456"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_admin_create_account_success(admin_client):
    """平台管理员可成功建号, 响应含 username + tenant_id。"""
    r = await admin_client.post("/api/desktop-auth/admin/accounts",
                                json={"username": "newuser", "password": "strongpass1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "newuser"
    assert isinstance(body["tenant_id"], int)


@pytest.mark.asyncio
async def test_admin_create_account_new_user_can_login(admin_client):
    """平台管理员建的账号可以用 /login 登录。"""
    r = await admin_client.post("/api/desktop-auth/admin/accounts",
                                json={"username": "logintest", "password": "mypassword!"})
    assert r.status_code == 200, r.text

    login_r = await admin_client.post("/api/desktop-auth/login",
                                      json={"username": "logintest", "password": "mypassword!"})
    assert login_r.status_code == 200
    assert login_r.json()["username"] == "logintest"


@pytest.mark.asyncio
async def test_admin_create_account_short_password(admin_client):
    """密码不足 8 位 → 400。"""
    r = await admin_client.post("/api/desktop-auth/admin/accounts",
                                json={"username": "shortpw", "password": "abc"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_create_account_duplicate(admin_client):
    """重复建同名账号 → 409。"""
    payload = {"username": "dupuser", "password": "pass1234!"}
    r1 = await admin_client.post("/api/desktop-auth/admin/accounts", json=payload)
    assert r1.status_code == 200
    r2 = await admin_client.post("/api/desktop-auth/admin/accounts", json=payload)
    assert r2.status_code == 409


@pytest_asyncio.fixture
async def nonadmin_client(db_session_factory):
    """已认证但非平台管理员(普通桌面账号)的 client — 用于验证 admin 端点拒绝。"""
    Session = db_session_factory
    from app.deps import resolve_default_tenant_id_for_user
    async with Session() as s:
        u = await da.provision_desktop_account(s, "plainuser", "pw123456")
        await s.commit()
        uid = u.id
        tid = await resolve_default_tenant_id_for_user(s, uid)
    token = create_access_token(uid, tenant_id=tid)  # 有 tid 的普通用户票

    from app.main import app
    from app.database import get_db

    async def _get_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"Authorization": f"Bearer {token}"}) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_create_account_authenticated_nonadmin_forbidden(nonadmin_client):
    """已认证但 is_platform_admin=False 的用户调 admin 端点 → 403(安全关键负向用例)。"""
    r = await nonadmin_client.post("/api/desktop-auth/admin/accounts",
                                   json={"username": "eve", "password": "pw123456"})
    assert r.status_code == 403
