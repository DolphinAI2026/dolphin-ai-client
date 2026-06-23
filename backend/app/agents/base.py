"""BaseAgent — 所有 agent 共享的运行时基类。

提供：
- LLM 调用循环
- Tool 注册 + 执行
- 事件发布（SSE）
- Trace 持久化
- 状态机（IDLE → RUNNING → {PAUSED, COMPLETED, FAILED, ABORTED}）
- 中断 / 取消 / 暂停-恢复
- 错误重试
- 13 个 hook 点（子类可覆盖）

子类需要实现：
- get_system_prompt()
- get_tools()
- get_max_turns()
- build_initial_user_message()
- should_terminate()
- finalize()

可选覆盖的 hook：
- before_run / after_run
- on_each_turn
- before_tool_call / after_tool_call
- on_llm_response
- on_max_turns_exceeded
- on_message_appended
- on_context_overflow
- on_stream_delta
- on_product_validation_failed
- on_retry
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from abc import ABC, abstractmethod
from typing import Any, Generic, Optional

from app.agents.types import (
    AgentContext,
    AgentResult,
    AgentStatus,
    AgentType,
    LLMResponse,
    ProductT,
    StopReason,
    Tool,
    ToolCall,
    ToolResult,
    TraceEventType,
)

logger = logging.getLogger(__name__)


def describe_exception(e: BaseException) -> str:
    """把异常转成给用户/前端看的非空描述。

    超时类异常(asyncio.TimeoutError / httpx.ReadTimeout 等)str(e) 常为空，
    若直接用 str(e) 会经 adapter 回退成无信息量的「unknown error」。空则退回类型名，
    保证错误永远可读、可定位。
    """
    msg = str(e).strip()
    return msg if msg else type(e).__name__


def _short_args_preview(args: dict[str, Any], limit: int = 140) -> str:
    """给 `tool_call` SSE 事件做一个人看得懂的参数预览。

    优先挑可读字段（query / path / file_path / ac_index 等），兜底是截断的 JSON。
    长字段（content / evidence 之类）直接略掉，不然会挤掉有用信息。
    """
    if not args:
        return ""
    # 常用字段优先（挑一个最能代表"干了什么"的字段；ac_index 不在这里——
    # check_ac 的 ac_result 行已经展示了 "AC #N"，这里再重复没意义）
    for k in ("query", "path", "file_path", "glob", "pattern", "url", "command"):
        if k in args and args[k] not in (None, ""):
            v = args[k]
            s = str(v)
            return s if len(s) <= limit else s[:limit] + "…"
    # 兜底：压成一行 JSON，跳掉 content/evidence/new_string/old_string 等大字段
    skip = {"content", "evidence", "new_string", "old_string"}
    compact = {k: v for k, v in args.items() if k not in skip}
    try:
        s = json.dumps(compact, ensure_ascii=False)
    except Exception:
        s = str(compact)
    return s if len(s) <= limit else s[:limit] + "…"


class BaseAgent(ABC, Generic[ProductT]):
    """所有 agent 的抽象基类"""

    # —— 子类必须设置 —— #
    agent_type: AgentType = AgentType.SYSTEM

    def __init__(self, context: AgentContext) -> None:
        self.ctx = context
        self.status = AgentStatus.IDLE

        # 中断/暂停 flag
        self._cancel_flag = asyncio.Event()
        self._pause_flag = asyncio.Event()
        self._resume_event = asyncio.Event()  # pause 时等待 resume

        # 运行状态
        self._turn = 0
        self._tokens_input = 0
        self._tokens_output = 0
        self._messages: list[dict[str, Any]] = []       # LLM 对话 messages
        self._tool_history: list[dict[str, Any]] = []   # tool 调用记录（用于循环检测）
        self._stop_reason: Optional[StopReason] = None
        self._error_message: Optional[str] = None

    # ══════════════════════════════════════════════════════════════
    # 子类必须实现
    # ══════════════════════════════════════════════════════════════

    @abstractmethod
    def get_system_prompt(self) -> str: ...

    @abstractmethod
    def get_tools(self) -> list[Tool]: ...

    @abstractmethod
    def get_max_turns(self) -> int: ...

    @abstractmethod
    def build_initial_user_message(self) -> str:
        """从 ctx.input 构造首条用户消息"""
        ...

    @abstractmethod
    def should_terminate(self) -> tuple[bool, str]:
        """每轮循环开始时检查是否应结束。返回 (是否终止, 原因)"""
        ...

    @abstractmethod
    async def finalize(self) -> ProductT:
        """循环结束后，产出最终物。不 raise 时表示成功产出。"""
        ...

    # ══════════════════════════════════════════════════════════════
    # 可选 hook（默认空实现）
    # ══════════════════════════════════════════════════════════════

    async def before_run(self) -> None:
        """run() 开始前（第一个 LLM 调用之前）"""
        pass

    async def after_run(self, result: AgentResult[ProductT]) -> None:
        """run() 结束后（无论成败）"""
        pass

    async def on_each_turn(self, turn: int) -> None:
        """每轮循环开始 — 循环检测 / nudge 通常在这里做"""
        pass

    async def before_tool_call(self, tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
        """tool 执行前。子类可修改 args 并返回。默认原样返回。"""
        return args

    async def after_tool_call(self, tool: Tool, result: ToolResult) -> ToolResult:
        """tool 执行后。子类可修改 result 并返回。默认原样返回。"""
        return result

    async def on_llm_response(self, response: LLMResponse) -> None:
        """LLM 响应解析后"""
        pass

    async def on_max_turns_exceeded(self) -> None:
        """轮次耗尽时 — 子类可实现降级产出策略"""
        pass

    async def on_message_appended(self, msg: dict[str, Any]) -> None:
        """消息追加到 history 后"""
        pass

    async def on_context_overflow(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """上下文接近超长。子类可返回压缩后的 messages。默认不压缩。"""
        return messages

    async def on_stream_delta(self, delta: dict[str, Any]) -> None:
        """流式 token 到达（仅流式模式）"""
        pass

    async def on_product_validation_failed(self, errors: list[str]) -> bool:
        """产物不合 schema 时。返回 True 表示允许重试 finalize；False 终结流程。"""
        return False

    async def on_retry(self, attempt: int, error: Exception) -> None:
        """LLM 重试前"""
        pass

    # ══════════════════════════════════════════════════════════════
    # 主循环 (不要被子类覆盖)
    # ══════════════════════════════════════════════════════════════

    async def run(self) -> AgentResult[ProductT]:
        result: AgentResult[ProductT] = AgentResult(status=AgentStatus.IDLE)
        # 判断是 fresh start 还是 resume：
        # resume 场景 —— _messages 已经由 from_snapshot 恢复（非空），_turn 也已恢复
        # fresh 场景 —— 首次构造 agent，_messages 是空 list，_turn=0
        is_resume = bool(self._messages)
        try:
            if is_resume:
                await self._publish("resumed", {
                    "session_id": self.ctx.session_id,
                    "turn": self._turn,
                    "messages_count": len(self._messages),
                })
            else:
                await self._publish("start", {"session_id": self.ctx.session_id})
            await self.before_run()

            prev_status = self.status
            self.status = AgentStatus.RUNNING
            await self._trace_state_change(prev_status, AgentStatus.RUNNING)

            if not is_resume:
                # 构造首条消息（fresh start）
                self._messages = [
                    {"role": "system", "content": self.get_system_prompt()},
                    {"role": "user", "content": self.build_initial_user_message()},
                ]
                await self._on_message_appended_safe(self._messages[-1])
            else:
                # resume 场景：历史已由 from_snapshot 恢复，追加当前 turn 的用户消息
                new_user_msg = {"role": "user", "content": self.build_initial_user_message()}
                self._messages.append(new_user_msg)
                await self._on_message_appended_safe(self._messages[-1])

            max_turns = self.get_max_turns()

            # —— 主循环 —— #
            while self._turn < max_turns:
                # 1. 中断检查
                if self._cancel_flag.is_set():
                    self._stop_reason = StopReason.CANCELLED
                    self.status = AgentStatus.ABORTED
                    await self._publish("aborted", {"reason": "user_cancel"})
                    break

                # 2. 暂停检查
                #
                # 语义：某个 tool 返回 should_pause=True（例如 ask_user 等用户答）→
                # `_handle_tool_calls` 会调 self.pause() 设置 _pause_flag。
                # 这里检测到后**立即退出 run()**，让上层 driver 拿到 PAUSED 状态
                # → driver 调用 suspend_session 落 snapshot 到 DB → HTTP 连接释放。
                # 用户回答后，新的请求构造新的 agent（from_snapshot + 注入 tool_result）
                # → 再调 run()（is_resume=True 接续跑）。
                #
                # 之前这里 `await _wait_for_resume_or_cancel()` 同进程阻塞，导致
                # driver 永远拿不到 run() 返回值 → snapshot 从不保存 → resume 无效。
                if self._pause_flag.is_set():
                    self.status = AgentStatus.PAUSED
                    await self._trace_state_change(AgentStatus.RUNNING, AgentStatus.PAUSED)
                    await self._publish("paused", {"session_id": self.ctx.session_id})
                    self._stop_reason = StopReason.PAUSED
                    break

                # 3. 子类 hook：循环检测 / nudge
                await self.on_each_turn(self._turn)

                # 3b. Context 压缩（子类可覆盖返回压缩后的 messages）
                try:
                    new_messages = await self.on_context_overflow(self._messages)
                    if new_messages is not None and new_messages is not self._messages:
                        self._messages = new_messages
                except Exception as e:
                    logger.warning("on_context_overflow hook failed: %s", e)

                # 4. 终止检查
                terminate, reason = self.should_terminate()
                if terminate:
                    self._stop_reason = StopReason.TERMINATE_CONDITION_MET
                    await self._trace(TraceEventType.STATE_CHANGE, {"terminate_reason": reason})
                    break

                # 5. 调 LLM（带重试）
                try:
                    response = await self._call_llm_with_retry()
                except Exception as e:
                    self._stop_reason = StopReason.ERROR
                    self._error_message = describe_exception(e)
                    self.status = AgentStatus.FAILED
                    await self._trace(TraceEventType.ERROR, {
                        "error_type": type(e).__name__,
                        "message": str(e),
                        "traceback": traceback.format_exc(),
                    })
                    await self._publish("failed", {"error": describe_exception(e)})
                    break

                await self.on_llm_response(response)

                # 6. 处理响应
                if response.tool_calls:
                    # 追加 assistant message（含 tool_calls）
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": tc.arguments_json},
                            }
                            for tc in response.tool_calls
                        ],
                    }
                    self._messages.append(assistant_msg)
                    await self._on_message_appended_safe(assistant_msg)

                    # 执行 tool calls（并行）
                    should_pause = await self._handle_tool_calls(response.tool_calls)
                    if should_pause:
                        self.pause()
                else:
                    # LLM 无 tool_call → 追加 content 后结束循环
                    self._messages.append({"role": "assistant", "content": response.content})
                    await self._on_message_appended_safe(self._messages[-1])
                    self._stop_reason = StopReason.LLM_NO_TOOL_CALL
                    break

                self._turn += 1
            else:
                # while 正常退出（turn >= max_turns）
                self._stop_reason = StopReason.MAX_TURNS_EXCEEDED
                await self._trace(TraceEventType.STATE_CHANGE, {"reason": "max_turns_exceeded"})
                await self.on_max_turns_exceeded()

            # —— 产出 —— #
            # PAUSED 场景不走 finalize（agent 没结束，只是等用户回答）
            product: Optional[ProductT] = None
            if self.status == AgentStatus.PAUSED:
                pass
            elif self.status not in (AgentStatus.ABORTED, AgentStatus.FAILED):
                try:
                    product = await self.finalize()
                    self.status = AgentStatus.COMPLETED
                except Exception as e:
                    self.status = AgentStatus.FAILED
                    self._error_message = f"finalize failed: {e}"
                    await self._trace(TraceEventType.ERROR, {
                        "stage": "finalize",
                        "error_type": type(e).__name__,
                        "message": str(e),
                    })

            # 构造 result
            result = AgentResult(
                status=self.status,
                stop_reason=self._stop_reason,
                product=product,
                turns_used=self._turn,
                tokens_input=self._tokens_input,
                tokens_output=self._tokens_output,
                error_message=self._error_message,
                snapshot=self.to_snapshot(),
            )

            await self._publish("done" if self.status == AgentStatus.COMPLETED else self.status.value, {
                "session_id": self.ctx.session_id,
                "status": self.status.value,
                "turns_used": self._turn,
            })
            return result

        except Exception as e:
            logger.exception("BaseAgent.run unexpected error")
            self.status = AgentStatus.FAILED
            self._error_message = describe_exception(e)
            await self._trace(TraceEventType.ERROR, {
                "error_type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            })
            await self._publish("failed", {"error": describe_exception(e)})
            result = AgentResult(
                status=AgentStatus.FAILED,
                stop_reason=StopReason.ERROR,
                turns_used=self._turn,
                tokens_input=self._tokens_input,
                tokens_output=self._tokens_output,
                error_message=describe_exception(e),
            )
            return result
        finally:
            try:
                await self.after_run(result)
            except Exception as e:
                logger.warning("after_run hook failed: %s", e)

    # ══════════════════════════════════════════════════════════════
    # 中断控制
    # ══════════════════════════════════════════════════════════════

    def cancel(self) -> None:
        """取消 agent。下一轮循环会检测到并退出。"""
        self._cancel_flag.set()
        self._resume_event.set()  # 唤醒 pause 状态

    def pause(self) -> None:
        """请求 agent 暂停。下一轮开始时 agent 会挂起等 resume。"""
        self._pause_flag.set()
        self._resume_event.clear()

    def resume(self) -> None:
        """唤醒 paused 的 agent"""
        self._pause_flag.clear()
        self._resume_event.set()

    async def _wait_for_resume_or_cancel(self) -> None:
        await self._resume_event.wait()

    # ══════════════════════════════════════════════════════════════
    # Suspend / Resume：序列化 agent 状态用于跨 HTTP 请求恢复
    # ══════════════════════════════════════════════════════════════

    def to_snapshot(self) -> dict[str, Any]:
        """序列化 agent 状态。子类可通过 _serialize_custom_state 添加字段。"""
        return {
            "agent_type": self.agent_type.value,
            "session_id": self.ctx.session_id,
            "status": self.status.value,
            "turn": self._turn,
            "messages": self._messages,
            "tool_history": self._tool_history,
            "tokens_input": self._tokens_input,
            "tokens_output": self._tokens_output,
            "stop_reason": self._stop_reason.value if self._stop_reason else None,
            "custom": self._serialize_custom_state(),
        }

    @classmethod
    def from_snapshot(cls, ctx: AgentContext, snapshot: dict[str, Any]) -> "BaseAgent":
        """从 snapshot 恢复 agent 状态。子类构造器应接受 AgentContext。"""
        agent = cls(ctx)
        try:
            agent.status = AgentStatus(snapshot.get("status", "idle"))
        except Exception:
            agent.status = AgentStatus.IDLE
        agent._turn = snapshot.get("turn", 0)
        agent._messages = list(snapshot.get("messages") or [])
        agent._tool_history = list(snapshot.get("tool_history") or [])
        agent._tokens_input = snapshot.get("tokens_input", 0)
        agent._tokens_output = snapshot.get("tokens_output", 0)
        sr = snapshot.get("stop_reason")
        agent._stop_reason = StopReason(sr) if sr else None
        agent._deserialize_custom_state(snapshot.get("custom") or {})
        return agent

    def _serialize_custom_state(self) -> dict[str, Any]:
        """子类覆盖：把子类特有状态序列化到 dict"""
        return {}

    def _deserialize_custom_state(self, data: dict[str, Any]) -> None:
        """子类覆盖：从 dict 恢复子类特有状态"""
        pass

    # ══════════════════════════════════════════════════════════════
    # 内部：LLM 调用 + 重试
    # ══════════════════════════════════════════════════════════════

    async def _call_llm_with_retry(self, max_retries: int = 3) -> LLMResponse:
        last_error: Optional[Exception] = None
        compacted_once = False
        for attempt in range(max_retries):
            try:
                return await self._call_llm()
            except Exception as e:
                last_error = e
                # 上下文超限: 压缩一次再重试（不消耗通用重试预算），仅压一次防死循环
                if self._is_context_length_error(e) and not compacted_once:
                    compacted_once = True
                    try:
                        self._messages = await self.on_context_overflow(self._messages)
                        await self._trace(TraceEventType.RETRY, {
                            "attempt": attempt + 1,
                            "error": "context_length → compacted",
                            "wait_seconds": 0,
                        })
                        continue
                    except Exception as ce:
                        logger.warning("context-length compact failed: %s", ce)
                        raise
                # 判断是否可重试（429 / timeout / 5xx）
                if not self._is_retryable(e) or attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                await self.on_retry(attempt + 1, e)
                await self._trace(TraceEventType.RETRY, {
                    "attempt": attempt + 1,
                    "error": str(e),
                    "wait_seconds": wait,
                })
                await asyncio.sleep(wait)
        raise last_error or RuntimeError("LLM retry exhausted")

    @staticmethod
    def _is_context_length_error(error: Exception) -> bool:
        """识别上下文超限类错误（需压缩后重试，而非原样重发）。"""
        import httpx
        msg = str(error).lower()
        if any(k in msg for k in ("context length", "context_length_exceeded",
                                  "maximum context", "too many tokens", "reduce the length")):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in {413}
        return False

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        """判断异常是否可重试"""
        import httpx
        if isinstance(error, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.NetworkError)):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            code = error.response.status_code
            return code in {429, 502, 503, 504, 529}
        # TimeoutError / asyncio.TimeoutError
        if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
            return True
        return False

    async def _call_llm(self) -> LLMResponse:
        """执行实际 LLM 调用。子类可覆盖（如要用特殊 provider）。

        默认实现：用 ctx.llm_client.chat_completion() 走非流式。
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
        raw = await self.ctx.llm_client.chat_completion(
            messages=self._messages,
            model=self.ctx.model,
            tools=tools_openai or None,
        )
        duration_ms = int((time.time() - start_ts) * 1000)

        # 解析 OpenAI 风格响应
        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = raw.get("usage", {})

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments_json=fn.get("arguments", "{}"),
            ))

        response = LLMResponse(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            tokens_input=usage.get("prompt_tokens") or 0,
            tokens_output=usage.get("completion_tokens") or 0,
            raw=raw,
        )

        self._tokens_input += response.tokens_input
        self._tokens_output += response.tokens_output

        await self._trace(TraceEventType.LLM_RESPONSE, {
            "content_preview": response.content[:200],
            "tool_calls": [{"name": tc.name, "args_preview": tc.arguments_json[:200]} for tc in tool_calls],
            "finish_reason": response.finish_reason,
        }, tokens_input=response.tokens_input, tokens_output=response.tokens_output, duration_ms=duration_ms)

        return response

    # ══════════════════════════════════════════════════════════════
    # 内部：Tool 执行
    # ══════════════════════════════════════════════════════════════

    async def _handle_tool_calls(self, tool_calls: list[ToolCall]) -> bool:
        """并行执行 tool calls，反馈给 LLM。返回是否需要 pause（如 ask_user）。"""
        tools_map = {t.name: t for t in self.get_tools()}

        # 并行执行
        async def _exec_one(tc: ToolCall) -> tuple[ToolCall, ToolResult]:
            tool = tools_map.get(tc.name)
            if tool is None:
                return tc, ToolResult(
                    success=False,
                    content=f"Error: tool '{tc.name}' not found",
                    error="tool_not_found",
                )
            try:
                args = tc.arguments
                args = await self.before_tool_call(tool, args)
                await self._trace(TraceEventType.TOOL_CALL, {"tool": tool.name, "args": args})
                # 带一个 args 预览给前端做"代码搜索: xxx"这种展示；
                # coding agent 自己在 before_tool_call 里发了更富的 agent_tool 事件，
                # 这里的 tool_call 事件对它是冗余但无害。
                await self._publish(
                    "tool_call",
                    {"tool": tool.name, "input_preview": _short_args_preview(args)},
                )

                start_ts = time.time()
                result = await tool.execute(args, self.ctx)
                duration_ms = int((time.time() - start_ts) * 1000)

                result = await self.after_tool_call(tool, result)

                await self._trace(TraceEventType.TOOL_RESULT, {
                    "tool": tool.name,
                    "success": result.success,
                    "content_preview": (result.content or "")[:300],
                    "error": result.error,
                }, duration_ms=duration_ms)
                await self._publish("tool_result", {
                    "tool": tool.name,
                    "success": result.success,
                })

                # tool 产生的面向用户事件
                if result.emit_event:
                    await self._publish(
                        result.emit_event.get("type", "tool_event"),
                        result.emit_event.get("data", {}),
                    )

                self._tool_history.append({
                    "name": tool.name,
                    "args": args,
                    "success": result.success,
                    "error": result.error,
                })
                return tc, result
            except Exception as e:
                logger.exception("Tool %s execution failed", tc.name)
                return tc, ToolResult(
                    success=False,
                    content=f"Tool execution error: {e}",
                    error=str(e),
                )

        results = await asyncio.gather(*[_exec_one(tc) for tc in tool_calls])

        # 反馈给 LLM
        should_pause = False
        for tc, res in results:
            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": res.content,
            }
            self._messages.append(tool_msg)
            await self._on_message_appended_safe(tool_msg)
            if res.should_pause:
                should_pause = True

        return should_pause

    # ══════════════════════════════════════════════════════════════
    # 内部：事件 + Trace
    # ══════════════════════════════════════════════════════════════

    async def _publish(self, action: str, data: dict[str, Any]) -> None:
        """发布带 namespace 的 SSE 事件。

        - 若 action 已经包含点号（如 tool emit_event.type 给的 `brainstorm.ask_user`
          或跨 agent 命名如 `iteration.classified`），直接用
        - 否则补上 `{agent_type}.` 前缀（如 action=`start` → `brainstorm.start`）

        这样 tool 的 emit_event.type 可以写完整 namespace 自述命名，不会被套两层。
        """
        if self.ctx.publisher is None:
            return
        event_type = action if "." in action else f"{self.agent_type.value}.{action}"
        try:
            await self.ctx.publisher.publish(
                conversation_id=self.ctx.conversation_id,
                event_type=event_type,
                agent=self.agent_type.value,
                session_id=self.ctx.session_id,
                data=data,
            )
        except Exception as e:
            logger.warning("publish event failed: %s", e)

    async def _trace(
        self,
        event_type: TraceEventType | str,
        payload: dict[str, Any],
        *,
        tokens_input: Optional[int] = None,
        tokens_output: Optional[int] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """写 agent_traces"""
        if self.ctx.trace_writer is None:
            return
        try:
            et = event_type.value if isinstance(event_type, TraceEventType) else event_type
            await self.ctx.trace_writer.write(
                session_type=self.agent_type.value,
                session_id=self.ctx.session_id,
                turn=self._turn,
                event_type=et,
                payload=payload,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                duration_ms=duration_ms,
                model=self.ctx.model,
            )
        except Exception as e:
            logger.warning("trace write failed: %s", e)

    async def _trace_state_change(self, from_status: AgentStatus, to_status: AgentStatus) -> None:
        await self._trace(TraceEventType.STATE_CHANGE, {
            "from": from_status.value,
            "to": to_status.value,
        })

    async def _on_message_appended_safe(self, msg: dict[str, Any]) -> None:
        try:
            await self.on_message_appended(msg)
        except Exception as e:
            logger.warning("on_message_appended hook failed: %s", e)
