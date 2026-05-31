"""Confidence 计算 — 简单版（架构文档 § 6.5）。

公式：confidence = 0.4 * scene_confidence + 0.6 * p1_coverage

不采用 5 维度复杂版的理由（架构文档）：
- 维度越多越容易被 LLM 打高分混过关
- 简单版更抗 game、更易调
"""
from __future__ import annotations

from app.agents.brainstorm.config import (
    CONFIDENCE_EMIT_BLOCK,
    CONFIDENCE_EMIT_OK,
    CONFIDENCE_EMIT_WARN,
    CONFIDENCE_WEIGHT_P1_COVERAGE,
    CONFIDENCE_WEIGHT_SCENE,
)
from app.agents.brainstorm.state import BrainstormState


def compute_confidence(state: BrainstormState) -> float:
    """按权重组合 scene_confidence 和 p1_coverage。范围 [0, 1]。"""
    score = (
        CONFIDENCE_WEIGHT_SCENE * max(0.0, min(1.0, state.scene_confidence))
        + CONFIDENCE_WEIGHT_P1_COVERAGE * state.p1_coverage()
    )
    return round(max(0.0, min(1.0, score)), 3)


def emit_decision(confidence: float) -> tuple[str, str]:
    """根据 confidence 返回 (gate, reason)。

    - gate="ok"：正常 emit
    - gate="warn"：emit 但前端展示"置信度较低"
    - gate="block"：拒绝 emit，继续反问或降级
    """
    if confidence >= CONFIDENCE_EMIT_OK:
        return "ok", f"confidence={confidence} ≥ {CONFIDENCE_EMIT_OK}，可直接 emit"
    if confidence >= CONFIDENCE_EMIT_WARN:
        return "warn", (
            f"confidence={confidence} ∈ [{CONFIDENCE_EMIT_WARN}, {CONFIDENCE_EMIT_OK})，"
            "emit 成功但前端应展示『方案置信度较低』提示"
        )
    if confidence >= CONFIDENCE_EMIT_BLOCK:
        return "block", (
            f"confidence={confidence} ∈ [{CONFIDENCE_EMIT_BLOCK}, {CONFIDENCE_EMIT_WARN})，"
            "emit 被拒，建议继续反问关键 P1 问题"
        )
    return "block", (
        f"confidence={confidence} < {CONFIDENCE_EMIT_BLOCK}，严重不足，"
        "必须继续反问或回到场景识别"
    )
