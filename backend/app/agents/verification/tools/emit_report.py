"""emit_report tool — 产出 VerificationReport 并结束 agent 循环。

行为：
1. 检查：所有 AC 必须已 check（没有 pending）—— 否则拒绝
2. 允许 LLM 对 constraints 做最后标注（constraint_updates 参数）
3. 记录 report_id，state.report_emitted=True → should_terminate 返回 True
4. 真实持久化由 driver 在 agent 完成后做（emit_report tool 只负责 state 标记 + 事件）
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from app.agents.types import AgentContext, Tool, ToolResult
from app.agents.verification.state import VerificationState

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "一段话总结本次验收结论（给用户看）。例：'整体通过，主色配置已生效；List 模式评分显示只读，符合 scenes 要求'",
        },
        "constraint_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "constraint 在清单中的 0-based 下标（hard 在前 soft 在后）"},
                    "status": {"type": "string", "enum": ["ok", "violated"]},
                    "evidence": {"type": "string"},
                },
                "required": ["index", "status"],
                "additionalProperties": False,
            },
            "description": (
                "可选 — 对 constraints 的最终标注。不传表示所有 constraint 保持 pending"
                "（会被视为 ok —— 未违反）"
            ),
        },
    },
    "required": ["summary"],
    "additionalProperties": False,
}


def _new_report_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"vr_{ts}_{secrets.token_hex(3)}"


def build_emit_report_tool(state: VerificationState) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        if state.report_emitted:
            return ToolResult(
                success=False,
                content="本 session 已 emit 过 report，不能重复",
                error="already_emitted",
            )

        # 硬检查：有 pending AC 时拒绝
        pending = state.pending_ac()
        if pending:
            pending_desc = "; ".join(f"#{p.index} {p.description[:40]}" for p in pending[:5])
            return ToolResult(
                success=False,
                content=(
                    f"❌ 还有 {len(pending)} 条 pending AC 未 check，不能 emit_report。"
                    f"待检查：{pending_desc}"
                ),
                error="pending_ac",
            )

        summary = str(args.get("summary", "")).strip()
        if not summary:
            return ToolResult(success=False, content="summary 不能为空", error="empty_summary")

        # 应用 constraint_updates
        updates = args.get("constraint_updates") or []
        for u in updates:
            try:
                idx = int(u["index"])
            except Exception:
                continue
            if 0 <= idx < len(state.constraint_results):
                c = state.constraint_results[idx]
                c.status = u.get("status", "ok")  # type: ignore[assignment]
                ev = (u.get("evidence") or "").strip()
                if ev:
                    c.evidence = ev

        # 未标注的 constraint 默认 ok
        for c in state.constraint_results:
            if c.status == "pending":
                c.status = "ok"

        # 生成 report_id
        report_id = _new_report_id()
        state.report_emitted = True
        state.emitted_report_id = report_id

        overall = state.overall_status()
        # 硬约束被违反时必须降到 failed
        hard_violated = state.constraints_hard_violated()
        if hard_violated and overall != "failed":
            overall = "failed"

        return ToolResult(
            success=True,
            content=(
                f"✅ VerificationReport 已 emit: {report_id}\n"
                f"overall_status={overall}\n"
                f"passed={state.passed_count()} / failed={state.failed_count()} / "
                f"total={len(state.ac_items)}\n"
                f"hard_violated={len(hard_violated)}\n"
                f"summary: {summary}"
            ),
            data={
                "report_id": report_id,
                "overall_status": overall,
                "passed_count": state.passed_count(),
                "failed_count": state.failed_count(),
                "hard_violated_count": len(hard_violated),
                "summary": summary,
                "items": [a.to_dict() for a in state.ac_items],
                "constraint_results": [c.to_dict() for c in state.constraint_results],
            },
            emit_event={
                "type": "verification.report_emitted",
                "data": {
                    "report_id": report_id,
                    "overall_status": overall,
                    "passed_count": state.passed_count(),
                    "failed_count": state.failed_count(),
                    # 前端要直接渲染每条 AC 的 pass/fail + evidence，
                    # 这里随事件一起发；数据已经在 state 里，没额外成本
                    "items": [a.to_dict() for a in state.ac_items],
                    "summary": summary,
                },
            },
        )

    return Tool(
        name="emit_report",
        description=(
            "产出最终 VerificationReport。调用前提：所有 AC 必须已 check（否则拒绝）。"
            "调用成功即 session 结束。"
        ),
        parameters_schema=_SCHEMA,
        execute=execute,
        idempotent=False,
    )
