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
import secrets
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.brainstorm import BrainstormAgent
from app.agents.coding.llm_config import load_coding_llm_config
from app.agents.coding.spec_bridge import render_spec_brief
from app.agents.db_publisher import get_db_publisher
from app.agents.db_trace_writer import get_db_trace_writer
from app.agents.iteration import (
    IterationLevel,
    classify_iteration,
)
from app.agents.iteration.spec_patch import PatchOp
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
    on_scaffold_done,
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
    # load_coding_llm_config 只认 "llmcfg:<id>" 前缀为"按 id 挑 config"，
    # 否则会把裸字符串当成 model 名 override（结果是退回租户默认，用户选择被忽略）。
    base_url, api_key, model = await load_coding_llm_config(
        tenant_id,
        f"llmcfg:{selected_model_id}" if selected_model_id else None,
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

    # Step 1.5：把用户这条消息作为事件写入 conversation_events，
    # 让 SSE 重连/重载时能按序回放（前端气泡就能重建）
    try:
        await get_db_publisher().scoped(db).publish(  # type: ignore[attr-defined]
            conversation_id=conv.id,
            event_type="conversation.user_message",
            agent="user",
            session_id=None,
            data={"text": payload.message},
        )
        await db.commit()
    except Exception as e:
        logger.warning("publish conversation.user_message failed (non-fatal): %s", e)

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
        # CONFIRM 阶段收到文本：用户在纠正/补充**已展示但尚未确认**的 Spec。
        #
        # 关键改造（2026-04-23）：旧逻辑"回 UNDERSTAND + 起全新 brainstorm session"
        # 把用户的纠正当全新需求喂给 BrainstormAgent，LLM 看不到旧 Spec，
        # 会把"附件 formValue 是对象数组"误判成"用户想做一个附件上传组件"
        # → 重开 scene 检测、重问场景。
        #
        # 现在改成走 iterate 分发（with from_confirm_phase=True）：
        # - trivial：LLM 基于旧 Spec 生成 SpecPatch，apply 出新 Spec 后**停在 CONFIRM**
        #   让用户看到更新后的 Spec 再点确认（不自动跑 coding）
        # - minor：起 brainstorm 但 trigger=ITERATE_MINOR（保留旧 Spec 上下文）
        # - major：起 brainstorm 但 trigger=ITERATE_MAJOR
        # - cross_scene：警告用户
        bs_active = await bs_svc.get_active_session_for_conversation(db, conv.id)
        if not bs_active:
            # CONFIRM 阶段一般 bs_active 还在，但保险起见扫已完成的会话
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

        # 找 base Spec 的两级 fallback：
        #   1) bs_active.final_spec_id —— 只在用户点过"确认生成"之后才会写（见
        #      driver.confirm_spec_and_prepare_coding → mark_session_completed）
        #   2) 但 CONFIRM 阶段 Spec 已展示、用户**未点确认**时 session 还是 ACTIVE，
        #      final_spec_id 是 None。此时直接按 session_id 反查 spec 表里最新那条。
        base_spec_row = None
        if bs_active and bs_active.final_spec_id:
            base_spec_row = await spec_service.get_spec(db, bs_active.final_spec_id)
        if not base_spec_row and bs_active:
            base_spec_row = await spec_service.get_latest_spec_for_session(db, bs_active.id)

        if base_spec_row:
            # 走 iterate 分发，带 from_confirm_phase=True
            await db.commit()
            asyncio.create_task(_run_iterate_dispatch_task(
                conversation_id=conv.id,
                user_id=ctx.user.id,
                tenant_id=ctx.tenant_id,
                workspace_id=conv.workspace_id,
                selected_model_id=payload.selected_model,
                user_message=payload.message,
                base_spec_id=base_spec_row.id,
                from_confirm_phase=True,
            ))
            decision = RouteDecision(
                action="refine_brainstorm",
                phase=Phase.CONFIRM,
                session_id=None,
                reason=(
                    "CONFIRM 阶段收到纠正消息，走 iterate 分级（trivial 直接打 patch 停在 CONFIRM；"
                    "minor/major 起 brainstorm 带旧 Spec 上下文）"
                ),
            )
            return _build_response(conv.id, decision)

        # 两级 fallback 都找不到 base_spec —— 降级到老的"重启 brainstorm"行为（理论上不该发生）
        logger.warning(
            "refine_brainstorm: 找不到 base_spec，conversation=%s，降级到全新 brainstorm",
            conv.id,
        )
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
    base_spec_brief: Optional[str] = None,
    allowed_paths: Optional[list[str]] = None,
) -> None:
    """后台跑 BrainstormAgent。独立 DB session，事件通过 publisher 推 SSE。

    commit 策略：task 结束时统一 commit；driver 层只 flush 不 commit，
    避免 task 内部复杂路径下多次 commit。publisher 的事件行是独立 session
    自我 commit（不受此影响）。

    Args:
        base_spec_brief: 非空 = iterate 场景，塞进 ctx.input 让 BrainstormAgent
            在 user message 里看到上一版 Spec 摘要，把 user_message 当作对 base_spec
            的纠正而不是新需求；同时切换 system prompt 到 iterate 模式。
        allowed_paths: 非空 = scope 约束，灌进 BrainstormState.allowed_paths，
            ask_user tool 校验 target_path 必须落在内（防越界重问已确定字段）。
    """
    async with AsyncSessionLocal() as task_db:
        try:
            input_data: dict[str, Any] = {"requirement": user_message}
            if base_spec_brief:
                input_data["base_spec_brief"] = base_spec_brief
                input_data["is_iteration"] = True
            if allowed_paths:
                input_data["allowed_paths"] = list(allowed_paths)
            agent_ctx = await _build_agent_context(
                task_db,
                session_id=session_id,
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                selected_model_id=selected_model_id,
                input_data=input_data,
            )
            agent = BrainstormAgent(agent_ctx)
            await driver.drive_brainstorm(task_db, agent=agent, session_id=session_id)
            await task_db.commit()
        except Exception as e:
            logger.exception("brainstorm task %s crashed: %s", session_id, e)
            try:
                await task_db.rollback()
            except Exception:
                pass


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
    """从 DB snapshot resume BrainstormAgent。

    关键：resume_session 会把 `user_message` 作为上一轮 ask_user 的 tool_result
    追加进 agent._messages，LLM 看到的是真正的对话历史 + 用户最新回答，
    而不是从头重跑（见架构文档 § 5.5）。
    """
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
                # input 保留 requirement 供 build_initial_user_message 兜底，
                # 但 resume 场景下 run() 不会调 build_initial_user_message
                input_data={"requirement": user_message},
            )
            _, agent = await bs_svc.resume_session(
                task_db,
                session_id=session_id,
                ctx=agent_ctx,
                user_answer=user_message,
            )
            await driver.drive_brainstorm(task_db, agent=agent, session_id=session_id)
            await task_db.commit()
        except Exception as e:
            logger.exception("brainstorm resume task %s crashed: %s", session_id, e)
            try:
                await task_db.rollback()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
# POST /coding/v2/spec/{spec_id}/start-coding
# ══════════════════════════════════════════════════════════════

class StartCodingResponse(BaseModel):
    conversation_id: int
    spec_id: str
    phase: str


class ConversationWorkspaceResponse(BaseModel):
    conversation_id: int
    workspace_id: Optional[str]


@router.get("/conversations/{conversation_id}/workspace", response_model=ConversationWorkspaceResponse)
async def get_conversation_workspace(
    conversation_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationWorkspaceResponse:
    """获取对话关联的 workspace_id（用于打开 IDE 等场景）。"""
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    if conv.tenant_id != ctx.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch")
    return ConversationWorkspaceResponse(
        conversation_id=conv.id,
        workspace_id=conv.workspace_id,
    )


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

    # 快照 envelope + workspace_id 到任务变量（避免 session 关闭后访问懒加载属性）
    envelope = dict(spec_row.content or {})
    # 确保 spec_id 字段存在（save_spec 写入的，但旧数据或异常路径可能缺失）
    if not envelope.get("spec_id"):
        envelope["spec_id"] = spec_row.id
    workspace_id = conv.workspace_id
    conversation_id = conv.id
    user_id = ctx.user.id
    tenant_id = ctx.tenant_id
    await db.commit()

    if phase == Phase.SCAFFOLD:
        # 首轮：工作区尚未创建，先 scaffold 再 coding
        asyncio.create_task(_run_scaffold_then_coding_task(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            spec_envelope=envelope,
        ))
    else:
        # 迭代：工作区已存在，直接 coding
        asyncio.create_task(_run_coding_task(
            conversation_id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            spec_envelope=envelope,
        ))

    return StartCodingResponse(
        conversation_id=conversation_id,
        spec_id=spec_id,
        phase=phase.value,
    )


def _spec_scene_to_project_type(scene_type: str) -> str:
    """Spec scene_type 字符串 → WorkspaceManager ProjectType 字符串"""
    return {
        "web_component_dual": "form-component-dual",
        "web_page": "form-page",
        "mobile_page": "mobile-page",
        "backend_api": "backend-api",
        "backend_feign": "backend-feign",
        "backend_scheduled": "backend-scheduled",
    }.get(scene_type, "form-component-dual")


async def _run_scaffold_then_coding_task(
    *,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    spec_envelope: dict[Any, Any],
) -> None:
    """后台任务：创建工作区（SCAFFOLD）→ 推进 phase GENERATE → 跑 CodingAgent。

    WorkspaceManager.create_workspace() 是同步 IO 密集型操作（拷贝模板），
    用 asyncio.to_thread 避免阻塞事件循环。
    """
    from app.coding.workspace import WorkspaceManager, ProjectType

    scene_type_str = spec_envelope.get("scene_type", "web_component_dual")
    project_type_str = _spec_scene_to_project_type(scene_type_str)
    identity = spec_envelope.get("identity") or {}
    code_name: str = identity.get("code_name") or "custom-dev"
    display_name: str = identity.get("display_name") or code_name

    async with AsyncSessionLocal() as task_db:
        async with AsyncSessionLocal() as pub_db:
            publisher = get_db_publisher().scoped(pub_db)  # type: ignore[attr-defined]
            try:
                # 发 scaffold 开始事件
                await publisher.publish(
                    conversation_id=conversation_id,
                    event_type="scaffold.started",
                    agent="orchestrator",
                    session_id=None,
                    data={
                        "scene_type": scene_type_str,
                        "project_type": project_type_str,
                        "code_name": code_name,
                    },
                )

                # 同步创建工作区，在线程池里跑（避免阻塞 event loop）
                ws_mgr = WorkspaceManager()
                try:
                    meta = await asyncio.to_thread(
                        ws_mgr.create_workspace,
                        ProjectType(project_type_str),
                        code_name,
                        user_id,
                        None,           # project_id
                        display_name,   # display_name
                    )
                except Exception as e:
                    logger.exception("scaffold: create_workspace 失败: %s", e)
                    await publisher.publish(
                        conversation_id=conversation_id,
                        event_type="scaffold.failed",
                        agent="orchestrator",
                        session_id=None,
                        data={"error": str(e)},
                    )
                    # phase → FAILED
                    from app.orchestrator import on_agent_failed
                    await on_agent_failed(task_db, conversation_id=conversation_id, error_message=str(e))
                    await task_db.commit()
                    return

                workspace_id: str = meta["id"]

                # 把 workspace_id 关联到 conversation
                conv = await task_db.get(Conversation, conversation_id)
                if conv:
                    conv.workspace_id = workspace_id
                    await task_db.flush()

                # phase: SCAFFOLD → GENERATE
                await on_scaffold_done(task_db, conversation_id=conversation_id)
                await task_db.commit()

                # 发 scaffold 完成事件
                await publisher.publish(
                    conversation_id=conversation_id,
                    event_type="scaffold.done",
                    agent="orchestrator",
                    session_id=None,
                    data={
                        "workspace_id": workspace_id,
                        "project_name": meta.get("project_name", code_name),
                        "display_name": meta.get("display_name", display_name),
                    },
                )

            except Exception as e:
                logger.exception("scaffold task crashed (conv=%s): %s", conversation_id, e)
                try:
                    await task_db.rollback()
                except Exception:
                    pass
                return

    # scaffold 成功后，用新 workspace_id 跑 coding
    await _run_coding_task(
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        spec_envelope=spec_envelope,
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
    from_confirm_phase: bool = False,
) -> None:
    """对既有 Spec 的精化 / 迭代：先 classify，然后按级别分派。

    两个调用入口：
    1. **DONE 后的新消息**（`from_confirm_phase=False`，默认）：组件开发已完成，
       用户追加新需求。trivial 直接 apply patch 后**自动继续 coding** 改代码。
    2. **CONFIRM 阶段的纠正**（`from_confirm_phase=True`）：Spec 已展示但还没确认，
       用户纠正 AI 假设或补充信息。trivial apply patch 后**停在 CONFIRM**
       让用户看到更新后的 Spec 再决定是否确认 → **不** 自动跑 coding。

    级别动作：
    - trivial：apply patch → 新版 Spec → （if from_confirm_phase 停在 CONFIRM；
      否则 drive_coding）
    - minor：起 brainstorm（反问聚焦细节，trigger = ITERATE_MINOR）
    - major：起完整 brainstorm（trigger = ITERATE_MAJOR）
    - cross_scene：发事件提醒用户新建工作区
    """
    from app.orchestrator import coordinator as orch_coord

    async with AsyncSessionLocal() as task_db:
        # 构造 LLMClient（参数格式必须是 "llmcfg:<id>"，见 _build_agent_context 注释）
        base_url, api_key, model = await load_coding_llm_config(
            tenant_id,
            f"llmcfg:{selected_model_id}" if selected_model_id else None,
        )
        llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)
        publisher = get_db_publisher().scoped(task_db)  # type: ignore[attr-defined]

        # 加载 base Spec
        base_spec = await spec_service.get_spec(task_db, base_spec_id)
        if not base_spec:
            logger.error("iterate dispatch: base spec %s 不存在", base_spec_id)
            try:
                await publisher.publish(
                    conversation_id=conversation_id,
                    event_type="iteration.failed",
                    agent="orchestrator",
                    session_id=None,
                    data={"error": f"spec {base_spec_id} not found"},
                )
            except Exception:
                pass
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
            try:
                await publisher.publish(
                    conversation_id=conversation_id,
                    event_type="iteration.failed",
                    agent="orchestrator",
                    session_id=None,
                    data={"error": f"classify failed: {e}"},
                )
            except Exception:
                pass
            return

        # 发事件给前端（带 RefineIntent 关键字段，便于审计）
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
                    "target_paths": list(classification.target_paths),
                    "derived_paths": list(classification.derived_paths),
                    "ambiguities_count": len(classification.ambiguities),
                },
            )
        except Exception as e:
            logger.warning("publish iteration.classified failed: %s", e)

        # ── Refine Strategy Router（4 类策略）──
        #
        # 1. CROSS_SCENE → Reject（跨场景，不动）
        # 2. classification.patch 存在 → Patch + (Open Questions if ambiguities)
        #    适用 trivial 全部场景，以及 minor/major 中 LLM 给了 patch 的场景
        # 3. 没 patch + target_paths 非空 → Constrained Brainstorm（带 allowed_paths）
        # 4. 没 patch + 没 target_paths → Fallback Brainstorm（兜底，不带 allowed_paths）

        # ── 路由 1：CROSS_SCENE ──
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
            return

        # ── 路由 2：Patch + Open Questions ──
        if classification.patch is not None:
            await _route_patch_with_ambiguities(
                task_db=task_db,
                publisher=publisher,
                base_spec=base_spec,
                base_spec_id=base_spec_id,
                classification=classification,
                conversation_id=conversation_id,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                selected_model_id=selected_model_id,
                user_message=user_message,
                from_confirm_phase=from_confirm_phase,
            )
            return

        # ── 路由 3 / 4：Constrained / Fallback Brainstorm ──
        # 没 patch 但有 target_paths → 起 brainstorm 但**作用域硬约束**在 allowed_paths
        # 既没 patch 也没 target_paths → 兜底 brainstorm（罕见，相当于让 LLM 重新展开聊）
        trigger = (
            bs_svc.BsTrigger.ITERATE_MINOR
            if classification.level == IterationLevel.MINOR
            else bs_svc.BsTrigger.ITERATE_MAJOR
        )
        allowed_paths = classification.allowed_paths
        if allowed_paths:
            logger.info(
                "iterate dispatch → Constrained Brainstorm (level=%s, allowed_paths=%s)",
                classification.level.value, allowed_paths,
            )
        else:
            logger.warning(
                "iterate dispatch → Fallback Brainstorm (level=%s, no target_paths from classifier)",
                classification.level.value,
            )
        await _start_brainstorm_for_iterate(
            task_db,
            conversation_id=conversation_id, user_id=user_id, tenant_id=tenant_id,
            workspace_id=workspace_id, selected_model_id=selected_model_id,
            user_message=user_message, trigger=trigger,
            base_spec_brief=_safe_render_spec_brief(base_spec.content or {}),
            allowed_paths=allowed_paths,  # 空列表表示无约束
        )


async def _route_patch_with_ambiguities(
    *,
    task_db,
    publisher,
    base_spec,
    base_spec_id: str,
    classification,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    workspace_id: Optional[str],
    selected_model_id: Optional[int],
    user_message: str,
    from_confirm_phase: bool,
) -> None:
    """路由 2：Patch + Open Questions。

    LLM 已经构造了 SpecPatch，意味着主要变更可以机械应用。
    如果同时有 ambiguities（用户没说清楚的次要字段），把它们转成 open_questions
    追加到新 envelope —— 用户在新 Spec 卡上能看到"AI 用了哪些默认假设"，
    可以再下一轮 refine 修正。
    """
    from app.orchestrator import coordinator as orch_coord

    # 构造扩展 patch：原 ops + 把 ambiguities 转为 add open_questions 的 ops
    patch = classification.patch
    extra_ops: list[PatchOp] = []
    for amb in classification.ambiguities:
        assumed = amb.default if amb.default is not None else "(未指定，请用户在下一版确认)"
        extra_ops.append(PatchOp(
            op="add",
            path="provenance.open_questions",
            value={
                "question": amb.question,
                "assumed_answer": str(assumed),
            },
        ))
    if extra_ops:
        patch.operations.extend(extra_ops)

    try:
        new_spec = await iteration_service.apply_patch_as_new_spec(
            task_db, base_spec_id=base_spec_id, patch=patch,
        )
        await task_db.commit()
    except Exception as e:
        logger.exception("iterate patch apply failed: %s", e)
        try:
            await publisher.publish(
                conversation_id=conversation_id,
                event_type="iteration.patch_failed",
                agent="orchestrator",
                session_id=None,
                data={"error": str(e), "falling_back": "constrained_brainstorm"},
            )
        except Exception:
            pass
        # patch apply 失败 → 降级为 Constrained Brainstorm（带 allowed_paths）
        await _start_brainstorm_for_iterate(
            task_db,
            conversation_id=conversation_id, user_id=user_id, tenant_id=tenant_id,
            workspace_id=workspace_id, selected_model_id=selected_model_id,
            user_message=user_message, trigger=bs_svc.BsTrigger.ITERATE_MINOR,
            base_spec_brief=_safe_render_spec_brief(base_spec.content or {}),
            allowed_paths=classification.allowed_paths,
        )
        return

    # phase 流转：
    #   - CONFIRM 阶段 refine（from_confirm_phase=True）→ 停 CONFIRM 等用户再确认
    #   - DONE 阶段 iterate（from_confirm_phase=False）→ 自动 GENERATE 跑 coding
    if from_confirm_phase:
        await orch_coord.reset_phase(task_db, conversation_id)
        await orch_coord.transition_phase(task_db, conversation_id=conversation_id, to=Phase.UNDERSTAND)
        await orch_coord.transition_phase(task_db, conversation_id=conversation_id, to=Phase.CONFIRM)
        await task_db.commit()
    else:
        await orch_coord.reset_phase(task_db, conversation_id)
        await orch_coord.transition_phase(task_db, conversation_id=conversation_id, to=Phase.UNDERSTAND)
        await orch_coord.transition_phase(task_db, conversation_id=conversation_id, to=Phase.CONFIRM)
        await orch_coord.transition_phase(task_db, conversation_id=conversation_id, to=Phase.GENERATE)
        await task_db.commit()

    # 发 trivial_patched 事件 — 前端 push 新版 Spec 卡
    try:
        await publisher.publish(
            conversation_id=conversation_id,
            event_type="iteration.trivial_patched",
            agent="orchestrator",
            session_id=None,
            data={
                "new_spec_id": new_spec.id,
                "new_version": new_spec.version,
                "parent_version": base_spec.version,
                "patch_ops_count": len(patch.operations),
                "ambiguities_resolved_as_open_questions": len(extra_ops),
                "rationale": classification.rationale,
                "stay_in_confirm": from_confirm_phase,
            },
        )
    except Exception:
        pass

    if from_confirm_phase:
        return

    # DONE 路径：自动跑 coding
    new_spec_envelope = dict(new_spec.content or {})
    if not new_spec_envelope.get("spec_id"):
        new_spec_envelope["spec_id"] = new_spec.id
    await _run_coding_task(
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        spec_envelope=new_spec_envelope,
    )


def _safe_render_spec_brief(envelope: dict[str, Any]) -> Optional[str]:
    """把 Spec envelope 渲染成 markdown brief；渲染异常时返回 None。

    brainstorm iterate 路径用，失败时退回"无 brief"行为，保证迭代任务不被渲染
    错误阻断。调用 spec_bridge.render_spec_brief（coding agent 也用同一个）。
    """
    if not envelope:
        return None
    try:
        text = render_spec_brief(envelope)
        return text.strip() or None
    except Exception as e:
        logger.warning("render_spec_brief failed: %s", e)
        return None


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
    base_spec_brief: Optional[str] = None,
    allowed_paths: Optional[list[str]] = None,
) -> None:
    """iterate 场景下开新 brainstorm session 的通用路径

    Args:
        base_spec_brief: 上一版 Spec 摘要，让 LLM 看到已有共识不再重问场景
        allowed_paths: Refine Intent 的 target_paths ∪ derived_paths。
            非空时 BrainstormAgent 的 ask_user tool 会硬约束 target_path 必须落在内，
            越界直接拒绝。这是"AI 不要答非所问"的 tool layer 强约束。
    """
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
        base_spec_brief=base_spec_brief,
        allowed_paths=allowed_paths,
    )


async def _run_coding_task(
    *,
    conversation_id: int,
    user_id: int,
    tenant_id: int,
    workspace_id: Optional[str],
    spec_envelope: dict[str, Any],
) -> None:
    """后台跑 CodingAgent → VerificationAgent autofix 闭环。

    Session 隔离：
    - task_db   driver 的 coordinator phase 转移
    - pub_db    publisher（含 per-conversation lock，serialize 并发事件写）
    - trace_db  trace_writer（含 per-instance lock，serialize asyncio.gather 并发 trace 写）

    三 session 分离可防止 asyncio.gather 并发工具调用时不同 db 操作互相干扰。
    """
    coding_session_id = f"c_{secrets.token_hex(6)}"

    async with (
        AsyncSessionLocal() as task_db,
        AsyncSessionLocal() as pub_db,
        AsyncSessionLocal() as trace_db,
    ):
        try:
            # 从 conversation 读用户在首条消息时选的 llm_config；不在就走租户默认
            conv_row = await task_db.get(Conversation, conversation_id)
            selected_cfg_id = conv_row.selected_llm_config_id if conv_row else None
            base_url, api_key, model = await load_coding_llm_config(
                tenant_id,
                f"llmcfg:{selected_cfg_id}" if selected_cfg_id else None,
            )
            llm_client = LLMClient(api_key=api_key, base_url=base_url, model=model)

            def _make_ctx(session_id: str) -> AgentContext:
                return AgentContext(
                    session_id=session_id,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    model=model,
                    workspace_id=workspace_id,
                    input={},
                    publisher=get_db_publisher().scoped(pub_db),    # type: ignore[attr-defined]
                    trace_writer=get_db_trace_writer().scoped(trace_db),  # type: ignore[attr-defined]
                    llm_client=llm_client,
                )

            if workspace_id:
                # workspace 已存在：跑 coding → verify autofix 闭环
                from app.coding.workspace import WorkspaceManager
                from app.models.agent_models import CodingSession as CodingSessionModel
                ws_mgr = WorkspaceManager()
                workspace_root = ""
                try:
                    workspace_root = str(ws_mgr.get_workspace_path(workspace_id))
                except Exception as e:
                    logger.warning("get_workspace_path(%s) 失败：%s，降级为无 verify", workspace_id, e)

                if workspace_root:
                    logger.info(
                        "coding task %s: workspace_root=%s，将运行 coding → verify autofix 闭环",
                        coding_session_id, workspace_root,
                    )
                    # 先创建 coding_sessions 行（verification_reports 有 FK 依赖它）
                    spec_id_for_cs = (spec_envelope.get("spec_id") or "") if isinstance(spec_envelope, dict) else ""
                    if not spec_id_for_cs:
                        logger.error("coding task %s: spec_envelope 缺少 spec_id，无法创建 CodingSession", coding_session_id)
                        return
                    cs_row = CodingSessionModel(
                        id=coding_session_id,
                        conversation_id=conversation_id,
                        spec_id=spec_id_for_cs,
                        workspace_id=workspace_id,
                        status="running",
                        model_used=model,
                    )
                    task_db.add(cs_row)
                    await task_db.commit()

                    # 构建错误录制器（project_type 从 workspace 读，scene_type 从 spec 读）
                    from app.services.error_recorder import AgentErrorRecorder
                    _project_type = ""
                    try:
                        ws_info = ws_mgr.get_workspace_info(workspace_id)
                        _project_type = (ws_info.get("project_type") or "").lower()
                    except Exception:
                        pass
                    _scene_type = (spec_envelope.get("scene_type") or "") if isinstance(spec_envelope, dict) else ""
                    error_recorder = AgentErrorRecorder(
                        coding_session_id=coding_session_id,
                        spec_id=spec_id_for_cs,
                        workspace_id=workspace_id,
                        project_type=_project_type,
                        scene_type=_scene_type,
                    )

                    def _make_ctx_with_recorder(session_id: str) -> AgentContext:
                        ctx = _make_ctx(session_id)
                        ctx.extra = {**(ctx.extra or {}), "error_recorder": error_recorder}
                        return ctx

                    autofix_result = await driver.drive_coding_with_autofix(
                        task_db,
                        conversation_id=conversation_id,
                        spec_envelope=spec_envelope,
                        coding_ctx_factory=lambda: _make_ctx_with_recorder(f"c_{secrets.token_hex(6)}"),
                        verification_ctx_factory=lambda: _make_ctx(f"v_{secrets.token_hex(6)}"),
                        workspace_root=workspace_root,
                        coding_session_id=coding_session_id,
                        workspace_id=workspace_id,
                    )
                    # 更新 coding_sessions 状态
                    cs_row.status = "completed" if autofix_result.final_status in ("passed", "partial") else "failed"
                    await task_db.commit()
                    return

            # 降级路径（workspace 不存在或路径解析失败）：直接 coding，不走 verify
            logger.warning(
                "coding task %s：workspace_id=%s 无效，降级为直接 coding（无 verify）",
                coding_session_id, workspace_id,
            )
            ctx = _make_ctx(coding_session_id)
            await driver.drive_coding_from_spec(task_db, spec_envelope=spec_envelope, ctx=ctx)
            await task_db.commit()

        except Exception as e:
            logger.exception("coding task %s crashed: %s", coding_session_id, e)
            try:
                await task_db.rollback()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
# Error Report API
# ══════════════════════════════════════════════════════════════

class ErrorEventItem(BaseModel):
    id: str
    coding_session_id: str
    spec_id: Optional[str]
    workspace_id: Optional[str]
    project_type: Optional[str]
    scene_type: Optional[str]
    round_index: int
    turn: int
    error_type: str
    tool_name: Optional[str]
    error_message: str
    resolved: bool
    created_at: str


class ErrorReportResponse(BaseModel):
    total: int
    tool_fail_count: int
    verify_fail_count: int
    resolved_count: int
    project_type_breakdown: dict[str, int]
    error_type_breakdown: dict[str, int]
    items: List[ErrorEventItem]


@router.get("/error-report", response_model=ErrorReportResponse)
async def get_error_report(
    session_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    project_type: Optional[str] = None,
    scene_type: Optional[str] = None,
    limit: int = 200,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
):
    """查询 CodingAgent 错误事件报告，用于提示词优化分析。

    支持按 session_id / workspace_id / project_type / scene_type 过滤。
    返回汇总统计 + 明细列表。
    """
    from sqlalchemy import select
    from app.models.agent_models import AgentErrorEvent

    stmt = select(AgentErrorEvent)
    if session_id:
        stmt = stmt.where(AgentErrorEvent.coding_session_id == session_id)
    if workspace_id:
        stmt = stmt.where(AgentErrorEvent.workspace_id == workspace_id)
    if project_type:
        stmt = stmt.where(AgentErrorEvent.project_type == project_type)
    if scene_type:
        stmt = stmt.where(AgentErrorEvent.scene_type == scene_type)
    stmt = stmt.order_by(AgentErrorEvent.created_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()

    items = [
        ErrorEventItem(
            id=r.id,
            coding_session_id=r.coding_session_id,
            spec_id=r.spec_id,
            workspace_id=r.workspace_id,
            project_type=r.project_type,
            scene_type=r.scene_type,
            round_index=r.round_index,
            turn=r.turn,
            error_type=r.error_type,
            tool_name=r.tool_name,
            error_message=r.error_message,
            resolved=r.resolved,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]

    project_type_breakdown: dict[str, int] = {}
    error_type_breakdown: dict[str, int] = {}
    for it in items:
        k = it.project_type or "unknown"
        project_type_breakdown[k] = project_type_breakdown.get(k, 0) + 1
        error_type_breakdown[it.error_type] = error_type_breakdown.get(it.error_type, 0) + 1

    return ErrorReportResponse(
        total=len(items),
        tool_fail_count=sum(1 for it in items if it.error_type in ("tool_fail", "tool_not_found")),
        verify_fail_count=sum(1 for it in items if it.error_type == "verify_fail"),
        resolved_count=sum(1 for it in items if it.resolved),
        project_type_breakdown=project_type_breakdown,
        error_type_breakdown=error_type_breakdown,
        items=items,
    )
