"""
VibeCodingAgent - OpenAI-compatible API agent for aPaaS component development

Replaces the Claude Agent SDK with direct httpx calls using OpenAI function-calling format.
Implements an autonomous agent loop:
  User requirement -> LLM -> tool calls -> execute tools -> feed results back -> repeat until done
"""

import asyncio
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
    "start_serve": "\U0001f680 Serve",
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
                        info = self.ws_mgr.get_workspace_info(self.ws_id)
                        _pt = (info.get("project_type", "") or "").lower()
                        progress_note = self._describe_tool_plan(tool_names, _pt)
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

                        # 写 Java 文件时，把 AI 可能生成的非标准空格（\u00a0 等）替换为普通空格，
                        # 避免 javac "非法字符" 编译错误。仅在 write_file 写 .java 时处理。
                        if func_name == "write_file":
                            _fp = func_args.get("file_path", "")
                            if isinstance(_fp, str) and _fp.endswith(".java"):
                                _raw = func_args.get("content", "")
                                _NONSTANDARD_SPACES = (
                                    "\u00a0",  # NO-BREAK SPACE
                                    "\u2002",  # EN SPACE
                                    "\u2003",  # EM SPACE
                                    "\u2009",  # THIN SPACE
                                    "\u200b",  # ZERO WIDTH SPACE
                                    "\u3000",  # IDEOGRAPHIC SPACE
                                    "\ufeff",  # BOM
                                )
                                _cleaned = _raw
                                for _ch in _NONSTANDARD_SPACES:
                                    _cleaned = _cleaned.replace(_ch, " " if _ch != "\u200b" and _ch != "\ufeff" else "")
                                if _cleaned != _raw:
                                    func_args = {**func_args, "content": _cleaned}

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
                            progress_callback=_tool_progress if func_name in ("run_command", "start_serve") else None,
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

                        # start_serve 成功 → 发出 serve_started 事件供前端注入调试扩展
                        if func_name == "start_serve" and not is_error:
                            try:
                                serve_data = json.loads(result_str)
                                # 单端：{"url": "..."}
                                serve_url = serve_data.get("url", "")
                                if serve_url:
                                    _emit({"type": "serve_started", "url": serve_url})
                                # 双端：{"web_url": "...", "mobile_url": "..."}
                                web_url = serve_data.get("web_url", "")
                                mobile_url = serve_data.get("mobile_url", "")
                                if web_url:
                                    _emit({"type": "serve_started", "url": web_url})
                                if mobile_url:
                                    _emit({"type": "serve_started", "url": mobile_url})
                            except (json.JSONDecodeError, Exception):
                                pass

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

    # ============================================================
    # 共享 prompt 段（form-component 单端 / form-component-dual 双端共用）
    # ------------------------------------------------------------
    # 这些段只有路径前缀不同（src vs web/src），用 __BASE_PATH__ 占位符
    # 让两个分支调用 .replace("__BASE_PATH__", ...) 渲染。
    # 维护这些规则只需改这一处，避免 dual / 单端漂移。
    # ============================================================

    _SHARED_WIDGET_CONFIG_SECTION = """
## widget.config.json Requirements
- **文件格式**: 生成 `{name}.widget.config.json`（纯 JSON，不是 JS 文件），路径为 `__BASE_PATH__/form-component-config/form-widget/{name}.widget.config.json`。
- **导入方式**: `index.js` 中使用 `import XxxWidgetConfig from './{name}.widget.config.json'`（必须带 `.json` 后缀）。
- Top-level structure MUST include: `version`, `code`, `desc`, `instance`, `component`, `widget`, `client`, `componentModelField`, `methods`, `formatValueSchema` — 缺少任何一个平台会崩溃。
- `code`: MUST start with `FORM_CUSTOM_` followed by a semantic uppercase string (e.g. `FORM_CUSTOM_DATA_SELECT`). Must match `apaas.json` `code` field.
- `desc.iconType`: fixed value `"DEFAULT"`.
- `desc.icon`: MUST be a real SVG string semantically matching the component (e.g. `"<svg xmlns=\\"http://www.w3.org/2000/svg\\" viewBox=\\"0 0 24 24\\">...</svg>"`). Never use an icon class string.
- **CRITICAL**: `desc.text`、`desc.description`、`widget.display.label` 必须根据**当前需求**填写真实的中文名称和描述，绝对禁止出现 "Demo"、"demo"、"Demo组件"、"Demo组件描述"、"Custom"、"custom"、"Component"、"自定义组件"、"通用组件" 等**占位/通用词**作为组件名称。例如国际手机号组件应填写 `"text": "国际手机号"`；日期时间段组件应填写 `"text": "日期时间段"`。
- **CRITICAL 命名铁则**: 组件的 kebab-case 英文名（用于 `code` 派生和所有文件命名）**必须反映组件核心功能**，从用户需求中提炼语义短语。**严禁**使用以下通用/占位词作为组件英文名：`custom` / `demo` / `component` / `custom-dev` / `form-component` / `custom-component`。示例：
  - 需求"日期时间段选择组件" → kebab-case 名 `date-time-range` → `code: "FORM_CUSTOM_DATE_TIME_RANGE"` → 文件名 `form-component-date-time-range-edit.vue`
  - 需求"星级评分" → `star-rating` → `FORM_CUSTOM_STAR_RATING` → `form-component-star-rating-edit.vue`
  - 需求"颜色选择器" → `color-picker` → `FORM_CUSTOM_COLOR_PICKER` → `form-component-color-picker-edit.vue`

  如果用户给的需求抽象（如"自定义组件"），必须在 brainstorm 阶段反问具体功能后再确定名字，不允许直接用 custom 兜底。
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
"""

    _SHARED_EDITOR_CONFIG_SECTION = """
## editor.config.json Requirements
- **文件格式**: 生成 `{name}.editor.config.json`（纯 JSON，不是 JS 文件），路径为 `__BASE_PATH__/form-component-config/form-editor/{name}.editor.config.json`。**不要**生成 `.editor.config.js`。
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
- **注册**：必须同时更新 `__BASE_PATH__/form-component-config/form-editor/index.js`，添加 import 和注册。
"""

    _SHARED_SETTING_VUE_SECTION = """
## setting.vue Rules

### ⚠️ 必须使用 scaffold 预置的 editor 原子组件（严禁用 Element UI 原生）

`__BASE_PATH__/form-component/form-editor/components/` 目录下 scaffold **已预置 6 个 editor 原子组件**（LLM 不要重新生成，直接 import 使用）：

- `form-custom-sechma-item.vue` — **仅在业务 editor 内部作为外壳容器使用**。**严禁**在 setting.vue 主体 template 里直接用：sechma-item 不提供 formValue 双向绑定，setting.vue 本体又没有 formValue，直用后写 `<el-date-picker v-model="formValue" />` 会掉进 phantom property，UI 正常但数据完全不存。
- `form-custom-input-editor.vue` — 单行输入（替代 `<el-input>`）
- `form-custom-select-editor.vue` — 下拉（替代 `<el-select>` + `<el-option>`，通过 `options` prop 传选项）
- `form-custom-textarea-editor.vue` — 多行输入（替代 `<el-input type="textarea">`）
- `form-custom-switch-editor.vue` — 开关（替代 `<el-switch>`）

还有 2 个字段赋值 editor：
- `form-custom-field-assign-editor.vue` — 主表字段赋值
- `form-custom-table-field-assign-editor.vue` — 子表字段赋值

**⚠️ 任何"组件把派生值/选中值写给其他字段"的场景都必须用字段赋值 editor**（数据选择类回填 / 派生值输出 / 联动赋值），**严禁**靠 aPaaS 字段联动规则等外部机制。

**`otherFields` 是"组件作为赋值源能产出的字段列表"**（组件侧的**源字段**，不是表单里其他字段）。每个元素 `{uuid, label, componentType}`：
- `uuid`：组件内部逻辑 key（自行编造的业务语义 id，不是真实字段 uuid）
- `label`：中文展示名
- `componentType`：按派生值类型选——数字 `FORM_NUMBER_INPUT` / 字符串 `FORM_TEXT_INPUT` / 金额 `FORM_MONEY_INPUT` / 手机号 `FORM_PHONE_INPUT` / 邮箱 `FORM_EMAIL_INPUT` / 证件号 `FORM_IDCARD_INPUT`

示例（时间差组件）：
```vue
<form-custom-field-assign-editor
  label="时间差赋值" property="diffAssign" v-bind="$props"
  :otherFields="diffSourceFields"
></form-custom-field-assign-editor>
```
```js
computed: {
  diffSourceFields() {
    return [{ uuid: 'diff', label: '时间差', componentType: 'FORM_NUMBER_INPUT' }];
  },
}
```

`otherTableFields`（子表赋值）：第一级 `componentType` 必须是 `FORM_WIDGET_SON_TABLE`，`children` 每项按 componentType 映射表选。

edit.vue 消费赋值配置：从 `customComponentConfig.diffAssign` 里拿到 `[{origin, target}]`，按 target.uuid 写值：
```js
this.$set(this.formData, pair.target.uuid, diff);
this.formEngine.formDataControl.ctlFormDataChanged = true;
```

**完整示例和 otherTableFields 结构详见 `.cursor/rules/setting-vue.mdc`。**

## 🛑 自造业务 editor 的强制约定

预置原子无法满足时允许新建 `components/form-custom-{业务名}-editor.vue`，**必须**按以下铁则（否则"UI 正常但数据存不进去"静默 bug）：

1. **必须** `mixins: [EditorFormConfigMixin, FormEditorMixin]` —— `formValue` 由 FormEditorMixin 自动双向绑定到 `componentConfig[configProperty][property]`，**禁止**自己实现 computed getter/setter。
2. **禁止** `this.$parent[configProperty]` 读配置（错误 API）。
3. **禁止**重复声明 `label` / `property` / `help` / `showRequired` / `placeholder` props —— FormEditorMixin 已提供，只声明业务特有 props。
4. **必须**用 `<form-custom-sechma-item>` 包裹（透传 label/property/configProperty/showRequired/help/rules 6 个 prop）。
5. 值变化调 `handleChange`（FormEditorMixin 提供）或让 `v-model="formValue"` 自动触发。**禁止** `$emit('update:componentConfig', ...)`。
6. 参考 scaffold 里 `form-custom-input-editor.vue` / `form-custom-select-editor.vue` 的结构。

**🔴 setting.vue 中严禁直接使用下列 Element UI 原生组件**：
- `<el-form-item>` / `<el-form>` / `<el-input>` / `<el-select>` / `<el-option>`
- `<el-switch>` / `<el-radio>` / `<el-radio-group>` / `<el-checkbox>` / `<el-checkbox-group>`

遇到上述需求**必须**用对应的 `form-custom-*-editor` 原子替换。

### 正确示例（模板即可复用）

```vue
<template>
  <div class="form-custom-{name}-setting">
    <form-custom-input-editor
      label="占位文本" property="placeholder" v-bind="$props"
      :help="['为空时的提示文字']"
    ></form-custom-input-editor>
    <form-custom-select-editor
      label="显示模式" property="mode" v-bind="$props"
      :options="modeOptions" :showRequired="true"
    ></form-custom-select-editor>
    <form-custom-switch-editor
      label="允许为空" property="nullable" v-bind="$props"
    ></form-custom-switch-editor>
  </div>
</template>

<script>
// 单端：@/mixin/form-config.mixin ；双端：@shared/mixin/form-config.mixin
import EditorFormConfigMixin from '@/mixin/form-config.mixin';
import FormCustomInputEditor from './components/form-custom-input-editor.vue';
import FormCustomSelectEditor from './components/form-custom-select-editor.vue';
import FormCustomSwitchEditor from './components/form-custom-switch-editor.vue';

export default {
  name: 'FormComponent{Name}Setting',  // 必须与 editor.config.json 的 componentName 一致（PascalCase）
  mixins: [EditorFormConfigMixin],
  components: { FormCustomInputEditor, FormCustomSelectEditor, FormCustomSwitchEditor },
  computed: {
    modeOptions() { return [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }]; },
  },
};
</script>
```

所有 editor 原子都约定同一组 props：`label`、`property`、`v-bind="$props"`（**必传**，透传 configProperty 给容器）；`showRequired` / `help`（字符串数组） / `placeholder` 可选；`form-custom-select-editor` 额外需要 `options`。

### 写入路径和校验规范
- setting.vue 通过 `componentConfig` prop 读取平台配置。editor 原子内部已封装 formValue 双向绑定到 `componentConfig.customComponentConfig[property]`，setting.vue 主体代码不需要手写读写逻辑。
- 如果业务必须写 `saveConfig()` / `handleChange()`，只能直接操作 `customComponentConfig.xxx`，严禁通过 `$emit('update:componentConfig', ...)` 或镜像状态回写
- 严禁调用不存在的配置写入 API：`formEngine.updateWidgetConfig(...)`、`formEngine.updateCustomComponentConfig(...)`、`formEngine.updateWidgetCustomConfig(...)`、`formEngine.updateSpecialConfig(...)`、`formEngine.setWidgetInfo(...)`
- 严禁在 setting.vue 中使用 `localConfig`、`formData`、`config` 这类镜像配置
- `inject` 声明必须带 `{ default: null }`
- 配置直接存 `customComponentConfig` 根级别，不要多嵌套（如 `{ chartConfig: { dataSource } }` 错，应为 `{ dataSource }`）
- 不要在 computed 里用 `$set`（会导致无限循环）
- formEngine 通过 prop 传入（不是 inject）
- **最外层容器不要设置 padding**，平台区域已做好布局，额外 padding 会压缩可用空间

### 文件路径
- `setting.vue` must be written to `__BASE_PATH__/form-component/form-editor/{name}-setting.vue`
- `editorConfigList` must be aggregated by `__BASE_PATH__/form-component-config/form-editor/index.js` from `./{name}.editor.config.json`

### 所有 7 个 scene 都必须完整实现（禁止 half-rename）
- 7 个 scene（edit / read / ide / list / print / search / search-ide）每个目录下的 `.vue` 文件都必须真实存在，对应 `index.js` 每一行 `import` 指向的文件都必须存在。
- **绝对禁止**出现"改了 index.js 的 import 路径但没建对应 vue"的 half-rename 状态——会导致 webpack 报 `Module not found` build 失败。
- 如果某个 scene 用不到，保持 scaffold 默认的 `form-component-demo-{scene}.vue` 原样（连带 index.js 也别改），不要半改。
- 7 个 scene 地位平等：不存在"edit 是主要，其他可简略"这样的优先级——每个 scene 都有独立 UI 职责，必须完整实现。
"""

    _SHARED_FORMVALUE_STORAGE_SECTION = """
## formValue 存储规范（★ 必须遵守，否则数据无法入库）
- 组件值改变后必须同步写入 `this.formValue`，平台通过 formValue 将数据持久化到数据库
- 组件内部 UI 状态可以用 `data` 维护，但业务值变化时必须同步到 formValue
- formValue 只接受基本数据类型：`string`、`number`、`boolean`、`null`
- 对象、数组等复杂类型必须先 `JSON.stringify()` 序列化再赋值，读取时用 `JSON.parse()` 反序列化
- 推荐模式：`mounted() { if (this.formValue) try { this.innerValue = JSON.parse(this.formValue) } catch(e) {} }`，`handleChange(val) { this.innerValue = val; this.formValue = JSON.stringify(val) }`
"""

    _SHARED_FORMENGINE_API_SECTION = """
## ⚠️ formEngine API 白名单（★ 极严格，违反会运行时崩溃）

**在写任何 `this.formEngine.xxx` 代码前，必须确认该属性/方法在以下白名单中。白名单外的一切 `formEngine.xxx(...)` 方法调用都是 LLM 臆想，不存在。**

### ✅ 允许的只读属性

- `formEngine.engineContext.instance.documentId` — 当前文档 ID
- `formEngine.engineContext.instance.instanceId` — 当前表单实例 ID
- `formEngine.formDataControl.allTileFormItemList` — 所有表单字段配置数组
- `formEngine.formDataControl.componentMap` — uuid → 组件配置 Map（用 `.get(uuid)` 访问）
- `formEngine.formDataControl.ctlComponentMap` — 表单控件实例 Map
- `formEngine.formRef` — 表单 ref 引用

### ✅ 允许调用的方法

- `formEngine.formRef.validateField(propKey, callback)` — 触发单字段校验
- `formEngine.bsEventControl.triggerEventValueChange(widget, event)` — 触发业务事件

### ✅ 允许写的状态标记

- `formEngine.formDataControl.ctlFormDataChanged = true` — 标记表单数据已变更（赋值**后**请确保 `this.formData` 已通过 `$set` 更新）

### ❌ 严禁臆想的方法（下列方法在 formEngine 上**根本不存在**，调用会直接报 `is not a function`）

| 臆想的错误调用 | 正确替代方案 |
|---|---|
| `formEngine.setWidgetValue(uuid, val)` | `this.$set(this.formData, uuid, val)` |
| `formEngine.setFieldValue(...)` / `setFormValue(...)` | 同上 |
| `formEngine.updateWidgetConfig(...)` | setting.vue 里用 `v-model="customComponentConfig.xxx"` 双向绑定 |
| `formEngine.updateCustomComponentConfig(...)` | 同上 |
| `formEngine.updateWidgetCustomConfig(...)` | 同上 |
| `formEngine.updateSpecialConfig(...)` | 同上 |
| `formEngine.setWidgetInfo(...)` | 同上 |
| `formEngine.saveConfig(...)` / `submitConfig(...)` / `applyConfig(...)` | 不存在，无需调用 |
| `formEngine.getFieldByCode(...)` / `getComponentByCode(...)` | 用 `allTileFormItemList.find(c => c.code === 'xxx')` |

**铁律**：
1. 写 `this.formEngine.xxx(...)` 前，先检查 xxx 是否在上方"允许调用的方法"中；不在就**不要写**
2. 给其他字段赋值**唯一正确方式**：`this.$set(this.formData, targetUuid, value)` + 可选 `this.formEngine.formDataControl.ctlFormDataChanged = true`
3. 修改自身组件配置**唯一正确方式**：setting.vue 里 `v-model="customComponentConfig.xxx"`
4. 如果你不确定某个 API 是否存在，**宁可不写，不要猜**
"""

    @classmethod
    def _render_form_component_sections(cls, base_path: str) -> str:
        """渲染 form-component 共享段（widget.config.json + editor.config.json + setting.vue + formValue）。

        base_path: 文件路径前缀。单端为 `src`，双端为 `web/src`。
        """
        return (
            cls._SHARED_WIDGET_CONFIG_SECTION.replace("__BASE_PATH__", base_path)
            + cls._SHARED_EDITOR_CONFIG_SECTION.replace("__BASE_PATH__", base_path)
            + cls._SHARED_SETTING_VUE_SECTION.replace("__BASE_PATH__", base_path)
            + cls._SHARED_FORMVALUE_STORAGE_SECTION
            + cls._SHARED_FORMENGINE_API_SECTION
        )

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
4. **Build 前一致性自检（必做）**: run build 前，用 glob 或 list_dir **逐个验证** 7 个 scene 目录 (`src/form-component/form-widget/{edit,read,ide,list,print,search,search-ide}/`) 下的 `index.js` 引用的每一个 `.vue` 文件是否都真实存在。只要有一个"index.js 引用了但 vue 不存在"，立即先补建/修正，不要先跑 build。
5. **THEN** run `npm run build` to check compilation
6. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly. Do NOT dump hidden reasoning or long analysis.
- **DO NOT loop**: Never read the same file twice. Never read more than 3 files before writing code.
- **Write ALL files at once**: In a single turn, call write_file for edit.vue, read.vue, ide.vue, setting.vue etc. Do NOT write one file per turn.
- **When generating designer config**: update `src/form-component/form-editor/index.js` and `src/form-component-config/form-editor/index.js` in the same batch as `setting.vue` / `{name}.editor.config.json`.
- **index.js 与 vue 必须一致**: 修改任何 `index.js` 的 import 路径时，**必须**同步确保对应 vue 文件存在（新建或重命名）。不允许出现 "index.js 指向的文件不存在" 的 half-rename 状态。如不需要某个 scene，保持 scaffold 默认的 `form-component-demo-{scene}.vue` 原样，index.js 也别改。
- **Be decisive**: You are an expert. After reading the scaffold structure and 1-2 example files, you have enough context to write the component.
- **Maximum 8 turns total**: If you haven't written code by turn 4, something is wrong. Write the code NOW.
- **NEVER use `<el-dialog>` inside form widgets** — it breaks FormEngine component resolution and crashes the platform with `Cannot read properties of undefined (reading 'edit')`. Use `<el-popover :append-to-body="true">` instead for any preview/popup interaction.

## Technical Constraints
- aPaaS form component with 7 render scenes (edit/read/ide/list/print/search/search-ide)
- Scaffold files already exist. Do NOT modify vue.config.js or babel.config.js. Avoid unrelated index.js changes, but you may update `src/form-component/form-editor/index.js` and `src/form-component-config/form-editor/index.js` when adding `setting.vue` / `editor.config.json`.
- Vue 2.7 + Element UI (globally registered, do NOT import Element UI)
- **console.log is stripped in production — use `console.info` for ALL debug output in every mode.**
- **formEngine is NOT available in `beforeCreate()` — only access `this.formEngine` from `created()` or later.**

## 🛑 目录结构铁则（绝对不要违反）

所有 7 个 scene 的 vue 文件**只能放在下列唯一目录下**：

```
src/form-component/form-widget/
├── edit/       ← form-component-{name}-edit.vue
├── read/       ← form-component-{name}-read.vue
├── ide/        ← form-component-{name}-ide.vue
├── list/       ← form-component-{name}-list.vue
├── print/      ← form-component-{name}-print.vue
├── search/     ← form-component-{name}-search.vue
└── search-ide/ ← form-component-{name}-search-ide.vue
```

**禁止**创建以下目录（常见幻觉，scaffold **不存在**）：
- ❌ `src/form-component/list-widget/`
- ❌ `src/form-component/print-widget/`
- ❌ `src/form-component/search-widget/`
- ❌ `src/form-component/search-ide-widget/`
- ❌ `src/form-component/edit-widget/`

注意：mixin 文件名（如 `list-widget.mixin.js`、`search-widget.mixin.js`）**只是文件名**，**不是目录名**。list/search/print/search-ide 的 vue 都在 `form-widget/{mode}/` 下。

## Mixin Per Mode (always use default import, never named import)
- edit / ide / read → `import FormWidgetMixin from '@/mixin/form-widget.mixin'`
- list            → `import ListWidgetMixin from '@/mixin/list-widget.mixin'` （仅是 mixin 文件名，不要据此创建 list-widget/ 目录）
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
""" + self._render_form_component_sections(base_path="src")
        if project_type == "form-component-dual":
            workflow = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-3 calls max): If `.cursor/rules/*.mdc` exists, read those rule files first, then read ONLY the key implementation files you need. Do NOT read every file.
3. **IMMEDIATELY write code**: Use write_file to create/update ALL component files (web/ and mobile/) in one batch. Call write_file multiple times in a SINGLE turn (parallel tool calls).
4. **Build 前一致性自检（必做）**: run build 前，用 glob 或 list_dir **逐个验证**两端 7 个 scene 目录（`web/src/form-component/form-widget/{edit,read,ide,list,print,search,search-ide}/` 和 `mobile/src/form-component/form-widget/{...}/`）下的 `index.js` 引用的每一个 `.vue` 文件是否都真实存在。只要有一个"index.js 引用了但 vue 不存在"，立即先补建/修正，不要先跑 build。
5. **THEN** run `npm run build` to check compilation (builds both web/ and mobile/)
6. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly. Do NOT dump hidden reasoning or long analysis.
- **DO NOT loop**: Never read the same file twice. Never read more than 3 files before writing code.
- **Write ALL files at once**: In a single turn, call write_file for ALL web/ and mobile/ vue files. Do NOT write one file per turn.
- **When generating designer config**: update `web/src/form-component/form-editor/index.js` and `web/src/form-component-config/form-editor/index.js` in the same batch as `setting.vue` / `{name}.editor.config.json`.
- **index.js 与 vue 必须一致**: 修改任何 `index.js` 的 import 路径时，**必须**同步确保对应 vue 文件存在（新建或重命名）。不允许出现 "index.js 指向的文件不存在" 的 half-rename 状态。如不需要某个 scene，保持 scaffold 默认的 `form-component-demo-{scene}.vue` / `mobile-form-component-demo-{scene}.vue` 原样，index.js 也别改。
- **Be decisive**: You are an expert. After reading the scaffold structure and 1-2 example files, you have enough context to write the component.
- **Maximum 8 turns total**: If you haven't written code by turn 4, something is wrong. Write the code NOW.
- **NEVER use `<el-dialog>` inside form widgets** — it breaks FormEngine component resolution and crashes the platform with `Cannot read properties of undefined (reading 'edit')`. Use `<el-popover :append-to-body="true">` instead for any preview/popup interaction.

## Technical Constraints — Dual-End Project
- This is a **dual-end** (PC + Mobile) project with three directories: `shared/`, `web/`, `mobile/`
- aPaaS form component with 7 render scenes (edit/read/ide/list/print/search/search-ide), both web/ and mobile/ have the same scenes
- Scaffold files already exist. Do NOT modify vue.config.js or babel.config.js.
- Vue 2.7 for both ends
- **PC (web/)**: Element UI (`el-*` components), globally registered, do NOT import
- **Mobile (mobile/)**: 可使用 **cube-ui**（平台全局注册，无需 import）或 **Vant 2**（`<van-*>` 组件，vue.config.js 已配置 `unplugin-vue-components` + `VantResolver` 按需自动引入，无需手动 import）。**注意：必须使用 Vant 2（vant@latest-v2），不要使用 Vant 3/4，因为项目基于 Vue 2.7**
- **console.log is stripped in production — use `console.info` for ALL debug output in every mode.**
- **formEngine is NOT available in `beforeCreate()` — only access `this.formEngine` from `created()` or later.**

## 🛑 目录结构铁则（双端项目，绝对不要违反）

web/ 和 mobile/ **两端**的 7 个 scene vue 都**只能放在各自的 form-widget/ 下**：

```
web/src/form-component/form-widget/
├── edit/       ← form-component-{name}-edit.vue
├── read/       ← form-component-{name}-read.vue
├── ide/        ← form-component-{name}-ide.vue
├── list/       ← form-component-{name}-list.vue
├── print/      ← form-component-{name}-print.vue
├── search/     ← form-component-{name}-search.vue
└── search-ide/ ← form-component-{name}-search-ide.vue

mobile/src/form-component/form-widget/
├── edit/       ← mobile-form-component-{name}-edit.vue
├── read/       ← mobile-form-component-{name}-read.vue
├── ide/        ← mobile-form-component-{name}-ide.vue
├── list/       ← mobile-form-component-{name}-list.vue
├── print/      ← mobile-form-component-{name}-print.vue
├── search/     ← mobile-form-component-{name}-search.vue
└── search-ide/ ← mobile-form-component-{name}-search-ide.vue
```

**禁止**创建以下目录（常见幻觉，scaffold **不存在**）：
- ❌ `web/src/form-component/list-widget/` / `print-widget/` / `search-widget/` / `search-ide-widget/`
- ❌ `mobile/src/form-component/list-widget/` / `print-widget/` / `search-widget/` / `search-ide-widget/`

注意：mixin 文件名（`list-widget.mixin.js` / `search-widget.mixin.js` / `print-widget.mixin.js`）**只是文件名**，**不是目录名**。list/search/print/search-ide 的 vue 全部在各端的 `form-widget/{mode}/` 下，没有例外。

## Mixin Per Mode — IMPORTANT: use @shared/ alias (NOT @/)
- edit / ide / read → `import FormWidgetMixin from '@shared/mixin/form-widget.mixin'`
- list            → `import ListWidgetMixin from '@shared/mixin/list-widget.mixin'` （仅是 mixin 文件名，不要据此创建 list-widget/ 目录）
- print           → `import PrintWidgetMixin from '@shared/mixin/print-widget.mixin'`
- search          → `import SearchWidgetMixin from '@shared/mixin/search-widget.mixin'`
- search-ide      → `import SearchIdeWidgetMixin from '@shared/mixin/search-ide-widget.mixin'`
- editor (setting.vue, web only) → `import EditorFormConfigMixin from '@shared/mixin/form-config.mixin'`
- **NEVER use `@/mixin/...`** — shared mixins live in `shared/mixin/`, the alias `@shared` points to `../shared`

## Mode-specific Rules
- **List mode**: config = `this.componentConfig` (NOT `this.widget`); `this.formValue` is the concrete value prop directly (no propKey indexing); NO `<x-proxy-form-item>` wrapper.
- **Print mode**: NO UI component tags — neither Element UI nor Vant renders in print context; NO `<x-proxy-form-item>`; pure HTML/CSS only; use structure `div.print-item > div.print-item-title + div.print-item-value`; when `widget.isInTable` is true, omit the title.
- **Search mode**: NO `<x-proxy-form-item>`; submit via `this.$emit('change', [value])` — value MUST be wrapped in an array; do NOT use formValue setter.
- **Search-IDE mode**: NO `<x-proxy-form-item>`; all inputs `disabled`; only implement when Search mode is also implemented.
- **IDE mode**: all inputs must be `disabled` — IDE renders in the form designer canvas where user interaction is not allowed.
- **Edit mode**: check `this.widget.readOnly`; guard formValue undefined with fallback; never use both `v-model` and `@input` on the same element (causes infinite loop).

## BOF Type & formValue
- BOF_NUMBER caveat: `formValue` may arrive as a string from the platform. Always guard: `const n = Number(this.formValue); if (isNaN(n)) { /* fallback */ }`.

## 组件 name 命名约定
- PC 组件：`FormComponentXxxEdit` / `FormComponentXxxIde` / `FormComponentXxxRead` 等（PascalCase）
- 移动端组件：`MobileFormComponentXxxEdit` / `MobileFormComponentXxxIde` 等（Mobile 前缀 + PC 命名）
- 移动端文件名：`mobile-{name}-edit.vue`（kebab-case，加 `mobile-` 前缀）

## widget.config.json 中必须同时声明 PC 和移动端组件
```json
{
  "component": { "ide": "FormComponentXxxIde", "edit": "FormComponentXxxEdit", ... },
  "client": {
    "mobile": {
      "component": { "ide": "MobileFormComponentXxxIde", "edit": "MobileFormComponentXxxEdit", ... }
    }
  }
}
```

## ⚠️ code 字段三文件必须同步
`shared/widget.config.json.code`、`web/src/apaas.json.customWidgetList[0].code`、`mobile/src/apaas.json.customWidgetList[0].code` 三者必须**完全一致**。如果使用语义化 code（如 `FORM_CUSTOM_TIME_PICKER`），必须同时更新这三个文件的 `code` 字段。

## ⚠️ 移动端 edit.vue 必须使用 `<x-proxy-form-item>` 包裹（与 PC 端一致）
- `mobile/src/form-component/form-widget/edit/mobile-{name}-edit.vue` 模板最外层必须是 `<x-proxy-form-item>`
- 即使移动端使用 cube-ui 或 Vant，`x-proxy-form-item` 仍由 shared/ 平台注入，用于标题/校验提示/只读态等统一行为
- 此规则**仅对 edit 场景生效**，list/print/search/search-ide 场景仍**不要**包裹 `x-proxy-form-item`

## ⚠️ 文件命名必须与 widget.config.json.code 语义一致
- 若 `shared/widget.config.json.code = FORM_CUSTOM_TIME_PICKER`，则 semantic = `time-picker`
- 各 scene 下文件名必须为 `form-component-time-picker-{scene}.vue`（PC）/ `mobile-form-component-time-picker-{scene}.vue`（移动）
- 禁止出现与 code 语义不一致的文件名（如 `form-component-time-only-picker-edit.vue`）

## ⚠️ "一个组件 = 一套文件"
- 每个自开发组件对应 7 个 scene 各一个 vue 文件（共 14 个：PC 7 + 移动 7），构成"一套"
- 多组件工程（`customWidgetList` 多项）每个组件一套，互不覆盖，`index.js` 按 code 聚合
- 单组件工程里每个 scene 目录**只保留这一个组件的 vue 文件**，其他一律清理（脚手架占位 `form-component-demo-*.vue` / `mobile-form-component-demo-*.vue` / 旧文件 / 语义不一致的副本必须显式 delete）

## FORM_COMPONENT_DUAL 路径规范（与 FORM_COMPONENT 单端的差异）
- 所有 widget.config.json / editor.config.json / setting.vue / index.js 都在 `web/` 子目录下，路径前缀为 `web/src/`
- 配置面板聚合文件：`web/src/form-component/form-editor/index.js`（import setting.vue 并放入数组）
- editorConfigList 聚合文件：`web/src/form-component-config/form-editor/index.js`（import editor.config.json）
- 以上 4 个文件必须**同一批次一起写入**
- 移动端 `mobile/` 没有 setting.vue 和 editor.config.json
""" + self._render_form_component_sections(base_path="web/src")
        elif project_type in ("menu-page", "form-page", "mobile-page"):
            workflow = """
## Workflow — IMPORTANT: Be efficient! Minimize tool calls.
0. **Before tool calls**: First write a short, user-facing progress note in Chinese (1-3 sentences) explaining what you understood and what you will do next.
1. **FIRST** (1 call): Use glob_files to see the project structure
2. **THEN** (1-2 calls max): Read ONLY the key files (`src/apaas.json`, `src/index.js`, `src/form-page/*.vue` or `src/Home.vue`, `src/api/index.js`)
3. **IMMEDIATELY write code**: Update the page files in one batch. Do NOT apply the 7-scene form-component pattern.
4. **THEN** run `npm run build` to check compilation
5. If errors, fix and rebuild. If success, report completion.

## CRITICAL Rules
- **Progress notes are visible to the user**: keep them brief, concrete, and friendly.
- **DO NOT loop**: Never read the same file twice. Never read more than 3 files before writing code.
- **Do NOT generate `widget.config.json`, `editor.config.json`, or `setting.vue`** — 这些是表单组件专属，页面场景不需要
- **Do NOT apply 7-scene pattern** (edit/read/ide/list/print/search/search-ide) — 页面只是普通 Vue 组件

## Technical Constraints — MENU_PAGE / FORM_PAGE
- 页面打包为 UMD 组件后部署，可作为独立菜单页面或被平台弹窗（x-lov）引用
- `templateType` 必须是 `MENU_PAGE`（或对应页面类型）
- Vue 2.7 + Element UI（全局注册，不要 import）
- **`$request` 不是 Promise** — 必须用 `.asyncThen()` / `.asyncErrorCatch()`，**不能用** `.then()` / `.catch()`
- **不要使用** `x-http-block-table` / `x-ag-grid` — 直接使用 Element UI 的 `<el-table>` + `<el-pagination>`
- 组件名必须是 `apaas-custom-{kebab-name}` 格式，与 `apaas.json` 的 router 配置一致
- `src/index.js` 中必须 `window[Symbol.for("组件名")] = Component` 注册
- 弹窗场景必须实现 `getSelectedData()` 方法，返回 `this.selectedRows` 数组
- **跨页多选** — el-table 翻页会清空选中，需自己维护 `selectedRows` 并用 `toggleRowSelection` 恢复
- 布局用 flex，表格区域 `flex: 1` 填充剩余空间
- 国际化目录 `src/form-page-local/` 必须存在（即使只有中文也要）
- 只修改 `src/` 下的业务文件，不要改 `vue.config.js`、`babel.config.js`

## API 来源说明（开始开发前必须确认）
页面需要数据才有意义。如果用户未说明数据来源，必须先问：
1. "数据从哪里获取？是使用低代码平台现有表单的 API，还是自定义外部 API？"
2. **平台 API**：需要 formId、tabId、字段映射
3. **自定义 API**：需要 API 地址和参数格式

若用户未提供，可用 mock 数据实现 UI 并标注 `// TODO: 替换为实际 API`，同时告知用户需要补充。

## mobile-page 特殊说明
- 移动端页面使用 cube-ui 组件库（平台全局注册，无需 import）
- 其他规则与 menu-page 相同
"""
        elif project_type == "layout":
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
    def _describe_tool_plan(tool_names: list[str], project_type: str = "") -> str:
        """Generate a short user-facing progress note when the model omits one."""
        if not tool_names:
            return ""

        unique_names = list(dict.fromkeys(tool_names))
        is_backend = project_type.startswith("backend")
        parts: list[str] = []

        if "glob_files" in unique_names:
            if is_backend:
                parts.append("我先快速扫一遍项目结构，确认脚手架文件布局。")
            else:
                parts.append("我先快速扫一遍项目结构，确认组件骨架和可复用文件。")
        if "grep_search" in unique_names:
            parts.append("我会顺手搜索关键实现，避免漏掉现有约定。")
        if "read_file" in unique_names:
            if is_backend:
                parts.append("接着读取少量关键文件，确认当前接口写法和示例代码风格。")
            else:
                parts.append("接着读取少量关键文件，确认当前组件写法和 mixin 用法。")
        if "write_file" in unique_names:
            if is_backend:
                parts.append("上下文已经够了，下一步开始批量写入 Java 文件。")
            else:
                parts.append("上下文已经够了，下一步开始批量写入组件文件。")
        if "edit_file" in unique_names:
            parts.append("我会在现有文件上做定向修改，尽量减少无关变动。")
        if "run_command" in unique_names:
            parts.append("代码写完后我会立刻做构建校验，确认没有编译问题。")

        if not parts:
            return "我正在推进下一步实现，很快会同步新的进展。"

        return " ".join(parts[:2])
