"""Spec CRUD + 版本操作 API。

端点（架构文档 § 4.5）：
- GET    /api/spec/{spec_id}                   获取完整 Spec envelope
- GET    /api/spec/{spec_id}/versions          获取版本历史
- POST   /api/spec/{spec_id}/confirm           确认 Spec → 触发 Phase SCAFFOLD/GENERATE
- POST   /api/spec/{spec_id}/refine            基于当前 draft 让 AI 再优化（stub → 走 brainstorm）
- POST   /api/spec/{spec_id}/rollback          回滚到某历史版本（生成新版本）

权限：
- 查询：本租户可见
- 修改：创建方或同租户管理员
（这里 MVP 只做租户隔离 + 创建人检查，不做细粒度 RBAC）
"""
from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models import agent_models
from app.models import Conversation
from app.orchestrator import coordinator as orchestrator
from app.orchestrator.phases import Phase
from app.services import brainstorm_session_service, spec_service
from app.services.brainstorm_session_service import BsStatus
from app.spec.validators import SpecValidationError

router = APIRouter(prefix="/spec", tags=["Spec"])


# ══════════════════════════════════════════════════════════════
# 响应模型
# ══════════════════════════════════════════════════════════════

class SpecSummary(BaseModel):
    """Spec 概要（列表视图用）"""
    spec_id: str
    scene_type: str
    code_name: str
    widget_code: Optional[str] = None
    version: int
    parent_version: Optional[int] = None
    confidence: float
    created_by: str
    created_at: str  # ISO


class SpecDetail(SpecSummary):
    """Spec 详情（含完整 envelope）"""
    envelope: dict[str, Any] = Field(..., description="完整 Spec envelope JSON")


def _row_to_summary(row: agent_models.Spec) -> SpecSummary:
    return SpecSummary(
        spec_id=row.id,
        scene_type=row.scene_type,
        code_name=row.code_name,
        widget_code=row.widget_code,
        version=row.version,
        parent_version=row.parent_version,
        confidence=row.confidence,
        created_by=row.created_by,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


def _row_to_detail(row: agent_models.Spec) -> SpecDetail:
    base = _row_to_summary(row)
    return SpecDetail(**base.model_dump(), envelope=row.content or {})


async def _load_spec_for_tenant(
    db: AsyncSession, spec_id: str, ctx: AuthContext
) -> agent_models.Spec:
    row = await spec_service.get_spec(db, spec_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"spec {spec_id} not found")

    # 通过 brainstorm_session 做租户隔离
    bs_row = await brainstorm_session_service.get_session(db, row.brainstorm_session_id)
    if not bs_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "brainstorm session missing")
    if bs_row.tenant_id != ctx.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch")
    return row


# ══════════════════════════════════════════════════════════════
# GET /spec/{id}
# ══════════════════════════════════════════════════════════════

@router.get("/{spec_id}", response_model=SpecDetail)
async def get_spec_api(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SpecDetail:
    row = await _load_spec_for_tenant(db, spec_id, ctx)
    return _row_to_detail(row)


# ══════════════════════════════════════════════════════════════
# GET /spec/{id}/versions
# ══════════════════════════════════════════════════════════════

@router.get("/{spec_id}/versions", response_model=list[SpecSummary])
async def list_spec_versions(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[SpecSummary]:
    row = await _load_spec_for_tenant(db, spec_id, ctx)
    versions = await spec_service.get_spec_versions(
        db,
        brainstorm_session_id=row.brainstorm_session_id,
        code_name=row.code_name,
    )
    return [_row_to_summary(v) for v in versions]


# ══════════════════════════════════════════════════════════════
# POST /spec/{id}/confirm
# ══════════════════════════════════════════════════════════════

class ConfirmResponse(BaseModel):
    spec_id: str
    brainstorm_session_id: str
    conversation_id: int
    phase_hint: str = Field(..., description="下一阶段建议：scaffold / generate / already_confirmed")


@router.post("/{spec_id}/confirm", response_model=ConfirmResponse)
async def confirm_spec(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfirmResponse:
    """用户确认 Spec → 把关联 brainstorm session 标记完成，记录 final_spec_id。

    返回 phase_hint 给前端或 orchestrator 决定下一步走 scaffold 还是 generate。
    实际触发 CodingAgent 由 Orchestrator（P2.4）负责。
    """
    row = await _load_spec_for_tenant(db, spec_id, ctx)

    bs_row = await brainstorm_session_service.get_session(db, row.brainstorm_session_id)
    assert bs_row is not None  # _load_spec_for_tenant 保证过

    phase_hint: str
    if bs_row.status == BsStatus.COMPLETED and bs_row.final_spec_id == spec_id:
        phase_hint = "already_confirmed"
    else:
        await brainstorm_session_service.mark_session_completed(
            db, session_id=row.brainstorm_session_id, final_spec_id=spec_id,
        )
        # 根据 conversation.workspace_id 判断是否需要先 scaffold
        conv = await db.get(Conversation, bs_row.conversation_id)
        need_scaffold = not bool(conv and conv.workspace_id)
        # 推进 phase：CONFIRM → SCAFFOLD 或 GENERATE
        try:
            await orchestrator.on_spec_confirmed(
                db,
                conversation_id=bs_row.conversation_id,
                spec_id=spec_id,
                need_scaffold=need_scaffold,
            )
        except Exception:
            # phase 非 CONFIRM（边缘情况，比如直接从 API 调）时忽略状态机错误，
            # 仍允许 session mark completed 成功
            pass
        phase_hint = "scaffold" if need_scaffold else "generate"

    await db.commit()

    return ConfirmResponse(
        spec_id=spec_id,
        brainstorm_session_id=row.brainstorm_session_id,
        conversation_id=bs_row.conversation_id,
        phase_hint=phase_hint,
    )


# ══════════════════════════════════════════════════════════════
# POST /spec/{id}/refine
# ══════════════════════════════════════════════════════════════

class RefineRequest(BaseModel):
    instruction: Optional[str] = Field(
        None, description="可选 — 用户对 refine 的额外指示（默认由 agent 自行优化）",
    )


class RefineResponse(BaseModel):
    brainstorm_session_id: str
    message: str


@router.post("/{spec_id}/refine", response_model=RefineResponse)
async def refine_spec(
    spec_id: str,
    payload: RefineRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RefineResponse:
    """基于当前 Spec 再跑一轮 BrainstormAgent 优化。

    MVP 行为：只把 brainstorm session 状态改回 active（如果已 completed），
    真实的再优化循环由 Orchestrator + BrainstormAgent 消费（P2.4）。
    这里只是提供状态切换入口。
    """
    row = await _load_spec_for_tenant(db, spec_id, ctx)
    bs_row = await brainstorm_session_service.get_session(db, row.brainstorm_session_id)
    assert bs_row is not None

    if bs_row.status in (BsStatus.ABORTED, BsStatus.FAILED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"session terminal ({bs_row.status})，不能 refine。建议新建 brainstorm。",
        )

    # 状态切到 active，清 final_spec_id（下一轮重新 emit）
    bs_row.status = BsStatus.ACTIVE
    bs_row.final_spec_id = None
    await db.flush()
    await db.commit()

    msg = "brainstorm session 已恢复 active，Orchestrator 将重新反问 / 优化并产出新版本 Spec。"
    if payload.instruction:
        msg += f" 用户指示：{payload.instruction[:200]}"

    return RefineResponse(
        brainstorm_session_id=row.brainstorm_session_id,
        message=msg,
    )


# ══════════════════════════════════════════════════════════════
# POST /spec/{id}/rollback
# ══════════════════════════════════════════════════════════════

class RollbackResponse(BaseModel):
    new_spec_id: str
    new_version: int
    parent_version: int
    message: str


@router.post("/{spec_id}/rollback", response_model=RollbackResponse)
async def rollback_spec(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RollbackResponse:
    """把指定历史版本克隆为新版本置于版本链顶端。"""
    row = await _load_spec_for_tenant(db, spec_id, ctx)

    try:
        new_row = await spec_service.rollback_to_version(db, spec_id=spec_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except SpecValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    await db.commit()

    return RollbackResponse(
        new_spec_id=new_row.id,
        new_version=new_row.version,
        parent_version=row.version,
        message=f"已回滚到 version {row.version} 的内容，新版本号 v{new_row.version}",
    )
