from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Severity = Literal["high", "medium", "low", "none"]
CheckStatus = Literal["pass", "partial", "fail", "na"]


@dataclass
class Finding:
    check_id: str
    dimension: str
    severity: Severity
    title: str
    detail: str
    objects: list[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class CheckResult:
    id: str
    dimension: str
    status: CheckStatus
    sub_score: float  # 0-100
    severity: Severity
    metric: Any = None
    findings: list[Finding] = field(default_factory=list)


@dataclass
class DimensionScore:
    dimension: str
    score: float | None  # None when na
    na: bool
    weight_base: float  # 配置权重
    weight_used: float  # 归一后全局实际权重
    checks: list[CheckResult] = field(default_factory=list)


@dataclass
class HealthReport:
    app_id: int
    apaas_app_id: str
    as_of: datetime
    total_score: int | None
    grade: str
    has_critical: bool
    dimensions: list[DimensionScore]
    findings: list[Finding]
    data_coverage: dict[str, bool]
    engine_version: str


@dataclass
class AppSnapshotInput:
    app_id: int
    apaas_app_id: str
    as_of: datetime
    menus: list[dict] | None = None
    models: list[dict] | None = None
    dicts: list[dict] | None = None
    roles: list[dict] | None = None
    processes: list[dict] | None = None
    events: list[dict] | None = None
    app_entry: dict | None = None  # query_app_list 中本应用条目
    deploy_records: list[dict] = field(default_factory=list)
    coverage: dict[str, bool] = field(default_factory=dict)  # 各源是否拉到
