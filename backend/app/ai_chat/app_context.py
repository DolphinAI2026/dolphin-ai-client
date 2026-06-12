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


async def _load_app_workspaces(
    db: AsyncSession,
    app_id: int,
    tenant_id: Optional[int],
    user_id: Optional[int],
) -> list[dict]:
    """Load self-dev workspaces explicitly bound to the current application."""
    if not user_id:
        return []
    try:
        from app.coding.workspace import WorkspaceManager

        manager = WorkspaceManager()
        rows = manager.list_accessible_workspaces(
            int(user_id),
            [int(app_id)],
            tenant_id=int(tenant_id) if tenant_id is not None else None,
        )
    except Exception as exc:
        log.warning("app_context: load app workspaces failed: %r", exc)
        return []

    out: list[dict] = []
    for ws in rows:
        try:
            project_id = ws.get("project_id")
            if project_id not in (None, "") and str(project_id) != str(app_id):
                continue
            ws = dict(ws)
            ws["binding_status"] = "bound" if str(project_id or "") == str(app_id) else "unbound_candidate"
            out.append(ws)
        except Exception:
            continue
    return out[:8]


def _workspace_line(ws: dict) -> str:
    ws_id = ws.get("id") or ws.get("ws_id") or ""
    project_type = ws.get("project_type") or ""
    project_name = ws.get("project_name") or ""
    display_name = ws.get("display_name") or project_name
    status = ws.get("status") or ""
    binding = ws.get("binding_status") or ("bound" if ws.get("project_id") else "unbound_candidate")
    binding_label = "已绑定" if binding == "bound" else "未绑定候选"
    return (
        f"- ws_id={ws_id} | type={project_type} | name={display_name} "
        f"| project_name={project_name} | status={status} | binding={binding_label}"
    )


async def build_app_context_block(
    db: AsyncSession, app_id: Optional[int], section: Optional[str] = None,
    tenant_id: Optional[int] = None, view_context: Optional[str] = None,
    user_id: Optional[int] = None,
) -> str:
    """组装应用上下文块。无 app_id / db 时返回空串。

    view_context: 前端传入的「用户此刻在看哪个表单/菜单/tab」的人话描述，让 agent
    知道「当前/这个」指的是哪个，不必去读浏览器页面（嵌入面板里浏览器工具不可用）。
    """
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
        "- 要了解应用结构（模型/表单/字段/菜单/流程）就用 list_apaas_* 等 MCP 工具直接查。",
    ]
    if view_context:
        parts.append(f"- 用户此刻正在看：{view_context}（用户说「当前/这个」表单/页面/字段时，默认指这个）")
    if section and section in _SECTION_HINTS:
        parts.append(f"- {_SECTION_HINTS[section]}")
    workspaces = await _load_app_workspaces(db, app_id, tenant_id, user_id)
    if workspaces:
        parts.append(
            "\n### 已有/候选自开发 workspace（优先复用）\n"
            "修改已有自开发代码 / 页面 / 组件时，先根据 ws_id 调 "
            "get_dev_workspace_status / glob_workspace / grep_workspace / read_workspace_file，"
            "再用 edit_workspace_files 或 write_workspace_files 修改。"
            "不要为同一个页面/组件调用 create_dev_workspace；只有用户明确要求新增一个自开发资产，"
            "且没有同名 workspace 时才允许新建。\n"
            + "\n".join(_workspace_line(ws) for ws in workspaces)
        )
    spec = await _load_spec_text(db, app_id)
    if spec:
        parts.append(f"\n### 应用 SPEC 摘要\n{spec}")
    skills = await _load_skills(db, app_id, tenant_id)
    if skills:
        parts.append("\n### 本应用已学习的操作技能（可复用，用 save_config_skill 可新增）\n" + "\n".join(f"- {s}" for s in skills))
    return "\n".join(parts)
