"""BrainstormAgent — 继承 BaseAgent[dict]，产出 Spec envelope dict。

职责：
- 通过 5 个 tool（detect_scene / ask_user / query_marketplace / read_workspace_context / emit_spec）
  把用户口语化需求转成结构化 Spec
- 遵守反问 9 原则（见 prompts.py）
- 在 max_turns 耗尽时降级：把当前 state 打包返回，并标注 degraded=True

和 CodingAgent 对比：
- CodingAgent 输出是"文件写入动作序列"，BrainstormAgent 输出是"一份结构化契约"
- CodingAgent 跑 30 轮，BrainstormAgent 跑 ≤15 轮
- CodingAgent 是自驱动循环，BrainstormAgent 可能中途 pause 等用户答
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.agents.base import BaseAgent
from app.agents.brainstorm.config import MAX_TURNS
from app.agents.brainstorm.prompts import AGENT_SYSTEM_PROMPT, build_user_prompt
from app.agents.brainstorm.state import BrainstormState
from app.agents.brainstorm.tools import build_brainstorm_tools
from app.agents.types import AgentContext, AgentType, Tool
from app.spec.schema import SceneType

logger = logging.getLogger(__name__)


class BrainstormAgent(BaseAgent[dict]):
    """产出 Spec envelope dict 的 agent"""

    agent_type = AgentType.BRAINSTORM

    def __init__(self, context: AgentContext) -> None:
        super().__init__(context)
        self._state = BrainstormState()
        self._tools: list[Tool] = build_brainstorm_tools(self._state)

        # 场景预判（可选，orchestrator 可以把上一轮识别的 scene 塞进来）
        scene_hint = (context.input or {}).get("scene_hint")
        if scene_hint:
            try:
                self._initial_scene_hint: Optional[SceneType] = SceneType(scene_hint)
            except Exception:
                self._initial_scene_hint = None
        else:
            self._initial_scene_hint = None

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
        inp = self.ctx.input or {}
        requirement = str(inp.get("requirement") or "").strip()
        if not requirement:
            raise ValueError("BrainstormAgent requires ctx.input['requirement']")

        workspace_info: Optional[dict[str, Any]] = None
        if self.ctx.workspace_id:
            # 懒加载，避免顶层循环依赖
            try:
                from app.coding import workspace as ws_module

                ws_mgr = ws_module.WorkspaceManager()
                workspace_info = ws_mgr.get_workspace_info(self.ctx.workspace_id)
            except Exception as e:
                logger.warning("加载 workspace 信息失败（继续走无 workspace 路径）: %s", e)
                workspace_info = None

        attachments = inp.get("attachments") or None
        is_iteration = bool(inp.get("is_iteration")) or workspace_info is not None

        return build_user_prompt(
            requirement=requirement,
            scene_hint=self._initial_scene_hint,
            workspace_info=workspace_info,
            attachments=attachments,
            is_iteration=is_iteration,
        )

    def should_terminate(self) -> tuple[bool, str]:
        # emit_spec 调用成功 → state.emitted=True → 下一轮终止
        if self._state.emitted:
            return True, f"spec_emitted: {self._state.emitted_spec_id}"
        return False, ""

    async def finalize(self) -> dict:
        """产出 Spec envelope。正常路径返回 emit_spec tool 写入的结构；
        降级路径（max_turns 耗尽未 emit）返回一个标注 degraded=True 的占位。
        """
        if self._state.emitted and self._state.emitted_spec_id:
            # emit_spec tool 执行时把完整 envelope 放进 tool result data，
            # 这里只需把 state 汇总返回给 orchestrator 即可；真正的 envelope
            # 持久化由 P2.3 API 层处理（orchestrator 从 tool_history 里捞到 envelope）。
            envelope = self._find_emit_envelope()
            return {
                "status": "ok",
                "spec_id": self._state.emitted_spec_id,
                "envelope": envelope,
                "degraded": False,
                "state_snapshot": self._state.to_snapshot(),
            }

        # 降级：未 emit 直接退出
        return {
            "status": "degraded",
            "spec_id": None,
            "envelope": None,
            "degraded": True,
            "reason": (self._stop_reason.value if self._stop_reason else "unknown"),
            "state_snapshot": self._state.to_snapshot(),
        }

    # ══════════════════════════════════════════════════════════════
    # Hook：把 emit_spec 成功时的 envelope 缓存下来（避免遍历 tool_history）
    # ══════════════════════════════════════════════════════════════

    async def after_tool_call(self, tool: Tool, result):  # type: ignore[override]
        # 记录到 tool_history，后续 _find_emit_envelope 用
        if tool.name == "emit_spec" and result.success:
            self._tool_history.append({
                "tool": "emit_spec",
                "success": True,
                "data": result.data,
            })
        return result

    def _find_emit_envelope(self) -> Optional[dict[str, Any]]:
        """从 tool_history 找最近一次 emit_spec 成功时的 envelope"""
        for entry in reversed(self._tool_history):
            if entry.get("tool") == "emit_spec" and entry.get("success"):
                data = entry.get("data") or {}
                env = data.get("envelope")
                if isinstance(env, dict):
                    return env
        return None

    # ══════════════════════════════════════════════════════════════
    # 降级策略：max_turns 耗尽时把剩余 P1 转成 open_questions 记录
    # ══════════════════════════════════════════════════════════════

    async def on_max_turns_exceeded(self) -> None:
        """轮次耗尽。BrainstormAgent 的降级策略：
        - 未 emit → 把未回答的 P1 标注成 open_question 并记录到 state
          （finalize 会返回 degraded=True，由 orchestrator 决定是否提示用户）
        """
        if self._state.emitted:
            return
        from app.spec.schema import OpenQuestion

        for q in self._state.p1_questions:
            if not q.answered and q.question_zh:
                if not any(oq.question == q.question_zh for oq in self._state.open_questions):
                    self._state.open_questions.append(
                        OpenQuestion(
                            question=q.question_zh,
                            assumed_answer="（max_turns 耗尽，agent 未能回答）",
                        )
                    )

    # ══════════════════════════════════════════════════════════════
    # Snapshot / Resume
    # ══════════════════════════════════════════════════════════════

    def _serialize_custom_state(self) -> dict[str, Any]:
        return {
            "brainstorm_state": self._state.to_snapshot(),
            "initial_scene_hint": self._initial_scene_hint.value if self._initial_scene_hint else None,
        }

    def _deserialize_custom_state(self, data: dict[str, Any]) -> None:
        bs = data.get("brainstorm_state")
        if isinstance(bs, dict):
            self._state = BrainstormState.from_snapshot(bs)
            # 重新绑 tools 到新 state 实例
            self._tools = build_brainstorm_tools(self._state)
        hint = data.get("initial_scene_hint")
        if hint:
            try:
                self._initial_scene_hint = SceneType(hint)
            except Exception:
                self._initial_scene_hint = None

    # ══════════════════════════════════════════════════════════════
    # 对外访问器（测试 / orchestrator 用）
    # ══════════════════════════════════════════════════════════════

    @property
    def state(self) -> BrainstormState:
        return self._state
