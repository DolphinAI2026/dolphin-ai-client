"""表分类器：把反向建模拿到的 DB schema 划分成 green/yellow/red/skip 四档。

输入：`schemas: dict[str, dict]`，键是表名，值是 `{"pk": str|None, "fields": [...]}`。
每个 field 至少包含 `name` / `type` / `nullable` / `comment` / `is_pk`。

输出：`{table_name: ClassifyResult}`，其中 `ClassifyResult` 用 health + badge +
reason + flags 四元组描述分类结果，方便上层 wizard 决定哪些表反向建模、哪些跳过、
哪些提示用户简化。

分类规则按优先级从上往下，第一个命中即返回（详见 `_RULES`）：

1. skip   框架表（Spring/Flyway/Quartz/act/oauth/databasechangelog 等前缀）
2. red    审计/历史表（_log/_audit/_history/_event/_trace 后缀）
3. red    无主键表
4. yellow 关联表（≤4 列且 ≥70% 列名以 _id 结尾）
5. yellow 超宽表（>30 列）
6. yellow 含 BLOB/LONGTEXT/MEDIUMTEXT 大字段
7. green  默认（5-30 列 + 有 PK + 至少一个业务字段名）
"""

from __future__ import annotations

from typing import Literal, TypedDict


class ClassifyResult(TypedDict):
    """单表分类结果。"""

    health: Literal["green", "yellow", "red", "skip"]
    badge: str
    reason: str
    flags: list[str]


# 框架表名前缀（不区分大小写）。
_FRAMEWORK_PREFIXES: tuple[str, ...] = (
    "spring_",
    "flyway_",
    "qrtz_",
    "shedlock_",
    "act_",
    "oauth_",
    "databasechangelog",
)

# 审计/历史/日志类后缀。
_AUDIT_SUFFIXES: tuple[str, ...] = ("_log", "_audit", "_history", "_event", "_trace")

# 视为「业务字段」的列名候选（用于 green 默认档的最后一道校验）。
_BUSINESS_FIELD_NAMES: frozenset[str] = frozenset(
    {"name", "title", "code", "desc", "desc_"}
)

# 视为「大字段」的列类型关键字（小写匹配）。
_BIG_FIELD_TYPES: tuple[str, ...] = ("blob", "longtext", "mediumtext")


def _is_framework_table(table_name: str) -> bool:
    """命中框架表前缀（不区分大小写）。"""
    lower = table_name.lower()
    return any(lower.startswith(prefix) for prefix in _FRAMEWORK_PREFIXES)


def _is_audit_table(table_name: str) -> bool:
    """命中审计/历史/日志类后缀（不区分大小写）。"""
    lower = table_name.lower()
    return any(lower.endswith(suffix) for suffix in _AUDIT_SUFFIXES)


def _has_primary_key(schema: dict) -> bool:
    """是否声明了主键：`pk` 字段非空，或任一 field `is_pk=True`。"""
    if schema.get("pk"):
        return True
    fields = schema.get("fields") or []
    return any(bool(f.get("is_pk")) for f in fields)


def _looks_like_join_table(fields: list[dict]) -> bool:
    """≤4 列且 ≥70% 列名以 `_id` 结尾，典型 m2m 中间表特征。"""
    if not fields or len(fields) > 4:
        return False
    id_like = sum(1 for f in fields if str(f.get("name", "")).lower().endswith("_id"))
    return id_like / len(fields) >= 0.7


def _has_big_field(fields: list[dict]) -> bool:
    """任一字段 type 含 blob/longtext/mediumtext。"""
    for field in fields:
        type_str = str(field.get("type", "")).lower()
        if any(token in type_str for token in _BIG_FIELD_TYPES):
            return True
    return False


def _has_business_field(fields: list[dict]) -> bool:
    """至少有一个业务字段名（name/title/code/desc/desc_）。"""
    for field in fields:
        name = str(field.get("name", "")).lower()
        if name in _BUSINESS_FIELD_NAMES:
            return True
    return False


def classify_single_table(table_name: str, schema: dict) -> ClassifyResult:
    """单张表分类（公开，方便测试）。

    按 `_RULES` 顺序匹配，首条命中即返回；都不命中则落到 green 默认档。
    """
    fields: list[dict] = schema.get("fields") or []
    n_cols = len(fields)

    if _is_framework_table(table_name):
        return ClassifyResult(
            health="skip",
            badge="框架表",
            reason="Spring/Flyway/Quartz 等框架自带表，不建模",
            flags=["framework"],
        )

    if _is_audit_table(table_name):
        return ClassifyResult(
            health="red",
            badge="不建议",
            reason="审计/历史日志表，CRUD 没意义",
            flags=["audit"],
        )

    if not _has_primary_key(schema):
        return ClassifyResult(
            health="red",
            badge="无主键",
            reason="无主键，平台 CRUD 需要主键",
            flags=["no_pk"],
        )

    if _looks_like_join_table(fields):
        return ClassifyResult(
            health="yellow",
            badge="关联表",
            reason="看起来是 m2m 关联表，建模为中间表",
            flags=["join_table"],
        )

    if n_cols > 30:
        return ClassifyResult(
            health="yellow",
            badge="建议简化",
            reason=f"列数 {n_cols}，建议表单只展示核心字段",
            flags=["too_wide"],
        )

    if _has_big_field(fields):
        return ClassifyResult(
            health="yellow",
            badge="建议简化",
            reason="含 BLOB/LONGTEXT 字段，建议表单不直接展示",
            flags=["big_field"],
        )

    flags: list[str] = []
    if not (5 <= n_cols <= 30):
        flags.append("col_count_out_of_range")
    if not _has_business_field(fields):
        flags.append("no_business_field")

    return ClassifyResult(
        health="green",
        badge="优秀",
        reason="字段适中、有主键，适合反向建模",
        flags=flags or ["ok"],
    )


def classify_tables(schemas: dict[str, dict]) -> dict[str, ClassifyResult]:
    """对每张表分类。返回 `{table_name: ClassifyResult}`，保持输入顺序。"""
    return {name: classify_single_table(name, schema) for name, schema in schemas.items()}
