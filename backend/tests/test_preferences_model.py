"""UserPreference ORM model 测试"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.models.preference import UserPreference
from app.models import User


@pytest.mark.asyncio
async def test_user_preference_default(db_session):
    """新建 UserPreference 默认 default_mode='simple'"""
    user = User(username="pref_test_1", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    pref = UserPreference(user_id=user.id)
    db_session.add(pref)
    await db_session.commit()
    await db_session.refresh(pref)
    assert pref.default_mode == "simple"


@pytest.mark.asyncio
async def test_application_default_mode_nullable(db_session):
    """Application.default_mode 默认 None"""
    from app.models import Application, Tenant
    tenant = (await db_session.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if not tenant:
        tenant = Tenant(tenant_name="t1", tenant_code="t1")
        db_session.add(tenant)
        await db_session.flush()
    user = User(username="app_default_test", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    app = Application(
        user_id=user.id, tenant_id=tenant.id, created_by=user.id,
        app_name="测试", app_code="testapp",
    )
    db_session.add(app)
    await db_session.commit()
    await db_session.refresh(app)
    assert app.default_mode is None
