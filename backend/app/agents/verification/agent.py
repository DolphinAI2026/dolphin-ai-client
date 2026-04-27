"""VerificationAgent — 消费 Spec + workspace，逐条验收 AC，产出 Report。

继承 BaseAgent[dict]：finalize 返回 VerificationReport 的 dict 表示，
driver 负责落 verification_reports 表。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from app.agents.base import BaseAgent
from app.agents.types import AgentContext, AgentType, Tool
from app.agents.verification.config import MAX_TURNS
from app.agents.verification.prompts import AGENT_SYSTEM_PROMPT, build_user_prompt
from app.agents.verification.state import VerificationState, init_state_from_spec
from app.agents.verification.tools import build_verification_tools

logger = logging.getLogger(__name__)


class VerificationAgent(BaseAgent[dict]):
    """验收 agent"""

    agent_type = AgentType.VERIFICATION

    def __init__(self, context: AgentContext) -> None:
        super().__init__(context)

        # 从 ctx.input 提取 Spec + workspace_root
        inp = context.input or {}
        envelope = inp.get("spec_envelope")
        if not isinstance(envelope, dict):
            raise ValueError("VerificationAgent 需要 ctx.input['spec_envelope']")
        self._spec_envelope: dict[str, Any] = envelope
        self._coding_session_id: Optional[str] = inp.get("coding_session_id")

        ws_root_str = inp.get("workspace_root") or "/tmp"
        self._workspace_root = Path(ws_root_str)

        self._state = init_state_from_spec(envelope)
        self._state.coding_session_id = self._coding_session_id
        self._tools: list[Tool] = build_verification_tools(
            self._state, self._workspace_root,
        )

    # ══════════════════════════════════════════════════════════════
    # 必填抽象方法
    # ══════════════════════════════════════════════════════════════

    def get_system_prompt(self) -> str:
        override = (self.ctx.input or {}).get("system_prompt")
        if isinstance(override, str) and override.strip():
            return override
        return AGENT_SYSTEM_PROMPT

    def get_tools(self) -> list[Tool]:
        return self._tools

    def get_max_turns(self) -> int:
        return int((self.ctx.input or {}).get("max_turns") or MAX_TURNS)

    def build_initial_user_message(self) -> str:
        return build_user_prompt(
            spec_envelope=self._spec_envelope,
            workspace_root=str(self._workspace_root),
            ac_items_snapshot=[a.to_dict() for a in self._state.ac_items],
            constraint_snapshot=[c.to_dict() for c in self._state.constraint_results],
        )

    def should_terminate(self) -> tuple[bool, str]:
        if self._state.report_emitted:
            return True, f"report_emitted: {self._state.emitted_report_id}"
        return False, ""

    async def finalize(self) -> dict:
        """汇总最终报告。driver 拿这个 dict 写 verification_reports 表。"""
        # 若未 emit（降级路径），把剩余 pending AC 标为 needs_review
        if not self._state.report_emitted:
            for ac in self._state.ac_items:
                if ac.status == "pending":
                    ac.status = "needs_review"
                    ac.evidence = "agent 超时或未完成检查，需人工审核"
                    ac.confidence = 0.0
            for c in self._state.constraint_results:
                if c.status == "pending":
                    c.status = "ok"  # 默认视作未违反

        overall = self._state.overall_status()
        hard_violated = self._state.constraints_hard_violated()
        if hard_violated and overall != "failed":
            overall = "failed"

        return {
            "report_id": self._state.emitted_report_id,
            "emitted": self._state.report_emitted,
            "overall_status": overall,
            "passed_count": self._state.passed_count(),
            "failed_count": self._state.failed_count(),
            "total_ac": len(self._state.ac_items),
            "hard_violated_count": len(hard_violated),
            "items": [a.to_dict() for a in self._state.ac_items],
            "constraint_results": [c.to_dict() for c in self._state.constraint_results],
            "spec_id": self._state.spec_id,
            "coding_session_id": self._state.coding_session_id,
        }

    # ══════════════════════════════════════════════════════════════
    # Snapshot / Restore
    # ══════════════════════════════════════════════════════════════

    def _serialize_custom_state(self) -> dict[str, Any]:
        return {
            "verification_state": self._state.to_snapshot(),
            "spec_envelope": self._spec_envelope,
            "workspace_root": str(self._workspace_root),
            "coding_session_id": self._coding_session_id,
        }

    def _deserialize_custom_state(self, data: dict[str, Any]) -> None:
        vs = data.get("verification_state")
        if isinstance(vs, dict):
            self._state = VerificationState.from_snapshot(vs)
        env = data.get("spec_envelope")
        if isinstance(env, dict):
            self._spec_envelope = env
        ws = data.get("workspace_root")
        if ws:
            self._workspace_root = Path(ws)
        self._coding_session_id = data.get("coding_session_id")
        # 重新绑 tool 到恢复后的 state
        self._tools = build_verification_tools(self._state, self._workspace_root)

    # ══════════════════════════════════════════════════════════════
    # 访问器
    # ══════════════════════════════════════════════════════════════

    @property
    def state(self) -> VerificationState:
        return self._state
