"""Seed data for multi-tenant system."""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.crypto import encrypt_password
from app.models import LLMConfig
from app.models.tenant import Tenant, Role
from app.permissions import PERMISSION_CODES


async def seed_default_roles(db: AsyncSession, tenant_id: int):
    """创建默认角色（租户管理员、开发者、查看者）"""

    # 检查是否已存在角色
    result = await db.execute(
        select(Role).where(Role.tenant_id == tenant_id).limit(1)
    )
    if result.scalar_one_or_none():
        return  # 已有角色，跳过

    # 1. 租户管理员 — 全部权限
    admin_permissions = {code: True for code in PERMISSION_CODES}
    admin_role = Role(
        tenant_id=tenant_id,
        role_name="租户管理员",
        role_code="R_tenant_admin",
        description="租户管理员，拥有全部权限",
        permissions=admin_permissions,
        is_system=True
    )
    db.add(admin_role)

    # 2. 开发者 — 应用和对话的全部权限
    developer_permissions = {
        "application:view": True,
        "application:create": True,
        "application:edit": True,
        "application:delete": True,
        "application:clone": True,
        "conversation:view": True,
        "conversation:create": True,
        "conversation:delete": True,
        "team:view": True,
    }
    developer_role = Role(
        tenant_id=tenant_id,
        role_name="开发者",
        role_code="R_developer",
        description="开发者，可以创建和管理应用",
        permissions=developer_permissions,
        is_system=False
    )
    db.add(developer_role)

    # 3. 查看者 — 只读权限
    viewer_permissions = {
        "application:view": True,
        "conversation:view": True,
    }
    viewer_role = Role(
        tenant_id=tenant_id,
        role_name="查看者",
        role_code="R_viewer",
        description="查看者，只能查看应用和对话",
        permissions=viewer_permissions,
        is_system=False
    )
    db.add(viewer_role)

    await db.commit()
    print(f"✅ 租户 {tenant_id} 的默认角色已创建")


def _builtin_llm_specs() -> list[dict]:
    """从环境变量构建内置模型配置清单。"""
    specs: list[dict] = []

    def _normalize_openai_base_url(base_url: str) -> str:
        base = (base_url or "").rstrip("/")
        if not base:
            return base
        if base.endswith(("/chat/completions", "/responses", "/v1")):
            return base
        # /anthropic 是 Anthropic SDK 专用路径，OpenAI compat 不需要，去掉
        if "/anthropic" in base:
            base = base[:base.index("/anthropic")]
        if not base or base.endswith("/v1"):
            return base
        return f"{base}/v1"

    def _append(
        *,
        config_name: str,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
        purpose: str,
        is_default: bool = False,
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ):
        if not base_url or not api_key or not model:
            return
        specs.append(
            {
                "config_name": config_name,
                "provider": provider,
                "base_url": _normalize_openai_base_url(base_url),
                "api_key": api_key,
                "model": model,
                "purpose": purpose,
                "is_default": is_default,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )

    _append(
        config_name="内置通用模型 (MiniMax)",
        provider="minimax",
        base_url=settings.llm_api_base,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        purpose="all",
        is_default=True,
    )
    _append(
        config_name="内置通用模型 (Qwen 3.5 Plus)",
        provider="qwen",
        base_url=settings.coding_model_qwen_base_url,
        api_key=settings.coding_model_qwen_api_key,
        model="qwen3.5-plus",
        purpose="all",
    )

    _append(
        config_name="内置 Coding Qwen",
        provider="qwen",
        base_url=settings.coding_model_qwen_base_url,
        api_key=settings.coding_model_qwen_api_key,
        model=settings.coding_model_qwen_model,
        purpose="coding",
    )
    _append(
        config_name="内置 Coding DeepSeek",
        provider="deepseek",
        base_url=settings.coding_model_deepseek_base_url,
        api_key=settings.coding_model_deepseek_api_key,
        model=settings.coding_model_deepseek_model,
        purpose="coding",
    )
    _append(
        config_name="内置 Coding Codex",
        provider="codex",
        base_url=settings.coding_model_codex_base_url,
        api_key=settings.coding_model_codex_api_key,
        model=settings.coding_model_codex_model,
        purpose="coding",
    )
    _append(
        config_name="内置 Coding GPT",
        provider="gpt",
        base_url=settings.coding_model_gpt54_base_url,
        api_key=settings.coding_model_gpt54_api_key,
        model=settings.coding_model_gpt54_model,
        purpose="coding",
    )
    _append(
        config_name="内置 Coding Sonnet",
        provider="sonnet",
        base_url=settings.coding_model_sonnet_base_url,
        api_key=settings.coding_model_sonnet_api_key,
        model=settings.coding_model_sonnet_model,
        purpose="coding",
        is_default=True,
    )
    _append(
        config_name="内置 Coding Opus",
        provider="opus",
        base_url=settings.coding_model_opus_base_url,
        api_key=settings.coding_model_opus_api_key,
        model=settings.coding_model_opus_model,
        purpose="coding",
    )

    return specs


async def sync_builtin_llm_configs(db: AsyncSession):
    """把 .env 中的内置模型同步到 llm_configs，避免前台重复手工配置。"""
    specs = _builtin_llm_specs()
    if not specs:
        return

    tenants = (await db.execute(select(Tenant))).scalars().all()
    if not tenants:
        return

    managed_names = {spec["config_name"] for spec in specs}

    for tenant in tenants:
        existing = (
            await db.execute(select(LLMConfig).where(LLMConfig.tenant_id == tenant.id))
        ).scalars().all()
        existing_by_name = {row.config_name: row for row in existing}

        manual_defaults = {
            purpose: any(
                row.is_default and row.config_name not in managed_names and row.purpose == purpose
                for row in existing
            )
            for purpose in {"all", "coding", "builder"}
        }

        synced_rows: list[LLMConfig] = []
        for spec in specs:
            row = existing_by_name.get(spec["config_name"])
            if row is None:
                row = LLMConfig(
                    tenant_id=tenant.id,
                    config_name=spec["config_name"],
                    provider=spec["provider"],
                    base_url=spec["base_url"],
                    api_key_enc=encrypt_password(spec["api_key"]),
                    model=spec["model"],
                    purpose=spec["purpose"],
                    is_default=False,
                    max_tokens=spec["max_tokens"],
                    temperature=spec["temperature"],
                    status="active",
                )
                db.add(row)
            else:
                row.provider = spec["provider"]
                row.base_url = spec["base_url"]
                row.api_key_enc = encrypt_password(spec["api_key"])
                row.model = spec["model"]
                row.purpose = spec["purpose"]
                row.max_tokens = spec["max_tokens"]
                row.temperature = spec["temperature"]
                if row.status not in {"active", "inactive", "error"}:
                    row.status = "active"
            synced_rows.append(row)

        by_purpose: dict[str, list[tuple[LLMConfig, dict]]] = {}
        for row, spec in zip(synced_rows, specs):
            by_purpose.setdefault(spec["purpose"], []).append((row, spec))

        for purpose, rows in by_purpose.items():
            if manual_defaults.get(purpose):
                continue
            default_name = next((spec["config_name"] for _, spec in rows if spec["is_default"]), None)
            for row, spec in rows:
                row.is_default = bool(default_name and spec["config_name"] == default_name)

    await db.commit()
    print("✅ 已同步内置 LLM 配置到 llm_configs")


async def seed_initial_data(db: AsyncSession):
    """初始化种子数据"""

    # 1. 检查是否已有默认租户
    result = await db.execute(
        select(Tenant).where(Tenant.tenant_code == "default")
    )
    default_tenant = result.scalar_one_or_none()

    if not default_tenant:
        # 创建默认租户（迁移脚本已创建，这里是兜底）
        default_tenant = Tenant(
            tenant_name="Default Tenant",
            tenant_code="default",
            plan_type="free",
            max_applications=100,
            status=1
        )
        db.add(default_tenant)
        await db.commit()
        await db.refresh(default_tenant)
        print(f"✅ 默认租户已创建，ID: {default_tenant.id}")

    # 2. 为默认租户创建角色
    await seed_default_roles(db, default_tenant.id)

    # 3. 同步环境变量中的内置模型到 llm_configs
    await sync_builtin_llm_configs(db)
