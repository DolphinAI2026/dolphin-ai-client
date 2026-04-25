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


def to_orm(spec: Spec, *, tenant_id: int, kind: str = "draft", commit_sha: Optional[str] = None) -> SpecORM:
    return SpecORM(
        id=spec.id,
        application_id=spec.application_id,
        version=spec.version,
        kind=kind,
        commit_sha=commit_sha,
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


def bootstrap_from_legacy_config(
    *, application_id: int, legacy_config: dict, created_by: int
) -> Spec:
    """Reverse-engineer a Spec from legacy Application.config (best effort).

    Used to upgrade old apps to SPEC mode. The output Spec has all items
    confirmed=false so the user can review before transitioning to ready.
    """
    from app.spec.schema import (
        Goal,
        Role,
        ObjectSpec,
        FieldSpec,
        DictSpec,
        DictOption,
        PermissionSpec,
        PermissionRule,
    )

    data = legacy_config.get("data", legacy_config)
    spec = empty_spec(created_by=created_by, application_id=application_id)
    spec.phase = Phase.DRAFTING

    if data.get("appName"):
        spec.goal = Goal(
            title=data["appName"],
            summary="(从已有应用反推)",
            business_problem="(请补充)",
            confirmed=False,
        )

    for r in data.get("roles", []):
        spec.roles.append(Role(
            code=r["code"],
            name=r["name"],
            scope=r.get("scope", "ALL"),
            confirmed=False,
        ))

    for d in data.get("dicts", []):
        spec.dicts.append(DictSpec(
            code=d["code"],
            name=d["name"],
            options=[DictOption(**o) for o in d.get("options", [])],
            confirmed=False,
        ))

    for m in data.get("models", []):
        fields = []
        for f in m.get("fields", []):
            fields.append(FieldSpec(
                code=f["code"],
                name=f["name"],
                type=f.get("type", "单行输入"),
                required=f.get("required", False),
                dict_code=f.get("dict"),
                ref_model=f.get("ref", {}).get("model") if f.get("ref") else None,
                ref_field=f.get("ref", {}).get("field") if f.get("ref") else None,
                confirmed=False,
            ))
        spec.objects.append(ObjectSpec(
            code=m["code"],
            name=m["name"],
            fields=fields,
            confirmed=False,
        ))

    for p in data.get("permissions", []):
        spec.permissions.append(PermissionSpec(
            object_code=p["form"],
            rules=[PermissionRule(**r) for r in p.get("rules", [])],
            confirmed=False,
        ))

    spec.completeness = derive_completeness(spec)
    return spec


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
