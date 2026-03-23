import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Tuple

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def encode_image_base64(image_path: str) -> str:
    """Read image file and return base64-encoded data URL."""
    path = Path(image_path)
    suffix = path.suffix.lower().lstrip(".")
    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    mime = mime_map.get(suffix, "image/png")
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


class LLMClient:
    def __init__(self):
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.doc_model = settings.llm_doc_model or self.model
        self.anthropic_base_url = settings.anthropic_base_url.rstrip("/")
        self.anthropic_api_key = settings.anthropic_api_key or self.api_key
        self.anthropic_model = settings.anthropic_model
        self.vision_model = settings.llm_vision_model or self.anthropic_model

    def _anthropic_messages_url(self) -> str:
        return f"{self.anthropic_base_url}/v1/messages"

    def _anthropic_headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

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
        system_parts: List[str] = []
        api_messages: List[Dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
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

            api_messages.append(
                {
                    "role": role,
                    "content": self._convert_content_to_anthropic(content),
                }
            )

        return "\n".join(part for part in system_parts if part).strip(), api_messages

    async def _anthropic_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        max_tokens: int,
        timeout: httpx.Timeout | float,
        temperature: float,
    ) -> Dict[str, Any]:
        system_text, api_messages = self._prepare_messages(messages)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text:
            payload["system"] = system_text

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                self._anthropic_messages_url(),
                headers=self._anthropic_headers(),
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _collect_text_from_response(data: Dict[str, Any]) -> Tuple[str, List[Dict[str, str]]]:
        texts: List[str] = []
        reasoning_details: List[Dict[str, str]] = []
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
        return "".join(texts), reasoning_details

    def _normalize_to_openai(self, data: Dict[str, Any], *, model: str) -> Dict[str, Any]:
        content, reasoning_details = self._collect_text_from_response(data)
        message: Dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if reasoning_details:
            message["reasoning_details"] = reasoning_details

        usage = data.get("usage", {})
        return {
            "id": data.get("id"),
            "object": "chat.completion",
            "model": data.get("model", model),
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": data.get("stop_reason"),
                }
            ],
            "usage": {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            },
            "_raw_anthropic": data,
        }

    async def chat_completion_stream(self, messages: List[Dict[str, Any]]) -> AsyncGenerator[str, None]:
        """
        调用 Anthropic Messages API，并转成现有调用方可消费的 OpenAI 风格 chunk。
        """
        system_text, api_messages = self._prepare_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": 16384,
            "stream": True,
        }
        if system_text:
            payload["system"] = system_text

        stream_timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)

        async with httpx.AsyncClient(timeout=stream_timeout) as client:
            async with client.stream(
                "POST",
                self._anthropic_messages_url(),
                headers=self._anthropic_headers(),
                json=payload,
            ) as response:
                response.raise_for_status()

                event_name = ""
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

                    data = json.loads(raw)
                    if event_name == "error":
                        error = data.get("error", {})
                        raise RuntimeError(error.get("message") or str(data))

                    if event_name != "content_block_delta":
                        continue

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

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 8192,
        timeout: float = 120.0,
        temperature: float = 0.3,
        model: str = None,
    ) -> Dict[str, Any]:
        """
        调用 Anthropic Messages API，并返回 OpenAI 风格结构给现有调用方。
        """
        effective_model = model or self.model
        data = await self._anthropic_completion(
            messages,
            model=effective_model,
            max_tokens=max_tokens,
            timeout=timeout,
            temperature=temperature,
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
