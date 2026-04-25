"""Phase A — Spec save 乐观锁

并发 save 同一 spec：
- 第一个调用方成功（DB row.version 自增 1）
- 第二个调用方传入旧 version → raise OptimisticLockError
"""
import pytest
from sqlalchemy import select

from app.spec.persistence import (
    empty_spec,
    save_spec,
    load_spec,
    OptimisticLockError,
)
from app.models.spec import Spec as SpecORM


@pytest.mark.asyncio
async def test_first_save_succeeds_then_subsequent_increments_version(db_session):
    """首次 save 落库，version=1。再 load + save → DB version 应自增到 2。"""
    spec = empty_spec(created_by=1)
    spec.version = 1

    # 首次 save
    await save_spec(db_session, spec, tenant_id=1)
    row = (await db_session.execute(select(SpecORM).where(SpecORM.id == spec.id))).scalar_one()
    assert row.version == 1

    # 重新 load → version 应该等于 DB row.version
    reloaded = await load_spec(db_session, spec.id, tenant_id=1)
    assert reloaded is not None
    assert reloaded.version == 1

    # 再次 save → DB version 自增到 2
    await save_spec(db_session, reloaded, tenant_id=1)
    row2 = (await db_session.execute(select(SpecORM).where(SpecORM.id == spec.id))).scalar_one()
    assert row2.version == 2


@pytest.mark.asyncio
async def test_stale_version_raises_optimistic_lock_error(db_session):
    """两会话拉同一 spec（version=1）。A 先 save → 2。B 拿着 v=1 再 save → OptimisticLockError。"""
    spec = empty_spec(created_by=1)
    spec.version = 1
    await save_spec(db_session, spec, tenant_id=1)

    # 两次 load 模拟两会话各拿到 version=1 的副本
    spec_a = await load_spec(db_session, spec.id, tenant_id=1)
    spec_b = await load_spec(db_session, spec.id, tenant_id=1)
    assert spec_a is not None and spec_b is not None
    assert spec_a.version == 1 and spec_b.version == 1

    # A 先 save 成功（DB → 2）
    await save_spec(db_session, spec_a, tenant_id=1)
    row = (await db_session.execute(select(SpecORM).where(SpecORM.id == spec.id))).scalar_one()
    assert row.version == 2

    # B 拿着过期 version=1 再 save → 应触发 OptimisticLockError
    with pytest.raises(OptimisticLockError):
        await save_spec(db_session, spec_b, tenant_id=1)
