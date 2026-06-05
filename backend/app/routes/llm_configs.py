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
from app.deps import AuthContext, get_auth_context, require_tenant_admin, resolve_effective_tenant_id
from app.models import LLMConfig
from app.crypto import encrypt_password, decrypt_password
from app.llm_client import LLMClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/llm-configs", tags=["llm-configs"])

# ── Provider presets ──
PROVIDER_PRESETS = {
    "minimax": {"base_url": "https://api.minimax.chat/v1", "models": ["MiniMax-M2.7", "MiniMax-M1"]},
    "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "models": ["qwen3.5-plus", "qwen3.6-plus", "qwen-max", "qwen-plus", "qwen-turbo", "qwen3-coder-next"]},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "models": ["deepseek-chat", "deepseek-coder"]},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "models": ["glm-4-plus", "glm-4"]},
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "models": ["moonshot-v1-128k", "moonshot-v1-32k"]},
    "openai": {"base_url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini"]},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "models": ["claude-sonnet-4-20250514"]},
    "dolphin": {
        "base_url": "http://ai-agent.dfy.definesys.cn/omnigate/0",
        "models": ["gpt-5.5", "gpt-5.4", "gpt-5.3-codex", "claude-sonnet-4-6", "claude-opus-4-6"],
    },
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
    tenant_id: Optional[int] = None  # 仅平台管理员可指定目标租户;租户管理员忽略


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


class LLMModelsFetchRequest(BaseModel):
    provider: str
    base_url: str
    api_key: str


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
    # /anthropic 是 Anthropic SDK 专用路径，OpenAI compat 不需要，去掉
    if "/anthropic" in base:
        base = base[:base.index("/anthropic")]
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


def _extract_model_names(data: object) -> list[str]:
    """兼容 OpenAI/DashScope/代理网关常见模型列表响应。"""
    if isinstance(data, dict):
        raw_items = data.get("data") or data.get("models") or data.get("model_list") or []
    elif isinstance(data, list):
        raw_items = data
    else:
        raw_items = []

    names: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = str(
                item.get("id")
                or item.get("model")
                or item.get("name")
                or item.get("model_name")
                or ""
            )
        else:
            name = ""
        name = name.strip()
        if name and name not in names:
            names.append(name)
    return names


# ── Routes ──

@router.get("/presets")
async def get_provider_presets():
    """获取供应商预设配置"""
    return PROVIDER_PRESETS


@router.get("")
async def list_llm_configs(
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Optional[int] = Query(None),
):
    """列出某租户的 LLM 配置。平台管理员可用 ?tenant_id= 指定;租户管理员强制本租户。"""
    effective_tid = await _resolve_target_tenant_id(db, ctx, tenant_id)
    result = await db.execute(
        select(LLMConfig)
        .where(LLMConfig.tenant_id == effective_tid)
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
    tenant_id = await resolve_effective_tenant_id(db, ctx)
    rows = await list_llm_configs_for_purpose(db, tenant_id, purpose)
    return [LLMConfigOptionResponse.from_db(row) for row in rows]


@router.post("/models")
async def fetch_llm_models(
    req: LLMModelsFetchRequest,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
):
    """使用管理员填写的 API Key 从模型服务拉取可用模型。"""
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail="请先填写 API Key，再拉取模型")
    if not req.base_url.strip():
        raise HTTPException(status_code=400, detail="请先填写接入地址")

    base = req.base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        models_url = f"{base[:-len('/chat/completions')]}/models"
    elif base.endswith("/responses"):
        models_url = f"{base[:-len('/responses')]}/models"
    elif base.endswith("/models"):
        models_url = base
    elif base.endswith("/v1"):
        models_url = f"{base}/models"
    else:
        models_url = f"{base}/v1/models"

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(
                models_url,
                headers={
                    "Authorization": f"Bearer {req.api_key}",
                    "Content-Type": "application/json",
                },
            )
    except Exception as exc:
        logger.warning("fetch llm models failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"拉取模型失败：{str(exc)[:200]}")

    if resp.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"拉取模型失败：HTTP {resp.status_code}: {resp.text[:300]}",
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"模型服务返回非 JSON：{str(exc)[:200]}")

    models = _extract_model_names(data)
    if not models:
        raise HTTPException(status_code=502, detail="模型服务未返回可识别的模型列表")
    return {"models": models}


@router.post("")
async def create_llm_config(
    req: LLMConfigCreate,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """新增 LLM 配置（管理员）"""
    target_tid = await _resolve_target_tenant_id(db, ctx, req.tenant_id)
    if req.is_default:
        await _clear_defaults(db, target_tid, req.purpose)

    config = LLMConfig(
        tenant_id=target_tid,
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
        select(LLMConfig).where(LLMConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    _assert_tenant_access(ctx, config.tenant_id)

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
        await _clear_defaults(db, config.tenant_id, config.purpose)
        config.is_default = True
    elif req.is_default is False:
        config.is_default = False

    if config.status == "inactive" and config.is_default:
        config.is_default = False
        await _assign_replacement_default(db, config.tenant_id, config.purpose, exclude_id=config.id)

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
        select(LLMConfig).where(LLMConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    _assert_tenant_access(ctx, config.tenant_id)

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
        select(LLMConfig).where(LLMConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    _assert_tenant_access(ctx, config.tenant_id)

    api_key = decrypt_password(config.api_key_enc)

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            # Dolphin omnigate 是统一 OpenAI 兼容网关，所有模型都走 chat/completions
            is_unified_gateway = "/omnigate" in (config.base_url or "").lower()
            is_codex = (
                not is_unified_gateway
                and (config.provider == "codex" or "codex" in (config.model or "").lower())
            )
            is_anthropic_compat = (
                not is_unified_gateway and "/anthropic" in (config.base_url or "")
            )

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
            elif is_anthropic_compat:
                # Anthropic-compatible proxy（如 MiniMax），使用 Messages API
                base = config.base_url.rstrip("/").removesuffix("/v1")
                url = f"{base}/v1/messages"
                llm = LLMClient(api_key=api_key, base_url=config.base_url, model=config.model)
                resp = await client.post(
                    url,
                    headers=llm._anthropic_headers(),
                    json={
                        "model": config.model,
                        "messages": [{"role": "user", "content": "回复OK"}],
                        "max_tokens": 10,
                    },
                )
            else:
                test_body: dict = {
                    "model": config.model,
                    "messages": [{"role": "user", "content": "回复OK"}],
                    "max_tokens": 50,
                }
                # 思考模型（如 Qwen3.x）禁用思考以加快测试速度
                if config.provider == "qwen" or "qwen3" in (config.model or "").lower():
                    test_body["enable_thinking"] = False
                resp = await client.post(
                    build_llm_chat_completions_url(config.base_url),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=test_body,
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
                elif is_anthropic_compat:
                    reply = ""
                    for block in data.get("content", []):
                        if block.get("type") == "text":
                            reply += block.get("text", "")
                else:
                    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"success": True, "reply": reply[:100]}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    except Exception as e:
        return {"success": False, "error": str(e)[:300]}


@router.post("/{config_id}/set-default")
async def set_default_llm_config(
    config_id: int,
    ctx: Annotated[AuthContext, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """设为默认 LLM 配置"""
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    _assert_tenant_access(ctx, config.tenant_id)
    if config.status != "active":
        raise HTTPException(status_code=400, detail="请先启用模型后再设为默认")

    await _clear_defaults(db, config.tenant_id, config.purpose)
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
        select(LLMConfig).where(LLMConfig.id == config_id)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    _assert_tenant_access(ctx, config.tenant_id)

    config.status = req.status
    if req.status == "inactive" and config.is_default:
        config.is_default = False
        await _assign_replacement_default(db, config.tenant_id, config.purpose, exclude_id=config.id)

    await db.commit()
    await db.refresh(config)
    return LLMConfigResponse.from_db(config)


# ── Helpers ──

def _is_platform_admin(ctx: AuthContext) -> bool:
    return ctx.tenant_role == "platform_admin" or ctx.user.is_platform_admin


async def _resolve_target_tenant_id(db: AsyncSession, ctx: AuthContext, requested: Optional[int]) -> int:
    """平台管理员用 requested(缺省回退 effective tenant);租户管理员强制自己租户。"""
    if _is_platform_admin(ctx):
        return requested if requested else await resolve_effective_tenant_id(db, ctx)
    return ctx.tenant_id


def _assert_tenant_access(ctx: AuthContext, tenant_id: int) -> None:
    """平台管理员可访问任意租户;否则只能访问自己租户(越权按 404,不泄漏存在性)。"""
    if _is_platform_admin(ctx):
        return
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="配置不存在")


async def _clear_defaults(db: AsyncSession, tenant_id: int, purpose: str):
    """清除本租户所有默认配置；默认模型每租户唯一。"""
    await db.execute(
        update(LLMConfig)
        .where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.is_default == True,
        )
        .values(is_default=False)
    )


async def _assign_replacement_default(
    db: AsyncSession,
    tenant_id: int,
    purpose: str,
    exclude_id: Optional[int] = None,
):
    """当默认模型被禁用时，尽量补一个本租户同用途的可用默认。"""
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
    """获取本租户指定用途的默认 LLM 配置（供其他模块使用）。"""
    # 先找精确匹配的 purpose
    result = await db.execute(
        select(LLMConfig)
        .where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.purpose == purpose,
            LLMConfig.is_default == True,
            LLMConfig.status == "active",
        )
        .order_by(LLMConfig.created_at.desc(), LLMConfig.id.desc())
    )
    config = result.scalars().first()
    if config:
        return config

    # 再找 purpose="all" 的
    result = await db.execute(
        select(LLMConfig)
        .where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.purpose == "all",
            LLMConfig.is_default == True,
            LLMConfig.status == "active",
        )
        .order_by(LLMConfig.created_at.desc(), LLMConfig.id.desc())
    )
    config = result.scalars().first()
    if config:
        return config

    # 兜底选一个本租户可用模型，避免历史数据没有 default 时功能不可用。
    result = await db.execute(
        select(LLMConfig)
        .where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.status == "active",
        )
        .order_by(LLMConfig.created_at.desc(), LLMConfig.id.desc())
    )
    rows = result.scalars().all()
    for row in rows:
        if row.purpose == purpose:
            return row
    for row in rows:
        if row.purpose == "all":
            return row
    return None


async def get_default_llm_config_id_for_purpose(db: AsyncSession, tenant_id: int, purpose: str) -> Optional[int]:
    config = await get_llm_config_for_purpose(db, tenant_id, purpose)
    return config.id if config else None


async def list_llm_configs_for_purpose(db: AsyncSession, tenant_id: int, purpose: str) -> list[LLMConfig]:
    """列出本租户指定用途可用的 LLM 配置，精确用途优先，其次 purpose=all。"""
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


async def get_active_llm_config_by_id(
    db: AsyncSession,
    tenant_id: int,
    config_id: int,
) -> Optional[LLMConfig]:
    """按 id 查本租户 active LLM 配置；不限 purpose。

    用于 vibe_coding / ai_chat 这类不限 purpose 的会话级 selected_llm_config_id 校验。
    """
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.id == config_id,
            LLMConfig.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def get_active_llm_config_by_id_for_purpose(
    db: AsyncSession,
    tenant_id: int,
    config_id: int,
    purpose: str,
) -> Optional[LLMConfig]:
    result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.tenant_id == tenant_id,
            LLMConfig.id == config_id,
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
