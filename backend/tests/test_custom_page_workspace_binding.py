from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import Application, Conversation, Tenant, User, UserTenant
from app.routes.applications.section_content import _auto_bind_custom_page_workspace


@pytest.mark.asyncio
async def test_custom_page_host_backfills_workspace_app_binding(db_session):
    tenant = Tenant(tenant_name="portal-tenant", tenant_code="portal-tenant")
    owner = User(username="portal_owner", hashed_password="x")
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
        workspace_id="1_4aa2694c",
        coding_app_id=None,
    )
    db_session.add_all([app, conv])
    await db_session.commit()

    fake_rows = [
        {
            "id": "1_4aa2694c",
            "tenant_id": tenant.id,
            "project_id": None,
            "project_type": "form-page",
            "project_name": "form-page-portal-showcase-page",
            "display_name": "门户展示页",
        }
    ]

    with (
        patch("app.coding.workspace.WorkspaceManager.list_accessible_workspaces", return_value=fake_rows),
        patch("app.coding.workspace.WorkspaceManager.stamp_project_id", return_value=True) as stamp,
    ):
        bound_ws_id = await _auto_bind_custom_page_workspace(
            db_session,
            app_id=app.id,
            tenant_id=tenant.id,
            user_id=owner.id,
            bundle_dir="form-page-portal-showcase-page",
            component_tag="apaas-custom-portal-showcase-page",
        )

    assert bound_ws_id == "1_4aa2694c"
    stamp.assert_called_once_with("1_4aa2694c", app.id)
    refreshed = (
        await db_session.execute(select(Conversation).where(Conversation.id == conv.id))
    ).scalar_one()
    assert refreshed.coding_app_id == app.id
