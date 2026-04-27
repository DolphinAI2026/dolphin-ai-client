"""emit_spec tool — 产出最终 Spec，结束 brainstorm 循环。

流程：
1. LLM 构造完整 Spec JSON 作为参数传入（不含 provenance/spec_id/schema_version —
   由系统补齐；LLM 只管业务字段）
2. 校验：
   - Pydantic schema（通过 TypeAdapter[Spec] 的 discriminated union）
   - 业务规则（app.spec.validators.validate_spec）
3. 校验通过 → 固化到 state.emitted_spec_id + state.emitted=True
   → 下一轮 should_terminate 返回 True
4. 校验失败 → ToolResult.success=False，把错误列表反馈给 LLM，让它修改重试

系统自动补齐：
- schema_version = "1.0"
- spec_id = ULID
- provenance.brainstorm_session_id = ctx.session_id
- provenance.created_at = now
- provenance.created_by = "agent"
- provenance.model = ctx.model
- provenance.version = 1（首次）或自增（P2.3 迭代）
- provenance.confidence = 由 confidence.py 计算（不信 LLM 自填）
- provenance.open_questions = LLM 传的 + state.open_questions 合并去重
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import TypeAdapter, ValidationError

logger = logging.getLogger(__name__)

from app.agents.brainstorm.confidence import compute_confidence, emit_decision
from app.agents.brainstorm.state import BrainstormState
from app.agents.types import AgentContext, Tool, ToolResult
from app.spec.schema import CreatedBy, OpenQuestion, Spec
from app.spec.validators import validate_spec


def _new_spec_id() -> str:
    """生成 Spec ID — 目前用时间戳 + 随机后缀；P2.3 接 DB 时换 ULID"""
    import secrets
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"spec_{ts}_{secrets.token_hex(3)}"


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scene_type": {
            "type": "string",
            "description": "场景类型（必须与 detect_scene 记录的一致）",
        },
        "identity": {
            "type": "object",
            "description": (
                "Identity 字段：code_name / display_name / description_cn / widget_code。"
                "组件场景必须给 widget_code（FORM_CUSTOM_*）。"
            ),
        },
        "intent": {
            "type": "object",
            "description": (
                "Intent 字段：original_requirement / core_purpose / acceptance_criteria。"
                "acceptance_criteria 至少 1 条，每条 ≥ 5 字，可验证。"
            ),
        },
        "spec": {
            "type": "object",
            "description": (
                "场景特定 spec 字段。ComponentSpec / PageSpec / BackendApiSpec 之一，"
                "结构以对应 Pydantic 模型为准。"
            ),
        },
        "metadata": {
            "type": "object",
            "description": "可选 — attachments / reference_component_ids / ui_mockup_url / extra",
        },
        "references": {
            "type": "array",
            "items": {"type": "object"},
            "description": "可选 — 关联其他 Spec（spec_id + relation）",
        },
        "open_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "assumed_answer": {"type": "string"},
                },
                "required": ["question", "assumed_answer"],
            },
            "description": (
                "你在 brainstorm 过程中做的**默认假设**清单。未消解的模糊点必须在此列出，"
                "否则 CodingAgent 不知道你偷懒默认了什么。"
            ),
        },
    },
    "required": ["scene_type", "identity", "intent", "spec"],
    "additionalProperties": False,
}


def build_emit_spec_tool(state: BrainstormState) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        if state.emitted:
            return ToolResult(
                success=False,
                content="本 session 已 emit 过 Spec，不能重复 emit。",
                error="already_emitted",
            )

        # LLM 传来的 open_questions 合并到 state
        new_oqs: list[OpenQuestion] = []
        for oq in args.get("open_questions") or []:
            try:
                new_oqs.append(OpenQuestion(**oq))
            except Exception as e:
                return ToolResult(
                    success=False,
                    content=f"open_questions 某条格式不对：{e}",
                    error=str(e),
                )

        # 合并去重（按 question 文本）
        merged_oqs = list(state.open_questions)
        seen = {oq.question for oq in merged_oqs}
        for oq in new_oqs:
            if oq.question not in seen:
                merged_oqs.append(oq)
                seen.add(oq.question)

        # 计算 confidence + 决策
        # ── iterate 模式跳过 confidence gate ──
        # 触发条件：state.allowed_paths 非空（由 _run_iterate_dispatch_task 注入）
        # 原因：iterate 场景下 scene/P1 都已在 base_spec 里定好，LLM 不会再调
        # detect_scene，导致 state.scene_confidence=0 / p1_coverage=0。
        # 如果仍卡在 gate="block"，LLM 会"必须回到 detect_scene"但 iterate prompt
        # 又禁止 detect_scene → 死循环 → 消息堆积到 LLM 返回 400。
        # 解法：iterate 模式信任 classifier 已经明确了改动范围，直接允许 emit。
        is_iterate = bool(state.allowed_paths)
        confidence = compute_confidence(state)
        gate, gate_reason = emit_decision(confidence)
        if gate == "block" and not is_iterate:
            return ToolResult(
                success=False,
                content=(
                    f"❌ emit 被拒：{gate_reason}\n"
                    f"当前状态：scene_confidence={state.scene_confidence}, "
                    f"p1_coverage={state.p1_coverage()}\n"
                    "请继续调用 ask_user 回答关键 P1 问题（若反问轮数未满），"
                    "或回到 detect_scene 重新识别场景。"
                ),
                error="confidence_too_low",
                data={"confidence": confidence, "gate": gate},
            )
        if is_iterate and gate == "block":
            logger.info(
                "emit_spec: iterate 模式跳过 confidence gate（allowed_paths=%s, computed_confidence=%.2f）",
                state.allowed_paths, confidence,
            )

        # 系统补齐字段
        spec_id = _new_spec_id()
        now = datetime.now(timezone.utc)
        envelope_dict: dict[str, Any] = {
            "schema_version": "1.0",
            "spec_id": spec_id,
            "scene_type": args.get("scene_type"),
            "provenance": {
                "brainstorm_session_id": ctx.session_id,
                "created_at": now.isoformat(),
                "created_by": CreatedBy.AGENT.value,
                "model": ctx.model,
                "version": 1,
                "parent_version": None,
                "confidence": confidence,
                "open_questions": [oq.model_dump() for oq in merged_oqs],
            },
            "identity": args.get("identity") or {},
            "intent": args.get("intent") or {},
            "spec": args.get("spec") or {},
            "metadata": args.get("metadata") or {},
            "references": args.get("references") or [],
        }

        # 1) Pydantic 校验（discriminated union）
        try:
            envelope = TypeAdapter(Spec).validate_python(envelope_dict)
        except ValidationError as e:
            return ToolResult(
                success=False,
                content=(
                    "❌ Spec 未通过 Pydantic 校验，请根据错误修改后重试：\n"
                    f"```\n{e}\n```"
                ),
                error="pydantic_validation_failed",
                data={"errors": e.errors()[:20]},
            )

        # 2) 业务规则校验
        vresult = validate_spec(envelope)
        if not vresult.ok:
            err_lines = [f"- [{e.code}] {e.path}: {e.message}" for e in vresult.errors]
            return ToolResult(
                success=False,
                content=(
                    "❌ Spec 未通过业务规则校验：\n"
                    + "\n".join(err_lines)
                    + "\n请根据 code 和 message 修改后重试。"
                ),
                error="business_validation_failed",
                data={"errors": [{"code": e.code, "path": e.path, "message": e.message} for e in vresult.errors]},
            )

        # 固化到 state
        state.emitted = True
        state.emitted_spec_id = spec_id
        state.open_questions = merged_oqs

        # warnings 以文本附带（不阻止 emit）
        warn_text = ""
        if vresult.warnings:
            warn_lines = [f"- [{w.code}] {w.path}: {w.message}" for w in vresult.warnings]
            warn_text = "\n\n⚠️ 有 warning（不阻断 emit）：\n" + "\n".join(warn_lines)

        gate_tag = "" if gate == "ok" else f"（置信度 gate={gate}：{gate_reason}）"

        # 注意：不在这里发 brainstorm.spec_emitted 事件。
        # drive_brainstorm 会在 spec 落库 commit 之后再发，避免前端
        # 收到事件时 spec 还没持久化（竞态 → 404）。
        return ToolResult(
            success=True,
            content=(
                f"✅ Spec 已 emit：{spec_id}\n"
                f"confidence={confidence} {gate_tag}"
                f"{warn_text}"
            ),
            data={
                "spec_id": spec_id,
                "confidence": confidence,
                "gate": gate,
                "warnings": [
                    {"code": w.code, "path": w.path, "message": w.message}
                    for w in vresult.warnings
                ],
                "envelope": envelope.model_dump(mode="json"),
            },
        )

    return Tool(
        name="emit_spec",
        description=(
            "产出最终 Spec，结束 brainstorm。完整字段（除 schema_version/spec_id/provenance "
            "由系统补齐外）必须齐全。会先做 Pydantic 校验，再做业务规则校验。"
            "任一失败 → tool result 错误，LLM 据此修改重试。"
        ),
        parameters_schema=_SCHEMA,
        execute=execute,
        idempotent=False,
    )
