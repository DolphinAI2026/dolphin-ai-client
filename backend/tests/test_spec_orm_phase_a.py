"""Phase A — Spec ORM 新字段（kind / commit_sha / tenant_id NOT NULL）

- kind: 'canonical' | 'draft'，默认 'draft'
- commit_sha: nullable string（apply 后绑定的 git commit）
- tenant_id: 不再有 default，必须显式传
"""
import pytest
from datetime import datetime
from sqlalchemy import select

from app.models.spec import Spec as SpecORM


@pytest.mark.asyncio
async def test_spec_default_kind_is_draft(db_session):
    spec = SpecORM(
        id="spec_phase_a_1",
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

    result = await db_session.execute(select(SpecORM).where(SpecORM.id == "spec_phase_a_1"))
    loaded = result.scalar_one()
    assert loaded.kind == "draft"
    assert loaded.commit_sha is None


@pytest.mark.asyncio
async def test_spec_kind_can_be_canonical_with_commit_sha(db_session):
    spec = SpecORM(
        id="spec_phase_a_2",
        application_id=None,
        version=1,
        kind="canonical",
        commit_sha="abc123def456",
        parent_spec_id=None,
        payload={"goal": None, "roles": [], "objects": []},
        phase="ready",
        completeness_confirmed=0,
        completeness_total=0,
        created_at=datetime(2026, 4, 25),
        updated_at=datetime(2026, 4, 25),
        created_by=1,
        tenant_id=1,
    )
    db_session.add(spec)
    await db_session.commit()

    result = await db_session.execute(select(SpecORM).where(SpecORM.id == "spec_phase_a_2"))
    loaded = result.scalar_one()
    assert loaded.kind == "canonical"
    assert loaded.commit_sha == "abc123def456"
