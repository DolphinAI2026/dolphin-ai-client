from __future__ import annotations

from . import checks
from .types import AppSnapshotInput, CheckResult, DimensionScore, HealthReport
from .weights import (
    BUCKET_WEIGHTS,
    DIMENSION_BUCKET,
    DIMENSION_WEIGHTS,
    ENGINE_VERSION,
    GATE_CAP,
    HAS_CRITICAL_SCORE_CAP,
    grade_for,
)

CHECK_FUNCS = {
    "menus": checks.check_menus,
    "models": checks.check_models,
    "dicts": checks.check_dicts,
    "roles": checks.check_roles,
    "processes": checks.check_processes,
    "events": checks.check_events,
    "deploy": checks.check_deploy,
    "activity": checks.check_activity,
}
SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}
_DIM_ORDER = list(CHECK_FUNCS)


def _dimension_score(results: list[CheckResult]) -> tuple[float | None, bool, bool]:
    scored = [c for c in results if c.status != "na"]
    if not scored:
        return None, True, False
    score = sum(c.sub_score for c in scored) / len(scored)
    has_high = any(c.severity == "high" and c.status == "fail" for c in scored)
    if has_high:
        score = min(score, GATE_CAP)
    return score, False, has_high


def run_health_engine(inp: AppSnapshotInput) -> HealthReport:
    dims: list[DimensionScore] = []
    has_critical = False
    for dim, fn in CHECK_FUNCS.items():
        results = fn(inp)
        score, na, high = _dimension_score(results)
        if high:
            has_critical = True
        dims.append(
            DimensionScore(
                dimension=dim,
                score=score,
                na=na,
                weight_base=DIMENSION_WEIGHTS[dim],
                weight_used=0.0,
                checks=results,
            )
        )

    # 桶内 N/A 归一 → 每维度在桶内的实际权重
    bucket_intra: dict[str, float] = {}
    for d in dims:
        bucket = DIMENSION_BUCKET[d.dimension]
        if not d.na:
            bucket_intra[bucket] = bucket_intra.get(bucket, 0.0) + d.weight_base

    # 桶分（桶内加权平均）
    bucket_scores: dict[str, float | None] = {}
    for bucket in BUCKET_WEIGHTS:
        bdims = [d for d in dims if DIMENSION_BUCKET[d.dimension] == bucket and not d.na]
        wsum = bucket_intra.get(bucket, 0.0)
        if bdims and wsum:
            bucket_scores[bucket] = sum((d.score or 0.0) * (d.weight_base / wsum) for d in bdims)
        else:
            bucket_scores[bucket] = None

    # 桶间归一（缺桶剔除）
    active = {b: BUCKET_WEIGHTS[b] for b in BUCKET_WEIGHTS if bucket_scores[b] is not None}
    bwsum = sum(active.values())
    total = None
    if bwsum:
        total = sum(bucket_scores[b] * (w / bwsum) for b, w in active.items())
    # 有高危时总分封顶 —— 等级不得高于"中等"
    if total is not None and has_critical:
        total = min(total, HAS_CRITICAL_SCORE_CAP)

    # 维度全局实际权重（落库阅读用）= 桶间占比 × 桶内占比
    for d in dims:
        bucket = DIMENSION_BUCKET[d.dimension]
        wsum = bucket_intra.get(bucket, 0.0)
        if (not d.na) and bwsum and wsum and bucket in active:
            d.weight_used = (active[bucket] / bwsum) * (d.weight_base / wsum)
        else:
            d.weight_used = 0.0

    all_findings = [f for d in dims for c in d.checks for f in c.findings]
    all_findings.sort(key=lambda f: (SEV_ORDER[f.severity], _DIM_ORDER.index(f.dimension)))
    total_int = round(total) if total is not None else None
    return HealthReport(
        app_id=inp.app_id,
        apaas_app_id=inp.apaas_app_id,
        as_of=inp.as_of,
        total_score=total_int,
        grade=grade_for(total),
        has_critical=has_critical,
        dimensions=dims,
        findings=all_findings,
        data_coverage=dict(inp.coverage),
        engine_version=ENGINE_VERSION,
    )
