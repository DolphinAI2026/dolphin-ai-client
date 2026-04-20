"""智能开发流水线 v2 —— Spec 驱动的全新入口。

与老 `/api/coding/pipeline` 的区别：
- **老路径**：pipeline.py 内置 scene_detection + brainstorm proposal 文本协议（耦合重）
- **新路径**：Orchestrator + BrainstormAgent + CodingAgent + Spec 契约（职责分离）

设计：HTTP **只做路由决策**，agent 跑在后台 task。客户端通过
`GET /api/sse/conversation/{id}` 订阅事件流；本路由的 HTTP 响应只返 202 +
路由动作描述。这样满足长连接解耦（SSE）+ 原子请求（POST）分离原则。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.brainstorm import BrainstormAgent
from app.agents.coding.llm_config import load_coding_llm_config
from app.agents.db_publisher import get_db_publisher
from app.agents.db_trace_writer import get_db_trace_writer
from app.agents.iteration import (
    IterationLevel,
    classify_iteration,
)
from app.agents.types import AgentContext
from app.database import AsyncSessionLocal, get_db
from app.deps import AuthContext, get_auth_context
from app.llm_client import LLMClient
from app.models import Conversation
from app.orchestrator import (
    Phase,
    RouteDecision,
    driver,
    get_phase,
    route_user_message,
    start_brainstorm,
)
from app.services import brainstorm_session_service as bs_svc
from app.services import iteration_service, spec_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coding/v2", tags=["Coding v2"])


# ══════════════════════════════════════════════════════════════
# Request / Response 模型
# ══════════════════════════════════════════════════════════════

class MessageRequest(BaseModel):
    conversation_id: Optional[int] = None
    """空表示新建 conversation；非空表示在既有对话里继续"""

    message: str
    """用户消息文本"""

    selected_model: Optional[int] = None
    """llm_configs.id；不传走租户默认"""


class MessageResponse(BaseModel):
    conversation_id: int
    action: str
    phase: str
    session_id: Optional[str] = None
    reason: str
    """给前端的调试提示 —— 解释本请求为什么走这条路"""

    hint_subscribe_sse: str
    """前端应立即订阅的 SSE URL"""


# ══════════════════════════════════════════════════════════════
# 工具：准备 AgentContext
# ══════════════════════════════════════════════════════════════

async def _build_agent_context(
    db: AsyncSession,
    *,
    session_id: str,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    workspace_id: Optional[str] = None,
    selected_model_id: Optional[int] = None,
    input_data: Optional[dict[str, Any]] = None,
) -> AgentContext:
    """统一构造 AgentContext（publisher / trace_writer / llm_client）"""
    base_url, api_key, model = await load_coding_llm_config(
        tenant_id,
        str(selected_model_id) if selected_model_id else None,
    )
    llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)

    publisher = get_db_publisher().scoped(db)  # type: ignore[attr-defined]
    trace_writer = get_db_trace_writer().scoped(db)  # type: ignore[attr-defined]

    return AgentContext(
        session_id=session_id,
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model=model,
        workspace_id=workspace_id,
        input=input_data or {},
        publisher=publisher,
        trace_writer=trace_writer,
        llm_client=llm_client,
    )


# ══════════════════════════════════════════════════════════════
# POST /coding/v2/message
# ══════════════════════════════════════════════════════════════

@router.post("/message", response_model=MessageResponse)
async def send_message(
    payload: MessageRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """发送一条消息给智能开发流水线。

    行为：
    1. 定位/新建 conversation
    2. 存一条 agent_message(role=user)
    3. 根据 phase 决定启动哪个 agent
    4. 派个 background task 跑 agent；HTTP 立即返回 202 hint
    5. 前端通过 SSE 接收 agent 事件
    """
    if not payload.message.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "message 不能为空")

    # Step 1：定位 / 新建 conversation
    conv: Conversation
    if payload.conversation_id is None:
        conv = Conversation(
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            title=payload.message[:50],
            agent_type="coding",
            status="active",
            selected_llm_config_id=payload.selected_model,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)
    else:
        conv = await db.get(Conversation, payload.conversation_id)
        if not conv:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
        if conv.tenant_id != ctx.tenant_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch")

    # Step 2：路由决策
    decision: RouteDecision = await route_user_message(db, conversation_id=conv.id)

    # Step 3：调度后台任务
    if decision.action in {"reject_message"}:
        # 不处理（agent 正在跑），直接返回
        await db.commit()
        return _build_response(conv.id, decision)

    if decision.action == "start_brainstorm":
        bs_row = await start_brainstorm(
            db,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            model=str(conv.selected_llm_config_id or "default"),
        )
        decision = RouteDecision(
            action="start_brainstorm",
            phase=Phase.UNDERSTAND,
            session_id=bs_row.id,
            reason=decision.reason,
        )
        await db.commit()
        asyncio.create_task(_run_brainstorm_task(
            session_id=bs_row.id,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            workspace_id=conv.workspace_id,
            selected_model_id=payload.selected_model,
            user_message=payload.message,
        ))
        return _build_response(conv.id, decision)

    if decision.action == "continue_brainstorm" or decision.action == "resume_brainstorm":
        # 续跑 brainstorm（用户补充回答 / 连接恢复）
        await db.commit()
        asyncio.create_task(_resume_brainstorm_task(
            session_id=decision.session_id,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            workspace_id=conv.workspace_id,
            selected_model_id=payload.selected_model,
            user_message=payload.message,
        ))
        return _build_response(conv.id, decision)

    if decision.action == "refine_brainstorm":
        # CONFIRM 阶段收到文本：视为 refine 触发 → 回到 UNDERSTAND + 新 brainstorm session
        from app.orchestrator import transition_phase
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        bs_row = await start_brainstorm(
            db,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            model=str(conv.selected_llm_config_id or "default"),
        )
        await db.commit()
        asyncio.create_task(_run_brainstorm_task(
            session_id=bs_row.id,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            workspace_id=conv.workspace_id,
            selected_model_id=payload.selected_model,
            user_message=payload.message,
        ))
        decision = RouteDecision(
            action="refine_brainstorm",
            phase=Phase.UNDERSTAND,
            session_id=bs_row.id,
            reason=decision.reason,
        )
        return _build_response(conv.id, decision)

    if decision.action == "iterate":
        # DONE 后新消息 —— 先调独立轻量 LLM 做分级（架构文档 § 6.6）
        # 1. 找到本 conversation 最新的已确认 Spec
        bs_active = await bs_svc.get_active_session_for_conversation(db, conv.id)
        # 找不到 active 时退回最近 completed 的 session
        if not bs_active:
            # 用最新 final_spec_id：扫 brainstorm_sessions 按 ended_at desc 取第一个有 final_spec_id 的
            from sqlalchemy import desc as _desc, select as _select
            stmt = (
                _select(bs_svc.agent_models.BrainstormSession)
                .where(
                    bs_svc.agent_models.BrainstormSession.conversation_id == conv.id,
                    bs_svc.agent_models.BrainstormSession.final_spec_id.isnot(None),
                )
                .order_by(_desc(bs_svc.agent_models.BrainstormSession.ended_at))
                .limit(1)
            )
            bs_active = (await db.execute(stmt)).scalar_one_or_none()

        base_spec_row = None
        if bs_active and bs_active.final_spec_id:
            base_spec_row = await spec_service.get_spec(db, bs_active.final_spec_id)

        classification = None
        if base_spec_row:
            # 启动后台 task 做 classify + dispatch（LLM 调用可能耗时）
            await db.commit()
            asyncio.create_task(_run_iterate_dispatch_task(
                conversation_id=conv.id,
                user_id=ctx.user.id,
                tenant_id=ctx.tenant_id,
                workspace_id=conv.workspace_id,
                selected_model_id=payload.selected_model,
                user_message=payload.message,
                base_spec_id=base_spec_row.id,
            ))
            decision = RouteDecision(
                action="iterate",
                phase=Phase.UNDERSTAND,  # 临时标记，真正 phase 由 dispatch 决定
                session_id=None,
                reason=(
                    "DONE 状态收到新消息，异步分级中（trivial 直接产 SpecPatch；"
                    "minor 起 brainstorm 反问 1 轮；major 起完整 brainstorm；"
                    "cross_scene 警告用户新建工作区）"
                ),
            )
            return _build_response(conv.id, decision)

        # 找不到 base spec —— 降级为完整 brainstorm
        logger.warning("iterate 找不到 base spec，conversation=%s，退回 brainstorm", conv.id)
        from app.orchestrator import transition_phase
        await transition_phase(db, conversation_id=conv.id, to=Phase.UNDERSTAND)
        bs_row = await start_brainstorm(
            db,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            model=str(conv.selected_llm_config_id or "default"),
            trigger_type=bs_svc.BsTrigger.ITERATE_MAJOR,
        )
        await db.commit()
        asyncio.create_task(_run_brainstorm_task(
            session_id=bs_row.id,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            workspace_id=conv.workspace_id,
            selected_model_id=payload.selected_model,
            user_message=payload.message,
        ))
        decision = RouteDecision(
            action="iterate",
            phase=Phase.UNDERSTAND,
            session_id=bs_row.id,
            reason="iterate 找不到 base spec，退回完整 brainstorm",
        )
        return _build_response(conv.id, decision)

    if decision.action == "restart":
        # FAILED / ABORTED 下用户发消息 = 重启
        from app.orchestrator import reset_phase
        await reset_phase(db, conv.id)
        await db.commit()
        # 再次路由，这次会 start_brainstorm
        decision2 = await route_user_message(db, conversation_id=conv.id)
        # 递归式地当成新请求处理不太好，简化：直接起一个 brainstorm
        bs_row = await start_brainstorm(
            db,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            model=str(conv.selected_llm_config_id or "default"),
        )
        await db.commit()
        asyncio.create_task(_run_brainstorm_task(
            session_id=bs_row.id,
            conversation_id=conv.id,
            user_id=ctx.user.id,
            tenant_id=ctx.tenant_id,
            workspace_id=conv.workspace_id,
            selected_model_id=payload.selected_model,
            user_message=payload.message,
        ))
        decision = RouteDecision(
            action="restart",
            phase=Phase.UNDERSTAND,
            session_id=bs_row.id,
            reason="由失败/取消状态重启 brainstorm",
        )
        return _build_response(conv.id, decision)

    # 兜底：返回 routing 结果但不做任何调度
    await db.commit()
    return _build_response(conv.id, decision)


def _build_response(conversation_id: int, decision: RouteDecision) -> MessageResponse:
    return MessageResponse(
        conversation_id=conversation_id,
        action=decision.action,
        phase=decision.phase.value,
        session_id=decision.session_id,
        reason=decision.reason,
        hint_subscribe_sse=f"/api/sse/conversation/{conversation_id}",
    )


# ══════════════════════════════════════════════════════════════
# 后台任务
# ══════════════════════════════════════════════════════════════

async def _run_brainstorm_task(
    *,
    session_id: str,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    workspace_id: Optional[str],
    selected_model_id: Optional[int],
    user_message: str,
) -> None:
    """后台跑 BrainstormAgent。独立 DB session，事件通过 publisher 推 SSE。"""
    async with AsyncSessionLocal() as task_db:
        try:
            agent_ctx = await _build_agent_context(
                task_db,
                session_id=session_id,
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                selected_model_id=selected_model_id,
                input_data={"requirement": user_message},
            )
            agent = BrainstormAgent(agent_ctx)
            await driver.drive_brainstorm(task_db, agent=agent, session_id=session_id)
        except Exception as e:
            logger.exception("brainstorm task %s crashed: %s", session_id, e)


async def _resume_brainstorm_task(
    *,
    session_id: str,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    workspace_id: Optional[str],
    selected_model_id: Optional[int],
    user_message: str,
) -> None:
    """从 DB snapshot resume BrainstormAgent，把用户新消息作为额外输入注入。"""
    async with AsyncSessionLocal() as task_db:
        try:
            agent_ctx = await _build_agent_context(
                task_db,
                session_id=session_id,
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                selected_model_id=selected_model_id,
                input_data={
                    "requirement": user_message,
                    # 注入 ask_user 的答案（供 tool 同步模式读取）
                    "_ask_user_answer": {"answer": user_message, "question_matches": True},
                },
            )
            _, agent = await bs_svc.resume_session(
                task_db, session_id=session_id, ctx=agent_ctx,
            )
            await driver.drive_brainstorm(task_db, agent=agent, session_id=session_id)
        except Exception as e:
            logger.exception("brainstorm resume task %s crashed: %s", session_id, e)


# ══════════════════════════════════════════════════════════════
# POST /coding/v2/spec/{spec_id}/start-coding
# ══════════════════════════════════════════════════════════════

class StartCodingResponse(BaseModel):
    conversation_id: int
    spec_id: str
    phase: str


@router.post("/spec/{spec_id}/start-coding", response_model=StartCodingResponse)
async def start_coding_from_spec(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StartCodingResponse:
    """用户在 CONFIRM 阶段点"确认生成代码"后调用（/api/spec/{id}/confirm 之后）。

    本接口不做 phase 二次推进（confirm 已经把 phase 推到 SCAFFOLD/GENERATE），
    只是把 CodingAgent 在后台跑起来。
    """
    from app.services import spec_service

    spec_row = await spec_service.get_spec(db, spec_id)
    if not spec_row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"spec {spec_id} not found")

    bs_row = await bs_svc.get_session(db, spec_row.brainstorm_session_id)
    if not bs_row or bs_row.tenant_id != ctx.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch")

    conv = await db.get(Conversation, bs_row.conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation missing")
    phase = await get_phase(db, conv.id)

    # 快照 envelope 到任务变量（避免 session 关闭后访问 spec_row.content）
    envelope = dict(spec_row.content or {})
    await db.commit()

    asyncio.create_task(_run_coding_task(
        conversation_id=conv.id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        workspace_id=conv.workspace_id,
        spec_envelope=envelope,
    ))

    return StartCodingResponse(
        conversation_id=conv.id,
        spec_id=spec_id,
        phase=phase.value,
    )


async def _run_iterate_dispatch_task(
    *,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    workspace_id: Optional[str],
    selected_model_id: Optional[int],
    user_message: str,
    base_spec_id: str,
) -> None:
    """DONE 后的新消息：先 classify，然后按级别分派。

    - trivial：apply patch → 新版 Spec → drive_coding
    - minor：起 brainstorm（反问聚焦细节）
    - major：起完整 brainstorm
    - cross_scene：发事件提醒用户新建工作区
    """
    from app.orchestrator import coordinator as orch_coord

    async with AsyncSessionLocal() as task_db:
        # 构造 LLMClient
        base_url, api_key, model = await load_coding_llm_config(
            tenant_id,
            str(selected_model_id) if selected_model_id else None,
        )
        llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)
        publisher = get_db_publisher().scoped(task_db)  # type: ignore[attr-defined]

        # 加载 base Spec
        base_spec = await spec_service.get_spec(task_db, base_spec_id)
        if not base_spec:
            logger.error("iterate dispatch: base spec %s 不存在", base_spec_id)
            return

        # classify
        try:
            classification = await classify_iteration(
                user_message=user_message,
                spec_envelope=base_spec.content or {},
                llm_client=llm_client,
            )
        except Exception as e:
            logger.exception("classify_iteration crashed: %s", e)
            return

        # 发事件给前端
        try:
            await publisher.publish(
                conversation_id=conversation_id,
                event_type="iteration.classified",
                agent="orchestrator",
                session_id=None,
                data={
                    "level": classification.level.value,
                    "rationale": classification.rationale,
                    "confidence": classification.confidence,
                    "has_patch": classification.patch is not None,
                },
            )
        except Exception as e:
            logger.warning("publish iteration.classified failed: %s", e)

        # 分派
        if classification.level == IterationLevel.CROSS_SCENE:
            try:
                await publisher.publish(
                    conversation_id=conversation_id,
                    event_type="iteration.cross_scene_warning",
                    agent="orchestrator",
                    session_id=None,
                    data={
                        "message": (
                            "你的修改跨场景了，当前工作区类型与新需求不匹配。"
                            "建议新建工作区，或明确缩小修改范围再重试。"
                        ),
                        "rationale": classification.rationale,
                    },
                )
            except Exception as e:
                logger.warning("publish cross_scene_warning failed: %s", e)
            return  # phase 保持 DONE，等用户操作

        if classification.level == IterationLevel.TRIVIAL and classification.patch is not None:
            # 快通道：直接 apply patch 产新 spec → coding
            try:
                new_spec = await iteration_service.apply_patch_as_new_spec(
                    task_db, base_spec_id=base_spec_id, patch=classification.patch,
                )
                await task_db.commit()
            except Exception as e:
                logger.exception("iterate trivial patch apply failed: %s", e)
                try:
                    await publisher.publish(
                        conversation_id=conversation_id,
                        event_type="iteration.patch_failed",
                        agent="orchestrator",
                        session_id=None,
                        data={"error": str(e), "falling_back": "minor"},
                    )
                except Exception:
                    pass
                # 降级：走 brainstorm minor
                await _start_brainstorm_for_iterate(
                    task_db,
                    conversation_id=conversation_id, user_id=user_id, tenant_id=tenant_id,
                    workspace_id=workspace_id, selected_model_id=selected_model_id,
                    user_message=user_message, trigger=bs_svc.BsTrigger.ITERATE_MINOR,
                )
                return

            # phase: DONE → UNDERSTAND → CONFIRM → GENERATE（用 reset + transitions）
            await orch_coord.reset_phase(task_db, conversation_id)
            await orch_coord.transition_phase(task_db, conversation_id=conversation_id, to=Phase.UNDERSTAND)
            await orch_coord.transition_phase(task_db, conversation_id=conversation_id, to=Phase.CONFIRM)
            await orch_coord.transition_phase(task_db, conversation_id=conversation_id, to=Phase.GENERATE)
            await task_db.commit()

            # 异步启动 coding
            try:
                await publisher.publish(
                    conversation_id=conversation_id,
                    event_type="iteration.trivial_patched",
                    agent="orchestrator",
                    session_id=None,
                    data={
                        "new_spec_id": new_spec.id,
                        "new_version": new_spec.version,
                        "patch_ops_count": len(classification.patch.operations),
                    },
                )
            except Exception:
                pass

            await _run_coding_task(
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                spec_envelope=new_spec.content or {},
            )
            return

        # MINOR / MAJOR：起 brainstorm
        trigger = (
            bs_svc.BsTrigger.ITERATE_MINOR
            if classification.level == IterationLevel.MINOR
            else bs_svc.BsTrigger.ITERATE_MAJOR
        )
        await _start_brainstorm_for_iterate(
            task_db,
            conversation_id=conversation_id, user_id=user_id, tenant_id=tenant_id,
            workspace_id=workspace_id, selected_model_id=selected_model_id,
            user_message=user_message, trigger=trigger,
        )


async def _start_brainstorm_for_iterate(
    task_db: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    workspace_id: Optional[str],
    selected_model_id: Optional[int],
    user_message: str,
    trigger: str,
) -> None:
    """iterate 场景下开新 brainstorm session 的通用路径"""
    from app.orchestrator import transition_phase as _transition

    await _transition(task_db, conversation_id=conversation_id, to=Phase.UNDERSTAND)
    bs_row = await start_brainstorm(
        task_db,
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        model=str(selected_model_id) if selected_model_id else "default",
        trigger_type=trigger,
    )
    await task_db.commit()
    await _run_brainstorm_task(
        session_id=bs_row.id,
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        selected_model_id=selected_model_id,
        user_message=user_message,
    )


async def _run_coding_task(
    *,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    workspace_id: Optional[str],
    spec_envelope: dict[str, Any],
) -> None:
    """后台跑 CodingAgent，消费 Spec"""
    import secrets

    session_id = f"c_{secrets.token_hex(6)}"
    async with AsyncSessionLocal() as task_db:
        try:
            agent_ctx = await _build_agent_context(
                task_db,
                session_id=session_id,
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                input_data={},
            )
            await driver.drive_coding_from_spec(
                task_db, spec_envelope=spec_envelope, ctx=agent_ctx,
            )
        except Exception as e:
            logger.exception("coding task %s crashed: %s", session_id, e)
