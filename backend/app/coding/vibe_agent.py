"""
VibeCodingAgent - OpenAI-compatible API agent for aPaaS component development

Replaces the Claude Agent SDK with direct httpx calls using OpenAI function-calling format.
Implements an autonomous agent loop:
  User requirement -> LLM -> tool calls -> execute tools -> feed results back -> repeat until done
"""

import json
import logging
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx

from app.coding.workspace import WorkspaceManager

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

    def __init__(self, ws_id: str, system_prompt: str | None = None, tenant_id: Optional[int] = None):
        self.ws_id = ws_id
        self.ws_mgr = WorkspaceManager()
        self.ws_path = self.ws_mgr.get_workspace_path(ws_id)
        self._system_prompt = system_prompt
        self.tenant_id = tenant_id

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
        from app.harness.tool_registry import ToolRegistry
        import asyncio

        tool_registry = ToolRegistry(profile="coding")

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
        final_result = "completed"
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
                        "tools": tool_registry.definitions,
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

                                choices = chunk.get("choices") or []
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})

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
                            # Ensure arguments is valid JSON string before adding to history
                            # Invalid JSON in tool_calls history will cause LLM API 400 errors
                            raw_args = entry["arguments"]
                            if isinstance(raw_args, str):
                                try:
                                    json.loads(raw_args)
                                    valid_args = raw_args
                                except json.JSONDecodeError:
                                    print(f"[Agent] Warning: invalid JSON arguments for tool '{entry['name']}', replacing with {{}}", flush=True)
                                    valid_args = "{}"
                            else:
                                valid_args = json.dumps(raw_args) if raw_args else "{}"
                            assembled_tool_calls.append({
                                "id": entry["id"] or f"call_{turn}_{idx}",
                                "type": "function",
                                "function": {"name": entry["name"], "arguments": valid_args},
                            })
                    if assembled_tool_calls:
                        assistant_msg["tool_calls"] = assembled_tool_calls
                    messages.append(assistant_msg)

                    # ── Check if agent is done ──
                    tool_names = [tc["function"]["name"] for tc in assembled_tool_calls]
                    print(f"[Agent] Turn {turn+1} done: text={len(full_content)}, tools={tool_names}", flush=True)

                    if not assembled_tool_calls:
                        if full_content.strip():
                            final_result = full_content.strip()
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

                        tool_event: dict = {
                            "type": "agent_tool",
                            "tool": func_name,
                            "tool_display": TOOL_ICONS.get(func_name, func_name),
                            "input_preview": self._format_tool_input(func_name, func_args),
                        }
                        # 对 write_file/edit_file 传递内容供前端展示代码
                        if func_name == "write_file":
                            tool_event["args"] = {
                                "file_path": func_args.get("file_path", ""),
                                "content": func_args.get("content", "")[:5000],
                            }
                        elif func_name == "edit_file":
                            tool_event["args"] = {
                                "file_path": func_args.get("file_path", ""),
                                "old_string": func_args.get("old_string", "")[:500],
                                "new_string": func_args.get("new_string", "")[:2000],
                            }
                        elif func_name == "run_command":
                            tool_event["args"] = {
                                "command": func_args.get("command", "")[:300],
                            }
                        elif func_name == "read_file":
                            tool_event["args"] = {
                                "file_path": func_args.get("file_path", ""),
                            }
                        _emit(tool_event)

                        # Execute
                        async def _tool_progress(chunk: str):
                            _emit({
                                "type": "agent_command_output",
                                "tool": func_name,
                                "tool_display": TOOL_ICONS.get(func_name, func_name),
                                "command": func_args.get("command", ""),
                                "chunk": chunk,
                            })

                        result = await tool_registry.execute(
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
                "result": final_result,
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
        Smart context compression — inspired by Claude Code patterns.
        Uses ContextCompactor for tool result cleanup + aggressive old message compression.
        """
        from app.context_compact import ContextCompactor

        if len(messages) <= 10:
            return

        # 1. 用 ContextCompactor 清理旧 tool 结果
        compressed = ContextCompactor.clean_tool_results(messages, keep_recent=4)
        messages[:] = compressed

        # 2. 进一步压缩旧 assistant 消息
        cutoff = len(messages) - 8
        for i in range(cutoff):
            msg = messages[i]
            if msg.get("role") == "assistant" and msg.get("content"):
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
        """Load LLM config from DB (preferred) or .env (fallback).

        Uses the shared Harness LLM resolver for DB lookup, with coding-specific
        URL normalization and env fallback.
        """
        # Try DB via shared resolver
        if self.tenant_id:
            try:
                from app.database import AsyncSessionLocal
                from app.harness.llm_resolver import resolve_llm_config

                # 解析 llmcfg: 前缀
                selected_config_id = None
                model_override_str = (model_override or "").strip()
                if model_override_str.startswith("llmcfg:"):
                    try:
                        selected_config_id = int(model_override_str.split(":", 1)[1])
                    except ValueError:
                        pass

                async with AsyncSessionLocal() as db:
                    resolved = await resolve_llm_config(
                        db, self.tenant_id,
                        purpose="coding",
                        selected_config_id=selected_config_id,
                    )
                    if resolved:
                        base_url = self._normalize_base_url(resolved.base_url)
                        return base_url, resolved.api_key, resolved.model
            except Exception:
                pass

        # Fallback to .env — 优先使用 VIBE_AGENT_* 专用变量，再 fallback 到 ANTHROPIC_*
        env = self._load_agent_env()
        base_url = env.get("VIBE_AGENT_BASE_URL") or env.get("ANTHROPIC_BASE_URL", "https://api.minimax.chat/v1")
        base_url = self._normalize_base_url(base_url)
        api_key = env.get("VIBE_AGENT_API_KEY") or env.get("ANTHROPIC_API_KEY", "")
        llm_model = model_override or env.get("VIBE_AGENT_MODEL") or env.get("ANTHROPIC_MODEL", "MiniMax-M2.7")
        return base_url, api_key, llm_model

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """Normalize LLM base URL to OpenAI-compatible format (ending with /v1)."""
        base_url = (base_url or "").rstrip("/")
        if "/anthropic" in base_url:
            base_url = base_url.replace("/anthropic", "/v1")
        if base_url.endswith("/chat/completions"):
            base_url = base_url[: -len("/chat/completions")]
        if not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        return base_url

    def _build_prompt(self, requirement: str, conversation_summary: str) -> str:
        """Build the user prompt that tells the agent what to do."""
        info = self.ws_mgr.get_workspace_info(self.ws_id)
        project_type = (info.get("project_type", "") or "").lower()
        files = info.get("files", []) or []
        rule_files = [
            file_path for file_path in files
            if file_path.startswith(".cursor/rules/") and file_path.endswith(".mdc")
        ]
        parts = [
            f"## Task\n{requirement}",
            f"\n## Workspace Info",
            f"- Project name: {info.get('project_name', '')}",
            f"- Project type: {project_type}",
            f"- Working directory: {self.ws_path}",
        ]

        if rule_files:
            parts.append("\n## Workspace Rules")
            parts.extend(f"- Read and follow `{rule_file}` before writing code" for rule_file in rule_files)

        if conversation_summary:
            parts.append(f"\n## Previous Conversation Summary\n{conversation_summary}")
        else:
            parts.append("\n## Previous Conversation Summary\nNone (first development session)")

        workflow = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-3 calls max): If `.cursor/rules/*.mdc` exists, read those rule files first, then read ONLY the key implementation files you need (edit.vue and mixin). Do NOT read every file.
3. **IMMEDIATELY write code**: Use write_file to create/update ALL component files in one batch. Call write_file multiple times in a SINGLE turn (parallel tool calls).
4. **THEN** run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly. Do NOT dump hidden reasoning or long analysis.
- **DO NOT loop**: Never read the same file twice. Never read more than 3 files before writing code.
- **Write ALL files at once**: In a single turn, call write_file for edit.vue, read.vue, ide.vue, setting.vue etc. Do NOT write one file per turn.
- **When generating designer config**: update `src/form-component/form-editor/index.js` and `src/form-component-config/form-editor/index.js` in the same batch as `setting.vue` / `{name}.editor.config.json`.
- **Be decisive**: You are an expert. After reading the scaffold structure and 1-2 example files, you have enough context to write the component.
- **Maximum 8 turns total**: If you haven't written code by turn 4, something is wrong. Write the code NOW.
- **NEVER use `<el-dialog>` inside form widgets** — it breaks FormEngine component resolution and crashes the platform with `Cannot read properties of undefined (reading 'edit')`. Use `<el-popover :append-to-body="true">` instead for any preview/popup interaction.

## Technical Constraints
- aPaaS form component with 7 render scenes (edit/read/ide/list/print/search/search-ide)
- Scaffold files already exist. Do NOT modify vue.config.js or babel.config.js. Avoid unrelated index.js changes, but you may update `src/form-component/form-editor/index.js` and `src/form-component-config/form-editor/index.js` when adding `setting.vue` / `editor.config.json`.
- Vue 2.7 + Element UI (globally registered, do NOT import Element UI)
- **console.log is stripped in production — use `console.info` for ALL debug output in every mode.**
- **formEngine is NOT available in `beforeCreate()` — only access `this.formEngine` from `created()` or later.**

## Mixin Per Mode (always use default import, never named import)
- edit / ide / read → `import FormWidgetMixin from '@/mixin/form-widget.mixin'`
- list            → `import ListWidgetMixin from '@/mixin/list-widget.mixin'`
- print           → `import PrintWidgetMixin from '@/mixin/print-widget.mixin'`
- search          → `import SearchWidgetMixin from '@/mixin/search-widget.mixin'`
- search-ide      → `import SearchIdeWidgetMixin from '@/mixin/search-ide-widget.mixin'`
- editor (setting.vue) → `import EditorFormConfigMixin from '@/mixin/form-config.mixin'`

## Mode-specific Rules
- **List mode**: config = `this.componentConfig` (NOT `this.widget`); `this.formValue` is the concrete value prop directly (no propKey indexing); NO `<x-proxy-form-item>` wrapper.
- **Print mode**: NO `<el-xxx>` tags — Element UI does not render in print context; NO `<x-proxy-form-item>`; pure HTML/CSS only; use structure `div.print-item > div.print-item-title + div.print-item-value`; when `widget.isInTable` is true, omit the title.
- **Search mode**: NO `<x-proxy-form-item>`; submit via `this.$emit('change', [value])` — value MUST be wrapped in an array; do NOT use formValue setter.
- **Search-IDE mode**: NO `<x-proxy-form-item>`; all inputs `disabled`; only implement when Search mode is also implemented.
- **IDE mode**: all inputs must be `disabled` — IDE renders in the form designer canvas where user interaction is not allowed.
- **Edit mode**: check `this.widget.readOnly`; guard formValue undefined with fallback; never use both `v-model` and `@input` on the same element (causes infinite loop).

## BOF Type & formValue
- BOF_NUMBER caveat: `formValue` may arrive as a string from the platform. Always guard: `const n = Number(this.formValue); if (isNaN(n)) { /* fallback */ }`.

## widget.config.json Requirements
- **文件格式**: 生成 `{name}.widget.config.json`（纯 JSON，不是 JS 文件），路径为 `src/form-component-config/form-widget/{name}.widget.config.json`。
- **导入方式**: `index.js` 中使用 `import XxxWidgetConfig from './{name}.widget.config.json'`（必须带 `.json` 后缀）。
- Top-level structure MUST include: `version`, `code`, `desc`, `instance`, `component`, `widget`, `client`, `componentModelField`, `methods`, `formatValueSchema` — 缺少任何一个平台会崩溃。
- `code`: MUST start with `FORM_CUSTOM_` followed by a semantic uppercase string (e.g. `FORM_CUSTOM_DATA_SELECT`). Must match `apaas.json` `code` field.
- `desc.iconType`: fixed value `"DEFAULT"`.
- `desc.icon`: MUST be a real SVG string semantically matching the component (e.g. `"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\">...</svg>"`). Never use an icon class string.
- **CRITICAL**: `desc.text`、`desc.description`、`widget.display.label` 必须根据**当前需求**填写真实的中文名称和描述，绝对禁止出现 "Demo"、"demo"、"Demo组件"、"Demo组件描述" 等占位文字。例如国际手机号组件应填写 `"text": "国际手机号"`。
- `instance`: fixed `{ "uuid": "$itemUuid", "inTable": false }`.
- `widget.display.width`: `3 | 6 | 12` (1/4 / 1/2 / full row). `mobileWidth`: `6 | 12`. `height: 1`. `hidden/readOnly/required/onlyCreateEdit`: all `false`.
- `widget.allow`: MUST include all 4 fields: `"calcRule": false`, `"useInTableColumn": <boolean>`, `"scanCode": false`, `"copy": false`. `useInTableColumn` should be `true` by default unless sub-table usage is explicitly not needed.
- `widget.default`: `{ "customDefaultKey": "defaultValue", "value": null }` — value is `null`, NOT `""`.
- `widget.validator`: `{ "uniqueCheck": false }`.
- `widget.special`: MUST include 3 fields: `frontBusinessObjectComponentType`, `saveWithHidden: false`, `customComponentConfig`. **`customComponentConfig` must contain the default values for ALL config properties defined in `setting.vue`** (e.g. `{"defaultCountryCode": "CN", "placeholder": "", "clearable": true}`). Use `{}` only when there is no setting panel. Do NOT use empty strings as defaults for string fields — use `null` or a sensible default instead.
- `widget.special.frontBusinessObjectComponentType`: `"BOF_TEXT"` for string/json values, `"BOF_NUMBER"` for numbers, `"BOF_DATE"` for single date values.
- `componentModelField` (top-level, NOT inside widget.special): `["STRING"]` for <500 chars, `["BIG_TEXT"]` for ≥500 chars, `["NUM"]` for numbers, `["DATE"]` for single dates.
- `widget.editor.config`: array starting with `["INFO","LABEL","FIELD_CODE","TITLE_DESCRIPTION","WIDTH","HIDDEN","READONLY","REQUIRED","EDITONNEW","UNIQUE","HIDDEN_SAVE","HIDDEN_TRIGGER","TRIGGER_BUSINESS_EVENTS"]`. **CRITICAL**: if a custom setting panel exists, the editor.config.json `code` (= widget code + `_SETTING`) MUST be appended at the **end** of this array. `FORMULA_RULE` only if needed. `excludeInTable` must be `["WIDTH"]` ONLY — do not add other values.
- `client.mobile.widget.editor.config`: same structure as `widget.editor.config`.
- `client.mobile.component`: required fields `edit`, `read`, `ide`; optional `list`, `association`, `lov`, `tableColumn`. Names should be `Mobile` + PC component name convention.
- `component` (PC): required `ide`, `edit`, `read`; optional `list`, `association`, `lov`, `print`, `search`, `searchIde`.

## editor.config.json Requirements
- **文件格式**: 生成 `{name}.editor.config.json`（纯 JSON，不是 JS 文件），路径为 `src/form-component-config/form-editor/{name}.editor.config.json`。**不要**生成 `.editor.config.js`。
- **⚠️ 此文件只有 4 个字段**，不能放任何其他内容（禁止 `editorConfigList`、`options`、`staticData`、`type`、`group` 等）：
  ```json
  {
    "code": "FORM_CUSTOM_RATE_SETTING",
    "editorConfigType": "FORM_CUSTOM_RATE_SETTING",
    "componentName": "FormComponentRateSetting",
    "configProperty": "customComponentConfig"
  }
  ```
- `code` = widget.config.json 的顶层 `code` + `_SETTING`（例如 widget `code` 为 `FORM_CUSTOM_RATE` 则此处为 `FORM_CUSTOM_RATE_SETTING`）。
- `editorConfigType`：**与 `code` 完全相同的值**。
- `componentName`：必须与 `setting.vue` 中的 `name` 选项完全一致。
- `configProperty`：**固定值 `"customComponentConfig"`，不可修改**。
- **文件命名规范**：文件名必须语义化，使用 `{组件名}.editor.config.json`，例如 `form-component-rate.editor.config.json`，不得使用 `dev-edit.editor.config.json` 这类无意义名称。
- **注册**：必须同时更新 `src/form-component-config/form-editor/index.js`，添加 import 和注册。

## setting.vue Rules
- setting.vue uses componentConfig prop + formEngine prop
- setting.vue 必须通过 `componentConfig` prop 读取平台配置，但模板中统一绑定 `customComponentConfig.xxx`（computed 别名），不要直接写 `componentConfig.customComponentConfig.xxx`
- 方法名不是关键，关键是配置写入路径必须正确：严禁在 setting.vue 中使用 `localConfig`、`formData`、`config` 这类镜像配置
- 如果存在 `saveConfig()` / `handleChange()` / `updateComponentConfig()` 等方法，它们也只能直接操作 `customComponentConfig.xxx`，不能通过 `$emit('update:componentConfig', ...)` 或镜像状态回写
- 严禁调用不存在的配置写入 API：`formEngine.updateWidgetConfig(...)`、`formEngine.updateCustomComponentConfig(...)`、`formEngine.updateWidgetCustomConfig(...)`、`formEngine.updateSpecialConfig(...)`、`formEngine.setWidgetInfo(...)`
- `setting.vue` must be written to `src/form-component/form-editor/{name}-setting.vue`
- `editorConfigList` must be aggregated by `src/form-component-config/form-editor/index.js` from `./{name}.editor.config.json`
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
- **Do NOT generate `widget.config.json`, `editor.config.json`, or `setting.vue` by default**.
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
