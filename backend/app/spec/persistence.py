"""Helpers to convert between Pydantic Spec and ORM Spec."""

from __future__ import annotations
from datetime import datetime, timezone
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.spec.schema import Spec, Completeness, Phase, derive_completeness
from app.models.spec import Spec as SpecORM


class OptimisticLockError(Exception):
    """触发场景：save_spec 时发现 DB 中的 version 比传入的 spec.version 大或不一致。
    意味着有并发会话已先一步保存。调用方应重新 load_spec → 合并 → 再 save。"""
    pass


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
    *, application_id: Optional[int], legacy_config: dict, created_by: int
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

    # 兼容遗留 V1 数据：op 可能是 "add,view,edit" 或 "add/edit" 这种合并值；
    # data 可能是 "CURRENT_USER_DEPT" 等业务方言。这里宽松归一化，保留能解析的，丢弃不合规的。
    _OP_ALIASES = {"all", "add", "edit", "delete", "view"}
    _DATA_ALIASES = {
        "all": "ALL", "self": "SELF", "dept": "DEPT", "dept_low": "DEPT_LOW",
        "current_user_dept": "DEPT", "current_user_dept_low_level": "DEPT_LOW",
    }
    for p in data.get("permissions", []):
        rules = []
        for r in p.get("rules", []):
            try:
                # 修正 op：拆分合并值，取第一个合规
                op = r.get("op", "all")
                if isinstance(op, str):
                    parts = [s.strip().lower() for s in op.replace("/", ",").split(",")]
                    valid = next((s for s in parts if s in _OP_ALIASES), None)
                    if not valid:
                        continue
                    r = {**r, "op": valid}
                # 修正 data：方言归一化
                d = r.get("data")
                if isinstance(d, str):
                    canonical = _DATA_ALIASES.get(d.lower())
                    if canonical:
                        r = {**r, "data": canonical}
                rules.append(PermissionRule(**r))
            except Exception:
                continue
        spec.permissions.append(PermissionSpec(
            object_code=p["form"],
            rules=rules,
            confirmed=False,
        ))

    spec.completeness = derive_completeness(spec)
    return spec


async def save_spec(db: AsyncSession, spec: Spec, *, tenant_id: int) -> SpecORM:
    """Upsert Spec by id with optimistic locking.

    新建（DB 无此 id）：直接插入，version=spec.version 或 1。
    已存在：DB row 的 version 必须等于 spec.version（即"我看到的版本"），
            否则 raise OptimisticLockError。成功时 row.version 自增 1。
    """
    existing = await db.execute(select(SpecORM).where(SpecORM.id == spec.id))
    row = existing.scalar_one_or_none()
    if row is None:
        row = to_orm(spec, tenant_id=tenant_id)
        if not row.version:
            row.version = 1
        db.add(row)
    else:
        if row.version != spec.version:
            raise OptimisticLockError(
                f"Spec {spec.id} version mismatch: db={row.version}, incoming={spec.version}"
            )
        row.payload = spec.model_dump(mode="json")
        row.phase = spec.phase.value
        row.completeness_confirmed = spec.completeness.confirmed
        row.completeness_total = spec.completeness.total
        row.application_id = spec.application_id
        row.parent_spec_id = spec.parent_spec_id
        row.updated_at = spec.updated_at
        row.version = row.version + 1  # CAS 自增
    await db.commit()
    # 保持调用方的 in-memory spec.version 与 DB 同步，连续 save 不会因 stale
    # version 触发 OptimisticLockError（如 stream 模式连续多个 spec_patch）
    spec.version = row.version
    return row


async def fork_canonical_to_draft(
    db: AsyncSession,
    *,
    canonical: Spec,
    user_id: int,
    tenant_id: int,
) -> Spec:
    """从 canonical Spec 派生一个 personal draft（深拷贝 + 新 id）。

    新 draft：
    - id 全新（new_spec_id）
    - parent_spec_id 指向 canonical.id
    - version 重置为 1（draft 自己的版本线，与 canonical 版本独立）
    - kind='draft'（持久化时由 to_orm 写入）
    - application_id 继承

    持久化 draft 到 DB，返回 in-memory Spec 对象。
    """
    new_id = new_spec_id()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # 通过 model_dump → re-parse 实现深拷贝
    payload = canonical.model_dump(mode="json")
    payload["id"] = new_id
    payload["parent_spec_id"] = canonical.id
    payload["version"] = 1
    payload["created_by"] = user_id
    payload["created_at"] = now.isoformat()
    payload["updated_at"] = now.isoformat()
    draft = Spec.model_validate(payload)

    # 持久化为 kind='draft'
    orm = to_orm(draft, tenant_id=tenant_id, kind="draft")
    db.add(orm)
    await db.commit()
    return draft
