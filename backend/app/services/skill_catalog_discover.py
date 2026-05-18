"""Discover real callables from app.skills and sync into agent_skill_catalog."""
from __future__ import annotations
import inspect
import logging
import importlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill_catalog import AgentSkillCatalog

logger = logging.getLogger(__name__)


# Map: callable name → (display name, category, default desc fallback)
SKILL_META = {
    "create_app": ("创建应用", "platform", "在 aPaaS 平台创建新应用记录，返回 app_id。"),
    "create_models": ("创建数据模型", "platform", "批量创建应用的数据模型表（含字段定义）。"),
    "create_dicts": ("创建数据字典", "platform", "批量创建应用使用的数据字典（含字典项）。"),
    "create_roles": ("创建角色", "platform", "为应用创建访问角色。"),
    "create_form": ("创建表单", "platform", "创建应用表单配置。"),
    "create_permissions": ("配置权限", "platform", "为角色配置数据模型 / 字段 / 操作粒度权限。"),
    "deploy_app": ("发布应用", "platform", "把应用发布到目标环境，使其可用。"),
    "login": ("aPaaS 登录", "platform", "用用户名密码换 platform token。"),
    "build_component": ("组件构建", "component", "通用组件构建器，支持 16 种 form widget。"),
    "run_full_build": ("一键构建", "orchestrator", "完整构建流程：创建应用 → 角色 → 字典 → 模型 → 表单 → 权限 → 发布。"),
}


def _extract_params_schema(fn: Any) -> dict | None:
    """Inspect callable signature → JSON schema (best-effort, no full type→jsonschema)."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    params: list[dict] = []
    for name, p in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        params.append({
            "name": name,
            "annotation": str(p.annotation) if p.annotation is not inspect.Parameter.empty else "Any",
            "required": p.default is inspect.Parameter.empty,
            "default": None if p.default is inspect.Parameter.empty else repr(p.default),
        })
    return {"params": params}


async def discover_skills(db: AsyncSession) -> int:
    """Scan app.skills package and insert new catalog rows. Returns count of NEW rows added."""
    pkg = importlib.import_module("app.skills")
    exports = getattr(pkg, "__all__", [])

    existing_rows = (await db.execute(select(AgentSkillCatalog))).scalars().all()
    existing_codes = {r.code for r in existing_rows}

    added = 0
    for code in exports:
        if code in existing_codes:
            continue
        if not hasattr(pkg, code):
            continue
        obj = getattr(pkg, code)
        # Only register callables (not registries / constants)
        if not callable(obj):
            continue
        meta = SKILL_META.get(code, (code, "general", inspect.getdoc(obj) or ""))
        display_name, category, fallback_desc = meta
        desc = (inspect.getdoc(obj) or fallback_desc).strip()
        # Identify module path
        module_path = obj.__module__ or "app.skills"
        callable_path = f"{module_path}:{code}"
        row = AgentSkillCatalog(
            code=code,
            name=display_name,
            desc=desc,
            category=category,
            callable_path=callable_path,
            params_schema=_extract_params_schema(obj),
            is_async=inspect.iscoroutinefunction(obj),
            is_active=True,
        )
        db.add(row)
        added += 1

    if added:
        await db.commit()
        logger.info("skill_catalog: added %d new rows", added)
    return added
