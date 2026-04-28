"""fork_canonical_to_draft 测试（Phase B Task 2）"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app.models import User, Application, Tenant
from app.models.spec import Spec as SpecORM
from app.builder_spec.schema import (
    Spec, Phase, Goal, Role, ObjectSpec, FieldSpec, DictSpec, DictOption,
    Completeness, derive_completeness,
)
from app.builder_spec.persistence import (
    new_spec_id, to_orm, fork_canonical_to_draft,
)


def _make_canonical_spec(application_id: int = 1, created_by: int = 1) -> Spec:
    """构造一个完整 canonical Spec（in-memory，未落库）"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    spec = Spec(
        id=new_spec_id(),
        application_id=application_id,
        version=3,  # canonical 自己有版本线
        parent_spec_id=None,
        phase=Phase.READY,
        goal=Goal(title="退款管理", summary="管理退款流程", business_problem="提升处理速度", confirmed=True),
        roles=[Role(code="approver", name="审批人", scope="DEPT", confirmed=True)],
        objects=[
            ObjectSpec(
                code="t_refund",
                name="退款单",
                fields=[
                    FieldSpec(code="amount", name="金额", type="数字", confirmed=True),
                ],
                confirmed=True,
            )
        ],
        dicts=[
            DictSpec(code="status", name="状态",
                     options=[DictOption(code="open", name="开启")], confirmed=True),
        ],
        permissions=[],
        completeness=Completeness(),
        created_at=now,
        updated_at=now,
        created_by=created_by,
    )
    spec.completeness = derive_completeness(spec)
    return spec


async def _seed_basics(db_session):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()
    user = User(username="u1", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    app = Application(
        user_id=user.id, tenant_id=tenant.id, created_by=user.id,
        app_name="app1", app_code="APP1",
    )
    db_session.add(app)
    await db_session.flush()
    return {"tenant": tenant, "user": user, "app": app}


@pytest.mark.asyncio
async def test_fork_canonical_returns_new_draft(db_session):
    seed = await _seed_basics(db_session)
    canonical = _make_canonical_spec(application_id=seed["app"].id, created_by=seed["user"].id)

    # 先把 canonical 落库（模拟正常状态）
    canonical_orm = to_orm(canonical, tenant_id=seed["tenant"].id, kind="canonical")
    db_session.add(canonical_orm)
    await db_session.commit()

    draft = await fork_canonical_to_draft(
        db_session,
        canonical=canonical,
        user_id=seed["user"].id + 100,  # 不同的 user 来 fork
        tenant_id=seed["tenant"].id,
    )

    assert draft.id != canonical.id
    assert draft.id.startswith("spec_")
    assert draft.parent_spec_id == canonical.id
    assert draft.version == 1  # draft 自己的版本线，重置为 1
    assert draft.application_id == seed["app"].id

    # DB 中应有 draft row 且 kind='draft'
    draft_row = (await db_session.execute(
        select(SpecORM).where(SpecORM.id == draft.id)
    )).scalar_one()
    assert draft_row.kind == "draft"
    assert draft_row.parent_spec_id == canonical.id


@pytest.mark.asyncio
async def test_fork_preserves_payload_content(db_session):
    seed = await _seed_basics(db_session)
    canonical = _make_canonical_spec(application_id=seed["app"].id, created_by=seed["user"].id)
    canonical_orm = to_orm(canonical, tenant_id=seed["tenant"].id, kind="canonical")
    db_session.add(canonical_orm)
    await db_session.commit()

    draft = await fork_canonical_to_draft(
        db_session,
        canonical=canonical,
        user_id=seed["user"].id,
        tenant_id=seed["tenant"].id,
    )

    # goal / roles / objects / dicts 一致
    assert draft.goal is not None
    assert draft.goal.title == canonical.goal.title
    assert draft.goal.business_problem == canonical.goal.business_problem
    assert len(draft.roles) == len(canonical.roles)
    assert draft.roles[0].code == canonical.roles[0].code
    assert len(draft.objects) == len(canonical.objects)
    assert draft.objects[0].code == canonical.objects[0].code
    assert len(draft.objects[0].fields) == len(canonical.objects[0].fields)
    assert draft.objects[0].fields[0].code == "amount"
    assert len(draft.dicts) == len(canonical.dicts)

    # 修改 draft 不应影响 canonical（深拷贝验证）
    draft.objects[0].fields.append(
        FieldSpec(code="reason", name="原因", type="单行输入", confirmed=False)
    )
    assert len(canonical.objects[0].fields) == 1
    assert len(draft.objects[0].fields) == 2


@pytest.mark.asyncio
async def test_fork_does_not_persist_canonical(db_session):
    """调 fork 不会修改 DB 中的 canonical row（kind/version 等）"""
    seed = await _seed_basics(db_session)
    canonical = _make_canonical_spec(application_id=seed["app"].id, created_by=seed["user"].id)
    canonical_orm = to_orm(canonical, tenant_id=seed["tenant"].id, kind="canonical")
    db_session.add(canonical_orm)
    await db_session.commit()

    canonical_id = canonical.id
    canonical_version = canonical.version

    await fork_canonical_to_draft(
        db_session,
        canonical=canonical,
        user_id=seed["user"].id,
        tenant_id=seed["tenant"].id,
    )

    # canonical row 仍在 DB 且未变
    canonical_row = (await db_session.execute(
        select(SpecORM).where(SpecORM.id == canonical_id)
    )).scalar_one()
    assert canonical_row.kind == "canonical"
    assert canonical_row.version == canonical_version
