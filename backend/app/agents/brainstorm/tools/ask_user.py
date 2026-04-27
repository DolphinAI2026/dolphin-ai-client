"""ask_user tool — 阻塞式反问。

行为：
1. 调用时发出 `brainstorm.ask_user` 事件（前端弹气泡）
2. ToolResult.should_pause=True → BaseAgent 执行完该 tool 后 pause
3. 用户回答后 orchestrator 调 agent.resume(answer=xxx)
   resume 机制由 P2.3 session suspend/resume 实装；在那之前，
   MVP 版本上由调用方（pipeline / 测试）通过 ctx.input["_ask_user_answer"]
   注入答案（同步模式）。

本 tool 只负责：
- 记录 ask_user_count（硬上限）
- 产出 event 给前端
- （若 ctx.input 内已塞好 mock 答案）立即返回答案 content，不 pause
"""
from __future__ import annotations

from typing import Any

from app.agents.brainstorm.config import MAX_ASK_USER_TURNS
from app.agents.brainstorm.state import BrainstormState
from app.agents.types import AgentContext, Tool, ToolResult

_ASK_USER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "中文问题文案，**一次只问一个**（硬要求）",
        },
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": "string", "description": "选项内部值"},
                    "label": {"type": "string", "description": "选项展示文案"},
                },
                "required": ["value", "label"],
                "additionalProperties": False,
            },
            "description": (
                "选项列表。**强烈推荐**每次都给，最后一项建议是『让我自己决定』。"
                "没选项时用户会被迫自己打字，体验差。"
            ),
        },
        "priority": {
            "type": "integer",
            "enum": [1, 2, 3],
            "description": "1=P1 关键 / 2=P2 重要 / 3=P3 锦上添花（P3 一般不该问）",
        },
        "p1_key": {
            "type": "string",
            "description": (
                "若此问题对应 state 里的某个 P1 key（如 form_value_shape），填进来，"
                "答案回来时会自动标记该 P1 为 answered"
            ),
        },
        "allow_free_text": {
            "type": "boolean",
            "description": "是否允许用户自由输入（默认 true）",
        },
        "context": {
            "type": "string",
            "description": "可选 — 给用户的背景说明（例：『用于决定 formValue 形态』）",
        },
    },
    "required": ["question", "priority"],
    "additionalProperties": False,
}


def build_ask_user_tool(state: BrainstormState) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        question = str(args.get("question", "")).strip()
        if not question:
            return ToolResult(success=False, content="question 不能为空", error="empty_question")

        priority = int(args.get("priority", 2))
        options = args.get("options") or []
        allow_free_text = bool(args.get("allow_free_text", True))
        p1_key = args.get("p1_key")
        context_note = args.get("context")

        # 计数 + 上限
        if state.ask_user_count >= MAX_ASK_USER_TURNS:
            return ToolResult(
                success=False,
                content=(
                    f"反问次数已达上限（{MAX_ASK_USER_TURNS}），不能再问。"
                    "请基于现有信息做默认假设、记 open_question，然后 emit_spec。"
                ),
                error="max_ask_user_exceeded",
            )
        state.ask_user_count += 1

        event_payload = {
            "question": question,
            "options": options,
            "priority": priority,
            "allow_free_text": allow_free_text,
            "context": context_note,
            "p1_key": p1_key,
            "ask_turn": state.ask_user_count,
            "max_ask_turns": MAX_ASK_USER_TURNS,
        }

        # —— MVP 同步注入模式 —— #
        # ctx.input 里若已塞 _ask_user_answer（测试或脚本场景），立即返回
        injected: dict[str, Any] | None = (ctx.input or {}).get("_ask_user_answer")
        if isinstance(injected, dict) and injected.get("question_matches", True):
            answer = str(injected.get("answer", "")).strip()
            if p1_key and answer:
                state.mark_p1_answered(p1_key, answer)
            content = f"[注入应答] 用户答：{answer or '（空）'}"
            return ToolResult(
                success=True,
                content=content,
                data={"answer": answer, "p1_key": p1_key},
                emit_event={"type": "brainstorm.ask_user", "data": event_payload},
            )

        # —— 正式模式：should_pause=True —— #
        return ToolResult(
            success=True,
            content=(
                "已发出反问（前端等待用户作答）。Agent 将挂起，"
                "用户作答后 orchestrator 会 resume 并把答案以 tool result 追加进来。"
            ),
            data={"pending": True, "p1_key": p1_key},
            emit_event={"type": "brainstorm.ask_user", "data": event_payload},
            should_pause=True,
        )

    return Tool(
        name="ask_user",
        description=(
            "向用户提一个问题并等待回答。遵守反问原则：一次一个问题、有选项用 options、"
            "按 P1 优先级、最多 5 轮。答案回来时若有 p1_key 会自动标记 P1 已回答。"
        ),
        parameters_schema=_ASK_USER_SCHEMA,
        execute=execute,
        requires_user=True,
        idempotent=False,
    )
