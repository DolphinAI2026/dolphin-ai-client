"""Harness Core — LLM 配置统一解析

消除 routes/chat.py、routes/requirements.py、coding/vibe_agent.py 三处
重复的 _get_tenant_llm_config + _serialize_llm_config 逻辑。
"""
from dataclasses import dataclass
from typing import Optional, AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

import logging

logger = logging.getLogger(__name__)


@dataclass
class ResolvedLLMConfig:
    """解析后的 LLM 配置，可直接用于 API 调用。"""
    model: str
    base_url: str
    api_key: str
    max_tokens: int = 8192
    config_id: Optional[int] = None
    config_name: Optional[str] = None
    provider: Optional[str] = None


async def resolve_llm_config(
    db: AsyncSession,
    tenant_id: int,
    *,
    purpose: str = "all",
    selected_config_id: Optional[int] = None,
) -> Optional[ResolvedLLMConfig]:
    """
    统一解析 LLM 配置。

    优先级：
    1. selected_config_id（会话选择的模型）
    2. 租户默认的 purpose 模型
    3. 租户默认的 "all" 模型
    4. 返回 None（调用方回退到 LLMClient 环境变量）
    """
    from app.crypto import decrypt_password
    from app.routes.llm_configs import resolve_llm_config_for_purpose

    config = await resolve_llm_config_for_purpose(db, tenant_id, purpose, selected_config_id)
    if not config:
        return None

    return ResolvedLLMConfig(
        model=config.model,
        base_url=config.base_url.rstrip("/"),
        api_key=decrypt_password(config.api_key_enc),
        max_tokens=config.max_tokens or 8192,
        config_id=config.id,
        config_name=config.config_name,
        provider=config.provider,
    )


def build_chat_completions_url(base_url: str) -> str:
    """构建 OpenAI 兼容的 chat/completions URL。"""
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


async def stream_with_config(
    config: Optional[ResolvedLLMConfig],
    messages: list,
    *,
    max_tokens: Optional[int] = None,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """
    使用解析后的配置流式调用 LLM。yield OpenAI 格式 JSON 字符串。
    config 为 None 时回退到 LLMClient（环境变量）。
    """
    if config is None:
        from app.llm_client import LLMClient
        llm = LLMClient()
        async for chunk in llm.chat_completion_stream(messages):
            yield chunk
        return

    payload = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens or config.max_tokens,
        "stream": True,
        "temperature": temperature,
    }
    timeout = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        url = build_chat_completions_url(config.base_url)
        async with client.stream(
            "POST", url,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        ) as response:
            async for line in response.aiter_lines():
                line = line.strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    yield data
