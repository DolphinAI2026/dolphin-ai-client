# aPaaS 原生多产物分解 + 单页预览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 多端/多页 coding 请求分解成 N≤4 个 aPaaS 单扩展产物(管理端 form-list + 用户端 mobile-page),挂一个 Project 分组、各自可预览;不适用时回落现有单产物 + G4 诚实声明。

**Architecture:** 编排器在 `run_coding_pipeline` 之上:① 多端强信号门(复用 delivery_honesty) ② LLM 分解出计划 ③ 对每个产物把聚焦 sub_request 当一次**普通首轮** `run_coding_pipeline(project_id=P)`,各自建工作区/检测 scene,打标透传 ④ 汇总。G3 给单页模板补真 mount preview harness。

**Tech Stack:** Python 3.13, FastAPI, async generators, pytest(asyncio_mode=auto), 现有 LLMClient / WorkspaceManager / run_coding_pipeline。

## Global Constraints

- 永不更糟:分解失败/不适用一律回落 `run_coding_pipeline` 单产物路径。
- 只在**首轮(非 iteration)+ 多端强信号**触发;iteration 永不分解。
- 复用现有生成原语 `run_coding_pipeline`,不重写 agent loop / autofix / 持久化。
- 不改 G4 / autofix / done 结构。新代码异常一律降级,不中断。
- 测试:新函数必有先失败的测试;LLM/子流水线在单测里 mock。
- 后端根:`/Users/mars/Vibe Coding/ai-builder/backend`,venv = `.venv/bin/python`。

---

### Task 1: 分解计划解析(纯函数)

**Files:**
- Create: `backend/app/coding/decompose.py`
- Test: `backend/tests/test_decompose_parse.py`

**Interfaces:**
- Produces: `Artifact = TypedDict{name:str, side:str, scene:str, sub_request:str}`;`parse_decomposition(raw_json: str, available_scenes: set[str], max_artifacts: int = 4) -> list[Artifact] | None`(N≤1 或全非法 → None)。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_decompose_parse.py
from app.coding.decompose import parse_decomposition

SCENES = {"form-list", "menu-page", "mobile-page", "form-page"}

def test_parses_valid_two_artifact_plan():
    raw = '{"artifacts":[{"name":"职位管理","side":"admin","scene":"form-list","sub_request":"做一个职位管理列表页"},{"name":"求职端","side":"user","scene":"mobile-page","sub_request":"做求职者移动端"}]}'
    plan = parse_decomposition(raw, SCENES)
    assert plan is not None and len(plan) == 2
    assert plan[0]["scene"] == "form-list" and plan[1]["side"] == "user"

def test_none_when_single_artifact():
    raw = '{"artifacts":[{"name":"x","side":"admin","scene":"form-list","sub_request":"做个列表"}]}'
    assert parse_decomposition(raw, SCENES) is None  # 1 个不值得分解

def test_drops_illegal_scene_keeps_valid():
    raw = '{"artifacts":[{"name":"a","side":"admin","scene":"WAT","sub_request":"x"},{"name":"b","side":"admin","scene":"form-list","sub_request":"y"},{"name":"c","side":"user","scene":"mobile-page","sub_request":"z"}]}'
    plan = parse_decomposition(raw, SCENES)
    assert plan is not None and len(plan) == 2 and all(a["scene"] in SCENES for a in plan)

def test_caps_at_max():
    arts = ",".join('{"name":"n%d","side":"admin","scene":"form-list","sub_request":"r"}' % i for i in range(8))
    plan = parse_decomposition('{"artifacts":[%s]}' % arts, SCENES, max_artifacts=4)
    assert plan is not None and len(plan) == 4

def test_none_on_garbage():
    assert parse_decomposition("not json", SCENES) is None
    assert parse_decomposition('{"artifacts":[]}', SCENES) is None
    assert parse_decomposition('{"artifacts":[{"scene":"form-list"}]}', SCENES) is None  # 缺 sub_request
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_decompose_parse.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.coding.decompose'`

- [ ] **Step 3: 写最小实现**

```python
# backend/app/coding/decompose.py
"""多端请求分解为 N 个 aPaaS 单扩展产物的计划解析 + LLM 调用。"""
from __future__ import annotations
import json
from typing import Optional, TypedDict


class Artifact(TypedDict):
    name: str
    side: str          # "admin" | "user"
    scene: str         # 单产物 scene 值
    sub_request: str   # 聚焦自然语言, 喂给一次首轮 run_coding_pipeline


def parse_decomposition(
    raw_json: str, available_scenes: set[str], max_artifacts: int = 4
) -> Optional[list[Artifact]]:
    """解析/校验 LLM 分解输出。非法/不值得分解(<2 有效项) → None。"""
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    raw_arts = data.get("artifacts") if isinstance(data, dict) else None
    if not isinstance(raw_arts, list):
        return None
    out: list[Artifact] = []
    for a in raw_arts:
        if not isinstance(a, dict):
            continue
        scene = str(a.get("scene") or "").strip()
        sub = str(a.get("sub_request") or "").strip()
        if scene not in available_scenes or not sub:
            continue
        out.append(Artifact(
            name=str(a.get("name") or sub[:20]).strip(),
            side=str(a.get("side") or "admin").strip(),
            scene=scene, sub_request=sub,
        ))
        if len(out) >= max_artifacts:
            break
    return out if len(out) >= 2 else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_decompose_parse.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/decompose.py backend/tests/test_decompose_parse.py
git commit -m "feat(coding): 多产物分解计划解析纯函数(parse_decomposition)"
```

---

### Task 2: 分解 LLM 调用 + 回落

**Files:**
- Modify: `backend/app/coding/decompose.py`
- Test: `backend/tests/test_decompose_llm.py`

**Interfaces:**
- Consumes: `parse_decomposition`(Task 1)。
- Produces: `_call_decompose_llm(prompt: str, llm_cfg: dict) -> str`(可 monkeypatch);`async decompose(requirement: str, llm_cfg: dict, available_scenes: set[str]) -> list[Artifact] | None`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_decompose_llm.py
import app.coding.decompose as dc
from app.coding.decompose import decompose

SCENES = {"form-list", "menu-page", "mobile-page", "form-page"}
CFG = {"api_key": "k", "base_url": "u", "model": "m"}

async def test_returns_plan_from_llm(monkeypatch):
    monkeypatch.setattr(dc, "_call_decompose_llm", lambda p, c: (
        '{"artifacts":[{"name":"职位管理","side":"admin","scene":"form-list","sub_request":"做职位管理列表页"},'
        '{"name":"求职端","side":"user","scene":"mobile-page","sub_request":"做求职移动端"}]}'))
    plan = await decompose("招聘系统 管理端+用户端两端", CFG, SCENES)
    assert plan is not None and len(plan) == 2

async def test_falls_back_to_none_on_llm_error(monkeypatch):
    def boom(p, c): raise RuntimeError("llm down")
    monkeypatch.setattr(dc, "_call_decompose_llm", boom)
    assert await decompose("招聘系统两端", CFG, SCENES) is None

async def test_none_when_llm_returns_single(monkeypatch):
    monkeypatch.setattr(dc, "_call_decompose_llm", lambda p, c:
        '{"artifacts":[{"name":"x","side":"admin","scene":"form-list","sub_request":"做列表"}]}')
    assert await decompose("做个列表", CFG, SCENES) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_decompose_llm.py -q`
Expected: FAIL — `AttributeError: module 'app.coding.decompose' has no attribute '_call_decompose_llm'` / ImportError on `decompose`.

- [ ] **Step 3: 写最小实现(追加到 decompose.py)**

```python
# 追加到 backend/app/coding/decompose.py
import logging
logger = logging.getLogger(__name__)

_DECOMPOSE_PROMPT = """你是 aPaaS 低代码平台的需求分解助手。把用户需求分解成多个**独立的单页面/单组件 aPaaS 扩展产物**。

可用 scene(每个产物必须选一个): form-list(列表+CRUD 管理页) / menu-page(菜单聚合页) / mobile-page(移动端页面) / form-page(单表单页)。

规则:
- 只有当需求明显是「多端(管理端+用户端)/多个独立页面/完整业务系统」时才分解成 2-4 个产物;否则返回 {"artifacts":[]}(交给单产物流程)。
- 管理端(HR/后台)用 form-list(每个核心实体一个列表管理页, 或合并相关实体)。用户端(求职者/前台/移动)用 mobile-page。
- 每个产物给一个**聚焦、能独立开发**的 sub_request(自然语言, 只描述这一个产物)。

示例输入: "做招聘系统, 管理端 HR 管职位/候选人/投递/面试, 用户端求职者浏览职位+投递"
示例输出: {"artifacts":[
  {"name":"招聘管理后台","side":"admin","scene":"form-list","sub_request":"做一个招聘管理列表页, 管理职位、候选人、投递、面试四类数据的增删改查"},
  {"name":"求职者端","side":"user","scene":"mobile-page","sub_request":"做一个求职者移动端页面, 浏览职位列表、投递简历、查看我的投递状态"}
]}
反例输入: "做一个登录页" → 输出: {"artifacts":[]}

只输出 JSON, 不要解释。用户需求:
"""


def _call_decompose_llm(prompt: str, llm_cfg: dict) -> str:
    from app.agents.coding.llm_config import _normalize_base_url  # 复用已有
    import httpx
    base = llm_cfg["base_url"].rstrip("/")
    resp = httpx.post(
        base + "/chat/completions",
        headers={"Authorization": f"Bearer {llm_cfg['api_key']}", "Content-Type": "application/json"},
        json={"model": llm_cfg["model"], "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 1200, "temperature": 0},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


async def decompose(requirement: str, llm_cfg: dict, available_scenes: set[str]) -> Optional[list[Artifact]]:
    """多端请求 → 产物计划;任何失败/不适用 → None(回落单产物)。"""
    try:
        raw = _call_decompose_llm(_DECOMPOSE_PROMPT + (requirement or ""), llm_cfg)
    except Exception as exc:  # noqa: BLE001
        logger.warning("decompose LLM 失败, 回落单产物: %r", exc)
        return None
    # 剥可能的 ```json 围栏
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1].lstrip("json").strip() if "```" in raw[3:] else raw
    return parse_decomposition(raw, available_scenes)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_decompose_llm.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/decompose.py backend/tests/test_decompose_llm.py
git commit -m "feat(coding): 分解 LLM 调用 + 失败回落 None(decompose)"
```

---

### Task 3: 编排器(N 次子流水线 + Project 分组)

**Files:**
- Create: `backend/app/coding/orchestrate.py`
- Test: `backend/tests/test_orchestrate.py`

**Interfaces:**
- Consumes: `decompose`(Task 2);`run_coding_pipeline(params, db)`(现有, 异步生成器);`PipelineParams`;`available_scenes` 由 SceneType 推导。
- Produces: `async run_multi_artifact(params, db, *, available_scenes, decomposer=decompose, runner=run_coding_pipeline, project_factory=...) -> AsyncIterator[dict]`(依赖注入便于测试)。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_orchestrate.py
from app.coding.orchestrate import run_multi_artifact

class _Params:
    def __init__(self): self.message="招聘系统 管理端+用户端"; self.user_id=1; self.tenant_id=1
    workspace_id=None; conversation_id=None; project_id=None; selected_model=None; app_id=None; attachments=None

async def _fake_decomposer(req, cfg, scenes):
    from app.coding.decompose import Artifact
    return [Artifact(name="后台",side="admin",scene="form-list",sub_request="做招聘管理列表页"),
            Artifact(name="求职端",side="user",scene="mobile-page",sub_request="做求职移动端")]

def _make_runner(record):
    async def runner(params, db):
        record.append(params.message)
        yield {"type":"step","step":"generate","status":"done","data":{}}
        yield {"type":"done","workspace_id":f"ws_{len(record)}","conversation_id":None}
    return runner

async def test_decomposes_runs_n_subpipelines_and_groups(monkeypatch):
    record=[]
    events=[]
    async def proj_factory(params, db): return 77
    async for ev in run_multi_artifact(_Params(), db=None,
            available_scenes={"form-list","mobile-page"},
            decomposer=_fake_decomposer, runner=_make_runner(record),
            project_factory=proj_factory):
        events.append(ev)
    assert len(record) == 2                                  # 跑了 2 个子产物
    assert any("职位" in m or "招聘" in m or "管理" in m for m in record)
    assert any(e.get("type")=="multi_artifact_plan" for e in events)      # 计划事件
    assert any(e.get("type")=="multi_artifact_summary" for e in events)   # 汇总事件
    summ=[e for e in events if e.get("type")=="multi_artifact_summary"][0]
    assert summ["project_id"]==77 and len(summ["artifacts"])==2

async def test_falls_back_to_single_when_no_plan(monkeypatch):
    record=[]
    async def none_decomposer(req,cfg,scenes): return None
    events=[ev async for ev in run_multi_artifact(_Params(), db=None,
            available_scenes={"form-list"}, decomposer=none_decomposer,
            runner=_make_runner(record), project_factory=None)]
    assert len(record)==1                                    # 回落: 整个原 message 跑一次
    assert record[0]=="招聘系统 管理端+用户端"
    assert not any(e.get("type")=="multi_artifact_plan" for e in events)

async def test_isolates_failing_artifact(monkeypatch):
    record=[]
    async def runner(params, db):
        record.append(params.message)
        if "求职" in params.message:
            raise RuntimeError("boom")
        yield {"type":"done","workspace_id":"ws","conversation_id":None}
    async def proj_factory(params, db): return 5
    events=[ev async for ev in run_multi_artifact(_Params(), db=None,
            available_scenes={"form-list","mobile-page"}, decomposer=_fake_decomposer,
            runner=runner, project_factory=proj_factory)]
    summ=[e for e in events if e.get("type")=="multi_artifact_summary"][0]
    fails=[a for a in summ["artifacts"] if a.get("status")=="failed"]
    assert len(fails)==1 and len(record)==2                  # 失败隔离, 不整崩
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_orchestrate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.coding.orchestrate'`

- [ ] **Step 3: 写最小实现**

```python
# backend/app/coding/orchestrate.py
"""多产物分解编排:把多端请求拆成 N 个聚焦 sub_request, 各跑一次首轮 run_coding_pipeline,
挂同一 Project 分组。复用现有单产物流水线当生成原语;失败隔离;无计划则回落单产物。"""
from __future__ import annotations
import logging
from typing import AsyncIterator, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


async def _default_project_factory(params, db) -> Optional[int]:
    """新建一个 Project 行作分组;失败返回 None(产物仍生成, 只是不分组)。"""
    try:
        from app.models import Project
        name = (params.message or "多产物应用").strip().split("\n")[0][:40]
        proj = Project(name=name, user_id=params.user_id, tenant_id=getattr(params, "tenant_id", None))
        db.add(proj); await db.commit(); await db.refresh(proj)
        return proj.id
    except Exception as exc:  # noqa: BLE001
        logger.warning("Project 分组创建失败(非致命): %r", exc)
        return None


def _sub_params(base, sub_request: str, project_id: Optional[int]):
    from app.coding.pipeline import PipelineParams
    return PipelineParams(
        message=sub_request, user_id=base.user_id, tenant_id=base.tenant_id,
        workspace_id=None, conversation_id=None, project_id=project_id,
        selected_model=getattr(base, "selected_model", None),
    )


async def run_multi_artifact(
    params, db, *, available_scenes: set[str],
    decomposer: Callable[..., Awaitable] , runner: Callable[..., AsyncIterator[dict]],
    project_factory: Optional[Callable[..., Awaitable]] = None,
    llm_cfg: Optional[dict] = None,
) -> AsyncIterator[dict]:
    plan = None
    try:
        plan = await decomposer(params.message, llm_cfg or {}, available_scenes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("分解异常, 回落单产物: %r", exc)
        plan = None

    if not plan:
        async for ev in runner(params, db):   # 回落: 整个原请求跑一次单产物
            yield ev
        return

    factory = project_factory or _default_project_factory
    project_id = await factory(params, db)
    yield {"type": "multi_artifact_plan", "project_id": project_id,
           "artifacts": [{"name": a["name"], "side": a["side"], "scene": a["scene"]} for a in plan]}

    results = []
    for idx, art in enumerate(plan):
        ws_id = None
        status = "done"
        try:
            async for ev in runner(_sub_params(params, art["sub_request"], project_id), db):
                ev = {**ev, "artifact_index": idx, "artifact_name": art["name"]}
                if ev.get("type") == "done" and ev.get("workspace_id"):
                    ws_id = ev["workspace_id"]
                yield ev
        except Exception as exc:  # noqa: BLE001 — 单产物失败隔离
            status = "failed"
            logger.warning("产物 %s 生成失败: %r", art["name"], exc)
            yield {"type": "multi_artifact_error", "artifact_index": idx,
                   "artifact_name": art["name"], "message": str(exc)}
        results.append({"name": art["name"], "side": art["side"], "scene": art["scene"],
                        "workspace_id": ws_id, "status": status})

    yield {"type": "multi_artifact_summary", "project_id": project_id, "artifacts": results}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_orchestrate.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/orchestrate.py backend/tests/test_orchestrate.py
git commit -m "feat(coding): 多产物编排器 run_multi_artifact(N 子流水线+Project 分组+失败隔离)"
```

---

### Task 4: 路由接线(入口判断)

**Files:**
- Modify: `backend/app/coding/pipeline.py`(在 `run_coding_pipeline` 之外加一个分流入口 `run_coding_entry`)
- Test: `backend/tests/test_coding_entry_routing.py`

**Interfaces:**
- Consumes: `run_multi_artifact`(Task 3)、`run_coding_pipeline`(现有)、`_has_multi_end_signal`(delivery_honesty)、`SceneType`(scenes.py)。
- Produces: `should_decompose(message: str, is_iteration: bool) -> bool`;`async run_coding_entry(params, db) -> AsyncIterator[dict]`(harness/路由改调它)。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_coding_entry_routing.py
from app.coding.pipeline import should_decompose

def test_decompose_only_first_turn_strong_signal():
    assert should_decompose("做招聘系统 管理端+用户端两端", is_iteration=False) is True
    assert should_decompose("做招聘系统 管理端+用户端两端", is_iteration=True) is False   # 迭代不分解
    assert should_decompose("做一个职位列表页", is_iteration=False) is False              # 单页不分解
    assert should_decompose("HR 后台管理, 求职者前台投递", is_iteration=False) is True     # 双侧强信号
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_coding_entry_routing.py -q`
Expected: FAIL — `ImportError: cannot import name 'should_decompose'`

- [ ] **Step 3: 写最小实现(追加到 pipeline.py 顶部 helper 区)**

```python
# 追加到 backend/app/coding/pipeline.py(import 区下方)
def should_decompose(message: str, is_iteration: bool) -> bool:
    """首轮 + 多端强信号 → 走多产物分解。迭代/弱信号 → 否。"""
    if is_iteration:
        return False
    try:
        from app.coding.delivery_honesty import _has_multi_end_signal
        return _has_multi_end_signal(message or "")
    except Exception:  # noqa: BLE001
        return False


async def run_coding_entry(params, db):
    """coding 统一入口: 多端强信号首轮 → 多产物编排;否则原单产物流水线。"""
    is_iteration = params.workspace_id is not None
    if should_decompose(params.message, is_iteration):
        from app.coding.orchestrate import run_multi_artifact
        from app.coding.scenes import SCENE_REGISTRY  # 单产物 scene 值集合
        from app.coding.decompose import decompose
        scenes = {"form-list", "menu-page", "mobile-page", "form-page"}
        # 解析本租户 LLM 供 decompose 用(失败则 decompose 内部回落)
        try:
            from app.agents.coding.llm_config import load_coding_llm_config
            b, k, m = await load_coding_llm_config(params.tenant_id, params.selected_model)
            llm_cfg = {"base_url": b, "api_key": k, "model": m}
        except Exception:  # noqa: BLE001
            llm_cfg = {}
        async for ev in run_multi_artifact(
            params, db, available_scenes=scenes, decomposer=decompose,
            runner=run_coding_pipeline, llm_cfg=llm_cfg,
        ):
            yield ev
        return
    async for ev in run_coding_pipeline(params, db):
        yield ev
```

- [ ] **Step 4: 跑测试 + 确认 import 不崩**

Run: `.venv/bin/python -m pytest tests/test_coding_entry_routing.py -q && .venv/bin/python -c "import app.coding.pipeline"`
Expected: PASS (1 passed) + `no error`

- [ ] **Step 5: 把 harness coding profile 改调 run_coding_entry**

Modify `backend/app/harness/profiles/coding.py:95`:把 `run_coding_pipeline(params, db)` 改为 `run_coding_entry(params, db)`(import 同步)。

Run: `.venv/bin/python -c "import app.harness.profiles.coding"`
Expected: `no error`

- [ ] **Step 6: 提交**

```bash
git add backend/app/coding/pipeline.py backend/app/harness/profiles/coding.py backend/tests/test_coding_entry_routing.py
git commit -m "feat(coding): 入口分流 run_coding_entry(多端强信号首轮→多产物编排)"
```

---

### Task 5: G3 — 单页 scene 本地预览 harness

**Files:**
- Create: `backend/templates/cli-generated/form-page-web/preview/index.html`、`preview/main.js`(若模板目录存在;否则定位真实模板路径后同构添加)
- Modify: `backend/templates/cli-generated/form-page-web/package.json`(scripts 加 `preview`)
- Test: `backend/tests/test_single_page_preview.py`

**Interfaces:**
- Consumes: `_resolve_serve_command`(`workspace.py:1795`)的「有 preview 脚本走 npm run preview」分支。
- Produces: 单页模板带可 mount 的 preview 入口 → `_resolve_serve_command` 对其返回 preview 命令。

- [ ] **Step 1: 先核实真实模板路径与 src/index.js 导出形态**

Run: `ls backend/templates/cli-generated/ && sed -n '1,30p' backend/templates/cli-generated/form-page-web/src/index.js 2>/dev/null`
据实定位模板目录与组件导出(UMD `{install}` vs 组件本身),preview/main.js 取真正页面组件挂载。

- [ ] **Step 2: 写失败测试**

```python
# backend/tests/test_single_page_preview.py
from pathlib import Path
from app.coding.workspace import WorkspaceManager

def test_resolve_serve_uses_preview_when_present(tmp_path: Path):
    # 造一个带 preview 脚本的单页工作区
    (tmp_path / "package.json").write_text(
        '{"scripts":{"serve":"node vibe-serve.js src/index.js","preview":"vue-cli-service serve preview/main.js"}}',
        encoding="utf-8")
    cmd = WorkspaceManager()._resolve_serve_command(tmp_path)
    assert "preview" in " ".join(cmd) or "main.js" in " ".join(cmd)
```

- [ ] **Step 3: 跑测试确认失败/通过状态**

Run: `.venv/bin/python -m pytest tests/test_single_page_preview.py -q`
若失败=`_resolve_serve_command` 签名/行为不符 → 据 `workspace.py:1795` 实际签名调整测试调用;目标是锁定「有 preview 脚本即走 preview」。

- [ ] **Step 4: 给模板补 preview harness**

`preview/index.html`: 一个 `<div id="app"></div>` + 挂载脚本入口。
`preview/main.js`: import `src/index.js` 的页面组件(按 Step 1 实测导出形态取真正组件)`new Vue({render:h=>h(Comp)}).$mount('#app')`。
`package.json` scripts 加 `"preview": "vue-cli-service serve preview/main.js"`。
(复用 `workspace.py:3831/3855` form-component-dual 现成内联 preview 模板写法。)

- [ ] **Step 5: 编排器每个产物生成后自动起 serve**

Modify `run_multi_artifact`(Task 3):产物 done 拿到 ws_id 后,`try: ws_mgr.start_serve(ws_id)` 读回 port 并入 summary 的该产物项;失败仅 log。

- [ ] **Step 6: 跑测试 + 提交**

Run: `.venv/bin/python -m pytest tests/test_single_page_preview.py tests/test_orchestrate.py -q`
Expected: PASS

```bash
git add backend/templates/cli-generated/form-page-web/preview backend/templates/cli-generated/form-page-web/package.json backend/app/coding/orchestrate.py backend/tests/test_single_page_preview.py
git commit -m "feat(coding): G3 单页 scene 真 mount preview harness + 编排自动起 serve"
```

---

### Task 6: 端到端 dogfood 验证

**Files:** 复用 `/tmp/recruit_dogfood.py`(改捕获 `multi_artifact_plan`/`multi_artifact_summary` 事件 + 改调 `run_coding_entry`)。

- [ ] **Step 1: 改 dogfood 驱动**:`run_coding_pipeline` → `run_coding_entry`;事件循环加记 `multi_artifact_plan`/`multi_artifact_summary`/`multi_artifact_error`。
- [ ] **Step 2: 后台真跑**:`run_in_background`,日志 `/tmp/recruit_dogfood_v3.log`。
- [ ] **Step 3: 验收断言**:日志出现 `multi_artifact_plan`(N≥2)+ `multi_artifact_summary`,N 个产物挂同一 project_id,各自有 workspace_id,(G3 后)各有 port。即:招聘请求**真分解成多个 aPaaS 产物**而非一个塞满的文件。
- [ ] **Step 4: 记录结果**:更新 memory `recruit_dogfood_gaps_2026_06_20`(标 A 方案落地 + 验收结论)。

---

## Self-Review

- **Spec coverage**: 多端检测(Task4 should_decompose)/ 分解器(Task1+2)/ 编排器+Project 分组+失败隔离(Task3)/ 接线(Task4)/ G3 预览(Task5)/ 回落(Task3 test_falls_back)/ 端到端(Task6)——spec 各节均有对应 task。
- **回落永不更糟**:Task3 `if not plan: runner(params)` + Task2 异常→None,已测。
- **类型一致**:`Artifact`(name/side/scene/sub_request)Task1 定义,Task2/3 一致使用;`run_multi_artifact` 依赖注入签名 Task3 定义、Task4 按之调用。
- **待执行期核实(非 placeholder, 是真实依赖)**:Task4 `SCENE_REGISTRY` 实际单产物 scene 值集合、Task5 模板真实路径与 `_resolve_serve_command` 签名、`Project` 模型字段(name/user_id/tenant_id 是否齐)、`load_coding_llm_config` 返回顺序(b,k,m)——每个 task Step 1 已含实测步骤。
