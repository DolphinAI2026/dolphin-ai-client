"""Orchestrator Driver — BrainstormAgent / CodingAgent 的运行驱动。

职责：
- 启动 Agent + 把产出物落地 DB（Spec / CodingSession）
- 把 agent 产出事件映射回 phase 转移
- 作为 pipeline.py 的替代（P4 新 API 会直接使用）

MVP 阶段不做：
- 多 agent 并行
- 断线重连的 SSE 补发（由 ConversationEvent 表 + P2.4 SSE 层负责）
- 完整的 iterate 分级（trivial/minor/major）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.brainstorm import BrainstormAgent
from app.agents.coding import CodingAgent
from app.agents.coding.spec_bridge import build_coding_input_from_spec
from app.agents.types import AgentContext, AgentResult, AgentStatus
from app.agents.verification import MAX_AUTO_FIX_ROUNDS, VerificationAgent
from app.orchestrator import coordinator as orch
from app.orchestrator.phases import Phase
from app.services import brainstorm_session_service as bs_svc
from app.services import spec_service
from app.services import verification_report_service as vr_svc

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 结果模型
# ══════════════════════════════════════════════════════════════

class BrainstormDriveResult:
    """drive_brainstorm 返回"""

    __slots__ = ("status", "session_id", "spec_id", "spec_envelope", "agent_result")

    def __init__(
        self,
        *,
        status: str,
        session_id: str,
        spec_id: Optional[str] = None,
        spec_envelope: Optional[dict[str, Any]] = None,
        agent_result: Optional[AgentResult] = None,
    ) -> None:
        self.status = status  # "emitted" / "degraded" / "failed" / "aborted"
        self.session_id = session_id
        self.spec_id = spec_id
        self.spec_envelope = spec_envelope
        self.agent_result = agent_result


class CodingDriveResult:
    """drive_coding 返回"""

    __slots__ = ("status", "spec_id", "agent_result")

    def __init__(
        self,
        *,
        status: str,
        spec_id: str,
        agent_result: Optional[AgentResult] = None,
    ) -> None:
        self.status = status  # "done" / "failed" / "aborted"
        self.spec_id = spec_id
        self.agent_result = agent_result


class VerificationDriveResult:
    """drive_verification 返回"""

    __slots__ = ("status", "report_id", "overall_status", "passed_count", "failed_count", "report_row", "agent_result")

    def __init__(
        self,
        *,
        status: str,
        report_id: Optional[str],
        overall_status: str,
        passed_count: int = 0,
        failed_count: int = 0,
        report_row: Optional[Any] = None,
        agent_result: Optional[AgentResult] = None,
    ) -> None:
        self.status = status  # "emitted" / "degraded" / "failed"
        self.report_id = report_id
        self.overall_status = overall_status  # passed / failed / partial / pending
        self.passed_count = passed_count
        self.failed_count = failed_count
        self.report_row = report_row
        self.agent_result = agent_result


class AutoFixLoopResult:
    """drive_coding_with_autofix 返回 —— 描述整个重试循环"""

    __slots__ = ("final_status", "rounds", "last_verification", "reports", "coding_results")

    def __init__(
        self,
        *,
        final_status: str,
        rounds: int,
        last_verification: Optional[VerificationDriveResult] = None,
        reports: Optional[list[VerificationDriveResult]] = None,
        coding_results: Optional[list[CodingDriveResult]] = None,
    ) -> None:
        self.final_status = final_status  # "passed" / "failed" / "partial" / "aborted"
        self.rounds = rounds
        self.last_verification = last_verification
        self.reports = reports or []
        self.coding_results = coding_results or []


# ══════════════════════════════════════════════════════════════
# drive_brainstorm
# ══════════════════════════════════════════════════════════════

async def drive_brainstorm(
    db: AsyncSession,
    *,
    agent: BrainstormAgent,
    session_id: str,
    auto_persist_spec: bool = True,
) -> BrainstormDriveResult:
    """跑完一次 BrainstormAgent，把产出 Spec 落库 + 推进 phase。

    语义：
    - agent.run() 结束时，若 state.emitted=True → 从 agent.state.emitted_spec_id
      拿到 Spec，通过 spec_service.save_spec 持久化
    - 同时 mark brainstorm_session 状态（保持 active —— 用户可能 refine）
    - 推进 conversation.coding_phase：UNDERSTAND → CONFIRM

    边界：
    - Paused（ask_user should_pause=True）→ 返回 status=paused，不动 phase
    - Failed → on_agent_failed，phase=FAILED
    - Degraded（max_turns 耗尽未 emit）→ 降级保存（confidence 低的 Spec）或直接报错

    调用方若有 pipeline 事件流，应配合 BaseAgent._publish 订阅。
    """
    result = await agent.run()

    conversation_id = agent.ctx.conversation_id
    final_status = result.status

    # —— 成功 emit —— #
    if (
        final_status == AgentStatus.COMPLETED
        and agent.state.emitted
        and result.product
    ):
        envelope = (result.product or {}).get("envelope")
        if not envelope and auto_persist_spec:
            logger.warning(
                "brainstorm %s completed but finalize 未返回 envelope，跳过持久化",
                session_id,
            )
            return BrainstormDriveResult(
                status="degraded",
                session_id=session_id,
                agent_result=result,
            )

        persisted_spec_id = None
        if auto_persist_spec and envelope:
            try:
                # reuse_envelope_spec_id=True：emit_spec tool 已经生成 spec_id 并通过
                #   brainstorm.spec_emitted event 发给前端了，必须让 DB 主键与 event 里
                #   的 spec_id 完全一致，否则前端按事件里的 id GET /api/spec/{id} 就 404。
                row = await spec_service.save_spec(
                    db,
                    brainstorm_session_id=session_id,
                    envelope=envelope,
                    reuse_envelope_spec_id=True,
                )
                persisted_spec_id = row.id
            except Exception as e:
                logger.exception("Spec 持久化失败（brainstorm session=%s）：%s", session_id, e)
                await bs_svc.mark_session_failed(
                    db, session_id=session_id, error_message=f"spec persist failed: {e}"
                )
                return BrainstormDriveResult(
                    status="failed",
                    session_id=session_id,
                    agent_result=result,
                )

        # 推进 phase：UNDERSTAND → CONFIRM
        try:
            await orch.on_brainstorm_emit(
                db,
                conversation_id=conversation_id,
                brainstorm_session_id=session_id,
                spec_id=persisted_spec_id or "inmem",
            )
        except Exception as e:
            logger.warning("phase 推进失败（非致命）: %s", e)

        return BrainstormDriveResult(
            status="emitted",
            session_id=session_id,
            spec_id=persisted_spec_id,
            spec_envelope=envelope,
            agent_result=result,
        )

    # —— 降级（未 emit 就退出）—— #
    if final_status == AgentStatus.COMPLETED and not agent.state.emitted:
        return BrainstormDriveResult(
            status="degraded",
            session_id=session_id,
            agent_result=result,
        )

    # —— Paused（ask_user 等回答）—— #
    if final_status == AgentStatus.PAUSED:
        # 把 snapshot 落 DB 供后续 resume
        await bs_svc.suspend_session(db, session_id=session_id, agent=agent, reason="ask_user_pause")
        return BrainstormDriveResult(
            status="paused",
            session_id=session_id,
            agent_result=result,
        )

    # —— Aborted / Failed —— #
    if final_status == AgentStatus.ABORTED:
        return BrainstormDriveResult(
            status="aborted",
            session_id=session_id,
            agent_result=result,
        )

    # 默认当 failed
    await bs_svc.mark_session_failed(
        db, session_id=session_id, error_message=result.error_message or "unknown"
    )
    await orch.on_agent_failed(
        db, conversation_id=conversation_id,
        error_message=result.error_message or "brainstorm failed",
    )
    return BrainstormDriveResult(
        status="failed",
        session_id=session_id,
        agent_result=result,
    )


# ══════════════════════════════════════════════════════════════
# drive_coding
# ══════════════════════════════════════════════════════════════

async def drive_coding_from_spec(
    db: AsyncSession,
    *,
    spec_envelope: dict[str, Any],
    ctx: AgentContext,
    conversation_summary: str = "",
    max_turns: int = 30,
    push_phase: bool = True,
) -> CodingDriveResult:
    """基于 Spec 启动 CodingAgent 并跑完。

    **不创建** `coding_sessions` DB 行（那是 P4 职责，需要 workspace_id 已落地），
    **不创建** workspace（也是 P4）—— 本函数只驱动 agent 产出代码事件。

    参数 ctx 应由调用方构造完毕（含 workspace_id、publisher、trace_writer、llm_client）。
    `input` 字段会被 spec_bridge 的产出覆盖。
    """
    if not ctx.llm_client:
        raise ValueError("AgentContext.llm_client 未注入，CodingAgent 无法运行")

    # 用 spec_bridge 构造 input（保留 ctx.input 里的自定义扩展字段）
    bridge_input = build_coding_input_from_spec(
        spec_envelope,
        conversation_summary=conversation_summary,
        max_turns=max_turns,
    )
    merged_input: dict[str, Any] = dict(ctx.input or {})
    # Spec 驱动的核心字段强制覆盖（防止调用方传入的 raw requirement 污染）
    merged_input.update(bridge_input)
    ctx.input = merged_input

    # 构造 agent（此时 ctx.input 里已有 spec_brief / spec_envelope / project_type）
    agent = CodingAgent(ctx)
    result = await agent.run()

    conversation_id = ctx.conversation_id
    spec_id = spec_envelope.get("spec_id") or ""

    if result.status == AgentStatus.COMPLETED:
        if push_phase:
            try:
                await orch.on_coding_done(db, conversation_id=conversation_id)
            except Exception as e:
                logger.warning("coding done 阶段推进失败（非致命）: %s", e)
        return CodingDriveResult(status="done", spec_id=spec_id, agent_result=result)

    if result.status == AgentStatus.ABORTED:
        return CodingDriveResult(status="aborted", spec_id=spec_id, agent_result=result)

    # FAILED / 其他
    await orch.on_agent_failed(
        db, conversation_id=conversation_id,
        error_message=result.error_message or "coding failed",
    )
    return CodingDriveResult(status="failed", spec_id=spec_id, agent_result=result)


# ══════════════════════════════════════════════════════════════
# 集成便捷 API
# ══════════════════════════════════════════════════════════════

async def confirm_spec_and_prepare_coding(
    db: AsyncSession,
    *,
    conversation_id: int,
    spec_id: str,
    need_scaffold: bool,
) -> dict[str, Any]:
    """用户 /confirm API 内部调用：mark brainstorm completed + phase 推进 + 返回 Spec envelope。

    调用方拿到 envelope 后可直接 drive_coding_from_spec。
    """
    # 加载 Spec
    spec_row = await spec_service.get_spec(db, spec_id)
    if not spec_row:
        raise ValueError(f"spec {spec_id} not found")

    await bs_svc.mark_session_completed(
        db, session_id=spec_row.brainstorm_session_id, final_spec_id=spec_id
    )
    await orch.on_spec_confirmed(
        db, conversation_id=conversation_id, spec_id=spec_id, need_scaffold=need_scaffold,
    )
    return spec_row.content or {}


# ══════════════════════════════════════════════════════════════
# drive_verification
# ══════════════════════════════════════════════════════════════

async def drive_verification(
    db: AsyncSession,
    *,
    ctx: AgentContext,
    spec_envelope: dict[str, Any],
    workspace_root: str,
    coding_session_id: str,
    auto_persist: bool = True,
) -> VerificationDriveResult:
    """跑 VerificationAgent 对 coding 产物做 AC 验收。

    调用方负责传 ctx（含 publisher / trace_writer / llm_client），
    以及 `workspace_root`（物理目录，agent 的 grep/read 工具从这里读）。

    成功时 report 自动落 verification_reports 表。
    """
    if not ctx.llm_client:
        raise ValueError("AgentContext.llm_client 未注入")

    merged_input = dict(ctx.input or {})
    merged_input.update({
        "spec_envelope": spec_envelope,
        "workspace_root": workspace_root,
        "coding_session_id": coding_session_id,
    })
    ctx.input = merged_input

    agent = VerificationAgent(ctx)
    result = await agent.run()

    final = result.product or {}
    report_row = None

    if auto_persist and result.status == AgentStatus.COMPLETED:
        try:
            report_row = await vr_svc.save_report(
                db,
                coding_session_id=coding_session_id,
                spec_id=spec_envelope.get("spec_id") or "",
                finalize_result=final,
                model_used=ctx.model,
            )
        except Exception as e:
            logger.exception("verification report persist failed: %s", e)

    # driver 侧 status：
    # - agent COMPLETED + emit_report 被调用 → "emitted"
    # - agent COMPLETED 但没 emit（max_turns 降级）→ "degraded"
    # - 其它（FAILED/ABORTED）→ "failed"
    drive_status = "failed"
    if result.status == AgentStatus.COMPLETED:
        drive_status = "emitted" if final.get("emitted") else "degraded"

    return VerificationDriveResult(
        status=drive_status,
        report_id=final.get("report_id") or (report_row.id if report_row else None),
        overall_status=final.get("overall_status") or "pending",
        passed_count=int(final.get("passed_count") or 0),
        failed_count=int(final.get("failed_count") or 0),
        report_row=report_row,
        agent_result=result,
    )


# ══════════════════════════════════════════════════════════════
# drive_coding_with_autofix —— 闭环：coding → verify → (failed?) → coding 重跑
# ══════════════════════════════════════════════════════════════

def _build_fix_hint_from_report(
    report: VerificationDriveResult, spec_envelope: dict[str, Any],
) -> str:
    """从失败报告构造给 CodingAgent 的"修复提示"。

    注入到 ctx.input['fix_hint']，CodingAgent 可在 prompt 里看到"上一轮 coding
    不合 AC 的原因 + 具体哪几条 AC 要修"。
    """
    if not report.agent_result or not report.agent_result.product:
        return ""
    items = report.agent_result.product.get("items") or []
    failed = [i for i in items if i.get("status") == "failed"]
    cons = report.agent_result.product.get("constraint_results") or []
    hard_violated = [c for c in cons if c.get("severity") == "hard" and c.get("status") == "violated"]

    if not failed and not hard_violated:
        return ""

    lines = ["## 上一轮验收的失败项（CodingAgent 请针对性修复）"]
    if failed:
        lines.append("### Acceptance Criteria 失败")
        for f in failed:
            lines.append(f"- #{f.get('index')} {f.get('description', '')}")
            if f.get("evidence"):
                lines.append(f"  证据: {f['evidence']}")
    if hard_violated:
        lines.append("### 硬约束违反")
        for c in hard_violated:
            lines.append(f"- {c.get('text', '')}")
            if c.get("evidence"):
                lines.append(f"  证据: {c['evidence']}")
    return "\n".join(lines)


async def drive_coding_with_autofix(
    db: AsyncSession,
    *,
    conversation_id: int,
    spec_envelope: dict[str, Any],
    coding_ctx_factory,
    verification_ctx_factory,
    workspace_root: str,
    coding_session_id: str,
    max_fix_rounds: int = MAX_AUTO_FIX_ROUNDS,
) -> AutoFixLoopResult:
    """驱动 coding → verify 循环，最多 max_fix_rounds 次重跑。

    Phase 管理（由本函数全权负责，drive_coding_from_spec 用 push_phase=False）：
        GENERATE → coding → VERIFY → (passed → DONE)
                                     (failed, round < max → GENERATE → retry)
                                     (failed, round == max → DONE[failed])

    Args:
        conversation_id: 用于 phase 转移
        coding_ctx_factory: 每轮调一次返回一个"新的 coding AgentContext"（含 publisher 等）
        verification_ctx_factory: 同上，verification 用的
        workspace_root: 物理目录
        coding_session_id: 当前 coding session（所有轮都记在同一 session 下）

    返回的 AutoFixLoopResult.final_status:
        - "passed" —— 最终 overall_status=passed
        - "partial" —— 最终 overall_status=partial（有 needs_review 但无 failed）
        - "failed" —— max_fix_rounds 轮后仍 failed
        - "aborted" —— agent 在某轮被 abort
    """
    reports: list[VerificationDriveResult] = []
    coding_results: list[CodingDriveResult] = []
    last_verification: Optional[VerificationDriveResult] = None

    fix_hint = ""
    for round_i in range(max_fix_rounds + 1):
        # —— coding —— #
        coding_ctx = coding_ctx_factory()
        if fix_hint:
            coding_ctx.input = {**(coding_ctx.input or {}), "fix_hint": fix_hint}
        # push_phase=False：phase 由本函数统一管理
        coding_result = await drive_coding_from_spec(
            db, spec_envelope=spec_envelope, ctx=coding_ctx, push_phase=False,
        )
        coding_results.append(coding_result)
        if coding_result.status == "aborted":
            return AutoFixLoopResult(
                final_status="aborted",
                rounds=round_i + 1,
                last_verification=last_verification,
                reports=reports,
                coding_results=coding_results,
            )
        if coding_result.status == "failed":
            # coding 自身就失败了；直接返回
            return AutoFixLoopResult(
                final_status="failed",
                rounds=round_i + 1,
                last_verification=last_verification,
                reports=reports,
                coding_results=coding_results,
            )

        # coding 成功：GENERATE → VERIFY
        try:
            await orch.on_coding_complete_start_verify(db, conversation_id=conversation_id)
        except Exception as e:
            logger.warning("phase GENERATE→VERIFY 推进失败（非致命）: %s", e)

        # —— verify —— #
        verification_ctx = verification_ctx_factory()
        vr_result = await drive_verification(
            db,
            ctx=verification_ctx,
            spec_envelope=spec_envelope,
            workspace_root=workspace_root,
            coding_session_id=coding_session_id,
        )
        reports.append(vr_result)
        last_verification = vr_result

        if vr_result.status == "emitted":
            if vr_result.overall_status == "passed":
                # VERIFY → DONE
                try:
                    await orch.on_coding_done(db, conversation_id=conversation_id)
                except Exception as e:
                    logger.warning("phase VERIFY→DONE 推进失败（非致命）: %s", e)
                return AutoFixLoopResult(
                    final_status="passed",
                    rounds=round_i + 1,
                    last_verification=vr_result,
                    reports=reports,
                    coding_results=coding_results,
                )
            if vr_result.overall_status in ("partial",):
                # partial 不重跑（都是 needs_review，交人工）
                try:
                    await orch.on_coding_done(db, conversation_id=conversation_id)
                except Exception as e:
                    logger.warning("phase VERIFY→DONE 推进失败（非致命）: %s", e)
                return AutoFixLoopResult(
                    final_status="partial",
                    rounds=round_i + 1,
                    last_verification=vr_result,
                    reports=reports,
                    coding_results=coding_results,
                )
            # overall_status == failed
            if round_i >= max_fix_rounds:
                # 已用完重试额度 → VERIFY → DONE（带 failed 状态）
                try:
                    await orch.on_coding_done(db, conversation_id=conversation_id)
                except Exception as e:
                    logger.warning("phase VERIFY→DONE 推进失败（非致命）: %s", e)
                return AutoFixLoopResult(
                    final_status="failed",
                    rounds=round_i + 1,
                    last_verification=vr_result,
                    reports=reports,
                    coding_results=coding_results,
                )
            # 还有重试额度 → VERIFY → GENERATE
            try:
                await orch.on_verify_retry(db, conversation_id=conversation_id)
            except Exception as e:
                logger.warning("phase VERIFY→GENERATE 推进失败（非致命）: %s", e)
            fix_hint = _build_fix_hint_from_report(vr_result, spec_envelope)
            continue

        # verify 降级或失败：不重跑，直接 VERIFY → DONE
        try:
            await orch.on_coding_done(db, conversation_id=conversation_id)
        except Exception as e:
            logger.warning("phase VERIFY→DONE 推进失败（非致命）: %s", e)
        return AutoFixLoopResult(
            final_status="failed",
            rounds=round_i + 1,
            last_verification=vr_result,
            reports=reports,
            coding_results=coding_results,
        )

    # 理论上不会走到这里
    try:
        await orch.on_coding_done(db, conversation_id=conversation_id)
    except Exception as e:
        logger.warning("phase VERIFY→DONE 推进失败（非致命）: %s", e)
    return AutoFixLoopResult(
        final_status="failed",
        rounds=max_fix_rounds + 1,
        last_verification=last_verification,
        reports=reports,
        coding_results=coding_results,
    )
