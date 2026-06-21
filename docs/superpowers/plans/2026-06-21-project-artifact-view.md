# 项目 → 产物视图(含跨产物依赖)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/project/:id` 重做成「产物按模式分组网格 + 跨产物声明式依赖图 + 点产物跳现有页面」,作为已落地多产物分解后端的展示层。

**Architecture:** 后端加一张 `ProjectArtifactDependency` 表 + decompose 声明依赖边 + orchestrate 落库 + 一个读接口;前端就地重写 `ProjectOverview.vue`,用纯函数适配器把 `platform_app + workspaces` 拼成统一产物列表、按 `project_type` 分组,依赖边按 ref 解析渲染。复用 origin/dev 的类型骨架与模式色 token,纯函数全 TDD。

**Tech Stack:** 后端 FastAPI + SQLAlchemy(async)+ pytest(asyncio_mode=auto);前端 Vue 3 + TypeScript + vitest(environment:node)。

## Global Constraints

逐条来自 spec(`docs/superpowers/specs/2026-06-21-project-artifact-view-design.md`),每个任务隐含遵守:

- 前端测试文件名 `*.spec.ts`(vitest `include: ['src/**/*.spec.ts']`),运行 `cd frontend && npx vitest run <file>`,环境 `node` 无 DOM —— 组件测试只能 `import src from '...vue?raw'` 做源码字符串断言,**禁用** `@vue/test-utils` mount。
- 后端测试 `tests/test_*.py`,`asyncio_mode=auto`(async 测试函数直接 `async def test_x(...)`,无需 `@pytest.mark.asyncio` 也可,但现有路由测试带了,沿用),运行 `cd backend && python -m pytest tests/<file> -v`。路由测试**直接 import handler 函数级调用** + `db_session` fixture + 手搓 `AuthContext`(见 Task 4)。
- 仓库无 alembic;新表由 `Base.metadata.create_all`(`app/database.py:63`)自动建,**不可**给已有表加列(那要手写 ALTER)。
- 改后端必重启进程(`backend/run.py` reload=False)才生效。
- v1 依赖边**仅 workspace↔workspace**;`app:<id>` ref 形式保留 schema 前向兼容但 v1 不产生。
- `parse_decomposition` 签名与返回**不变**(现有 6 个单测零改动);依赖解析走新函数 `parse_dependencies`。
- 模式映射表(`projectTypeToMode`)、状态归一表(`normalizeArtifactStatus`)、摘要表(`projectTypeToLabel`)的取值**逐字**照 spec §3.1/§5.3/§3.2。
- 置灰动作按钮 tooltip 文案:新建产物→「即将支持:当前请在对话里发起多产物分解」;重新部署/继续构建→「即将支持」。
- 模式色仅作装饰(图标/边框/chip 背景),不作正文文字色。

---

## File Structure

**后端**
- Modify `backend/app/coding/decompose.py` — 加 `parse_dependencies`;`decompose()` 返回 `(artifacts, deps)`;prompt 增补。
- Modify `backend/app/models/__init__.py` — 加 `ProjectArtifactDependency` 模型。
- Modify `backend/app/coding/orchestrate.py` — `run_multi_artifact` 兼容 tuple plan + 落库依赖(注入式 `dep_writer`)。
- Modify `backend/app/routes/projects.py` — 加 `GET /{project_id}/dependencies` handler + `_dep_to_dict`。
- Test: `backend/tests/test_decompose_deps.py` / 改 `test_decompose_llm.py` / `test_orchestrate_deps.py` / `test_projects_dependencies_route.py`。

**前端**
- Modify `frontend/src/styles/design-v3-tokens.css` — 加模式色块(copy origin/dev)。
- Create `frontend/src/composables/projectVM.ts` — 类型 + `projectTypeToMode`/`projectTypeToLabel`/`normalizeArtifactStatus`/`buildArtifacts`/`resolveDependencies` 纯函数。
- Modify `frontend/src/api/projects.ts` — `ArtifactDependency` 类型 + `listDependencies`。
- Create `frontend/src/composables/useProjectArtifacts.ts` — 数据编排(核心 `buildProjectView(projectId, api)` 可注入测试)。
- Create `frontend/src/components/project/ArtifactCard.vue` / `ArtifactGroup.vue` / `ArtifactDependencyGraph.vue`。
- Modify `frontend/src/views/ProjectOverview.vue` — 重写为编排上述。
- Test: `frontend/src/composables/projectVM.spec.ts` / `useProjectArtifacts.spec.ts` / `frontend/src/components/project/*.spec.ts`。

---

## Task 1: 后端 — `parse_dependencies` + `decompose()` 返回依赖

**Files:**
- Modify: `backend/app/coding/decompose.py`
- Test: `backend/tests/test_decompose_deps.py`(新增)、`backend/tests/test_decompose_llm.py`(改)

**Interfaces:**
- Produces:
  - `parse_dependencies(raw_json: str, n_artifacts: int) -> list[dict]` —— 每项 `{"from":int,"to":int,"expose":str,"consume":str,"note":str}`;非法/越界/自引用丢弃;缺失→`[]`。
  - `decompose(requirement, llm_cfg, available_scenes) -> Optional[tuple[list[Artifact], list[dict]]]` —— 无计划仍返回 `None`(回落语义不变),否则 `(artifacts, dependencies)`。
- Consumes: 无(本任务起点)。

- [ ] **Step 1: 写失败测试 `test_decompose_deps.py`**

```python
from app.coding.decompose import parse_dependencies


def test_parses_valid_dependency():
    raw = ('{"artifacts":[{},{}],"dependencies":[{"from":0,"to":1,'
           '"expose":"暴露 /api/ticket","consume":"consume ticketApi","note":"改字段会影响用户端"}]}')
    deps = parse_dependencies(raw, n_artifacts=2)
    assert len(deps) == 1
    assert deps[0]["from"] == 0 and deps[0]["to"] == 1
    assert deps[0]["expose"] == "暴露 /api/ticket"


def test_drops_out_of_range_and_self_ref():
    raw = ('{"dependencies":[{"from":0,"to":5,"expose":"x","consume":"y","note":""},'
           '{"from":1,"to":1,"expose":"x","consume":"y","note":""},'
           '{"from":0,"to":1,"expose":"ok","consume":"ok","note":""}]}')
    deps = parse_dependencies(raw, n_artifacts=2)
    assert len(deps) == 1 and deps[0]["expose"] == "ok"


def test_empty_when_missing_or_illegal():
    assert parse_dependencies('{"artifacts":[{}]}', 1) == []
    assert parse_dependencies('not json', 2) == []
    assert parse_dependencies('{"dependencies":"nope"}', 2) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_decompose_deps.py -v`
Expected: FAIL —— `ImportError: cannot import name 'parse_dependencies'`

- [ ] **Step 3: 实现 `parse_dependencies`(加到 `decompose.py`,放在 `parse_decomposition` 之后)**

```python
def parse_dependencies(raw_json: str, n_artifacts: int) -> list[dict]:
    """解析 LLM 声明的产物间依赖边。from/to 是 artifact index;
    越界/自引用/非法一律丢弃;缺失或整体非法 → []。永不抛。"""
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return []
    raw_deps = data.get("dependencies") if isinstance(data, dict) else None
    if not isinstance(raw_deps, list):
        return []
    out: list[dict] = []
    for d in raw_deps:
        if not isinstance(d, dict):
            continue
        try:
            fr = int(d.get("from"))
            to = int(d.get("to"))
        except (TypeError, ValueError):
            continue
        if not (0 <= fr < n_artifacts and 0 <= to < n_artifacts) or fr == to:
            continue
        out.append({
            "from": fr, "to": to,
            "expose": str(d.get("expose") or "").strip(),
            "consume": str(d.get("consume") or "").strip(),
            "note": str(d.get("note") or "").strip(),
        })
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_decompose_deps.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 改 `decompose()` 返回 `(artifacts, deps)` + prompt 增补**

在 `_DECOMPOSE_PROMPT` 的「规则」末尾加一行,并在示例输出里补 dependencies(改 `decompose.py` 的 prompt 常量):

```python
# 在示例输出 JSON 里,artifacts 同级加:
#   ,"dependencies":[{"from":0,"to":1,"expose":"管理端暴露工单接口 /api/ticket","consume":"用户端 consume ticketApi","note":"改配置端工单字段会影响用户端调用代码"}]
# 规则末尾加一行:
#   - 若产物间有「一个暴露接口/数据、另一个消费」的关系,在 dependencies 里声明(from/to 用 artifacts 下标,0 起);无则省略。
```

改 `decompose()` 函数末尾的 return:

```python
    arts = parse_decomposition(raw, available_scenes)
    if not arts:
        return None
    deps = parse_dependencies(raw, len(arts))
    return arts, deps
```

- [ ] **Step 6: 改 `test_decompose_llm.py` 适配 tuple 返回**

把现有断言里 `plan = await decompose(...)` 后对 list 的使用改成解包。例如(按该文件现有用例调整):

```python
    result = await decompose(req, cfg, SCENES)
    assert result is not None
    arts, deps = result
    assert len(arts) == 2
    # 无计划用例仍断言 result is None
```

- [ ] **Step 7: 跑全部 decompose 测试(含未改的 parse 测试必须仍绿)**

Run: `cd backend && python -m pytest tests/test_decompose_deps.py tests/test_decompose_parse.py tests/test_decompose_llm.py -v`
Expected: PASS(`test_decompose_parse.py` 6 个零改动通过 = 契约未破)

- [ ] **Step 8: 提交**

```bash
git add backend/app/coding/decompose.py backend/tests/test_decompose_deps.py backend/tests/test_decompose_llm.py
git commit -m "feat(coding): decompose 声明式跨产物依赖 parse_dependencies + decompose 返回(artifacts,deps)"
```

---

## Task 2: 后端 — `ProjectArtifactDependency` 模型

**Files:**
- Modify: `backend/app/models/__init__.py`(在 `ProjectMember` 类之后插入)
- Test: `backend/tests/test_artifact_dependency_model.py`(新增)

**Interfaces:**
- Produces: ORM 模型 `ProjectArtifactDependency`,列 `id/project_id/from_ref/to_ref/expose_label/consume_label/note/created_at`。

- [ ] **Step 1: 写失败测试**

```python
from app.models import ProjectArtifactDependency


def test_model_columns_exist():
    cols = set(ProjectArtifactDependency.__table__.columns.keys())
    assert {"id", "project_id", "from_ref", "to_ref",
            "expose_label", "consume_label", "note", "created_at"} <= cols


def test_table_name():
    assert ProjectArtifactDependency.__tablename__ == "project_artifact_dependencies"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_artifact_dependency_model.py -v`
Expected: FAIL —— `ImportError: cannot import name 'ProjectArtifactDependency'`

- [ ] **Step 3: 实现模型(仿 `ProjectMember`,放其后)**

```python
class ProjectArtifactDependency(Base):
    """跨产物声明式依赖 — 一个产物暴露、另一个消费(workspace↔workspace, v1)"""
    __tablename__ = "project_artifact_dependencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    from_ref: Mapped[str] = mapped_column(String(80), nullable=False)   # workspace:<id>
    to_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    expose_label: Mapped[str] = mapped_column(String(120), default="")
    consume_label: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_artifact_dependency_model.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/__init__.py backend/tests/test_artifact_dependency_model.py
git commit -m "feat(models): ProjectArtifactDependency 表(声明式跨产物依赖, create_all 自动建)"
```

---

## Task 3: 后端 — orchestrate 落库依赖

**Files:**
- Modify: `backend/app/coding/orchestrate.py`
- Test: `backend/tests/test_orchestrate_deps.py`(新增)

**Interfaces:**
- Consumes: Task 1 的 `decompose() -> (artifacts, deps)`;Task 2 的 `ProjectArtifactDependency`。
- Produces: `run_multi_artifact(..., dep_writer=None)` —— 新增可选注入参数 `dep_writer(project_id, edges)`(edges 为 `[{from_ref,to_ref,expose_label,consume_label,note}]`);默认写 DB,测试可注入 fake。`run_multi_artifact` 兼容 `decomposer` 返回 list(旧 fake)或 `(arts, deps)`(真 decompose)。

- [ ] **Step 1: 写失败测试**

```python
from app.coding.orchestrate import run_multi_artifact
from app.coding.decompose import Artifact


class _P:
    message = "招聘 管理端+用户端"; user_id = 1; tenant_id = 1
    workspace_id = None; conversation_id = None; project_id = None
    selected_model = None; app_id = None; attachments = None


def _runner(rec):
    async def runner(params, db):
        rec.append(params.message)
        yield {"type": "done", "workspace_id": f"ws_{len(rec)}", "conversation_id": None}
    return runner


async def _decomposer_with_deps(req, cfg, scenes):
    arts = [Artifact(name="后台", side="admin", scene="form-list", sub_request="管理列表"),
            Artifact(name="用户端", side="user", scene="mobile-page", sub_request="移动端")]
    deps = [{"from": 0, "to": 1, "expose": "暴露 /api/ticket",
             "consume": "consume ticketApi", "note": "改字段影响用户端"}]
    return arts, deps


async def test_writes_resolved_edges():
    written = []
    async def dep_writer(project_id, edges):
        written.append((project_id, edges))
    async def proj_factory(params, db):
        return 42
    rec = []
    events = [ev async for ev in run_multi_artifact(
        _P(), db=None, available_scenes={"form-list", "mobile-page"},
        decomposer=_decomposer_with_deps, runner=_runner(rec),
        project_factory=proj_factory, dep_writer=dep_writer)]
    assert len(written) == 1
    pid, edges = written[0]
    assert pid == 42 and len(edges) == 1
    assert edges[0]["from_ref"] == "workspace:ws_1"
    assert edges[0]["to_ref"] == "workspace:ws_2"
    assert edges[0]["expose_label"] == "暴露 /api/ticket"


async def test_legacy_list_decomposer_still_works():
    # 旧 fake 返回 list(无 deps),不传 dep_writer → 不崩、不写边
    async def legacy(req, cfg, scenes):
        return [Artifact(name="a", side="admin", scene="form-list", sub_request="x"),
                Artifact(name="b", side="user", scene="mobile-page", sub_request="y")]
    rec = []
    events = [ev async for ev in run_multi_artifact(
        _P(), db=None, available_scenes={"form-list", "mobile-page"},
        decomposer=legacy, runner=_runner(rec), project_factory=None)]
    assert any(e.get("type") == "multi_artifact_summary" for e in events)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_orchestrate_deps.py -v`
Expected: FAIL —— `run_multi_artifact() got an unexpected keyword argument 'dep_writer'`

- [ ] **Step 3: 实现 —— 加 `_unpack_plan`、`dep_writer` 参数、落库步**

在 `orchestrate.py` 顶部加 helper:

```python
def _unpack_plan(raw):
    """decomposer 可能返回 (arts, deps) 或 旧式 list 或 None。归一成 (arts, deps)。"""
    if raw is None:
        return None, []
    if isinstance(raw, tuple):
        arts, deps = raw
        return (arts or None), (deps or [])
    return (raw or None), []   # 旧 fake 返回 list


async def _default_dep_writer(project_id, edges):
    """默认把依赖边写 DB;无 project_id 或无边则跳过;异常非致命。"""
    if not project_id or not edges:
        return
    try:
        from app.database import AsyncSessionLocal
        from app.models import ProjectArtifactDependency
        async with AsyncSessionLocal() as s:
            for e in edges:
                s.add(ProjectArtifactDependency(
                    project_id=project_id, from_ref=e["from_ref"], to_ref=e["to_ref"],
                    expose_label=e.get("expose_label", ""), consume_label=e.get("consume_label", ""),
                    note=e.get("note", "")))
            await s.commit()
    except Exception as exc:  # noqa: BLE001 — 落库失败非致命
        logger.warning("依赖落库失败(非致命): %r", exc)
```

改 `run_multi_artifact` 签名加 `dep_writer: Optional[Callable[..., Awaitable]] = None`;把 `plan = await decomposer(...)` 后改用 `_unpack_plan`:

```python
    raw = None
    try:
        raw = await decomposer(params.message, llm_cfg or {}, available_scenes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("分解异常, 回落单产物: %r", exc)
        raw = None
    plan, deps = _unpack_plan(raw)

    if not plan:
        async for ev in runner(params, db):
            yield ev
        return
```

在结尾 `yield {"type": "multi_artifact_summary", ...}` **之前**,按 index 解析边并写库:

```python
    # 声明式依赖落库(v1 仅 workspace↔workspace;某端产物失败则跳过该边)
    if deps:
        ws_by_idx = {i: r["workspace_id"] for i, r in enumerate(results) if r.get("workspace_id")}
        edges = []
        for d in deps:
            fw, tw = ws_by_idx.get(d["from"]), ws_by_idx.get(d["to"])
            if not fw or not tw:
                continue
            edges.append({"from_ref": f"workspace:{fw}", "to_ref": f"workspace:{tw}",
                          "expose_label": d.get("expose", ""), "consume_label": d.get("consume", ""),
                          "note": d.get("note", "")})
        if edges:
            await (dep_writer or _default_dep_writer)(project_id, edges)
```

- [ ] **Step 4: 跑新测试 + 现有 orchestrate 测试(必须全绿)**

Run: `cd backend && python -m pytest tests/test_orchestrate_deps.py tests/test_orchestrate.py -v`
Expected: PASS(新 2 个 + 现有 6 个;`_unpack_plan` 保旧 list fake 工作)

- [ ] **Step 5: 提交**

```bash
git add backend/app/coding/orchestrate.py backend/tests/test_orchestrate_deps.py
git commit -m "feat(coding): orchestrate 把声明的依赖边解析成 workspace ref 落库(注入式 dep_writer)"
```

---

## Task 4: 后端 — `GET /projects/:id/dependencies` 接口

**Files:**
- Modify: `backend/app/routes/projects.py`(在 `list_members` handler :369 附近加新 handler）
- Test: `backend/tests/test_projects_dependencies_route.py`(新增,仿 `test_projects_routes_phase_a.py`)

**Interfaces:**
- Consumes: Task 2 的 `ProjectArtifactDependency`;现有 `require_project_access`、`get_auth_context`、`get_db`、`AuthContext`。
- Produces: `async def list_dependencies(project_id, ctx, db) -> list[dict]`,每项 `{from_ref,to_ref,expose_label,consume_label,note}`。

- [ ] **Step 1: 写失败测试(仿 phase_a 的 `_setup` + 直接调 handler)**

```python
import pytest
from sqlalchemy import select
from app.deps import AuthContext
from app.models import Project, ProjectMember, User, ProjectArtifactDependency
from app.models.tenant import Tenant, UserTenant
from app.routes.projects import list_dependencies


async def _setup(db_session):
    tenant = Tenant(tenant_name="t1", tenant_code="t1"); db_session.add(tenant); await db_session.flush()
    owner = User(username="o", hashed_password="x"); db_session.add(owner); await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))
    project = Project(name="p", user_id=owner.id, tenant_id=tenant.id); db_session.add(project); await db_session.flush()
    db_session.add(ProjectMember(project_id=project.id, user_id=owner.id, role="owner"))
    await db_session.commit()
    ctx = AuthContext(user=owner, tenant_id=tenant.id, tenant_role="tenant_admin", org_permissions={})
    return ctx, project.id


@pytest.mark.asyncio
async def test_lists_dependencies(db_session):
    ctx, pid = await _setup(db_session)
    db_session.add(ProjectArtifactDependency(
        project_id=pid, from_ref="workspace:a", to_ref="workspace:b",
        expose_label="暴露X", consume_label="consumeX", note="n"))
    await db_session.commit()
    rows = await list_dependencies(pid, ctx, db_session)
    assert len(rows) == 1 and rows[0]["from_ref"] == "workspace:a"
    assert rows[0]["expose_label"] == "暴露X"


@pytest.mark.asyncio
async def test_empty_when_none(db_session):
    ctx, pid = await _setup(db_session)
    rows = await list_dependencies(pid, ctx, db_session)
    assert rows == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_projects_dependencies_route.py -v`
Expected: FAIL —— `ImportError: cannot import name 'list_dependencies'`

- [ ] **Step 3: 实现 handler(加到 `projects.py`,紧跟 `list_members`)**

```python
def _dep_to_dict(d: "ProjectArtifactDependency") -> dict:
    return {"from_ref": d.from_ref, "to_ref": d.to_ref,
            "expose_label": d.expose_label, "consume_label": d.consume_label, "note": d.note}


@router.get("/{project_id}/dependencies")
async def list_dependencies(
    project_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await require_project_access(project_id, ctx, db, need="view")
    from app.models import ProjectArtifactDependency
    rows = (await db.execute(
        select(ProjectArtifactDependency).where(ProjectArtifactDependency.project_id == project_id)
    )).scalars().all()
    return [_dep_to_dict(d) for d in rows]
```

> 注:`require_project_access` 的具体参数照该文件 `list_members`(:369-376)写法对齐(need/role 关键字以现有代码为准);`select` 已在文件顶部 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_projects_dependencies_route.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/routes/projects.py backend/tests/test_projects_dependencies_route.py
git commit -m "feat(projects): GET /projects/:id/dependencies 读接口(can_view 鉴权)"
```

---

## Task 5: 前端 — 模式色 token

**Files:**
- Modify: `frontend/src/styles/design-v3-tokens.css`

**Interfaces:**
- Produces: CSS 变量 `--build/--lowcode/--fullcode/--agent` + 对应 `-bg`。

- [ ] **Step 1: 加模式色到 `:root` 块**(copy 自 origin/dev,放在 `:root{...}` 内已有变量后)

```css
  /* 产物模式色(桌面 IA) */
  --build:#34D3E0;    --build-bg:rgba(52,211,224,0.12);
  --lowcode:#7C8CFF;  --lowcode-bg:rgba(124,140,255,0.13);
  --fullcode:#A78BFA; --fullcode-bg:rgba(167,139,250,0.13);
  --agent:#FBBF24;    --agent-bg:rgba(251,191,36,0.12);
```

- [ ] **Step 2: 验证编译不报错**

Run: `cd frontend && npx vite build --mode development 2>&1 | tail -5`
(或跳过,留待 Task 13 整体验证)Expected: 无 CSS 解析错误。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/styles/design-v3-tokens.css
git commit -m "feat(ia): 加产物模式色 token(--build/lowcode/fullcode/agent)"
```

---

## Task 6: 前端 — `projectVM.ts` 模式/标签/状态纯函数

**Files:**
- Create: `frontend/src/composables/projectVM.ts`
- Test: `frontend/src/composables/projectVM.spec.ts`

**Interfaces:**
- Produces:
  - `type Mode = 'build' | 'lowcode' | 'fullcode' | 'agent'`
  - `interface ArtifactVM { id: string; name: string; mode: Mode; summary: string; status: {label:string; tone:string}; target: {path:string; query:Record<string,string>} }`
  - `projectTypeToMode(pt: string): Mode`
  - `projectTypeToLabel(pt: string): string`
  - `normalizeArtifactStatus(raw: string): {label:string; tone:string}`

- [ ] **Step 1: 写失败测试**

```typescript
import { describe, it, expect } from 'vitest'
import { projectTypeToMode, projectTypeToLabel, normalizeArtifactStatus } from '@/composables/projectVM'

describe('projectTypeToMode', () => {
  it('backend-* → fullcode', () => {
    for (const t of ['backend-api', 'backend-feign', 'backend-scheduled'])
      expect(projectTypeToMode(t)).toBe('fullcode')
  })
  it('前端自开发类 → lowcode', () => {
    for (const t of ['form-component-dual', 'form-page', 'menu-page', 'mobile-page', 'form-list', 'layout', 'plugin', 'web-login'])
      expect(projectTypeToMode(t)).toBe('lowcode')
  })
  it('未知 → lowcode 兜底', () => {
    expect(projectTypeToMode('???')).toBe('lowcode')
  })
})

describe('projectTypeToLabel', () => {
  it('已知值给中文标签', () => {
    expect(projectTypeToLabel('form-list')).toBe('表单列表页')
    expect(projectTypeToLabel('backend-api')).toBe('后端接口')
  })
  it('未知值回原文', () => {
    expect(projectTypeToLabel('xyz')).toBe('xyz')
  })
})

describe('normalizeArtifactStatus', () => {
  it('按词表映射', () => {
    expect(normalizeArtifactStatus('building')).toEqual({ label: '构建中', tone: 'building' })
    expect(normalizeArtifactStatus('ready')).toEqual({ label: '已完成', tone: 'done' })
    expect(normalizeArtifactStatus('creating')).toEqual({ label: 'AI 在写', tone: 'building' })
    expect(normalizeArtifactStatus('deployed')).toEqual({ label: '已部署', tone: 'live' })
    expect(normalizeArtifactStatus('draft')).toEqual({ label: '草稿', tone: 'draft' })
    expect(normalizeArtifactStatus('error')).toEqual({ label: '失败', tone: 'error' })
  })
  it('未知 → draft tone + 原文', () => {
    expect(normalizeArtifactStatus('weird')).toEqual({ label: 'weird', tone: 'draft' })
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/composables/projectVM.spec.ts`
Expected: FAIL —— 模块/导出不存在。

- [ ] **Step 3: 实现 `projectVM.ts`**

```typescript
// 项目 → 产物视图 view-model(纯函数,可单测;不依赖 DOM/组件)。
export type Mode = 'build' | 'lowcode' | 'fullcode' | 'agent'

export interface ArtifactVM {
  id: string
  name: string
  mode: Mode
  summary: string
  status: { label: string; tone: string }
  target: { path: string; query: Record<string, string> }
}

const FULLCODE = new Set(['backend-api', 'backend-feign', 'backend-scheduled'])
const LOWCODE = new Set(['form-component-dual', 'form-page', 'menu-page', 'mobile-page', 'form-list', 'layout', 'plugin', 'web-login'])

export function projectTypeToMode(pt: string): Mode {
  const s = String(pt || '')
  if (FULLCODE.has(s)) return 'fullcode'
  if (LOWCODE.has(s)) return 'lowcode'
  return 'lowcode'
}

const LABELS: Record<string, string> = {
  'form-list': '表单列表页', 'mobile-page': '移动端页面', 'form-page': '菜单页面',
  'menu-page': '菜单页面', 'form-component-dual': '自开发组件', 'layout': '自定义布局',
  'plugin': '插件', 'web-login': '登录页', 'backend-api': '后端接口',
  'backend-feign': '外部调用', 'backend-scheduled': '定时任务',
}
export function projectTypeToLabel(pt: string): string {
  return LABELS[String(pt || '')] || String(pt || '')
}

export function normalizeArtifactStatus(raw: string): { label: string; tone: string } {
  switch (String(raw || '')) {
    case 'creating':
    case 'installing': return { label: 'AI 在写', tone: 'building' }
    case 'building': return { label: '构建中', tone: 'building' }
    case 'ready': return { label: '已完成', tone: 'done' }
    case 'deployed': return { label: '已部署', tone: 'live' }
    case 'draft': return { label: '草稿', tone: 'draft' }
    case 'error': return { label: '失败', tone: 'error' }
    default: return { label: String(raw || '草稿'), tone: 'draft' }
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/composables/projectVM.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/composables/projectVM.ts frontend/src/composables/projectVM.spec.ts
git commit -m "feat(ia): projectVM 模式/标签/状态纯函数(按 project_type 真实语义)"
```

---

## Task 7: 前端 — `buildArtifacts` + `resolveDependencies`

**Files:**
- Modify: `frontend/src/composables/projectVM.ts`
- Test: `frontend/src/composables/projectVM.spec.ts`(追加)

**Interfaces:**
- Consumes: Task 6 的 `projectTypeToMode/Label`、`normalizeArtifactStatus`、`ArtifactVM`。
- Produces:
  - `buildArtifacts(project, workspaces): ArtifactVM[]` —— 应用本体(若 `platform_connected && platform_app_id`,mode='build',target `/chat?project_id`)+ 每个 workspace(target `/coding?workspace_id`)。
  - `resolveDependencies(edges, artifacts): Array<{from:ArtifactVM; to:ArtifactVM; exposeLabel; consumeLabel; note}>` —— 按 `workspace:<id>` ref 匹配 `artifact.id`;悬空跳过。

- [ ] **Step 1: 追加失败测试**

```typescript
import { buildArtifacts, resolveDependencies } from '@/composables/projectVM'

describe('buildArtifacts', () => {
  it('连平台时含应用本体 + 工作区,各带跳转目标', () => {
    const project: any = { id: 7, platform_connected: true, platform_app_id: 'APP1', platform_app_name: '工单配置端', name: 'p' }
    const ws: any = [{ id: 'ws1', project_type: 'mobile-page', display_name: '移动端报修', status: 'building' }]
    const arts = buildArtifacts(project, ws)
    const app = arts.find(a => a.mode === 'build')!
    expect(app.target).toEqual({ path: '/chat', query: { project_id: '7' } })
    const w = arts.find(a => a.id === 'workspace:ws1')!
    expect(w.mode).toBe('lowcode')
    expect(w.summary).toBe('移动端页面')
    expect(w.status).toEqual({ label: '构建中', tone: 'building' })
    expect(w.target).toEqual({ path: '/coding', query: { workspace_id: 'ws1' } })
  })
  it('未连平台 → 无应用本体', () => {
    const arts = buildArtifacts({ id: 1, platform_connected: false } as any, [])
    expect(arts.length).toBe(0)
  })
})

describe('resolveDependencies', () => {
  it('按 ref 匹配产物,悬空跳过', () => {
    const arts = buildArtifacts({ id: 1, platform_connected: false } as any,
      [{ id: 'a', project_type: 'form-list', status: 'ready' } as any,
       { id: 'b', project_type: 'mobile-page', status: 'ready' } as any])
    const edges = [
      { from_ref: 'workspace:a', to_ref: 'workspace:b', expose_label: 'X', consume_label: 'Y', note: 'n' },
      { from_ref: 'workspace:a', to_ref: 'workspace:gone', expose_label: 'X', consume_label: 'Y', note: '' },
    ]
    const out = resolveDependencies(edges, arts)
    expect(out.length).toBe(1)
    expect(out[0].from.id).toBe('workspace:a')
    expect(out[0].to.id).toBe('workspace:b')
    expect(out[0].exposeLabel).toBe('X')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/composables/projectVM.spec.ts`
Expected: FAIL —— `buildArtifacts`/`resolveDependencies` 未定义。

- [ ] **Step 3: 实现(追加到 `projectVM.ts`)**

```typescript
export function buildArtifacts(
  project: Record<string, any>,
  workspaces: Array<Record<string, any>>,
): ArtifactVM[] {
  const out: ArtifactVM[] = []
  if (project?.platform_connected && project?.platform_app_id) {
    out.push({
      id: `app:${project.platform_app_id}`,
      name: project.platform_app_name || project.name || '低代码应用',
      mode: 'build',
      summary: '低代码应用',
      status: normalizeArtifactStatus(project.platform_connected ? 'deployed' : 'draft'),
      target: { path: '/chat', query: { project_id: String(project.id) } },
    })
  }
  for (const w of workspaces || []) {
    out.push({
      id: `workspace:${w.id}`,
      name: w.display_name || w.project_name || String(w.id),
      mode: projectTypeToMode(w.project_type),
      summary: projectTypeToLabel(w.project_type),
      status: normalizeArtifactStatus(w.status),
      target: { path: '/coding', query: { workspace_id: String(w.id) } },
    })
  }
  return out
}

export interface ResolvedEdge {
  from: ArtifactVM; to: ArtifactVM
  exposeLabel: string; consumeLabel: string; note: string
}
export function resolveDependencies(
  edges: Array<Record<string, any>>,
  artifacts: ArtifactVM[],
): ResolvedEdge[] {
  const byId = new Map(artifacts.map(a => [a.id, a]))
  const out: ResolvedEdge[] = []
  for (const e of edges || []) {
    const from = byId.get(e.from_ref), to = byId.get(e.to_ref)
    if (!from || !to) continue
    out.push({ from, to, exposeLabel: e.expose_label || '', consumeLabel: e.consume_label || '', note: e.note || '' })
  }
  return out
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/composables/projectVM.spec.ts`
Expected: PASS(全部)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/composables/projectVM.ts frontend/src/composables/projectVM.spec.ts
git commit -m "feat(ia): buildArtifacts(应用+工作区→统一产物)+ resolveDependencies(边按 ref 解析)"
```

---

## Task 8: 前端 — `projectsApi.listDependencies`

**Files:**
- Modify: `frontend/src/api/projects.ts`

**Interfaces:**
- Produces: `interface ArtifactDependency { from_ref; to_ref; expose_label; consume_label; note }`;`projectsApi.listDependencies(id: number)`。

- [ ] **Step 1: 加类型 + 方法**(在 `projects.ts`,`ProjectMember` 类型旁加 interface;`projectsApi` 对象里 `listMembers` 后加方法)

```typescript
export interface ArtifactDependency {
  from_ref: string
  to_ref: string
  expose_label: string
  consume_label: string
  note: string
}
```

```typescript
  /** 列出项目的跨产物依赖边 */
  listDependencies(id: number) {
    return request.get<any, ArtifactDependency[]>(`/projects/${id}/dependencies`)
  },
```

- [ ] **Step 2: 类型检查通过**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep projects.ts || echo "no projects.ts type errors"`
Expected: `no projects.ts type errors`(注:仓库 build 预存其他类型错,只看本文件)

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/projects.ts
git commit -m "feat(api): projectsApi.listDependencies + ArtifactDependency 类型"
```

---

## Task 9: 前端 — `useProjectArtifacts` 数据编排

**Files:**
- Create: `frontend/src/composables/useProjectArtifacts.ts`
- Test: `frontend/src/composables/useProjectArtifacts.spec.ts`

**Interfaces:**
- Consumes: Task 6/7 的 `buildArtifacts`/`resolveDependencies`;Task 8 的 `projectsApi`(注入)。
- Produces:
  - `buildProjectView(projectId: number, api): Promise<{project; groups; dependencies; members; error}>` —— 核心可注入 api 的纯编排(并行拉、各自降级、分组)。`groups: Array<{mode: Mode; label: string; artifacts: ArtifactVM[]}>`。
  - `useProjectArtifacts(projectId)` —— 薄 ref 包装(供组件用)。

- [ ] **Step 1: 写失败测试(注入 fake api,无需 mount/DOM)**

```typescript
import { describe, it, expect } from 'vitest'
import { buildProjectView } from '@/composables/useProjectArtifacts'

const fakeApi = {
  get: async () => ({ id: 7, name: 'p', platform_connected: false, created_at: '2026-06-20' }),
  listWorkspaces: async () => ([{ id: 'a', project_type: 'form-list', status: 'ready' },
                                { id: 'b', project_type: 'mobile-page', status: 'building' }]),
  listMembers: async () => ([{ id: 1, role: 'owner' }]),
  listDependencies: async () => ([{ from_ref: 'workspace:a', to_ref: 'workspace:b', expose_label: 'X', consume_label: 'Y', note: 'n' }]),
}

describe('buildProjectView', () => {
  it('并行拉+分组+解析依赖', async () => {
    const r = await buildProjectView(7, fakeApi as any)
    expect(r.project.id).toBe(7)
    expect(r.members.length).toBe(1)
    expect(r.groups.find(g => g.mode === 'lowcode')!.artifacts.length).toBe(2)
    expect(r.dependencies.length).toBe(1)
    expect(r.error).toBeNull()
  })
  it('某请求失败 → 该块降级,不整崩', async () => {
    const partial = { ...fakeApi, listMembers: async () => { throw new Error('boom') },
                      listDependencies: async () => { throw new Error('boom') } }
    const r = await buildProjectView(7, partial as any)
    expect(r.members).toEqual([])
    expect(r.dependencies).toEqual([])
    expect(r.groups.length).toBeGreaterThan(0)   // 工作区仍在
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/composables/useProjectArtifacts.spec.ts`
Expected: FAIL —— 模块不存在。

- [ ] **Step 3: 实现**

```typescript
import { ref } from 'vue'
import { projectsApi } from '@/api/projects'
import { buildArtifacts, resolveDependencies, type ArtifactVM, type Mode } from '@/composables/projectVM'

const MODE_GROUP_LABEL: Record<Mode, string> = {
  build: '低代码产物 · Builder', lowcode: '低代码二开 · Builder',
  fullcode: '全代码产物 · Code', agent: '智能体 · Agent',
}
const MODE_ORDER: Mode[] = ['build', 'lowcode', 'fullcode', 'agent']

async function safe<T>(p: Promise<T>, fallback: T): Promise<T> {
  try { return await p } catch { return fallback }
}

export async function buildProjectView(projectId: number, api = projectsApi) {
  const [project, workspaces, members, edges] = await Promise.all([
    safe(api.get(projectId), null as any),
    safe(api.listWorkspaces(projectId), [] as any[]),
    safe(api.listMembers(projectId), [] as any[]),
    safe(api.listDependencies(projectId), [] as any[]),
  ])
  const artifacts = project ? buildArtifacts(project, workspaces) : []
  const groups = MODE_ORDER
    .map(mode => ({ mode, label: MODE_GROUP_LABEL[mode], artifacts: artifacts.filter(a => a.mode === mode) }))
    .filter(g => g.artifacts.length > 0)
  const dependencies = resolveDependencies(edges, artifacts)
  return { project, groups, members, dependencies, error: project ? null : 'not_found' as const }
}

export function useProjectArtifacts(projectId: number) {
  const project = ref<any>(null)
  const groups = ref<Array<{ mode: Mode; label: string; artifacts: ArtifactVM[] }>>([])
  const members = ref<any[]>([])
  const dependencies = ref<ReturnType<typeof resolveDependencies>>([])
  const loading = ref(true)
  const error = ref<string | null>(null)
  async function load() {
    loading.value = true
    const r = await buildProjectView(projectId)
    project.value = r.project; groups.value = r.groups
    members.value = r.members; dependencies.value = r.dependencies
    error.value = r.error
    loading.value = false
  }
  return { project, groups, members, dependencies, loading, error, load }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/composables/useProjectArtifacts.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/composables/useProjectArtifacts.ts frontend/src/composables/useProjectArtifacts.spec.ts
git commit -m "feat(ia): useProjectArtifacts 数据编排(并行拉+各自降级+模式分组+依赖解析)"
```

---

## Task 10: 前端 — `ArtifactCard.vue`

**Files:**
- Create: `frontend/src/components/project/ArtifactCard.vue`
- Test: `frontend/src/components/project/ArtifactCard.spec.ts`

**Interfaces:**
- Consumes: `ArtifactVM`(props `artifact`)。emit `open`(点击)。
- Produces: 单产物卡。模式色用 `--{mode}` / `--{mode}-bg`;状态点 + 文案并排,error 加 `!` 图标;名称 line-clamp 2,卡 min-height/min-width。

- [ ] **Step 1: 写失败测试(`?raw` 源码断言)**

```typescript
import { describe, it, expect } from 'vitest'
// @ts-ignore
import src from '@/components/project/ArtifactCard.vue?raw'

describe('ArtifactCard.vue', () => {
  it('用 artifact prop + 触发 open + 状态点带 aria-label', () => {
    expect(src).toContain('defineProps')
    expect(src).toContain('artifact')
    expect(src).toContain("emit('open'")
    expect(src).toContain('aria-label')
  })
  it('模式色用 css 变量 + 名称 line-clamp', () => {
    expect(src).toMatch(/var\(--\$\{|var\(--' \+|--build|mode/)  // 模式驱动的色
    expect(src).toContain('line-clamp')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/project/ArtifactCard.spec.ts`
Expected: FAIL —— 文件不存在。

- [ ] **Step 3: 实现 `ArtifactCard.vue`**

```vue
<template>
  <button class="artifact-card" :style="{ '--m': `var(--${artifact.mode})`, '--mbg': `var(--${artifact.mode}-bg)` }"
          @click="emit('open', artifact)">
    <div class="ac-top">
      <span class="ac-icon" :style="{ background: 'var(--mbg)', color: 'var(--m)' }">◧</span>
      <span class="ac-mode" :style="{ background: 'var(--mbg)', color: 'var(--m)' }">{{ modeLabel }}</span>
    </div>
    <div class="ac-name">{{ artifact.name }}</div>
    <div class="ac-summary">{{ artifact.summary }}</div>
    <div class="ac-status">
      <span class="ac-dot" :class="`tone-${artifact.status.tone}`"
            :aria-label="artifact.status.label" :title="artifact.status.label"></span>
      <span v-if="artifact.status.tone === 'error'" class="ac-err" aria-hidden="true">!</span>
      <span class="ac-status-label">{{ artifact.status.label }}</span>
    </div>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ArtifactVM } from '@/composables/projectVM'
const props = defineProps<{ artifact: ArtifactVM }>()
const emit = defineEmits<{ (e: 'open', a: ArtifactVM): void }>()
const MODE_LABEL: Record<string, string> = { build: '构建', lowcode: '低代码二开', fullcode: 'Code', agent: 'Agent' }
const modeLabel = computed(() => MODE_LABEL[props.artifact.mode] || props.artifact.mode)
</script>

<style scoped>
.artifact-card { display:flex; flex-direction:column; gap:6px; text-align:left;
  min-height:80px; min-width:200px; padding:14px 16px; border:1px solid var(--line-2);
  border-radius:14px; background:var(--surface-2,#fff); cursor:pointer; }
.artifact-card:hover { border-color:var(--m); }
.ac-top { display:flex; justify-content:space-between; align-items:center; }
.ac-icon { width:28px; height:28px; border-radius:8px; display:grid; place-items:center; font-size:14px; }
.ac-mode { font-size:11px; padding:2px 8px; border-radius:8px; }
.ac-name { font-weight:600; font-size:14px; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.ac-summary { font-size:12px; color:var(--text-2,#888); }
.ac-status { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-2,#888); }
.ac-dot { width:7px; height:7px; border-radius:50%; background:var(--text-3,#bbb); }
.ac-dot.tone-building { background:#FBBF24; } .ac-dot.tone-live { background:#34D3E0; }
.ac-dot.tone-done { background:#4fb286; } .ac-dot.tone-error { background:#d9685e; }
.ac-dot.tone-draft { background:#9ba6af; }
.ac-err { color:#d9685e; font-weight:700; }
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/project/ArtifactCard.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/project/ArtifactCard.vue frontend/src/components/project/ArtifactCard.spec.ts
git commit -m "feat(ia): ArtifactCard 产物卡(模式色+状态点无障碍+名称截断)"
```

---

## Task 11: 前端 — `ArtifactGroup.vue`

**Files:**
- Create: `frontend/src/components/project/ArtifactGroup.vue`
- Test: `frontend/src/components/project/ArtifactGroup.spec.ts`

**Interfaces:**
- Consumes: Task 10 `ArtifactCard`;props `{ label: string; artifacts: ArtifactVM[] }`;转发 `open`。
- Produces: 一个模式组(标题 + 网格,`grid auto-fill minmax(200px,1fr)`,<600px 单列)。

- [ ] **Step 1: 写失败测试**

```typescript
import { describe, it, expect } from 'vitest'
// @ts-ignore
import src from '@/components/project/ArtifactGroup.vue?raw'

describe('ArtifactGroup.vue', () => {
  it('渲染 label + 遍历 artifacts 用 ArtifactCard + 网格', () => {
    expect(src).toContain('ArtifactCard')
    expect(src).toContain('v-for')
    expect(src).toContain('label')
    expect(src).toContain('minmax(200px')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/project/ArtifactGroup.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

```vue
<template>
  <section class="artifact-group">
    <header class="ag-head"><h3 class="ag-label">{{ label }}</h3></header>
    <div class="ag-grid">
      <ArtifactCard v-for="a in artifacts" :key="a.id" :artifact="a" @open="emit('open', $event)" />
    </div>
  </section>
</template>

<script setup lang="ts">
import ArtifactCard from './ArtifactCard.vue'
import type { ArtifactVM } from '@/composables/projectVM'
defineProps<{ label: string; artifacts: ArtifactVM[] }>()
const emit = defineEmits<{ (e: 'open', a: ArtifactVM): void }>()
</script>

<style scoped>
.artifact-group { margin-bottom:28px; }
.ag-label { font-size:13px; color:var(--text-2,#888); margin-bottom:12px; font-weight:600; }
.ag-grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); }
@media (max-width:600px){ .ag-grid { grid-template-columns:1fr; } }
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/project/ArtifactGroup.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/project/ArtifactGroup.vue frontend/src/components/project/ArtifactGroup.spec.ts
git commit -m "feat(ia): ArtifactGroup 模式分组网格(响应式单列退化)"
```

---

## Task 12: 前端 — `ArtifactDependencyGraph.vue`

**Files:**
- Create: `frontend/src/components/project/ArtifactDependencyGraph.vue`
- Test: `frontend/src/components/project/ArtifactDependencyGraph.spec.ts`

**Interfaces:**
- Consumes: Task 7 `ResolvedEdge[]`(prop `edges`)。
- Produces: 线性依赖列表(from-chip → 箭头+expose/consume 标签 → to-chip,note 行);`edges` 空 → 整块不渲染;>6 折叠;标签 line-clamp。

- [ ] **Step 1: 写失败测试**

```typescript
import { describe, it, expect } from 'vitest'
// @ts-ignore
import src from '@/components/project/ArtifactDependencyGraph.vue?raw'

describe('ArtifactDependencyGraph.vue', () => {
  it('空边不渲染 + 遍历 edges + 显 note', () => {
    expect(src).toContain('v-if')          // 空时隐藏
    expect(src).toContain('edges')
    expect(src).toContain('v-for')
    expect(src).toContain('note')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/project/ArtifactDependencyGraph.spec.ts`
Expected: FAIL

- [ ] **Step 3: 实现**

```vue
<template>
  <section v-if="edges.length" class="dep-graph">
    <h3 class="dg-title">跨产物依赖</h3>
    <div v-for="(e, i) in shown" :key="i" class="dg-edge">
      <div class="dg-row">
        <span class="dg-chip" :style="chip(e.from.mode)">{{ e.from.name }}</span>
        <span class="dg-flow">
          <span class="dg-label">{{ e.exposeLabel }}</span>
          <span class="dg-arrow">→</span>
          <span class="dg-label">{{ e.consumeLabel }}</span>
        </span>
        <span class="dg-chip" :style="chip(e.to.mode)">{{ e.to.name }}</span>
      </div>
      <div v-if="e.note" class="dg-note">⚠ {{ e.note }}</div>
    </div>
    <button v-if="edges.length > LIMIT && !expanded" class="dg-more" @click="expanded = true">
      展开其余 {{ edges.length - LIMIT }} 条
    </button>
  </section>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ResolvedEdge } from '@/composables/projectVM'
const props = defineProps<{ edges: ResolvedEdge[] }>()
const LIMIT = 6
const expanded = ref(false)
const shown = computed(() => props.expanded ? props.edges : props.edges.slice(0, LIMIT))
function chip(mode: string) { return { background: `var(--${mode}-bg)`, color: `var(--${mode})` } }
</script>

<style scoped>
.dep-graph { margin-top:8px; padding:16px; border:1px solid var(--line-2); border-radius:14px; background:var(--surface-2,#fff); }
.dg-title { font-size:13px; color:var(--text-2,#888); margin-bottom:12px; font-weight:600; }
.dg-edge { padding:10px 0; border-top:1px solid var(--line-1, #eee); }
.dg-edge:first-of-type { border-top:none; }
.dg-row { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.dg-chip { padding:4px 10px; border-radius:8px; font-size:12px; font-weight:600; }
.dg-flow { display:flex; align-items:center; gap:6px; font-size:11px; color:var(--text-2,#888); }
.dg-label { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.dg-note { margin-top:6px; font-size:12px; color:#d9a441; }
.dg-more { margin-top:8px; font-size:12px; background:none; border:none; color:var(--m,#7C8CFF); cursor:pointer; }
</style>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/project/ArtifactDependencyGraph.spec.ts`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/project/ArtifactDependencyGraph.vue frontend/src/components/project/ArtifactDependencyGraph.spec.ts
git commit -m "feat(ia): ArtifactDependencyGraph 线性依赖列表(空隐藏/折叠/标签截断)"
```

---

## Task 13: 前端 — `ProjectOverview.vue` 重写编排

**Files:**
- Modify: `frontend/src/views/ProjectOverview.vue`
- Test: `frontend/src/views/ProjectOverview.spec.ts`(新增 `?raw`)

**Interfaces:**
- Consumes: Task 9 `useProjectArtifacts`;Task 11 `ArtifactGroup`;Task 12 `ArtifactDependencyGraph`。
- Produces: 页面 = Header(面包屑+成员N+溢出菜单,页内段)+ Hero(meta loading 显「—」)+ groups(loading 显 skeleton)+ 依赖图 + 空/错误态 + 点产物用 `artifact.target` 路由跳转 + 置灰动作按钮带 tooltip。

- [ ] **Step 1: 写失败测试**

```typescript
import { describe, it, expect } from 'vitest'
// @ts-ignore
import src from '@/views/ProjectOverview.vue?raw'

describe('ProjectOverview.vue 重写', () => {
  it('用 useProjectArtifacts + ArtifactGroup + 依赖图', () => {
    expect(src).toContain('useProjectArtifacts')
    expect(src).toContain('ArtifactGroup')
    expect(src).toContain('ArtifactDependencyGraph')
  })
  it('点产物用 artifact.target 跳转', () => {
    expect(src).toContain('.target')
    expect(src).toContain('router.push')
  })
  it('置灰动作 tooltip 文案 + loading 骨架 + 空态', () => {
    expect(src).toContain('即将支持')
    expect(src).toMatch(/skeleton|loading/)
    expect(src).toContain('还没有产物')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/views/ProjectOverview.spec.ts`
Expected: FAIL

- [ ] **Step 3: 重写 `ProjectOverview.vue`**

完整替换 `<template>` 与 `<script setup>`(保留路由参数读取 `projectId`、`ThemeToggle`、settings 入口;删旧 entry-cards/workspace 列表渲染,改用新组件)。模板骨架:

```vue
<template>
  <div class="project-overview">
    <!-- #header (页内段,不抽组件) -->
    <header class="po-header">
      <div class="header-left">
        <button class="back-btn" @click="router.push('/')" title="返回">‹</button>
        <nav class="crumb"><span>项目</span><b>{{ project?.name || '加载中…' }}</b></nav>
      </div>
      <div class="header-right">
        <span class="members">成员 {{ members.length }}</span>
        <ThemeToggle />
        <button class="settings-btn" @click="openSettings" title="应用设置">⚙</button>
      </div>
    </header>

    <div class="po-scroll"><div class="po-content">
      <!-- #hero 段 -->
      <section class="po-hero">
        <div class="hero-icon">▣</div>
        <div>
          <h1 class="hero-name">{{ project?.name || '加载中…' }}</h1>
          <p class="hero-desc" v-if="project?.description">{{ project.description }}</p>
          <div class="hero-meta">
            <span>{{ loading ? '—' : totalArtifacts }} 产物</span>
            <span>· {{ loading ? '—' : members.length }} 成员</span>
            <span v-if="project?.created_at">· {{ project.created_at.slice(0,10) }} 创建</span>
          </div>
        </div>
        <div class="hero-actions">
          <button class="ghost" disabled title="即将支持">重新部署</button>
          <button class="ghost" disabled title="即将支持:当前请在对话里发起多产物分解">新建产物</button>
        </div>
      </section>

      <!-- 错误态 -->
      <div v-if="error === 'not_found'" class="po-empty">项目不存在或无权限。</div>

      <!-- loading 骨架 -->
      <template v-else-if="loading">
        <div class="ag-grid">
          <div class="skeleton-card" v-for="i in 2" :key="i" />
          <div class="skeleton-card" v-for="i in 2" :key="'b'+i" />
        </div>
      </template>

      <!-- 空态 -->
      <div v-else-if="!groups.length" class="po-empty">还没有产物。</div>

      <!-- 产物分组 + 依赖图 -->
      <template v-else>
        <ArtifactGroup v-for="g in groups" :key="g.mode" :label="g.label" :artifacts="g.artifacts" @open="openArtifact" />
        <ArtifactDependencyGraph :edges="dependencies" />
      </template>
    </div></div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ThemeToggle from '@/components/ThemeToggle.vue'        // 路径以现有为准
import ArtifactGroup from '@/components/project/ArtifactGroup.vue'
import ArtifactDependencyGraph from '@/components/project/ArtifactDependencyGraph.vue'
import { useProjectArtifacts } from '@/composables/useProjectArtifacts'
import type { ArtifactVM } from '@/composables/projectVM'

const route = useRoute()
const router = useRouter()
const projectId = Number(route.params.id)
const { project, groups, members, dependencies, loading, error, load } = useProjectArtifacts(projectId)
const totalArtifacts = computed(() => groups.value.reduce((n, g) => n + g.artifacts.length, 0))

function openArtifact(a: ArtifactVM) { router.push(a.target) }
function openSettings() { router.push(`/project/${projectId}/git`) }   // 沿用现有设置入口

onMounted(load)
</script>
```

> 注:`ThemeToggle` 与 `openSettings` 目标路径以现有 `ProjectOverview.vue` 为准(实现时对照原文件 import 路径);CSS 复用原文件已有变量类,新增 `.po-hero/.skeleton-card/.po-empty` 等样式。

- [ ] **Step 4: 跑测试确认通过 + 全前端单测**

Run: `cd frontend && npx vitest run src/views/ProjectOverview.spec.ts && npx vitest run src/composables src/components/project`
Expected: PASS(全部)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/ProjectOverview.vue frontend/src/views/ProjectOverview.spec.ts
git commit -m "feat(ia): ProjectOverview 重写为产物视图(分组+依赖图+loading/空/错误态+导航)"
```

---

## Task 14: 端到端真验(验收门)

**Files:** 无(验证任务)

- [ ] **Step 1: 重启后端**(改后端必重启,`run.py` reload=False)

Run: 重启 `backend/run.py` 进程。

- [ ] **Step 2: 跑后端全量相关测试**

Run: `cd backend && python -m pytest tests/test_decompose_deps.py tests/test_decompose_parse.py tests/test_decompose_llm.py tests/test_orchestrate.py tests/test_orchestrate_deps.py tests/test_artifact_dependency_model.py tests/test_projects_dependencies_route.py -v`
Expected: 全 PASS。

- [ ] **Step 3: 本地真跑一次多产物分解**(tenant1 gpt-5.5 omnigate,preview 库 /tmp/fb_demo.db)

发一个明确两端请求(如「做招聘系统,管理端 HR 管职位/候选人,用户端求职者浏览职位+投递」),走 `run_coding_entry`→`run_multi_artifact`。确认:生成 ≥2 产物挂同一 Project + `project_artifact_dependencies` 表里有边(若 LLM 声明了)。

Run(核对库):`sqlite3 /tmp/fb_demo.db "select project_id,from_ref,to_ref,expose_label from project_artifact_dependencies;"`
Expected: 有行(从 ref 形如 `workspace:<id>`)。

- [ ] **Step 4: 预览验证前端**(preview workflow)

起 desktop/web 预览,进 `/project/<新项目id>`:确认产物按模式分组、状态徽标、依赖图显示(暴露→消费+note)、点产物分别跳 `/chat?project_id` 与 `/coding?workspace_id`。截图留证。

- [ ] **Step 5: 收尾提交(若验证中有小修)**

```bash
git add -A && git commit -m "test(ia): 项目→产物视图端到端验证 + 微调"
```

---

## Self-Review(对照 spec 自检)

**1. Spec 覆盖**:
- §3.1 projectTypeToMode → Task 6 ✓;§3.2 projectTypeToLabel → Task 6 ✓;§3.3 导航(/chat?project_id、/coding?workspace_id)→ Task 7 target + Task 13 ✓
- §4.1 新表 → Task 2 ✓;§4.2 parse_dependencies + decompose 返回 → Task 1 ✓;§4.3 orchestrate 落库 → Task 3 ✓;§4.4 读接口 + listDependencies → Task 4 + Task 8 ✓;§4.5 v1 仅 workspace↔workspace → Task 3 ref 解析 ✓
- §5.1 组件边界(Header/Hero 不抽组件)→ Task 13 页内段 ✓;§5.2 useProjectArtifacts → Task 9 ✓;§5.3 状态归一 → Task 6 ✓;§5.4 渲染细节(截断/无障碍/loading/折叠/窄屏/tooltip)→ Task 10-13 ✓;§5.5 复用 token → Task 5 ✓
- §6 错误/边界 → Task 9(各自降级)+ Task 13(空/错误态)✓;§7 测试 → 各任务 TDD + Task 14 ✓

**2. 占位扫描**:无 TBD/TODO;每个代码步给了完整代码。两处「以现有为准」(require_project_access 参数、ThemeToggle/openSettings 路径)是对齐现有约定的实现注记,非占位 —— 实现者照原文件抄。

**3. 类型一致**:`ArtifactVM`(Task6)被 Task7/9/10 一致引用;`ResolvedEdge`(Task7)被 Task12 引用;`buildProjectView` 返回 `{project,groups,members,dependencies,error}` 与 Task9 测试、Task13 解构一致;后端 `dep_writer(project_id, edges)` 的 edge 键(from_ref/to_ref/expose_label/consume_label/note)在 Task3 写入与 Task4 `_dep_to_dict` 读出一致。

---

## Execution Handoff

(见 spec §8:这是 5 块拆分的第 2 块;实现完即第一块可上手验证视觉语言。)
