import pytest
from sqlalchemy import select
from app.models import Application


@pytest.mark.asyncio
async def test_register_ai_code_app_creates_and_is_idempotent(db_session):
    from app.routes.online_coding import _register_ai_code_app

    meta = {"id": "oc-xyz", "user_id": 1, "tenant_id": 1, "task": "我的 vibe 应用"}
    await _register_ai_code_app(db_session, meta)
    # 第二次调用应幂等，不重复建
    await _register_ai_code_app(db_session, meta)

    rows = (
        await db_session.execute(
            select(Application).where(Application.source_workspace_id == "oc-xyz")
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].app_type == "ai-code"
    assert rows[0].app_name == "我的 vibe 应用"
    assert rows[0].status == "developing"
