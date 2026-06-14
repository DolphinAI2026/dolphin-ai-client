"""Config Assistant self-learning skill tools."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import delete, or_, select

from app.database import AsyncSessionLocal
from app.models import ConfigAssistantSkill


_registered_mcp_ids: set[int] = set()


def register(mcp, resolve_identity: Callable[[int | None, int | None], tuple[int, int]]) -> None:
    """Register config skill tools on the shared FastMCP instance."""
    marker = id(mcp)
    if marker in _registered_mcp_ids:
        return
    _registered_mcp_ids.add(marker)

    @mcp.tool()
    async def save_config_skill(
        name: str,
        intent_keywords: str,
        steps_md: str,
        app_id: int = 0,
        notes: str = "",
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """把刚做完的一类操作存成 skill。下次用户说类似话，AI 能直接 follow 这个 skill 不用从零摸索。

        入参：
          name             skill 名（10-40 字，譬如"加报销单备注字段并挂表单"）
          intent_keywords  匹配关键词，逗号分隔（"加字段,新增字段,挂表单"）— SYSTEM_PROMPT 拼 prompt 时按 token 匹配
          steps_md         markdown 步骤（含 apaas MCP 调用，要写清"先 list X 拿 id 再 update"）
          app_id           可选，0 = 全局 skill（适用所有应用），>0 = 仅当前应用
          notes            可选备注（"小心 X 字段会触发审批" 之类）

        返回：{ok, skill_id, message}
        """
        if not name.strip() or not steps_md.strip():
            return {"ok": False, "error_code": "INVALID_PARAMS", "message": "name 和 steps_md 必填"}
        tid, _uid = resolve_identity(tenant_id, user_id)
        async with AsyncSessionLocal() as db:
            row = ConfigAssistantSkill(
                tenant_id=tid,
                app_id=app_id if app_id > 0 else None,
                name=name.strip()[:120],
                intent_keywords=intent_keywords.strip()[:500],
                steps_md=steps_md.strip(),
                notes=notes.strip() if notes.strip() else None,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return {
                "ok": True,
                "skill_id": row.id,
                "message": f"已保存 skill「{row.name}」(id={row.id})，下次说{intent_keywords.split(',')[0] if intent_keywords else '类似'}时我会复用。",
            }

    @mcp.tool()
    async def list_config_skills(
        app_id: int = 0,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """列出当前 tenant 的可用 skills（app_id=0 时列全局+所有 app 的；指定 app_id 列全局+该 app 的）。

        返回 [{id, name, intent_keywords, steps_md (前 500 字摘要), notes, scope}]
        """
        tid, _ = resolve_identity(tenant_id, user_id)
        async with AsyncSessionLocal() as db:
            stmt = select(ConfigAssistantSkill).where(ConfigAssistantSkill.tenant_id == tid)
            if app_id > 0:
                stmt = stmt.where(or_(
                    ConfigAssistantSkill.app_id.is_(None),
                    ConfigAssistantSkill.app_id == app_id,
                ))
            stmt = stmt.order_by(ConfigAssistantSkill.created_at.desc()).limit(50)
            rows = (await db.execute(stmt)).scalars().all()
            return {
                "ok": True,
                "count": len(rows),
                "skills": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "intent_keywords": r.intent_keywords,
                        "steps_md_excerpt": (r.steps_md or "")[:500],
                        "notes": r.notes,
                        "scope": "app" if r.app_id else "global",
                        "use_count": r.use_count,
                    }
                    for r in rows
                ],
            }

    @mcp.tool()
    async def get_config_skill(
        skill_id: int,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """读完整 skill 的 steps_md（list 只返摘要，要细节得调它）。

        会自动 +1 use_count + 更新 last_used_at，统计哪些 skill 被复用最多。
        """
        tid, _ = resolve_identity(tenant_id, user_id)
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(ConfigAssistantSkill).where(
                    ConfigAssistantSkill.id == skill_id,
                    ConfigAssistantSkill.tenant_id == tid,
                )
            )).scalar_one_or_none()
            if not row:
                return {"ok": False, "error_code": "NOT_FOUND", "message": f"skill_id={skill_id} 不存在"}
            row.use_count += 1
            row.last_used_at = datetime.utcnow()
            await db.commit()
            return {
                "ok": True,
                "skill": {
                    "id": row.id,
                    "name": row.name,
                    "intent_keywords": row.intent_keywords,
                    "steps_md": row.steps_md,
                    "notes": row.notes,
                    "scope": "app" if row.app_id else "global",
                    "use_count": row.use_count,
                },
            }

    @mcp.tool()
    async def delete_config_skill(
        skill_id: int,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """删除一个 skill — 用户说"忘了这个流程"/"以后不要这么干"时调。"""
        tid, _ = resolve_identity(tenant_id, user_id)
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(ConfigAssistantSkill).where(
                    ConfigAssistantSkill.id == skill_id,
                    ConfigAssistantSkill.tenant_id == tid,
                )
            )).scalar_one_or_none()
            if not row:
                return {"ok": False, "error_code": "NOT_FOUND", "message": f"skill_id={skill_id} 不存在"}
            name = row.name
            await db.execute(delete(ConfigAssistantSkill).where(ConfigAssistantSkill.id == skill_id))
            await db.commit()
            return {"ok": True, "message": f"已删除 skill「{name}」"}

