from datetime import datetime

import pytest

from app.auth import get_password_hash
from app.crypto import encrypt_password
from app.deps import AuthContext
from app.models import APaaSUserCredential, User
from app.models.tenant import Tenant, UserTenant
from app.routes.apaas import apaas_embed_credentials


@pytest.mark.asyncio
async def test_embed_credentials_prefers_current_tenant_user_credential(db_session):
    tenant = Tenant(
        tenant_name="绿色测试",
        tenant_code="green",
        status=1,
        apaas_tenant_id_str="tenant-current",
    )
    user = User(
        username="tenant-admin",
        hashed_password=get_password_hash("secret"),
        is_active=True,
        apaas_token="legacy-token",
        apaas_tenant_id="tenant-legacy",
    )
    db_session.add_all([tenant, user])
    await db_session.flush()
    db_session.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1, is_default=True))
    db_session.add(
        APaaSUserCredential(
            user_id=user.id,
            local_tenant_id=tenant.id,
            apaas_user_id="apaas-user",
            apaas_tenant_id="tenant-current",
            base_url="https://apaas-trial.definesys.cn",
            account="tenant-admin",
            password_enc=encrypt_password("secret"),
            token="current-tenant-token",
            status="connected",
            last_login_at=datetime.utcnow(),
        )
    )
    await db_session.flush()

    ctx = AuthContext(
        user=user,
        tenant_id=tenant.id,
        tenant_role="tenant_admin",
        apaas_tenant_id="tenant-legacy",
        org_permissions={},
    )

    result = await apaas_embed_credentials(ctx, db_session)

    assert result.connected is True
    assert result.apaas_token == "current-tenant-token"
    assert result.apaas_tenant_id == "tenant-current"


@pytest.mark.asyncio
async def test_embed_credentials_falls_back_to_legacy_user_token(db_session):
    tenant = Tenant(
        tenant_name="默认租户",
        tenant_code="default",
        status=1,
        apaas_tenant_id_str="tenant-bound",
    )
    user = User(
        username="legacy-user",
        hashed_password=get_password_hash("secret"),
        is_active=True,
        apaas_token="legacy-token",
        apaas_tenant_id="tenant-legacy",
    )
    db_session.add_all([tenant, user])
    await db_session.flush()

    ctx = AuthContext(
        user=user,
        tenant_id=tenant.id,
        tenant_role="tenant_admin",
        apaas_tenant_id="tenant-legacy",
        org_permissions={},
    )

    result = await apaas_embed_credentials(ctx, db_session)

    assert result.connected is True
    assert result.apaas_token == "legacy-token"
    assert result.apaas_tenant_id == "tenant-bound"
