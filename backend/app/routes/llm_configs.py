"""LLM 模型配置管理 — 管理员可通过前台配置接入的大模型"""
from __future__ import annotations
import logging
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.database import get_db
from app.deps import AuthContext, get_auth_context, require_tenant_admin
from app.models import LLMConfig
from app.crypto import encrypt_password, decrypt_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/llm-configs", tags=["llm-configs"])

# ── Provider presets ──
PROVIDER_PRESETS = {
    "minimax": {"base_url": "https://api.minimax.chat/v1", "models": ["MiniMax-M2.7", "MiniMax-M1"]},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen3.5-plus", "qwen-max", "qwen-plus", "qwen-turbo", "qwen3-coder-next"]},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "models": ["deepseek-chat", "deepseek-coder"]},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "models": ["glm-4-plus", "glm-4"]},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-128k", "moonshot-v1-32k"]},
    "openai": {"base_url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini"]},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "models": ["claude-sonnet-4-20250514"]},
}


# ── Schemas ──
class LLMConfigCreate(BaseModel):
    config_name: str
    provider: str
    base_url: str
    api_key: str  # 明文传入，后端加密存储
    model: str
    purpose: str = "all"
    is_default: bool = False
    max_tokens: int = 8192
    temperature: float = 0.3


class LLMConfigUpdate(BaseModel):
    config_name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None  # 不传则不更新
    model: Optional[str] = None
    purpose: Optional[str] = None
    is_default: Optional[bool] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    status: Optional[str] = None


class LLMConfigStatusUpdate(BaseModel):
    status: str


class LLMConfigResponse(BaseModel):
    id: int
    config_name: str
    provider: str
    base_url: str
    model: str
    purpose: str
    is_default: bool
    max_tokens: int
    temperature: float
    status: str
    created_at: str
    updated_at: str

    @staticmethod
    def from_db(row: LLMConfig) -> "LLMConfigResponse":
        return LLMConfigResponse(
            id=row.id,
            config_name=row.config_name,
            provider=row.provider,
            base_url=row.base_url,
            model=row.model,
            purpose=row.purpose,
            is_default=row.is_default,
            max_tokens=row.max_tokens,
            temperature=row.temperature,
            status=row.status,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
        )


class LLMConfigOptionResponse(BaseModel):
    id: int
    config_name: str
    provider: str
    model: str
    purpose: str
    is_default: bool

    @staticmethod
    def from_db(row: LLMConfig) -> "LLMConfigOptionResponse":
        return LLMConfigOptionResponse(
            id=row.id,
            config_name=row.config_name,
            provider=row.provider,
            model=row.model,
            purpose=row.purpose,
            is_default=row.is_default,
        )


def build_llm_chat_completions_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/responses"):
        return f"{base[:-len('/responses')]}/chat/completions"
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/chat/completions"


def build_llm_responses_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/responses"):
        return base
    if base.endswith("/chat/completions"):
        return f"{base[:-len('/chat/completions')]}/responses"
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/responses"


# ── Routes ──

@router.get("/presets")
async def get_provider_presets():
    """获取供应商预设配置"""
    return PROVIDER_PRESETS


@router.get("")
async def list_llm_configs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出当前租户的 LLM 配置"""
    result = await db.execute(
        select(LLMConfig)
        .where(LLMConfig.tenant_id == ctx.tenant_id)
        .order_by(LLMConfig.is_default.desc(), LLMConfig.created_at.desc())
    )
    rows = result.scalars().all()
    return [LLMConfigResponse.from_db(r) for r in rows]


@router.get("/options")
async def list_llm_config_options(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    purpose: str = Query("builder"),
):
    """列出指定用途可用的模型选项（面向普通用户的只读列表）。"""
    rows = await list_llm_configs_for_purpose(db, ctx.tenant_id, purpose)
    return [LLMConfigOptionResponse.from_db(row) for row in rows]


@router.post("")
async def create_llm_config(
    req: LLMConfigCreate,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """新增 LLM 配置（管理员）"""
    # 如果设为默认，先清除其他同 purpose 的默认
    if req.is_default:
        await _clear_defaults(db, ctx.tenant_id, req.purpose)

    config = LLMConfig(
        tenant_id=ctx.tenant_id,
        config_name=req.config_name,
        provider=req.provider,
        base_url=req.base_url.rstrip("/"),
        api_key_enc=encrypt_password(req.api_key),
        model=req.model,
        purpose=req.purpose,
        is_default=req.is_default,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return LLMConfigResponse.from_db(config)


@router.put("/{config_id}")
async def update_llm_config(
    config_id: int,
    req: LLMConfigUpdate,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """编辑 LLM 配置（管理员）"""
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.id == config_id, LLMConfig.tenant_id == ctx.tenant_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    if req.config_name is not None:
        config.config_name = req.config_name
    if req.provider is not None:
        config.provider = req.provider
    if req.base_url is not None:
        config.base_url = req.base_url.rstrip("/")
    if req.api_key is not None:
        config.api_key_enc = encrypt_password(req.api_key)
    if req.model is not None:
        config.model = req.model
    if req.purpose is not None:
        config.purpose = req.purpose
    if req.max_tokens is not None:
        config.max_tokens = req.max_tokens
    if req.temperature is not None:
        config.temperature = req.temperature
    if req.status is not None:
        if req.status not in {"active", "inactive", "error"}:
            raise HTTPException(status_code=400, detail="不支持的模型状态")
        config.status = req.status
    if req.is_default is True:
        if config.status != "active":
            raise HTTPException(status_code=400, detail="未启用模型不能设为默认")
        await _clear_defaults(db, ctx.tenant_id, config.purpose)
        config.is_default = True
    elif req.is_default is False:
        config.is_default = False

    if config.status == "inactive" and config.is_default:
        config.is_default = False
        await _assign_replacement_default(db, ctx.tenant_id, config.purpose, exclude_id=config.id)

    await db.commit()
    await db.refresh(config)
    return LLMConfigResponse.from_db(config)


@router.delete("/{config_id}")
async def delete_llm_config(
    config_id: int,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """删除 LLM 配置（管理员）"""
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.id == config_id, LLMConfig.tenant_id == ctx.tenant_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    await db.delete(config)
    await db.commit()
    return {"ok": True}


@router.post("/{config_id}/test")
async def test_llm_config(
    config_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """测试 LLM 配置连接"""
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.id == config_id, LLMConfig.tenant_id == ctx.tenant_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    api_key = decrypt_password(config.api_key_enc)

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            is_codex = config.provider == "codex" or "codex" in (config.model or "").lower()
            if is_codex:
                resp = await client.post(
                    build_llm_responses_url(config.base_url),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config.model,
                        "input": "回复OK",
                    },
                )
            else:
                resp = await client.post(
                    build_llm_chat_completions_url(config.base_url),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config.model,
                        "messages": [{"role": "user", "content": "回复OK"}],
                        "max_tokens": 10,
                    },
                )
            if resp.status_code == 200:
                data = resp.json()
                if is_codex:
                    reply = ""
                    for item in data.get("output", []):
                        if item.get("type") != "message":
                            continue
                        for content in item.get("content", []):
                            reply += content.get("text", "")
                else:
                    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"success": True, "reply": reply[:100]}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


@router.post("/{config_id}/set-default")
async def set_default_llm_config(
    config_id: int,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """设为默认 LLM 配置"""
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.id == config_id, LLMConfig.tenant_id == ctx.tenant_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    if config.status != "active":
        raise HTTPException(status_code=400, detail="请先启用模型后再设为默认")

    await _clear_defaults(db, ctx.tenant_id, config.purpose)
    config.is_default = True
    await db.commit()
    await db.refresh(config)
    return LLMConfigResponse.from_db(config)


@router.post("/{config_id}/status")
async def update_llm_config_status(
    config_id: int,
    req: LLMConfigStatusUpdate,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """全局启用/禁用模型配置。"""
    if req.status not in {"active", "inactive"}:
        raise HTTPException(status_code=400, detail="状态只支持 active 或 inactive")

    result = await db.execute(
        select(LLMConfig).where(LLMConfig.id == config_id, LLMConfig.tenant_id == ctx.tenant_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    config.status = req.status
    if req.status == "inactive" and config.is_default:
        config.is_default = False
        await _assign_replacement_default(db, ctx.tenant_id, config.purpose, exclude_id=config.id)

    await db.commit()
    await db.refresh(config)
    return LLMConfigResponse.from_db(config)


# ── Helpers ──

async def _clear_defaults(db: AsyncSession, tenant_id: int, purpose: str):
    """清除同租户同用途的其他默认配置"""
    await db.execute(
        update(LLMConfig)
        .where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.is_default == True,
            LLMConfig.purpose.in_([purpose, "all"]) if purpose != "all" else LLMConfig.purpose.isnot(None),
        )
        .values(is_default=False)
    )


async def _assign_replacement_default(
    db: AsyncSession,
    tenant_id: int,
    purpose: str,
    exclude_id: Optional[int] = None,
):
    """当默认模型被禁用时，尽量补一个同用途的可用默认。"""
    stmt = (
        select(LLMConfig)
        .where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.purpose == purpose,
            LLMConfig.status == "active",
        )
        .order_by(LLMConfig.created_at.desc(), LLMConfig.id.desc())
    )
    if exclude_id is not None:
        stmt = stmt.where(LLMConfig.id != exclude_id)
    replacement = (await db.execute(stmt)).scalars().first()
    if replacement:
        replacement.is_default = True


async def get_llm_config_for_purpose(db: AsyncSession, tenant_id: int, purpose: str) -> Optional[LLMConfig]:
    """获取指定用途的默认 LLM 配置（供其他模块使用）"""
    # 先找精确匹配的 purpose
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.purpose == purpose,
            LLMConfig.is_default == True,
            LLMConfig.status == "active",
        )
    )
    config = result.scalar_one_or_none()
    if config:
        return config

    # 再找 purpose="all" 的
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.purpose == "all",
            LLMConfig.is_default == True,
            LLMConfig.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def get_default_llm_config_id_for_purpose(db: AsyncSession, tenant_id: int, purpose: str) -> Optional[int]:
    config = await get_llm_config_for_purpose(db, tenant_id, purpose)
    return config.id if config else None


async def list_llm_configs_for_purpose(db: AsyncSession, tenant_id: int, purpose: str) -> list[LLMConfig]:
    """列出指定用途可用的 LLM 配置，精确用途优先，其次 purpose=all。"""
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.status == "active",
        )
    )
    rows = result.scalars().all()

    exact = [row for row in rows if row.purpose == purpose]
    shared = [row for row in rows if row.purpose == "all"]

    sort_key = lambda row: (0 if row.is_default else 1, -(row.id or 0))
    exact.sort(key=sort_key)
    shared.sort(key=sort_key)

    return exact + [row for row in shared if row.id not in {item.id for item in exact}]


async def get_active_llm_config_by_id_for_purpose(
    db: AsyncSession,
    tenant_id: int,
    config_id: int,
    purpose: str,
) -> Optional[LLMConfig]:
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.id == config_id,
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.status == "active",
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        return None
    if config.purpose not in {purpose, "all"}:
        return None
    return config


async def resolve_llm_config_for_purpose(
    db: AsyncSession,
    tenant_id: int,
    purpose: str,
    selected_config_id: Optional[int] = None,
) -> Optional[LLMConfig]:
    if selected_config_id:
        config = await get_active_llm_config_by_id_for_purpose(
            db,
            tenant_id,
            selected_config_id,
            purpose,
        )
        if config:
            return config
    return await get_llm_config_for_purpose(db, tenant_id, purpose)
