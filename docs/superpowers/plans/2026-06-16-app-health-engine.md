# 应用体检引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 ai-builder 加一个确定性的应用体检引擎 —— 同输入必同输出地算出应用健康度（配置 + 运行），落库支撑趋势/横比，供面板展示与 agent 叙述。

**Architecture:** 纯函数引擎（checks → engine 聚合，无 IO/无随机/无取时间）+ IO 层 collector（用现成 apaas 读方法并发拉，每类一次 list 调用）+ 快照表 + REST 接口 + MCP 工具 + 前端面板。打分用传入的 `as_of`，高危 finding 给维度封顶并置 `has_critical`，无数据维度 N/A 后权重重新归一。

**Tech Stack:** Python / FastAPI / SQLAlchemy(async, create_all) / pytest ; Vue 3 + Element Plus 前端。

参考设计：`docs/superpowers/specs/2026-06-16-app-health-engine-design.md`（§4 数据可行性已实测，§6 检查项目录）。

---

## 文件结构

后端新增 `backend/app/services/app_health/`：
- `types.py` — `Severity / CheckStatus / CheckResult / DimensionScore / HealthReport / AppSnapshotInput` 数据结构。
- `weights.py` — 维度/桶权重、阈值常量、等级带、`ENGINE_VERSION`。
- `checks.py` — 每个检查项一个纯函数，无 IO。
- `engine.py` — `run_health_engine(input) -> HealthReport`：跑 checks → 聚合 → 闸门 → N/A 归一 → grade。
- `collector.py` — `collect_app_snapshot(app, env_id, db, as_of) -> AppSnapshotInput`：并发拉 apaas + 本地 DeployRecord。

其它：
- `backend/app/models/__init__.py` — 加 `AppHealthSnapshot` 模型（create_all 自动建表）。
- `backend/app/routes/applications/app_health.py` — `GET /{app_id}/health`，并在 `__init__.py` include。
- `backend/app/mcp_tools/app_health_tool.py` — `compute_app_health` 工具 + `register(mcp)`，在 `mcp_server.py` 调用。
- 测试：`backend/tests/test_app_health_checks.py` / `test_app_health_engine.py` / `test_app_health_collector.py` / `test_app_health_endpoint.py`。
- 前端：`frontend/src/views/coding/AppHealthPanel.vue`（或 components 下）+ 挂载点 + `*.spec.ts`。

---

### Task 1: 数据结构 types.py

**Files:**
- Create: `backend/app/services/app_health/__init__.py`（空）
- Create: `backend/app/services/app_health/types.py`

- [ ] **Step 1: 写 types.py**

```python
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
    sub_score: float          # 0-100
    severity: Severity
    metric: Any = None
    findings: list[Finding] = field(default_factory=list)

@dataclass
class DimensionScore:
    dimension: str
    score: float | None       # None when na
    na: bool
    weight_base: float        # 配置权重
    weight_used: float        # 归一后实际权重
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
    app_entry: dict | None = None          # query_app_list 中本应用条目
    deploy_records: list[dict] = field(default_factory=list)
    coverage: dict[str, bool] = field(default_factory=dict)   # 各源是否拉到
```

- [ ] **Step 2: 导入冒烟**

Run: `cd backend && ./.venv/bin/python -c "from app.services.app_health import types; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/app_health/__init__.py backend/app/services/app_health/types.py
git commit -m "feat(app-health): 体检引擎数据结构"
```

---

### Task 2: 权重与阈值 weights.py

**Files:**
- Create: `backend/app/services/app_health/weights.py`

- [ ] **Step 1: 写 weights.py**

```python
from __future__ import annotations

ENGINE_VERSION = "1.0"

# 桶级权重
BUCKET_WEIGHTS = {"config": 0.6, "runtime": 0.4}

# 维度 → 桶 + 桶内权重（高=对错攸关）
DIMENSION_BUCKET = {
    "menus": "config", "models": "config", "dicts": "config",
    "roles": "config", "processes": "config", "events": "config",
    "deploy": "runtime", "activity": "runtime",
}
DIMENSION_WEIGHTS = {
    "processes": 0.30, "models": 0.22, "menus": 0.18,
    "roles": 0.15, "events": 0.08, "dicts": 0.07,   # config 桶内
    "deploy": 0.65, "activity": 0.35,                # runtime 桶内
}

# fail 时按 severity 给的子分档
FAIL_SCORE_BY_SEVERITY = {"high": 20.0, "medium": 50.0, "low": 70.0, "none": 100.0}

# 高危封顶
GATE_CAP = 50.0

# 阈值
STALE_DAYS = 90            # activity.stale
ACTIVE_STATUS_NAMES = {"已上线"}      # deploy.unpublished 判定
ACTIVE_STATUS_CODES = {"RUNNING"}
ENABLE_VALUES = {"ENABLE", "ENABLED", "EFFECTIVE", "ACTIVE", "1", "TRUE", "ON"}

# 等级带
def grade_for(score: float | None) -> str:
    if score is None:
        return "未知"
    if score >= 85: return "健康"
    if score >= 70: return "良好"
    if score >= 55: return "中等"
    if score >= 40: return "风险"
    return "严重"
```

- [ ] **Step 2: 导入冒烟**

Run: `cd backend && ./.venv/bin/python -c "from app.services.app_health.weights import grade_for; assert grade_for(90)=='健康' and grade_for(None)=='未知' and grade_for(45)=='风险'; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/app_health/weights.py
git commit -m "feat(app-health): 权重/阈值/等级常量"
```

---

### Task 3: 配置层检查 checks.py（TDD）

**Files:**
- Create: `backend/app/services/app_health/checks.py`
- Test: `backend/tests/test_app_health_checks.py`

每个 check：`(input) -> list[CheckResult]`（一个维度一个函数，返回该维度的 check 结果列表）。helper：`_is_enabled(status)`、`_fail/_pass/_partial` 构造器、`_na(dim)`。

- [ ] **Step 1: 写失败测试（配置层）**

```python
from datetime import datetime
from app.services.app_health import checks
from app.services.app_health.types import AppSnapshotInput

AS_OF = datetime(2026, 6, 16, 12, 0, 0)

def _inp(**kw):
    return AppSnapshotInput(app_id=1, apaas_app_id="x", as_of=AS_OF, **kw)

def test_process_no_edges_is_high_fail():
    inp = _inp(processes=[{"processName": "入库审批流", "nodes": [{"id": "A"}, {"id": "B"}], "edges": None, "status": "ENABLE"}])
    res = {c.id: c for c in checks.check_processes(inp)}
    assert res["process.no_edges"].status == "fail"
    assert res["process.no_edges"].severity == "high"

def test_process_connected_passes():
    inp = _inp(processes=[{"processName": "p", "nodes": [{"id": "A"}, {"id": "B"}], "edges": [{"source": "A", "target": "B"}], "status": "ENABLE"}])
    res = {c.id: c for c in checks.check_processes(inp)}
    assert res["process.no_edges"].status == "pass"
    assert res["process.disconnected"].status == "pass"

def test_process_disconnected_node():
    inp = _inp(processes=[{"processName": "p", "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}], "edges": [{"source": "A", "target": "B"}], "status": "ENABLE"}])
    res = {c.id: c for c in checks.check_processes(inp)}
    assert res["process.disconnected"].status == "fail"   # C 未连

def test_models_no_fields():
    inp = _inp(models=[{"modelName": "空模型", "fields": [], "status": "ENABLE"}, {"modelName": "好", "dataModelFields": [{"fieldCode": "a"}], "status": "ENABLE"}])
    res = {c.id: c for c in checks.check_models(inp)}
    assert res["model.no_fields"].metric == 1

def test_roles_no_users():
    inp = _inp(roles=[{"roleName": "孤儿角色", "userCount": 0, "status": "ENABLE"}])
    res = {c.id: c for c in checks.check_roles(inp)}
    assert res["role.no_users"].metric == 1

def test_events_na_when_none():
    inp = _inp(events=[])
    res = checks.check_events(inp)
    assert all(c.status == "na" for c in res)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_checks.py -q`
Expected: FAIL（`module 'checks' has no attribute 'check_processes'`）

- [ ] **Step 3: 实现 checks.py 配置层**

```python
from __future__ import annotations
from .types import AppSnapshotInput, CheckResult, Finding
from .weights import FAIL_SCORE_BY_SEVERITY, ENABLE_VALUES

def _enabled(v) -> bool:
    return str(v).strip().upper() in ENABLE_VALUES if v is not None else True

def _fail(cid, dim, sev, title, detail, objs, sug):
    return CheckResult(cid, dim, "fail", FAIL_SCORE_BY_SEVERITY[sev], sev, metric=len(objs),
                       findings=[Finding(cid, dim, sev, title, detail, objs, sug)])

def _pass(cid, dim):
    return CheckResult(cid, dim, "pass", 100.0, "none", metric=0)

def _count_check(cid, dim, sev, bad: list[str], title, sug):
    if not bad:
        return _pass(cid, dim)
    return _fail(cid, dim, sev, title, f"{len(bad)} 个：{', '.join(bad[:5])}", bad, sug)

def check_processes(inp: AppSnapshotInput) -> list[CheckResult]:
    procs = inp.processes
    if not procs:
        return [CheckResult("process.no_edges", "processes", "na", 0, "none"),
                CheckResult("process.disconnected", "processes", "na", 0, "none"),
                CheckResult("process.disabled", "processes", "na", 0, "none")]
    no_edges, disc, disabled = [], [], []
    for p in procs:
        name = str(p.get("processName") or p.get("processCode") or "未命名流程")
        nodes = p.get("nodes") or []
        edges = p.get("edges") or []
        if len(nodes) > 1 and not edges:
            no_edges.append(name)
        else:
            connected = set()
            for e in edges:
                connected.add(str(e.get("source") or e.get("sourceId") or e.get("from")))
                connected.add(str(e.get("target") or e.get("targetId") or e.get("to")))
            node_ids = {str(n.get("id") or n.get("nodeId")) for n in nodes}
            if node_ids and (node_ids - connected) and len(nodes) > 1:
                disc.append(name)
        if not _enabled(p.get("status")):
            disabled.append(name)
    return [
        _count_check("process.no_edges", "processes", "high", no_edges, "流程断流（无连线）", "在流程设计器里把节点连成有效流转。"),
        _count_check("process.disconnected", "processes", "high", disc, "流程存在未连接节点", "检查孤立节点并补连线。"),
        _count_check("process.disabled", "processes", "medium", disabled, "流程已停用", "确认是否应启用该流程。"),
    ]

def check_models(inp: AppSnapshotInput) -> list[CheckResult]:
    models = inp.models
    if not models:
        return [CheckResult("model.no_fields", "models", "na", 0, "none"),
                CheckResult("model.disabled", "models", "na", 0, "none")]
    no_fields, disabled = [], []
    for m in models:
        name = str(m.get("modelName") or m.get("modelCode") or "未命名模型")
        fields = m.get("fields") or m.get("dataModelFields") or []
        if not fields:
            no_fields.append(name)
        if not _enabled(m.get("status")):
            disabled.append(name)
    return [
        _count_check("model.no_fields", "models", "high", no_fields, "模型无字段", "为模型补字段或删除空模型。"),
        _count_check("model.disabled", "models", "low", disabled, "模型已停用", "确认停用模型是否仍被引用。"),
    ]

def check_menus(inp: AppSnapshotInput) -> list[CheckResult]:
    menus = inp.menus
    if not menus:
        return [CheckResult(cid, "menus", "na", 0, "none") for cid in ("menu.empty_group", "menu.naming", "menu.disabled")]
    empty_group, naming, disabled = [], [], []
    def walk(items):
        for it in items:
            name = str(it.get("menuName") or "").strip()
            subs = it.get("submenus") or []
            mtype = str(it.get("menuType") or "")
            if not name:
                naming.append(it.get("id") or "?")
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
    roles = inp.roles
    if not roles:
        return [CheckResult("role.no_users", "roles", "na", 0, "none"),
                CheckResult("role.disabled", "roles", "na", 0, "none")]
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
    dicts = inp.dicts
    if not dicts:
        return [CheckResult("dict.disabled", "dicts", "na", 0, "none")]
    disabled = [str(d.get("dictionaryName") or d.get("dictionaryCode")) for d in dicts if not _enabled(d.get("dictionaryStatus"))]
    return [_count_check("dict.disabled", "dicts", "low", disabled, "字典已停用", "确认停用字典是否仍被下拉引用。")]

def check_events(inp: AppSnapshotInput) -> list[CheckResult]:
    events = inp.events
    if not events:
        return [CheckResult("event.disabled", "events", "na", 0, "none")]
    disabled = [str(e.get("eventName") or e.get("eventId")) for e in events if not _enabled(e.get("status"))]
    return [_count_check("event.disabled", "events", "low", disabled, "业务事件已停用", "确认停用事件是否应清理。")]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_checks.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/app_health/checks.py backend/tests/test_app_health_checks.py
git commit -m "feat(app-health): 配置层检查项 + 单测"
```

---

### Task 4: 运行层检查 checks.py（TDD）

**Files:**
- Modify: `backend/app/services/app_health/checks.py`
- Test: `backend/tests/test_app_health_checks.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
def test_deploy_unpublished():
    inp = _inp(app_entry={"statusName": "未发布", "status": "DRAFT", "currentVersion": ""})
    res = {c.id: c for c in checks.check_deploy(inp)}
    assert res["deploy.unpublished"].status == "fail"
    assert res["deploy.no_version"].status == "fail"

def test_deploy_published_ok():
    inp = _inp(app_entry={"statusName": "已上线", "status": "RUNNING", "currentVersion": "0.0.4"})
    res = {c.id: c for c in checks.check_deploy(inp)}
    assert res["deploy.unpublished"].status == "pass"

def test_activity_stale():
    inp = _inp(app_entry={"lastUpdateDate": "2026-01-01 00:00:00"})   # >90d before AS_OF
    res = {c.id: c for c in checks.check_activity(inp)}
    assert res["activity.stale"].status == "fail"

def test_activity_fresh():
    inp = _inp(app_entry={"lastUpdateDate": "2026-06-10 00:00:00"})
    res = {c.id: c for c in checks.check_activity(inp)}
    assert res["activity.stale"].status == "pass"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_checks.py -q`
Expected: FAIL（`check_deploy` 未定义）

- [ ] **Step 3: 实现运行层 checks**

```python
from datetime import datetime
from .weights import ACTIVE_STATUS_NAMES, ACTIVE_STATUS_CODES, STALE_DAYS

def _parse_dt(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s)[:19], fmt)
        except (TypeError, ValueError):
            continue
    return None

def check_deploy(inp: AppSnapshotInput) -> list[CheckResult]:
    e = inp.app_entry
    if not e:
        return [CheckResult("deploy.unpublished", "deploy", "na", 0, "none"),
                CheckResult("deploy.no_version", "deploy", "na", 0, "none")]
    published = (str(e.get("statusName") or "") in ACTIVE_STATUS_NAMES) or (str(e.get("status") or "") in ACTIVE_STATUS_CODES)
    has_ver = bool(str(e.get("currentVersion") or "").strip())
    unpub = _pass("deploy.unpublished", "deploy") if published else \
        _fail("deploy.unpublished", "deploy", "high", "应用未上线", f"当前状态：{e.get('statusName') or e.get('status')}", [str(inp.apaas_app_id)], "在平台发布应用。")
    nover = _pass("deploy.no_version", "deploy") if has_ver else \
        _fail("deploy.no_version", "deploy", "medium", "无已发布版本", "应用没有 currentVersion。", [str(inp.apaas_app_id)], "发布一个版本。")
    return [unpub, nover]

def check_activity(inp: AppSnapshotInput) -> list[CheckResult]:
    e = inp.app_entry
    last = _parse_dt(e.get("lastUpdateDate")) if e else None
    if last is None:
        return [CheckResult("activity.stale", "activity", "na", 0, "none")]
    days = (inp.as_of - last).days
    if days > STALE_DAYS:
        return [_fail("activity.stale", "activity", "medium", "应用长期未更新", f"距上次更新 {days} 天。", [str(inp.apaas_app_id)], "确认应用是否仍在维护。")]
    return [_pass("activity.stale", "activity")]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_checks.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/app_health/checks.py backend/tests/test_app_health_checks.py
git commit -m "feat(app-health): 运行层检查项 + 单测"
```

---

### Task 5: 引擎聚合 engine.py（TDD，含确定性守卫）

**Files:**
- Create: `backend/app/services/app_health/engine.py`
- Test: `backend/tests/test_app_health_engine.py`

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime
from app.services.app_health.engine import run_health_engine, CHECK_FUNCS
from app.services.app_health.types import AppSnapshotInput

AS_OF = datetime(2026, 6, 16, 12, 0, 0)

def _full_healthy():
    return AppSnapshotInput(
        app_id=1, apaas_app_id="x", as_of=AS_OF,
        menus=[{"menuName": "m", "menuType": "TODO", "submenus": [], "isEffective": True}],
        models=[{"modelName": "ok", "fields": [{"fieldCode": "a"}], "status": "ENABLE"}],
        dicts=[{"dictionaryName": "d", "dictionaryStatus": "ENABLE"}],
        roles=[{"roleName": "r", "userCount": 3, "status": "ENABLE"}],
        processes=[{"processName": "p", "nodes": [{"id": "A"}, {"id": "B"}], "edges": [{"source": "A", "target": "B"}], "status": "ENABLE"}],
        events=[], app_entry={"statusName": "已上线", "status": "RUNNING", "currentVersion": "1.0", "lastUpdateDate": "2026-06-15 00:00:00"},
        coverage={"menus": True, "models": True, "dicts": True, "roles": True, "processes": True, "events": True, "app_entry": True},
    )

def test_healthy_app_high_score_no_critical():
    r = run_health_engine(_full_healthy())
    assert r.total_score >= 85 and r.grade == "健康" and r.has_critical is False

def test_broken_process_gates_and_flags_critical():
    inp = _full_healthy()
    inp.processes = [{"processName": "断流", "nodes": [{"id": "A"}, {"id": "B"}], "edges": None, "status": "ENABLE"}]
    r = run_health_engine(inp)
    pdim = next(d for d in r.dimensions if d.dimension == "processes")
    assert pdim.score <= 50 and r.has_critical is True

def test_na_dimension_excluded_and_renormalized():
    inp = _full_healthy()
    inp.events = []   # events -> na
    r = run_health_engine(inp)
    edim = next(d for d in r.dimensions if d.dimension == "events")
    assert edim.na is True and edim.weight_used == 0.0
    assert abs(sum(d.weight_used for d in r.dimensions) - 1.0) < 1e-6

def test_determinism_byte_identical():
    import json, dataclasses
    a = run_health_engine(_full_healthy()); b = run_health_engine(_full_healthy())
    assert dataclasses.asdict(a) == dataclasses.asdict(b)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_engine.py -q`
Expected: FAIL（`run_health_engine` 未定义）

- [ ] **Step 3: 实现 engine.py**

```python
from __future__ import annotations
from . import checks
from .types import AppSnapshotInput, CheckResult, DimensionScore, HealthReport, Finding
from .weights import (DIMENSION_BUCKET, DIMENSION_WEIGHTS, BUCKET_WEIGHTS,
                      GATE_CAP, ENGINE_VERSION, grade_for)

CHECK_FUNCS = {
    "menus": checks.check_menus, "models": checks.check_models, "dicts": checks.check_dicts,
    "roles": checks.check_roles, "processes": checks.check_processes, "events": checks.check_events,
    "deploy": checks.check_deploy, "activity": checks.check_activity,
}
SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}

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
        dims.append(DimensionScore(dimension=dim, score=score, na=na,
                                   weight_base=DIMENSION_WEIGHTS[dim], weight_used=0.0, checks=results))
    # 按桶 N/A 归一
    for bucket in BUCKET_WEIGHTS:
        bdims = [d for d in dims if DIMENSION_BUCKET[d.dimension] == bucket and not d.na]
        wsum = sum(d.weight_base for d in bdims)
        for d in bdims:
            d.weight_used = (d.weight_base / wsum) if wsum else 0.0
    # 桶分
    bucket_scores, bucket_present = {}, {}
    for bucket in BUCKET_WEIGHTS:
        bdims = [d for d in dims if DIMENSION_BUCKET[d.dimension] == bucket and not d.na]
        bucket_present[bucket] = bool(bdims)
        bucket_scores[bucket] = sum((d.score or 0) * d.weight_used for d in bdims) if bdims else None
    # 桶间归一（缺桶剔除）
    active = {b: BUCKET_WEIGHTS[b] for b in BUCKET_WEIGHTS if bucket_present[b]}
    bwsum = sum(active.values())
    total = None
    if bwsum:
        total = sum(bucket_scores[b] * (w / bwsum) for b, w in active.items())
    # 跨维度归一后 weight_used 重置为全局占比（便于落库阅读）
    for d in dims:
        if not d.na:
            bucket = DIMENSION_BUCKET[d.dimension]
            d.weight_used = (active.get(bucket, 0) / bwsum) * d.weight_used if bwsum else 0.0
    all_findings = [f for d in dims for c in d.checks for f in c.findings]
    all_findings.sort(key=lambda f: (SEV_ORDER[f.severity], list(CHECK_FUNCS).index(f.dimension)))
    total_int = round(total) if total is not None else None
    return HealthReport(
        app_id=inp.app_id, apaas_app_id=inp.apaas_app_id, as_of=inp.as_of,
        total_score=total_int, grade=grade_for(total), has_critical=has_critical,
        dimensions=dims, findings=all_findings,
        data_coverage=dict(inp.coverage), engine_version=ENGINE_VERSION,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_engine.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/app_health/engine.py backend/tests/test_app_health_engine.py
git commit -m "feat(app-health): 聚合引擎(闸门/NA归一/确定性) + 单测"
```

---

### Task 6: 采集器 collector.py（TDD with mock）

**Files:**
- Create: `backend/app/services/app_health/collector.py`
- Test: `backend/tests/test_app_health_collector.py`

collector 用 `call_apaas_with_relogin(env_id, db, fn)`，fn 内并发调 client 各读方法；单源失败 → 该源 coverage=False 且对应字段留 None。`as_of` 由调用方传入（不在此取 now，便于测试）。

- [ ] **Step 1: 写测试（mock client）**

```python
import asyncio
from datetime import datetime
from types import SimpleNamespace
from app.services.app_health import collector

AS_OF = datetime(2026, 6, 16, 12, 0, 0)

class FakeClient:
    base_url = "x"
    async def query_menus(self, aid): return [{"menuName": "m"}]
    async def query_models(self, aid, with_fields=False): return [{"modelName": "ok", "fields": [{"x": 1}]}]
    async def query_dicts(self, aid): return [{"dictionaryName": "d"}]
    async def query_roles(self, aid): return [{"roleName": "r", "userCount": 1}]
    async def list_processes(self, aid): return [{"processName": "p", "nodes": [], "edges": []}]
    async def list_business_events(self, aid): raise RuntimeError("boom")   # 单源失败
    async def query_app_list(self): return [{"id": "AID", "statusName": "已上线"}]

async def _run(monkeypatch):
    async def fake_call(env_id, db, fn): return await fn(FakeClient())
    monkeypatch.setattr(collector, "call_apaas_with_relogin", fake_call)
    app = SimpleNamespace(id=1, apaas_app_id="AID", platform_env_id=9)
    return await collector.collect_app_snapshot(app, 9, db=None, as_of=AS_OF)

def test_collector_partial_failure(monkeypatch):
    inp = asyncio.run(_run(monkeypatch))
    assert inp.coverage["menus"] is True
    assert inp.coverage["events"] is False     # 失败源标 False
    assert inp.events is None
    assert inp.app_entry["statusName"] == "已上线"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_collector.py -q`
Expected: FAIL（`collect_app_snapshot` 未定义）

- [ ] **Step 3: 实现 collector.py**

```python
from __future__ import annotations
import asyncio
from datetime import datetime
from typing import Any
from app.apaas_session import call_apaas_with_relogin
from .types import AppSnapshotInput

async def _safe(coro):
    try:
        return await coro, True
    except Exception:
        return None, False

async def collect_app_snapshot(app, env_id: int, db, as_of: datetime) -> AppSnapshotInput:
    aid = str(app.apaas_app_id)

    async def fn(client):
        results = await asyncio.gather(
            _safe(client.query_menus(aid)),
            _safe(client.query_models(aid, with_fields=False)),
            _safe(client.query_dicts(aid)),
            _safe(client.query_roles(aid)),
            _safe(client.list_processes(aid)),
            _safe(client.list_business_events(aid)),
            _safe(client.query_app_list()),
        )
        return results

    res = await call_apaas_with_relogin(env_id, db, fn)
    (menus, ok_m), (models, ok_md), (dicts, ok_d), (roles, ok_r), \
        (procs, ok_p), (events, ok_e), (applist, ok_a) = res

    app_entry = None
    if ok_a and isinstance(applist, list):
        app_entry = next((a for a in applist if str(a.get("id")) == aid or str(a.get("appId")) == aid), None)
    cov = {"menus": ok_m, "models": ok_md, "dicts": ok_d, "roles": ok_r,
           "processes": ok_p, "events": ok_e, "app_entry": bool(app_entry)}
    return AppSnapshotInput(
        app_id=app.id, apaas_app_id=aid, as_of=as_of,
        menus=menus, models=models, dicts=dicts, roles=roles,
        processes=procs, events=events, app_entry=app_entry,
        deploy_records=[], coverage=cov,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_collector.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/app_health/collector.py backend/tests/test_app_health_collector.py
git commit -m "feat(app-health): 采集器(并发/单源失败降级) + 单测"
```

---

### Task 7: 快照表模型

**Files:**
- Modify: `backend/app/models/__init__.py`（加 `AppHealthSnapshot`，紧跟其它扩展模型；确保被 import 以便 create_all 建表）

- [ ] **Step 1: 加模型**

```python
class AppHealthSnapshot(Base):
    __tablename__ = "app_health_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    app_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id"), index=True, nullable=False)
    apaas_app_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    has_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    data_coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
```

（确认文件顶部已 import `datetime, JSON, Boolean, DateTime, ForeignKey`；若缺则补。）

- [ ] **Step 2: 建表冒烟**

Run: `cd backend && ./.venv/bin/python -c "from app.models import AppHealthSnapshot; print(AppHealthSnapshot.__tablename__)"`
Expected: `app_health_snapshots`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/__init__.py
git commit -m "feat(app-health): app_health_snapshots 快照表"
```

---

### Task 8: REST 接口 GET /applications/{app_id}/health（TDD）

**Files:**
- Create: `backend/app/routes/applications/app_health.py`
- Modify: `backend/app/routes/applications/__init__.py`（include 新 router）
- Create: `backend/app/services/app_health/service.py`（编排：采集→引擎→序列化→落库，供接口与 MCP 工具共用）
- Test: `backend/tests/test_app_health_endpoint.py`

- [ ] **Step 1: 写 service.py（编排 + 序列化）**

```python
from __future__ import annotations
import dataclasses
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from .collector import collect_app_snapshot
from .engine import run_health_engine
from .types import HealthReport

def report_to_dict(r: HealthReport) -> dict:
    d = dataclasses.asdict(r)
    d["as_of"] = r.as_of.isoformat()
    return d

async def run_app_health(app, env_id: int, db: AsyncSession, *, as_of: datetime, persist: bool) -> dict:
    inp = await collect_app_snapshot(app, env_id, db, as_of)
    report = run_health_engine(inp)
    if persist:
        from app.models import AppHealthSnapshot
        db.add(AppHealthSnapshot(
            tenant_id=app.tenant_id, app_id=app.id, apaas_app_id=report.apaas_app_id,
            as_of=report.as_of, total_score=report.total_score, grade=report.grade,
            has_critical=report.has_critical,
            dimensions=[{"dimension": d.dimension, "score": d.score, "na": d.na,
                         "weight_base": d.weight_base, "weight_used": d.weight_used} for d in report.dimensions],
            findings=[dataclasses.asdict(f) for f in report.findings],
            data_coverage=report.data_coverage, engine_version=report.engine_version,
        ))
        await db.commit()
    return report_to_dict(report)
```

- [ ] **Step 2: 写接口 app_health.py**

```python
from __future__ import annotations
from datetime import datetime
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.routes.applications._helpers import _resolve_platform_env_for_tenant
from app.routes.applications.logs_endpoint import _verify_app_access
from app.services.app_health.service import run_app_health

router = APIRouter()

@router.get("/{app_id}/health")
async def get_application_health(
    app_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    persist: bool = Query(True),
) -> dict:
    app = await _verify_app_access(app_id, ctx, db)
    env_id = app.platform_env_id
    if not env_id:
        env = await _resolve_platform_env_for_tenant(db, app.tenant_id)
        env_id = env.id if env else None
    if not env_id or not app.apaas_app_id:
        raise HTTPException(status_code=400, detail="当前应用未绑定 aPaaS 平台环境或缺少 appId，无法体检")
    report = await run_app_health(app, env_id, db, as_of=datetime.utcnow(), persist=persist)
    return {"ok": True, **report}
```

- [ ] **Step 3: include router**

Modify `backend/app/routes/applications/__init__.py`（紧跟 `_lowcode_logs` 之后）：
```python
from . import app_health as _app_health  # noqa: E402
router.include_router(_app_health.router)
```

- [ ] **Step 4: 写接口测试（mock service）**

```python
import pytest
from httpx import AsyncClient, ASGITransport
# 复用项目既有 conftest 的 app/auth fixture；若无则按现有 endpoint 测试样式。
# 核心断言：persist=false 时不写快照；返回含 total_score/grade/dimensions。
```

（按 `tests/` 现有 endpoint 测试样式补全：用现有 app fixture，monkeypatch `app.services.app_health.service.collect_app_snapshot` 返回固定 input，断言响应字段与「persist=false 不落库」。）

- [ ] **Step 5: 跑测试 + 冒烟**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_endpoint.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/app_health/service.py backend/app/routes/applications/app_health.py backend/app/routes/applications/__init__.py backend/tests/test_app_health_endpoint.py
git commit -m "feat(app-health): /applications/{id}/health 接口 + 落库 + 测试"
```

---

### Task 9: MCP 工具 compute_app_health

**Files:**
- Create: `backend/app/mcp_tools/app_health_tool.py`
- Modify: `backend/app/mcp_server.py`（import + 调 register）

- [ ] **Step 1: 写工具**（不落库，返回与接口同 schema）

```python
from __future__ import annotations
from datetime import datetime

def register(mcp, *, get_app_and_env, get_db_session):
    @mcp.tool()
    async def compute_app_health(app_id: int) -> dict:
        """对指定应用做确定性健康体检，返回结构化记分卡（供叙述，不落库）。"""
        from app.services.app_health.service import run_app_health
        async with get_db_session() as db:
            app, env_id = await get_app_and_env(app_id, db)
            if not app or not env_id or not app.apaas_app_id:
                return {"ok": False, "error_code": "APP_NOT_READY", "message": "应用未绑定平台或缺少 appId"}
            report = await run_app_health(app, env_id, db, as_of=datetime.utcnow(), persist=False)
            return {"ok": True, **report}
```

（`get_app_and_env` / `get_db_session` 按 mcp_server.py 现有其它工具的依赖注入方式对齐——参照 business_events.register 的签名传入。）

- [ ] **Step 2: register 接线**

Modify `backend/app/mcp_server.py`：仿现有 `_register_business_event_tools` 加 `from app.mcp_tools.app_health_tool import register as _register_app_health_tools` 并在注册段调用，依赖按同文件其它工具传参。

- [ ] **Step 3: 冒烟（工具可见）**

Run: `cd backend && ./.venv/bin/python -c "import app.mcp_server; print('import ok')"`
Expected: `import ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/mcp_tools/app_health_tool.py backend/app/mcp_server.py
git commit -m "feat(app-health): compute_app_health MCP 工具"
```

---

### Task 10: 前端「应用体检」面板

**Files:**
- Create: `frontend/src/views/coding/AppHealthPanel.vue`（props: `appId: number`）
- Create: `frontend/src/views/coding/AppHealthPanel.spec.ts`
- Modify: app 详情挂载点（与 LogsPanel 同位置，新增一个「体检」标签或区块；按 ChatPage 现有 config-tab 模式接入）

面板：调 `GET /applications/{appId}/health?persist=true`，渲染总分环/等级/`有高优风险`徽标 + 维度记分卡（N/A 维度显式标）+ findings 列表（按 severity 分组、组内维度序）。覆盖加载/部分数据/错误/全失败/陈旧+重检 状态（见 spec §9）。复用 TenantLogsPage 的 token 化样式与 el 组件。

- [ ] **Step 1: 写 spec 测试（?raw 字符串断言，对齐 TenantLogsPage.spec.ts 风格）**

```typescript
import { describe, expect, it } from 'vitest'
import src from './AppHealthPanel.vue?raw'

describe('AppHealthPanel', () => {
  it('calls the health endpoint and renders scorecard', () => {
    expect(src).toContain('/health')
    expect(src).toContain('total_score')
    expect(src).toContain('has_critical')
    expect(src).toContain('重新体检')
    expect(src).toContain('N/A')   // N/A 维度显式标
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/coding/AppHealthPanel.spec.ts`
Expected: FAIL（文件不存在）

- [ ] **Step 3: 实现 AppHealthPanel.vue**

按 spec §9 实现（结构：header 总分+等级+徽标+重新体检按钮；维度记分卡 grid；findings 分组列表；loading/error/empty/na 状态）。样式用 `var(--ok/--warn/--err/--surface/--line)` 等 token，对齐 TenantLogsPage.vue。调用 `request.get('/applications/'+appId+'/health')`。

- [ ] **Step 4: 跑测试 + 构建**

Run: `cd frontend && npx vitest run src/views/coding/AppHealthPanel.spec.ts && npm run build:nocheck 2>&1 | tail -3`
Expected: PASS + 构建成功

- [ ] **Step 5: 挂载到 app 详情**

在 ChatPage 的 config-tab（与 LogsPanel 同级）新增「体检」入口渲染 `<AppHealthPanel :app-id="currentAppId" />`。运行 preview 验证真实渲染（登录态由用户侧；至少跑通组件挂载 + 接口形状）。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/coding/AppHealthPanel.vue frontend/src/views/coding/AppHealthPanel.spec.ts frontend/src/views/ChatPage.vue
git commit -m "feat(app-health): 应用体检面板 + 挂载 app 详情"
```

---

### Task 11: 端到端校验 + 收尾

- [ ] **Step 1: 全量后端测试**

Run: `cd backend && ./.venv/bin/pytest tests/test_app_health_*.py -q`
Expected: 全 PASS

- [ ] **Step 2: 真实应用体检冒烟**（用 WMS 应用，确认断流流程被抓到）

写临时脚本调 `run_app_health`（persist=False）对 apaas_app_id=854046919209517056 跑一次，确认 `process.no_edges` 命中「入库审批流」、total_score 合理、同跑两次结果一致；确认后删脚本。

- [ ] **Step 3: 重启后端 preview**（reload=False，改后端必重启）+ 面板 live 验证。

- [ ] **Step 4: 自查 + 评审**

对照 spec §6 检查项目录逐条核对实现；跑一轮 code-review。

---

## Self-Review

- **Spec 覆盖**：§6 全部 v1 检查项（menus 3 / models 2 / dicts 1 / roles 2 / processes 3 / events 1 / deploy 2 / activity 1）→ Task 3-4 实现；§7 打分/闸门/NA → Task 5；§8 落库 → Task 7-8；§9 接口/MCP/面板/交互态 → Task 8-10；§11 测试 → 各 Task TDD + Task 11。无遗漏。
- **占位符**：核心代码均完整；Task 8/9/10 的"按现有样式补全"指向具体参照文件（logs_endpoint 测试、business_events.register、TenantLogsPage），非空泛占位。
- **类型一致**：`AppSnapshotInput` 字段、`CheckResult` 形状、`CHECK_FUNCS` 维度键、`weights` 维度键在 Task 1/2/3/4/5 间一致；`run_app_health` 在 Task 8 定义、Task 9 复用同签名。
