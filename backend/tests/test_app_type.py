import pytest
from app.models import Application


@pytest.mark.asyncio
async def test_application_default_app_type_is_low_code(db_session):
    app = Application(
        user_id=1, tenant_id=1, created_by=1,
        app_name="测试应用", app_code="test_app",
    )
    db_session.add(app)
    await db_session.commit()
    await db_session.refresh(app)
    assert app.app_type == "low-code"
    assert app.source_workspace_id is None


@pytest.mark.asyncio
async def test_application_ai_code_with_workspace(db_session):
    app = Application(
        user_id=1, tenant_id=1, created_by=1,
        app_name="vibe 应用", app_code="vibe_app",
        app_type="ai-code", source_workspace_id="ws-abc123",
    )
    db_session.add(app)
    await db_session.commit()
    await db_session.refresh(app)
    assert app.app_type == "ai-code"
    assert app.source_workspace_id == "ws-abc123"
