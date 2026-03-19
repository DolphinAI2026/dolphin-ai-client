import httpx
from typing import AsyncGenerator, Dict, Any, List
from app.config import settings


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

    async def chat_completion(self, messages: List[Dict[str, str]], *, max_tokens: int = 8192, timeout: float = 120.0, temperature: float = 0.3) -> Dict[str, Any]:
        """
        调用LLM API进行非流式对话
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
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
            return response.json()
