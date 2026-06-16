from __future__ import annotations

from datetime import datetime

from .types import AppSnapshotInput, CheckResult, Finding
from .weights import (
    ACTIVE_STATUS_CODES,
    ACTIVE_STATUS_NAMES,
    ENABLE_VALUES,
    FAIL_SCORE_BY_SEVERITY,
    STALE_DAYS,
)


def _enabled(v) -> bool:
    return str(v).strip().upper() in ENABLE_VALUES if v is not None else True


def _fail(cid, dim, sev, title, detail, objs, sug) -> CheckResult:
    return CheckResult(
        cid,
        dim,
        "fail",
        FAIL_SCORE_BY_SEVERITY[sev],
        sev,
        metric=len(objs),
        findings=[Finding(cid, dim, sev, title, detail, objs, sug)],
    )


def _pass(cid, dim) -> CheckResult:
    return CheckResult(cid, dim, "pass", 100.0, "none", metric=0)


def _count_check(cid, dim, sev, bad: list[str], title, sug) -> CheckResult:
    if not bad:
        return _pass(cid, dim)
    return _fail(cid, dim, sev, title, f"{len(bad)} 个：{', '.join(bad[:5])}", bad, sug)


def _na(cid, dim) -> CheckResult:
    return CheckResult(cid, dim, "na", 0.0, "none")


def _as_dicts(seq) -> list[dict]:
    """只保留 dict 项 —— 真实接口偶尔返回字符串/混杂结构，防御性过滤。"""
    if not isinstance(seq, list):
        return []
    return [x for x in seq if isinstance(x, dict)]


def _parse_dt(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s)[:19], fmt)
        except (TypeError, ValueError):
            continue
    return None


# ─── 配置层 ──────────────────────────────────────────────────────────


def check_processes(inp: AppSnapshotInput) -> list[CheckResult]:
    # 注：连线(edges)只在流程详情里，collector 已逐流程补详情并标 _detail_ok。
    # 仅对补到详情的流程判"断流"；没详情的不判（避免误报）。拓扑级"未连通"检查
    # （边的 source/target 格式未确认）留 v2，v1 只判"完全无连线"。
    procs = _as_dicts(inp.processes)
    if not procs:
        return [_na("process.no_edges", "processes"), _na("process.disabled", "processes")]
    detailed = [p for p in procs if p.get("_detail_ok")]
    disabled = [
        str(p.get("processName") or p.get("processCode") or "未命名流程")
        for p in procs
        if not _enabled(p.get("status"))
    ]
    disabled_check = _count_check("process.disabled", "processes", "medium", disabled, "流程已停用", "确认是否应启用该流程。")
    if not detailed:
        # 没拿到任何流程详情 → 连线情况未知，断流检查转 N/A
        return [_na("process.no_edges", "processes"), disabled_check]
    no_edges = [
        str(p.get("processName") or p.get("processCode") or "未命名流程")
        for p in detailed
        if len(p.get("nodes") or []) > 1 and not (p.get("edges") or [])
    ]
    return [
        _count_check("process.no_edges", "processes", "high", no_edges, "流程断流（无连线）", "在流程设计器里把节点连成有效流转。"),
        disabled_check,
    ]


def check_models(inp: AppSnapshotInput) -> list[CheckResult]:
    # 注：字段级检查（无字段/缺主键）需逐模型拉字段（with_fields=True 是 O(N²) 风暴），
    # 或平台列接口并不内联字段 —— v1 不做，留 v2。这里只用列里就有的 status。
    models = _as_dicts(inp.models)
    if not models:
        return [_na("model.disabled", "models")]
    disabled = [
        str(m.get("modelName") or m.get("modelCode") or "未命名模型")
        for m in models
        if not _enabled(m.get("status"))
    ]
    return [_count_check("model.disabled", "models", "low", disabled, "模型已停用", "确认停用模型是否仍被引用。")]


def check_menus(inp: AppSnapshotInput) -> list[CheckResult]:
    menus = _as_dicts(inp.menus)
    if not menus:
        return [_na(c, "menus") for c in ("menu.empty_group", "menu.naming", "menu.disabled")]
    empty_group, naming, disabled = [], [], []

    def walk(items):
        for it in _as_dicts(items):
            name = str(it.get("menuName") or "").strip()
            subs = it.get("submenus") or []
            mtype = str(it.get("menuType") or "")
            if not name:
                naming.append(str(it.get("id") or "?"))
            if mtype in ("GROUP", "DIR", "FOLDER") and not subs:
                empty_group.append(name or str(it.get("id")))
            if it.get("isEffective") is False:
                disabled.append(name or str(it.get("id")))
            if subs:
                walk(subs)

    walk(menus)
    return [
        _count_check("menu.empty_group", "menus", "medium", empty_group, "空菜单分组", "删除空分组或为其挂菜单。"),
        _count_check("menu.naming", "menus", "low", naming, "菜单命名缺失", "补全菜单名称。"),
        _count_check("menu.disabled", "menus", "low", disabled, "菜单已停用", "确认停用菜单是否应移除。"),
    ]


def check_roles(inp: AppSnapshotInput) -> list[CheckResult]:
    roles = _as_dicts(inp.roles)
    if not roles:
        return [_na("role.no_users", "roles"), _na("role.disabled", "roles")]
    no_users, disabled = [], []
    for r in roles:
        name = str(r.get("roleName") or r.get("roleCode") or "未命名角色")
        try:
            uc = int(r.get("userCount") or 0)
        except (TypeError, ValueError):
            uc = 0
        if uc == 0:
            no_users.append(name)
        if not _enabled(r.get("status")):
            disabled.append(name)
    return [
        _count_check("role.no_users", "roles", "medium", no_users, "角色无用户", "为角色分配成员或清理无用角色。"),
        _count_check("role.disabled", "roles", "low", disabled, "角色已停用", "确认停用角色是否应删除。"),
    ]


def check_dicts(inp: AppSnapshotInput) -> list[CheckResult]:
    dicts = _as_dicts(inp.dicts)
    if not dicts:
        return [_na("dict.disabled", "dicts")]
    disabled = [
        str(d.get("dictionaryName") or d.get("dictionaryCode"))
        for d in dicts
        if not _enabled(d.get("dictionaryStatus"))
    ]
    return [_count_check("dict.disabled", "dicts", "low", disabled, "字典已停用", "确认停用字典是否仍被下拉引用。")]


def check_events(inp: AppSnapshotInput) -> list[CheckResult]:
    events = _as_dicts(inp.events)
    if not events:
        return [_na("event.disabled", "events")]
    disabled = [str(e.get("eventName") or e.get("eventId")) for e in events if not _enabled(e.get("status"))]
    return [_count_check("event.disabled", "events", "low", disabled, "业务事件已停用", "确认停用事件是否应清理。")]


# ─── 运行层 ──────────────────────────────────────────────────────────


def check_deploy(inp: AppSnapshotInput) -> list[CheckResult]:
    e = inp.app_entry
    if not e:
        return [_na("deploy.unpublished", "deploy"), _na("deploy.no_version", "deploy")]
    published = (str(e.get("statusName") or "") in ACTIVE_STATUS_NAMES) or (
        str(e.get("status") or "") in ACTIVE_STATUS_CODES
    )
    has_ver = bool(str(e.get("currentVersion") or "").strip())
    unpub = (
        _pass("deploy.unpublished", "deploy")
        if published
        else _fail(
            "deploy.unpublished",
            "deploy",
            "high",
            "应用未上线",
            f"当前状态：{e.get('statusName') or e.get('status')}",
            [str(inp.apaas_app_id)],
            "在平台发布应用。",
        )
    )
    nover = (
        _pass("deploy.no_version", "deploy")
        if has_ver
        else _fail(
            "deploy.no_version",
            "deploy",
            "medium",
            "无已发布版本",
            "应用没有 currentVersion。",
            [str(inp.apaas_app_id)],
            "发布一个版本。",
        )
    )
    return [unpub, nover]


def check_activity(inp: AppSnapshotInput) -> list[CheckResult]:
    e = inp.app_entry
    last = _parse_dt(e.get("lastUpdateDate")) if e else None
    if last is None:
        return [_na("activity.stale", "activity")]
    days = (inp.as_of - last).days
    if days > STALE_DAYS:
        return [
            _fail(
                "activity.stale",
                "activity",
                "medium",
                "应用长期未更新",
                f"距上次更新 {days} 天。",
                [str(inp.apaas_app_id)],
                "确认应用是否仍在维护。",
            )
        ]
    return [_pass("activity.stale", "activity")]
