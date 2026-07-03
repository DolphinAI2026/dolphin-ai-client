from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models import Application


def _ctx(user_id: int = 11, tenant_id: int = 7, role: str = "member"):
    return SimpleNamespace(user=SimpleNamespace(id=user_id), tenant_id=tenant_id, tenant_role=role)


@pytest.mark.asyncio
async def test_list_applications_filters_by_app_type(db_session):
    from app.routes.applications.crud import list_applications

    db_session.add_all([
        Application(
            tenant_id=7,
            user_id=11,
            created_by=11,
            app_name="低代码应用",
            app_code="lowcode",
            app_type="low-code",
            status="draft",
        ),
        Application(
            tenant_id=7,
            user_id=11,
            created_by=11,
            app_name="全代码应用",
            app_code="fullcode",
            app_type="ai-code",
            status="draft",
        ),
    ])
    await db_session.commit()

    low_code = await list_applications(
        _ctx(),
        db_session,
        team_scope=None,
        include_remote=False,
        source_filter=None,
        include_config=True,
        app_type="low-code",
    )
    ai_code = await list_applications(
        _ctx(),
        db_session,
        team_scope=None,
        include_remote=False,
        source_filter=None,
        include_config=True,
        app_type="ai-code",
    )

    assert [app.app_code for app in low_code] == ["lowcode"]
    assert [app.app_code for app in ai_code] == ["fullcode"]
