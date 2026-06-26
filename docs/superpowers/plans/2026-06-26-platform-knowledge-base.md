# 平台知识库(规范库) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给得小帆加一个平台级、可在线编辑的知识库(规范库),让「搭建/二次开发」规范从 prompt/代码搬进库,改库即生效;agent 通过渐进披露清单 + `read_knowledge`/`search_knowledge` 工具消费,wire-once 进统一 `run_agent` 引擎。

**Architecture:** DB 存 wiki 式 markdown 文档(`knowledge_docs` 表);纯逻辑模块 `knowledge_base.py` 提供查询 + 清单渲染;两个只读本地工具注册进 `ai_chat/tools.py`(自动落 base-local/core,所有 profile 可用);`run_agent` 拼 system prompt 时注入 published 文档目录;平台管理员经 `/api/knowledge` CRUD 维护。不走向量化,检索用可移植 LIKE 切词。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + SQLite(本地)/MySQL(线上);pytest + pytest-asyncio;前端 Vue 3 + Element Plus + `@/utils/request`。

## Global Constraints

- **只读工具,无副作用**:`read_knowledge`/`search_knowledge` 只查库,任何 profile 给都安全。
- **只 `status='published'` 进 agent**;`tenant_id` 本期**恒为 NULL**(=全局),列仅预留。
- **写权限 = 平台管理员**(`require_platform_admin`);读路由也限管理员;agent 不经 HTTP,直接查 DB。
- **`get_db` 不 autocommit** —— 所有写端点必须显式 `await db.commit()`。
- **新模型必须在 `backend/app/models/__init__.py` 注册导入**,否则 `create_all` 漏表(历史踩坑)。
- **base 本地工具不进 `tool_registry.yaml`**(那是 MCP 专用);注册进 `ai_chat/tools.py` 的 `TOOL_SCHEMAS` + `TOOL_HANDLERS` 即自动落 `_BASE_LOCAL_NAMES`/`CORE_TOOL_NAMES`,在 dev-apaas 与默认 Builder 两 profile 下都恒在、不被延迟。
- **检索可移植**:用 `ilike` LIKE 子串匹配(SQLite/MySQL 行为一致),不用 FULLTEXT/FTS。
- **本地 = SQLite,线上 = MySQL**:任何索引/唯一约束改动,合并前用 docker mysql:8 跑一次 `create_all` 验证(`slug` String(160) 唯一索引 640 字节 < 3072,安全)。
- 后端测试自带内存库 fixture(`sqlite+aiosqlite://` + `StaticPool` + `create_all`),不依赖外部 DB。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/app/models/knowledge_doc.py`(建) | `KnowledgeDoc` ORM 模型 |
| `backend/app/models/__init__.py`(改) | 注册模型导入 |
| `backend/app/knowledge_base.py`(建) | 纯逻辑:查询 published/by-slug/search + 渲染清单 |
| `backend/app/ai_chat/tools.py`(改) | 2 个工具 schema + 2 个 execute fn + `TOOL_HANDLERS` 条目 |
| `backend/app/ai_chat/agent.py`(改) | `_append_knowledge_manifest` + 在 902 行 `_append_skill_manifest` 后调用 |
| `backend/app/deps.py`(改) | `require_platform_admin` 依赖 |
| `backend/app/routes/knowledge.py`(建) | `/knowledge` CRUD(平台管理员) |
| `backend/app/main.py`(改) | 注册 knowledge 路由 |
| `frontend/src/api/knowledge.ts`(建) | 前端 API 客户端 |
| `frontend/src/views/KnowledgeBasePage.vue`(建) | 管理页(列表 + markdown 编辑 + 发布开关) |
| `frontend/src/router/index.ts`(改) | 注册路由 + 导航入口 |
| `backend/tests/test_knowledge_*.py`(建) | 各任务测试 |

---

## Phase 1 — 后端核心(agent 可消费)

### Task 1: KnowledgeDoc 模型

**Files:**
- Create: `backend/app/models/knowledge_doc.py`
- Modify: `backend/app/models/__init__.py`(在 ~410 行 `ConfigAssistantSkill` 导入旁加一行)
- Test: `backend/tests/test_knowledge_model.py`

**Interfaces:**
- Produces: `KnowledgeDoc`(表 `knowledge_docs`),字段 `id, slug, title, summary, category, tags, body_md, status, tenant_id, updated_by, created_at, updated_at`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_knowledge_model.py
import pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select
from app.database import Base
import app.models  # noqa: F401 — 注册全部 ORM 映射


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_doc_roundtrip(db):
    from app.models.knowledge_doc import KnowledgeDoc
    d = KnowledgeDoc(slug="definesys-event-sdk", title="definesys 事件 SDK",
                     summary="写侧 SDK 规范", category="二次开发", body_md="# 正文", status="published")
    db.add(d); await db.commit()
    got = (await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.slug == "definesys-event-sdk"))).scalar_one()
    assert got.title == "definesys 事件 SDK"
    assert got.tenant_id is None
    assert got.status == "published"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_knowledge_model.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models.knowledge_doc` 或 `no such table: knowledge_docs`。

- [ ] **Step 3: Create the model**

```python
# backend/app/models/knowledge_doc.py
"""平台知识库(规范库)文档 — wiki 式 markdown,渐进披露给 agent。

平台级单库:tenant_id 恒为 NULL(=全局),列预留供后续租户覆盖(C 方案),本期不写非 NULL。
只 status='published' 进 agent。
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

BigText = Text().with_variant(LONGTEXT, "mysql")


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="平台规范", index=True)
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body_md: Mapped[str] = mapped_column(BigText, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    # NULL=平台全局(本期恒 NULL);列预留,避免后续 MySQL ALTER(项目用 create_all 不改既有表)。
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    updated_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
```

- [ ] **Step 4: Register the model in `__init__.py`**

在 `backend/app/models/__init__.py` 的 `ConfigAssistantSkill` 导入行(~410)后加:

```python
from app.models.knowledge_doc import KnowledgeDoc  # noqa: E402, F401  — 平台知识库(规范库)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_knowledge_model.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/knowledge_doc.py backend/app/models/__init__.py backend/tests/test_knowledge_model.py
git commit -m "feat(knowledge): KnowledgeDoc 模型 + 注册"
```

---

### Task 2: knowledge_base 核心(查询 + 清单渲染)

**Files:**
- Create: `backend/app/knowledge_base.py`
- Test: `backend/tests/test_knowledge_base.py`

**Interfaces:**
- Consumes: `KnowledgeDoc`(Task 1)
- Produces:
  - `async list_published_docs(db) -> list[KnowledgeDoc]`
  - `async get_published_doc(db, slug: str) -> KnowledgeDoc | None`
  - `async search_published_docs(db, query: str, limit: int = 8) -> list[KnowledgeDoc]`
  - `build_knowledge_manifest(docs: list[KnowledgeDoc]) -> str`(纯函数)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_knowledge_base.py
import pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
import app.models  # noqa: F401


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _seed(db):
    from app.models.knowledge_doc import KnowledgeDoc
    db.add_all([
        KnowledgeDoc(slug="a", title="表单字段规范", summary="字段口径", category="搭建",
                     body_md="字段命名用蛇形", status="published"),
        KnowledgeDoc(slug="b", title="definesys 事件 SDK", summary="写侧 API",
                     category="二次开发", body_md="afterFormData 用法", status="published"),
        KnowledgeDoc(slug="c", title="草稿", summary="未发布", category="搭建",
                     body_md="draft body", status="draft"),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_list_published_excludes_draft(db):
    from app.knowledge_base import list_published_docs
    await _seed(db)
    slugs = [d.slug for d in await list_published_docs(db)]
    assert slugs == ["b", "a"]  # 按 category 排序:二次开发 < 搭建(unicode),再按 title


@pytest.mark.asyncio
async def test_get_published_doc(db):
    from app.knowledge_base import get_published_doc
    await _seed(db)
    assert (await get_published_doc(db, "b")).title == "definesys 事件 SDK"
    assert await get_published_doc(db, "c") is None      # draft 不可读
    assert await get_published_doc(db, "zzz") is None     # 不存在


@pytest.mark.asyncio
async def test_search_ranks_title_over_body(db):
    from app.knowledge_base import search_published_docs
    await _seed(db)
    hits = await search_published_docs(db, "字段")
    assert hits[0].slug == "a"        # 标题命中权重最高
    assert all(h.status == "published" for h in hits)


def test_build_manifest_groups_and_empty():
    from app.knowledge_base import build_knowledge_manifest
    from app.models.knowledge_doc import KnowledgeDoc
    assert build_knowledge_manifest([]) == ""   # 空集 no-op
    m = build_knowledge_manifest([
        KnowledgeDoc(slug="b", title="T2", summary="S2", category="二次开发", body_md="x", status="published"),
    ])
    assert "## 平台知识库" in m and "[二次开发]" in m and "b: T2 — S2" in m
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_knowledge_base.py -v`
Expected: FAIL — `ModuleNotFoundError: app.knowledge_base`。

- [ ] **Step 3: Create the module**

```python
# backend/app/knowledge_base.py
"""平台知识库(规范库)核心 — 查询 + 渐进披露清单渲染。

纯逻辑,被 agent 工具(ai_chat/tools.py)与 manifest 注入(agent.py)复用。
检索用可移植 ilike LIKE 子串匹配(SQLite/MySQL 一致),不走向量/FULLTEXT。
"""
from __future__ import annotations
import re
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.knowledge_doc import KnowledgeDoc


async def list_published_docs(db: AsyncSession) -> list[KnowledgeDoc]:
    res = await db.execute(
        select(KnowledgeDoc)
        .where(KnowledgeDoc.status == "published", KnowledgeDoc.tenant_id.is_(None))
        .order_by(KnowledgeDoc.category, KnowledgeDoc.title)
    )
    return list(res.scalars().all())


async def get_published_doc(db: AsyncSession, slug: str) -> KnowledgeDoc | None:
    res = await db.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.slug == slug,
            KnowledgeDoc.status == "published",
            KnowledgeDoc.tenant_id.is_(None),
        )
    )
    return res.scalar_one_or_none()


def _tokenize(query: str) -> list[str]:
    parts = re.split(r"[\s,，、;；:：。.!！?？/\\()()\[\]]+", (query or "").strip())
    return [p for p in parts if p]


def _score(d: KnowledgeDoc, tokens: list[str]) -> int:
    s = 0
    title, summary, body = (d.title or "").lower(), (d.summary or "").lower(), (d.body_md or "").lower()
    for t in tokens:
        tl = t.lower()
        if tl in title: s += 5
        if tl in summary: s += 3
        if tl in body: s += 1
    return s


async def search_published_docs(db: AsyncSession, query: str, limit: int = 8) -> list[KnowledgeDoc]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    conds = [
        or_(KnowledgeDoc.title.ilike(f"%{t}%"),
            KnowledgeDoc.summary.ilike(f"%{t}%"),
            KnowledgeDoc.body_md.ilike(f"%{t}%"))
        for t in tokens
    ]
    res = await db.execute(
        select(KnowledgeDoc).where(
            KnowledgeDoc.status == "published",
            KnowledgeDoc.tenant_id.is_(None),
            or_(*conds),  # 命中任一 token 即入选,Python 端按命中加权排序
        )
    )
    docs = list(res.scalars().all())
    docs.sort(key=lambda d: _score(d, tokens), reverse=True)
    return docs[:limit]


def build_knowledge_manifest(docs: list[KnowledgeDoc]) -> str:
    if not docs:
        return ""
    by_cat: dict[str, list[KnowledgeDoc]] = {}
    for d in docs:
        by_cat.setdefault(d.category or "其他", []).append(d)
    lines = [
        "\n\n## 平台知识库(规范)",
        "需要某条规范时,先 `read_knowledge(slug)` 读全文,或 `search_knowledge(query)` 检索:",
    ]
    for cat in sorted(by_cat):
        lines.append(f"[{cat}]")
        for d in by_cat[cat]:
            lines.append(f"- {d.slug}: {d.title} — {d.summary}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_knowledge_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/knowledge_base.py backend/tests/test_knowledge_base.py
git commit -m "feat(knowledge): 查询 + 检索 + 清单渲染核心"
```

---

### Task 3: read_knowledge / search_knowledge 工具

**Files:**
- Modify: `backend/app/ai_chat/tools.py`(`TOOL_SCHEMAS` 列表尾部加 2 项;`TOOL_HANDLERS` dict 加 2 项;新增 2 个 execute fn)
- Test: `backend/tests/test_knowledge_tools.py`

**Interfaces:**
- Consumes: `knowledge_base.get_published_doc` / `search_published_docs`(Task 2)
- Produces: `async execute_read_knowledge(args, session, db) -> str`、`async execute_search_knowledge(args, session, db) -> str`;工具名 `read_knowledge`/`search_knowledge` 进 `TOOL_SCHEMAS` → 自动落 `_BASE_LOCAL_NAMES`/`CORE_TOOL_NAMES`。

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_knowledge_tools.py
import pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
import app.models  # noqa: F401


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _seed(db):
    from app.models.knowledge_doc import KnowledgeDoc
    db.add_all([
        KnowledgeDoc(slug="sdk", title="事件 SDK", summary="写侧", category="二次开发",
                     body_md="afterFormData", status="published"),
        KnowledgeDoc(slug="draft1", title="草稿", summary="x", category="搭建",
                     body_md="y", status="draft"),
    ])
    await db.commit()


@pytest.mark.asyncio
async def test_read_knowledge_states(db):
    from app.ai_chat.tools import execute_read_knowledge
    await _seed(db)
    ok = await execute_read_knowledge({"slug": "sdk"}, None, db)
    assert "afterFormData" in ok and "事件 SDK" in ok
    assert "不存在" in await execute_read_knowledge({"slug": "draft1"}, None, db)  # draft 不可读
    assert "不存在" in await execute_read_knowledge({"slug": "zzz"}, None, db)
    assert "缺少" in await execute_read_knowledge({}, None, db)


@pytest.mark.asyncio
async def test_search_knowledge_hit_and_miss(db):
    from app.ai_chat.tools import execute_search_knowledge
    await _seed(db)
    hit = await execute_search_knowledge({"query": "写侧"}, None, db)
    assert "sdk" in hit
    assert "未检索到" in await execute_search_knowledge({"query": "完全不相关XYZ"}, None, db)


def test_knowledge_tools_registered_as_core():
    from app.ai_chat.tools import TOOL_HANDLERS, _BASE_LOCAL_NAMES, CORE_TOOL_NAMES
    for name in ("read_knowledge", "search_knowledge"):
        assert name in TOOL_HANDLERS
        assert name in _BASE_LOCAL_NAMES   # 自动随 TOOL_SCHEMAS
        assert name in CORE_TOOL_NAMES     # 恒在,不被延迟
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_knowledge_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'execute_read_knowledge'`。

- [ ] **Step 3: Add the two tool schemas**

在 `backend/app/ai_chat/tools.py` 的 `TOOL_SCHEMAS` 列表里,`use_skill` 那一项之后(列表闭合 `]` 之前,约 308 行)插入:

```python
    {
        "type": "function",
        "function": {
            "name": "read_knowledge",
            "description": (
                "读取平台知识库中一篇规范文档的全文(搭建/二次开发/平台规范等)。"
                "文档清单见系统提示「平台知识库」。需要某条规范细节时调它。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"slug": {"type": "string", "description": "文档 slug(与清单一致)"}},
                "required": ["slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "在平台知识库里按关键词检索规范文档,返回命中文档的 slug/标题/摘要。"
                "不确定读哪篇、或清单里没直接对上时用它。"
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索关键词"}},
                "required": ["query"],
            },
        },
    },
```

- [ ] **Step 4: Add the two execute functions**

在 `tools.py` 各 `execute_*` 函数区(如 `execute_use_skill` 之后)加:

```python
async def execute_read_knowledge(args: dict, session, db) -> str:
    slug = (args.get("slug") or "").strip()
    if not slug:
        return "错误：缺少 slug 参数"
    from app.knowledge_base import get_published_doc
    doc = await get_published_doc(db, slug)
    if not doc:
        return f"错误：知识库中不存在已发布的文档 slug='{slug}'(可先用 search_knowledge 检索)"
    return f"# {doc.title}\n\n{doc.body_md}"


async def execute_search_knowledge(args: dict, session, db) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "错误：缺少 query 参数"
    from app.knowledge_base import search_published_docs
    docs = await search_published_docs(db, query)
    if not docs:
        return f"知识库中未检索到与 '{query}' 相关的规范文档。"
    lines = [f"检索到 {len(docs)} 篇相关规范(用 read_knowledge(slug) 读全文):"]
    for d in docs:
        snippet = (d.summary or d.body_md or "")[:200]
        lines.append(f"- [{d.category}] {d.slug}: {d.title} — {snippet}")
    return "\n".join(lines)
```

- [ ] **Step 5: Register in `TOOL_HANDLERS`**

在 `TOOL_HANDLERS` dict(约 1227 行,`"use_skill": execute_use_skill,` 之后)加:

```python
    "read_knowledge": execute_read_knowledge,
    "search_knowledge": execute_search_knowledge,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_knowledge_tools.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai_chat/tools.py backend/tests/test_knowledge_tools.py
git commit -m "feat(knowledge): read_knowledge / search_knowledge 工具(base-local)"
```

---

### Task 4: 注入知识库清单进 run_agent

**Files:**
- Modify: `backend/app/ai_chat/agent.py`(新增 `_append_knowledge_manifest`;在 902 行 `_append_skill_manifest(messages)` 后加 `await _append_knowledge_manifest(messages, db)`)
- Test: `backend/tests/test_knowledge_manifest_inject.py`

**Interfaces:**
- Consumes: `knowledge_base.list_published_docs` / `build_knowledge_manifest`(Task 2)
- Produces: `async _append_knowledge_manifest(messages: list[dict], db) -> None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_knowledge_manifest_inject.py
import pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
import app.models  # noqa: F401


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_manifest_appended_to_system(db):
    from app.ai_chat.agent import _append_knowledge_manifest
    from app.models.knowledge_doc import KnowledgeDoc
    db.add(KnowledgeDoc(slug="sdk", title="事件 SDK", summary="写侧", category="二次开发",
                        body_md="x", status="published"))
    await db.commit()
    msgs = [{"role": "system", "content": "BASE"}]
    await _append_knowledge_manifest(msgs, db)
    assert msgs[0]["content"].startswith("BASE")
    assert "平台知识库" in msgs[0]["content"] and "sdk: 事件 SDK" in msgs[0]["content"]


@pytest.mark.asyncio
async def test_manifest_empty_is_noop(db):
    from app.ai_chat.agent import _append_knowledge_manifest
    msgs = [{"role": "system", "content": "BASE"}]
    await _append_knowledge_manifest(msgs, db)   # 空库
    assert msgs[0]["content"] == "BASE"


@pytest.mark.asyncio
async def test_manifest_skips_non_system_head(db):
    from app.ai_chat.agent import _append_knowledge_manifest
    from app.models.knowledge_doc import KnowledgeDoc
    db.add(KnowledgeDoc(slug="s", title="T", summary="S", category="搭建", body_md="x", status="published"))
    await db.commit()
    msgs = [{"role": "user", "content": "hi"}]
    await _append_knowledge_manifest(msgs, db)   # 头不是 system → 不动
    assert msgs[0]["content"] == "hi"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_knowledge_manifest_inject.py -v`
Expected: FAIL — `ImportError: cannot import name '_append_knowledge_manifest'`。

- [ ] **Step 3: Add `_append_knowledge_manifest`**

在 `agent.py` 的 `_append_skill_manifest`(76 行)之后加(注意是 **async**,因为要查 DB):

```python
async def _append_knowledge_manifest(messages: list[dict], db) -> None:
    """把平台知识库 published 文档目录追加到 system message(渐进披露)。

    空库 no-op、异常不致命 —— 与 _append_skill_manifest 同模式,但内容来自 DB。
    """
    try:
        from app.knowledge_base import list_published_docs, build_knowledge_manifest
        manifest = build_knowledge_manifest(await list_published_docs(db))
    except Exception as exc:  # noqa: BLE001 — 知识库扫描失败不应中断对话
        logger.warning("knowledge manifest 注入失败: %r", exc)
        return
    if manifest and messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
        messages[0]["content"] = (messages[0].get("content") or "") + manifest
    elif manifest:
        logger.warning("knowledge manifest skipped: messages[0] is not a system message")
```

- [ ] **Step 4: Call it in run_agent**

在 `agent.py:902` `_append_skill_manifest(messages)` 之后加一行(该处在 `_run_agent_inner` 内,`db` 在作用域):

```python
    _append_skill_manifest(messages)
    await _append_knowledge_manifest(messages, db)   # 平台知识库目录(渐进披露)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_knowledge_manifest_inject.py -v`
Expected: PASS

- [ ] **Step 6: Full backend test sweep(防回归)**

Run: `cd backend && python -m pytest tests/test_knowledge_*.py -v`
Expected: 全 PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/app/ai_chat/agent.py backend/tests/test_knowledge_manifest_inject.py
git commit -m "feat(knowledge): 注入知识库清单进 run_agent(wire-once 覆盖全 profile)"
```

---

## Phase 2 — 编辑面(平台管理员 CRUD + UI)

### Task 5: require_platform_admin 依赖

**Files:**
- Modify: `backend/app/deps.py`(在 `require_tenant_admin`,336 行后加)
- Test: `backend/tests/test_require_platform_admin.py`

**Interfaces:**
- Produces: `async require_platform_admin(ctx) -> AuthContext`(非平台管理员抛 403)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_require_platform_admin.py
import pytest
from types import SimpleNamespace
from fastapi import HTTPException


def _ctx(role, is_pa):
    return SimpleNamespace(tenant_role=role, user=SimpleNamespace(is_platform_admin=is_pa))


@pytest.mark.asyncio
async def test_allows_platform_admin():
    from app.deps import require_platform_admin
    ctx = _ctx("platform_admin", False)
    assert await require_platform_admin(ctx) is ctx


@pytest.mark.asyncio
async def test_allows_user_flag():
    from app.deps import require_platform_admin
    ctx = _ctx("member", True)
    assert await require_platform_admin(ctx) is ctx


@pytest.mark.asyncio
async def test_rejects_tenant_admin():
    from app.deps import require_platform_admin
    with pytest.raises(HTTPException) as ei:
        await require_platform_admin(_ctx("tenant_admin", False))
    assert ei.value.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_require_platform_admin.py -v`
Expected: FAIL — `ImportError: cannot import name 'require_platform_admin'`。

- [ ] **Step 3: Add the dependency**

在 `backend/app/deps.py` 的 `require_tenant_admin` 之后加:

```python
async def require_platform_admin(
    ctx: Annotated[AuthContext, Depends(get_auth_context)]
) -> AuthContext:
    """Require platform admin role."""
    if ctx.tenant_role != "platform_admin" and not ctx.user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要平台管理员权限",
        )
    return ctx
```

> 注:测试直接传 `SimpleNamespace` 调函数本体(绕过 `Depends`),验证纯逻辑;`Depends(get_auth_context)` 仅在真实请求注入时生效。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_require_platform_admin.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/deps.py backend/tests/test_require_platform_admin.py
git commit -m "feat(deps): require_platform_admin 依赖"
```

---

### Task 6: knowledge CRUD 路由

**Files:**
- Create: `backend/app/routes/knowledge.py`
- Modify: `backend/app/main.py`(注册路由,镜像 skills 路由的 include 方式)
- Test: `backend/tests/test_knowledge_routes.py`

**Interfaces:**
- Consumes: `KnowledgeDoc`、`require_platform_admin`、`get_db`
- Produces: `router`(prefix `/knowledge`),端点 `GET /docs`、`GET /docs/{slug}`、`POST /docs`、`PUT /docs/{slug}`、`DELETE /docs/{slug}`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_knowledge_routes.py
import pytest, pytest_asyncio
from types import SimpleNamespace
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.deps import require_platform_admin
import app.models  # noqa: F401


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_db():
        async with Session() as s:
            yield s

    from app.routes import knowledge
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api")
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[require_platform_admin] = lambda: SimpleNamespace(user=SimpleNamespace(id=1))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_crud_flow(client):
    r = await client.post("/api/knowledge/docs", json={
        "slug": "sdk", "title": "事件 SDK", "summary": "写侧", "category": "二次开发",
        "body_md": "afterFormData", "status": "published"})
    assert r.status_code == 200, r.text
    assert (await client.get("/api/knowledge/docs")).json()["docs"][0]["slug"] == "sdk"
    assert (await client.get("/api/knowledge/docs/sdk")).json()["body_md"] == "afterFormData"
    r = await client.put("/api/knowledge/docs/sdk", json={
        "slug": "sdk", "title": "事件 SDK v2", "summary": "写侧", "category": "二次开发",
        "body_md": "updated", "status": "published"})
    assert r.json()["title"] == "事件 SDK v2"
    assert (await client.delete("/api/knowledge/docs/sdk")).json()["ok"] is True
    assert (await client.get("/api/knowledge/docs/sdk")).status_code == 404


@pytest.mark.asyncio
async def test_duplicate_slug_409(client):
    body = {"slug": "x", "title": "T", "summary": "", "category": "搭建", "body_md": "b", "status": "draft"}
    assert (await client.post("/api/knowledge/docs", json=body)).status_code == 200
    assert (await client.post("/api/knowledge/docs", json=body)).status_code == 409


@pytest.mark.asyncio
async def test_non_admin_403():
    # 不覆盖 require_platform_admin → 真实依赖,无 token → 401/403
    from app.routes import knowledge
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/knowledge/docs")).status_code in (401, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_knowledge_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: app.routes.knowledge`。

- [ ] **Step 3: Create the route**

```python
# backend/app/routes/knowledge.py
"""平台知识库(规范库)管理 — /knowledge CRUD。仅平台管理员可读写;
agent 不经此路由,直接查 DB(app.knowledge_base)。"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.deps import AuthContext, require_platform_admin
from app.models.knowledge_doc import KnowledgeDoc

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class DocIn(BaseModel):
    slug: str
    title: str
    summary: str = ""
    category: str = "平台规范"
    tags: Optional[str] = None
    body_md: str
    status: str = "draft"


class DocOut(BaseModel):
    id: int
    slug: str
    title: str
    summary: str
    category: str
    tags: Optional[str]
    body_md: str
    status: str
    updated_at: datetime

    @classmethod
    def of(cls, d: KnowledgeDoc) -> "DocOut":
        return cls(id=d.id, slug=d.slug, title=d.title, summary=d.summary,
                   category=d.category, tags=d.tags, body_md=d.body_md,
                   status=d.status, updated_at=d.updated_at)


@router.get("/docs")
async def list_docs(
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Optional[str] = None,
    status: Optional[str] = None,
):
    stmt = select(KnowledgeDoc).where(KnowledgeDoc.tenant_id.is_(None))
    if category:
        stmt = stmt.where(KnowledgeDoc.category == category)
    if status:
        stmt = stmt.where(KnowledgeDoc.status == status)
    res = await db.execute(stmt.order_by(KnowledgeDoc.category, KnowledgeDoc.title))
    return {"docs": [DocOut.of(d).model_dump() for d in res.scalars().all()]}


@router.get("/docs/{slug}")
async def get_doc(
    slug: str,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    res = await db.execute(select(KnowledgeDoc).where(
        KnowledgeDoc.slug == slug, KnowledgeDoc.tenant_id.is_(None)))
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "文档不存在")
    return DocOut.of(d).model_dump()


@router.post("/docs")
async def create_doc(
    body: DocIn,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if (await db.execute(select(KnowledgeDoc).where(KnowledgeDoc.slug == body.slug))).scalar_one_or_none():
        raise HTTPException(409, f"slug 已存在: {body.slug}")
    d = KnowledgeDoc(slug=body.slug, title=body.title, summary=body.summary,
                     category=body.category, tags=body.tags, body_md=body.body_md,
                     status=body.status, tenant_id=None, updated_by=ctx.user.id)
    db.add(d)
    await db.commit()           # get_db 不 autocommit,必须显式 commit
    await db.refresh(d)
    return DocOut.of(d).model_dump()


@router.put("/docs/{slug}")
async def update_doc(
    slug: str,
    body: DocIn,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    res = await db.execute(select(KnowledgeDoc).where(
        KnowledgeDoc.slug == slug, KnowledgeDoc.tenant_id.is_(None)))
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "文档不存在")
    d.title, d.summary, d.category = body.title, body.summary, body.category
    d.tags, d.body_md, d.status = body.tags, body.body_md, body.status
    d.updated_by = ctx.user.id
    await db.commit()
    await db.refresh(d)
    return DocOut.of(d).model_dump()


@router.delete("/docs/{slug}")
async def delete_doc(
    slug: str,
    ctx: Annotated[AuthContext, Depends(require_platform_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    res = await db.execute(select(KnowledgeDoc).where(
        KnowledgeDoc.slug == slug, KnowledgeDoc.tenant_id.is_(None)))
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(404, "文档不存在")
    await db.delete(d)
    await db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Register router in main.py**

在 `backend/app/main.py` 里找到 skills 路由注册那一段(`from app.routes import ... skills ...` + `app.include_router(skills.router, prefix="/api")`),照同样方式加:

```python
from app.routes import knowledge  # 与其它 routes import 放一起
app.include_router(knowledge.router, prefix="/api")
```

(若 main.py 用集中列表注册,则把 `knowledge.router` 加进同一列表;镜像 `skills.router` 的写法。)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_knowledge_routes.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/knowledge.py backend/app/main.py backend/tests/test_knowledge_routes.py
git commit -m "feat(knowledge): /knowledge CRUD 路由(平台管理员)"
```

---

### Task 7: 前端 API 客户端 + 管理页 + 路由

**Files:**
- Create: `frontend/src/api/knowledge.ts`
- Create: `frontend/src/views/KnowledgeBasePage.vue`
- Modify: `frontend/src/router/index.ts`(加路由 + 导航入口,镜像 `PlatformTenants.vue` 的注册方式)
- Test: `frontend/src/api/knowledge.spec.ts`(api 客户端单测)

**Interfaces:**
- Consumes: 后端 `/api/knowledge/*`(Task 6)
- Produces: `listKnowledgeDocs / getKnowledgeDoc / createKnowledgeDoc / updateKnowledgeDoc / deleteKnowledgeDoc`

- [ ] **Step 1: Create the API client**

```typescript
// frontend/src/api/knowledge.ts
import request from '@/utils/request'

// baseURL 已是 /api;request 响应拦截器已 unwrap response.data。
export interface KnowledgeDoc {
  id: number
  slug: string
  title: string
  summary: string
  category: string
  tags: string | null
  body_md: string
  status: 'draft' | 'published'
  updated_at: string
}

export async function listKnowledgeDocs(params?: { category?: string; status?: string }): Promise<KnowledgeDoc[]> {
  const data = await request.get<any, { docs?: KnowledgeDoc[] }>('/knowledge/docs', { params })
  return data?.docs || []
}
export async function getKnowledgeDoc(slug: string): Promise<KnowledgeDoc> {
  return request.get<any, KnowledgeDoc>(`/knowledge/docs/${encodeURIComponent(slug)}`)
}
export async function createKnowledgeDoc(body: Partial<KnowledgeDoc>): Promise<KnowledgeDoc> {
  return request.post<any, KnowledgeDoc>('/knowledge/docs', body)
}
export async function updateKnowledgeDoc(slug: string, body: Partial<KnowledgeDoc>): Promise<KnowledgeDoc> {
  return request.put<any, KnowledgeDoc>(`/knowledge/docs/${encodeURIComponent(slug)}`, body)
}
export async function deleteKnowledgeDoc(slug: string): Promise<void> {
  await request.delete<any, { ok: boolean }>(`/knowledge/docs/${encodeURIComponent(slug)}`)
}
```

- [ ] **Step 2: Write + run the api client test**

```typescript
// frontend/src/api/knowledge.spec.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
vi.mock('@/utils/request', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))
import request from '@/utils/request'
import { listKnowledgeDocs, createKnowledgeDoc } from './knowledge'

describe('knowledge api', () => {
  beforeEach(() => vi.clearAllMocks())
  it('listKnowledgeDocs unwraps docs', async () => {
    ;(request.get as any).mockResolvedValue({ docs: [{ slug: 'a' }] })
    expect(await listKnowledgeDocs()).toEqual([{ slug: 'a' }])
    expect(request.get).toHaveBeenCalledWith('/knowledge/docs', { params: undefined })
  })
  it('createKnowledgeDoc posts body', async () => {
    ;(request.post as any).mockResolvedValue({ slug: 'a' })
    await createKnowledgeDoc({ slug: 'a', title: 'T', body_md: 'x' })
    expect(request.post).toHaveBeenCalledWith('/knowledge/docs', { slug: 'a', title: 'T', body_md: 'x' })
  })
})
```

Run: `cd frontend && npx vitest run src/api/knowledge.spec.ts`
Expected: PASS

- [ ] **Step 3: Create the admin page**

新建 `frontend/src/views/KnowledgeBasePage.vue`,镜像 `frontend/src/views/PlatformTenants.vue` / `McpToolsPage.vue` 的 Element Plus 列表页结构。要素:
- `onMounted` 调 `listKnowledgeDocs()` 填表格(列:slug、title、category、status、updated_at)。
- 「新建」按钮 + 行内「编辑」「删除」。
- 编辑用 `el-dialog`/`el-drawer`:`el-input` slug/title/summary/tags + `el-select` category(选项:搭建/二次开发/平台规范) + `el-input type="textarea"` 编辑 `body_md`(markdown 纯文本即可,v1 不上富文本) + `el-switch`/`el-select` 控 status(draft/published)。
- 保存:有 id 走 `updateKnowledgeDoc(slug, form)`,否则 `createKnowledgeDoc(form)`;成功后 `ElMessage.success` + 刷新列表。
- 删除:`ElMessageBox.confirm` 后 `deleteKnowledgeDoc(slug)`。

> 不写满整页代码:严格照 `PlatformTenants.vue` 的 script setup + `<el-table>` + 弹窗表单骨架改字段名即可,避免引入与现有页面不一致的风格。

- [ ] **Step 4: Register route + nav**

在 `frontend/src/router/index.ts` 里照 `PlatformTenants` 的路由项加一条:

```typescript
{
  path: '/knowledge',
  name: 'knowledge-base',
  component: () => import('@/views/KnowledgeBasePage.vue'),
  meta: { title: '平台知识库', requiresPlatformAdmin: true },  // meta 键名对齐 PlatformTenants 现有用法
},
```

并在平台管理员能看到的导航处(`PlatformTenants` 入口旁)加一个「平台知识库」入口。具体导航组件以 `PlatformTenants` 当前挂的位置为准。

- [ ] **Step 5: Verify in preview**

启动 dev server,以平台管理员登录,打开 `/knowledge`:新建一篇 published 文档 → 列表出现 → 编辑改 body → 删除。用 preview 工具截图确认。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/knowledge.ts frontend/src/api/knowledge.spec.ts frontend/src/views/KnowledgeBasePage.vue frontend/src/router/index.ts
git commit -m "feat(knowledge): 前端管理页 + API + 路由"
```

---

## Phase 3 — seed + 防漂移

### Task 8: 盘点现有「搭建/二次开发」规范(调研,产出清单)

**Files:**
- Create: `docs/knowledge-seed-inventory-2026-06-26.md`(盘点结果)

- [ ] **Step 1: 扫描规范出处**

跑下列检索,定位现在散落的规范文本:

```bash
cd backend
grep -rn "definesys\|afterFormData\|afterTableData\|SYSTEM_PROMPT\|system_prompt" app/agents/profile.py app/coding/pipeline.py app/harness/profiles/ | grep -v venv
grep -rln "你是\|规范\|约定\|步骤\|必须\|禁止" app/agents app/coding app/harness | grep -v venv
```

并查阅已知调研文档:`docs/research-apaas-event-python-spec-2026-06-05.md`(definesys 读侧契约已摸透,写侧未决)。

- [ ] **Step 2: 产出盘点清单**

在 `docs/knowledge-seed-inventory-2026-06-26.md` 里逐条列出:出处文件:行 → 规范主题 → 建议 slug/category → 可否搬(真规范=可搬;工程脚手架/接线=留代码)。**诚实标注**:写侧 SDK 文档若仓库内确实没有,则该篇 seed 内容待用户提供 definesys 写 SDK 文档,本期先建占位(status=draft,不进 agent)。

- [ ] **Step 3: Commit**

```bash
git add docs/knowledge-seed-inventory-2026-06-26.md
git commit -m "docs(knowledge): 现有规范盘点(seed 输入)"
```

---

### Task 9: seed 初始文档 + prompt 留薄(防漂移)

**Files:**
- Create: `backend/scripts/seed_knowledge_docs.py`(幂等 upsert seed 文档)
- Modify: 盘点中标「可搬」的 prompt/常量文件(对应段落删/留薄)
- Test: `backend/tests/test_seed_knowledge_docs.py`

**Interfaces:**
- Consumes: `KnowledgeDoc`、盘点清单(Task 8)

- [ ] **Step 1: Write the failing test(幂等 upsert)**

```python
# backend/tests/test_seed_knowledge_docs.py
import pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select
from app.database import Base
import app.models  # noqa: F401


@pytest_asyncio.fixture
async def session_maker():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_is_idempotent(session_maker):
    from app.scripts.seed_knowledge_docs import upsert_seed_docs
    from app.models.knowledge_doc import KnowledgeDoc
    async with session_maker() as db:
        await upsert_seed_docs(db)
        await upsert_seed_docs(db)   # 再跑一次不重复
    async with session_maker() as db:
        rows = (await db.execute(select(KnowledgeDoc))).scalars().all()
        slugs = [r.slug for r in rows]
        assert len(slugs) == len(set(slugs))     # 无重复
        assert len(slugs) >= 1
```

> 脚本放 `backend/scripts/`,但为可测试,核心 `upsert_seed_docs(db)` 放可导入模块 `backend/app/scripts/seed_knowledge_docs.py`;CLI 包装从这里 import。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_seed_knowledge_docs.py -v`
Expected: FAIL — 模块不存在。

- [ ] **Step 3: Write the seed module**

```python
# backend/app/scripts/seed_knowledge_docs.py
"""幂等 upsert 平台知识库 seed 文档。按 slug upsert,可重复跑。

SEED 内容来自 docs/knowledge-seed-inventory-2026-06-26.md 标「可搬」的条目。
仓库内查不到来源的(如 definesys 写侧 SDK)建占位 status='draft'(不进 agent),待补。
"""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.knowledge_doc import KnowledgeDoc

SEED: list[dict] = [
    # 示例:从 profile.py dev-apaas 提示词搬出的「二次开发工作方式」约定。
    {
        "slug": "dev-apaas-working-rules",
        "title": "二次开发工作方式约定",
        "summary": "在已有工作区内开发的核心约定:确认即开干、最多问一次、在绑定 ws 内干活",
        "category": "二次开发",
        "body_md": "## 工作方式\n- 确认即开干……\n- 先 read/glob/grep 看清现有代码再动手……\n",
        "status": "published",
    },
    # 占位:写侧 SDK 文档仓库内无来源,建 draft,待用户提供 definesys 写 SDK 文档。
    {
        "slug": "definesys-event-write-sdk",
        "title": "definesys 自定义事件 写侧 SDK 规范",
        "summary": "(占位)写侧 SDK 可用 API,待补充权威文档",
        "category": "二次开发",
        "body_md": "> 待补充:definesys 写 SDK 文档(用户提供后转 published)。\n",
        "status": "draft",
    },
]


async def upsert_seed_docs(db: AsyncSession) -> int:
    n = 0
    for item in SEED:
        existing = (await db.execute(
            select(KnowledgeDoc).where(KnowledgeDoc.slug == item["slug"]))).scalar_one_or_none()
        if existing:
            for k, v in item.items():
                setattr(existing, k, v)
        else:
            db.add(KnowledgeDoc(**item, tenant_id=None))
        n += 1
    await db.commit()
    return n
```

并加 CLI 包装 `backend/scripts/seed_knowledge_docs.py`:

```python
"""CLI:python -m scripts.seed_knowledge_docs(对当前 DATABASE_URL 跑 seed)。"""
import asyncio
from app.database import AsyncSessionLocal
from app.scripts.seed_knowledge_docs import upsert_seed_docs


async def _main():
    async with AsyncSessionLocal() as db:
        n = await upsert_seed_docs(db)
        print(f"seeded/updated {n} knowledge docs")


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: prompt 留薄(防漂移)**

对 Task 8 盘点中标「可搬且已 seed published」的条目,把对应 prompt/常量段落删掉或替换成一行引导(例:在 `profile.py` 的 `_DEV_APAAS_SYSTEM_PROMPT` 里被搬走的细则,改为「详细约定见知识库 `dev-apaas-working-rules`,需要时 read_knowledge」)。**只搬已 published 的**;draft 占位的不要动 prompt(否则规范暂时丢失)。每搬一条,跑一遍相关既有测试确认 prompt 装配不破。

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_seed_knowledge_docs.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/scripts/seed_knowledge_docs.py backend/scripts/seed_knowledge_docs.py backend/tests/test_seed_knowledge_docs.py
git add -u  # 被留薄的 prompt 文件
git commit -m "feat(knowledge): seed 初始文档 + prompt 留薄(防漂移)"
```

---

## Phase 4 — 验证

### Task 10: MySQL 模式校验 + 全量回归 + 端到端

- [ ] **Step 1: MySQL create_all 校验**

docker 起 mysql:8,把 `DATABASE_URL` 指过去跑一次建表,确认 `knowledge_docs`(尤其 `slug` 唯一索引、`body_md` LONGTEXT)能建,不报索引超长:

```bash
docker run -d --name kb-mysql -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=fb -p 3307:3306 mysql:8
# 等就绪后,用指向该库的 DATABASE_URL 触发一次 create_all(起一次 backend 或跑建表脚本)
docker rm -f kb-mysql
```

Expected: 建表成功,无 `Specified key was too long` 之类报错。

- [ ] **Step 2: 后端全量回归**

Run: `cd backend && python -m pytest -q`
Expected: 知识库相关全绿;既有失败数与改动前一致(对照基线,不得新增红)。

- [ ] **Step 3: 端到端(真 LLM)**

本地 tenant + gpt-5.5 omnigate:经管理页发布一篇 `category=二次开发` 的 published 文档(如 `dev-apaas-working-rules` 或一篇明确含某 API 用法的规范)→ 开一个 `mode=code` 会话(dev-apaas profile)→ 提一个需要该规范的需求 → 观察 agent 是否主动 `search_knowledge`/`read_knowledge` 并据此作答。用 agent 可观测 trace 核对工具调用。

> ⚠️ 改后端必重启 backend 进程(`run.py` reload=False);浏览器若实时不渲染,刷新即可(缓存,非 bug)。

- [ ] **Step 4: Commit(若有修正)**

```bash
git commit -am "test(knowledge): MySQL 校验 + e2e 验证修正"
```

---

## 配套清理(本计划范围外,独立 spec)

旧 `/coding/pipeline` 引擎退役 + 删除是**单独一份 spec/plan**,不并入本计划(见设计文档 `docs/superpowers/specs/2026-06-26-platform-knowledge-base-design.md` 的「配套清理」一节)。删前先查清 `frontend/src/api/harness.ts` 的 `codingPipelineUrl`、`useCodingPipeline` 等是否还有活引用。

---

## Self-Review

- **Spec 覆盖**:范围/权限→Task 1+5+6;数据模型→Task 1;编辑面→Task 6+7;消费(注入+工具)→Task 3+4;检索可移植→Task 2;seed+防漂移→Task 8+9;非目标(不向量/不接旧 pipeline/不租户覆盖)→全程未触;配套清理→独立节。**全覆盖**。
- **占位符**:Task 7(Vue 页面)、Task 8/9(seed)按性质给「过程 + 范本 + 一个 worked example」而非逐行,因内容依赖盘点结果;已诚实标注且给可跑骨架,非空头占位。
- **类型一致**:`KnowledgeDoc` 字段、`list_published_docs/get_published_doc/search_published_docs/build_knowledge_manifest`、`execute_read_knowledge/execute_search_knowledge`、`require_platform_admin`、`/knowledge/docs` 端点签名在各任务间一致。
- **spec 订正**:设计文档原写「工具必须进 tool_registry.yaml」——经核实 base 本地工具不进 registry,本计划据实改为注册进 `ai_chat/tools.py`;设计文档已同步订正。
