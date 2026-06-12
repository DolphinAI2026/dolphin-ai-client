"""Seed Coding & Vibe agent prompts from hardcoded Python constants.

Phase D — extracts Coding (`agent_id='whale'`) and Vibe Coding (`agent_id='vibe'`)
hardcoded prompts into `agent_prompts` rows so admins can edit them via the
/agents UI without redeploying code.

Coding agent runtime:
  app.agents.coding.CodingAgent reads system prompt via ctx.input["system_prompt"],
  which is fed by app.coding.pipeline at construction time. Phase D wires that
  callsite to DB-first via app.services.prompt_resolver.resolve_prompt.

Vibe Coding agent runtime:
  app.vibe_coding.agent._build_initial_messages injects SYSTEM_PROMPT as the
  first system message. Phase D rewires that callsite to DB-first.

Idempotent: only inserts rows for (tenant_id, agent_id, phase) tuples that
do not already exist. Safe to call repeatedly as a lazy upsert.
"""
from __future__ import annotations
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent_prompt import AgentPrompt

logger = logging.getLogger(__name__)


def _load_coding_prompts() -> dict[str, str]:
    """Returns { phase: template } for the Coding (whale) agent.

    Reflects on `app.coding.prompts`:
      AGENT_SYSTEM_PROMPT → "default"

    Future _PROMPT-suffixed constants in that module will be auto-picked up
    using the same naming → phase mapping as Builder's seed loader.
    """
    from app.coding import prompts as p
    out: dict[str, str] = {}
    if hasattr(p, "AGENT_SYSTEM_PROMPT"):
        out["default"] = p.AGENT_SYSTEM_PROMPT
    for name in dir(p):
        if name == "AGENT_SYSTEM_PROMPT" or not name.endswith("_PROMPT"):
            continue
        val = getattr(p, name)
        if not isinstance(val, str):
            continue
        # e.g. SOME_PHASE_PROMPT → "some_phase"
        parts = name.split("_")
        if len(parts) >= 3:
            phase = "_".join(parts[:-1]).lower()
        else:
            phase = name.lower().replace("_prompt", "")
        if phase and phase not in out:
            out[phase] = val
    return out


def _load_unified_prompts() -> dict[str, str]:
    """Returns { phase: template } for the unified AIChat agent.

    The unified system prompt is the highest-traffic chat link. Its static
    template lives in `app.ai_chat.agent.SYSTEM_PROMPT_UNIFIED` (STANDARD_DOC_FORMAT
    is already baked in at import time; the app-context block is appended at
    runtime and intentionally NOT stored in DB).

    Imported lazily here to avoid a heavy `app.ai_chat.agent` import at startup
    and any circular import via prompt_resolver.
    """
    from app.ai_chat import agent as ai_chat_agent
    return {"system": ai_chat_agent.SYSTEM_PROMPT_UNIFIED}


async def seed_coding_prompts_for_tenant(db: AsyncSession, tenant_id: int) -> int:
    """Insert default Coding + Vibe + Unified prompts for a tenant if missing.

    Returns total count inserted across all agents.
    """
    inserted = 0
    loaders: list[tuple[str, callable, str]] = [
        ("whale", _load_coding_prompts, "app.coding.prompts.AGENT_SYSTEM_PROMPT"),
        ("unified", _load_unified_prompts, "app.ai_chat.agent.SYSTEM_PROMPT_UNIFIED"),
    ]
    for agent_id, loader, src in loaders:
        try:
            prompts = loader()
        except Exception as e:
            logger.warning("Failed to load %s prompts: %s", agent_id, e)
            continue
        for phase, template in prompts.items():
            existing = (await db.execute(
                select(AgentPrompt).where(
                    AgentPrompt.tenant_id == tenant_id,
                    AgentPrompt.agent_id == agent_id,
                    AgentPrompt.phase == phase,
                )
            )).scalar_one_or_none()
            if existing:
                continue
            db.add(AgentPrompt(
                tenant_id=tenant_id,
                agent_id=agent_id,
                phase=phase,
                template=template,
                notes=f"Seeded from {src} (phase={phase})",
            ))
            inserted += 1
    if inserted:
        await db.commit()
        logger.info(
            "coding_prompt_seed: inserted %d rows for tenant %d", inserted, tenant_id,
        )
    return inserted
