"""run_agent(ai-chat) 事件 → Code UI(useCodingPipeline)认的 coding.* 事件。

Phase 1':Code 改由 run_agent 驱动,但前端仍消费 coding.* 事件词汇,
这里做一层翻译,保证前端零改动。见
docs/superpowers/plans/2026-06-24-unified-agent-engine-phase1-retire-coding-pipeline.md
"""
from __future__ import annotations

# run_agent 工具名(MCP/workspace 复数命名)→ Code UI 工具卡 action(coding 单数命名)
TOOL_NAME_TO_CODING = {
    "write_workspace_files": "write_file",
    "edit_workspace_files": "edit_file",
    "read_workspace_file": "read_file",
    "glob_workspace": "glob_files",
    "grep_workspace": "grep_search",
    "run_workspace_command": "run_command",
}

# Code UI 无对应卡的事件:thinking/run_started 是 meta;tool_call_delta 是逐 token 参数流;
# assistant_thinking_lock 是 ai-chat 专属锁;artifact_created 由面板自重读磁盘覆盖。
_NOISE = {
    "thinking", "run_started", "tool_call_delta",
    "assistant_thinking_lock", "artifact_created",
}


def map_runagent_event(event: str, data: dict) -> list[dict]:
    """把单个 run_agent 事件翻成 0~N 条 Code UI 事件。"""
    if event in _NOISE:
        return []
    if event == "assistant_delta":
        return [{"type": "agent_thinking_delta", "text": data.get("text", "")}]
    if event == "assistant_message":
        return [{"type": "content", "content": data.get("content", "")}]
    if event == "tool_call_start":
        name = data.get("tool_name", "")
        return [{
            "type": "agent_tool",
            "action": TOOL_NAME_TO_CODING.get(name, name),
            "id": data.get("id"),
            "args": data.get("args"),
            "status": "running",
        }]
    if event == "tool_call_end":
        name = data.get("tool_name", "")
        return [{
            "type": "agent_result",
            "id": data.get("id"),
            "action": TOOL_NAME_TO_CODING.get(name, name),
            "status": data.get("status"),
            "result": data.get("result_text"),
        }]
    if event == "ask_user":
        return [{
            "type": "clarify",
            "question": data.get("question"),
            "options": data.get("options"),
        }]
    if event == "done":
        return [{"type": "agent_done"}, {"type": "done", "ok": data.get("ok", True)}]
    if event == "error":
        return [{"type": "error", "error": data.get("error", "")}]
    return []
