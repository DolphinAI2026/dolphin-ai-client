"""BrainstormAgent — 需求对焦 + Spec 产出 agent。

见 docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md § 6

子模块：
- agent.py：BrainstormAgent(BaseAgent[dict])
- prompts.py：system prompt + build_user_prompt
- config.py：运行参数（max_turns / confidence 阈值 / ask_user 上限）
- confidence.py：compute_confidence + emit_decision
- state.py：BrainstormState + P1 清单
- tools/：5 个 tool 实现
"""
from app.agents.brainstorm.agent import BrainstormAgent
from app.agents.brainstorm.confidence import compute_confidence, emit_decision
from app.agents.brainstorm.config import (
    CONFIDENCE_EMIT_BLOCK,
    CONFIDENCE_EMIT_OK,
    CONFIDENCE_EMIT_WARN,
    MAX_ASK_USER_TURNS,
    MAX_TURNS,
)
from app.agents.brainstorm.state import BrainstormState, P1Question, make_p1_list
from app.agents.brainstorm.tools import build_brainstorm_tools

__all__ = [
    "BrainstormAgent",
    "BrainstormState",
    "P1Question",
    "make_p1_list",
    "build_brainstorm_tools",
    "compute_confidence",
    "emit_decision",
    "MAX_TURNS",
    "MAX_ASK_USER_TURNS",
    "CONFIDENCE_EMIT_OK",
    "CONFIDENCE_EMIT_WARN",
    "CONFIDENCE_EMIT_BLOCK",
]
