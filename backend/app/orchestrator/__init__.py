"""Orchestrator — 智能开发流水线的编排层（纯 Python，无 LLM）。

见 docs/internal/INTELLIGENT_DEV_AGENT_ARCHITECTURE_V1_2026-04-19.md § 2.3 / § 2.2

子模块：
- phases.py：Phase 枚举 + 合法转移表
- coordinator.py：phase 转移 + session 绑定 + 消息路由
"""
from app.orchestrator.coordinator import (
    RouteDecision,
    attach_brainstorm_session,
    attach_coding_session,
    detach_brainstorm_session,
    detach_coding_session,
    get_phase,
    on_agent_failed,
    on_brainstorm_emit,
    on_coding_done,
    on_spec_confirmed,
    on_user_cancel,
    reset_phase,
    route_user_message,
    start_brainstorm,
    transition_phase,
)
from app.orchestrator.driver import (
    AutoFixLoopResult,
    BrainstormDriveResult,
    CodingDriveResult,
    VerificationDriveResult,
    confirm_spec_and_prepare_coding,
    drive_brainstorm,
    drive_coding_from_spec,
    drive_coding_with_autofix,
    drive_verification,
)
from app.orchestrator.phases import (
    Phase,
    PhaseTransitionError,
    assert_transition,
    can_transition,
    is_awaiting_user,
    is_running,
    is_terminal,
    parse_phase,
)

__all__ = [
    # Phases
    "Phase",
    "PhaseTransitionError",
    "assert_transition",
    "can_transition",
    "parse_phase",
    "is_terminal",
    "is_running",
    "is_awaiting_user",
    # Coordinator
    "RouteDecision",
    "route_user_message",
    "get_phase",
    "transition_phase",
    "reset_phase",
    "attach_brainstorm_session",
    "detach_brainstorm_session",
    "attach_coding_session",
    "detach_coding_session",
    "start_brainstorm",
    "on_brainstorm_emit",
    "on_spec_confirmed",
    "on_coding_done",
    "on_agent_failed",
    "on_user_cancel",
    # Driver
    "BrainstormDriveResult",
    "CodingDriveResult",
    "VerificationDriveResult",
    "AutoFixLoopResult",
    "drive_brainstorm",
    "drive_coding_from_spec",
    "drive_verification",
    "drive_coding_with_autofix",
    "confirm_spec_and_prepare_coding",
]
