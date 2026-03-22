"""
VibeCodingAgent - 基于 Claude Agent SDK 的 aPaaS 组件开发 Agent

替代原有的一次性代码生成模式，实现：
  用户需求 → Agent 循环：读文件 → 写代码 → 跑命令 → 看报错 → 改代码 → 直到成功
"""

import json
import logging
from pathlib import Path
from typing import AsyncIterator

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
    StreamEvent,
    PermissionResultAllow,
)
from app.coding.workspace import WorkspaceManager, WORKSPACE_ROOT

logger = logging.getLogger(__name__)


# Tool display names for frontend
TOOL_ICONS = {
    "Read": "\U0001f4c2 Read",
    "Write": "\U0001f4dd Write",
    "Edit": "\u270f\ufe0f Edit",
    "Bash": "\u26a1 Bash",
    "Glob": "\U0001f50d Glob",
    "Grep": "\U0001f50e Grep",
    "MultiEdit": "\u270f\ufe0f MultiEdit",
}


def _truncate(s: str, maxlen: int = 300) -> str:
    """Truncate a string to maxlen characters."""
    if len(s) <= maxlen:
        return s
    return s[:maxlen] + "..."


class VibeCodingAgent:
    """
    Wraps the Claude Agent SDK to perform autonomous coding within an aPaaS workspace.
    Agent runs in a background asyncio.Task. Events are pushed to an asyncio.Queue.
    SSE consumers read from the queue — if SSE disconnects, the agent keeps running.
    """

    # 全局注册表：{ws_id: {"task": Task, "queue": Queue, "events": list, "done": bool}}
    _running_agents: dict = {}

    def __init__(self, ws_id: str, system_prompt: str | None = None):
        self.ws_id = ws_id
        self.ws_path = WORKSPACE_ROOT / ws_id
        self.ws_mgr = WorkspaceManager()
        self._system_prompt = system_prompt

    async def start(
        self,
        requirement: str,
        conversation_summary: str = "",
        max_turns: int = 30,
        model: str | None = None,
    ) -> str:
        """
        Start the agent as a background task. Returns immediately.
        Use stream_events() to consume events via SSE.
        If agent is already running for this workspace, returns existing task info.
        """
        import asyncio

        if self.ws_id in self._running_agents:
            info = self._running_agents[self.ws_id]
            if not info["done"]:
                logger.info(f"Agent already running for {self.ws_id}")
                return "already_running"

        # 创建事件队列
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        events_history: list = []

        # 启动后台任务
        task = asyncio.create_task(
            self._run_background(requirement, conversation_summary, max_turns, model, event_queue, events_history)
        )

        VibeCodingAgent._running_agents[self.ws_id] = {
            "task": task,
            "queue": event_queue,
            "events": events_history,
            "done": False,
        }

        return "started"

    async def stream_events(self) -> AsyncIterator[dict]:
        """
        Consume events from a running agent. Can be called multiple times
        (e.g., after SSE reconnect) — missed events are replayed from history.
        """
        import asyncio

        if self.ws_id not in self._running_agents:
            yield {"type": "agent_error", "message": "No agent running for this workspace"}
            return

        info = self._running_agents[self.ws_id]
        queue = info["queue"]
        events = info["events"]

        # 先回放已有的事件历史（处理重连场景）
        for event in events:
            yield event

        # 然后从队列实时消费新事件
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield event
                if event.get("type") in ("agent_done", "agent_error"):
                    break
            except asyncio.TimeoutError:
                # 检查 Agent 是否已完成
                if info["done"]:
                    break
                # 发心跳保持 SSE 连接
                yield {"type": "heartbeat"}

    async def _run_background(
        self,
        requirement: str,
        conversation_summary: str,
        max_turns: int,
        model: str | None,
        event_queue,
        events_history: list,
    ):
        """Background task that runs the agent loop and pushes events to queue."""
        prompt = self._build_prompt(requirement, conversation_summary)
        agent_env = self._load_agent_env()
        agent_model = model or agent_env.get("ANTHROPIC_MODEL") or None

        options = ClaudeAgentOptions(
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "MultiEdit"],
            system_prompt=self._system_prompt,
            permission_mode="bypassPermissions",
            max_turns=max_turns,
            cwd=str(self.ws_path),
            model=agent_model,
            env=agent_env if agent_env else {},
        )

        try:
            async for message in query(prompt=prompt, options=options):
                converted = self._convert_message(message)
                for event in converted:
                    events_history.append(event)
                    try:
                        event_queue.put_nowait(event)
                    except Exception:
                        pass  # Queue full, skip (history still has it)
        except Exception as e:
            logger.exception("VibeCodingAgent background error")
            error_event = {"type": "agent_error", "message": str(e)}
            events_history.append(error_event)
            try:
                event_queue.put_nowait(error_event)
            except Exception:
                pass
        finally:
            if self.ws_id in self._running_agents:
                self._running_agents[self.ws_id]["done"] = True

    # Legacy sync run (kept for backward compatibility)
    async def run(
        self,
        requirement: str,
        conversation_summary: str = "",
        max_turns: int = 30,
        model: str | None = None,
    ) -> AsyncIterator[dict]:
        """Start agent and stream events. Agent survives SSE disconnect."""
        status = await self.start(requirement, conversation_summary, max_turns, model)
        if status == "already_running":
            yield {"type": "agent_thinking", "content": "Agent 正在运行中，重新连接事件流..."}

        async for event in self.stream_events():
            if event.get("type") == "heartbeat":
                continue
            yield event

    @staticmethod
    def _load_agent_env() -> dict:
        """直接从 .env 文件读取 Agent 相关的环境变量，不受宿主 Claude Code 影响"""
        env = {}
        env_path = Path(__file__).parent.parent.parent / ".env"
        if not env_path.exists():
            return env
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key.startswith("ANTHROPIC_") or key == "API_TIMEOUT_MS":
                    env[key] = value
        except Exception:
            pass
        return env

    def _build_prompt(self, requirement: str, conversation_summary: str) -> str:
        """Build the user prompt that tells the agent what to do."""
        info = self.ws_mgr.get_workspace_info(self.ws_id)
        parts = [
            f"## Task\n{requirement}",
            f"\n## Workspace Info",
            f"- Project name: {info.get('project_name', '')}",
            f"- Project type: {info.get('project_type', '')}",
            f"- Working directory: {self.ws_path}",
        ]

        if conversation_summary:
            parts.append(f"\n## Previous Conversation Summary\n{conversation_summary}")
        else:
            parts.append("\n## Previous Conversation Summary\nNone (first development session)")

        parts.append("""
## Workflow
1. Use Glob and Read to understand the existing scaffold structure
2. Write/modify component code (edit.vue, read.vue, ide.vue, setting.vue, etc.)
3. Run `npm run serve` to check compilation
4. If errors occur, read the error output and fix the code
5. Repeat until compilation succeeds, then report completion

## Important Constraints
- This is an aPaaS form component with 7 render scenes (edit/read/ide/list/print/search/search-ide)
- The scaffold files already exist. Do NOT modify package.json, vue.config.js, babel.config.js, or index.js infrastructure files (unless adding a new npm dependency to package.json)
- Vue 2.7 + Element UI (globally registered, do NOT import)
- Use FormWidgetMixin's formValue and widget capabilities
- setting.vue uses componentConfig prop + formEngine prop
""")
        return "\n".join(parts)

    def _convert_message(self, message) -> list[dict]:
        """Convert a single SDK message to a list of SSE event dicts."""
        events = []

        # --- AssistantMessage: Claude's thinking and tool calls ---
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    events.append({
                        "type": "agent_thinking",
                        "content": block.text,
                    })
                elif isinstance(block, ThinkingBlock) and block.thinking.strip():
                    # Extended thinking - could optionally surface this
                    events.append({
                        "type": "agent_thinking",
                        "content": block.thinking,
                    })
                elif isinstance(block, ToolUseBlock):
                    # Format the tool call info for display
                    tool_display = TOOL_ICONS.get(block.name, block.name)
                    input_preview = self._format_tool_input(block.name, block.input)
                    events.append({
                        "type": "agent_tool",
                        "tool": block.name,
                        "tool_display": tool_display,
                        "tool_use_id": block.id,
                        "input_preview": input_preview,
                    })
                elif isinstance(block, ToolResultBlock):
                    content_str = ""
                    if isinstance(block.content, str):
                        content_str = block.content
                    elif isinstance(block.content, list):
                        for item in block.content:
                            if isinstance(item, dict) and item.get("text"):
                                content_str += item["text"]
                    events.append({
                        "type": "agent_result",
                        "tool_use_id": block.tool_use_id,
                        "output_preview": _truncate(content_str),
                        "is_error": bool(block.is_error),
                    })

        # --- ResultMessage: Agent finished ---
        elif isinstance(message, ResultMessage):
            events.append({
                "type": "agent_done",
                "result": message.result or "",
                "session_id": message.session_id,
                "num_turns": message.num_turns,
                "cost_usd": message.total_cost_usd,
                "is_error": message.is_error,
            })

        # --- SystemMessage: init, progress etc ---
        elif isinstance(message, SystemMessage):
            if message.subtype == "init":
                events.append({
                    "type": "agent_thinking",
                    "content": "Agent session initialized...",
                })

        # --- StreamEvent: partial streaming events ---
        elif isinstance(message, StreamEvent):
            # StreamEvent contains raw event dicts from the CLI
            ev = message.event
            ev_type = ev.get("type", "")
            if ev_type == "assistant" and "content" in ev:
                # Partial assistant text
                for block in ev.get("content", []):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        events.append({
                            "type": "agent_thinking",
                            "content": block["text"],
                        })

        return events

    def _format_tool_input(self, tool_name: str, tool_input: dict) -> str:
        """Format tool input for display in the frontend."""
        if tool_name in ("Read", "Glob"):
            path = tool_input.get("file_path") or tool_input.get("pattern") or tool_input.get("path", "")
            return _truncate(str(path), 200)
        elif tool_name == "Write":
            path = tool_input.get("file_path", "")
            content = tool_input.get("content", "")
            lines = content.count("\n") + 1
            return f"{path} ({lines} lines)"
        elif tool_name == "Edit":
            path = tool_input.get("file_path", "")
            old = _truncate(tool_input.get("old_string", ""), 60)
            return f"{path}: {old} -> ..."
        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            return _truncate(cmd, 200)
        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", "")
            return f"/{pattern}/ in {path}"
        else:
            return _truncate(json.dumps(tool_input, ensure_ascii=False), 200)
