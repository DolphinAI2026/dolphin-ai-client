from __future__ import annotations

ENGINE_VERSION = "1.0"

# 桶级权重
BUCKET_WEIGHTS = {"config": 0.6, "runtime": 0.4}

# 维度 → 桶
DIMENSION_BUCKET = {
    "menus": "config",
    "models": "config",
    "dicts": "config",
    "roles": "config",
    "processes": "config",
    "events": "config",
    "deploy": "runtime",
    "activity": "runtime",
}

# 桶内维度权重（高=对错攸关）
DIMENSION_WEIGHTS = {
    "processes": 0.30,
    "models": 0.22,
    "menus": 0.18,
    "roles": 0.15,
    "events": 0.08,
    "dicts": 0.07,
    "deploy": 0.65,
    "activity": 0.35,
}

# fail 时按 severity 给的子分档
FAIL_SCORE_BY_SEVERITY = {"high": 20.0, "medium": 50.0, "low": 70.0, "none": 100.0}

# 高危封顶：单维度封顶 + 有高危时总分封顶（避免"健康 88 却 6 条断流"这种过乐观读数）
GATE_CAP = 50.0
HAS_CRITICAL_SCORE_CAP = 69.0  # 有高危 finding 时总分最高 69（即等级最高"中等"）

# 阈值
STALE_DAYS = 90  # activity.stale
ACTIVE_STATUS_NAMES = {"已上线"}  # deploy.unpublished 判定
ACTIVE_STATUS_CODES = {"RUNNING"}
ENABLE_VALUES = {"ENABLE", "ENABLED", "EFFECTIVE", "ACTIVE", "1", "TRUE", "ON"}


def grade_for(score: float | None) -> str:
    if score is None:
        return "未知"
    if score >= 85:
        return "健康"
    if score >= 70:
        return "良好"
    if score >= 55:
        return "中等"
    if score >= 40:
        return "风险"
    return "严重"
