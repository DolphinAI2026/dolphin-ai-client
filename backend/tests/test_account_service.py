import hashlib
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import User
from app.auth import get_password_hash, verify_password
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture
async def account_db():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        yield s


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


@pytest.mark.asyncio
async def test_same_username_different_source_coexist(account_db):
    account_db.add(User(username="zhangsan", hashed_password="x", account_source="desktop"))
    account_db.add(User(username="zhangsan", hashed_password="y", account_source="apaas"))
    await account_db.flush()  # 复合唯一下不该抛 IntegrityError
    rows = (await account_db.execute(select(User).where(User.username == "zhangsan"))).scalars().all()
    assert len(rows) == 2


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


@pytest_asyncio.fixture
async def account_client(monkeypatch):
    # 共享内存库 + monkeypatch AsyncSessionLocal, 让路由(get_db)和测试看同一个库
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.AsyncSessionLocal", Session)
    monkeypatch.setattr("app.config.settings.public_account_base_url", "")  # authority
    from services.account_service.main import create_app
    app = create_app()
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


# ─── M2: bcrypt 72 字节截断 ──────────────────────────────────────────────────

def test_long_cjk_password_does_not_crash():
    """25 个中文字符 = 75 字节 > bcrypt 72 字节上限, 不应抛 ValueError。"""
    pw = "密" * 25
    h = get_password_hash(pw)          # 不该抛 ValueError
    assert h.startswith("$2")
    assert verify_password(pw, h) is True


# ─── M1: federation 撞名 (apaas 同名行共存) 不 MultipleResultsFound ────────────

@pytest.mark.asyncio
async def test_federation_mirror_with_apaas_namesake_no_crash(account_client):
    """federation 模式: 先有 apaas 同名行, 再 provision_desktop_account → 不应抛 AccountExistsError。
    login authority 模式下 verify_desktop_account 只认 desktop 行 → 正常登录。"""
    c, Session = account_client
    from app import desktop_accounts as da
    async with Session() as db:
        # 先放一个 apaas 同名账号 (模拟 aPaaS 登录同步过来的)
        db.add(User(username="dup", hashed_password="apaas-hash", account_source="apaas", is_active=True))
        await db.flush()
        # provision_desktop_account 应只检查 desktop 行, apaas 同名不应阻止
        await da.provision_desktop_account(db, "dup", "ruijing2026", is_platform_admin=False)
        await db.commit()
    # authority 模式登录 → verify_desktop_account 只认 desktop 行 → 成功
    r = await c.post("/api/desktop-auth/login", json={"username": "dup", "password": "ruijing2026"})
    assert r.status_code == 200
    assert r.json()["username"] == "dup"
