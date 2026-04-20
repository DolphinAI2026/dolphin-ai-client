"""VerificationAgent — AC 验收 agent。

见 docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md § 2.1 / § 5.2
"""
from app.agents.verification.agent import VerificationAgent
from app.agents.verification.config import MAX_AUTO_FIX_ROUNDS, MAX_TURNS
from app.agents.verification.state import (
    AcItem,
    ConstraintResult,
    VerificationState,
    init_state_from_spec,
)
from app.agents.verification.tools import build_verification_tools

__all__ = [
    "VerificationAgent",
    "VerificationState",
    "AcItem",
    "ConstraintResult",
    "init_state_from_spec",
    "build_verification_tools",
    "MAX_TURNS",
    "MAX_AUTO_FIX_ROUNDS",
]
