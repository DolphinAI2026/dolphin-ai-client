import hashlib
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import User
from app.auth import get_password_hash, verify_password


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
