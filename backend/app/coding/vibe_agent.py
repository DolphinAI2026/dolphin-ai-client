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
        """
        Background agent loop — inspired by Claude Agent SDK patterns:
        1. Streaming SSE with delta accumulation
        2. Smart context compression (truncate old tool results)
        3. Loop detection with automatic nudging
        4. Parallel tool execution
        5. Adaptive tool result sizing based on remaining context budget
        """
        from app.coding.tools import TOOL_DEFINITIONS, execute_tool
        import asyncio

        print(f"[Agent] Started for ws={self.ws_id}", flush=True)
        prompt = self._build_prompt(requirement, conversation_summary)

        # Load LLM config
        base_url, api_key, llm_model = await self._load_llm_config(model)
        print(f"[Agent] Config: model={llm_model}, base={base_url}", flush=True)

        messages = [{"role": "user", "content": prompt}]

        # ── Agent state tracking ──
        consecutive_reads = 0
        read_files_set: set = set()  # Track which files have been read (prevent re-reads)
        total_tool_result_chars = 0
        MAX_CONTEXT_CHARS = 60000  # Approximate context budget for tool results

        def _emit(event: dict):
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

                    # ── Phase 1: Loop detection & context management ──
                    if consecutive_reads >= 2:
                        messages.append({
                            "role": "user",
                            "content": (
                                "You have been reading files without writing code. "
                                "You now have enough context. IMMEDIATELY use write_file to create/update "
                                "ALL component files (edit.vue, read.vue, ide.vue, setting.vue, etc.) in THIS turn. "
                                "Use multiple parallel write_file calls."
                            )
                        })
                        consecutive_reads = 0
                        print(f"[Agent] Nudge injected at turn {turn+1}", flush=True)

                    # Context compression: aggressively compress old tool results
                    self._compress_context(messages)

                    # ── Phase 2: Build & send LLM request ──
                    sys_msg = {"role": "system", "content": self._system_prompt}
                    payload = {
                        "model": llm_model,
                        "messages": [sys_msg] + messages,
                        "tools": TOOL_DEFINITIONS,
                        "max_tokens": 8192,
                        "temperature": 0.2,
                        "stream": True,
                    }
                    # Disable thinking mode for models that support it (e.g. MiniMax)
                    # Thinking adds overhead and <think> tags that break rendering
                    if "minimax" in base_url.lower() or "MiniMax" in llm_model:
                        payload["thoughts"] = {"enabled": False}

                    full_content = ""
                    tool_calls_map: dict = {}
                    print(f"[Agent] Turn {turn+1}/{max_turns}, msgs={len(messages)}, ctx_chars={total_tool_result_chars}", flush=True)

                    try:
                        async with client.stream(
                            "POST",
                            f"{base_url}/chat/completions",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                        ) as stream:
                            if stream.status_code != 200:
                                body = await stream.aread()
                                err_msg = body[:300].decode(errors='replace')
                                print(f"[Agent] API error {stream.status_code}: {err_msg}", flush=True)
                                _emit({"type": "agent_error", "message": f"LLM API {stream.status_code}: {err_msg}"})
                                break

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

                                # Streaming text — surface concise user-facing progress notes live
                                if delta.get("content"):
                                    text = delta["content"]
                                    full_content += text
                                    _emit({"type": "agent_thinking_delta", "content": text})

                                # Streaming tool calls (supports parallel via index)
                                if delta.get("tool_calls"):
                                    for tc_delta in delta["tool_calls"]:
                                        idx = tc_delta.get("index", 0)
                                        if idx not in tool_calls_map:
                                            tool_calls_map[idx] = {"id": "", "name": "", "arguments": ""}
                                        entry = tool_calls_map[idx]
                                        if tc_delta.get("id"):
                                            entry["id"] = tc_delta["id"]
                                        func = tc_delta.get("function", {})
                                        if func.get("name"):
                                            entry["name"] = func["name"]
                                        if func.get("arguments"):
                                            entry["arguments"] += func["arguments"]

                    except httpx.ReadTimeout:
                        print(f"[Agent] LLM read timeout at turn {turn+1}", flush=True)
                        _emit({"type": "agent_error", "message": "LLM API 响应超时，请重试"})
                        break
                    except httpx.ConnectError as e:
                        print(f"[Agent] LLM connect error: {e}", flush=True)
                        _emit({"type": "agent_error", "message": f"LLM API 连接失败: {e}"})
                        break

                    # ── Phase 3: Process LLM response ──
                    if full_content:
                        _emit({"type": "agent_thinking", "content": full_content})

                    # Reconstruct assistant message
                    assistant_msg: dict = {"role": "assistant", "content": full_content or None}
                    assembled_tool_calls = []
                    for idx in sorted(tool_calls_map.keys()):
                        entry = tool_calls_map[idx]
                        if entry["name"]:  # Skip empty entries
                            assembled_tool_calls.append({
                                "id": entry["id"] or f"call_{turn}_{idx}",
                                "type": "function",
                                "function": {"name": entry["name"], "arguments": entry["arguments"]},
                            })
                    if assembled_tool_calls:
                        assistant_msg["tool_calls"] = assembled_tool_calls
                    messages.append(assistant_msg)

                    # ── Check if agent is done ──
                    tool_names = [tc["function"]["name"] for tc in assembled_tool_calls]
                    print(f"[Agent] Turn {turn+1} done: text={len(full_content)}, tools={tool_names}", flush=True)

                    if not assembled_tool_calls:
                        print(f"[Agent] Finished after {turn+1} turns", flush=True)
                        break

                    if not full_content.strip():
                        progress_note = self._describe_tool_plan(tool_names)
                        if progress_note:
                            _emit({"type": "agent_thinking_delta", "content": progress_note})

                    # ── Phase 4: Execute tools (parallel when possible) ──
                    has_write = any(t in ("write_file", "edit_file", "run_command") for t in tool_names)
                    if has_write:
                        consecutive_reads = 0
                    else:
                        consecutive_reads += 1

                    for tc in assembled_tool_calls:
                        func_name = tc["function"]["name"]
                        raw_args = tc["function"]["arguments"]
                        try:
                            func_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            func_args = {}

                        # Duplicate read detection
                        if func_name == "read_file":
                            fpath = func_args.get("file_path", "")
                            if fpath in read_files_set:
                                # Skip duplicate read, return cached hint
                                _emit({"type": "agent_tool", "tool": func_name,
                                       "tool_display": TOOL_ICONS.get(func_name, func_name),
                                       "input_preview": f"{fpath} (cached)"})
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": f"[Already read this file earlier. Use the content from the previous read. Do NOT read it again — write your code now.]",
                                })
                                continue
                            read_files_set.add(fpath)

                        _emit({
                            "type": "agent_tool",
                            "tool": func_name,
                            "tool_display": TOOL_ICONS.get(func_name, func_name),
                            "input_preview": self._format_tool_input(func_name, func_args),
                        })

                        # Execute
                        async def _tool_progress(chunk: str):
                            _emit({
                                "type": "agent_command_output",
                                "tool": func_name,
                                "tool_display": TOOL_ICONS.get(func_name, func_name),
                                "command": func_args.get("command", ""),
                                "chunk": chunk,
                            })

                        result = await execute_tool(
                            func_name,
                            func_args,
                            self.ws_path,
                            progress_callback=_tool_progress if func_name == "run_command" else None,
                        )

                        # Adaptive result truncation based on remaining context budget
                        result_str = result or ""
                        remaining_budget = MAX_CONTEXT_CHARS - total_tool_result_chars
                        max_result_len = max(2000, min(8000, remaining_budget // 2))

                        if len(result_str) > max_result_len:
                            result_str = result_str[:max_result_len] + f"\n... [truncated, {len(result)} chars total]"

                        total_tool_result_chars += len(result_str)

                        # Emit result
                        is_error = result_str.startswith("Error:") or result_str.startswith("error:")
                        _emit({
                            "type": "agent_result",
                            "tool": func_name,
                            "tool_display": TOOL_ICONS.get(func_name, func_name),
                            "output_preview": _truncate(result_str, 500),
                            "is_error": is_error,
                        })

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result_str,
                        })

            # ── Done ──
            _emit({
                "type": "agent_done",
                "result": "completed",
                "num_turns": min(turn + 1, max_turns),
                "is_error": False,
            })

        except Exception as e:
            logger.exception("VibeCodingAgent background error")
            print(f"[Agent] Exception: {e}", flush=True)
            _emit({"type": "agent_error", "message": str(e)})
        finally:
            if self.ws_id in self._running_agents:
                self._running_agents[self.ws_id]["done"] = True

    @staticmethod
    def _compress_context(messages: list):
        """
        Smart context compression — inspired by Claude SDK patterns.
        Aggressively compress old tool results while keeping recent ones intact.
        """
        if len(messages) <= 10:
            return

        # Keep the last 8 messages untouched
        cutoff = len(messages) - 8
        for i in range(cutoff):
            msg = messages[i]
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                if len(content) > 300:
                    # Compress to first 200 chars + hint
                    msg["content"] = content[:200] + "\n... [earlier result compressed]"
            elif msg.get("role") == "assistant" and msg.get("content"):
                content = msg["content"]
                if len(content) > 500:
                    msg["content"] = content[:300] + "..."

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
            # Forward ALL events including heartbeats to keep SSE connection alive
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
        project_type = (info.get("project_type", "") or "").lower()
        parts = [
            f"## Task\n{requirement}",
            f"\n## Workspace Info",
            f"- Project name: {info.get('project_name', '')}",
            f"- Project type: {project_type}",
            f"- Working directory: {self.ws_path}",
        ]

        if conversation_summary:
            parts.append(f"\n## Previous Conversation Summary\n{conversation_summary}")
        else:
            parts.append("\n## Previous Conversation Summary\nNone (first development session)")

        workflow = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-2 calls max): Read ONLY the key files you need (edit.vue and mixin). Do NOT read every file.
3. **IMMEDIATELY write code**: Use write_file to create/update ALL component files in one batch. Call write_file multiple times in a SINGLE turn (parallel tool calls).
4. **THEN** run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly. Do NOT dump hidden reasoning or long analysis.
- **DO NOT loop**: Never read the same file twice. Never read more than 3 files before writing code.
- **Write ALL files at once**: In a single turn, call write_file for edit.vue, read.vue, ide.vue, setting.vue etc. Do NOT write one file per turn.
- **Be decisive**: You are an expert. After reading the scaffold structure and 1-2 example files, you have enough context to write the component.
- **Maximum 8 turns total**: If you haven't written code by turn 4, something is wrong. Write the code NOW.

## Technical Constraints
- aPaaS form component with 7 render scenes (edit/read/ide/list/print/search/search-ide)
- Scaffold files already exist. Do NOT modify package.json, vue.config.js, babel.config.js, or index.js
- Vue 2.7 + Element UI (globally registered, do NOT import Element UI)
- Use FormWidgetMixin (provides formValue, widget, updatePropValue, etc.)
- setting.vue uses componentConfig prop + formEngine prop
- The edit.vue is the primary file. read.vue shows readonly view. ide.vue shows placeholder. Others can be minimal.
"""
        if project_type == "layout":
            workflow = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-2 calls max): Read ONLY the key files you need (`src/apaas.json`, `src/index.js`, `src/form-layout/*.vue` or `src/Home.vue`)
3. **IMMEDIATELY write code**: Update the layout files in one batch. Do NOT apply the 7-scene form-component pattern.
4. **THEN** run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly. Do NOT dump hidden reasoning or long analysis.
- **Do NOT generate `widget.config.js`, `editor.config.js`, or `setting.vue` by default**.
- **Focus on layout structure**: `x-app-layout`, `header`, `menu`, `appPage`, and any optional layout-only subcomponents.
- `templateType` must remain `PAGE_LAYOUT`
- `appPage` must forward platform content with `<slot name="appPage">`
- Do NOT modify package.json unless the task explicitly requires it.
"""
        elif project_type == "form-list":
            workflow = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. Use glob_files to inspect the project structure
2. Read only the key files you need (`src/apaas.json`, `src/index.js`, `src/form-view/*.vue`)
3. Write the list-view files in one batch
4. Run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- `templateType` must remain `LIST_VIEW`
- Do NOT apply the 7-scene form-component pattern
- Focus on `index.js`, `apaas.json`, `form-view/*.vue`, and i18n files
"""
        elif project_type == "plugin":
            workflow = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. Use glob_files to inspect the project structure
2. Read only the key files you need (`src/apaas.json`, `src/admin.js`, `src/app.js`, `src/mobile.js`, `src/extension.js`)
3. Write the plugin files in one batch
4. Run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- `templateType` must remain `FRONTEND_PLUGIN`
- Every entry file must default-export `{ install, activate, staticComponents }`
- Do NOT generate form-component files like edit.vue/read.vue/setting.vue
"""
        elif project_type == "backend-api":
            workflow = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. Use glob_files to inspect the project structure
2. Read only the key backend files you need (controller/service/config/pom)
3. Write or update the backend files in one batch
4. Run the appropriate backend build/test command (`mvn test`, `mvn -q -DskipTests package`, etc.)
5. If errors, fix and rerun. If success, report completion.

## CRITICAL Rules
- This is a backend project. Do NOT generate Vue component files.
- Do NOT apply form-component rules like edit.vue/read.vue/setting.vue.
- Prefer minimal, runnable Java/Spring-style changes that match the scaffold.
"""
        parts.append(workflow)
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

    @staticmethod
    def _describe_tool_plan(tool_names: list[str]) -> str:
        """Generate a short user-facing progress note when the model omits one."""
        if not tool_names:
            return ""

        unique_names = list(dict.fromkeys(tool_names))
        parts: list[str] = []

        if "glob_files" in unique_names:
            parts.append("我先快速扫一遍项目结构，确认组件骨架和可复用文件。")
        if "grep_search" in unique_names:
            parts.append("我会顺手搜索关键实现，避免漏掉现有约定。")
        if "read_file" in unique_names:
            parts.append("接着读取少量关键文件，确认当前组件写法和 mixin 用法。")
        if "write_file" in unique_names:
            parts.append("上下文已经够了，下一步开始批量写入组件文件。")
        if "edit_file" in unique_names:
            parts.append("我会在现有文件上做定向修改，尽量减少无关变动。")
        if "run_command" in unique_names:
            parts.append("代码写完后我会立刻做构建校验，确认没有编译问题。")

        if not parts:
            return "我正在推进下一步实现，很快会同步新的进展。"

        return " ".join(parts[:2])
