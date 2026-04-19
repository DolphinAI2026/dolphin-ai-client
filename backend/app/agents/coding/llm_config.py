"""Coding Agent 使用的 LLM 配置解析（从 VibeCodingAgent 迁移到独立模块）。

职责：
- 从租户 DB 的 llm_configs 解析 coding purpose 的配置
- fallback 到 .env 里的 VIBE_AGENT_* / ANTHROPIC_* 环境变量
- URL normalization（把 /anthropic 改 /v1 等）

使用方：
- backend/app/coding/pipeline.py: brainstorm LLM 调用 + CodingAgent 创建
- 未来 BrainstormAgent / VerificationAgent 也可共用

历史：原位于 backend/app/coding/vibe_agent.py 的 _load_agent_env / _load_llm_config /
_normalize_base_url（class 级方法）。Stage 4 清理时抽到这里作为 module-level 函数。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _normalize_base_url(base_url: str) -> str:
    """把 LLM base URL 归一化为 OpenAI-compatible 格式（以 /v1 结尾）。"""
    base_url = (base_url or "").rstrip("/")
    if "/anthropic" in base_url:
        base_url = base_url.replace("/anthropic", "/v1")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]
    if not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return base_url


def _load_agent_env() -> dict[str, str]:
    """从 backend/.env 读取 agent 相关环境变量（ANTHROPIC_* / API_TIMEOUT_MS / VIBE_AGENT_*）。

    作为 DB 查询的 fallback。脚本/测试模式下主力。
    """
    env: dict[str, str] = {}
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
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
            if (
                key.startswith("ANTHROPIC_")
                or key == "API_TIMEOUT_MS"
                or key.startswith("VIBE_AGENT_")
            ):
                env[key] = value
    except Exception:
        logger.exception("Failed to read agent .env")
    return env


async def load_coding_llm_config(
    tenant_id: Optional[int],
    model_override: Optional[str] = None,
) -> Tuple[str, str, str]:
    """解析 coding 用途的 LLM 配置。

    优先级：
    1. DB（若 tenant_id 存在）：走 app.harness.llm_resolver.resolve_llm_config
       - 支持 model_override 前缀 "llmcfg:<id>" 指定具体配置
    2. Fallback .env：VIBE_AGENT_* 专用 > ANTHROPIC_* 通用

    返回 (base_url, api_key, model)。base_url 经 _normalize_base_url 归一化。
    """
    # 1) DB 查询
    if tenant_id:
        try:
            from app.database import AsyncSessionLocal
            from app.harness.llm_resolver import resolve_llm_config

            selected_config_id: Optional[int] = None
            override_str = (model_override or "").strip()
            if override_str.startswith("llmcfg:"):
                try:
                    selected_config_id = int(override_str.split(":", 1)[1])
                except ValueError:
                    pass

            async with AsyncSessionLocal() as db:
                resolved = await resolve_llm_config(
                    db, tenant_id,
                    purpose="coding",
                    selected_config_id=selected_config_id,
                )
                if resolved:
                    base_url = _normalize_base_url(resolved.base_url)
                    return base_url, resolved.api_key, resolved.model
        except Exception:
            logger.exception("DB resolve_llm_config failed, falling back to .env")

    # 2) .env fallback
    env = _load_agent_env()
    base_url_raw = (
        env.get("VIBE_AGENT_BASE_URL")
        or env.get("ANTHROPIC_BASE_URL", "https://api.minimax.chat/v1")
    )
    base_url = _normalize_base_url(base_url_raw)
    api_key = env.get("VIBE_AGENT_API_KEY") or env.get("ANTHROPIC_API_KEY", "")
    llm_model = (
        model_override
        or env.get("VIBE_AGENT_MODEL")
        or env.get("ANTHROPIC_MODEL", "MiniMax-M2.7")
    )
    return base_url, api_key, llm_model
