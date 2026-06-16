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
    assert user.is_platform_admin is False
    ut = (await session.execute(
        UserTenant.__table__.select().where(UserTenant.user_id == user.id)
    )).first()
    assert ut is not None and ut.is_default is True
    t = await session.get(Tenant, ut.tenant_id)
    assert t is not None and t.tenant_code


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


@pytest.mark.asyncio
async def test_apaas_same_username_not_verified_as_desktop(session):
    """核心安全属性: 同名 aPaaS 账号绝不能被 verify_desktop_account 认作桌面账号。"""
    from app.auth import get_password_hash
    session.add(User(
        username="dave", hashed_password=get_password_hash("pw123456"),
        is_active=True, account_source="apaas",
    ))
    await session.commit()
    assert await da.verify_desktop_account(session, "dave", "pw123456") is None
