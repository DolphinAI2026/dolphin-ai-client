"""C3-a — resolve_custom_page_dev_target: 自开发页面绑定工作区是否在 npm run serve。

dev_running=True → 预览 src 切 dev server；否则走既有 UMD custom-page-host。
本仓库无共享 db fixture，按惯例每测自建 StaticPool 内存库。
"""
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Application, Conversation, Tenant, User, UserTenant
from app.routes.applications.section_content import resolve_custom_page_dev_target


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_dev_target_returns_running_serve_port_for_bound_workspace(db_session):
    tenant = Tenant(tenant_name="dev-tenant", tenant_code="dev-tenant")
    owner = User(username="dev_owner", hashed_password="x")
    db_session.add_all([tenant, owner])
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))
    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="门户管理后台",
        app_code="portal-mgmt",
        apaas_app_id="853249733408325632",
    )
    conv = Conversation(
        user_id=owner.id,
        tenant_id=tenant.id,
        title="[迁移] 门户展示页",
        agent_type="coding",
        workspace_id="1_devws",
        coding_app_id=None,
    )
    db_session.add_all([app, conv])
    await db_session.commit()

    fake_rows = [
        {
            "id": "1_devws",
            "tenant_id": tenant.id,
            "project_id": None,
            "project_type": "form-page",
            "project_name": "form-page-portal-showcase-page",
            "display_name": "门户展示页",
        }
    ]

    with (
        patch("app.coding.workspace.WorkspaceManager.list_accessible_workspaces", return_value=fake_rows),
        patch("app.coding.workspace.WorkspaceManager.stamp_project_id", return_value=True),
        patch("app.coding.workspace.WorkspaceManager.is_serve_running", return_value={"running": True, "port": 8081}),
    ):
        result = await resolve_custom_page_dev_target(
            db_session,
            app_id=app.id,
            tenant_id=tenant.id,
            user_id=owner.id,
            bundle_dir="form-page-portal-showcase-page",
            component_tag="apaas-custom-portal-showcase-page",
        )

    assert result == {"dev_running": True, "port": 8081, "ws_id": "1_devws"}


@pytest.mark.asyncio
async def test_dev_target_reports_not_running_when_serve_down(db_session):
    tenant = Tenant(tenant_name="dev-tenant-2", tenant_code="dev-tenant-2")
    owner = User(username="dev_owner_2", hashed_password="x")
    db_session.add_all([tenant, owner])
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))
    app = Application(
        user_id=owner.id,
        tenant_id=tenant.id,
        created_by=owner.id,
        app_name="门户管理后台",
        app_code="portal-mgmt-2",
        apaas_app_id="853249733408325999",
    )
    conv = Conversation(
        user_id=owner.id,
        tenant_id=tenant.id,
        title="门户展示页",
        agent_type="coding",
        workspace_id="1_devws2",
        coding_app_id=app.id,
    )
    db_session.add_all([app, conv])
    await db_session.commit()

    fake_rows = [
        {
            "id": "1_devws2",
            "tenant_id": tenant.id,
            "project_id": app.id,
            "project_type": "form-page",
            "project_name": "form-page-portal-showcase-page",
            "display_name": "门户展示页",
        }
    ]

    with (
        patch("app.coding.workspace.WorkspaceManager.list_accessible_workspaces", return_value=fake_rows),
        patch("app.coding.workspace.WorkspaceManager.stamp_project_id", return_value=True),
        patch("app.coding.workspace.WorkspaceManager.is_serve_running", return_value={"running": False}),
    ):
        result = await resolve_custom_page_dev_target(
            db_session,
            app_id=app.id,
            tenant_id=tenant.id,
            user_id=owner.id,
            bundle_dir="form-page-portal-showcase-page",
            component_tag="apaas-custom-portal-showcase-page",
        )

    assert result == {"dev_running": False, "port": None, "ws_id": "1_devws2"}
