"""Helpers to convert between Pydantic Spec and ORM Spec."""

from __future__ import annotations
from datetime import datetime, timezone
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.spec.schema import Spec, Completeness, Phase, derive_completeness
from app.models.spec import Spec as SpecORM


def new_spec_id() -> str:
    return f"spec_{uuid.uuid4().hex[:12]}"


def empty_spec(*, created_by: int, application_id: Optional[int] = None) -> Spec:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    s = Spec(
        id=new_spec_id(),
        application_id=application_id,
        phase=Phase.GATHERING,
        completeness=Completeness(),
        created_at=now,
        updated_at=now,
        created_by=created_by,
    )
    s.completeness = derive_completeness(s)
    return s


def to_orm(spec: Spec, *, tenant_id: int) -> SpecORM:
    return SpecORM(
        id=spec.id,
        application_id=spec.application_id,
        version=spec.version,
        parent_spec_id=spec.parent_spec_id,
        payload=spec.model_dump(mode="json"),
        phase=spec.phase.value,
        completeness_confirmed=spec.completeness.confirmed,
        completeness_total=spec.completeness.total,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
        created_by=spec.created_by,
        tenant_id=tenant_id,
    )


def from_orm(row: SpecORM) -> Spec:
    return Spec.model_validate(row.payload)


async def load_spec(db: AsyncSession, spec_id: str, *, tenant_id: int | None = None) -> Optional[Spec]:
    stmt = select(SpecORM).where(SpecORM.id == spec_id)
    if tenant_id is not None:
        stmt = stmt.where(SpecORM.tenant_id == tenant_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return from_orm(row) if row else None


async def save_spec(db: AsyncSession, spec: Spec, *, tenant_id: int) -> SpecORM:
    """Upsert Spec by id."""
    existing = await db.execute(select(SpecORM).where(SpecORM.id == spec.id))
    row = existing.scalar_one_or_none()
    if row is None:
        row = to_orm(spec, tenant_id=tenant_id)
        db.add(row)
    else:
        row.payload = spec.model_dump(mode="json")
        row.phase = spec.phase.value
        row.completeness_confirmed = spec.completeness.confirmed
        row.completeness_total = spec.completeness.total
        row.application_id = spec.application_id
        row.version = spec.version
        row.parent_spec_id = spec.parent_spec_id
        row.updated_at = spec.updated_at
    await db.commit()
    return row
