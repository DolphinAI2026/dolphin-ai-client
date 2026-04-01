"""Harness Core — SSE 兼容适配器

将内部 harness 事件翻译成现有前端能识别的 SSE 格式，
保证 Phase 1 迁移时前端不需要改动。
"""
from app.harness.events import (
    THREAD_STARTED, THREAD_COMPLETED,
    TURN_STARTED, TURN_COMPLETED, TURN_FAILED,
    ITEM_STARTED, ITEM_DELTA, ITEM_COMPLETED,
    APPROVAL_REQUESTED, APPROVAL_RESOLVED,
)


class GenericSSEAdapter:
    """通用适配器 — 用于 builder / requirements / platform mode。"""

    def translate(self, event: dict) -> dict:
        et = event.get("event_type", "")
        data = event.get("data", {})

        if et == TURN_STARTED:
            return {"type": "status", "content": "开始处理..."}
        elif et == ITEM_DELTA:
            kind = data.get("kind", "")
            if kind == "content":
                return {"type": "content", "content": data.get("text", "")}
            elif kind == "thinking":
                return {"type": "thinking", "content": data.get("text", "")}
            else:
                return {"type": "status", "content": data.get("text", "")}
        elif et == ITEM_STARTED:
            kind = data.get("kind", "")
            if kind == "tool_call":
                return {"type": "tool", "tool": data.get("tool", ""), "content": data.get("preview", "")}
            return {"type": "status", "content": f"执行中: {kind}"}
        elif et == ITEM_COMPLETED:
            return {"type": "status", "content": ""}  # 静默
        elif et == TURN_COMPLETED:
            return {"type": "done", "data": data}
        elif et == TURN_FAILED:
            return {"type": "error", "message": data.get("error", "执行失败")}
        elif et == APPROVAL_REQUESTED:
            return {"type": "approval_request", "data": data}
        elif et == APPROVAL_RESOLVED:
            return {"type": "approval_resolved", "data": data}
        else:
            # 透传未知事件
            return {"type": "harness_event", "event_type": et, "data": data}


class CodingSSEAdapter:
    """编码模式适配器 — 翻译为 CodingPage 能识别的事件格式。

    CodingProfile 现在运行完整 pipeline（scene detect → workspace → agent → IDE URL），
    pipeline 事件通过 EventBus 发出时带有 kind=system/content/thinking/tool_call/tool_result。
    此适配器将 harness 事件翻译回前端 CodingPage 已有的事件格式。
    """

    def translate(self, event: dict) -> dict:
        et = event.get("event_type", "")
        data = event.get("data", {})

        if et == TURN_STARTED:
            # pipeline 会自己发 step 事件，不需要额外 generate running
            return {}
        elif et == ITEM_DELTA:
            kind = data.get("kind", "")
            if kind == "thinking":
                return {"type": "agent_thinking_delta", "content": data.get("text", "")}
            elif kind == "content":
                return {"type": "content", "content": data.get("text", "")}
            elif kind == "system":
                # Pipeline step/scene_detected 等系统事件 — 透传给前端
                # data 内已包含完整的 pipeline 事件（type/step/status/data 等）
                passthrough = {k: v for k, v in data.items() if k != "kind"}
                return passthrough if passthrough.get("type") else {}
            return {}
        elif et == ITEM_STARTED:
            kind = data.get("kind", "")
            if kind == "tool_call":
                return {
                    "type": "agent_tool",
                    "tool": data.get("tool", ""),
                    "tool_display": data.get("tool_display", ""),
                    "input_preview": data.get("preview", ""),
                    "args": data.get("args", {}),
                }
            return {}
        elif et == ITEM_COMPLETED:
            kind = data.get("kind", "")
            if kind == "tool_result":
                return {
                    "type": "agent_result",
                    "tool": data.get("tool", ""),
                    "output_preview": data.get("output", ""),
                    "is_error": data.get("is_error", False),
                }
            elif kind == "system":
                # Pipeline done 事件 — 透传（包含 workspace_id, conversation_id, ide_url）
                passthrough = {k: v for k, v in data.items() if k != "kind"}
                return passthrough if passthrough.get("type") else {}
            return {}
        elif et == TURN_COMPLETED:
            # 如果 pipeline 已经发了 done 事件，这里不重复
            return {}
        elif et == TURN_FAILED:
            return {"type": "error", "message": data.get("error", "")}
        else:
            return {"type": "harness_event", "event_type": et, "data": data}


# ── 适配器注册表 ──

_ADAPTERS = {
    "generic": GenericSSEAdapter,
    "coding": CodingSSEAdapter,
}


def get_sse_adapter(name: str = "generic"):
    cls = _ADAPTERS.get(name, GenericSSEAdapter)
    return cls()
