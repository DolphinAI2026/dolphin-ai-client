import base64
import httpx
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List
from app.config import settings


def encode_image_base64(image_path: str) -> str:
    """Read image file and return base64-encoded data URL"""
    path = Path(image_path)
    suffix = path.suffix.lower().lstrip(".")
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
    mime = mime_map.get(suffix, "image/png")
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


class LLMClient:
    def __init__(self):
        self.api_base = settings.llm_api_base
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model

    async def chat_completion_stream(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """
        调用LLM API进行流式对话
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": 16384
        }

        # 流式请求需要更长的超时：连接10s，读取每个chunk 300s
        stream_timeout = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=stream_timeout) as client:
            async with client.stream(
                "POST",
                f"{self.api_base}/v1/chat/completions",
                headers=headers,
                json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        yield data

    async def chat_completion(self, messages: List[Dict[str, str]], *, max_tokens: int = 8192, timeout: float = 120.0, temperature: float = 0.3, model: str = None) -> Dict[str, Any]:
        """
        调用LLM API进行非流式对话
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.api_base}/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            # MiniMax-M1 默认 thinking 模式：content 为空，答案在 reasoning_details
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content")
            if not content and msg.get("reasoning_details"):
                # 从 reasoning_details 提取最后一段文本作为回答
                details = msg["reasoning_details"]
                if isinstance(details, list):
                    texts = [d.get("text", "") for d in details if isinstance(d, dict) and d.get("text")]
                    if texts:
                        msg["content"] = texts[-1]
                        data["choices"][0]["message"] = msg

            return data

    async def chat_completion_vision(self, messages: List[Dict], *, max_tokens: int = 4096, temperature: float = 0.3) -> str:
        """
        Vision-capable chat completion. Messages can contain image content.
        Messages format: [{"role": "user", "content": [
            {"type": "text", "text": "..."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
        ]}]
        Returns just the text response string.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Vision 用 MiniMax-M2.7 模型（支持多模态 + thinking）
        vision_model = "MiniMax-M2.7" if "MiniMax" in self.model else self.model

        payload = {
            "model": vision_model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "thinking": {"type": "enabled", "budget_tokens": 2048}
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.api_base}/v1/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content", "")
            # thinking 模式下 content 可能是 list 或包含 <think> 标签的文本
            if isinstance(content, list):
                for block in reversed(content):
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
                return str(content)
            # 去掉 <think>...</think> 标签，只返回实际回答
            import re
            content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
            return content
