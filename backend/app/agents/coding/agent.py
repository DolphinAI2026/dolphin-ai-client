"""CodingAgent — 从 VibeCodingAgent 迁移到 BaseAgent 架构。

Stage 分步实施：
- 2.1（当前）：骨架 + tool_registry 包装
- 2.2：流式 LLM 调用（覆盖 _call_llm）
- 2.3：完整 prompt 构造（搬 _build_prompt）
- 2.4：循环检测 / context 压缩 / 状态序列化
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.agents.base import BaseAgent
from app.agents.coding.prompts import build_user_prompt
from app.agents.coding.tools import build_coding_tools
from app.agents.types import AgentContext, AgentResult, AgentStatus, AgentType, LLMResponse, Tool, ToolCall, ToolResult, TraceEventType
from app.observability import recorder
from app.coding.prompts import AGENT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# Tool display names for frontend（从 VibeCodingAgent 搬）
TOOL_ICONS: dict[str, str] = {
    "read_file": "\U0001f4c2 Read",
    "write_file": "\U0001f4dd Write",
    "edit_file": "\u270f\ufe0f Edit",
    "run_command": "\u26a1 Command",
    "glob_files": "\U0001f50d Glob",
    "grep_search": "\U0001f50e Grep",
    "start_serve": "\U0001f680 Serve",
    "run_workspace_preview": "\U0001f41e 运行/调试",
}


# Context 预算（与 VibeCodingAgent 一致）
MAX_CONTEXT_CHARS = 60000

# 轮内上下文软预算(token); 超过则本地压缩。约取模型上下文窗口的 ~70% 折算的保守值。
CODING_CONTEXT_TOKEN_BUDGET = 90_000

# Nudge 触发阈值（连续 N 轮只读不写）
NUDGE_CONSECUTIVE_READS_THRESHOLD = 2

# Nudge 消息文本（从 VibeCodingAgent 搬）
NUDGE_MESSAGE = (
    "You have been reading files without writing code. "
    "You now have enough context. IMMEDIATELY use write_file to create/update "
    "ALL component files (edit.vue, read.vue, ide.vue, setting.vue, etc.) in THIS turn. "
    "Use multiple parallel write_file calls."
)

ITERATION_NUDGE_MESSAGE = (
    "You have been reading files in an existing workspace. This is an iteration, not first generation. "
    "Use edit_file to patch only the necessary snippets from the current files. "
    "不要 write_file 整份重写已有文件；只修改必要片段。 "
    "Use write_file only for brand-new files or when the user explicitly requested a full rewrite."
)


def _truncate(s: str, maxlen: int = 300) -> str:
    if not s or len(s) <= maxlen:
        return s
    return s[:maxlen] + "..."


def _format_tool_input(tool_name: str, tool_input: dict) -> str:
    """前端 tool display 预览（从 VibeCodingAgent._format_tool_input 搬）"""
    import json as _json
    if tool_name == "read_file":
        return _truncate(str(tool_input.get("file_path", "")), 200)
    if tool_name == "glob_files":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return _truncate(f"{pattern}" + (f" in {path}" if path else ""), 200)
    if tool_name == "write_file":
        path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        lines = content.count("\n") + 1
        return f"{path} ({lines} lines)"
    if tool_name == "edit_file":
        path = tool_input.get("file_path", "")
        old = _truncate(tool_input.get("old_string", ""), 60)
        return f"{path}: {old} -> ..."
    if tool_name == "run_command":
        return _truncate(tool_input.get("command", ""), 200)
    if tool_name == "grep_search":
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path", "")
        return f"/{pattern}/" + (f" in {path}" if path else "")
    return _truncate(_json.dumps(tool_input, ensure_ascii=False), 200)


def _describe_tool_plan(tool_names: list[str], project_type: str = "") -> str:
    """LLM 无 progress note 时，自动生成简短进度笔记（从 VibeCodingAgent._describe_tool_plan 搬）"""
    if not tool_names:
        return ""
    unique = list(dict.fromkeys(tool_names))
    is_backend = project_type.startswith("backend")
    parts: list[str] = []
    if "glob_files" in unique:
        parts.append("我先快速扫一遍项目结构，确认脚手架文件布局。" if is_backend
                     else "我先快速扫一遍项目结构，确认组件骨架和可复用文件。")
    if "grep_search" in unique:
        parts.append("我会顺手搜索关键实现，避免漏掉现有约定。")
    if "read_file" in unique:
        parts.append("接着读取少量关键文件，确认当前接口写法和示例代码风格。" if is_backend
                     else "接着读取少量关键文件，确认当前组件写法和 mixin 用法。")
    if "write_file" in unique:
        parts.append("上下文已经够了，下一步开始批量写入 Java 文件。" if is_backend
                     else "上下文已经够了，下一步开始批量写入组件文件。")
    if "edit_file" in unique:
        parts.append("我会在现有文件上做定向修改，尽量减少无关变动。")
    if "run_command" in unique:
        parts.append("代码写完后我会立刻做构建校验，确认没有编译问题。")
    if not parts:
        return "我正在推进下一步实现，很快会同步新的进展。"
    return " ".join(parts[:2])


class CodingAgent(BaseAgent[dict]):
    """编码 agent — 消费需求（Stage 3 后消费 Spec）产出代码。

    继承 BaseAgent 获得通用能力：
    - LLM 循环 / tool 执行 / 事件发布 / trace 持久化
    - 中断 / 暂停 / 恢复 / suspend-resume

    子类负责提供（Stage 2.x 逐步实现）：
    - system prompt（现有 AGENT_SYSTEM_PROMPT）
    - tool 集合（tool_registry 包装）
    - user prompt 构造（vibe_agent._build_prompt 的内容）
    - 流式 LLM 调用（覆盖 _call_llm）
    - 循环检测 / nudge
    """

    agent_type = AgentType.CODING

    # ctx.input 期望字段（Stage 3 会替换成消费 Spec）：
    #   requirement: str             用户原始需求或 brainstorm 确认后的 effective_requirement
    #   conversation_summary: str    历史对话摘要（可选）
    #   max_turns: int               默认 30
    #   system_prompt: str           可选，默认用 AGENT_SYSTEM_PROMPT

    def __init__(self, context: AgentContext) -> None:
        super().__init__(context)
        # 缓存 tools，避免每轮重建
        self._cached_tools: list[Tool] | None = None

        # CodingAgent 专属状态
        self._final_result: dict[str, Any] = {}
        self._llm_said_done: bool = False

        # 循环检测
        self._consecutive_reads: int = 0
        self._read_files_set: set[str] = set()  # 已读过的 file_path

        # Context 预算跟踪
        self._total_tool_result_chars: int = 0

        # Token 预算（可被测试覆盖）
        self._context_token_budget: int = CODING_CONTEXT_TOKEN_BUDGET

        # 去重上一轮 progress note（避免多轮同 tool_calls 重复刷屏）
        self._last_progress_note: str = ""

        # 缓存 project_type（从 workspace 读一次，供 _describe_tool_plan 用）
        self._cached_project_type: str | None = None

        # 可观测（旁路）：run 生命周期由 before_run/after_run 管，
        # llm/tool step 由 on_llm_response/after_tool_call 记。None=未开 run（hook no-op）。
        self._obs_run_id: str | None = None
        self._obs_seq: int = 0

    # ══════════════════════════════════════════════════════════════
    # BaseAgent 必须实现的抽象方法
    # ══════════════════════════════════════════════════════════════

    def get_system_prompt(self) -> str:
        # 允许 ctx.input 覆盖 system prompt（测试/定制），默认用 AGENT_SYSTEM_PROMPT
        prompt = self.ctx.input.get("system_prompt")
        if prompt:
            return prompt
        return AGENT_SYSTEM_PROMPT

    def get_tools(self) -> list[Tool]:
        if self._cached_tools is None:
            self._cached_tools = build_coding_tools()
        return self._cached_tools

    def get_max_turns(self) -> int:
        return int(self.ctx.input.get("max_turns", 30))

    def _is_iteration_mode(self) -> bool:
        return bool((self.ctx.input or {}).get("is_iteration"))

    def build_initial_user_message(self) -> str:
        """构造首条 user message。

        双路径支持：
        - 旧路径（raw requirement）：输入无 spec_envelope，与 VibeCodingAgent 字节级一致
        - 新路径（Spec 驱动）：输入有 spec_envelope / spec_brief → 在 Task 后追加
          Structured Spec 段；Task 段用 intent.core_purpose 或用户原话

        AutoFix 路径：drive_coding_with_autofix 每轮把 `fix_hint` 塞进 ctx.input、
        `round_index` 塞进 ctx.extra。round_index>0 时前置一段"本次是重试"banner，
        告知 LLM workspace 里已有上轮代码、只针对性修失败的 AC。
        """
        requirement = self.ctx.input.get("requirement", "")
        summary = self.ctx.input.get("conversation_summary", "")
        # Spec 驱动时上游会塞 spec_brief；未传时保持旧行为
        spec_brief = self.ctx.input.get("spec_brief") or None
        # AutoFix 重试路径：driver.py 每轮重跑时注入
        fix_hint = self.ctx.input.get("fix_hint") or None
        round_index = int((self.ctx.extra or {}).get("round_index", 0))
        # 「在应用上定制」bound 模式：pipeline 把绑定应用上下文塞进 ctx.input["app_context"]
        # → prompt 里提示 agent 先读工具核对真实模型/菜单(工具范围后端已锁本应用)。
        app_context = self.ctx.input.get("app_context") or None

        # 获取 workspace info（project_name / project_type / files）
        workspace_info: dict[str, Any] = {}
        workspace_path: Path = Path("/tmp")  # 兜底
        if self.ctx.workspace_id:
            try:
                from app.coding.workspace import WorkspaceManager
                ws_mgr = WorkspaceManager()
                workspace_info = ws_mgr.get_workspace_info(self.ctx.workspace_id) or {}
                workspace_path = ws_mgr.get_workspace_path(self.ctx.workspace_id)
            except Exception as e:
                logger.warning("无法获取 workspace info: %s", e)

        # Spec 驱动：若 ctx.input 指定了 project_type 但 workspace 未知，用 input 覆盖
        # （让 CodingAgent 选对 workflow 模板，即使 workspace 还没创建）
        if not workspace_info.get("project_type") and self.ctx.input.get("project_type"):
            workspace_info = dict(workspace_info)
            workspace_info["project_type"] = self.ctx.input["project_type"]

        return build_user_prompt(
            requirement=requirement,
            conversation_summary=summary,
            workspace_info=workspace_info,
            workspace_path=workspace_path,
            spec_brief=spec_brief,
            fix_hint=fix_hint,
            round_index=round_index,
            app_context=app_context,
            is_iteration=self._is_iteration_mode(),
        )

    def should_terminate(self) -> tuple[bool, str]:
        # 子类终止条件：
        # - LLM 无 tool_call（主动结束）
        # - 未来可加：所有 scene 文件已写 + build 成功等
        if self._llm_said_done:
            return True, "LLM 无 tool_call，判定完成"
        return False, ""

    async def finalize(self) -> dict:
        """产出结果。MVP 阶段返回空 dict，Stage 3 会扩展（files_written / scene_info）。"""
        return self._final_result

    # ══════════════════════════════════════════════════════════════
    # Hook 覆盖（Stage 2.x 会逐步填充）
    # ══════════════════════════════════════════════════════════════

    def _obs_app_id(self) -> str | None:
        """best-effort 取绑定应用 id 给可观测 run（headroom；取不到也无妨）。"""
        extra = self.ctx.extra or {}
        if extra.get("bound_apaas_app_id"):
            return str(extra["bound_apaas_app_id"])
        app_context = (self.ctx.input or {}).get("app_context") or {}
        return app_context.get("apaas_app_id") or None

    async def before_run(self) -> None:
        """run 开始：开一条可观测 run（旁路，recorder 自吞异常，绝不反噬主流程）。"""
        await super().before_run()
        self._obs_run_id = await recorder.start_run(
            agent_type="coding",
            tenant_id=self.ctx.tenant_id,
            user_id=self.ctx.user_id,
            session_id=self.ctx.conversation_id,  # coding 以 conversation 为会话维度
            app_id=self._obs_app_id(),
            model=self.ctx.model,
        )
        self._obs_seq = 0

    async def after_run(self, result: AgentResult) -> None:
        """run 结束：收尾可观测 run（状态映射到 success/error/aborted）。"""
        if self._obs_run_id:
            status = {
                AgentStatus.COMPLETED: "success",
                AgentStatus.FAILED: "error",
                AgentStatus.ABORTED: "aborted",
                AgentStatus.PAUSED: "success",  # 暂停=本轮正常结束、等用户答，不算失败
            }.get(result.status, "success")
            await recorder.end_run(
                self._obs_run_id, status=status, error=result.error_message
            )
        await super().after_run(result)

    async def on_llm_response(self, response) -> None:
        """LLM 响应后的处理：
        1. 可观测：先记一条 llm step（token 来自流式 _call_llm 填的 usage）
        2. 如果没 tool_call → 标记 done
        3. 如果有 tool_call 但 content 为空 → 自动生成简短 progress note 推送（避免用户看到空白轮）
        """
        # 埋点放在最前面，先于下面「无 tool_call 即 return」的早退，保证每轮都记到。
        if self._obs_run_id:
            self._obs_seq += 1
            await recorder.record_step(
                self._obs_run_id, step_type="llm", seq=self._obs_seq,
                prompt_tokens=response.tokens_input or None,
                completion_tokens=response.tokens_output or None,
            )

        if not response.tool_calls:
            self._llm_said_done = True
            self._final_result["final_text"] = response.content
            return

        # 有 tool_calls 但没 content：生成进度笔记
        if not (response.content or "").strip():
            tool_names = [tc.name for tc in response.tool_calls]
            project_type = self._get_project_type()
            note = _describe_tool_plan(tool_names, project_type)
            # 去重（避免连续多轮同 tool_names 生成同 note 刷屏）
            if note and note != self._last_progress_note:
                # 发 aggregate（agent_thinking）而非 delta：note 是事后合成的
                # 完整文本，不存在"后续 delta 继续追加"的语义。
                # 若发 delta，前端延续上一条未封口的 thinking 条目把 note 拼上去，
                # 造成"思考卡尾部突然多出一段和上下文不连贯的文字"。
                # 走 aggregate：前端 sealed 逻辑自动把 note 渲染成独立条目。
                await self._publish("agent_thinking", {"content": note})
                self._last_progress_note = note

    async def on_each_turn(self, turn: int) -> None:
        """每轮循环检测：连续 N 轮只读不写 → 注入 nudge 消息。"""
        if self._consecutive_reads >= NUDGE_CONSECUTIVE_READS_THRESHOLD:
            nudge_msg = {
                "role": "user",
                "content": ITERATION_NUDGE_MESSAGE if self._is_iteration_mode() else NUDGE_MESSAGE,
            }
            self._messages.append(nudge_msg)
            self._consecutive_reads = 0
            await self._trace(TraceEventType.NUDGE, {
                "reason": "consecutive_reads_without_write",
                "turn": turn,
            })
            await self._on_message_appended_safe(nudge_msg)

    async def on_context_overflow(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Context 压缩 — 按 token 预算两步本地压缩，轮内不调 LLM。

        第一道（便宜）: clean_tool_results，清理旧工具结果，最近 4 条保留完整。
        若仍超过 _context_token_budget，第二道: ContextCompactor.compact 本地压缩
        （去代码块 + 保留最近几轮），不发 LLM 请求。

        跨轮的 LLM 摘要由 pipeline 出轮做（Task 4+）。
        """
        from app.context_compact import ContextCompactor
        from app.agents.token_estimate import estimate_tokens

        # 第一道（便宜）: 清旧工具结果
        try:
            cleaned = ContextCompactor.clean_tool_results(messages, keep_recent=4)
        except Exception as e:
            logger.warning("ContextCompactor.clean_tool_results unavailable, skip: %s", e)
            cleaned = list(messages)

        if estimate_tokens(cleaned) <= self._context_token_budget:
            return cleaned

        # 第二道: 仍超预算 → 本地 compact（不传 llm_cfg → 纯本地，去代码块 + 保留最近 max_rounds 轮）
        try:
            return ContextCompactor().compact(cleaned, mode="coding_with_workspace")
        except Exception as e:
            logger.warning("ContextCompactor.compact failed, returning cleaned: %s", e)
            return cleaned

    def token_usage_snapshot(self) -> dict:
        """当前 token 用量快照:累计 LLM 消耗 + 当前上下文占用 + 预算。供 done 事件透前端(#2)。"""
        from app.agents.token_estimate import estimate_tokens
        return {
            "tokens_input": self._tokens_input,
            "tokens_output": self._tokens_output,
            "context_tokens": estimate_tokens(self._messages),
            "context_budget": self._context_token_budget,
        }

    async def before_tool_call(self, tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
        """tool 执行前：发前端 agent_tool 事件（带 tool_display 预览）。"""
        preview = _format_tool_input(tool.name, args)
        # 字段名与 VibeCodingAgent 原格式对齐：key 用 "tool"（不是 "name"）
        event_data: dict[str, Any] = {
            "tool": tool.name,
            "tool_display": TOOL_ICONS.get(tool.name, tool.name),
            "input_preview": preview,
        }
        # write_file / edit_file 透传内容给前端展示。
        # edit_file 透传 old_string + new_string,前端据此渲染红绿 diff(对齐 Claude Code)。
        if tool.name == "write_file":
            event_data["input"] = {
                "file_path": args.get("file_path", ""),
                "content": args.get("content") or "",
            }
        elif tool.name == "edit_file":
            event_data["input"] = {
                "file_path": args.get("file_path", ""),
                "old_string": args.get("old_string") or "",
                "new_string": args.get("new_string") or "",
                "content": args.get("new_string") or "",  # 兼容旧前端
            }
        await self._publish("agent_tool", event_data)
        return args

    async def after_tool_call(self, tool: Tool, result: ToolResult) -> ToolResult:
        """tool 执行后：
        1. 更新 consecutive_reads 计数（read 家族 +1，write 家族清零）
        2. 更新 read_files_set
        3. 动态截断 tool result（按剩余 context budget）
        4. 发 agent_result 事件
        """
        tool_name = tool.name

        # consecutive_reads 计数
        if tool_name in ("write_file", "edit_file", "run_command"):
            self._consecutive_reads = 0
        elif tool_name in ("read_file", "glob_files", "grep_search"):
            # 只在 read 族上 +1
            self._consecutive_reads += 1

        # 已读文件集合（用于 Stage 4 可能加的 dedup）
        if tool_name == "read_file":
            fpath = ""
            # 从最近 tool_history 取 args（_handle_tool_calls 会写入）
            if self._tool_history:
                last = self._tool_history[-1]
                if last.get("name") == tool_name:
                    fpath = (last.get("args") or {}).get("file_path", "") or ""
            if fpath:
                self._read_files_set.add(fpath)

        # 动态截断
        content = result.content or ""
        remaining_budget = MAX_CONTEXT_CHARS - self._total_tool_result_chars
        max_result_len = max(2000, min(8000, remaining_budget // 2))
        if len(content) > max_result_len:
            truncated = content[:max_result_len] + f"\n... [truncated, {len(content)} chars total]"
            # 返回副本（不改原 ToolResult）
            result = ToolResult(
                success=result.success,
                content=truncated,
                data=result.data,
                error=result.error,
                emit_event=result.emit_event,
                should_pause=result.should_pause,
            )
        self._total_tool_result_chars += len(result.content or "")

        # 发 agent_result 事件（兼容 VibeCodingAgent 旧格式）
        await self._publish("agent_result", {
            "tool": tool_name,
            "tool_display": TOOL_ICONS.get(tool_name, tool_name),
            "output_preview": _truncate(result.content or "", 500),
            "is_error": not result.success,
        })

        # 可观测：记一条 tool step（成功/失败都记；失败带错误文本）
        if self._obs_run_id:
            self._obs_seq += 1
            await recorder.record_step(
                self._obs_run_id, step_type="tool", seq=self._obs_seq,
                tool_name=tool_name,
                status="success" if result.success else "error",
                result_text=None if result.success
                else (result.error or result.content or "")[:2000],
            )

        return result

    def _get_project_type(self) -> str:
        """缓存 project_type（从 workspace_info 读，默认空字符串）。"""
        if self._cached_project_type is None:
            try:
                from app.coding.workspace import WorkspaceManager
                info = WorkspaceManager().get_workspace_info(self.ctx.workspace_id) if self.ctx.workspace_id else {}
                self._cached_project_type = (info.get("project_type", "") or "").lower()
            except Exception:
                self._cached_project_type = ""
        return self._cached_project_type

    # ══════════════════════════════════════════════════════════════
    # LLM 流式调用（覆盖 BaseAgent._call_llm）
    # ══════════════════════════════════════════════════════════════

    async def _call_llm(self) -> LLMResponse:
        """流式调用 LLM，实时推送 thinking/tool_calls delta，最后返回完整 LLMResponse。

        关键行为：
        - 使用 LLMClient.chat_completion_stream(tools=...)
        - content_delta → publish "coding.agent_thinking_delta" 事件
        - reasoning_content → publish "coding.agent_thinking_delta" 事件（same channel）
        - tool_calls delta → 累积到完整 tool_call（OpenAI 风格）
        - 最后组装 LLMResponse 返回
        """
        if self.ctx.llm_client is None:
            raise RuntimeError("AgentContext.llm_client is not set")

        tools_openai = [t.to_openai_function() for t in self.get_tools()]

        # 记录 request trace
        await self._trace(TraceEventType.LLM_REQUEST, {
            "model": self.ctx.model,
            "messages_count": len(self._messages),
            "tools_count": len(tools_openai),
        })

        start_ts = time.time()
        full_content: str = ""
        reasoning_content: str = ""
        finish_reason: str | None = None
        # usage chunk（include_usage 开启后，网关在 [DONE] 前回的那条 choices 为空、带 usage 的 chunk）
        usage_data: dict | None = None
        # 按 OpenAI 流式 tool_calls 格式累积：index → {id, name, arguments}
        tool_calls_map: dict[int, dict[str, str]] = {}

        try:
            async for chunk_raw in self.ctx.llm_client.chat_completion_stream(
                messages=self._messages,
                max_tokens=int(self.ctx.input.get("max_tokens", 8192)),
                tools=tools_openai or None,
            ):
                try:
                    chunk = json.loads(chunk_raw) if isinstance(chunk_raw, str) else chunk_raw
                except Exception:
                    continue

                # usage chunk：choices 为空、带 usage（include_usage 开启后 [DONE] 前到达）。
                # 必须在 `if not choices: continue` 之前捕获，否则会被空 choices 短路掉。
                if chunk.get("usage"):
                    usage_data = chunk["usage"]

                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}

                # 1. content delta → 实时推给前端
                text = delta.get("content")
                if text:
                    full_content += text
                    await self._emit_stream_delta({"content": text})

                # 2. reasoning delta（thinking 模式）
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    reasoning_content += reasoning
                    await self._emit_stream_delta({"reasoning_content": reasoning})

                # 3. tool_calls delta 累积
                tc_list = delta.get("tool_calls") or []
                for tc_delta in tc_list:
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {"id": "", "name": "", "arguments": ""}
                    entry = tool_calls_map[idx]
                    if tc_delta.get("id"):
                        entry["id"] = tc_delta["id"]
                    fn = tc_delta.get("function") or {}
                    if fn.get("name"):
                        entry["name"] = fn["name"]
                    if "arguments" in fn:
                        entry["arguments"] += fn["arguments"] or ""

                # 4. finish_reason
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
        except Exception as e:
            # 让 BaseAgent 的重试 wrapper 接住（对 httpx timeout / 429 / 5xx 重试）
            raise

        duration_ms = int((time.time() - start_ts) * 1000)

        # 累积完的 tool_calls 按 index 排序
        assembled_tool_calls: list[ToolCall] = []
        for idx in sorted(tool_calls_map.keys()):
            entry = tool_calls_map[idx]
            if not entry["name"]:
                continue  # 跳过空 entry
            args_json = entry["arguments"] or "{}"
            # 校验 JSON 合法性；非法则传空 dict（避免后续 LLM API 400）
            try:
                json.loads(args_json)
            except Exception:
                logger.warning("Invalid tool_call args for %s: %r", entry["name"], args_json[:200])
                args_json = "{}"
            assembled_tool_calls.append(ToolCall(
                id=entry["id"] or f"call_{idx}",
                name=entry["name"],
                arguments_json=args_json,
            ))

        # 从 usage chunk 抠 token（网关透传 OpenAI 风格 prompt/completion_tokens）
        usage_data = usage_data or {}
        tokens_input = int(usage_data.get("prompt_tokens") or 0)
        tokens_output = int(usage_data.get("completion_tokens") or 0)

        response = LLMResponse(
            content=full_content,
            tool_calls=assembled_tool_calls,
            finish_reason=finish_reason,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            raw={"streamed": True, "usage": usage_data or None},
        )

        # 与 BaseAgent 非流式 _call_llm 一致：在调用点内累计本 agent 的总 token
        # （loop 的 _call_llm_with_retry 调用点不另行累计，故此处累计不会重复计数）
        self._tokens_input += tokens_input
        self._tokens_output += tokens_output

        await self._trace(TraceEventType.LLM_RESPONSE, {
            "content_preview": full_content[:200],
            "reasoning_preview": reasoning_content[:200] if reasoning_content else "",
            "tool_calls": [
                {"name": tc.name, "args_preview": tc.arguments_json[:200]}
                for tc in assembled_tool_calls
            ],
            "finish_reason": finish_reason,
        }, tokens_input=tokens_input, tokens_output=tokens_output, duration_ms=duration_ms)

        # 流式结束后，发 aggregated thinking 事件（会落 DB）
        # 用途：
        # 1. 刷新后回放能重建完整思考文本（delta 事件是 ephemeral 不存 DB）
        # 2. 前端收到 aggregate 会把对应 thinking 条目置 sealed=true，
        #    阻止下一轮的 delta 继续往这条上拼（否则会出现"条目文本跨轮累积"的 bug）
        # 拆分: content(答案/narration)与 reasoning(思维链)各发一个 aggregate, 不再拼接。
        # 前端按 reasoning 标志分流: content → thinking 卡, reasoning → 折叠「思考过程」卡。
        if full_content:
            await self._publish("agent_thinking", {"content": full_content})
        if reasoning_content:
            await self._publish("agent_thinking", {"content": reasoning_content, "reasoning": True})

        return response

    async def _emit_stream_delta(self, delta: dict[str, Any]) -> None:
        """把流式 delta 发布为前端事件 + 触发 on_stream_delta hook。

        事件命名：coding.agent_thinking_delta（兼容 VibeCodingAgent 旧格式）。
        """
        if delta.get("content"):
            await self._publish("agent_thinking_delta", {"content": delta["content"]})
        elif delta.get("reasoning_content"):
            await self._publish("agent_thinking_delta", {
                "content": delta["reasoning_content"],
                "reasoning": True,
            })
        try:
            await self.on_stream_delta(delta)
        except Exception as e:
            logger.warning("on_stream_delta hook failed: %s", e)

    # ══════════════════════════════════════════════════════════════
    # 自定义状态序列化（Stage 2.4 完善）
    # ══════════════════════════════════════════════════════════════

    def _serialize_custom_state(self) -> dict[str, Any]:
        return {
            "final_result": self._final_result,
            "llm_said_done": self._llm_said_done,
            "consecutive_reads": self._consecutive_reads,
            "read_files": sorted(self._read_files_set),
            "total_tool_result_chars": self._total_tool_result_chars,
            "last_progress_note": self._last_progress_note,
            "cached_project_type": self._cached_project_type,
        }

    def _deserialize_custom_state(self, data: dict[str, Any]) -> None:
        self._final_result = data.get("final_result") or {}
        self._llm_said_done = bool(data.get("llm_said_done"))
        self._consecutive_reads = int(data.get("consecutive_reads") or 0)
        self._read_files_set = set(data.get("read_files") or [])
        self._total_tool_result_chars = int(data.get("total_tool_result_chars") or 0)
        self._last_progress_note = data.get("last_progress_note") or ""
        self._cached_project_type = data.get("cached_project_type")
