"""detect_scene tool — 记录 LLM 对场景的判定结果，展开 P1 清单。

语义：LLM 通过上下文推理出场景后，调用此 tool 把判定固化到 state，
     系统据此加载对应 P1 问题清单（下一轮对话 LLM 就能看到推荐问什么）。

设计取舍：
- 不做独立的"小 LLM 识别"，成本更高且 LLM 已能在主对话里推理
- 但 tool result 会返回 P1 清单，让 LLM 清楚下一步反问方向
- 允许多次调用（置信度提高或场景变更时覆盖）
"""
from __future__ import annotations

from typing import Any

from app.agents.brainstorm.state import BrainstormState, make_p1_list
from app.agents.types import AgentContext, Tool, ToolResult
from app.spec.schema import SceneType

_DETECT_SCENE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scene_type": {
            "type": "string",
            "enum": [s.value for s in SceneType],
            "description": (
                "识别出的场景。web_component_dual=双端组件，web_page=PC页面，"
                "mobile_page=移动页面，backend_api=后端接口，backend_feign=外部调用，"
                "backend_scheduled=定时任务"
            ),
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "场景识别置信度 0-1。低于 0.5 时系统会提示需要继续澄清。",
        },
        "reason": {
            "type": "string",
            "description": "一句话说明判定依据（关键词 / 需求结构 / 附件等）",
        },
    },
    "required": ["scene_type", "confidence", "reason"],
    "additionalProperties": False,
}


def build_detect_scene_tool(state: BrainstormState) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        try:
            scene = SceneType(args["scene_type"])
        except (KeyError, ValueError) as e:
            return ToolResult(
                success=False,
                content=f"scene_type 非法：{e}",
                error=str(e),
            )

        confidence = float(args.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        reason = str(args.get("reason", "")).strip() or "(无)"

        # 更新 state
        state.scene_type = scene
        state.scene_confidence = confidence

        # 场景变化时重新展开 P1（保留已回答的同 key 项）
        old_answered = {q.key: (q.answered, q.answer) for q in state.p1_questions if q.answered}
        new_p1 = make_p1_list(scene)
        for q in new_p1:
            if q.key in old_answered:
                q.answered, q.answer = old_answered[q.key]
        state.p1_questions = new_p1

        # 给 LLM 反馈：本场景 P1 清单
        lines = [
            f"场景已记录：{scene.value}（confidence={confidence}）",
            f"判定依据：{reason}",
            "",
            "**本场景 P1 关键决策**（按顺序反问）：",
        ]
        for q in state.p1_questions:
            status = "✅ 已回答" if q.answered else "❓ 待问"
            ans = f"（答：{q.answer}）" if q.answered and q.answer else ""
            lines.append(f"- [{status}] {q.key} — {q.question_zh}{ans}")
        if confidence < 0.5:
            lines.append("")
            lines.append("⚠️ 置信度偏低，建议先问一个澄清性问题再继续。")

        return ToolResult(
            success=True,
            content="\n".join(lines),
            data={
                "scene_type": scene.value,
                "confidence": confidence,
                "p1_keys": [q.key for q in state.p1_questions],
            },
            emit_event={
                "type": "brainstorm.scene_detected",
                "data": {
                    "scene_type": scene.value,
                    "confidence": confidence,
                    "reason": reason,
                },
            },
        )

    return Tool(
        name="detect_scene",
        description=(
            "根据用户需求判定场景并固化到 state。返回该场景的 P1 关键决策清单。"
            "**必须**在反问 / emit_spec 前调用一次。场景有变时可再次调用覆盖。"
        ),
        parameters_schema=_DETECT_SCENE_SCHEMA,
        execute=execute,
        idempotent=True,
    )
