"""应用上下文 prompt 组装 — session 锁定 app_id 时给 run_agent 注入。

从 config stream（applications/__init__.py）移植 SPEC / skill / section 三段加载，
抽成不依赖路由的纯函数。无 app_id 时返回空串（自由态零影响）。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# 设计器 section 软提示（同 config 的 _CONFIG_CHAT_SECTION_HINTS 精神，不硬过滤）
_SECTION_HINTS = {
    "data": "用户当前在「数据建模」区，优先用模型字段/字典相关工具。",
    "ui": "用户当前在「页面/表单」区，优先用菜单/表单/列表相关工具。",
    "logic": "用户当前在「流程/逻辑」区，优先用流程/业务事件相关工具。",
    "permission": "用户当前在「权限」区，优先用角色/访问控制相关工具。",
    "extension": "用户当前在「扩展/二次开发」区，可用自开发包上传/关联 + codegen 工具。",
}


async def _load_application(db: AsyncSession, app_id: int) -> Optional[dict]:
    from app.models import Application
    try:
        app = await db.get(Application, app_id)
    except Exception as exc:
        log.warning("app_context: load application %s failed: %r", app_id, exc)
        return None
    if not app:
        return None
    return {
        "id": app.id,
        "name": getattr(app, "app_name", "") or "",
        "platform_env_id": getattr(app, "platform_env_id", None),
        "apaas_app_id": getattr(app, "apaas_app_id", None),
    }


async def _load_spec_text(db: AsyncSession, app_id: int) -> str:
    """移植 applications/__init__.py:2948-2967 的 SPEC 加载（canonical_spec → config_preview → requirement_doc，各 ≤12000）。"""
    from app.models import Application
    from app.models.spec import Spec
    try:
        app = await db.get(Application, app_id)
    except Exception:
        return ""
    if not app:
        return ""
    if getattr(app, "canonical_spec_id", None):
        try:
            row = (await db.execute(select(Spec).where(Spec.id == app.canonical_spec_id))).scalar_one_or_none()
            if row and row.payload:
                return json.dumps(row.payload, ensure_ascii=False)[:12000]
        except Exception as exc:
            log.warning("app_context: load canonical spec failed: %r", exc)
    if getattr(app, "config_preview", None):
        return app.config_preview[:12000]
    if getattr(app, "requirement_doc", None):
        return app.requirement_doc[:12000]
    return ""


async def _load_skills(db: AsyncSession, app_id: int, tenant_id: Optional[int]) -> list[str]:
    """移植 applications/__init__.py:3025-3046 的 skill 加载（本租户 + 本应用/全局，top 20）。"""
    if tenant_id is None:
        return []
    try:
        from app.models import ConfigAssistantSkill
        rows = (await db.execute(
            select(ConfigAssistantSkill)
            .where(
                ConfigAssistantSkill.tenant_id == tenant_id,
                or_(
                    ConfigAssistantSkill.app_id.is_(None),
                    ConfigAssistantSkill.app_id == app_id,
                ),
            )
            .order_by(ConfigAssistantSkill.use_count.desc(), ConfigAssistantSkill.created_at.desc())
            .limit(20)
        )).scalars().all()
        return [f"【skill_id={r.id}】「{r.name}」  关键词: {r.intent_keywords}" for r in rows]
    except Exception as exc:
        log.warning("app_context: load skills failed: %r", exc)
        return []


async def build_app_context_block(
    db: AsyncSession, app_id: Optional[int], section: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> str:
    """组装应用上下文块。无 app_id / db 时返回空串。"""
    if not app_id or db is None:
        return ""
    app = await _load_application(db, app_id)
    if not app:
        return ""
    parts = [
        "\n\n## 当前应用上下文（已锁定）",
        f"- 应用：{app['name']}（内部 id={app['id']}，apaas_app_id={app.get('apaas_app_id')}，env={app.get('platform_env_id')}）",
        "- 你正在这个应用内工作。配置改动立即生效；二次开发 / codegen 你现在就能干（相关工具已具备）。",
        "- 不要新建其它应用、不要跨应用操作；apaas 工具的 env_id / apaas_app_id 由后端按锁定应用填死。",
    ]
    if section and section in _SECTION_HINTS:
        parts.append(f"- {_SECTION_HINTS[section]}")
    spec = await _load_spec_text(db, app_id)
    if spec:
        parts.append(f"\n### 应用 SPEC 摘要\n{spec}")
    skills = await _load_skills(db, app_id, tenant_id)
    if skills:
        parts.append("\n### 本应用已学习的操作技能（可复用，用 save_config_skill 可新增）\n" + "\n".join(f"- {s}" for s in skills))
    return "\n".join(parts)
