"""两实例端到端测试:account-service(authority) + sidecar(federation)。

authority 端用 services.account_service.main.create_app() — 和生产完全一致。
sidecar 端是一个只挂 desktop_auth.router 的最小 FastAPI app(与 account-service 对称,
public_account_base_url 非空 → 走 federation 分支)。

两实例联通机制:
  sidecar 的 _remote_authenticate 被替换为一个通过 ASGITransport 把请求发到
  authority_app 的函数。调用时临时将 settings.public_account_base_url 恢复为 "",
  确保 authority_app 走 authority 分支,不会触发无限递归。

这与生产场景的对应关系:
  - 生产里 authority 和 sidecar 是两个独立进程,各自有独立的环境变量/settings 实例。
  - 测试里无法真正隔离 settings 对象,所以在 _fake_remote_via_asgi 内临时恢复
    public_account_base_url="" 来模拟"authority 进程本身是 authority 模式"的语义。
"""
import pytest
import pytest_asyncio
from contextlib import contextmanager
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base
from app.config import settings as global_settings


# ─────────────────────────────────────────────────────────────────────────────
# 构造最小 sidecar app(只含 desktop_auth.router)
# ─────────────────────────────────────────────────────────────────────────────

def _make_sidecar_app(session_factory) -> FastAPI:
    """最小 federation sidecar: 只挂 desktop_auth.router + 覆盖 get_db。"""
    from app.routes import desktop_auth
    from app.database import get_db

    mini = FastAPI(title="sidecar-test")
    mini.include_router(desktop_auth.router, prefix="/api")

    async def _get_db_override():
        async with session_factory() as s:
            yield s

    mini.dependency_overrides[get_db] = _get_db_override
    return mini


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def two_instance_setup(monkeypatch):
    """
    搭两套独立 app + 内存库:
      - authority_app  (account-service via create_app(), authority 模式)
      - sidecar_app    (最小 FastAPI, desktop_auth.router, federation 模式)

    sidecar 的 _remote_authenticate 通过 ASGITransport 把请求发到 authority_app。

    Yields: (authority_client, sidecar_client, authority_session_factory, sidecar_session_factory)
    """
    # ── authority 实例 ──────────────────────────────────────────────────────
    auth_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with auth_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    authority_sf = async_sessionmaker(auth_engine, expire_on_commit=False, class_=AsyncSession)

    from services.account_service.main import create_app as make_authority
    from app.database import get_db

    # authority 先以 "" 模式初始化
    monkeypatch.setattr("app.config.settings.public_account_base_url", "")
    monkeypatch.setattr(database, "AsyncSessionLocal", authority_sf)

    authority_app = make_authority()

    async def _auth_get_db():
        async with authority_sf() as s:
            yield s

    authority_app.dependency_overrides[get_db] = _auth_get_db

    # ── sidecar 实例 ────────────────────────────────────────────────────────
    sc_engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with sc_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sidecar_sf = async_sessionmaker(sc_engine, expire_on_commit=False, class_=AsyncSession)
    sidecar_app = _make_sidecar_app(sidecar_sf)

    # sidecar 需要 public_account_base_url 非空以触发 federation 分支
    monkeypatch.setattr("app.config.settings.public_account_base_url", "http://authority.internal")
    monkeypatch.setattr(database, "AsyncSessionLocal", sidecar_sf)

    # ── 让 sidecar 的 _remote_authenticate 通过 ASGITransport 打到 authority_app ─
    #
    # 调用 authority_app 前临时将 settings.public_account_base_url 重置为 "":
    # 这模拟"authority 进程自身是 authority 模式(无 public_account_base_url)"的语义,
    # 避免单进程测试环境里两 app 共享同一 settings 对象造成的无限递归。
    authority_transport = ASGITransport(app=authority_app)

    async def _fake_remote_via_asgi(base_url: str, username: str, password: str):
        original = global_settings.public_account_base_url
        global_settings.public_account_base_url = ""  # 临时切 authority 模式
        try:
            async with AsyncClient(transport=authority_transport, base_url="http://authority.internal") as c:
                resp = await c.post(
                    "/api/desktop-auth/login",
                    json={"username": username, "password": password},
                )
        finally:
            global_settings.public_account_base_url = original  # 恢复

        if resp.status_code == 401:
            return None
        resp.raise_for_status()
        body = resp.json()
        return {"username": body.get("username", username)}

    monkeypatch.setattr("app.routes.desktop_auth._remote_authenticate", _fake_remote_via_asgi)

    authority_transport_for_client = ASGITransport(app=authority_app)
    sidecar_transport = ASGITransport(app=sidecar_app)

    async with AsyncClient(transport=authority_transport_for_client, base_url="http://authority.internal") as auth_c:
        async with AsyncClient(transport=sidecar_transport, base_url="http://sidecar.internal") as sc_c:
            yield auth_c, sc_c, authority_sf, sidecar_sf

    authority_app.dependency_overrides.clear()
    sidecar_app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_federation_correct_password_returns_sidecar_token(two_instance_setup):
    """正确密码 federation 登录 → 200 + sidecar 本地签的 token(含 username)。"""
    auth_c, sc_c, authority_sf, sidecar_sf = two_instance_setup

    # 在 authority 上预置账号
    from app import desktop_accounts as da
    async with authority_sf() as db:
        await da.provision_desktop_account(db, "alice", "password123")
        await db.commit()

    # sidecar federation 登录
    resp = await sc_c.post(
        "/api/desktop-auth/login",
        json={"username": "alice", "password": "password123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert body["access_token"]


@pytest.mark.asyncio
async def test_federation_wrong_password_returns_401(two_instance_setup):
    """错密码 federation 登录 → 401。"""
    auth_c, sc_c, authority_sf, sidecar_sf = two_instance_setup

    from app import desktop_accounts as da
    async with authority_sf() as db:
        await da.provision_desktop_account(db, "bob", "correct_pw")
        await db.commit()

    resp = await sc_c.post(
        "/api/desktop-auth/login",
        json={"username": "bob", "password": "wrong_pw"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_federation_mirrors_user_locally(two_instance_setup):
    """federation 登录成功后, sidecar 本地库里应有该用户的镜像。"""
    from sqlalchemy import select, func
    from app.models import User

    auth_c, sc_c, authority_sf, sidecar_sf = two_instance_setup

    from app import desktop_accounts as da
    async with authority_sf() as db:
        await da.provision_desktop_account(db, "carol", "pw_carol_99")
        await db.commit()

    resp = await sc_c.post(
        "/api/desktop-auth/login",
        json={"username": "carol", "password": "pw_carol_99"},
    )
    assert resp.status_code == 200

    # sidecar 本地库里有镜像
    async with sidecar_sf() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(User).where(User.username == "carol")
            )
        ).scalar()
    assert n == 1


@pytest.mark.asyncio
async def test_federation_second_login_reuses_mirror(two_instance_setup):
    """同一 federation 用户二次登录复用本地镜像, 不重复建号。"""
    from sqlalchemy import select, func
    from app.models import User

    auth_c, sc_c, authority_sf, sidecar_sf = two_instance_setup

    from app import desktop_accounts as da
    async with authority_sf() as db:
        await da.provision_desktop_account(db, "dave", "pw_dave_99")
        await db.commit()

    r1 = await sc_c.post(
        "/api/desktop-auth/login",
        json={"username": "dave", "password": "pw_dave_99"},
    )
    assert r1.status_code == 200

    r2 = await sc_c.post(
        "/api/desktop-auth/login",
        json={"username": "dave", "password": "pw_dave_99"},
    )
    assert r2.status_code == 200
    assert r2.json()["username"] == "dave"

    async with sidecar_sf() as s:
        n = (
            await s.execute(
                select(func.count()).select_from(User).where(User.username == "dave")
            )
        ).scalar()
    assert n == 1  # 只镜像一份


@pytest.mark.asyncio
async def test_authority_login_directly(two_instance_setup):
    """authority 端本身可以直接登录(不经 federation 转发)。"""
    auth_c, sc_c, authority_sf, sidecar_sf = two_instance_setup

    from app import desktop_accounts as da
    async with authority_sf() as db:
        await da.provision_local_admin_account(db, "eve", "eve_password")
        await db.commit()

    # 直接打 authority 的 /api/desktop-auth/login
    # 注: authority_client 的请求会在 _fake_remote_via_asgi 外触发,
    #     此时 public_account_base_url 是 "http://authority.internal"(sidecar 模式)。
    # 为了测试 authority 直接登录,我们临时切回 "" 模式。
    original = global_settings.public_account_base_url
    global_settings.public_account_base_url = ""
    try:
        resp = await auth_c.post(
            "/api/desktop-auth/login",
            json={"username": "eve", "password": "eve_password"},
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "eve"

        bad = await auth_c.post(
            "/api/desktop-auth/login",
            json={"username": "eve", "password": "bad"},
        )
        assert bad.status_code == 401
    finally:
        global_settings.public_account_base_url = original
