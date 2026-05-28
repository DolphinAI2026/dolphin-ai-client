import pytest
from sqlalchemy import select
from app.models import Application


class _FakeUser:
    id = 1


class _FakeCtx:
    user = _FakeUser()
    tenant_id = 1


@pytest.mark.asyncio
async def test_ensure_ai_code_application_creates_and_is_idempotent(db_session):
    from app.routes.vibe_coding_chat import _ensure_ai_code_application

    ctx = _FakeCtx()
    await _ensure_ai_code_application(db_session, "ws-xyz", ctx, "我的 vibe 应用")
    # 第二次调用应幂等，不重复建
    await _ensure_ai_code_application(db_session, "ws-xyz", ctx, "我的 vibe 应用")

    rows = (
        await db_session.execute(
            select(Application).where(Application.source_workspace_id == "ws-xyz")
        )
    ).scalars().all()

    assert len(rows) == 1
    assert rows[0].app_type == "ai-code"
    assert rows[0].app_name == "我的 vibe 应用"
    assert rows[0].status == "developing"
