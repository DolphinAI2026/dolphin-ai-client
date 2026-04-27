"""BrainstormAgent 运行参数（阈值 / 上限 / 默认值）。

分离到独立文件是为了：
- 单元测试易 monkey-patch
- 未来根据场景动态调参（不同 scene_type 不同上限）不会散在代码各处
"""
from __future__ import annotations


# —— 轮次上限 —— #
MAX_TURNS: int = 15
"""BaseAgent 主循环上限。超过即降级 emit（见 on_max_turns_exceeded）"""

MAX_ASK_USER_TURNS: int = 5
"""ask_user 调用次数上限（架构文档 § 6.1 第 8 条：最多 5 轮反问）"""

# —— Confidence 阈值（架构文档 § 6.5）—— #
CONFIDENCE_EMIT_OK: float = 0.75
"""≥ 此值 emit_spec 正常放行"""

CONFIDENCE_EMIT_WARN: float = 0.5
"""[WARN, OK) 区间 emit 成功但打 warning（前端展示"方案置信度较低"）"""

CONFIDENCE_EMIT_BLOCK: float = 0.3
"""< 此值拒绝 emit，强制继续反问或降级"""

# —— Confidence 权重（架构文档 § 6.5）—— #
CONFIDENCE_WEIGHT_SCENE: float = 0.4
CONFIDENCE_WEIGHT_P1_COVERAGE: float = 0.6

# —— query_marketplace 返回上限 —— #
MARKETPLACE_TOP_K: int = 5
"""相似组件/页面检索返回前 K 条"""

# —— Session timeout（架构文档 § 6.7）—— #
SUSPEND_AFTER_IDLE_MINUTES: int = 30
ABORT_AFTER_SUSPENDED_DAYS: int = 7
