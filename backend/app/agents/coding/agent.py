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
from typing import Any

from app.agents.base import BaseAgent
from app.agents.coding.tools import build_coding_tools
from app.agents.types import AgentContext, AgentType, LLMResponse, Tool, ToolCall, TraceEventType

logger = logging.getLogger(__name__)


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

        # CodingAgent 专属状态（Stage 2.4 会完善）
        self._final_result: dict[str, Any] = {}
        self._llm_said_done: bool = False  # LLM 无 tool_call 时设为 True

    # ══════════════════════════════════════════════════════════════
    # BaseAgent 必须实现的抽象方法
    # ══════════════════════════════════════════════════════════════

    def get_system_prompt(self) -> str:
        # Stage 2.3 会从 prompts.py 引入完整 AGENT_SYSTEM_PROMPT
        # 现在先用 ctx.input 里的值或简单占位
        prompt = self.ctx.input.get("system_prompt")
        if prompt:
            return prompt
        return "你是 aPaaS 资深前端工程师。（Stage 2.3 待补完整 prompt）"

    def get_tools(self) -> list[Tool]:
        if self._cached_tools is None:
            self._cached_tools = build_coding_tools()
        return self._cached_tools

    def get_max_turns(self) -> int:
        return int(self.ctx.input.get("max_turns", 30))

    def build_initial_user_message(self) -> str:
        # Stage 2.3 会实现完整 prompt（7-scene 规则、workspace info 等）
        requirement = self.ctx.input.get("requirement", "")
        summary = self.ctx.input.get("conversation_summary", "")
        parts = []
        if summary:
            parts.append(f"## Previous Conversation Summary\n{summary}")
        parts.append(f"## Task\n{requirement}")
        return "\n\n".join(parts)

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

    async def on_llm_response(self, response) -> None:
        """LLM 响应后：如果没 tool_call，记录"主动 done"标志。"""
        if not response.tool_calls:
            self._llm_said_done = True
            # 把 LLM 的 content 作为最终文本
            self._final_result["final_text"] = response.content

    async def on_each_turn(self, turn: int) -> None:
        # Stage 2.4：在这里实现循环检测 + nudge
        pass

    async def on_context_overflow(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Stage 2.4：搬 vibe_agent._compress_context
        return messages

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

        response = LLMResponse(
            content=full_content,
            tool_calls=assembled_tool_calls,
            finish_reason=finish_reason,
            # 流式没有 usage 字段，留 0（未来可从 chunk 里抠或再补一次 count）
            tokens_input=0,
            tokens_output=0,
            raw={"streamed": True},
        )

        await self._trace(TraceEventType.LLM_RESPONSE, {
            "content_preview": full_content[:200],
            "reasoning_preview": reasoning_content[:200] if reasoning_content else "",
            "tool_calls": [
                {"name": tc.name, "args_preview": tc.arguments_json[:200]}
                for tc in assembled_tool_calls
            ],
            "finish_reason": finish_reason,
        }, duration_ms=duration_ms)

        # 如果没 tool_calls 就整条 assistant content 作为 "thinking" 事件（兼容老 SSE）
        if not assembled_tool_calls and full_content:
            await self._publish("agent_thinking", {"content": full_content})

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
        }

    def _deserialize_custom_state(self, data: dict[str, Any]) -> None:
        self._final_result = data.get("final_result") or {}
        self._llm_said_done = bool(data.get("llm_said_done"))
