"""
VibeCodingAgent - OpenAI-compatible API agent for aPaaS component development

Replaces the Claude Agent SDK with direct httpx calls using OpenAI function-calling format.
Implements an autonomous agent loop:
  User requirement -> LLM -> tool calls -> execute tools -> feed results back -> repeat until done
"""

import json
import logging
from pathlib import Path
from typing import AsyncIterator

import httpx

from app.coding.workspace import WorkspaceManager, WORKSPACE_ROOT

logger = logging.getLogger(__name__)


# Tool display names for frontend
TOOL_ICONS = {
    "read_file": "\U0001f4c2 Read",
    "write_file": "\U0001f4dd Write",
    "edit_file": "\u270f\ufe0f Edit",
    "run_command": "\u26a1 Command",
    "glob_files": "\U0001f50d Glob",
    "grep_search": "\U0001f50e Grep",
}


def _truncate(s: str, maxlen: int = 300) -> str:
    """Truncate a string to maxlen characters."""
    if len(s) <= maxlen:
        return s
    return s[:maxlen] + "..."


class VibeCodingAgent:
    """
    Wraps an OpenAI-compatible API to perform autonomous coding within an aPaaS workspace.
    Agent runs in a background asyncio.Task. Events are pushed to an asyncio.Queue.
    SSE consumers read from the queue -- if SSE disconnects, the agent keeps running.
    """

    # Global registry: {ws_id: {"task": Task, "queue": Queue, "events": list, "done": bool}}
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

        # Create event queue
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        events_history: list = []

        # Start background task
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
        (e.g., after SSE reconnect) -- missed events are replayed from history.
        """
        import asyncio

        if self.ws_id not in self._running_agents:
            yield {"type": "agent_error", "message": "No agent running for this workspace"}
            return

        info = self._running_agents[self.ws_id]
        queue = info["queue"]
        events = info["events"]

        # Replay existing event history (handles reconnect scenario)
        for event in events:
            yield event

        # Then consume new events from queue in real-time
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield event
                if event.get("type") in ("agent_done", "agent_error"):
                    break
            except asyncio.TimeoutError:
                # Check if agent has finished
                if info["done"]:
                    break
                # Send heartbeat to keep SSE connection alive
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
        from app.coding.tools import TOOL_DEFINITIONS, execute_tool

        prompt = self._build_prompt(requirement, conversation_summary)

        # Load LLM config: try DB first, fall back to .env
        base_url, api_key, llm_model = await self._load_llm_config(model)

        messages = [{"role": "user", "content": prompt}]

        def _emit(event: dict):
            """Push event to queue and history."""
            events_history.append(event)
            try:
                event_queue.put_nowait(event)
            except Exception:
                pass

        turn = 0
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)
            ) as client:
                for turn in range(max_turns):
                    # Build request payload
                    payload = {
                        "model": llm_model,
                        "messages": [{"role": "system", "content": self._system_prompt}] + messages,
                        "tools": TOOL_DEFINITIONS,
                        "max_tokens": 8192,
                        "temperature": 0.2,
                        "stream": True,
                    }

                    # ── Streaming LLM call ──
                    full_content = ""
                    tool_calls_map: dict = {}  # index -> {id, name, arguments}

                    async with client.stream(
                        "POST",
                        f"{base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    ) as stream:
                        async for line in stream.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            delta = chunk.get("choices", [{}])[0].get("delta", {})

                            # ── Streaming text content (thinking) ──
                            if delta.get("content"):
                                text = delta["content"]
                                full_content += text
                                _emit({"type": "agent_thinking_delta", "content": text})

                            # ── Streaming tool calls ──
                            if delta.get("tool_calls"):
                                for tc_delta in delta["tool_calls"]:
                                    idx = tc_delta.get("index", 0)
                                    if idx not in tool_calls_map:
                                        tool_calls_map[idx] = {
                                            "id": tc_delta.get("id", ""),
                                            "name": "",
                                            "arguments": "",
                                        }
                                    entry = tool_calls_map[idx]
                                    if tc_delta.get("id"):
                                        entry["id"] = tc_delta["id"]
                                    func = tc_delta.get("function", {})
                                    if func.get("name"):
                                        entry["name"] = func["name"]
                                    if func.get("arguments"):
                                        entry["arguments"] += func["arguments"]

                    # ── End of thinking: emit full thinking block ──
                    if full_content:
                        _emit({"type": "agent_thinking", "content": full_content})

                    # ── Reconstruct assistant message for conversation history ──
                    assistant_msg: dict = {"role": "assistant", "content": full_content or None}
                    assembled_tool_calls = []
                    for idx in sorted(tool_calls_map.keys()):
                        entry = tool_calls_map[idx]
                        assembled_tool_calls.append({
                            "id": entry["id"],
                            "type": "function",
                            "function": {"name": entry["name"], "arguments": entry["arguments"]},
                        })
                    if assembled_tool_calls:
                        assistant_msg["tool_calls"] = assembled_tool_calls
                    messages.append(assistant_msg)

                    # ── If no tool_calls, agent is done ──
                    if not assembled_tool_calls:
                        break

                    # ── Execute each tool call ──
                    for tc in assembled_tool_calls:
                        func_name = tc["function"]["name"]
                        raw_args = tc["function"]["arguments"]
                        try:
                            func_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            func_args = {}

                        # Emit tool event
                        _emit({
                            "type": "agent_tool",
                            "tool": func_name,
                            "tool_display": TOOL_ICONS.get(func_name, func_name),
                            "input_preview": self._format_tool_input(func_name, func_args),
                        })

                        # Execute tool
                        result = await execute_tool(func_name, func_args, self.ws_path)

                        # Emit result event
                        _emit({
                            "type": "agent_result",
                            "tool": func_name,
                            "tool_display": TOOL_ICONS.get(func_name, func_name),
                            "output_preview": _truncate(result, 500) if result else "(empty)",
                        })

                        # Add tool result to messages
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result,
                        })

            # Done event
            _emit({
                "type": "agent_done",
                "result": "completed",
                "num_turns": min(turn + 1, max_turns),
                "is_error": False,
            })

        except Exception as e:
            logger.exception("VibeCodingAgent background error")
            _emit({"type": "agent_error", "message": str(e)})
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
        """Read agent-related env vars directly from .env file."""
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

    async def _load_llm_config(self, model_override=None):
        """Load LLM config from DB (preferred) or .env (fallback)."""
        # Try DB first
        try:
            from app.database import AsyncSessionLocal
            from app.routes.llm_configs import get_llm_config_for_purpose

            async with AsyncSessionLocal() as db:
                # Use tenant_id=1 as default (workspace doesn't carry tenant context)
                config = await get_llm_config_for_purpose(db, tenant_id=1, purpose="coding")
                if config:
                    from app.crypto import decrypt_password

                    return (
                        config.base_url,
                        decrypt_password(config.api_key_enc),
                        model_override or config.model,
                    )
        except Exception:
            pass

        # Fallback to .env
        env = self._load_agent_env()
        base_url = env.get("ANTHROPIC_BASE_URL", "https://api.minimax.chat/v1")
        # Convert Anthropic URL format to OpenAI-compatible
        if "/anthropic" in base_url:
            base_url = base_url.replace("/anthropic", "/v1")
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        api_key = env.get("ANTHROPIC_API_KEY", "")
        llm_model = model_override or env.get("ANTHROPIC_MODEL", "MiniMax-M2.7")
        return base_url, api_key, llm_model

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
1. Use glob_files and read_file to understand the existing scaffold structure
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

    def _format_tool_input(self, tool_name: str, tool_input: dict) -> str:
        """Format tool input for display in the frontend."""
        if tool_name == "read_file":
            return _truncate(str(tool_input.get("file_path", "")), 200)
        elif tool_name == "glob_files":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", "")
            return _truncate(f"{pattern}" + (f" in {path}" if path else ""), 200)
        elif tool_name == "write_file":
            path = tool_input.get("file_path", "")
            content = tool_input.get("content", "")
            lines = content.count("\n") + 1
            return f"{path} ({lines} lines)"
        elif tool_name == "edit_file":
            path = tool_input.get("file_path", "")
            old = _truncate(tool_input.get("old_string", ""), 60)
            return f"{path}: {old} -> ..."
        elif tool_name == "run_command":
            cmd = tool_input.get("command", "")
            return _truncate(cmd, 200)
        elif tool_name == "grep_search":
            pattern = tool_input.get("pattern", "")
            path = tool_input.get("path", "")
            return f"/{pattern}/" + (f" in {path}" if path else "")
        else:
            return _truncate(json.dumps(tool_input, ensure_ascii=False), 200)
