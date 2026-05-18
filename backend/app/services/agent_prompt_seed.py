"""Seed default agent prompts from the existing hardcoded Python constants.

Phase C — extracts Builder agent's _PROMPT module constants into
agent_prompts rows so admins can edit them via /agents UI without code change.

Idempotent: only inserts rows for (tenant_id, agent_id, phase) tuples that
do not already exist. Safe to call on every agent run as a lazy upsert.
"""
from __future__ import annotations
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent_prompt import AgentPrompt

logger = logging.getLogger(__name__)


# Imported lazily to avoid heavy module loads at startup
def _load_builder_prompts() -> dict[str, str]:
    """Returns { phase: template } for the Builder agent.

    Reflects on the `app.builder_spec.agent` module's `_PROMPT`-suffixed
    string constants. Naming convention → phase key:
      SPEC_GATHERING_PROMPT         → "gathering"
      SPEC_DRAFTING_PROMPT          → "drafting"
      SPEC_REVISION_PROMPT          → "revision"
      SPEC_BOOTSTRAP_SILENT_PROMPT  → "bootstrap_silent"
      SPEC_BOOTSTRAP_INTERACTIVE_PROMPT → "bootstrap_interactive"
      SPEC_BOOTSTRAP_DIFF_PROMPT    → "bootstrap_diff"
    """
    from app.builder_spec import agent as builder_agent_mod
    out: dict[str, str] = {}
    for name in dir(builder_agent_mod):
        if not name.endswith("_PROMPT"):
            continue
        val = getattr(builder_agent_mod, name)
        if not isinstance(val, str):
            continue
        # 'SPEC_GATHERING_PROMPT' → 'gathering';
        # 'SPEC_BOOTSTRAP_SILENT_PROMPT' → 'bootstrap_silent'
        parts = name.split("_")
        if len(parts) >= 3:
            phase = "_".join(parts[1:-1]).lower()
        else:
            phase = name.lower().replace("_prompt", "")
        out[phase] = val
    return out


async def seed_agent_prompts_for_tenant(db: AsyncSession, tenant_id: int) -> int:
    """Insert default prompts for an agent if rows don't exist. Returns count inserted."""
    inserted = 0

    # Builder agent — load from app/builder_spec/agent.py module constants
    try:
        builder_prompts = _load_builder_prompts()
    except Exception as e:
        logger.warning("Failed to load builder prompts: %s", e)
        builder_prompts = {}

    for phase, template in builder_prompts.items():
        existing = (await db.execute(
            select(AgentPrompt).where(
                AgentPrompt.tenant_id == tenant_id,
                AgentPrompt.agent_id == "builder",
                AgentPrompt.phase == phase,
            )
        )).scalar_one_or_none()
        if existing:
            continue
        db.add(AgentPrompt(
            tenant_id=tenant_id,
            agent_id="builder",
            phase=phase,
            template=template,
            notes=f"Seeded from builder_spec.agent.SPEC_{phase.upper()}_PROMPT",
        ))
        inserted += 1

    if inserted:
        await db.commit()
        logger.info(
            "agent_prompt_seed: inserted %d Builder rows for tenant %d",
            inserted, tenant_id,
        )
    return inserted
