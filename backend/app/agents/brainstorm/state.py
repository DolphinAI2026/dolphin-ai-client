"""BrainstormAgent 运行态 — P1 问题清单 / 已回答项 / 检测到的场景。

独立于 BaseAgent 的 _messages：那边是 LLM 上下文，这边是业务语义状态。
snapshot 时要把这里的字段一起持久化（P2.3 才接 DB）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.spec.schema import OpenQuestion, SceneType


@dataclass
class P1Question:
    """P1 关键决策 — 架构文档 § 6.3 的场景特定问题"""
    key: str
    """问题标识，如 form_value_shape / bof_type"""

    question_zh: str
    """中文问题（给用户看的版本，与实际 ask_user 的 question 可能略有差异）"""

    answered: bool = False
    """用户是否已回答（或 LLM 已通过其他方式获取到答案）"""

    answer: Optional[str] = None
    """具体答案（字符串化，便于 snapshot）"""


# ══════════════════════════════════════════════════════════════
# 场景 → P1 清单
# ══════════════════════════════════════════════════════════════

def _component_p1() -> list[P1Question]:
    return [
        P1Question("form_value_shape", "组件的值是单值、范围还是数组？"),
        P1Question("bof_type", "数据存储类型是字符串、数字还是日期？"),
        P1Question("scenes_required", "需要哪些渲染场景（edit/read/list/print/search）？"),
    ]


def _web_page_p1() -> list[P1Question]:
    return [
        P1Question("page_form", "页面主要形式：表单、列表、详情、图表、混合？"),
        P1Question("data_source", "数据从哪里来？接口是否已有？"),
        P1Question("needs_pagination", "列表是否需要分页 / 搜索 / 筛选？"),
    ]


def _mobile_page_p1() -> list[P1Question]:
    return [
        P1Question("page_form", "移动端页面主要形式：列表、详情、表单、混合？"),
        P1Question("data_source", "数据从哪里来？接口是否已有？"),
        P1Question("navigation_mode", "导航方式：Tab / 顶部返回 / 下拉刷新？"),
    ]


def _backend_api_p1() -> list[P1Question]:
    return [
        P1Question("endpoint_count", "一共几个接口？每个接口做什么？"),
        P1Question("mpaas_tables", "是否读写 MpaaS 表？读哪些，写哪些？"),
        P1Question("auth", "是否需要特殊鉴权（租户级 / 用户级 / 内部免鉴权）？"),
    ]


def _backend_feign_p1() -> list[P1Question]:
    return [
        P1Question("upstream_api", "要调用的外部接口：URL / 方法 / 鉴权方式？"),
        P1Question("input_output", "入参 / 出参结构？"),
        P1Question("failover", "调用失败时的降级策略？"),
    ]


def _backend_scheduled_p1() -> list[P1Question]:
    return [
        P1Question("cron", "执行频率？cron 表达式或口语化描述"),
        P1Question("job_task", "任务做什么（读表 / 写表 / 调外部）？"),
        P1Question("concurrency", "是否需要防止重入？失败如何重试？"),
    ]


P1_BY_SCENE: dict[SceneType, list[P1Question]] = {
    SceneType.WEB_COMPONENT_DUAL: _component_p1(),
    SceneType.WEB_PAGE: _web_page_p1(),
    SceneType.MOBILE_PAGE: _mobile_page_p1(),
    SceneType.BACKEND_API: _backend_api_p1(),
    SceneType.BACKEND_FEIGN: _backend_feign_p1(),
    SceneType.BACKEND_SCHEDULED: _backend_scheduled_p1(),
}


def make_p1_list(scene: SceneType) -> list[P1Question]:
    """返回给定场景的 P1 问题 deep copy（避免外部 mutate 影响其他实例）"""
    return [P1Question(q.key, q.question_zh, q.answered, q.answer) for q in P1_BY_SCENE.get(scene, [])]


# ══════════════════════════════════════════════════════════════
# BrainstormState — agent 运行期完整业务状态
# ══════════════════════════════════════════════════════════════

@dataclass
class BrainstormState:
    """BrainstormAgent 业务语义状态。

    和 BaseAgent._messages 互补：
    - _messages：完整 LLM 对话（LLM 看得到）
    - BrainstormState：agent 内部决策用的结构化字段（LLM 看不到原始，通过 tools 查询）
    """
    scene_type: Optional[SceneType] = None
    """detect_scene tool 产出的结果"""

    scene_confidence: float = 0.0
    """场景识别置信度 0-1，scene_type=None 时必然为 0"""

    p1_questions: list[P1Question] = field(default_factory=list)
    """基于 scene_type 展开的 P1 问题清单（detect_scene 后填充）"""

    ask_user_count: int = 0
    """已问用户的次数（硬上限 MAX_ASK_USER_TURNS）"""

    open_questions: list[OpenQuestion] = field(default_factory=list)
    """未消解的模糊点 + 做的默认假设"""

    marketplace_queries: list[str] = field(default_factory=list)
    """已做过的 marketplace 检索 query（防重复查）"""

    workspace_context_read: bool = False
    """是否读过 workspace context（迭代场景）"""

    emitted: bool = False
    """是否已 emit_spec（emit 后 should_terminate=True）"""

    emitted_spec_id: Optional[str] = None
    """emit 后的 spec_id（finalize 取用）"""

    # —— Snapshot / restore —— #

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "scene_type": self.scene_type.value if self.scene_type else None,
            "scene_confidence": self.scene_confidence,
            "p1_questions": [
                {"key": q.key, "question_zh": q.question_zh, "answered": q.answered, "answer": q.answer}
                for q in self.p1_questions
            ],
            "ask_user_count": self.ask_user_count,
            "open_questions": [{"question": oq.question, "assumed_answer": oq.assumed_answer} for oq in self.open_questions],
            "marketplace_queries": list(self.marketplace_queries),
            "workspace_context_read": self.workspace_context_read,
            "emitted": self.emitted,
            "emitted_spec_id": self.emitted_spec_id,
        }

    @classmethod
    def from_snapshot(cls, snap: dict[str, Any]) -> "BrainstormState":
        scene = SceneType(snap["scene_type"]) if snap.get("scene_type") else None
        p1 = [
            P1Question(q["key"], q["question_zh"], q.get("answered", False), q.get("answer"))
            for q in snap.get("p1_questions", [])
        ]
        oqs = [OpenQuestion(**o) for o in snap.get("open_questions", [])]
        return cls(
            scene_type=scene,
            scene_confidence=snap.get("scene_confidence", 0.0),
            p1_questions=p1,
            ask_user_count=snap.get("ask_user_count", 0),
            open_questions=oqs,
            marketplace_queries=list(snap.get("marketplace_queries", [])),
            workspace_context_read=snap.get("workspace_context_read", False),
            emitted=snap.get("emitted", False),
            emitted_spec_id=snap.get("emitted_spec_id"),
        )

    # —— 语义辅助 —— #

    def p1_coverage(self) -> float:
        """已回答 P1 的比例，用于 confidence 计算"""
        if not self.p1_questions:
            return 0.0
        answered = sum(1 for q in self.p1_questions if q.answered)
        return answered / len(self.p1_questions)

    def mark_p1_answered(self, key: str, answer: str) -> bool:
        """把某个 P1 标记为已回答；返回是否命中"""
        for q in self.p1_questions:
            if q.key == key:
                q.answered = True
                q.answer = answer
                return True
        return False

    def all_p1_answered(self) -> bool:
        return all(q.answered for q in self.p1_questions) if self.p1_questions else False
