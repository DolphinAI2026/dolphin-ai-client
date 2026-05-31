"""VerificationAgent 的业务状态。

与 BaseAgent._messages（LLM 上下文）互补：这里记录"哪些 AC 已检查、结果如何"。
snapshot/restore 支持长跑（未来可能跑多分钟）中途断线恢复。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


# AC 单项结果状态
AcStatus = Literal["pending", "passed", "failed", "needs_review"]


@dataclass
class AcItem:
    """单条 acceptance criterion 的验收记录"""
    index: int
    """在 intent.acceptance_criteria 里的 0-based 下标"""

    description: str
    """AC 原文"""

    status: AcStatus = "pending"
    """验收状态"""

    evidence: str = ""
    """证据 —— grep 命中片段 / read 出的代码行 / LLM 总结。给用户看"""

    confidence: float = 0.0
    """0-1，LLM 对自己判断的置信度"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "description": self.description,
            "status": self.status,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AcItem":
        return cls(
            index=d["index"],
            description=d["description"],
            status=d.get("status", "pending"),  # type: ignore[arg-type]
            evidence=d.get("evidence", ""),
            confidence=float(d.get("confidence", 0.0)),
        )


@dataclass
class ConstraintResult:
    """hard/soft constraint 的检查结果"""
    text: str
    severity: Literal["hard", "soft"]
    status: Literal["pending", "ok", "violated"] = "pending"
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "severity": self.severity,
            "status": self.status,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConstraintResult":
        return cls(
            text=d["text"],
            severity=d.get("severity", "hard"),  # type: ignore[arg-type]
            status=d.get("status", "pending"),  # type: ignore[arg-type]
            evidence=d.get("evidence", ""),
        )


@dataclass
class VerificationState:
    """VerificationAgent 业务态"""
    spec_id: Optional[str] = None
    """被验收的 Spec ID"""

    coding_session_id: Optional[str] = None
    """对应的 coding session（用于 VerificationReport.coding_session_id）"""

    ac_items: list[AcItem] = field(default_factory=list)
    """所有 AC 的检查记录。agent 启动时从 Spec.intent.acceptance_criteria 初始化"""

    constraint_results: list[ConstraintResult] = field(default_factory=list)
    """hard/soft constraints 的检查记录"""

    report_emitted: bool = False
    """emit_report 工具是否已调用"""

    emitted_report_id: Optional[str] = None
    """emit 后的 report id（finalize 用）"""

    # —— 运行态辅助（不持久化）—— #
    read_files: set[str] = field(default_factory=set)
    """已读过的相对路径，避免重复读"""

    grep_queries: list[str] = field(default_factory=list)
    """已做过的 grep query 原文，便于 LLM 判断'是否已查过'"""

    # —— 查询辅助 —— #

    def pending_ac(self) -> list[AcItem]:
        return [a for a in self.ac_items if a.status == "pending"]

    def passed_count(self) -> int:
        return sum(1 for a in self.ac_items if a.status == "passed")

    def failed_count(self) -> int:
        return sum(1 for a in self.ac_items if a.status == "failed")

    def overall_status(self) -> Literal["passed", "failed", "partial", "pending"]:
        """汇总状态：
        - pending：还有未检查的
        - passed：全部 passed（无 failed、无 needs_review）
        - failed：至少一条 failed
        - partial：有 needs_review 但无 failed
        """
        if any(a.status == "pending" for a in self.ac_items):
            return "pending"
        if any(a.status == "failed" for a in self.ac_items):
            return "failed"
        if any(a.status == "needs_review" for a in self.ac_items):
            return "partial"
        return "passed"

    def constraints_hard_violated(self) -> list[ConstraintResult]:
        return [c for c in self.constraint_results if c.severity == "hard" and c.status == "violated"]

    # —— snapshot —— #

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "spec_id": self.spec_id,
            "coding_session_id": self.coding_session_id,
            "ac_items": [a.to_dict() for a in self.ac_items],
            "constraint_results": [c.to_dict() for c in self.constraint_results],
            "report_emitted": self.report_emitted,
            "emitted_report_id": self.emitted_report_id,
            "read_files": sorted(self.read_files),
            "grep_queries": list(self.grep_queries),
        }

    @classmethod
    def from_snapshot(cls, snap: dict[str, Any]) -> "VerificationState":
        return cls(
            spec_id=snap.get("spec_id"),
            coding_session_id=snap.get("coding_session_id"),
            ac_items=[AcItem.from_dict(x) for x in snap.get("ac_items") or []],
            constraint_results=[ConstraintResult.from_dict(x) for x in snap.get("constraint_results") or []],
            report_emitted=snap.get("report_emitted", False),
            emitted_report_id=snap.get("emitted_report_id"),
            read_files=set(snap.get("read_files") or []),
            grep_queries=list(snap.get("grep_queries") or []),
        )


# ══════════════════════════════════════════════════════════════
# 从 Spec envelope 初始化 state
# ══════════════════════════════════════════════════════════════

def init_state_from_spec(envelope: dict[str, Any]) -> VerificationState:
    """把 Spec 的 acceptance_criteria / constraints 展开为 AcItem / ConstraintResult"""
    state = VerificationState(spec_id=envelope.get("spec_id"))
    intent = envelope.get("intent") or {}
    acs = intent.get("acceptance_criteria") or []
    for i, txt in enumerate(acs):
        state.ac_items.append(AcItem(index=i, description=str(txt)))

    spec = envelope.get("spec") or {}
    for c in spec.get("constraints_hard") or []:
        state.constraint_results.append(ConstraintResult(text=str(c), severity="hard"))
    for c in spec.get("constraints_soft") or []:
        state.constraint_results.append(ConstraintResult(text=str(c), severity="soft"))

    return state
