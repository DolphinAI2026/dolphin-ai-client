"""check_ac tool — 记录单条 acceptance criterion 的验收结果。

LLM 完成 grep / read 调查后调用此 tool 记录结论。每次一条。
"""
from __future__ import annotations

from typing import Any

from app.agents.types import AgentContext, Tool, ToolResult
from app.agents.verification.config import AC_CONFIDENCE_LOW
from app.agents.verification.state import VerificationState

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ac_index": {
            "type": "integer",
            "minimum": 0,
            "description": "要记录的 AC 的 0-based 下标（见首条消息列出的 #N）",
        },
        "status": {
            "type": "string",
            "enum": ["passed", "failed", "needs_review"],
            "description": "验收结论。needs_review 表示证据不充分，人工审核",
        },
        "evidence": {
            "type": "string",
            "description": (
                "证据。**必填**。例：'在 edit.vue:32-45 看到 click 事件绑定、"
                "v-model 到 formValue.value，与 AC #0 一致'。"
                "failed 时必须说清楚缺什么 / 哪里错，让下游 CodingAgent 知道怎么改"
            ),
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "对自己判断的置信度 0-1。找到明确证据 ≥ 0.85；不确定 < 0.7",
        },
    },
    "required": ["ac_index", "status", "evidence", "confidence"],
    "additionalProperties": False,
}


def build_check_ac_tool(state: VerificationState) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        try:
            idx = int(args["ac_index"])
        except (KeyError, ValueError, TypeError) as e:
            return ToolResult(success=False, content=f"ac_index 非法：{e}", error="bad_index")

        status = str(args.get("status", ""))
        if status not in ("passed", "failed", "needs_review"):
            return ToolResult(
                success=False,
                content=f"status 必须为 passed/failed/needs_review，收到：{status}",
                error="bad_status",
            )

        evidence = str(args.get("evidence", "")).strip()
        if not evidence:
            return ToolResult(
                success=False,
                content="evidence 不能为空（failed 尤其要说清'哪里错'）",
                error="empty_evidence",
            )

        try:
            confidence = float(args.get("confidence", 0.0))
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        # 找对应 AC
        target = None
        for item in state.ac_items:
            if item.index == idx:
                target = item
                break
        if target is None:
            return ToolResult(
                success=False,
                content=f"AC #{idx} 不存在（共 {len(state.ac_items)} 条）",
                error="ac_not_found",
            )

        # 低置信度的 passed 降级为 needs_review
        effective_status = status
        if status == "passed" and confidence < AC_CONFIDENCE_LOW:
            effective_status = "needs_review"

        target.status = effective_status  # type: ignore[assignment]
        target.evidence = evidence
        target.confidence = confidence

        # 反馈给 LLM：更新后的整体状态
        pending = state.pending_ac()
        pending_summary = (
            f"还有 {len(pending)} 条 pending" if pending else "所有 AC 已 check，请调 emit_report"
        )
        content = (
            f"✅ 已记录：AC #{idx} → {effective_status} (confidence={confidence})\n"
            f"Evidence: {evidence[:200]}\n"
            f"进度：passed={state.passed_count()} / failed={state.failed_count()} / "
            f"total={len(state.ac_items)}；{pending_summary}"
        )
        if effective_status != status:
            content += f"\n（注：status 从 {status} 降级为 {effective_status}，因 confidence 过低）"

        return ToolResult(
            success=True,
            content=content,
            data={
                "ac_index": idx,
                "status": effective_status,
                "confidence": confidence,
                "pending_indexes": [a.index for a in pending],
            },
            emit_event={
                "type": "verification.ac_checked",
                "data": {
                    "ac_index": idx,
                    "status": effective_status,
                    "confidence": confidence,
                },
            },
        )

    return Tool(
        name="check_ac",
        description=(
            "记录单条 Acceptance Criterion 的验收结果。基于 grep/read 找到的证据调用。"
            "每条 AC 至少调用一次；重复调用最后一次覆盖前面的结果。"
        ),
        parameters_schema=_SCHEMA,
        execute=execute,
        idempotent=False,
    )
