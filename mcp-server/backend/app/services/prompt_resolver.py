"""Resolve agent prompt from DB first, fall back to hardcoded constant.

Used by Coding (whale) + Vibe (vibe) agent callsites. The Builder agent has
its own resolver inside builder_spec (Phase C). Both agents lazy-seed when
the row is missing so first call on a fresh tenant just works.

Usage:
    from app.services.prompt_resolver import resolve_prompt
    prompt = await resolve_prompt(
        db, tenant_id, agent_id="whale", phase="default",
        fallback=AGENT_SYSTEM_PROMPT,
    )
"""
from __future__ import annotations
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent_prompt import AgentPrompt

logger = logging.getLogger(__name__)


async def _fetch(
    db: AsyncSession, tenant_id: int, agent_id: str, phase: str,
) -> Optional[str]:
    row = (await db.execute(
        select(AgentPrompt).where(
            AgentPrompt.tenant_id == tenant_id,
            AgentPrompt.agent_id == agent_id,
            AgentPrompt.phase == phase,
        )
    )).scalar_one_or_none()
    return row.template if row else None


async def resolve_prompt(
    db: AsyncSession,
    tenant_id: int,
    *,
    agent_id: str,
    phase: str,
    fallback: str,
) -> str:
    """DB-first prompt resolution with lazy seed + hardcoded fallback.

    1. Try DB row for (tenant_id, agent_id, phase).
    2. If missing, lazy-seed all (whale + vibe) defaults for this tenant.
    3. Re-fetch; on still-missing return the hardcoded fallback.

    The fallback is what shipped in code today (e.g. AGENT_SYSTEM_PROMPT). If
    DB is unreachable or seeding fails, runtime behavior is preserved.
    """
    try:
        tmpl = await _fetch(db, tenant_id, agent_id, phase)
        if tmpl:
            return tmpl
    except Exception as e:
        logger.warning(
            "resolve_prompt: DB lookup failed for tenant=%s agent=%s phase=%s: %s",
            tenant_id, agent_id, phase, e,
        )
        return fallback

    # Lazy seed (idempotent — only inserts missing rows)
    try:
        from app.services.coding_prompt_seed import seed_coding_prompts_for_tenant
        await seed_coding_prompts_for_tenant(db, tenant_id)
    except Exception as e:
        logger.warning(
            "resolve_prompt: lazy seed failed for tenant=%s: %s", tenant_id, e,
        )
        return fallback

    try:
        tmpl = await _fetch(db, tenant_id, agent_id, phase)
        if tmpl:
            return tmpl
    except Exception:
        pass
    return fallback
