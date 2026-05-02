"""Voice — 语音转文字（STT）中转。

复用现有 LLMConfig（OpenAI 兼容协议）凭证，前端 MediaRecorder 录音上传，
后端转发到 `{base_url}/v1/audio/transcriptions`（Whisper API 协议）。

兼容性：
- ✅ OneAPI / FastGPT / 新一API 等 OpenAI 兼容网关（国内常见）
- ✅ OpenAI 官方
- ⚠️ 直连 DeepSeek / 阿里 / 字节 — 协议不同，会返回 4xx/5xx，前端兜底报错
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.harness.llm_resolver import resolve_llm_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# 上传音频体积上限（默认 25MB，跟 OpenAI Whisper API 对齐）
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def _build_transcriptions_url(base_url: str) -> str:
    """构建 OpenAI 兼容的 audio/transcriptions URL。"""
    base = base_url.rstrip("/")
    if base.endswith("/audio/transcriptions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/audio/transcriptions"
    return f"{base}/v1/audio/transcriptions"


@router.post("/transcribe")
async def transcribe(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    audio: Annotated[UploadFile, File(description="音频文件 (webm/opus/wav/mp3/m4a)")],
    selected_llm_config_id: Annotated[Optional[int], Form()] = None,
    language: Annotated[str, Form()] = "zh",
    model: Annotated[str, Form()] = "whisper-1",
):
    """前端上传录音，后端调用 LLM 网关的 Whisper 协议转写。

    Args:
        audio: 音频 multipart upload
        selected_llm_config_id: 复用对话当前选的 LLMConfig（没传则用租户默认）
        language: ISO-639-1 语言代码（zh / en / ja 等），网关识别用
        model: STT 模型名（whisper-1 是 OpenAI 标准，OneAPI 类网关一般也认）

    Returns:
        {"text": "识别文本"}
    """
    # 1) 读音频内容
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空音频文件")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"音频体积超过 {MAX_AUDIO_BYTES // 1024 // 1024}MB 上限",
        )

    # 2) 拿当前租户/会话的 LLM 配置
    config = await resolve_llm_config(
        db,
        ctx.tenant_id,
        purpose="all",
        selected_config_id=selected_llm_config_id,
    )
    if not config:
        raise HTTPException(
            status_code=400,
            detail="租户没有可用的 LLM 配置，请先在「系统设置 - 大模型」里配置一个",
        )

    # 3) 转发到 OpenAI 兼容 transcriptions 端点
    url = _build_transcriptions_url(config.base_url)
    filename = audio.filename or "audio.webm"
    content_type = audio.content_type or "audio/webm"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {config.api_key}"},
                files={"file": (filename, raw, content_type)},
                data={"model": model, "language": language},
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="语音识别超时，请重试")
    except httpx.HTTPError as e:
        logger.warning("STT 网络错误: %s", e)
        raise HTTPException(status_code=502, detail=f"语音识别网关错误: {e}")

    if resp.status_code >= 400:
        # 网关报错 — 大概率是不支持 Whisper 协议（直连 DeepSeek / 阿里等会 404）
        body_preview = (resp.text or "")[:300]
        logger.warning("STT 网关返回 %s: %s", resp.status_code, body_preview)
        if resp.status_code == 404:
            raise HTTPException(
                status_code=400,
                detail=f"当前 LLM 配置「{config.config_name}」不支持语音识别（{config.provider} 直连不兼容 Whisper 协议）。"
                       f"请改用 OneAPI / 新一 API 等 OpenAI 兼容网关，或单独配置一个支持 STT 的模型",
            )
        raise HTTPException(
            status_code=502,
            detail=f"语音识别失败 ({resp.status_code}): {body_preview}",
        )

    # 4) 解析响应（Whisper 标准返回 {"text": "..."}，OneAPI 类一致）
    try:
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="语音识别返回非 JSON 响应")

    text = (data.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="语音识别返回空文本")

    return {"text": text, "model": model, "config_name": config.config_name}
