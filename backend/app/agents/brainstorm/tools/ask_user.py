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

def _validate_options(raw: Any) -> tuple[list[dict[str, str]] | None, str | None]:
    """校验 ask_user 的 options 参数。

    合法：`None` / `[]` / `[{"value": str, "label": str}, ...]`
    非法（观察到的 LLM 错误）：`[[{...}, {...}]]`（多裹一层数组）、dict、字符串、
    item 缺 value/label、value/label 非 string。

    返回 `(normalized, None)` 表示通过；`(None, error_msg)` 表示拒绝，error_msg
    会作为 tool_result content 回给 LLM，LLM 看到错误后会按正确格式重试。
    """
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, (
            f"options 必须是数组，当前是 {type(raw).__name__}。"
            '正确格式：[{"value": "xxx", "label": "展示文案"}, ...]'
        )
    normalized: list[dict[str, str]] = []
    for idx, item in enumerate(raw):
        if isinstance(item, list):
            return None, (
                f"options[{idx}] 是数组而不是对象（LLM 常见错误：多裹了一层 [...]）。"
                '正确格式是一维数组：[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]，'
                '不要写成 [[{"value": "a", ...}, {"value": "b", ...}]]。'
            )
        if not isinstance(item, dict):
            return None, (
                f"options[{idx}] 必须是对象，当前是 {type(item).__name__}。"
                '正确格式：{"value": "xxx", "label": "展示文案"}'
            )
        value = item.get("value")
        label = item.get("label")
        if not isinstance(value, str) or not value:
            return None, f'options[{idx}] 缺少非空字符串字段 "value"'
        if not isinstance(label, str) or not label:
            return None, f'options[{idx}] 缺少非空字符串字段 "label"'
        normalized.append({"value": value, "label": label})
    return normalized, None


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
        "target_path": {
            "type": "string",
            "description": (
                "本问题指向的 Spec 字段路径（dot+[index] 语法，如 "
                "spec.config_properties[2].editor_props.multiple）。"
                "**iterate 模式必填**：会被校验是否在 allowed_paths 内，越界拒绝。"
                "fresh 模式可省略（无 scope 约束）。"
            ),
        },
    },
    "required": ["question", "priority"],
    "additionalProperties": False,
}


def _path_in_scope(target: str, allowed: list[str]) -> bool:
    """target 是否落在 allowed 内（精确匹配 OR 是 allowed 中某个的子路径）。

    例：allowed = ["spec.config_properties[2]"], target = "spec.config_properties[2].editor_props.multiple"
    → True（target 是 allowed 元素的下钻）。

    反之：allowed = ["spec.config_properties[2].ui_editor"], target = "spec.config_properties[2].default"
    → False（target 不是 allowed 任何元素的子路径）。
    """
    if not allowed:
        return True
    if target in allowed:
        return True
    for a in allowed:
        # 子路径匹配：target 以 "{a}." 或 "{a}[" 开头
        if target.startswith(a + ".") or target.startswith(a + "["):
            return True
    return False


def build_ask_user_tool(state: BrainstormState) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        question = str(args.get("question", "")).strip()
        if not question:
            return ToolResult(success=False, content="question 不能为空", error="empty_question")

        priority = int(args.get("priority", 2))
        options, opt_err = _validate_options(args.get("options"))
        if opt_err is not None:
            return ToolResult(
                success=False,
                content=f"options 参数格式错误：{opt_err}",
                error="invalid_options_format",
            )
        allow_free_text = bool(args.get("allow_free_text", True))
        p1_key = args.get("p1_key")
        context_note = args.get("context")
        target_path = str(args.get("target_path") or "").strip() or None

        # ── Iterate scope 强校验 ── #
        # state.allowed_paths 非空 = iterate 模式（_run_iterate_dispatch_task 注入）
        # 此时 target_path 必填且必须落在 allowed_paths 范围内。
        # 这是"AI 不要答非所问"的硬约束，比 prompt 喊话强。
        if state.allowed_paths:
            if not target_path:
                return ToolResult(
                    success=False,
                    content=(
                        "iterate 模式下 ask_user 必须填 target_path 字段（指向你想问的 Spec 路径）。"
                        f"当前允许范围：{state.allowed_paths}。"
                        "如果你想问的字段不在这个范围里，说明你越界了——"
                        "用户的修正只针对这些字段，其它字段已在上一版 Spec 里明确，**不要重问**。"
                    ),
                    error="missing_target_path",
                )
            if not _path_in_scope(target_path, state.allowed_paths):
                return ToolResult(
                    success=False,
                    content=(
                        f"target_path={target_path!r} 越界了。本次 refine 的允许范围是："
                        f"{state.allowed_paths}。"
                        "你只能就这些字段反问。其它字段已在上一版 Spec 明确，"
                        "**严禁**借问「补充确认」的名义重新讨论已确定的事。"
                        "请重新选择 target_path（或如果你不需要反问，直接 emit_spec）。"
                    ),
                    error="target_path_out_of_scope",
                )

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
            "target_path": target_path,
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
