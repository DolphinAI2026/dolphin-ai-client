import pytest
from datetime import datetime
from sqlalchemy import select, inspect

from app.models.spec import Spec as SpecORM


@pytest.mark.asyncio
async def test_spec_orm_persist_and_load(db_session):
    spec = SpecORM(
        id="spec_test_1",
        application_id=None,
        version=1,
        parent_spec_id=None,
        payload={"goal": None, "roles": [], "objects": []},
        phase="gathering",
        completeness_confirmed=0,
        completeness_total=0,
        created_at=datetime(2026, 4, 25),
        updated_at=datetime(2026, 4, 25),
        created_by=1,
        tenant_id=1,
    )
    db_session.add(spec)
    await db_session.commit()

    result = await db_session.execute(select(SpecORM).where(SpecORM.id == "spec_test_1"))
    loaded = result.scalar_one()
    assert loaded.phase == "gathering"
    assert loaded.payload["roles"] == []


def _get_columns(table_name):
    def _inner(sync_session):
        insp = inspect(sync_session.connection())
        return [c["name"] for c in insp.get_columns(table_name)]
    return _inner


@pytest.mark.asyncio
async def test_application_has_canonical_spec_id_column(db_session):
    from app.models import Application  # noqa: F401
    cols = await db_session.run_sync(_get_columns("applications"))
    assert "canonical_spec_id" in cols


@pytest.mark.asyncio
async def test_conversation_has_spec_id_column(db_session):
    from app.models import Conversation  # noqa: F401
    cols = await db_session.run_sync(_get_columns("conversations"))
    assert "spec_id" in cols
