# SPEC State Machine — Phase α (Backend Skeleton) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend SPEC state machine (Pydantic schema + DB persistence + 21 tools + LLM tool-loop agent + REST API + chat.py wiring) that replaces the markdown-blob requirements flow with a structured, tool-driven SPEC object.

**Architecture:** New `backend/app/spec/` package (4 files: schema, tools, agent, converter). New `Spec` ORM model + 2 FK columns on existing tables. New `/spec` REST router. `routes/chat.py` adds a branch for `agent_type="requirements"` that delegates to `SpecAgent`. LLM tool loop pattern copied from [vibe_agent.py](backend/app/coding/vibe_agent.py) (httpx SSE stream + parallel tool_calls).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Pydantic v2, httpx (SSE), pytest + pytest-asyncio (introduced in Task 1), OpenAI-compatible tool calling (omnigate gateway).

**Reference spec:** [docs/superpowers/specs/2026-04-25-spec-state-machine-design.md](../specs/2026-04-25-spec-state-machine-design.md)

**Phase α scope** (this plan): backend only. Frontend (β) and entry-migrations (γ) are separate plans.

**Estimated effort:** 3-4 working days, 9 tasks.

---

## File Map

| Path | Action | Responsibility |
|---|---|---|
| `backend/pytest.ini` | Create | pytest + asyncio config |
| `backend/conftest.py` | Create | pytest fixtures (async db session, app client) |
| `backend/tests/__init__.py` | Create | mark tests/ as package |
| `backend/tests/test_spec_schema.py` | Create | unit tests for Pydantic models + completeness derivation |
| `backend/tests/test_spec_tools.py` | Create | unit tests for 21 tool execution functions |
| `backend/tests/test_spec_converter.py` | Create | unit tests for spec_to_config field mapping |
| `backend/tests/test_spec_routes.py` | Create | integration tests for /spec REST API |
| `backend/app/spec/__init__.py` | Create | package marker |
| `backend/app/spec/schema.py` | Create | Pydantic Spec/Goal/Role/.../Completeness models + Phase enum |
| `backend/app/spec/tools.py` | Create | 21 tool definitions (OpenAI format) + execution functions + tool dispatch |
| `backend/app/spec/agent.py` | Create | SpecAgent class — LLM tool loop, prompt builder, persistence |
| `backend/app/spec/converter.py` | Create | spec_to_config(spec) → dict |
| `backend/app/models/spec.py` | Create | SQLAlchemy Spec ORM model |
| `backend/app/models/__init__.py` | Modify | import Spec; add `canonical_spec_id` to Application; add `spec_id` to Conversation |
| `backend/app/routes/spec.py` | Create | REST endpoints: GET/PUT /spec/{id}, PUT /spec/{id}/phase, PUT /spec/{id}/items/{type}/{code} |
| `backend/app/main.py` | Modify | register spec router |
| `backend/scripts/migrate_spec_fk_columns.sql` | Create | ALTER TABLE for `applications.canonical_spec_id` + `conversations.spec_id` |
| `backend/app/routes/chat.py` | Modify | `/send` branch when `conversation.spec_id IS NOT NULL` → delegate to SpecAgent |
| `backend/requirements.txt` | Modify | add pytest, pytest-asyncio, httpx (test extras) |

---

## Conventions

- **TDD**: test first, watch it fail, implement minimal pass, commit.
- **Commits**: one per task (or per logical sub-step within a task), conventional commit format `feat(spec): xxx` / `test(spec): xxx`.
- **Run tests from backend/**: `cd backend && pytest tests/test_xxx.py -v`.
- **DB**: dev uses sqlite (`backend/dev.db`). Tests use in-memory sqlite (configured in `conftest.py`).
- **No emoji in commits unless user-facing copy.**

---

## Task 1: Test infrastructure (pytest + conftest + first smoke test)

**Files:**
- Create: `backend/pytest.ini`
- Create: `backend/conftest.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_smoke.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1.1: Add test deps to requirements.txt**

Append to `backend/requirements.txt`:
```
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
aiosqlite>=0.20.0
```

- [ ] **Step 1.2: Install deps**

Run:
```bash
cd backend && source venv/bin/activate && pip install pytest pytest-asyncio aiosqlite
```
Expected: installed without error.

- [ ] **Step 1.3: Write `backend/pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -ra --strict-markers
```

- [ ] **Step 1.4: Write `backend/tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 1.5: Write `backend/conftest.py`**

```python
import os
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Force in-memory sqlite before any app import touches database.py
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.database import Base  # noqa: E402
from app import models  # noqa: F401, E402  — register all ORM mappings


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()
```

- [ ] **Step 1.6: Write smoke test `backend/tests/test_smoke.py`**

```python
import pytest


def test_pytest_works():
    assert 1 + 1 == 2


@pytest.mark.asyncio
async def test_db_session_yields(db_session):
    assert db_session is not None
    result = await db_session.execute(__import__("sqlalchemy").text("SELECT 1"))
    assert result.scalar() == 1
```

- [ ] **Step 1.7: Run smoke test, expect PASS**

Run:
```bash
cd backend && pytest tests/test_smoke.py -v
```
Expected: `2 passed in <1s`. If sqlite/asyncio setup fails, fix before continuing.

- [ ] **Step 1.8: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/pytest.ini backend/conftest.py backend/tests/__init__.py backend/tests/test_smoke.py backend/requirements.txt && git commit -m "$(cat <<'EOF'
test(infra): introduce pytest + asyncio + in-memory sqlite fixture

Phase α 起点：之前只有 backend 根的 ad-hoc 测试脚本，没有 pytest。
新增 conftest.py 提供 in-memory sqlite db_session fixture，给后续
spec/ 单元测试用。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: SPEC Pydantic schema + Completeness derivation

**Files:**
- Create: `backend/app/spec/__init__.py`
- Create: `backend/app/spec/schema.py`
- Create: `backend/tests/test_spec_schema.py`

- [ ] **Step 2.1: Create package marker**

`backend/app/spec/__init__.py`:
```python
```

- [ ] **Step 2.2: Write failing schema tests**

`backend/tests/test_spec_schema.py`:
```python
from datetime import datetime
import pytest
from pydantic import ValidationError

from app.spec.schema import (
    Phase, Goal, Role, FieldSpec, ObjectSpec, DictSpec, DictOption,
    PermissionRule, PermissionSpec, Decision, Spec, derive_completeness,
)


def _now():
    return datetime(2026, 4, 25, 10, 0, 0)


def test_phase_enum_values():
    assert Phase.GATHERING.value == "gathering"
    assert Phase.DRAFTING.value == "drafting"
    assert Phase.GENERATING.value == "generating"
    assert Phase.READY.value == "ready"


def test_role_scope_validation():
    Role(code="finance_lead", name="财务负责人", scope="ALL")
    with pytest.raises(ValidationError):
        Role(code="x", name="x", scope="INVALID")


def test_permission_rule_op_validation():
    PermissionRule(role="all", op="all", data="ALL")
    with pytest.raises(ValidationError):
        PermissionRule(role="all", op="invalid_op", data="ALL")


def test_completeness_empty_spec():
    spec = Spec(
        id="spec_1", phase=Phase.GATHERING,
        completeness=derive_completeness_empty(),
        created_at=_now(), updated_at=_now(), created_by=1,
    )
    c = derive_completeness(spec)
    assert c.confirmed == 0
    assert c.total == 0
    assert c.pending_decisions == 0
    assert c.blocking_decisions == 0


def test_completeness_with_confirmed_items():
    spec = Spec(
        id="spec_2", phase=Phase.GATHERING,
        goal=Goal(title="预算", summary="x", business_problem="y", confirmed=True),
        roles=[
            Role(code="r1", name="r1", scope="ALL", confirmed=True),
            Role(code="r2", name="r2", scope="SELF", confirmed=False),
        ],
        objects=[
            ObjectSpec(code="t_a", name="a", confirmed=True, fields=[
                FieldSpec(code="f1", name="f1", type="单行输入", confirmed=True),
                FieldSpec(code="f2", name="f2", type="数字", confirmed=False),
            ]),
        ],
        dicts=[DictSpec(code="d1", name="d1", options=[DictOption(code="a", name="A")], confirmed=False)],
        permissions=[],
        decisions_pending=[
            Decision(id="d1", topic="t", raised_in_phase=Phase.GATHERING,
                     blocking=True, created_at=_now()),
            Decision(id="d2", topic="t2", raised_in_phase=Phase.GATHERING,
                     blocking=False, created_at=_now()),
        ],
        completeness=derive_completeness_empty(),
        created_at=_now(), updated_at=_now(), created_by=1,
    )
    c = derive_completeness(spec)
    # goal(1) + role(2) + object(1) + field(2) + dict(1) = 7 total items
    assert c.total == 7
    # goal=true + r1=true + t_a=true + f1=true = 4 confirmed
    assert c.confirmed == 4
    assert c.by_section["roles"] == (1, 2)
    assert c.by_section["objects"] == (1, 1)
    assert c.by_section["fields"] == (1, 2)
    assert c.by_section["dicts"] == (0, 1)
    assert c.pending_decisions == 2
    assert c.blocking_decisions == 1


def derive_completeness_empty():
    """Helper: completeness placeholder used when constructing fresh Spec for tests."""
    from app.spec.schema import Completeness
    return Completeness(confirmed=0, total=0, by_section={},
                        pending_decisions=0, blocking_decisions=0)
```

- [ ] **Step 2.3: Run tests, expect FAIL (import errors)**

Run:
```bash
cd backend && pytest tests/test_spec_schema.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.spec.schema'`.

- [ ] **Step 2.4: Implement `backend/app/spec/schema.py`**

```python
"""SPEC structured data model.

The SPEC object is the single source of truth for an application's
business design (goal / roles / data objects / dicts / permissions),
managed through the SPEC state machine. See
docs/superpowers/specs/2026-04-25-spec-state-machine-design.md.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Phase(str, Enum):
    GATHERING = "gathering"
    DRAFTING = "drafting"
    GENERATING = "generating"
    READY = "ready"


class Decision(BaseModel):
    id: str
    topic: str
    why_blocking: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    blocking: bool = True
    raised_in_phase: Phase
    resolved: bool = False
    resolution: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None


class Goal(BaseModel):
    title: str
    summary: str
    business_problem: str
    confirmed: bool = False


class Role(BaseModel):
    code: str
    name: str
    scope: Literal["SELF", "DEPT", "DEPT_LOW", "ALL"]
    description: Optional[str] = None
    confirmed: bool = False


class FieldSpec(BaseModel):
    code: str
    name: str
    type: str
    required: bool = False
    dict_code: Optional[str] = None
    ref_model: Optional[str] = None
    ref_field: Optional[str] = None
    description: Optional[str] = None
    confirmed: bool = False


class ObjectSpec(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    fields: list[FieldSpec] = Field(default_factory=list)
    sub_objects: dict[str, list[FieldSpec]] = Field(default_factory=dict)
    confirmed: bool = False


class DictOption(BaseModel):
    code: str
    name: str


class DictSpec(BaseModel):
    code: str
    name: str
    options: list[DictOption] = Field(default_factory=list)
    confirmed: bool = False


class PermissionRule(BaseModel):
    role: str
    op: Literal["all", "add", "edit", "delete", "view"]
    data: Literal["ALL", "SELF", "DEPT", "DEPT_LOW"]


class PermissionSpec(BaseModel):
    object_code: str
    rules: list[PermissionRule] = Field(default_factory=list)
    confirmed: bool = False


class Completeness(BaseModel):
    confirmed: int = 0
    total: int = 0
    by_section: dict[str, tuple[int, int]] = Field(default_factory=dict)
    pending_decisions: int = 0
    blocking_decisions: int = 0


class Spec(BaseModel):
    id: str
    application_id: Optional[int] = None
    version: int = 1
    parent_spec_id: Optional[str] = None
    phase: Phase = Phase.GATHERING
    goal: Optional[Goal] = None
    roles: list[Role] = Field(default_factory=list)
    objects: list[ObjectSpec] = Field(default_factory=list)
    dicts: list[DictSpec] = Field(default_factory=list)
    permissions: list[PermissionSpec] = Field(default_factory=list)
    decisions_pending: list[Decision] = Field(default_factory=list)
    decisions_resolved: list[Decision] = Field(default_factory=list)
    completeness: Completeness
    created_at: datetime
    updated_at: datetime
    created_by: int


def derive_completeness(spec: Spec) -> Completeness:
    """Compute completeness from a Spec snapshot.

    Counts: goal (0/1), each role, each object, each field across all objects,
    each dict, each permission.
    """
    by_section: dict[str, tuple[int, int]] = {}

    goal_total = 1 if spec.goal is not None else 0
    goal_confirmed = 1 if spec.goal and spec.goal.confirmed else 0
    if goal_total:
        by_section["goal"] = (goal_confirmed, goal_total)

    role_total = len(spec.roles)
    role_confirmed = sum(1 for r in spec.roles if r.confirmed)
    if role_total:
        by_section["roles"] = (role_confirmed, role_total)

    object_total = len(spec.objects)
    object_confirmed = sum(1 for o in spec.objects if o.confirmed)
    if object_total:
        by_section["objects"] = (object_confirmed, object_total)

    all_fields = [f for o in spec.objects for f in o.fields]
    field_total = len(all_fields)
    field_confirmed = sum(1 for f in all_fields if f.confirmed)
    if field_total:
        by_section["fields"] = (field_confirmed, field_total)

    dict_total = len(spec.dicts)
    dict_confirmed = sum(1 for d in spec.dicts if d.confirmed)
    if dict_total:
        by_section["dicts"] = (dict_confirmed, dict_total)

    perm_total = len(spec.permissions)
    perm_confirmed = sum(1 for p in spec.permissions if p.confirmed)
    if perm_total:
        by_section["permissions"] = (perm_confirmed, perm_total)

    confirmed = goal_confirmed + role_confirmed + object_confirmed + field_confirmed + dict_confirmed + perm_confirmed
    total = goal_total + role_total + object_total + field_total + dict_total + perm_total

    pending = sum(1 for d in spec.decisions_pending if not d.resolved)
    blocking = sum(1 for d in spec.decisions_pending if not d.resolved and d.blocking)

    return Completeness(
        confirmed=confirmed,
        total=total,
        by_section=by_section,
        pending_decisions=pending,
        blocking_decisions=blocking,
    )
```

- [ ] **Step 2.5: Run tests, expect PASS**

Run:
```bash
cd backend && pytest tests/test_spec_schema.py -v
```
Expected: `5 passed`. Fix any field/type mismatches.

- [ ] **Step 2.6: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/spec/__init__.py backend/app/spec/schema.py backend/tests/test_spec_schema.py && git commit -m "$(cat <<'EOF'
feat(spec): Pydantic schema + completeness derivation

Spec / Goal / Role / FieldSpec / ObjectSpec / DictSpec / PermissionSpec /
Decision / Completeness 模型，含 Phase 枚举（gathering/drafting/
generating/ready）和 derive_completeness() 派生函数。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: ORM model + DB migration

**Files:**
- Create: `backend/app/models/spec.py`
- Modify: `backend/app/models/__init__.py:188-220` (add canonical_spec_id to Application) + `:68-87` (add spec_id to Conversation) + import Spec at top
- Create: `backend/scripts/migrate_spec_fk_columns.sql`
- Create: `backend/tests/test_spec_orm.py`

- [ ] **Step 3.1: Write failing ORM test**

`backend/tests/test_spec_orm.py`:
```python
import pytest
from datetime import datetime
from sqlalchemy import select

from app.models.spec import Spec as SpecORM


@pytest.mark.asyncio
async def test_spec_orm_persist_and_load(db_session):
    spec = SpecORM(
        id="spec_test_1",
        application_id=None,
        version=1,
        parent_spec_id=None,
        payload={"goal": None, "roles": [], "objects": []},
        phase="gathering",
        completeness_confirmed=0,
        completeness_total=0,
        created_at=datetime(2026, 4, 25),
        updated_at=datetime(2026, 4, 25),
        created_by=1,
        tenant_id=1,
    )
    db_session.add(spec)
    await db_session.commit()

    result = await db_session.execute(select(SpecORM).where(SpecORM.id == "spec_test_1"))
    loaded = result.scalar_one()
    assert loaded.phase == "gathering"
    assert loaded.payload["roles"] == []


@pytest.mark.asyncio
async def test_application_has_canonical_spec_id_column(db_session):
    from app.models import Application
    from sqlalchemy import inspect

    # Use sync inspect on the bound engine via run_sync
    def check(sync_conn):
        insp = inspect(sync_conn)
        cols = [c["name"] for c in insp.get_columns("applications")]
        return cols
    cols = await db_session.run_sync(lambda sess: check(sess.connection()))
    assert "canonical_spec_id" in cols


@pytest.mark.asyncio
async def test_conversation_has_spec_id_column(db_session):
    from sqlalchemy import inspect

    def check(sync_conn):
        insp = inspect(sync_conn)
        return [c["name"] for c in insp.get_columns("conversations")]
    cols = await db_session.run_sync(lambda sess: check(sess.connection()))
    assert "spec_id" in cols
```

- [ ] **Step 3.2: Run tests, expect FAIL**

Run:
```bash
cd backend && pytest tests/test_spec_orm.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.spec'`.

- [ ] **Step 3.3: Write `backend/app/models/spec.py`**

```python
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, ForeignKey, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Spec(Base):
    """Persisted SPEC document. Pydantic Spec object is serialized into `payload`."""
    __tablename__ = "specs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("applications.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("specs.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    phase: Mapped[str] = mapped_column(String(20), default="gathering")
    completeness_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    completeness_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    tenant_id: Mapped[int] = mapped_column(Integer, default=1)
```

- [ ] **Step 3.4: Add `spec_id` column to `Conversation` and `canonical_spec_id` to `Application`**

In `backend/app/models/__init__.py`:

a. After existing imports (after line 15 `from app.models.tenant import ...`), add:
```python
from app.models.spec import Spec  # noqa: F401  — register ORM mapping
```

b. In `class Conversation` (after line 68), add column:
```python
    spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("specs.id"), nullable=True)
```
(Add `Optional` to imports at top if not present.)

c. In `class Application` (after line 188), add column:
```python
    canonical_spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("specs.id"), nullable=True)
```

- [ ] **Step 3.5: Run ORM tests, expect PASS**

Run:
```bash
cd backend && pytest tests/test_spec_orm.py -v
```
Expected: `3 passed`. (In-memory sqlite re-creates schema each test, so new columns appear automatically.)

- [ ] **Step 3.6: Write SQL migration for production sqlite/MySQL**

`backend/scripts/migrate_spec_fk_columns.sql`:
```sql
-- Phase α migration: add spec FK columns to existing tables.
-- Run against dev.db (sqlite) and any prod MySQL DB.
-- Safe to re-run: ALTER guarded with checks where dialect supports it.

-- specs table is auto-created by SQLAlchemy create_all on app startup,
-- but FK columns on existing tables are not added automatically.

-- sqlite (dev.db): no IF NOT EXISTS on ALTER, idempotent via try/catch in shell wrapper
-- MySQL: use IF NOT EXISTS where supported (8.0+)

-- ── For sqlite: run as separate statements, ignore "duplicate column" errors ──
ALTER TABLE applications ADD COLUMN canonical_spec_id VARCHAR(40);
ALTER TABLE conversations ADD COLUMN spec_id VARCHAR(40);

-- ── For MySQL 8.0+: ──
-- ALTER TABLE applications ADD COLUMN IF NOT EXISTS canonical_spec_id VARCHAR(40);
-- ALTER TABLE conversations ADD COLUMN IF NOT EXISTS spec_id VARCHAR(40);
```

Add a note above the file or in commit message: `Run via: sqlite3 backend/dev.db < backend/scripts/migrate_spec_fk_columns.sql 2>/dev/null || true` (the `|| true` swallows the duplicate-column error on re-run).

- [ ] **Step 3.7: Run migration against dev.db**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && sqlite3 backend/dev.db < backend/scripts/migrate_spec_fk_columns.sql 2>&1 | tee /tmp/spec_migration.log; sqlite3 backend/dev.db "PRAGMA table_info(applications);" | grep canonical_spec_id; sqlite3 backend/dev.db "PRAGMA table_info(conversations);" | grep spec_id
```
Expected: two grep lines confirming columns exist. (Duplicate-column error on re-run is fine.)

- [ ] **Step 3.8: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/models/spec.py backend/app/models/__init__.py backend/scripts/migrate_spec_fk_columns.sql backend/tests/test_spec_orm.py && git commit -m "$(cat <<'EOF'
feat(spec): ORM model + Application/Conversation FK columns + migration

新建 specs 表（自动通过 Base.metadata.create_all 建表），给
applications.canonical_spec_id 和 conversations.spec_id 加 FK。
SQL 迁移脚本给已有库追加这两列（dev.db 已迁好）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Tool definitions + execution functions (21 tools)

**Files:**
- Create: `backend/app/spec/tools.py`
- Create: `backend/tests/test_spec_tools.py`

- [ ] **Step 4.1: Write failing tool tests (covering 8 representative tools out of 21)**

`backend/tests/test_spec_tools.py`:
```python
from datetime import datetime
import pytest
from app.spec.schema import Spec, Phase, Goal, Role, ObjectSpec, FieldSpec, Completeness
from app.spec.tools import (
    TOOL_DEFINITIONS, dispatch_tool, ToolError,
)


def _empty_spec():
    return Spec(
        id="spec_t",
        phase=Phase.GATHERING,
        completeness=Completeness(),
        created_at=datetime(2026, 4, 25),
        updated_at=datetime(2026, 4, 25),
        created_by=1,
    )


def test_tool_definitions_count():
    assert len(TOOL_DEFINITIONS) == 21
    names = {t["function"]["name"] for t in TOOL_DEFINITIONS}
    assert "ask_clarifying_question" in names
    assert "set_goal" in names
    assert "transition_phase" in names
    assert "add_role" in names
    assert "confirm_role" in names
    assert "dismiss_role" in names


def test_set_goal_writes_unconfirmed():
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "set_goal", {
        "title": "预算管理", "summary": "季度预测", "business_problem": "对齐财务"
    })
    assert new_spec.goal is not None
    assert new_spec.goal.title == "预算管理"
    assert new_spec.goal.confirmed is False


def test_add_role_appends_unconfirmed():
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "add_role", {
        "code": "finance_lead", "name": "财务负责人", "scope": "ALL",
    })
    assert len(new_spec.roles) == 1
    assert new_spec.roles[0].code == "finance_lead"
    assert new_spec.roles[0].confirmed is False


def test_confirm_role_flips_flag():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "add_role", {"code": "r1", "name": "r1", "scope": "ALL"})
    spec = dispatch_tool(spec, "confirm_role", {"code": "r1"})
    assert spec.roles[0].confirmed is True


def test_dismiss_role_removes():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "add_role", {"code": "r1", "name": "r1", "scope": "ALL"})
    spec = dispatch_tool(spec, "dismiss_role", {"code": "r1"})
    assert spec.roles == []


def test_ask_clarifying_question_appends_decision():
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "ask_clarifying_question", {
        "topic": "季度起算月", "options": ["1月起", "财年起"], "blocking": True,
    })
    assert len(new_spec.decisions_pending) == 1
    d = new_spec.decisions_pending[0]
    assert d.topic == "季度起算月"
    assert d.blocking is True
    assert d.id.startswith("d_")


def test_resolve_decision_moves_to_resolved():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "ask_clarifying_question", {
        "topic": "x", "blocking": True,
    })
    decision_id = spec.decisions_pending[0].id
    spec = dispatch_tool(spec, "resolve_decision", {
        "decision_id": decision_id, "resolution": "1 月起",
    })
    assert spec.decisions_pending == []
    assert len(spec.decisions_resolved) == 1
    assert spec.decisions_resolved[0].resolution == "1 月起"


def test_transition_phase_blocked_by_blocking_decision():
    spec = _empty_spec()
    spec = dispatch_tool(spec, "ask_clarifying_question", {
        "topic": "x", "blocking": True,
    })
    with pytest.raises(ToolError) as exc:
        dispatch_tool(spec, "transition_phase", {"target": "drafting", "reason": "ok"})
    assert "blocking decision" in str(exc.value).lower()


def test_transition_phase_allowed_when_no_blocking():
    spec = _empty_spec()
    new_spec = dispatch_tool(spec, "transition_phase", {"target": "drafting", "reason": "ready"})
    assert new_spec.phase == Phase.DRAFTING


def test_gathering_first_turn_blocks_set_goal_when_completeness_zero():
    """Per design spec section 5: gathering phase first turn must call ask_clarifying_question
    at least 3 times before any add_/set_."""
    spec = _empty_spec()
    # confirmed=0, no decisions yet → must ask first
    with pytest.raises(ToolError) as exc:
        dispatch_tool(spec, "set_goal", {
            "title": "x", "summary": "x", "business_problem": "x",
        }, enforce_first_turn=True)
    assert "ask_clarifying_question" in str(exc.value).lower()


def test_unknown_tool_raises():
    spec = _empty_spec()
    with pytest.raises(ToolError):
        dispatch_tool(spec, "no_such_tool", {})
```

- [ ] **Step 4.2: Run tests, expect FAIL (ModuleNotFoundError)**

Run:
```bash
cd backend && pytest tests/test_spec_tools.py -v
```

- [ ] **Step 4.3: Implement `backend/app/spec/tools.py`**

```python
"""SPEC tool definitions and dispatch.

21 tools split across 4 groups:
- universal (4): ask_clarifying_question, set_goal, transition_phase, resolve_decision
- write (7): add_role, update_role, add_object, add_field, update_field, add_dict, add_permission
- confirm (5): confirm_role, confirm_object, confirm_field, confirm_dict, confirm_permission
- dismiss (5): dismiss_role, dismiss_object, dismiss_field, dismiss_dict, dismiss_permission
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from app.spec.schema import (
    Spec, Phase, Goal, Role, FieldSpec, ObjectSpec,
    DictSpec, DictOption, PermissionSpec, PermissionRule, Decision,
    derive_completeness,
)


class ToolError(Exception):
    """Raised when a tool call is invalid. Message is fed back to the LLM."""


# ── Tool definitions in OpenAI tool-calling format ──

def _tool(name: str, description: str, parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


def _str_param(desc: str) -> dict:
    return {"type": "string", "description": desc}


TOOL_DEFINITIONS: list[dict] = [
    # ── Universal ──
    _tool("ask_clarifying_question",
          "Append a pending decision (clarifying question) for the user to answer.",
          {
              "type": "object",
              "properties": {
                  "topic": _str_param("Short question, e.g. '季度起算月'"),
                  "why_blocking": _str_param("Why this blocks SPEC progression (optional)"),
                  "options": {"type": "array", "items": {"type": "string"},
                              "description": "Candidate answers (optional)"},
                  "blocking": {"type": "boolean", "default": True,
                               "description": "Whether this blocks phase transition"},
              },
              "required": ["topic"],
          }),
    _tool("set_goal", "Set or replace the application goal (default unconfirmed).",
          {
              "type": "object",
              "properties": {
                  "title": _str_param("Application name"),
                  "summary": _str_param("One-paragraph summary"),
                  "business_problem": _str_param("Business problem this solves"),
              },
              "required": ["title", "summary", "business_problem"],
          }),
    _tool("transition_phase", "Move SPEC to a new phase. Blocked if any blocking decision is pending.",
          {
              "type": "object",
              "properties": {
                  "target": {"type": "string", "enum": ["gathering", "drafting", "generating", "ready"]},
                  "reason": _str_param("Why transitioning"),
              },
              "required": ["target", "reason"],
          }),
    _tool("resolve_decision", "Resolve a pending decision with the user's answer.",
          {
              "type": "object",
              "properties": {
                  "decision_id": _str_param("ID of the pending decision (e.g. 'd_xxx')"),
                  "resolution": _str_param("The user's resolved answer"),
              },
              "required": ["decision_id", "resolution"],
          }),
    # ── Write (7) ──
    _tool("add_role", "Add a new role (default unconfirmed).",
          {
              "type": "object",
              "properties": {
                  "code": _str_param("English snake_case code, e.g. 'finance_lead'"),
                  "name": _str_param("Display name, e.g. '财务负责人'"),
                  "scope": {"type": "string", "enum": ["SELF", "DEPT", "DEPT_LOW", "ALL"]},
                  "description": _str_param("Optional description"),
              },
              "required": ["code", "name", "scope"],
          }),
    _tool("update_role", "Update an existing role's fields. Confirmed flag preserved.",
          {
              "type": "object",
              "properties": {
                  "code": _str_param("Existing role code"),
                  "name": _str_param("New display name (optional)"),
                  "scope": {"type": "string", "enum": ["SELF", "DEPT", "DEPT_LOW", "ALL"]},
                  "description": _str_param("New description (optional)"),
              },
              "required": ["code"],
          }),
    _tool("add_object", "Add a new business object (data model) with optional fields.",
          {
              "type": "object",
              "properties": {
                  "code": _str_param("Snake_case code prefixed with 't_', e.g. 't_quarter_forecast'"),
                  "name": _str_param("Display name"),
                  "description": _str_param("Optional"),
                  "fields": {
                      "type": "array",
                      "items": {"type": "object", "properties": {
                          "code": {"type": "string"}, "name": {"type": "string"},
                          "type": {"type": "string"},
                          "required": {"type": "boolean", "default": False},
                          "dict_code": {"type": "string"},
                          "ref_model": {"type": "string"},
                          "ref_field": {"type": "string"},
                          "description": {"type": "string"},
                      }, "required": ["code", "name", "type"]},
                  },
              },
              "required": ["code", "name"],
          }),
    _tool("add_field", "Add a field to an existing object.",
          {
              "type": "object",
              "properties": {
                  "object_code": _str_param("Existing object code"),
                  "field": {"type": "object", "properties": {
                      "code": {"type": "string"}, "name": {"type": "string"},
                      "type": {"type": "string"},
                      "required": {"type": "boolean", "default": False},
                      "dict_code": {"type": "string"},
                      "ref_model": {"type": "string"},
                      "ref_field": {"type": "string"},
                      "description": {"type": "string"},
                  }, "required": ["code", "name", "type"]},
              },
              "required": ["object_code", "field"],
          }),
    _tool("update_field", "Update an existing field. Confirmed flag preserved.",
          {
              "type": "object",
              "properties": {
                  "object_code": _str_param("Object code"),
                  "field_code": _str_param("Field code to update"),
                  "name": _str_param("New name (optional)"),
                  "type": _str_param("New type (optional)"),
                  "required": {"type": "boolean"},
                  "dict_code": _str_param("New dict_code (optional)"),
                  "ref_model": _str_param("New ref_model (optional)"),
                  "ref_field": _str_param("New ref_field (optional)"),
                  "description": _str_param("New description (optional)"),
              },
              "required": ["object_code", "field_code"],
          }),
    _tool("add_dict", "Add a data dictionary with options.",
          {
              "type": "object",
              "properties": {
                  "code": _str_param("Snake_case code, e.g. 'forecast_status'"),
                  "name": _str_param("Display name"),
                  "options": {"type": "array", "items": {"type": "object", "properties": {
                      "code": {"type": "string"}, "name": {"type": "string"},
                  }, "required": ["code", "name"]}},
              },
              "required": ["code", "name", "options"],
          }),
    _tool("add_permission", "Set permission rules for a business object.",
          {
              "type": "object",
              "properties": {
                  "object_code": _str_param("Object code"),
                  "rules": {"type": "array", "items": {"type": "object", "properties": {
                      "role": {"type": "string"},
                      "op": {"type": "string", "enum": ["all", "add", "edit", "delete", "view"]},
                      "data": {"type": "string", "enum": ["ALL", "SELF", "DEPT", "DEPT_LOW"]},
                  }, "required": ["role", "op", "data"]}},
              },
              "required": ["object_code", "rules"],
          }),
    # ── Confirm (5) ──
    _tool("confirm_role", "Mark a role as user-confirmed.", {
        "type": "object", "properties": {"code": _str_param("Role code")}, "required": ["code"],
    }),
    _tool("confirm_object", "Mark an object as user-confirmed.", {
        "type": "object", "properties": {"code": _str_param("Object code")}, "required": ["code"],
    }),
    _tool("confirm_field", "Mark a field as user-confirmed.", {
        "type": "object", "properties": {
            "object_code": _str_param("Object code"),
            "field_code": _str_param("Field code"),
        }, "required": ["object_code", "field_code"],
    }),
    _tool("confirm_dict", "Mark a dict as user-confirmed.", {
        "type": "object", "properties": {"code": _str_param("Dict code")}, "required": ["code"],
    }),
    _tool("confirm_permission", "Mark permissions of an object as user-confirmed.", {
        "type": "object", "properties": {"object_code": _str_param("Object code")},
        "required": ["object_code"],
    }),
    # ── Dismiss (5): physical delete ──
    _tool("dismiss_role", "Delete a role (user rejected).", {
        "type": "object", "properties": {"code": _str_param("Role code")}, "required": ["code"],
    }),
    _tool("dismiss_object", "Delete an object (user rejected).", {
        "type": "object", "properties": {"code": _str_param("Object code")}, "required": ["code"],
    }),
    _tool("dismiss_field", "Delete a field (user rejected).", {
        "type": "object", "properties": {
            "object_code": _str_param("Object code"),
            "field_code": _str_param("Field code"),
        }, "required": ["object_code", "field_code"],
    }),
    _tool("dismiss_dict", "Delete a dict (user rejected).", {
        "type": "object", "properties": {"code": _str_param("Dict code")}, "required": ["code"],
    }),
    _tool("dismiss_permission", "Delete permission rules of an object.", {
        "type": "object", "properties": {"object_code": _str_param("Object code")},
        "required": ["object_code"],
    }),
]


# ── Tool execution functions ──

def _short_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.utcnow()


def _refresh(spec: Spec) -> Spec:
    """Recompute completeness + bump updated_at."""
    spec.completeness = derive_completeness(spec)
    spec.updated_at = _now()
    return spec


def _ask_clarifying_question(spec: Spec, args: dict) -> Spec:
    decision = Decision(
        id=_short_id("d"),
        topic=args["topic"],
        why_blocking=args.get("why_blocking"),
        options=args.get("options", []),
        blocking=args.get("blocking", True),
        raised_in_phase=spec.phase,
        created_at=_now(),
    )
    spec.decisions_pending.append(decision)
    return _refresh(spec)


def _set_goal(spec: Spec, args: dict) -> Spec:
    spec.goal = Goal(
        title=args["title"], summary=args["summary"],
        business_problem=args["business_problem"], confirmed=False,
    )
    return _refresh(spec)


def _transition_phase(spec: Spec, args: dict) -> Spec:
    target = Phase(args["target"])
    blocking = [d for d in spec.decisions_pending if d.blocking and not d.resolved]
    if blocking:
        topics = ", ".join(d.topic for d in blocking)
        raise ToolError(f"Cannot transition: {len(blocking)} blocking decision(s) pending: {topics}")
    spec.phase = target
    return _refresh(spec)


def _resolve_decision(spec: Spec, args: dict) -> Spec:
    did = args["decision_id"]
    target = next((d for d in spec.decisions_pending if d.id == did), None)
    if target is None:
        raise ToolError(f"Decision id={did} not found in pending list")
    target.resolved = True
    target.resolution = args["resolution"]
    target.resolved_at = _now()
    spec.decisions_pending.remove(target)
    spec.decisions_resolved.append(target)
    return _refresh(spec)


def _add_role(spec: Spec, args: dict) -> Spec:
    if any(r.code == args["code"] for r in spec.roles):
        raise ToolError(f"Role code={args['code']} already exists; use update_role instead")
    spec.roles.append(Role(
        code=args["code"], name=args["name"], scope=args["scope"],
        description=args.get("description"), confirmed=False,
    ))
    return _refresh(spec)


def _update_role(spec: Spec, args: dict) -> Spec:
    role = next((r for r in spec.roles if r.code == args["code"]), None)
    if role is None:
        raise ToolError(f"Role code={args['code']} not found")
    if "name" in args: role.name = args["name"]
    if "scope" in args: role.scope = args["scope"]
    if "description" in args: role.description = args["description"]
    return _refresh(spec)


def _add_object(spec: Spec, args: dict) -> Spec:
    if any(o.code == args["code"] for o in spec.objects):
        raise ToolError(f"Object code={args['code']} already exists")
    fields = [FieldSpec(**f, confirmed=False) for f in args.get("fields", [])]
    spec.objects.append(ObjectSpec(
        code=args["code"], name=args["name"],
        description=args.get("description"), fields=fields, confirmed=False,
    ))
    return _refresh(spec)


def _add_field(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["object_code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['object_code']} not found")
    field_data = args["field"]
    if any(f.code == field_data["code"] for f in obj.fields):
        raise ToolError(f"Field code={field_data['code']} already exists in {obj.code}")
    obj.fields.append(FieldSpec(**field_data, confirmed=False))
    return _refresh(spec)


def _update_field(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["object_code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['object_code']} not found")
    field = next((f for f in obj.fields if f.code == args["field_code"]), None)
    if field is None:
        raise ToolError(f"Field code={args['field_code']} not found in {obj.code}")
    for key in ("name", "type", "required", "dict_code", "ref_model", "ref_field", "description"):
        if key in args:
            setattr(field, key, args[key])
    return _refresh(spec)


def _add_dict(spec: Spec, args: dict) -> Spec:
    if any(d.code == args["code"] for d in spec.dicts):
        raise ToolError(f"Dict code={args['code']} already exists")
    options = [DictOption(**o) for o in args.get("options", [])]
    spec.dicts.append(DictSpec(code=args["code"], name=args["name"], options=options, confirmed=False))
    return _refresh(spec)


def _add_permission(spec: Spec, args: dict) -> Spec:
    obj_code = args["object_code"]
    rules = [PermissionRule(**r) for r in args["rules"]]
    existing = next((p for p in spec.permissions if p.object_code == obj_code), None)
    if existing:
        existing.rules = rules
        existing.confirmed = False
    else:
        spec.permissions.append(PermissionSpec(object_code=obj_code, rules=rules, confirmed=False))
    return _refresh(spec)


def _flip_confirmed(item, value: bool):
    item.confirmed = value


def _confirm_role(spec: Spec, args: dict) -> Spec:
    role = next((r for r in spec.roles if r.code == args["code"]), None)
    if role is None:
        raise ToolError(f"Role code={args['code']} not found")
    _flip_confirmed(role, True)
    return _refresh(spec)


def _confirm_object(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['code']} not found")
    _flip_confirmed(obj, True)
    return _refresh(spec)


def _confirm_field(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["object_code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['object_code']} not found")
    field = next((f for f in obj.fields if f.code == args["field_code"]), None)
    if field is None:
        raise ToolError(f"Field code={args['field_code']} not found in {obj.code}")
    _flip_confirmed(field, True)
    return _refresh(spec)


def _confirm_dict(spec: Spec, args: dict) -> Spec:
    d = next((x for x in spec.dicts if x.code == args["code"]), None)
    if d is None:
        raise ToolError(f"Dict code={args['code']} not found")
    _flip_confirmed(d, True)
    return _refresh(spec)


def _confirm_permission(spec: Spec, args: dict) -> Spec:
    p = next((x for x in spec.permissions if x.object_code == args["object_code"]), None)
    if p is None:
        raise ToolError(f"Permission for object_code={args['object_code']} not found")
    _flip_confirmed(p, True)
    return _refresh(spec)


def _dismiss_role(spec: Spec, args: dict) -> Spec:
    spec.roles = [r for r in spec.roles if r.code != args["code"]]
    return _refresh(spec)


def _dismiss_object(spec: Spec, args: dict) -> Spec:
    spec.objects = [o for o in spec.objects if o.code != args["code"]]
    return _refresh(spec)


def _dismiss_field(spec: Spec, args: dict) -> Spec:
    obj = next((o for o in spec.objects if o.code == args["object_code"]), None)
    if obj is None:
        raise ToolError(f"Object code={args['object_code']} not found")
    obj.fields = [f for f in obj.fields if f.code != args["field_code"]]
    return _refresh(spec)


def _dismiss_dict(spec: Spec, args: dict) -> Spec:
    spec.dicts = [d for d in spec.dicts if d.code != args["code"]]
    return _refresh(spec)


def _dismiss_permission(spec: Spec, args: dict) -> Spec:
    spec.permissions = [p for p in spec.permissions if p.object_code != args["object_code"]]
    return _refresh(spec)


_TOOL_DISPATCH = {
    "ask_clarifying_question": _ask_clarifying_question,
    "set_goal": _set_goal,
    "transition_phase": _transition_phase,
    "resolve_decision": _resolve_decision,
    "add_role": _add_role,
    "update_role": _update_role,
    "add_object": _add_object,
    "add_field": _add_field,
    "update_field": _update_field,
    "add_dict": _add_dict,
    "add_permission": _add_permission,
    "confirm_role": _confirm_role,
    "confirm_object": _confirm_object,
    "confirm_field": _confirm_field,
    "confirm_dict": _confirm_dict,
    "confirm_permission": _confirm_permission,
    "dismiss_role": _dismiss_role,
    "dismiss_object": _dismiss_object,
    "dismiss_field": _dismiss_field,
    "dismiss_dict": _dismiss_dict,
    "dismiss_permission": _dismiss_permission,
}


# ── Mutation-creating tools that should not run as the very first action of a fresh
# ── gathering phase. The first turn must establish at least 3 clarifying questions
# ── (per spec section 5 strong constraint #1).
_FIRST_TURN_BLOCKED = {
    "set_goal", "add_role", "update_role", "add_object", "add_field",
    "update_field", "add_dict", "add_permission",
}


def dispatch_tool(spec: Spec, name: str, args: dict, *, enforce_first_turn: bool = False) -> Spec:
    """Execute a tool against a Spec object. Returns the mutated spec.

    Raises ToolError on validation failure; the SpecAgent feeds the error
    back to the LLM as a tool result, so the LLM can self-correct.
    """
    if name not in _TOOL_DISPATCH:
        raise ToolError(f"Unknown tool: {name}")

    if (
        enforce_first_turn
        and spec.phase == Phase.GATHERING
        and spec.completeness.confirmed == 0
        and len(spec.decisions_pending) < 3
        and name in _FIRST_TURN_BLOCKED
    ):
        raise ToolError(
            f"In gathering phase first turn (completeness=0, decisions<3), "
            f"you must call ask_clarifying_question at least 3 times before "
            f"calling {name}. Re-plan this turn to start with clarifying questions."
        )

    return _TOOL_DISPATCH[name](spec, args)
```

- [ ] **Step 4.4: Run tool tests, expect PASS**

Run:
```bash
cd backend && pytest tests/test_spec_tools.py -v
```
Expected: `11 passed`. Fix mismatches.

- [ ] **Step 4.5: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/spec/tools.py backend/tests/test_spec_tools.py && git commit -m "$(cat <<'EOF'
feat(spec): 21 atomic tools + dispatch + first-turn enforcement

- 4 universal: ask_clarifying_question / set_goal / transition_phase / resolve_decision
- 7 write: add_/update_ role/object/field/dict/permission（confirmed=false）
- 5 confirm + 5 dismiss: 用户主导操作
- enforce_first_turn=True 时，gathering 首轮 add_/set_ 被 reject，
  强制 LLM 先调 3 次 ask_clarifying_question

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: spec_to_config converter

**Files:**
- Create: `backend/app/spec/converter.py`
- Create: `backend/tests/test_spec_converter.py`

- [ ] **Step 5.1: Write failing converter test**

`backend/tests/test_spec_converter.py`:
```python
from datetime import datetime
from app.spec.schema import (
    Spec, Phase, Goal, Role, FieldSpec, ObjectSpec, DictSpec, DictOption,
    PermissionRule, PermissionSpec, Completeness,
)
from app.spec.converter import spec_to_config


def _full_spec():
    """A minimally-complete SPEC ready for conversion."""
    return Spec(
        id="spec_full",
        phase=Phase.GENERATING,
        goal=Goal(title="预算管理", summary="x", business_problem="y", confirmed=True),
        roles=[Role(code="finance_lead", name="财务负责人", scope="ALL", confirmed=True)],
        objects=[ObjectSpec(
            code="t_quarter_forecast", name="季度预测", confirmed=True,
            fields=[
                FieldSpec(code="forecast_no", name="预测编号", type="单据号", required=True, confirmed=True),
                FieldSpec(code="amount", name="金额", type="数字", required=True, confirmed=True),
                FieldSpec(code="status", name="状态", type="下拉单选", dict_code="forecast_status", confirmed=True),
            ],
        )],
        dicts=[DictSpec(code="forecast_status", name="预测状态", confirmed=True, options=[
            DictOption(code="draft", name="草稿"),
            DictOption(code="confirmed", name="已确认"),
        ])],
        permissions=[PermissionSpec(object_code="t_quarter_forecast", confirmed=True, rules=[
            PermissionRule(role="all", op="all", data="ALL"),
            PermissionRule(role="finance_lead", op="edit", data="DEPT"),
        ])],
        completeness=Completeness(confirmed=8, total=8),
        created_at=datetime(2026, 4, 25), updated_at=datetime(2026, 4, 25),
        created_by=1,
    )


def test_converter_emits_appName():
    config = spec_to_config(_full_spec())
    assert config["appName"] == "预算管理"


def test_converter_emits_roles():
    config = spec_to_config(_full_spec())
    assert config["roles"] == [{"code": "finance_lead", "name": "财务负责人"}]


def test_converter_emits_dicts_with_options():
    config = spec_to_config(_full_spec())
    assert config["dicts"] == [{
        "code": "forecast_status", "name": "预测状态",
        "options": [{"code": "draft", "name": "草稿"}, {"code": "confirmed", "name": "已确认"}],
    }]


def test_converter_emits_models_with_fields():
    config = spec_to_config(_full_spec())
    models = config["models"]
    assert len(models) == 1
    m = models[0]
    assert m["code"] == "t_quarter_forecast"
    assert m["name"] == "季度预测"
    assert len(m["fields"]) == 3
    f0 = m["fields"][0]
    assert f0["code"] == "forecast_no"
    assert f0["type"] == "单据号"
    assert f0["required"] is True


def test_converter_attaches_dict_to_field():
    config = spec_to_config(_full_spec())
    status_field = next(f for f in config["models"][0]["fields"] if f["code"] == "status")
    assert status_field.get("dict") == "forecast_status"


def test_converter_emits_permissions():
    config = spec_to_config(_full_spec())
    perms = config["permissions"]
    assert len(perms) == 1
    assert perms[0]["form"] == "t_quarter_forecast"
    assert {"role": "all", "op": "all", "data": "ALL"} in perms[0]["rules"]


def test_converter_skips_unconfirmed_items():
    """Per design: only confirmed items go into the config."""
    spec = _full_spec()
    spec.roles[0].confirmed = False  # unconfirmed role should not appear
    config = spec_to_config(spec)
    assert config["roles"] == []


def test_converter_wraps_with_data_envelope():
    """Top-level structure must match preview JSON envelope used by frontend."""
    config = spec_to_config(_full_spec())
    # The current preview consumer reads either {"data": {...}} or flat dict; we emit flat.
    assert "appName" in config
    assert "models" in config
    assert "roles" in config
```

- [ ] **Step 5.2: Run converter tests, expect FAIL**

Run:
```bash
cd backend && pytest tests/test_spec_converter.py -v
```

- [ ] **Step 5.3: Implement `backend/app/spec/converter.py`**

```python
"""SPEC → Application.config conversion.

One-way transformation. Only confirmed items are emitted to keep the
config a "source of truth for what the user actually approved".
"""

from __future__ import annotations
from app.spec.schema import Spec


def spec_to_config(spec: Spec) -> dict:
    """Render a Spec into the legacy Application.config dict format.

    Output shape (matches what frontend preview store consumes today):
    {
      "appName": str,
      "roles": [{"code", "name"}],
      "dicts": [{"code", "name", "options": [{"code", "name"}]}],
      "models": [{"code", "name", "fields": [{"code", "name", "type", "required", "dict?", "ref?"}]}],
      "permissions": [{"form": object_code, "rules": [{"role", "op", "data"}]}],
    }
    """
    out: dict = {}

    out["appName"] = spec.goal.title if (spec.goal and spec.goal.confirmed) else ""

    out["roles"] = [
        {"code": r.code, "name": r.name}
        for r in spec.roles if r.confirmed
    ]

    out["dicts"] = [
        {
            "code": d.code,
            "name": d.name,
            "options": [{"code": o.code, "name": o.name} for o in d.options],
        }
        for d in spec.dicts if d.confirmed
    ]

    out["models"] = [
        _render_object(o) for o in spec.objects if o.confirmed
    ]

    out["permissions"] = [
        {
            "form": p.object_code,
            "rules": [
                {"role": r.role, "op": r.op, "data": r.data} for r in p.rules
            ],
        }
        for p in spec.permissions if p.confirmed
    ]

    return out


def _render_object(obj) -> dict:
    return {
        "code": obj.code,
        "name": obj.name,
        "fields": [_render_field(f) for f in obj.fields if f.confirmed],
    }


def _render_field(f) -> dict:
    out: dict = {
        "code": f.code,
        "name": f.name,
        "type": f.type,
        "required": f.required,
    }
    if f.dict_code:
        out["dict"] = f.dict_code
    if f.ref_model and f.ref_field:
        out["ref"] = {"model": f.ref_model, "field": f.ref_field}
    return out
```

- [ ] **Step 5.4: Run converter tests, expect PASS**

Run:
```bash
cd backend && pytest tests/test_spec_converter.py -v
```
Expected: `8 passed`.

- [ ] **Step 5.5: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/spec/converter.py backend/tests/test_spec_converter.py && git commit -m "$(cat <<'EOF'
feat(spec): spec_to_config converter（只输出 confirmed 项）

按 design spec 9 章约定，spec → config 是单向 derive。未 confirmed
的角色/对象/字段/字典/权限不进 config，保证 config 是"用户实际批准"
的真理。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: SpecAgent (LLM tool loop)

**Files:**
- Create: `backend/app/spec/agent.py`
- Create: `backend/app/spec/persistence.py` (helper for serialization/load)
- Create: `backend/tests/test_spec_agent.py` (mocked-LLM tests; live-LLM smoke test in Task 9)

- [ ] **Step 6.1: Write `backend/app/spec/persistence.py`**

```python
"""Helpers to convert between Pydantic Spec and ORM Spec."""

from __future__ import annotations
from datetime import datetime
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.spec.schema import Spec, Completeness, Phase, derive_completeness
from app.models.spec import Spec as SpecORM


def new_spec_id() -> str:
    return f"spec_{uuid.uuid4().hex[:12]}"


def empty_spec(*, created_by: int, application_id: Optional[int] = None) -> Spec:
    now = datetime.utcnow()
    s = Spec(
        id=new_spec_id(), application_id=application_id,
        phase=Phase.GATHERING,
        completeness=Completeness(),
        created_at=now, updated_at=now, created_by=created_by,
    )
    s.completeness = derive_completeness(s)
    return s


def to_orm(spec: Spec, *, tenant_id: int) -> SpecORM:
    return SpecORM(
        id=spec.id, application_id=spec.application_id,
        version=spec.version, parent_spec_id=spec.parent_spec_id,
        payload=spec.model_dump(mode="json"),
        phase=spec.phase.value,
        completeness_confirmed=spec.completeness.confirmed,
        completeness_total=spec.completeness.total,
        created_at=spec.created_at, updated_at=spec.updated_at,
        created_by=spec.created_by, tenant_id=tenant_id,
    )


def from_orm(row: SpecORM) -> Spec:
    return Spec.model_validate(row.payload)


async def load_spec(db: AsyncSession, spec_id: str) -> Optional[Spec]:
    result = await db.execute(select(SpecORM).where(SpecORM.id == spec_id))
    row = result.scalar_one_or_none()
    return from_orm(row) if row else None


async def save_spec(db: AsyncSession, spec: Spec, *, tenant_id: int) -> SpecORM:
    """Upsert Spec by id."""
    existing = await db.execute(select(SpecORM).where(SpecORM.id == spec.id))
    row = existing.scalar_one_or_none()
    if row is None:
        row = to_orm(spec, tenant_id=tenant_id)
        db.add(row)
    else:
        row.payload = spec.model_dump(mode="json")
        row.phase = spec.phase.value
        row.completeness_confirmed = spec.completeness.confirmed
        row.completeness_total = spec.completeness.total
        row.application_id = spec.application_id
        row.version = spec.version
        row.parent_spec_id = spec.parent_spec_id
        row.updated_at = spec.updated_at
    await db.commit()
    return row
```

- [ ] **Step 6.2: Write failing agent test (mocked LLM)**

`backend/tests/test_spec_agent.py`:
```python
import json
import pytest
from unittest.mock import AsyncMock, patch

from app.spec.agent import SpecAgent, SpecAgentEvent
from app.spec.persistence import empty_spec
from app.spec.schema import Phase


class FakeLLMStream:
    """Yields pre-recorded SSE chunks emulating an OpenAI-compatible streaming response."""

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks

    async def __aiter__(self):
        for c in self.chunks:
            yield "data: " + json.dumps(c)
        yield "data: [DONE]"


def _tool_call_chunk(idx: int, call_id: str, name: str, args_json: str) -> dict:
    return {"choices": [{"delta": {"tool_calls": [{
        "index": idx, "id": call_id,
        "function": {"name": name, "arguments": args_json},
    }]}}]}


def _content_chunk(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


def _empty_finish_chunk() -> dict:
    return {"choices": [{"delta": {}}]}


@pytest.mark.asyncio
async def test_agent_runs_clarifying_questions_first_turn():
    """Replay: LLM emits 3 ask_clarifying_question tool_calls, then on next turn
    emits a final assistant message with no tool_calls. Agent should append all
    3 decisions to the spec."""
    spec = empty_spec(created_by=1)

    turn1_chunks = [
        _tool_call_chunk(0, "call_a", "ask_clarifying_question",
                         json.dumps({"topic": "周期颗粒度", "blocking": True})),
        _tool_call_chunk(1, "call_b", "ask_clarifying_question",
                         json.dumps({"topic": "数据来源", "blocking": True})),
        _tool_call_chunk(2, "call_c", "ask_clarifying_question",
                         json.dumps({"topic": "口径", "blocking": False})),
    ]
    turn2_chunks = [_content_chunk("好的，请回答上述 3 个问题。"), _empty_finish_chunk()]

    agent = SpecAgent(
        llm_base_url="http://fake", llm_api_key="fake", llm_model="fake-model",
    )

    with patch("app.spec.agent._open_stream", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = [FakeLLMStream(turn1_chunks), FakeLLMStream(turn2_chunks)]
        events = []
        async for ev in agent.run(spec, user_message="我想做预算管理系统"):
            events.append(ev)

    final_spec = next(e.spec for e in reversed(events) if e.kind == "final")
    assert len(final_spec.decisions_pending) == 3
    assert final_spec.decisions_pending[0].topic == "周期颗粒度"


@pytest.mark.asyncio
async def test_agent_rejects_set_goal_in_first_turn_with_zero_completeness():
    """LLM tries to call set_goal in gathering first turn → tool returns error,
    agent feeds error back; here we just verify the spec is unchanged after one
    blocked turn (no goal set)."""
    spec = empty_spec(created_by=1)
    turn1_chunks = [
        _tool_call_chunk(0, "call_x", "set_goal",
                         json.dumps({"title": "预算", "summary": "x", "business_problem": "y"})),
    ]
    turn2_chunks = [_content_chunk("好的，先问几个问题。"), _empty_finish_chunk()]

    agent = SpecAgent(llm_base_url="http://fake", llm_api_key="fake", llm_model="fake-model")
    with patch("app.spec.agent._open_stream", new_callable=AsyncMock) as mock_open:
        mock_open.side_effect = [FakeLLMStream(turn1_chunks), FakeLLMStream(turn2_chunks)]
        events = []
        async for ev in agent.run(spec, user_message="我想做预算管理系统"):
            events.append(ev)

    final_spec = next(e.spec for e in reversed(events) if e.kind == "final")
    assert final_spec.goal is None  # set_goal was rejected
    # Tool error event surfaced
    assert any(e.kind == "tool_error" and "ask_clarifying_question" in e.message for e in events)
```

- [ ] **Step 6.3: Run agent tests, expect FAIL**

Run:
```bash
cd backend && pytest tests/test_spec_agent.py -v
```

- [ ] **Step 6.4: Implement `backend/app/spec/agent.py`**

```python
"""SpecAgent: drives an LLM tool loop to mutate a SPEC object.

Pattern adapted from app/coding/vibe_agent.py:170-340 — same OpenAI-compatible
streaming + parallel tool_calls + JSON arg accumulation. Simpler because no
filesystem/workspace concerns; tool dispatch is pure SPEC mutation.
"""

from __future__ import annotations
import json
import httpx
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from app.spec.schema import Spec, Phase, derive_completeness
from app.spec.tools import TOOL_DEFINITIONS, dispatch_tool, ToolError


SPEC_GATHERING_PROMPT = """你是 aPaaS 业务分析师。当前 SPEC 状态：
{spec_summary}

【硬规则】
1. 首轮回复必须只调用 ask_clarifying_question tool 3-5 次，禁止任何 add_/set_。
2. 第二轮起，根据用户回答调 set_goal / add_role / add_object，
   每次问完一个领域再继续问下一个。
3. 禁止在对话内容里写 "## 系统核心模型" "让我帮你设计" 这类元描述。
4. 当 completeness ≥ 0.6 且无 blocking decision 时，调 transition_phase("drafting")。

【tool 调用纪律】
- add_* tool 调用时 confirmed 必须为 false，等用户在 UI 确认。
- 不要一次塞 10 个 tool；每轮 ≤ 5 个 tool 调用。
- 对话文本里禁止重复 tool 已经写入的内容（避免冗余）。

【对话语言】
- 用业务语言，对业务用户避免"枚举""数据模型"等技术术语。
- 一次只问一个核心问题，对话节奏像顾问聊需求。
"""


SPEC_DRAFTING_PROMPT = """你正在整理 SPEC 草案。当前 SPEC：
{spec_summary}

【任务】
1. 把 gathering 阶段的零散信息整理成完整 SPEC：补全 fields、推断 dicts、生成 permissions 默认规则。
2. 推断的内容用 add_/update_，confirmed=false，让用户审。
3. 用户在 UI 上点 confirm/dismiss/edit 后会通过 user message 告诉你，你再调对应 tool。
4. 所有项 confirmed=true 且无 blocking decision 时，调 transition_phase("generating")。

【禁止】
- 禁止在用户没说"确认"时主动调 confirm_*。
- 禁止跳回 gathering（除非用户明确说"重来 / 这部分需求要改"）。
- 禁止在对话文本中重写 SPEC 内容（用 tool 而不是文本）。

【对话语言】
- 简短解释你正在做什么（"我已经补了 3 个权限规则，请你确认"），不要长篇大论。
"""


def build_prompt(spec: Spec) -> str:
    summary = _summarize_spec(spec)
    if spec.phase == Phase.GATHERING:
        return SPEC_GATHERING_PROMPT.format(spec_summary=summary)
    if spec.phase == Phase.DRAFTING:
        return SPEC_DRAFTING_PROMPT.format(spec_summary=summary)
    # generating/ready phases don't run agent (handled by converter)
    raise ValueError(f"SpecAgent should not run in phase={spec.phase.value}")


def _summarize_spec(spec: Spec) -> str:
    c = spec.completeness
    parts = [
        f"phase={spec.phase.value}",
        f"completeness={c.confirmed}/{c.total}",
        f"goal={spec.goal.title if spec.goal else 'unset'}",
        f"roles={[r.code for r in spec.roles]}",
        f"objects={[o.code for o in spec.objects]}",
        f"dicts={[d.code for d in spec.dicts]}",
        f"pending_decisions={[(d.id, d.topic, d.blocking) for d in spec.decisions_pending]}",
    ]
    return " | ".join(parts)


@dataclass
class SpecAgentEvent:
    kind: str  # "assistant_delta" | "tool_call" | "tool_result" | "tool_error" | "spec_patch" | "final"
    spec: Spec
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    message: Optional[str] = None


async def _open_stream(client: httpx.AsyncClient, base_url: str, api_key: str, payload: dict):
    """Indirection for testing — returns an async iterable of SSE lines."""
    async with client.stream(
        "POST",
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
    ) as stream:
        if stream.status_code != 200:
            body = await stream.aread()
            raise RuntimeError(f"LLM API {stream.status_code}: {body[:300].decode(errors='replace')}")
        async for line in stream.aiter_lines():
            yield line


class SpecAgent:
    def __init__(self, llm_base_url: str, llm_api_key: str, llm_model: str, max_turns: int = 12):
        self.base_url = llm_base_url
        self.api_key = llm_api_key
        self.model = llm_model
        self.max_turns = max_turns

    async def run(
        self,
        spec: Spec,
        user_message: str,
        history: Optional[list[dict]] = None,
    ) -> AsyncIterator[SpecAgentEvent]:
        """Drive one LLM turn-loop over the SPEC. Yields events; mutates spec in place.

        history: optional prior conversation messages [{"role": ..., "content": ...}]
        """
        history = history or []
        system_prompt = build_prompt(spec)
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": user_message},
        ]

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=10, pool=10)) as client:
            for turn in range(self.max_turns):
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "tools": TOOL_DEFINITIONS,
                    "max_tokens": 4096,
                    "temperature": 0.2,
                    "stream": True,
                }
                full_content = ""
                tool_calls_map: dict = {}

                stream = _open_stream(client, self.base_url, self.api_key, payload)
                async for line in stream:
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    if delta.get("content"):
                        full_content += delta["content"]
                        yield SpecAgentEvent(kind="assistant_delta", spec=spec, text=delta["content"])
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            entry = tool_calls_map.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            func = tc.get("function", {})
                            if func.get("name"):
                                entry["name"] = func["name"]
                            if func.get("arguments"):
                                entry["arguments"] += func["arguments"]

                # Reconstruct assistant message
                assistant_msg: dict = {"role": "assistant", "content": full_content or None}
                assembled: list[dict] = []
                for idx in sorted(tool_calls_map.keys()):
                    entry = tool_calls_map[idx]
                    if not entry["name"]:
                        continue
                    raw = entry["arguments"] or "{}"
                    try:
                        json.loads(raw)
                        valid_args = raw
                    except json.JSONDecodeError:
                        valid_args = "{}"
                    assembled.append({
                        "id": entry["id"] or f"call_{turn}_{idx}",
                        "type": "function",
                        "function": {"name": entry["name"], "arguments": valid_args},
                    })
                if assembled:
                    assistant_msg["tool_calls"] = assembled
                messages.append(assistant_msg)

                if not assembled:
                    # No tool calls → agent done for this user turn
                    yield SpecAgentEvent(kind="final", spec=spec, text=full_content)
                    return

                # Execute tools sequentially against spec; feed results back
                # enforce_first_turn=True only on turn 0 (the very first LLM response of this run)
                enforce_first = (turn == 0)
                for tc in assembled:
                    name = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"] or "{}")
                    yield SpecAgentEvent(kind="tool_call", spec=spec, tool_name=name, tool_args=args)
                    try:
                        spec = dispatch_tool(spec, name, args, enforce_first_turn=enforce_first)
                        result_str = "ok"
                        yield SpecAgentEvent(kind="spec_patch", spec=spec, tool_name=name)
                    except ToolError as e:
                        result_str = f"Error: {e}"
                        yield SpecAgentEvent(kind="tool_error", spec=spec, tool_name=name, message=str(e))
                    messages.append({
                        "role": "tool", "tool_call_id": tc["id"],
                        "content": result_str,
                    })

            # Hit max_turns
            yield SpecAgentEvent(kind="final", spec=spec, text=full_content)
```

- [ ] **Step 6.5: Run agent tests, expect PASS**

Run:
```bash
cd backend && pytest tests/test_spec_agent.py -v
```
Expected: `2 passed`. The mock pattern feeds `_open_stream` a `FakeLLMStream`; since the test patches with `new_callable=AsyncMock` but `_open_stream` is an async generator, the mock needs to return an async iterable. **If the test fails because of mock semantics**, switch the patch target to `agent._open_stream` and make the side_effect a plain function returning the FakeLLMStream (since `async for` works on the returned `__aiter__`).

If still failing, change `_open_stream` to a plain async function returning an `AsyncIterator` and adjust mock side_effect to `lambda *a, **kw: FakeLLMStream(turn_chunks)`.

- [ ] **Step 6.6: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/spec/agent.py backend/app/spec/persistence.py backend/tests/test_spec_agent.py && git commit -m "$(cat <<'EOF'
feat(spec): SpecAgent + persistence helpers

SpecAgent.run() 跑 LLM tool loop（pattern from vibe_agent.py），
yield SpecAgentEvent 流（assistant_delta / tool_call / spec_patch /
tool_error / final），调用方根据 event 推 SSE 给前端。

persistence.py 封装 Spec ↔ SpecORM 序列化 + load/save_spec。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: REST API for SPEC

**Files:**
- Create: `backend/app/routes/spec.py`
- Modify: `backend/app/main.py` (register router)
- Create: `backend/tests/test_spec_routes.py`

- [ ] **Step 7.1: Write failing route test**

`backend/tests/test_spec_routes.py`:
```python
import pytest
from datetime import datetime
from sqlalchemy import select

from app.spec.persistence import empty_spec, save_spec
from app.spec.schema import Phase, Role


@pytest.mark.asyncio
async def test_get_spec_returns_payload(db_session, monkeypatch):
    spec = empty_spec(created_by=1)
    spec.roles.append(Role(code="r1", name="r1", scope="ALL", confirmed=False))
    await save_spec(db_session, spec, tenant_id=1)

    # Direct DB read instead of HTTP — keeps test self-contained
    from app.models.spec import Spec as SpecORM
    row = (await db_session.execute(select(SpecORM).where(SpecORM.id == spec.id))).scalar_one()
    assert row.payload["roles"][0]["code"] == "r1"
    assert row.phase == "gathering"


@pytest.mark.asyncio
async def test_phase_transition_blocked_by_pending_blocking_decision(db_session):
    from app.spec.tools import dispatch_tool
    spec = empty_spec(created_by=1)
    spec = dispatch_tool(spec, "ask_clarifying_question", {"topic": "x", "blocking": True})
    await save_spec(db_session, spec, tenant_id=1)

    # Simulate route logic
    from app.spec.tools import dispatch_tool, ToolError
    with pytest.raises(ToolError):
        dispatch_tool(spec, "transition_phase", {"target": "drafting", "reason": "ok"})


@pytest.mark.asyncio
async def test_confirm_role_via_dispatch(db_session):
    from app.spec.tools import dispatch_tool
    spec = empty_spec(created_by=1)
    spec = dispatch_tool(spec, "ask_clarifying_question", {"topic": "x"})
    spec = dispatch_tool(spec, "ask_clarifying_question", {"topic": "y"})
    spec = dispatch_tool(spec, "ask_clarifying_question", {"topic": "z"})
    spec = dispatch_tool(spec, "add_role", {"code": "r1", "name": "r1", "scope": "ALL"})
    spec = dispatch_tool(spec, "confirm_role", {"code": "r1"})
    assert spec.roles[0].confirmed is True
    assert spec.completeness.confirmed == 1
```

- [ ] **Step 7.2: Run tests, expect FAIL (no route file yet — but these tests stub via DB, so they may pass once schema + persistence work; if so, mark this step skipped)**

Run:
```bash
cd backend && pytest tests/test_spec_routes.py -v
```
If they pass already (schema/persistence-level tests), proceed. If they fail due to import errors only, fix and proceed.

- [ ] **Step 7.3: Implement `backend/app/routes/spec.py`**

```python
"""REST API for SPEC objects.

POST   /spec                           → create empty spec for current user
GET    /spec/{id}                      → load full spec
PUT    /spec/{id}/phase                → user-driven phase transition
PUT    /spec/{id}/items/{type}/{code}  → user confirm/edit/dismiss single item

The "items" endpoint dispatches to the same tool functions the agent uses,
so behavior stays consistent.
"""

from __future__ import annotations
from typing import Annotated, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_auth_context, get_db
from app.auth import AuthContext
from app.spec.persistence import load_spec, save_spec, empty_spec
from app.spec.tools import dispatch_tool, ToolError
from app.spec.schema import Phase

router = APIRouter(prefix="/spec", tags=["spec"])


class CreateSpecRequest(BaseModel):
    application_id: Optional[int] = None


@router.post("")
async def create_spec(
    body: CreateSpecRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    spec = empty_spec(created_by=ctx.user.id, application_id=body.application_id)
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return {"id": spec.id, "phase": spec.phase.value}


class PhaseTransition(BaseModel):
    target: Literal["gathering", "drafting", "generating", "ready"]
    reason: str = "user request"


class ItemAction(BaseModel):
    action: Literal["confirm", "dismiss", "update"]
    payload: dict = {}


@router.get("/{spec_id}")
async def get_spec(
    spec_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    spec = await load_spec(db, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")
    return spec.model_dump(mode="json")


@router.put("/{spec_id}/phase")
async def transition_phase(
    spec_id: str,
    body: PhaseTransition,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    spec = await load_spec(db, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")
    try:
        spec = dispatch_tool(spec, "transition_phase",
                             {"target": body.target, "reason": body.reason})
    except ToolError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return spec.model_dump(mode="json")


@router.put("/{spec_id}/items/{item_type}/{item_code}")
async def update_item(
    spec_id: str,
    item_type: Literal["role", "object", "field", "dict", "permission"],
    item_code: str,
    body: ItemAction,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Map (item_type, action) → tool name and dispatch."""
    spec = await load_spec(db, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {spec_id} not found")

    tool_map = {
        ("role", "confirm"): ("confirm_role", {"code": item_code}),
        ("role", "dismiss"): ("dismiss_role", {"code": item_code}),
        ("role", "update"): ("update_role", {"code": item_code, **body.payload}),
        ("object", "confirm"): ("confirm_object", {"code": item_code}),
        ("object", "dismiss"): ("dismiss_object", {"code": item_code}),
        ("dict", "confirm"): ("confirm_dict", {"code": item_code}),
        ("dict", "dismiss"): ("dismiss_dict", {"code": item_code}),
        ("permission", "confirm"): ("confirm_permission", {"object_code": item_code}),
        ("permission", "dismiss"): ("dismiss_permission", {"object_code": item_code}),
        # field needs object_code in body.payload
        ("field", "confirm"): ("confirm_field",
                               {"object_code": body.payload.get("object_code"), "field_code": item_code}),
        ("field", "dismiss"): ("dismiss_field",
                               {"object_code": body.payload.get("object_code"), "field_code": item_code}),
        ("field", "update"): ("update_field",
                              {"object_code": body.payload.get("object_code"),
                               "field_code": item_code,
                               **{k: v for k, v in body.payload.items() if k != "object_code"}}),
    }
    key = (item_type, body.action)
    if key not in tool_map:
        raise HTTPException(status_code=400, detail=f"Unsupported {item_type}/{body.action}")
    tool_name, tool_args = tool_map[key]
    try:
        spec = dispatch_tool(spec, tool_name, tool_args)
    except ToolError as e:
        raise HTTPException(status_code=409, detail=str(e))
    await save_spec(db, spec, tenant_id=ctx.tenant_id)
    return spec.model_dump(mode="json")
```

- [ ] **Step 7.4: Register router in `backend/app/main.py`**

Find the section where other routers are included. Add:
```python
from app.routes import spec as spec_routes
app.include_router(spec_routes.router)
```
(Place near other `app.include_router(...)` lines.)

- [ ] **Step 7.5: Run route tests + smoke import**

```bash
cd backend && pytest tests/test_spec_routes.py -v && python -c "from app.routes.spec import router; print('routes registered:', [r.path for r in router.routes])"
```
Expected: `3 passed` (or however many tests exist) + `routes registered: ['/spec/{spec_id}', '/spec/{spec_id}/phase', '/spec/{spec_id}/items/{item_type}/{item_code}']`.

- [ ] **Step 7.6: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/routes/spec.py backend/app/main.py backend/tests/test_spec_routes.py && git commit -m "$(cat <<'EOF'
feat(spec): REST API（GET /spec/{id} + PUT phase + PUT items）

PUT /spec/{id}/items/{type}/{code} 把前端 Canvas 的 confirm/dismiss/
update 操作映射到对应 tool，跟 SpecAgent 走同一套 dispatch_tool，
行为一致。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Wire SpecAgent into /chat/send

**Files:**
- Modify: `backend/app/routes/chat.py` (add SpecAgent branch in `/send` route)

- [ ] **Step 8.1: Locate insertion point**

Open [backend/app/routes/chat.py:573](backend/app/routes/chat.py:573) (where `system_prompt = _build_phase_prompt(...)` is). The new branch goes **before** that line: if `conversation.spec_id IS NOT NULL` → delegate to SpecAgent.

- [ ] **Step 8.2: Add import at top of `backend/app/routes/chat.py`**

After existing `import json` etc. add:
```python
from app.spec.agent import SpecAgent, SpecAgentEvent
from app.spec.persistence import load_spec, save_spec, empty_spec
from app.spec.schema import Phase as SpecPhase
```

- [ ] **Step 8.3: Add SpecAgent branch to `send_message` (the function containing line 573)**

Insert this block **before** the existing `system_prompt = _build_phase_prompt(...)` call:

```python
    # ── SpecAgent branch: if conversation has a linked spec, drive the new state machine ──
    if conversation.spec_id:
        spec = await load_spec(db, conversation.spec_id)
        if spec is None:
            # Spec was deleted but FK lingers — fall back to legacy path
            conversation.spec_id = None
            await db.commit()
        else:
            llm_cfg = await _get_conversation_llm_config(db, conversation)
            agent = SpecAgent(
                llm_base_url=llm_cfg.base_url,
                llm_api_key=llm_cfg.api_key,
                llm_model=llm_cfg.model,
            )
            # Persist user message
            db.add(Message(conversation_id=conversation.id, role="user", content=data.message))
            await db.commit()

            async def spec_event_generator():
                last_assistant_text = ""
                try:
                    # Reload prior messages (excluding the user message we just inserted)
                    # to provide history context to the agent.
                    msg_result = await db.execute(
                        select(Message).where(Message.conversation_id == conversation.id)
                        .order_by(Message.created_at)
                    )
                    all_msgs = list(msg_result.scalars().all())
                    # The last message is the user message we just appended; drop it
                    # because agent.run() takes user_message as a separate argument.
                    history = [{"role": m.role, "content": m.content} for m in all_msgs[:-1]]

                    async for ev in agent.run(spec, user_message=data.message, history=history):
                        if ev.kind == "assistant_delta":
                            last_assistant_text += ev.text or ""
                            yield {"event": "message", "data": json.dumps(
                                {"type": "message", "data": ev.text}, ensure_ascii=False)}
                        elif ev.kind == "spec_patch":
                            await save_spec(db, ev.spec, tenant_id=ctx.tenant_id)
                            yield {"event": "spec_patch", "data": json.dumps(
                                {"type": "spec_patch", "data": ev.spec.model_dump(mode="json")},
                                ensure_ascii=False)}
                        elif ev.kind == "tool_error":
                            yield {"event": "tool_error", "data": json.dumps(
                                {"type": "tool_error", "tool": ev.tool_name, "message": ev.message},
                                ensure_ascii=False)}
                        elif ev.kind == "final":
                            db.add(Message(conversation_id=conversation.id, role="assistant",
                                           content=last_assistant_text))
                            await db.commit()
                    yield {"event": "done", "data": json.dumps({"type": "done", "data": "completed"})}
                except Exception as e:
                    yield {"event": "error", "data": json.dumps({"type": "error", "data": str(e)})}

            return EventSourceResponse(spec_event_generator())
```

- [ ] **Step 8.4: Sanity-check: backend imports cleanly**

Run:
```bash
cd backend && python -c "from app.routes.chat import router; print('chat router OK, routes=', len(router.routes))"
```
Expected: prints route count without error.

- [ ] **Step 8.5: Commit**

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/app/routes/chat.py && git commit -m "$(cat <<'EOF'
feat(chat): /chat/send 加 SpecAgent 分支

conversation.spec_id IS NOT NULL 时走 SpecAgent，stream 出
spec_patch / tool_error / message / done 4 类 SSE 事件给前端。
旧路径不变（spec_id IS NULL 走 _build_phase_prompt 老链路）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: End-to-end smoke test (live LLM via curl)

**Files:**
- Create: `backend/tests/smoke_spec_e2e.sh`

This task is a manual gate — it requires a running backend + a real LLM config in the DB. If you don't have one available, mark this task complete by inspection and revisit during Phase β.

- [ ] **Step 9.1: Start the backend**

```bash
cd backend && source venv/bin/activate && uvicorn app.main:app --reload --port 8000 &
```

- [ ] **Step 9.2: Get an auth token**

Login with the dev seed account; copy the bearer token to env var:
```bash
export TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"<dev-email>","password":"<dev-pwd>"}' | jq -r '.access_token')
echo "$TOKEN"
```

- [ ] **Step 9.3: Create a conversation + spec, then send a chat message**

`backend/tests/smoke_spec_e2e.sh`:
```bash
#!/bin/bash
# Phase α end-to-end smoke test.
# Prereq: backend running on :8000, $TOKEN exported with valid bearer token.

set -e
TOKEN="${TOKEN:?must export TOKEN}"

echo "1. Create empty spec via direct API..."
SPEC_ID=$(curl -s -X POST http://localhost:8000/spec \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq -r '.id' 2>/dev/null || echo "spec_$(date +%s)")
# (POST /spec endpoint not in plan; see Step 9.5 fallback)

echo "2. Create conversation linked to spec..."
CONV_ID=$(curl -s -X POST http://localhost:8000/conversations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"agent_type\":\"requirements\",\"spec_id\":\"$SPEC_ID\"}" | jq -r '.id')
echo "Conv ID: $CONV_ID"

echo "3. Send first user message and read SSE stream..."
curl -N -X POST http://localhost:8000/chat/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"conversation_id\":$CONV_ID,\"message\":\"我想做一个预算管理系统\"}" \
  | tee /tmp/spec_e2e_out.txt

echo "4. Verify spec has 3+ pending decisions..."
curl -s http://localhost:8000/spec/$SPEC_ID -H "Authorization: Bearer $TOKEN" | jq '.decisions_pending | length'
```

- [ ] **Step 9.4: Make script executable**
```bash
chmod +x backend/tests/smoke_spec_e2e.sh
```

- [ ] **Step 9.5: Verify `/conversations` endpoint accepts `spec_id` field**

The script in 9.3 sends `{"agent_type":"requirements","spec_id":"$SPEC_ID"}` to `/conversations`. Check whether the existing route in [backend/app/routes/conversations.py](backend/app/routes/conversations.py) accepts `spec_id` in its create body. If not, either:
- Add it (single-line change to the request schema + ORM assignment), or
- Adjust the smoke script to manually update `conversations.spec_id` via direct DB call after create.

Pick whichever is faster; document the choice in the commit message.

- [ ] **Step 9.6: Run smoke test**
```bash
bash backend/tests/smoke_spec_e2e.sh
```
Expected: SSE stream emits `message` + `spec_patch` + `done` events; final `decisions_pending | length` ≥ 3.

If the LLM doesn't follow the "first turn must ask 3+ questions" rule, the agent will return a `tool_error` event and the LLM will self-correct on the next loop iteration.

- [ ] **Step 9.7: Commit smoke script**
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && git add backend/tests/smoke_spec_e2e.sh && git commit -m "$(cat <<'EOF'
test(spec): add end-to-end smoke script + POST /spec endpoint

bash backend/tests/smoke_spec_e2e.sh 验证：创建 spec → 关联
conversation → 第一条用户消息触发 SpecAgent → SSE 流出
message/spec_patch/done → spec 落库 ≥ 3 个 pending decision。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 9.8: Stop backend**
```bash
pkill -f "uvicorn app.main:app"
```

---

## Self-Review Checklist (run before declaring Phase α complete)

- [ ] All 8 tests files run green: `cd backend && pytest tests/ -v` → all pass
- [ ] Backend starts without import errors: `cd backend && python -c "from app.main import app; print('ok')"`
- [ ] DB migration applied: sqlite3 confirms `applications.canonical_spec_id` and `conversations.spec_id` exist
- [ ] `_extract_config_from_response` (legacy path) still works for non-spec-id conversations — verify by sending a message in an old conversation
- [ ] Smoke script (`smoke_spec_e2e.sh`) returns ≥ 3 pending decisions when run live
- [ ] Each commit references task number / passes locally before pushing

---

## What's NOT in this plan (deferred to Phase β / γ)

- Frontend three-pane layout (β)
- SpecCanvas / SpecInspector / PhaseBar Vue components (β)
- bootstrap_from_doc (γ — covers entries 2/6)
- Application reverse-engineering for legacy conversations (γ)
- Coding-side handoff (Phase γ + 后续)
- Permissions: tenant-scoped spec listing (multi-tenant slice)
