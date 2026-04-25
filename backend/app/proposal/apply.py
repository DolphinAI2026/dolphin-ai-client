"""第二道门 + ops 执行（apply 流程，Phase B v1）"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.spec.schema import Spec
from app.spec.persistence import load_spec
from app.models import Application
from app.models.collaboration import ChangeProposal
from app.proposal.validation import validate as validate_spec


REVERSIBILITY_LEVELS = {"green": 0, "yellow": 1, "red": 2}


@dataclass
class ApplyOp:
    kind: str           # 'create_object' | 'add_field' | 'modify_field' | 'drop_field' | ...
    target: str         # eg 'object:Customer'
    detail: dict
    reversibility: str  # 'green' | 'yellow' | 'red'


@dataclass
class ApplyPlan:
    ops: list[ApplyOp]
    has_irreversible: bool
    rebase_required: bool
    rebase_reason: Optional[str] = None
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ops": [{"kind": o.kind, "target": o.target, "detail": o.detail,
                     "reversibility": o.reversibility} for o in self.ops],
            "has_irreversible": self.has_irreversible,
            "rebase_required": self.rebase_required,
            "rebase_reason": self.rebase_reason,
            "issues": self.issues,
        }


def diff_spec(canonical: Optional[Spec], draft: Spec) -> list[ApplyOp]:
    """对比 canonical 和 draft，输出 ops 清单 + 可逆性标记。

    简化实现：
    - 新增 object → create_object (yellow)
    - 删 object → drop_object (red)
    - 加字段 → add_field (yellow)
    - 删字段 → drop_field (red)
    - 改字段类型 → modify_field (red)
    - 加 dict / 加 role → green
    """
    ops: list[ApplyOp] = []
    canonical_objs = {o.code: o for o in canonical.objects} if canonical else {}
    draft_objs = {o.code: o for o in draft.objects}

    for code, obj in draft_objs.items():
        if code not in canonical_objs:
            ops.append(ApplyOp(
                kind="create_object", target=f"object:{code}",
                detail={"name": obj.name, "field_count": len(obj.fields)},
                reversibility="yellow",
            ))
            for f in obj.fields:
                ops.append(ApplyOp(
                    kind="add_field", target=f"object:{code}.{f.code}",
                    detail={"type": f.type}, reversibility="yellow",
                ))
        else:
            old = canonical_objs[code]
            old_fields = {f.code: f for f in old.fields}
            new_fields = {f.code: f for f in obj.fields}
            for fc, f in new_fields.items():
                if fc not in old_fields:
                    ops.append(ApplyOp(
                        kind="add_field", target=f"object:{code}.{fc}",
                        detail={"type": f.type}, reversibility="yellow",
                    ))
                elif old_fields[fc].type != f.type:
                    ops.append(ApplyOp(
                        kind="modify_field", target=f"object:{code}.{fc}",
                        detail={"old_type": old_fields[fc].type, "new_type": f.type},
                        reversibility="red",
                    ))
            for fc in old_fields.keys() - new_fields.keys():
                ops.append(ApplyOp(
                    kind="drop_field", target=f"object:{code}.{fc}",
                    detail={}, reversibility="red",
                ))

    for code in canonical_objs.keys() - draft_objs.keys():
        ops.append(ApplyOp(
            kind="drop_object", target=f"object:{code}",
            detail={}, reversibility="red",
        ))

    # dicts / roles 简化处理：仅 add，不 diff（v1）
    canonical_dicts = {d.code for d in canonical.dicts} if canonical else set()
    for d in draft.dicts:
        if d.code not in canonical_dicts:
            ops.append(ApplyOp(
                kind="add_dict", target=f"dict:{d.code}",
                detail={"option_count": len(d.options)},
                reversibility="green",
            ))

    canonical_roles = {r.code for r in canonical.roles} if canonical else set()
    for r in draft.roles:
        if r.code not in canonical_roles:
            ops.append(ApplyOp(
                kind="add_role", target=f"role:{r.code}",
                detail={"name": r.name},
                reversibility="green",
            ))

    return ops


async def build_apply_plan(
    db: AsyncSession,
    *,
    application_id: int,
    draft_spec_id: str,
    base_canonical_id: Optional[str],
    tenant_id: int,
) -> ApplyPlan:
    """计算第二道门：算 diff + 检测 rebase + 标可逆性。不联平台的纯计算部分。"""
    issues: list[str] = []
    rebase_required = False
    rebase_reason = None

    # 1. 取当前 canonical（可能比 base 更新 → rebase 需要）
    app = (await db.execute(select(Application).where(Application.id == application_id))).scalar_one()
    current_canonical_id = app.canonical_spec_id
    if base_canonical_id and current_canonical_id and current_canonical_id != base_canonical_id:
        rebase_required = True
        rebase_reason = f"canonical 已从 {base_canonical_id} 推进到 {current_canonical_id}"

    canonical = await load_spec(db, current_canonical_id, tenant_id=tenant_id) if current_canonical_id else None
    draft = await load_spec(db, draft_spec_id, tenant_id=tenant_id)
    if not draft:
        return ApplyPlan(ops=[], has_irreversible=False, rebase_required=False,
                         issues=["draft spec 不存在"])

    # 2. 重跑第一道门（apply 时再确认）
    val = validate_spec(draft)
    if not val.ok:
        issues.append("draft 校验未通过")
        for r in (val.completeness, val.consistency, val.naming, val.markdown):
            if not r.ok:
                issues.extend(r.issues)

    # 3. 计算 ops + 可逆性
    ops = diff_spec(canonical, draft)
    has_irreversible = any(o.reversibility == "red" for o in ops)

    return ApplyPlan(
        ops=ops,
        has_irreversible=has_irreversible,
        rebase_required=rebase_required,
        rebase_reason=rebase_reason,
        issues=issues,
    )


async def execute_apply(
    db: AsyncSession,
    *,
    proposal_id: str,
    plan: ApplyPlan,
    tenant_id: int,
) -> dict:
    """执行 ops。Phase B v1 简化版：

    不真正调平台 API（避开 generation 流复杂度）；
    只把 draft promote 成新的 canonical Spec（kind='canonical'），
    然后 application.canonical_spec_id 指过去。

    Phase C/D 时把 step_executor 接进来真实部署到平台。
    """
    from datetime import datetime, timezone
    from app.models.spec import Spec as SpecORM

    proposal_row = (await db.execute(
        select(ChangeProposal).where(ChangeProposal.id == proposal_id)
    )).scalar_one()

    # apply_log 累计
    apply_log: list[dict] = []
    success = True
    failure_reason = None

    try:
        # 加载 draft
        draft = await load_spec(db, proposal_row.draft_spec_id, tenant_id=tenant_id)
        if not draft:
            raise RuntimeError("draft 不存在")

        # 把 draft kind 改成 canonical
        spec_row = (await db.execute(
            select(SpecORM).where(SpecORM.id == draft.id)
        )).scalar_one()
        spec_row.kind = "canonical"

        # application.canonical_spec_id 指过去
        app_row = (await db.execute(
            select(Application).where(Application.id == proposal_row.application_id)
        )).scalar_one()
        previous_canonical = app_row.canonical_spec_id
        app_row.canonical_spec_id = draft.id

        for op in plan.ops:
            apply_log.append({"op": op.kind, "target": op.target, "status": "noop_in_v1"})

        proposal_row.status = "applied"
        proposal_row.applied_at = datetime.now(timezone.utc).replace(tzinfo=None)
        proposal_row.apply_log = {"ops": apply_log, "previous_canonical": previous_canonical}
        await db.commit()

        # 同步到 git（如绑定）
        try:
            from app.git.sync import finalize_apply_to_git
            tag = await finalize_apply_to_git(db, proposal=proposal_row, application=app_row)
            if tag:
                proposal_row.apply_log = {**(proposal_row.apply_log or {}), "git_tag": tag}
                await db.commit()
        except Exception as ge:
            # git 失败不让 apply 失败 — 标 warning 即可（已经在平台 apply 了）
            apply_log.append({"git_finalize_failed": str(ge)})
            proposal_row.apply_log = {**(proposal_row.apply_log or {}), "git_finalize_failed": str(ge)}
            await db.commit()
    except Exception as e:
        success = False
        failure_reason = str(e)
        proposal_row.status = "apply_failed"
        proposal_row.apply_log = {"ops": apply_log, "error": failure_reason}
        await db.commit()

    return {"success": success, "failure_reason": failure_reason, "apply_log": apply_log}
