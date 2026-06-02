"""Seed data for multi-tenant system."""
from __future__ import annotations
from collections.abc import Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.crypto import encrypt_password
from app.models import LLMConfig
from app.models.tenant import Tenant, Role
from app.permissions import PERMISSION_CODES


async def seed_default_roles(db: AsyncSession, tenant_id: int, *, commit: bool = True):
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

    if commit:
        await db.commit()
    else:
        await db.flush()
    print(f"✅ 租户 {tenant_id} 的默认角色已创建")


def _builtin_llm_specs() -> list[dict]:
    """从环境变量构建内置模型配置清单。"""
    specs: list[dict] = []

    def _normalize_openai_base_url(base_url: str) -> str:
        base = (base_url or "").rstrip("/")
        if not base:
            return base
        # Anthropic SDK 路径原样保存，vibe_agent 调用时自己会转换为 /v1
        if "/anthropic" in base:
            return base
        if base.endswith(("/chat/completions", "/responses", "/v1")):
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

    # 精简内置模型清单：低代码搭建统一走 gpt-5.5 / Qwen。
    # gpt-5.4 的历史连接信息容易漂移，停止作为内置 seed 初始化。
    # 其余模型用户按需通过"新增模型"自行添加。
    _append(
        config_name="内置通用模型 (gpt-5.5)",
        provider="dolphin",
        base_url=settings.dolphin_base_url,
        api_key=settings.dolphin_api_key,
        model=settings.dolphin_model,  # gpt-5.5
        purpose="all",
        is_default=True,
    )
    _append(
        config_name="内置通用模型 (Qwen 3.6 Plus)",
        provider="qwen",
        base_url=settings.coding_model_qwen_base_url,
        api_key=settings.coding_model_qwen_api_key,
        model="qwen3.6-plus",
        purpose="all",
    )

    return specs


# 历史 builtin 名清单：之前 seed 出来现在不再要的（精简到 gpt5.5/qwen3.6 后）
# 启动 sync 时若 tenant 下有这些 config_name 自动删除，避免管理员手工清理。
_OBSOLETE_BUILTIN_NAMES = {
    "内置通用模型 (MiniMax)",
    "内置通用模型 (Qwen 3.5 Plus)",
    "内置 Coding Qwen",
    "内置 Coding DeepSeek",
    "内置 Coding Codex",
    "内置 Coding GPT",
    "内置 Coding GPT (gpt-5.4)",
    "内置 Coding Sonnet",
    "内置 Coding Opus",
    "内置通用模型 (Dolphin gpt-5.5)",  # 旧名，新版改成 "内置通用模型 (gpt-5.5)"
    "dolphin.ai",  # 2026-06-02 旧 config_name(dolphin 集成已删，只剩 omnigate 网关）→ 清理，sync 会重新 seed 规范名
}


async def sync_builtin_llm_configs(
    db: AsyncSession,
    tenant_ids: Sequence[int] | None = None,
    *,
    commit: bool = True,
):
    """把 .env 中的内置模型同步到 llm_configs，避免前台重复手工配置。

    同时清理 _OBSOLETE_BUILTIN_NAMES 列表里的旧 builtin（之前 seed 出来现在
    不再要的），避免每次重启又出现一堆默认模型。
    """
    tenant_id_list = list(tenant_ids or [])
    if tenant_id_list:
        tenants = (
            await db.execute(select(Tenant).where(Tenant.id.in_(tenant_id_list)))
        ).scalars().all()
    else:
        tenants = (await db.execute(select(Tenant))).scalars().all()
    if not tenants:
        return

    specs = _builtin_llm_specs()
    managed_names = {spec["config_name"] for spec in specs}

    for tenant in tenants:
        # 1. 清理 obsolete builtin（不影响用户手工添加的同名 / 自定义命名 config）
        obsolete_rows = (await db.execute(
            select(LLMConfig).where(
                LLMConfig.tenant_id == tenant.id,
                LLMConfig.config_name.in_(_OBSOLETE_BUILTIN_NAMES),
            )
        )).scalars().all()
        for row in obsolete_rows:
            await db.delete(row)
        await db.flush()  # 让后续 select 看到删除结果

        if not specs:
            continue

        # 2. 已有同 (provider, model, purpose) 的用户配置则跳过新建（防止 builtin 跟用户自定义重复）
        existing = (
            await db.execute(select(LLMConfig).where(LLMConfig.tenant_id == tenant.id))
        ).scalars().all()
        existing_duplicate_by_key: dict[tuple[str, str, str], LLMConfig] = {}
        for row in existing:
            if row.config_name in managed_names:
                continue
            existing_duplicate_by_key.setdefault((row.provider, row.model, row.purpose), row)
        existing_by_name = {row.config_name: row for row in existing}

        manual_defaults = {
            purpose: any(
                row.is_default and row.config_name not in managed_names and row.purpose == purpose
                for row in existing
            )
            for purpose in {"all", "coding", "builder"}
        }

        synced_pairs: list[tuple[LLMConfig, dict]] = []
        for spec in specs:
            row = existing_by_name.get(spec["config_name"])
            if row is None:
                duplicate_row = existing_duplicate_by_key.get(
                    (spec["provider"], spec["model"], spec["purpose"])
                )
                if duplicate_row is not None:
                    # 复用用户已有同模型同用途配置，但仍保留 spec 元信息参与默认值判断。
                    synced_pairs.append((duplicate_row, spec))
                    continue
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
                # 2026-05-21 修：之前每次重启都把 max_tokens / temperature 强制覆盖
                # 回 spec hardcode (8192 / 0.3)，用户改成 200K / 1M 都被擦掉。
                # 现在只同步 .env 真"权威"字段 (provider/base_url/api_key/model)，
                # max_tokens / temperature 是用户在前台可调的"偏好"字段，保留不动。
                row.provider = spec["provider"]
                row.base_url = spec["base_url"]
                row.api_key_enc = encrypt_password(spec["api_key"])
                row.model = spec["model"]
                row.purpose = spec["purpose"]
                # row.max_tokens = spec["max_tokens"]      ← 故意删，保留用户编辑
                # row.temperature = spec["temperature"]    ← 同上
                if row.status not in {"active", "inactive", "error"}:
                    row.status = "active"
            synced_pairs.append((row, spec))

        by_purpose: dict[str, list[tuple[LLMConfig, dict]]] = {}
        for row, spec in synced_pairs:
            by_purpose.setdefault(spec["purpose"], []).append((row, spec))

        for purpose, rows in by_purpose.items():
            if manual_defaults.get(purpose):
                continue
            default_name = next((spec["config_name"] for _, spec in rows if spec["is_default"]), None)
            for row, spec in rows:
                row.is_default = bool(default_name and spec["config_name"] == default_name)

    if commit:
        await db.commit()
    else:
        await db.flush()
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
