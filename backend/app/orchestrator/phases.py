"""Phase 状态机 — Orchestrator 层的核心。

架构文档 § 2.2：
    UNDERSTAND → CONFIRM → SCAFFOLD → GENERATE → VERIFY → DONE
       ↑                                                    │
       └──────────── ITERATE ←──────────────────────────────┘

MVP 把 SCAFFOLD / GENERATE 合并（都由 CodingAgent 驱动，区别只是是否新建 workspace）。
ITERATE 是 DONE 后用户再发消息的回路；本身不是一个 phase，是 triggering transition。
"""
from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    """对话的 coding phase（持久化到 conversations.coding_phase）"""
    IDLE = "idle"               # 未启动任何 agent（新建对话首状态）
    UNDERSTAND = "understand"   # BrainstormAgent 运行中（反问 / 场景识别）
    CONFIRM = "confirm"         # Brainstorm 产出 Spec，等用户确认
    SCAFFOLD = "scaffold"       # 新 workspace 创建中（仅首轮 initial）
    GENERATE = "generate"       # CodingAgent 运行中
    VERIFY = "verify"           # VerificationAgent 运行中（P4 实装；MVP 可跳过）
    DONE = "done"               # 全部完成，等用户迭代或关闭
    FAILED = "failed"           # 任一 agent 失败且无法恢复
    ABORTED = "aborted"         # 用户主动取消


# ══════════════════════════════════════════════════════════════
# 合法转移表
# ══════════════════════════════════════════════════════════════

# 每个 phase → 允许的下一个 phase 集合
_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.IDLE: {Phase.UNDERSTAND, Phase.ABORTED},
    Phase.UNDERSTAND: {
        Phase.CONFIRM,       # brainstorm emit spec 成功
        Phase.UNDERSTAND,    # 同 phase 自循环（ask_user 等用户答）
        Phase.FAILED,
        Phase.ABORTED,
    },
    Phase.CONFIRM: {
        Phase.SCAFFOLD,      # 用户确认 + 首轮
        Phase.GENERATE,      # 用户确认 + 迭代（workspace 已存在）
        Phase.UNDERSTAND,    # refine → 回到反问
        Phase.ABORTED,
        Phase.FAILED,
    },
    Phase.SCAFFOLD: {
        Phase.GENERATE,
        Phase.FAILED,
        Phase.ABORTED,
    },
    Phase.GENERATE: {
        Phase.VERIFY,        # MVP 可短路到 DONE
        Phase.DONE,
        Phase.FAILED,
        Phase.ABORTED,
    },
    Phase.VERIFY: {
        Phase.DONE,
        Phase.GENERATE,      # AC 失败 → 重试 coding（≤ 2 次，由 Orchestrator 计数）
        Phase.FAILED,
        Phase.ABORTED,
    },
    Phase.DONE: {
        Phase.UNDERSTAND,    # ITERATE：用户再发消息
    },
    Phase.FAILED: {
        Phase.UNDERSTAND,    # 重启一次 brainstorm（用户干预）
        Phase.ABORTED,
    },
    Phase.ABORTED: set(),    # 终态
}


class PhaseTransitionError(ValueError):
    """phase 转移违反状态机"""


def can_transition(from_phase: Phase, to_phase: Phase) -> bool:
    """判断转移是否合法"""
    return to_phase in _TRANSITIONS.get(from_phase, set())


def assert_transition(from_phase: Phase, to_phase: Phase) -> None:
    """合法转移断言 — 非法时 raise PhaseTransitionError"""
    if not can_transition(from_phase, to_phase):
        allowed = sorted(p.value for p in _TRANSITIONS.get(from_phase, set()))
        raise PhaseTransitionError(
            f"不允许从 phase={from_phase.value} 转到 {to_phase.value}；"
            f"合法转移：{allowed}"
        )


def parse_phase(value: str | None) -> Phase:
    """把 DB 字符串安全转 Phase，未知值当 IDLE。"""
    if not value:
        return Phase.IDLE
    try:
        return Phase(value)
    except ValueError:
        return Phase.IDLE


# ══════════════════════════════════════════════════════════════
# 语义查询
# ══════════════════════════════════════════════════════════════

def is_terminal(phase: Phase) -> bool:
    """DONE / FAILED / ABORTED 是终态（不会自动推进）"""
    return phase in (Phase.DONE, Phase.FAILED, Phase.ABORTED)


def is_running(phase: Phase) -> bool:
    """agent 正在运行（UI 应该显示进度）"""
    return phase in (Phase.UNDERSTAND, Phase.SCAFFOLD, Phase.GENERATE, Phase.VERIFY)


def is_awaiting_user(phase: Phase) -> bool:
    """等用户交互（UI 应该解锁输入或显示按钮）"""
    return phase in (Phase.IDLE, Phase.CONFIRM, Phase.DONE, Phase.FAILED)
