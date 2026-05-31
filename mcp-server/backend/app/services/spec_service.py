"""Spec 持久化 + 版本链服务。

职责：
- 把 BrainstormAgent 产出的 Spec envelope dict 落到 specs 表
- 版本链维护（version / parent_version）
- 查询：by id / by conversation / by code_name 的版本历史

表结构见 backend/app/models/agent_models.py 的 Spec 类。
不直接 import 顶层 `from app.models import Spec`（会和 SQLAlchemy Base 类名冲突），
只用 agent_models 模块命名空间。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import agent_models
from app.spec import validate_spec
from app.spec.schema import Spec as SpecEnvelope
from app.spec.validators import SpecValidationError


def new_spec_id() -> str:
    """生成 Spec ID。用时间戳 + random hex 简易替代 ULID（按时间粗略有序即可）"""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")[:17]
    return f"spec_{ts}_{secrets.token_hex(3)}"


def _envelope_from_dict(data: dict[str, Any]) -> SpecEnvelope:
    """把 dict 反序列化为 discriminated union。ValidationError 往上抛。"""
    return TypeAdapter(SpecEnvelope).validate_python(data)


async def save_spec(
    db: AsyncSession,
    *,
    brainstorm_session_id: str,
    envelope: dict[str, Any],
    parent_version: Optional[int] = None,
    validate: bool = True,
    reuse_envelope_spec_id: bool = False,
) -> agent_models.Spec:
    """把 Spec envelope 持久化到 specs 表。

    Args:
        envelope: 完整 Spec envelope dict（含 schema_version / spec_id / provenance / ...）
                  一般由 BrainstormAgent.emit_spec 产出。
        parent_version: 迭代场景下指向被迭代版本；None=首次产出
        validate: True 时走 Pydantic + 业务规则校验；False 仅做基础字段检查

    Returns:
        持久化后的 Spec ORM 对象（未 commit，由调用方决定事务边界）
    """
    # 1. Schema + 业务规则校验
    if validate:
        try:
            env_obj = _envelope_from_dict(envelope)
        except ValidationError as e:
            raise ValueError(f"Spec schema invalid: {e}") from e
        vresult = validate_spec(env_obj)
        if not vresult.ok:
            raise SpecValidationError(vresult.errors)
    else:
        env_obj = None  # 未校验

    # 2. 计算版本号
    if parent_version is not None:
        version = parent_version + 1
    else:
        # 首版。若 session 已有同 code_name 的 Spec，自增
        code_name = envelope.get("identity", {}).get("code_name") or ""
        stmt = (
            select(agent_models.Spec)
            .where(
                agent_models.Spec.brainstorm_session_id == brainstorm_session_id,
                agent_models.Spec.code_name == code_name,
            )
            .order_by(desc(agent_models.Spec.version))
            .limit(1)
        )
        prev = (await db.execute(stmt)).scalar_one_or_none()
        version = (prev.version + 1) if prev else 1

    # 3. 从 envelope 抽取索引字段
    identity = envelope.get("identity") or {}
    provenance = envelope.get("provenance") or {}

    code_name = identity.get("code_name") or ""
    if not code_name:
        raise ValueError("envelope.identity.code_name is required")

    # 覆盖 provenance 字段，确保和 DB 记录一致（即使 agent 传了别的 version）
    envelope = dict(envelope)  # shallow copy
    envelope["provenance"] = dict(provenance)
    envelope["provenance"]["version"] = version
    envelope["provenance"]["parent_version"] = parent_version

    # spec_id：每个持久化记录一个独立 ID（DB 主键）。
    # envelope 里的 spec_id 是 emit_spec tool 生成的临时 ID，默认被新 ID 覆盖。
    # 只有显式传 reuse_envelope_spec_id=True（如 CLI 导入场景）才复用原值。
    if reuse_envelope_spec_id and envelope.get("spec_id"):
        spec_id = envelope["spec_id"]
    else:
        spec_id = new_spec_id()
    envelope["spec_id"] = spec_id

    row = agent_models.Spec(
        id=spec_id,
        brainstorm_session_id=brainstorm_session_id,
        schema_version=envelope.get("schema_version") or "1.0",
        scene_type=envelope.get("scene_type"),
        code_name=code_name,
        widget_code=identity.get("widget_code"),
        version=version,
        parent_version=parent_version,
        created_by=provenance.get("created_by") or "agent",
        confidence=float(provenance.get("confidence") or 0.0),
        content=envelope,
    )
    db.add(row)
    await db.flush()  # 保证 id 生效，但不 commit（让调用方决定事务）
    return row


async def get_spec(db: AsyncSession, spec_id: str) -> Optional[agent_models.Spec]:
    return (
        await db.execute(select(agent_models.Spec).where(agent_models.Spec.id == spec_id))
    ).scalar_one_or_none()


async def get_spec_versions(
    db: AsyncSession,
    *,
    brainstorm_session_id: Optional[str] = None,
    code_name: Optional[str] = None,
) -> list[agent_models.Spec]:
    """获取版本链。按 version 降序（最新在前）。

    至少传一个过滤条件，否则返回空列表（不允许裸扫全表）。
    """
    if not brainstorm_session_id and not code_name:
        return []
    stmt = select(agent_models.Spec)
    if brainstorm_session_id:
        stmt = stmt.where(agent_models.Spec.brainstorm_session_id == brainstorm_session_id)
    if code_name:
        stmt = stmt.where(agent_models.Spec.code_name == code_name)
    stmt = stmt.order_by(desc(agent_models.Spec.version))
    return list((await db.execute(stmt)).scalars().all())


async def get_latest_spec_for_session(
    db: AsyncSession, brainstorm_session_id: str
) -> Optional[agent_models.Spec]:
    stmt = (
        select(agent_models.Spec)
        .where(agent_models.Spec.brainstorm_session_id == brainstorm_session_id)
        .order_by(desc(agent_models.Spec.version))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def rollback_to_version(
    db: AsyncSession,
    *,
    spec_id: str,
) -> agent_models.Spec:
    """把指定 spec_id（某个历史版本）克隆为新版本（版本号 = 最新 + 1）。

    不删除后续版本（保持历史可追溯）；只是在版本链顶端加一条 content 相同的新记录，
    provenance.created_by 打上 user 标记。
    """
    target = await get_spec(db, spec_id)
    if not target:
        raise ValueError(f"spec {spec_id} not found")

    # 找同 code_name 的最大版本号
    stmt = (
        select(agent_models.Spec)
        .where(
            agent_models.Spec.brainstorm_session_id == target.brainstorm_session_id,
            agent_models.Spec.code_name == target.code_name,
        )
        .order_by(desc(agent_models.Spec.version))
        .limit(1)
    )
    top = (await db.execute(stmt)).scalar_one_or_none()
    new_version = (top.version + 1) if top else 1

    new_id = new_spec_id()
    new_content = dict(target.content or {})
    new_content = {**new_content, "spec_id": new_id}
    prov = dict(new_content.get("provenance") or {})
    prov["version"] = new_version
    prov["parent_version"] = target.version
    prov["created_by"] = "user"  # 用户回滚视作 user 操作
    prov["created_at"] = datetime.now(timezone.utc).isoformat()
    new_content["provenance"] = prov

    row = agent_models.Spec(
        id=new_id,
        brainstorm_session_id=target.brainstorm_session_id,
        schema_version=target.schema_version,
        scene_type=target.scene_type,
        code_name=target.code_name,
        widget_code=target.widget_code,
        version=new_version,
        parent_version=target.version,
        created_by="user",
        confidence=target.confidence,
        content=new_content,
    )
    db.add(row)
    await db.flush()
    return row
