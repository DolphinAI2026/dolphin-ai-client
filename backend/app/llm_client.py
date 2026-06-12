import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self._openai_base_url: str | None = None  # 非 Anthropic 兼容 URL
        if base_url:
            _raw = base_url.rstrip("/")
            if "/anthropic" in _raw:
                # Anthropic-compatible proxy（如 MiniMax）
                self.anthropic_base_url = _raw.removesuffix("/v1")
                self._openai_base_url = None
                self.doc_model = settings.llm_doc_model or self.model
            else:
                # OpenAI-compatible provider（如 千问/qwen）
                self._openai_base_url = _raw
                self.anthropic_base_url = settings.anthropic_base_url.rstrip("/")
                # OpenAI provider 用自己的 model，不用 MiniMax 专属的 doc_model
                self.doc_model = self.model
        else:
            self.anthropic_base_url = settings.anthropic_base_url.rstrip("/")
            self.doc_model = settings.llm_doc_model or self.model
        self.anthropic_api_key = api_key or settings.anthropic_api_key or self.api_key
        self.anthropic_model = model or settings.anthropic_model
        self.vision_model = settings.llm_vision_model or self.anthropic_model

    def _anthropic_messages_url(self) -> str:
        return f"{self.anthropic_base_url}/v1/messages"

    def _anthropic_headers(self) -> Dict[str, str]:
        base_url = (self.anthropic_base_url or "").lower()
        headers = {
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        if "api.anthropic.com" not in base_url:
            headers["Authorization"] = self.anthropic_api_key
        return headers

    @staticmethod
    def _parse_data_url(url: str) -> Tuple[str, str]:
        match = re.match(r"^data:([^;]+);base64,(.+)$", url, re.DOTALL)
        if not match:
            raise ValueError("Anthropic image input requires a data URL")
        media_type, data = match.groups()
        return media_type, data

    def _convert_content_to_anthropic(self, content: Any) -> str | List[Dict[str, Any]]:
        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return str(content)

        blocks: List[Dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                blocks.append({"type": "text", "text": str(item)})
                continue

            block_type = item.get("type")
            if block_type == "text":
                blocks.append({"type": "text", "text": item.get("text", "")})
                continue

            if block_type == "image_url":
                image_url = item.get("image_url", {}).get("url", "")
                media_type, data = self._parse_data_url(image_url)
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    }
                )
                continue

            logger.warning("忽略不支持的 Anthropic content block: %s", block_type)

        return blocks or ""

    def _prepare_messages(self, messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """将 OpenAI 风格 messages 转成 Anthropic 风格。

        处理四种特殊情况：
        1. role="system" → 抽取到 system_text（Anthropic 的 system 独立字段）
        2. role="assistant" + tool_calls → assistant content 里加 tool_use blocks
        3. role="tool"（工具结果）→ 转成 user role + tool_result content block
           连续的 tool 消息合并到同一个 user message 里（Anthropic 要求）
        4. 普通 text / image_url → 保持原逻辑
        """
        system_parts: List[str] = []
        api_messages: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # 1. system
            if role == "system":
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            system_parts.append(block.get("text", ""))
                        else:
                            system_parts.append(str(block))
                else:
                    system_parts.append(str(content))
                continue

            # 2. assistant with tool_calls
            if role == "assistant" and msg.get("tool_calls"):
                blocks: List[Dict[str, Any]] = []
                if content:
                    if isinstance(content, str) and content.strip():
                        blocks.append({"type": "text", "text": content})
                    elif isinstance(content, list):
                        text_blocks = self._convert_content_to_anthropic(content)
                        if isinstance(text_blocks, list):
                            blocks.extend(text_blocks)
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                    try:
                        tool_input = json.loads(fn.get("arguments", "{}") or "{}")
                    except Exception:
                        tool_input = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": tool_input,
                    })
                api_messages.append({"role": "assistant", "content": blocks})
                continue

            # 3. tool result → 合并到最近的 user message（Anthropic 要求）
            if role == "tool":
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                }
                # 若上一条已是 user 且内容是 list，追加；否则新建
                if api_messages and api_messages[-1]["role"] == "user" and isinstance(api_messages[-1]["content"], list):
                    api_messages[-1]["content"].append(tool_result_block)
                else:
                    api_messages.append({"role": "user", "content": [tool_result_block]})
                continue

            # 4. 普通消息
            api_messages.append(
                {
                    "role": role,
                    "content": self._convert_content_to_anthropic(content),
                }
            )

        return "\n".join(part for part in system_parts if part).strip(), api_messages

    @staticmethod
    def _convert_openai_tools_to_anthropic(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """把 OpenAI function-calling 格式的 tools 转成 Anthropic tool use 格式。

        OpenAI:    [{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}]
        Anthropic: [{"name": ..., "description": ..., "input_schema": {...}}]
        """
        converted: List[Dict[str, Any]] = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            # 兼容两种形式：嵌套 function 字段 / 平铺
            if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
                fn = tool["function"]
                name = fn.get("name")
                description = fn.get("description", "")
                parameters = fn.get("parameters") or {"type": "object", "properties": {}}
            else:
                name = tool.get("name")
                description = tool.get("description", "")
                parameters = tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}}
            if not name:
                continue
            converted.append({
                "name": name,
                "description": description,
                "input_schema": parameters,
            })
        return converted

    @staticmethod
    def _convert_openai_tool_choice_to_anthropic(tool_choice: Union[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """把 OpenAI tool_choice 转成 Anthropic tool_choice 格式。

        OpenAI:    "auto" / "none" / "required" / {"type": "function", "function": {"name": "xxx"}}
        Anthropic: {"type": "auto"} / None / {"type": "any"} / {"type": "tool", "name": "xxx"}
        """
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            if tool_choice == "auto":
                return {"type": "auto"}
            if tool_choice == "none":
                return None  # Anthropic: 不传 tool_choice 即 none
            if tool_choice == "required":
                return {"type": "any"}
            return {"type": "auto"}
        if isinstance(tool_choice, dict):
            if tool_choice.get("type") == "function":
                name = tool_choice.get("function", {}).get("name")
                if name:
                    return {"type": "tool", "name": name}
            # 已经是 Anthropic 格式直接返回
            if tool_choice.get("type") in {"auto", "any", "tool"}:
                return tool_choice
        return None

    async def _anthropic_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        timeout: httpx.Timeout | float,
        temperature: float,
        max_retries: int = 2,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        import asyncio
        system_text, api_messages = self._prepare_messages(messages)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = self._convert_openai_tools_to_anthropic(tools)
            anthropic_tc = self._convert_openai_tool_choice_to_anthropic(tool_choice)
            if anthropic_tc:
                payload["tool_choice"] = anthropic_tc

        last_err = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                wait = min(2 ** attempt, 10)
                logger.warning(f"LLM 调用重试 {attempt}/{max_retries}，等待 {wait}s...")
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        self._anthropic_messages_url(),
                        headers=self._anthropic_headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    return response.json()
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.NetworkError, httpx.RemoteProtocolError) as e:
                last_err = e
                logger.warning(f"LLM 调用网络错误 (attempt {attempt+1}): {e}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    last_err = e
                    logger.warning(f"LLM 服务端错误 {e.response.status_code} (attempt {attempt+1})")
                else:
                    raise  # 4xx 错误不重试
        raise last_err  # 所有重试都失败

    @staticmethod
    def _collect_text_from_response(data: Dict[str, Any]) -> Tuple[str, List[Dict[str, str]]]:
        """向后兼容接口：只返回 text 和 reasoning，不返回 tool_uses。

        新代码建议用 _parse_anthropic_content。
        """
        text, reasoning, _tool_uses = LLMClient._parse_anthropic_content(data)
        return text, reasoning

    @staticmethod
    def _parse_anthropic_content(
        data: Dict[str, Any],
    ) -> Tuple[str, List[Dict[str, str]], List[Dict[str, Any]]]:
        """完整解析 Anthropic content blocks。

        返回 (text, reasoning_details, tool_uses)
        tool_uses 元素结构：{"id": str, "name": str, "input": dict}
        """
        texts: List[str] = []
        reasoning_details: List[Dict[str, str]] = []
        tool_uses: List[Dict[str, Any]] = []
        for block in data.get("content", []):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                texts.append(block.get("text", ""))
            elif block_type == "thinking":
                thinking = block.get("thinking", "")
                if thinking:
                    reasoning_details.append({"text": thinking})
            elif block_type == "tool_use":
                tool_uses.append({
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": block.get("input", {}) or {},
                })
        return "".join(texts), reasoning_details, tool_uses

    @staticmethod
    def _anthropic_tool_uses_to_openai_tool_calls(
        tool_uses: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """把 Anthropic tool_use block 转成 OpenAI tool_calls 格式（返回给调用方）。

        OpenAI 格式: [{"id", "type": "function", "function": {"name", "arguments": "<json str>"}}]
        """
        tool_calls: List[Dict[str, Any]] = []
        for tu in tool_uses:
            tool_calls.append({
                "id": tu.get("id", ""),
                "type": "function",
                "function": {
                    "name": tu.get("name", ""),
                    "arguments": json.dumps(tu.get("input") or {}, ensure_ascii=False),
                },
            })
        return tool_calls

    def _normalize_to_openai(self, data: Dict[str, Any], *, model: str) -> Dict[str, Any]:
        content, reasoning_details, tool_uses = self._parse_anthropic_content(data)
        message: Dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if reasoning_details:
            message["reasoning_details"] = reasoning_details
        if tool_uses:
            message["tool_calls"] = self._anthropic_tool_uses_to_openai_tool_calls(tool_uses)

        # Anthropic stop_reason → OpenAI finish_reason 映射
        stop_reason = data.get("stop_reason")
        finish_reason = stop_reason
        if stop_reason == "tool_use":
            finish_reason = "tool_calls"
        elif stop_reason == "end_turn":
            finish_reason = "stop"
        elif stop_reason == "max_tokens":
            finish_reason = "length"

        usage = data.get("usage", {})
        return {
            "id": data.get("id"),
            "object": "chat.completion",
            "model": data.get("model", model),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            },
            "_raw_anthropic": data,
        }

    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 8192,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式 LLM 调用，统一输出 OpenAI 风格 chunk（含 tool_calls delta）。
        OpenAI-compatible：原样透传 tools；Anthropic：格式转换 + 流式事件重组。
        """
        if self._openai_base_url:
            base = self._openai_base_url.rstrip("/")
            if base.endswith("/v1"):
                url = f"{base}/chat/completions"
            else:
                url = f"{base}/v1/chat/completions"

            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
                # 让 OpenAI 兼容网关在 [DONE] 前回一个带 usage 的 chunk（token 必采）。
                # 该 chunk 的 choices 为空、带 usage，原样透传给上层流式消费者累计。
                "stream_options": {"include_usage": True},
            }
            if tools:
                payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
            stream_timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

            async with httpx.AsyncClient(timeout=stream_timeout) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        logger.error("OpenAI stream error %s: %s", response.status_code, body.decode()[:500])
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            yield json.dumps(json.loads(raw), ensure_ascii=False)
                        except Exception:
                            continue
            return

        # —— Anthropic path —— #
        system_text, api_messages = self._prepare_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system_text:
            payload["system"] = system_text
        if tools:
            payload["tools"] = self._convert_openai_tools_to_anthropic(tools)
            anthropic_tc = self._convert_openai_tool_choice_to_anthropic(tool_choice)
            if anthropic_tc:
                payload["tool_choice"] = anthropic_tc

        stream_timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

        async with httpx.AsyncClient(timeout=stream_timeout) as client:
            async with client.stream(
                "POST",
                self._anthropic_messages_url(),
                headers=self._anthropic_headers(),
                json=payload,
            ) as response:
                response.raise_for_status()

                # Anthropic 流式 tool_use 事件重组：
                # content_block_start (type=tool_use, id, name)
                #   → 发送 OpenAI 风格的 tool_calls 起始 delta（含 id/name，arguments=""）
                # content_block_delta (type=input_json_delta, partial_json)
                #   → 发送 arguments 增量 delta
                # 同一个 tool_use block 共享一个 OpenAI index，按 content_block 索引映射
                event_name = ""
                block_index_to_tool: Dict[int, Dict[str, Any]] = {}  # block_idx → {openai_index, id, name}

                async for line in response.aiter_lines():
                    if not line:
                        event_name = ""
                        continue

                    if line.startswith("event: "):
                        event_name = line[7:].strip()
                        continue

                    if not line.startswith("data: "):
                        continue

                    raw = line[6:]
                    if raw.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(raw)
                    except Exception:
                        continue

                    if event_name == "error":
                        error = data.get("error", {})
                        raise RuntimeError(error.get("message") or str(data))

                    # tool_use 开始 → 发送 OpenAI tool_calls 起始 delta
                    if event_name == "content_block_start":
                        block = data.get("content_block", {}) or {}
                        if block.get("type") == "tool_use":
                            block_idx = data.get("index", 0)
                            # OpenAI tool_calls 的 index 从 0 开始，与 Anthropic block_idx 解耦
                            openai_idx = len(block_index_to_tool)
                            block_index_to_tool[block_idx] = {
                                "openai_index": openai_idx,
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                            }
                            yield json.dumps({
                                "choices": [{
                                    "delta": {
                                        "tool_calls": [{
                                            "index": openai_idx,
                                            "id": block.get("id", ""),
                                            "type": "function",
                                            "function": {
                                                "name": block.get("name", ""),
                                                "arguments": "",
                                            },
                                        }],
                                    },
                                }],
                            }, ensure_ascii=False)
                        continue

                    if event_name == "content_block_delta":
                        block_idx = data.get("index", 0)
                        delta = data.get("delta", {})
                        delta_type = delta.get("type")

                        if delta_type == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield json.dumps(
                                    {"choices": [{"delta": {"content": text}}]},
                                    ensure_ascii=False,
                                )
                        elif delta_type == "thinking_delta":
                            thinking = delta.get("thinking", "")
                            if thinking:
                                yield json.dumps(
                                    {"choices": [{"delta": {"reasoning_content": thinking}}]},
                                    ensure_ascii=False,
                                )
                        elif delta_type == "input_json_delta":
                            partial = delta.get("partial_json", "")
                            tool_meta = block_index_to_tool.get(block_idx)
                            if partial and tool_meta is not None:
                                yield json.dumps({
                                    "choices": [{
                                        "delta": {
                                            "tool_calls": [{
                                                "index": tool_meta["openai_index"],
                                                "function": {"arguments": partial},
                                            }],
                                        },
                                    }],
                                }, ensure_ascii=False)
                        continue

                    # message_delta 携带 stop_reason（用于判断 finish）
                    if event_name == "message_delta":
                        stop_reason = (data.get("delta") or {}).get("stop_reason")
                        if stop_reason:
                            finish = "tool_calls" if stop_reason == "tool_use" else (
                                "stop" if stop_reason == "end_turn" else (
                                    "length" if stop_reason == "max_tokens" else stop_reason
                                )
                            )
                            yield json.dumps(
                                {"choices": [{"delta": {}, "finish_reason": finish}]},
                                ensure_ascii=False,
                            )
                        continue

    async def _openai_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        timeout: float,
        temperature: float,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """OpenAI-compatible chat/completions 调用（用于千问等非 Anthropic proxy）。

        tools / tool_choice 透传给 OpenAI API（function-calling 格式原样传递）。
        """
        base = self._openai_base_url.rstrip("/")
        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        # 将 system 消息合并到 messages（OpenAI 原生支持 system role，无需额外处理）
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        import asyncio as _asyncio
        _retryable_codes = {429, 529, 503, 502}
        _max_retries = 3
        for _attempt in range(_max_retries + 1):
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            if response.status_code in _retryable_codes and _attempt < _max_retries:
                wait = 2 ** _attempt  # 1s, 2s, 4s
                logger.warning(f"LLM API {response.status_code}，{wait}s 后重试（{_attempt+1}/{_max_retries}）")
                await _asyncio.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 8192,
        timeout: float = 120.0,
        temperature: float = 0.3,
        model: str = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        调用 LLM 并返回 OpenAI 风格结构。
        自动根据 base_url 类型选择 Anthropic Messages API 或 OpenAI chat/completions。

        tools: OpenAI function-calling 格式。不传或 None 时行为与旧版完全一致。
        tool_choice: "auto" / "none" / "required" / {"type": "function", "function": {"name": ...}}
        """
        effective_model = model or self.model
        if self._openai_base_url:
            return await self._openai_completion(
                messages,
                model=effective_model,
                max_tokens=max_tokens,
                timeout=timeout,
                temperature=temperature,
                tools=tools,
                tool_choice=tool_choice,
            )
        data = await self._anthropic_completion(
            messages,
            model=effective_model,
            max_tokens=max_tokens,
            timeout=timeout,
            temperature=temperature,
            tools=tools,
            tool_choice=tool_choice,
        )
        return self._normalize_to_openai(data, model=effective_model)

    async def chat_completion_vision(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """
        Vision 调用也统一走 Anthropic Messages API。
        """
        data = await self._anthropic_completion(
            messages,
            model=self.vision_model,
            max_tokens=max_tokens,
            timeout=120.0,
            temperature=temperature,
        )
        content, _ = self._collect_text_from_response(data)
        return re.sub(r"<think>[\s\S]*?</think>", "", content).strip()

    async def claude_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 16384,
        timeout: float = 300.0,
        temperature: float = 0.2,
    ) -> str:
        """
        通过 Anthropic Messages API 调用大上下文模型。
        返回纯文本内容。
        """
        data = await self._anthropic_completion(
            messages,
            model=self.anthropic_model,
            max_tokens=max_tokens,
            timeout=timeout,
            temperature=temperature,
        )
        content, _ = self._collect_text_from_response(data)
        return content
