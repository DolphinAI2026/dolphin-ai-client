import pytest
from sqlalchemy import select

from app.deps import AuthContext
from app.models import Application, PlatformEnv, User
from app.models.tenant import Tenant, UserTenant
from app.routes.applications import list_applications, list_applications_page, match_applications_by_name


async def _seed_user(db_session):
    tenant = Tenant(tenant_name="tenant", tenant_code="tenant")
    user = User(username="apps_owner", hashed_password="x")
    db_session.add_all([tenant, user])
    await db_session.flush()
    db_session.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1))
    await db_session.flush()
    return tenant, user


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user,
        tenant_id=tenant_id,
        tenant_role="tenant_admin",
        org_permissions={},
    )


@pytest.mark.asyncio
async def test_application_page_returns_page_and_counts(db_session):
    tenant, user = await _seed_user(db_session)
    for index in range(25):
        db_session.add(Application(
            user_id=user.id,
            tenant_id=tenant.id,
            created_by=user.id,
            app_name=f"Draft {index}",
            app_code=f"draft-{index}",
            status="draft",
        ))
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="Generating",
        app_code="generating",
        status="generating",
    ))
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="Completed",
        app_code="completed",
        status="completed",
    ))
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="Linked",
        app_code="linked",
        status="draft",
        apaas_app_id="remote-1",
    ))
    await db_session.commit()

    result = await list_applications_page(
        _ctx(user, tenant.id),
        db_session,
        page=2,
        page_size=10,
    )

    assert result["total"] == 28
    assert result["page"] == 2
    assert result["page_size"] == 10
    assert result["total_pages"] == 3
    assert len(result["items"]) == 10
    assert result["counts"] == {
        "all": 28,
        "active": 1,
        "deployed": 2,
        "draft": 25,
    }


@pytest.mark.asyncio
async def test_list_applications_include_config_false_omits_preview_keeps_counts(db_session):
    """include_config=False 应省掉沉重的 config_preview blob，但 models/roles 等计数仍由
    _enrich 解析得出，不能丢。"""
    import json

    tenant, user = await _seed_user(db_session)
    cfg = {
        "data": {
            "appName": "WithCfg",
            "appCode": "withcfg",
            "models": [{"code": "m1"}, {"code": "m2"}],
            "roles": [{"code": "r1"}],
            "dicts": [],
        }
    }
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="WithCfg",
        app_code="withcfg",
        status="draft",
        config_preview=json.dumps(cfg),
    ))
    await db_session.commit()

    # 默认 include_config=True：config_preview 内嵌
    full = await list_applications(
        _ctx(user, tenant.id), db_session,
        team_scope=None, include_remote=False, source_filter=None, include_config=True, app_type=None,
    )
    assert len(full) == 1
    assert full[0].config_preview is not None
    assert full[0].models == 2
    assert full[0].roles == 1

    # include_config=False：config_preview 省掉，但计数保留
    lean = await list_applications(
        _ctx(user, tenant.id), db_session,
        team_scope=None, include_remote=False, source_filter=None, include_config=False, app_type=None,
    )
    assert len(lean) == 1
    assert lean[0].config_preview is None
    assert lean[0].models == 2
    assert lean[0].roles == 1


@pytest.mark.asyncio
async def test_list_applications_uses_effective_tenant_for_unscoped_platform_admin(db_session):
    tenant, user = await _seed_user(db_session)
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="Imported App",
        app_code="imported-app",
        status="completed",
        apaas_app_id="remote-imported",
    ))
    await db_session.commit()

    result = await list_applications(
        AuthContext(
            user=user,
            tenant_id=0,
            tenant_role="platform_admin",
            org_permissions={"*": True},
            tenant_access_scope="unscoped",
        ),
        db_session,
        team_scope=None,
        include_remote=False,
        source_filter=None,
        include_config=False,
        app_type="low-code",
    )

    assert [app.apaas_app_id for app in result] == ["remote-imported"]


@pytest.mark.asyncio
async def test_control_plane_application_list_does_not_require_local_tenant(db_session):
    """Control Plane desktop scope is valid without a local SQLite tenant projection."""
    user = User(
        username="cp_apps_owner",
        hashed_password="x",
        account_source="control_plane",
        coding_tenant_id="cp-tenant-1",
    )
    db_session.add(user)
    await db_session.commit()

    result = await list_applications(
        AuthContext(
            user=user,
            tenant_id=0,
            tenant_role="tenant_admin",
            org_permissions={},
            tenant_access_scope="control_plane_code",
            control_plane_tenant_id="cp-tenant-1",
        ),
        db_session,
        team_scope=None,
        include_remote=False,
        source_filter=None,
        include_config=False,
        app_type="low-code",
    )

    assert result == []


@pytest.mark.asyncio
async def test_list_applications_uses_current_tenant_platform_env_for_remote_apps(db_session, monkeypatch):
    from app.routes.applications import crud

    tenant, user = await _seed_user(db_session)
    db_session.add(
        PlatformEnv(
            tenant_id=tenant.id,
            env_name="Tenant Env",
            base_url="https://apaas.example.com/backend",
            platform_tenant_id="apaas-tenant-1",
            token="env-token",
            is_default=True,
            status="connected",
        )
    )
    await db_session.commit()

    calls = []

    class FakeAPaaSClient:
        def __init__(self, *, base_url, tenant_id, token=None):
            calls.append({"base_url": base_url, "tenant_id": tenant_id, "token": token})

        async def query_app_list(self):
            return [{"id": "remote-1", "appName": "Remote App", "appCode": "remote-app"}]

    monkeypatch.setattr(crud, "APaaSClient", FakeAPaaSClient)

    apps = await list_applications(
        _ctx(user, tenant.id),
        db_session,
        team_scope=None,
        include_remote=True,
        source_filter=None,
        include_config=False,
        app_type=None,
    )

    assert calls == [{
        "base_url": "https://apaas.example.com/backend",
        "tenant_id": "apaas-tenant-1",
        "token": "env-token",
    }]
    assert len(apps) == 1
    assert apps[0].source == "remote"
    assert apps[0].apaas_app_id == "remote-1"
    assert apps[0].apaas_url == (
        "https://apaas.example.com/platform/apaas-tenant-1/admin/app-store/edit-app"
        "?appId=remote-1&currentStepIndex=0"
    )


@pytest.mark.asyncio
async def test_seed_binds_default_tenant_to_configured_apaas_tenant(db_session, monkeypatch):
    from app.config import settings
    from app.seed_data import bind_default_tenant_platform_env

    tenant = Tenant(tenant_name="Default Tenant", tenant_code="default")
    db_session.add(tenant)
    await db_session.flush()

    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example.com/backend", raising=False)
    monkeypatch.setattr(settings, "apaas_tenant_id", "apaas-tenant-1", raising=False)

    await bind_default_tenant_platform_env(db_session, tenant)
    await db_session.refresh(tenant)

    env = (
        await db_session.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == tenant.id,
                PlatformEnv.platform_tenant_id == "apaas-tenant-1",
            )
        )
    ).scalar_one()
    assert tenant.apaas_tenant_id_str == "apaas-tenant-1"
    assert tenant.apaas_env_id == env.id
    assert env.base_url == "https://apaas.example.com/backend"
    assert env.is_default is True


@pytest.mark.asyncio
async def test_seed_binds_default_tenant_with_configured_apaas_token(db_session, monkeypatch):
    from app.config import settings
    from app.seed_data import bind_default_tenant_platform_env

    tenant = Tenant(tenant_name="Default Tenant", tenant_code="default")
    db_session.add(tenant)
    await db_session.flush()

    monkeypatch.setattr(settings, "apaas_base_url", "https://apaas.example.com/backend", raising=False)
    monkeypatch.setattr(settings, "apaas_tenant_id", "apaas-tenant-1", raising=False)
    monkeypatch.setattr(settings, "apaas_token", "local-token", raising=False)

    await bind_default_tenant_platform_env(db_session, tenant)

    env = (
        await db_session.execute(
            select(PlatformEnv).where(
                PlatformEnv.tenant_id == tenant.id,
                PlatformEnv.platform_tenant_id == "apaas-tenant-1",
            )
        )
    ).scalar_one()
    assert env.token == "local-token"
    assert env.status == "connected"


@pytest.mark.asyncio
async def test_list_applications_bound_env_without_token_does_not_call_remote(db_session, monkeypatch):
    from app.routes.applications import crud

    tenant, user = await _seed_user(db_session)
    db_session.add(
        PlatformEnv(
            tenant_id=tenant.id,
            env_name="Bound Env",
            base_url="https://apaas.example.com/backend",
            platform_tenant_id="apaas-tenant-1",
            is_default=True,
            status="disconnected",
        )
    )
    await db_session.commit()

    class UnexpectedAPaaSClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("remote aPaaS client should not be created without token or credentials")

    monkeypatch.setattr(crud, "APaaSClient", UnexpectedAPaaSClient)

    apps = await list_applications(
        _ctx(user, tenant.id),
        db_session,
        team_scope=None,
        include_remote=True,
        source_filter=None,
        include_config=False,
        app_type=None,
    )

    assert apps == []


@pytest.mark.asyncio
async def test_application_page_stage_filter_and_page_clamp(db_session):
    tenant, user = await _seed_user(db_session)
    db_session.add_all([
        Application(
            user_id=user.id,
            tenant_id=tenant.id,
            created_by=user.id,
            app_name="Draft",
            app_code="draft",
            status="draft",
        ),
        Application(
            user_id=user.id,
            tenant_id=tenant.id,
            created_by=user.id,
            app_name="Generating",
            app_code="generating",
            status="generating",
        ),
    ])
    await db_session.commit()

    result = await list_applications_page(
        _ctx(user, tenant.id),
        db_session,
        stage="active",
        page=99,
        page_size=20,
    )

    assert result["total"] == 1
    assert result["page"] == 1
    assert result["total_pages"] == 1
    assert [item.app_code for item in result["items"]] == ["generating"]


@pytest.mark.asyncio
async def test_match_applications_by_name_handles_generic_suffix_similarity(db_session):
    tenant, user = await _seed_user(db_session)
    db_session.add_all([
        Application(
            user_id=user.id,
            tenant_id=tenant.id,
            created_by=user.id,
            app_name="客户拜访管理",
            app_code="customer_visit",
            status="completed",
        ),
        Application(
            user_id=user.id,
            tenant_id=tenant.id,
            created_by=user.id,
            app_name="仓库库存管理",
            app_code="warehouse_inventory",
            status="draft",
        ),
    ])
    await db_session.commit()

    result = await match_applications_by_name(
        _ctx(user, tenant.id),
        db_session,
        app_name_like="客户拜访管理应用",
        app_code_like="",
        limit=5,
    )

    assert [item.app_name for item in result] == ["客户拜访管理"]


@pytest.mark.asyncio
async def test_match_applications_by_name_flags_same_code_and_name_change(db_session):
    tenant, user = await _seed_user(db_session)
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="客户拜访管理",
        app_code="customer_visit",
        status="completed",
    ))
    await db_session.commit()

    result = await match_applications_by_name(
        _ctx(user, tenant.id),
        db_session,
        app_name_like="客户拜访管理应用",
        app_code_like="customer_visit",
        limit=5,
    )

    assert len(result) == 1
    assert result[0].app_name == "客户拜访管理"
    assert "code_exact" in result[0].match_reasons
    assert result[0].name_will_change is True


@pytest.mark.asyncio
async def test_match_applications_by_name_matches_by_code_without_name(db_session):
    tenant, user = await _seed_user(db_session)
    db_session.add(Application(
        user_id=user.id,
        tenant_id=tenant.id,
        created_by=user.id,
        app_name="客户拜访管理",
        app_code="customer_visit",
        status="completed",
    ))
    await db_session.commit()

    result = await match_applications_by_name(
        _ctx(user, tenant.id),
        db_session,
        app_name_like="",
        app_code_like="customer_visit",
        limit=5,
    )

    assert len(result) == 1
    assert result[0].app_name == "客户拜访管理"
    assert result[0].match_reasons == ["code_exact"]
    assert result[0].name_will_change is False
