"""Read-only enterprise Code baseline collection and snapshot projection."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_chat.skills import SkillRegistry
from app.models import PlatformEnv, RegisteredWorkspace
from app.models.knowledge_doc import KnowledgeDoc
from app.system_assistant.policy import available_actions, choose_recommended_action

log = logging.getLogger(__name__)

_NODE_LABELS = {
    "workspace": "工程与工作区",
    "environment": "环境",
    "capability": "能力",
    "knowledge": "知识",
    "skill": "Skill",
    "governance": "治理",
    "templates": "模板来源",
}
_NODE_ORDER = tuple(_NODE_LABELS)


def _normalise_fact(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "unavailable", "source_status": "unavailable", "items": [], "metadata": {}}
    result = dict(value)
    result.setdefault("status", "missing")
    source_status = result.get("source_status")
    if source_status not in {"ready", "partial", "unavailable"}:
        # ``not_needed`` belongs to a node status, never to source health.
        result["source_status"] = "ready" if result["status"] == "not_needed" else "unavailable"
    result.setdefault("items", [])
    result.setdefault("metadata", {})
    return result


def build_baseline_snapshot(facts: dict[str, Any], *, tenant_id: int) -> dict[str, Any]:
    """Project generic source facts into the stable P0 response shape."""

    nodes: list[dict[str, Any]] = []
    source_status: dict[str, str] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for node_id in _NODE_ORDER:
        fact = _normalise_fact(facts.get(node_id))
        metadata = dict(fact.get("metadata") or {})
        if "validation_status" in fact:
            metadata.setdefault("validation_status", fact["validation_status"])
        status = fact["status"]
        if status == "ready" and metadata.get("validation_status") == "stale":
            status = "stale"
        node = {
            "id": node_id,
            "label": _NODE_LABELS[node_id],
            "status": status,
            "source_status": fact["source_status"],
            "items": list(fact.get("items") or []),
            "metadata": metadata,
        }
        nodes.append(node)
        by_id[node_id] = node
        source_status[node_id] = fact["source_status"]

    action = choose_recommended_action(by_id)
    return {
        "baseline_snapshot": {
            "version": "p0",
            "readonly": True,
            "tenant_id": int(tenant_id),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "nodes": nodes,
            "metadata": {
                "plan_created": False,
                "dynamic_plan_source": "not_available_in_p0",
                "unavailable_sources": [key for key, status in source_status.items() if status == "unavailable"],
                "partial_sources": [key for key, status in source_status.items() if status == "partial"],
            },
        },
        "recommended_action": action,
        "available_actions": available_actions(action),
        "source_status": source_status,
    }


def _source_failure(source: str, error: Exception) -> dict[str, Any]:
    log.warning("system assistant baseline source unavailable: %s: %s", source, error)
    return {"status": "unavailable", "source_status": "unavailable", "items": [], "metadata": {"error": source}}


async def collect_baseline_facts(db: AsyncSession, ctx: Any) -> dict[str, Any]:
    """Read only facts visible to the current user and tenant context."""

    tenant_id = int(getattr(ctx, "tenant_id", 0) or 0)
    user_id = int(getattr(getattr(ctx, "user", None), "id", 0) or 0)
    role = str(getattr(ctx, "tenant_role", "member") or "member")
    can_manage_environment = role in {"platform_admin", "tenant_admin"}
    facts: dict[str, Any] = {}

    try:
        rows = (await db.execute(
            select(RegisteredWorkspace).where(
                RegisteredWorkspace.tenant_id == tenant_id,
                RegisteredWorkspace.user_id == user_id,
            )
        )).scalars().all()
        facts["workspace"] = {
            "status": "ready" if rows else "missing",
            "source_status": "ready",
            "items": [{"id": row.ws_id, "name": row.display_name, "kind": row.workspace_type} for row in rows],
            "metadata": {"validation_status": "ready" if rows else "not_needed"},
        }
        facts["workspace"]["metadata"].update({"shared_assets": "unavailable"})
    except Exception as error:
        facts["workspace"] = _source_failure("workspace", error)

    if not can_manage_environment:
        facts["environment"] = {
            "status": "unavailable",
            "source_status": "unavailable",
            "items": [],
            "metadata": {
                "reason": "tenant_admin_required",
                "action": "request_environment_access",
            },
        }
    else:
        try:
            rows = (await db.execute(
                select(PlatformEnv).where(PlatformEnv.tenant_id == tenant_id)
            )).scalars().all()
            facts["environment"] = {
                "status": "ready" if any(row.status == "connected" for row in rows) else ("missing" if not rows else "partial"),
                "source_status": "ready",
                "items": [{"id": row.alias or str(row.id), "status": row.status, "default": row.is_default} for row in rows],
            }
        except Exception as error:
            facts["environment"] = _source_failure("environment", error)

    try:
        rows = (await db.execute(
            select(KnowledgeDoc).where(
                KnowledgeDoc.status == "published", KnowledgeDoc.tenant_id.is_(None)
            )
        )).scalars().all()
        facts["knowledge"] = {
            "status": "partial" if rows else "unavailable",
            "source_status": "partial" if rows else "unavailable",
            "items": [
                {
                    "id": row.slug,
                    "title": row.title,
                    "category": row.category,
                    "source": "builder_local_cache",
                }
                for row in rows
            ],
            "metadata": {
                "local_source": "builder_local_cache",
                "authoritative_source": "full_workspace",
                "authoritative_source_status": "unavailable",
            },
        }
    except Exception as error:
        facts["knowledge"] = _source_failure("knowledge", error)

    try:
        skills = [skill for skill in SkillRegistry().scan() if skill.source == "platform"]
        facts["skill"] = {
            "status": "partial" if skills else "unavailable",
            "source_status": "partial" if skills else "unavailable",
            "items": [
                {
                    "id": skill.name,
                    "source": "local_platform_preset",
                    "description": skill.description,
                }
                for skill in skills
            ],
            "metadata": {
                "local_source": "local_platform_preset",
                "unverified_user_skills_omitted": True,
                "authoritative_source": "full_workspace",
                "authoritative_source_status": "unavailable",
            },
        }
    except Exception as error:
        facts["skill"] = _source_failure("skill", error)

    permissions = getattr(ctx, "org_permissions", {}) or {}
    granted_permissions = (
        sorted(code for code, allowed in permissions.items() if allowed)
        if isinstance(permissions, dict)
        else []
    )
    facts["governance"] = {
        "status": "ready",
        "source_status": "ready",
        "items": [{"id": role, "permissions": granted_permissions}],
    }
    # No local API currently exposes shared Full Workspace assets, remote
    # capabilities, or a template catalog. Keep those facts explicit.
    facts["capability"] = {
        "status": "partial",
        "source_status": "partial",
        "items": [{"id": "local_read_only_baseline"}],
        "metadata": {"remote_capabilities": "unavailable"},
    }
    facts["templates"] = {
        "status": "unavailable",
        "source_status": "unavailable",
        "items": [],
        "metadata": {"reason": "template_catalog_not_exposed_in_p0"},
    }
    return facts


async def build_bootstrap(db: AsyncSession, ctx: Any) -> dict[str, Any]:
    facts = await collect_baseline_facts(db, ctx)
    return build_baseline_snapshot(facts, tenant_id=int(getattr(ctx, "tenant_id", 0) or 0))
