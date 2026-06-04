# Agent 可观测模块 Phase 1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给睿鲸 AI 搭一个统一 agent 可观测底座（`agent_run` / `agent_step` 两表 + `recorder` 写入门面 + token 必采），把 ai-builder 一条链路埋点跑通，并提供租户只看自己的 Trace 下钻视图。

**Architecture:** 新增两张旁路表 + 一个 `app/observability/recorder.py` 写入门面（每个方法用独立 `AsyncSessionLocal` 会话、吞掉自身所有异常，绝不影响主 agent）。在 `ai_chat/agent.py::run_agent` 外面套一层薄 wrapper 管 run 生命周期（start/end），run 内部在「每轮 LLM done」「每个 tool 结束」两处单点记 step；token 通过给 `_call_llm_stream` 的流式 payload 加 `stream_options.include_usage` 并捕获 usage chunk 拿到。现有 `AIChatToolCall` 保留，埋点处双写。读 API（`GET /api/agent-runs`、`GET /api/agent-runs/{run_id}`）强制 `where tenant_id = 当前租户`，前端用 Element Plus `el-drawer` 做 Trace 抽屉（复用 ToolCard 视觉语言）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async（`Mapped`/`mapped_column`）、本地 SQLite / 线上 MySQL（无 Alembic，`Base.metadata.create_all` 自动建表）、pytest + pytest-asyncio（`asyncio_mode=auto`、内存 SQLite）、Vue 3 + Element Plus + axios。Python 3.13（`.venv`）。

**范围边界（Phase 1 只做这些，其余进 Phase 2）：** 仅 ai-builder 一条链路埋点（config / coding / builder 三条不动）；只有租户视角的 trace 视图（无 dashboard 聚合、无平台管理员全局页）；不迁老数据（从上线起记）；不做成本估算 / 告警 / 留存清理。

---

## File Structure

新增：
- `backend/app/models/agent_observability.py` — `AgentRun` + `AgentStep` 两个 ORM 模型（本文件自带 `BigText` 定义，跟 `models/ai_chat.py` 同款，避免循环导入）。
- `backend/app/observability/__init__.py` — 空包标记。
- `backend/app/observability/recorder.py` — 写入门面：`start_run` / `record_step` / `end_run`，旁路、吞异常、独立会话。
- `backend/app/routes/agent_observability.py` — 读 API 路由（租户作用域）。
- `backend/tests/test_agent_observability_models.py` — 模型建表与默认值测试。
- `backend/tests/test_agent_observability_recorder.py` — recorder 生命周期 + 聚合 + 吞异常测试。
- `backend/tests/test_agent_observability_llm_usage.py` — `_call_llm_stream` 采 token 测试。
- `backend/tests/test_agent_observability_run_agent.py` — run_agent 埋点端到端（mock LLM）测试。
- `backend/tests/test_agent_observability_api.py` — 读 API 租户隔离测试。
- `frontend/src/api/agentObservability.ts` — 前端 API 客户端。
- `frontend/src/components/common/AgentRunTraceDrawer.vue` — Trace 抽屉组件。

修改：
- `backend/app/models/__init__.py` — early-import 块加一行注册新模型。
- `backend/app/database.py` — `init_db()` 加一行 import 触发建表。
- `backend/app/ai_chat/agent.py` — import recorder；token 捕获改 `_call_llm_stream`；run_agent 改薄 wrapper + 内部记 step；落 assistant 消息时把 run_id 塞进 `extra_meta`、`assistant_message` 事件带上 run_id。
- `backend/app/routes/ai_chat.py` — `_message_to_dict` 从 `extra_meta` 透出 `run_id`（让刷新后的历史消息也能挂「查看本次 trace」）。
- `backend/app/main.py` — 注册 `agent_observability` 路由。
- `frontend/src/api/aiChat.ts` — `AIChatMessage` 接口加 `run_id`。
- `frontend/src/views/AIChatPage.vue` — 捕获 `run_started` 的 run_id；`agentMessages` 把 run_id 带进 `meta`；会话头部加「Agent 活动」入口；处理每条回复的 `open-trace`；挂载 Trace 抽屉。
- `frontend/src/components/common/AgentConversation.vue` — assistant 消息脚注（复制/反馈旁）加「查看本次 trace」按钮，`emit('open-trace', item)`。

---

## Task 1: AgentRun / AgentStep 模型 + 注册

**Files:**
- Create: `backend/app/models/agent_observability.py`
- Modify: `backend/app/models/__init__.py:32`（early-import 块尾）
- Modify: `backend/app/database.py`（`init_db()` 内 import 块）
- Test: `backend/tests/test_agent_observability_models.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_agent_observability_models.py`:

```python
"""Agent 可观测两张表建表 + 默认值。"""
from __future__ import annotations

import pytest

from app.models.agent_observability import AgentRun, AgentStep


@pytest.mark.asyncio
async def test_agent_run_defaults(db_session):
    run = AgentRun(
        run_id="run_abc",
        agent_type="ai_builder",
        tenant_id=7,
        user_id=3,
        session_id="42",
        model="gpt-5.5",
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    assert run.id is not None
    assert run.status == "running"
    assert run.total_prompt_tokens == 0
    assert run.total_completion_tokens == 0
    assert run.total_tokens == 0
    assert run.turn_count == 0
    assert run.started_at is not None
    assert run.created_at is not None
    assert run.ended_at is None


@pytest.mark.asyncio
async def test_agent_step_persists(db_session):
    step = AgentStep(
        run_id="run_abc",
        seq=1,
        step_type="llm",
        prompt_tokens=120,
        completion_tokens=34,
    )
    db_session.add(step)
    await db_session.commit()
    await db_session.refresh(step)

    assert step.id is not None
    assert step.run_id == "run_abc"
    assert step.seq == 1
    assert step.step_type == "llm"
    assert step.prompt_tokens == 120
    assert step.ts is not None
    # nullable 工具字段缺省为 None
    assert step.tool_name is None
    assert step.args_json is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.agent_observability'`

- [ ] **Step 3: 写模型**

Create `backend/app/models/agent_observability.py`:

```python
"""Agent 可观测统一底座 — 2 张表，所有 agent 链路的 run / step 都聚到这里。

- agent_run   一次运行（= 一条用户消息触发的完整工具循环）
- agent_step  run 内每一步（llm / tool / error / artifact）

写入只走 app/observability/recorder.py（旁路，吞自身异常，不影响主 agent）。
现有 AIChatToolCall / AgentTrace 等保留，埋点处双写。
关联用 run_id（uuid hex）做逻辑外键，不加硬 FK —— 跟 AgentTrace 一样，旁路表
不该因为主表行缺失而写不进去。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import String, Text, DateTime, Integer, JSON, Index
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 大结果文本：MySQL 用 LONGTEXT（4GB），SQLite 等价 TEXT。
# 本地定义（跟 models/ai_chat.py:24 同款），避免从 app.models 反向 import 造成循环。
BigText = Text().with_variant(LONGTEXT, "mysql")


class AgentRun(Base):
    """一次 agent 运行。"""

    __tablename__ = "agent_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    # ai_builder / config / coding / builder
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    tenant_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    app_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # model 不在 spec 表里，但 Phase 2「token→¥ 成本估算」明确需要按模型拆分，
    # 一列 nullable 几乎零成本，先采着，省得 Phase 2 再加列迁移。
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # running / success / error
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    __table_args__ = (
        # 租户作用域 + 时间倒序列表的复合索引
        Index("ix_agent_run_tenant_created", "tenant_id", "created_at"),
    )


class AgentStep(Base):
    """run 内一步。"""

    __tablename__ = "agent_step"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 逻辑外键 → AgentRun.run_id（不加硬 FK，旁路表）
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    # llm / tool / error / artifact
    step_type: Mapped[str] = mapped_column(String(16), nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    args_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    result_text: Mapped[Optional[str]] = mapped_column(BigText, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # llm step 用
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_agent_step_run_seq", "run_id", "seq"),
    )
```

- [ ] **Step 4: 注册模型（两处）**

在 `backend/app/models/__init__.py:32`（`SpecSection` import 那行之后）加一行：

```python
from app.models.spec_section import SpecSection  # noqa: F401  — design-v4 草稿层 SpecSection
from app.models.agent_observability import AgentRun, AgentStep  # noqa: F401  — Agent 可观测底座
```

在 `backend/app/database.py` 的 `init_db()` 函数里、其它 `import app.models.xxx` 那一串后面加一行（确保 `create_all` 能看到新表）：

```python
    import app.models.spec_document  # noqa: F401
    import app.models.agent_observability  # noqa: F401  — Agent 可观测底座
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_models.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: 确认整库 import 不破**

Run: `cd backend && .venv/bin/python -c "import app.models; import app.main; print('ok')"`
Expected: 打印 `ok`，无 ImportError / 循环导入报错

- [ ] **Step 7: 提交**

```bash
git add backend/app/models/agent_observability.py backend/app/models/__init__.py backend/app/database.py backend/tests/test_agent_observability_models.py
git commit -m "feat(observability): add agent_run / agent_step tables"
```

---

## Task 2: recorder 写入门面

**Files:**
- Create: `backend/app/observability/__init__.py`
- Create: `backend/app/observability/recorder.py`
- Test: `backend/tests/test_agent_observability_recorder.py`

> 设计要点：每个方法开自己的 `AsyncSessionLocal()` 会话（跟主 agent 的 db session 隔离 —— recorder 的 commit 绝不能把主流程半成品事务带翻，主流程 rollback 也牵连不到它）；所有异常 try/except 吞掉只 `logger.warning`。`end_run` 从 `agent_step` 用 SQL 聚合 token / turn_count，单一真相源。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_agent_observability_recorder.py`:

```python
"""recorder 生命周期 + 聚合 + 吞异常。

注意：recorder 内部用 app.database.AsyncSessionLocal 开会话，所以本测试要把
AsyncSessionLocal 指到一个共享的内存 SQLite engine（而不是用 db_session fixture
那个 per-test engine），否则 recorder 写的行跟断言查的不是同一个库。
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import app.database as database
from app.database import Base
from app.models.agent_observability import AgentRun, AgentStep
from app.observability import recorder


@pytest_asyncio.fixture
async def shared_db(monkeypatch):
    """共享内存 SQLite：用 StaticPool 让所有连接看同一个 :memory: 库。"""
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    # recorder 用 AsyncSessionLocal，把它指到本 engine
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    monkeypatch.setattr(recorder, "AsyncSessionLocal", Session)
    async with Session() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_full_lifecycle_aggregates_tokens(shared_db):
    run_id = await recorder.start_run(
        agent_type="ai_builder", tenant_id=7, user_id=3, session_id=42, model="gpt-5.5"
    )
    assert run_id and isinstance(run_id, str)

    await recorder.record_step(run_id, step_type="llm", seq=1, prompt_tokens=100, completion_tokens=20)
    await recorder.record_step(
        run_id, step_type="tool", seq=2, tool_name="read_attachment",
        args={"id": 1}, result_text="ok", status="success", duration_ms=12,
    )
    await recorder.record_step(run_id, step_type="llm", seq=3, prompt_tokens=80, completion_tokens=10)

    await recorder.end_run(run_id, status="success")

    run = (
        await shared_db.execute(select(AgentRun).where(AgentRun.run_id == run_id))
    ).scalar_one()
    assert run.status == "success"
    assert run.total_prompt_tokens == 180
    assert run.total_completion_tokens == 30
    assert run.total_tokens == 210
    assert run.turn_count == 2  # 两个 llm step
    assert run.ended_at is not None
    assert run.duration_ms is not None and run.duration_ms >= 0

    steps = (
        await shared_db.execute(
            select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)
        )
    ).scalars().all()
    assert [s.seq for s in steps] == [1, 2, 3]


@pytest.mark.asyncio
async def test_end_run_missing_run_is_noop(shared_db):
    # 不存在的 run_id：不抛，安静返回
    await recorder.end_run("does_not_exist", status="success")


@pytest.mark.asyncio
async def test_recorder_swallows_internal_errors(shared_db, monkeypatch):
    # 让 record_step 内部建会话就炸 —— recorder 必须吞掉，不能往外抛
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(recorder, "AsyncSessionLocal", _boom)
    # 不抛异常即通过
    await recorder.record_step("run_x", step_type="llm", seq=1, prompt_tokens=1)
    rid = await recorder.start_run(agent_type="ai_builder")
    assert isinstance(rid, str)  # start_run 即便写库失败也返回 id
    await recorder.end_run("run_x", status="error")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.observability'`

- [ ] **Step 3: 写 recorder**

Create `backend/app/observability/__init__.py`:

```python
"""Agent 可观测包：统一 run/step 底座的写入门面。"""
```

Create `backend/app/observability/recorder.py`:

```python
"""Agent 可观测写入门面（旁路）。

所有写入只经此处。任何异常都被吞掉 —— observability 绝不能影响主 agent 流程。
每个方法用独立 AsyncSessionLocal 会话，跟主 agent 的 db session 隔离，避免 recorder
的 commit 把主流程半成品事务带翻 / 被主流程 rollback 牵连。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import case, func, select

from app.database import AsyncSessionLocal
from app.models.agent_observability import AgentRun, AgentStep

logger = logging.getLogger(__name__)


async def start_run(
    *,
    agent_type: str,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
    session_id: Optional[Any] = None,
    app_id: Optional[Any] = None,
    model: Optional[str] = None,
) -> str:
    """开一条 run，返回 run_id（uuid hex）。

    即便写库失败也返回一个 id —— 后续 record_step 写的是孤儿 step（无害），
    end_run 查不到 run 自然 no-op。调用方因此永远拿到一个非空 run_id，省去 None 判断。
    """
    run_id = uuid.uuid4().hex
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                AgentRun(
                    run_id=run_id,
                    agent_type=agent_type,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=None if session_id is None else str(session_id),
                    app_id=None if app_id is None else str(app_id),
                    model=model,
                    status="running",
                    started_at=datetime.utcnow(),
                )
            )
            await db.commit()
    except Exception:
        logger.warning("[observability] start_run failed", exc_info=True)
    return run_id


async def record_step(
    run_id: str,
    *,
    step_type: str,
    seq: int,
    tool_name: Optional[str] = None,
    args: Optional[dict] = None,
    result_text: Optional[str] = None,
    status: Optional[str] = None,
    duration_ms: Optional[int] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
) -> None:
    """记一步。llm step 传 prompt/completion tokens；tool step 传 tool_name/args/result。"""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                AgentStep(
                    run_id=run_id,
                    seq=seq,
                    step_type=step_type,
                    tool_name=tool_name,
                    args_json=args,
                    result_text=result_text,
                    status=status,
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    ts=datetime.utcnow(),
                )
            )
            await db.commit()
    except Exception:
        logger.warning("[observability] record_step failed run_id=%s", run_id, exc_info=True)


async def end_run(run_id: str, *, status: str, error: Optional[str] = None) -> None:
    """收尾：状态 + duration + 从 steps 聚合 tokens / turn_count（llm step 数）。"""
    try:
        async with AsyncSessionLocal() as db:
            run = (
                await db.execute(select(AgentRun).where(AgentRun.run_id == run_id))
            ).scalar_one_or_none()
            if run is None:
                return
            now = datetime.utcnow()
            run.status = status
            run.error_message = error
            run.ended_at = now
            if run.started_at is not None:
                run.duration_ms = int((now - run.started_at).total_seconds() * 1000)
            agg = (
                await db.execute(
                    select(
                        func.coalesce(func.sum(AgentStep.prompt_tokens), 0),
                        func.coalesce(func.sum(AgentStep.completion_tokens), 0),
                        # turn_count = llm step 数；用 case-sum 而非 FILTER，跨 SQLite/MySQL 都稳
                        func.coalesce(
                            func.sum(case((AgentStep.step_type == "llm", 1), else_=0)), 0
                        ),
                    ).where(AgentStep.run_id == run_id)
                )
            ).one()
            run.total_prompt_tokens = int(agg[0] or 0)
            run.total_completion_tokens = int(agg[1] or 0)
            run.total_tokens = run.total_prompt_tokens + run.total_completion_tokens
            run.turn_count = int(agg[2] or 0)
            await db.commit()
    except Exception:
        logger.warning("[observability] end_run failed run_id=%s", run_id, exc_info=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_recorder.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/observability backend/tests/test_agent_observability_recorder.py
git commit -m "feat(observability): add recorder write facade with token aggregation"
```

---

## Task 3: `_call_llm_stream` 采 token

**Files:**
- Modify: `backend/app/ai_chat/agent.py:382-475`（`_call_llm_stream`）
- Test: `backend/tests/test_agent_observability_llm_usage.py`

> 关键：OpenAI 兼容流式默认不回 usage。要在 payload 加 `stream_options.include_usage`，网关才会在 `[DONE]` 前发一个 `choices: []` 但带 `usage` 的 chunk。现有代码第 440 行 `if not choices: continue` 会把这个 usage chunk 跳过 —— 所以捕获必须放在那行之前。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_agent_observability_llm_usage.py`:

```python
"""_call_llm_stream 把 usage chunk 的 token 透到 done 事件。"""
from __future__ import annotations

import asyncio
import json
import types

import pytest

import app.ai_chat.agent as agent_mod


class _FakeStreamResp:
    """假 httpx 流式 response：模拟 OpenAI include_usage 的 chunk 序列。"""

    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_lines(self):
        for ln in self._lines:
            yield ln

    async def aread(self):
        return b""

    def raise_for_status(self):
        return None


class _FakeClient:
    def __init__(self, lines):
        self._lines = lines
        self.sent_payload = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None, json=None):
        self.sent_payload = json
        return _FakeStreamResp(self._lines)


@pytest.mark.asyncio
async def test_stream_captures_usage_into_done(monkeypatch):
    # content chunk → usage chunk（choices 空）→ [DONE]
    lines = [
        'data: ' + json.dumps({"choices": [{"delta": {"content": "你好"}}]}),
        'data: ' + json.dumps({"choices": [], "usage": {"prompt_tokens": 111, "completion_tokens": 22, "total_tokens": 133}}),
        'data: [DONE]',
    ]
    captured = {}

    def _fake_async_client(*a, **kw):
        c = _FakeClient(lines)
        captured["client"] = c
        return c

    monkeypatch.setattr(agent_mod.httpx, "AsyncClient", _fake_async_client)

    cfg = types.SimpleNamespace(
        model="gpt-5.5", temperature=0.2, max_tokens=2048,
        base_url="http://llm", api_key="k",
    )
    # _apply_provider_payload_compat 读 cfg 的若干属性，给个 no-op 替身省事
    monkeypatch.setattr(agent_mod, "_apply_provider_payload_compat", lambda c, p: None)

    abort = asyncio.Event()
    events = []
    async for ev in agent_mod._call_llm_stream(cfg, [{"role": "user", "content": "hi"}], [], abort):
        events.append(ev)

    # payload 里带了 include_usage
    assert captured["client"].sent_payload["stream_options"] == {"include_usage": True}

    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert done[0]["usage"] == {"prompt_tokens": 111, "completion_tokens": 22, "total_tokens": 133}
    assert done[0]["message"]["content"] == "你好"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_llm_usage.py -v`
Expected: FAIL — `KeyError: 'stream_options'`（payload 没带）或 `KeyError: 'usage'`（done 没透 usage）

- [ ] **Step 3: 改 `_call_llm_stream`**

改 `backend/app/ai_chat/agent.py`。

(a) payload 加 `stream_options`（在 `"stream": True,` 之后，约 404 行）：

```python
        "stream": True,
        # 让 OpenAI 兼容网关在 [DONE] 前回一个带 usage 的 chunk（token 必采）
        "stream_options": {"include_usage": True},
    }
```

(b) 在 `accumulated_content = ""` 旁（约 407 行）加 usage 累加变量：

```python
    accumulated_content = ""
    usage_data: Optional[dict] = None
    tool_buf: dict[int, dict] = {}
```

(c) 在 `chunk = json.loads(data)` 的 try/except 之后、`choices = chunk.get("choices") or []` 之前（约 439 行）插入 usage 捕获 —— 必须在 `if not choices: continue` 之前，因为 usage chunk 的 choices 是空的：

```python
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                # usage chunk：choices 为空、带 usage（include_usage 开启后 [DONE] 前到达）
                if chunk.get("usage"):
                    usage_data = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
```

(d) done 事件带上 usage（约 469-475 行）：

```python
    final_tool_calls = [tool_buf[k] for k in sorted(tool_buf.keys())]
    yield {
        "type": "done",
        "message": {
            "content": accumulated_content,
            "tool_calls": final_tool_calls if final_tool_calls else None,
        },
        "usage": usage_data,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_llm_usage.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/ai_chat/agent.py backend/tests/test_agent_observability_llm_usage.py
git commit -m "feat(observability): capture LLM token usage from streaming response"
```

---

## Task 4: run_agent 埋点（薄 wrapper + 单点记 step）

**Files:**
- Modify: `backend/app/ai_chat/agent.py`（import；`run_agent` 改 wrapper；旧 body 改名 `_run_agent_inner` + 内部埋点）
- Test: `backend/tests/test_agent_observability_run_agent.py`

> 设计：不把 330 行循环重新缩进。把当前 `run_agent`（579 行起的整段）**改名**为 `_run_agent_inner`，多收一个 `holder` 参数；新写一个 8 行的 `run_agent` wrapper，用 `try/finally` 保证 `end_run` 在所有 9 个退出点 **以及** SSE 客户端中途断开（`GeneratorExit`）时都触发一次。step 在「每轮 LLM done」「每个 tool 结束」两处单点记录。

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_agent_observability_run_agent.py`:

```python
"""run_agent 端到端埋点（mock 掉 LLM 与工具，验证 AgentRun/AgentStep 落库）。

跟 recorder 测试一样，需要把 AsyncSessionLocal 指到共享内存库，让 recorder 写的行
能被断言查到；同时把这个共享 session 传给 run_agent 当主 db。
"""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import app.database as database
import app.ai_chat.agent as agent_mod
from app.database import Base
from app.models import AIChatSession
from app.models.agent_observability import AgentRun, AgentStep
from app.observability import recorder


@pytest_asyncio.fixture
async def shared_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", Session)
    monkeypatch.setattr(recorder, "AsyncSessionLocal", Session)
    async with Session() as s:
        yield s
    await engine.dispose()


def _stub_llm(monkeypatch, turns):
    """monkeypatch _call_llm_stream：按 turns 依次产出。每个 turn 是 done 事件 dict。"""
    seq = iter(turns)

    async def _fake_stream(cfg, messages, tools, abort_event, timeout=180):
        yield next(seq)

    monkeypatch.setattr(agent_mod, "_call_llm_stream", _fake_stream)


async def _seed_session(db) -> AIChatSession:
    s = AIChatSession(tenant_id=7, user_id=3, title="t", status="active")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@pytest.mark.asyncio
async def test_no_tool_run_records_run_and_llm_step(shared_db, monkeypatch):
    s = await _seed_session(shared_db)

    monkeypatch.setattr(
        agent_mod, "_resolve_llm_config",
        _aval(types_ns(model="gpt-5.5")),
    )
    monkeypatch.setattr(
        agent_mod, "_build_initial_messages",
        _aval([{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]),
    )
    monkeypatch.setattr(agent_mod, "get_all_tool_schemas", _aval([]))
    # 单轮：无 tool_calls + 有 content + 带 usage
    _stub_llm(monkeypatch, [{
        "type": "done",
        "message": {"content": "完成了", "tool_calls": None},
        "usage": {"prompt_tokens": 50, "completion_tokens": 8},
    }])

    abort = asyncio.Event()
    events = []
    async for ev in agent_mod.run_agent(shared_db, s, "hi", abort):
        events.append((ev["event"], ev["data"]))

    # run_started 事件带 run_id
    started = [json.loads(d) for (e, d) in events if e == "run_started"]
    assert started and started[0]["run_id"]
    run_id = started[0]["run_id"]

    # assistant_message 事件带 run_id（前端每条回复挂「查看本次 trace」靠它）
    asst_evt = [json.loads(d) for (e, d) in events if e == "assistant_message"]
    assert asst_evt and asst_evt[0]["run_id"] == run_id

    run = (await shared_db.execute(select(AgentRun).where(AgentRun.run_id == run_id))).scalar_one()
    assert run.agent_type == "ai_builder"
    assert run.tenant_id == 7
    assert run.user_id == 3
    assert run.session_id == str(s.id)
    assert run.status == "success"
    assert run.total_prompt_tokens == 50
    assert run.total_completion_tokens == 8
    assert run.total_tokens == 58
    assert run.turn_count == 1

    steps = (await shared_db.execute(
        select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)
    )).scalars().all()
    assert len(steps) == 1
    assert steps[0].step_type == "llm"
    assert steps[0].prompt_tokens == 50


@pytest.mark.asyncio
async def test_tool_run_records_tool_step(shared_db, monkeypatch):
    s = await _seed_session(shared_db)
    monkeypatch.setattr(agent_mod, "_resolve_llm_config", _aval(types_ns(model="gpt-5.5")))
    monkeypatch.setattr(
        agent_mod, "_build_initial_messages",
        _aval([{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]),
    )
    monkeypatch.setattr(agent_mod, "get_all_tool_schemas", _aval([]))

    async def _fake_exec(tool_name, args, session, db):
        return "工具结果 ok"

    monkeypatch.setattr(agent_mod, "execute_tool", _fake_exec)

    # turn1：调一个工具；turn2：收尾文本
    _stub_llm(monkeypatch, [
        {
            "type": "done",
            "message": {
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "read_attachment", "arguments": "{\"id\": 1}"}}],
            },
            "usage": {"prompt_tokens": 40, "completion_tokens": 5},
        },
        {
            "type": "done",
            "message": {"content": "搞定", "tool_calls": None},
            "usage": {"prompt_tokens": 60, "completion_tokens": 9},
        },
    ])

    abort = asyncio.Event()
    events = []
    async for ev in agent_mod.run_agent(shared_db, s, "hi", abort):
        events.append((ev["event"], ev["data"]))

    run_id = [json.loads(d) for (e, d) in events if e == "run_started"][0]["run_id"]
    run = (await shared_db.execute(select(AgentRun).where(AgentRun.run_id == run_id))).scalar_one()
    assert run.status == "success"
    assert run.turn_count == 2          # 两个 llm step
    assert run.total_tokens == 40 + 5 + 60 + 9

    steps = (await shared_db.execute(
        select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.seq)
    )).scalars().all()
    kinds = [s.step_type for s in steps]
    assert kinds == ["llm", "tool", "llm"]
    tool_step = steps[1]
    assert tool_step.tool_name == "read_attachment"
    assert tool_step.status == "success"
    assert tool_step.args_json == {"id": 1}


# ── 小工具：把一个值包成 async 函数（monkeypatch 用） ──
def _aval(value):
    async def _f(*a, **kw):
        return value
    return _f


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_run_agent.py -v`
Expected: FAIL — 没有 `run_started` 事件 / 查不到 AgentRun 行（埋点还没加）

- [ ] **Step 3: import recorder**

`backend/app/ai_chat/agent.py` 顶部 import 区（约 40 行、models import 块之后）加：

```python
from app.observability import recorder
```

- [ ] **Step 4: 当前 `run_agent` 改名为 `_run_agent_inner`，加 `holder` 参数**

把 `backend/app/ai_chat/agent.py:579` 的函数签名从：

```python
async def run_agent(
    db: AsyncSession,
    session: AIChatSession,
    current_user_message: str,
    abort_event: asyncio.Event,
) -> AsyncIterator[dict]:
    """主 agent loop。yield SSE 事件给 routes 转发到前端。"""
```

改为（仅改函数名 + 加一个 `holder` 参数，**函数体其余不动、不重新缩进**）：

```python
async def _run_agent_inner(
    db: AsyncSession,
    session: AIChatSession,
    current_user_message: str,
    abort_event: asyncio.Event,
    holder: dict,
) -> AsyncIterator[dict]:
    """主 agent loop body。run 生命周期由外层 run_agent wrapper 管。
    holder = {"run_id": str|None, "status": "running"/"success"/"error", "error": str|None}
    """
```

- [ ] **Step 5: 在 config 解析成功后 start_run（约 593 行 thinking 事件之后）**

把：

```python
    yield _sse("thinking", {"text": f"使用模型：{cfg.model}"})

    try:
        messages = await _build_initial_messages(db, session, current_user_message)
```

改为：

```python
    yield _sse("thinking", {"text": f"使用模型：{cfg.model}"})

    # ── 可观测：开 run（旁路；config 解析失败的早退发生在此之前，不记） ──
    holder["run_id"] = await recorder.start_run(
        agent_type="ai_builder",
        tenant_id=getattr(session, "tenant_id", None),
        user_id=getattr(session, "user_id", None),
        session_id=session.id,
        model=cfg.model,
    )
    yield _sse("run_started", {"run_id": holder["run_id"]})
    _obs_seq = 0  # run 内 step 单调递增序号

    try:
        messages = await _build_initial_messages(db, session, current_user_message)
```

并把紧跟的 except 块里的 done 事件带上 run_id、记下错误：

```python
    except Exception as e:
        holder["error"] = f"构建上下文失败：{e}"
        yield _sse("error", {"error": holder["error"]})
        yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
        return
```

- [ ] **Step 6: 主 LLM done 处记 llm step（约 660-664 行）**

把：

```python
                elif chunk["type"] == "done":
                    evt = _drain_delta()
                    if evt is not None:
                        yield evt
                    assistant_msg = chunk["message"]
```

改为：

```python
                elif chunk["type"] == "done":
                    evt = _drain_delta()
                    if evt is not None:
                        yield evt
                    assistant_msg = chunk["message"]
                    _obs_usage = chunk.get("usage") or {}
                    _obs_seq += 1
                    await recorder.record_step(
                        holder["run_id"], step_type="llm", seq=_obs_seq,
                        prompt_tokens=_obs_usage.get("prompt_tokens"),
                        completion_tokens=_obs_usage.get("completion_tokens"),
                    )
```

- [ ] **Step 7: 沉默重试的 done 处也记 llm step（约 731-735 行）**

把：

```python
                        elif chunk["type"] == "done":
                            evt = _drain_delta()
                            if evt is not None:
                                yield evt
                            retry_assistant = chunk["message"]
```

改为：

```python
                        elif chunk["type"] == "done":
                            evt = _drain_delta()
                            if evt is not None:
                                yield evt
                            retry_assistant = chunk["message"]
                            _obs_ru = chunk.get("usage") or {}
                            _obs_seq += 1
                            await recorder.record_step(
                                holder["run_id"], step_type="llm", seq=_obs_seq,
                                prompt_tokens=_obs_ru.get("prompt_tokens"),
                                completion_tokens=_obs_ru.get("completion_tokens"),
                            )
```

- [ ] **Step 8: 落 assistant 消息塞 run_id + 事件带 run_id + 成功出口置 success（约 750-766 行）**

(a) 持久化 assistant message 时把 run_id 塞进 `extra_meta`（约 750 行），让刷新后历史消息也知道自己属于哪个 run：

把：

```python
                asst_db = AIChatMessage(
                    session_id=session.id,
                    role="assistant",
                    content=content,
                )
```

改为：

```python
                asst_db = AIChatMessage(
                    session_id=session.id,
                    role="assistant",
                    content=content,
                    extra_meta={"run_id": holder["run_id"]},
                )
```

(b) `assistant_message` 事件带上 run_id（约 758 行）—— 前端每条回复挂「查看本次 trace」靠它（实时路径）：

把：

```python
                yield _sse("assistant_message", {
                    "id": asst_db.id,
                    "session_id": asst_db.session_id,
                    "role": "assistant",
                    "content": content,
                    "created_at": asst_db.created_at.isoformat(),
                })
```

改为：

```python
                yield _sse("assistant_message", {
                    "id": asst_db.id,
                    "session_id": asst_db.session_id,
                    "role": "assistant",
                    "content": content,
                    "run_id": holder["run_id"],
                    "created_at": asst_db.created_at.isoformat(),
                })
```

(c) 成功出口置 success（约 765 行）：

把：

```python
            yield _sse("done", {"ok": True})
            return
```

改为：

```python
            holder["status"] = "success"
            yield _sse("done", {"ok": True, "run_id": holder["run_id"]})
            return
```

- [ ] **Step 9: tool 结束处记 tool step（约 845-851 行 tool_call_end 之后）**

在 `yield _sse("tool_call_end", {...})` 整段之后插入：

```python
            yield _sse("tool_call_end", {
                "id": tc_db.id,
                "tool_name": tool_name,
                "status": tc_db.status,
                "result_text": result_text[:600] + ("..." if len(result_text) > 600 else ""),
                "duration_ms": tc_db.duration_ms,
            })

            # ── 可观测：双写 tool step（AIChatToolCall 已写，这里给统一底座再记一笔） ──
            _obs_seq += 1
            await recorder.record_step(
                holder["run_id"], step_type="tool", seq=_obs_seq,
                tool_name=tool_name, args=args, result_text=result_text,
                status=tc_db.status, duration_ms=tc_db.duration_ms,
            )
```

- [ ] **Step 10: ask_user 暂停出口置 success（约 921 行）**

把：

```python
        if asked_user:
            # 提了问题就停 loop，等下一轮 user send
            yield _sse("done", {"ok": True, "awaiting_user": True})
            return
```

改为：

```python
        if asked_user:
            # 提了问题就停 loop，等下一轮 user send
            holder["status"] = "success"
            yield _sse("done", {"ok": True, "awaiting_user": True, "run_id": holder["run_id"]})
            return
```

- [ ] **Step 11: 各 error 出口记 error 文案（status 默认就是 error，只需补 error 文案）**

在以下出口把错误写进 holder（status 保持默认 "error"）：

MAX_TURNS（约 925 行）：

```python
    # 超过 MAX_TURNS
    holder["error"] = f"达到最大循环次数 {MAX_TURNS}，已停止"
    yield _sse("error", {"error": holder["error"]})
    yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
```

LLM HTTP 错（约 678 行）`yield _sse("error", ...)` 之前加：

```python
            holder["error"] = f"LLM 调用失败 {e.response.status_code}: {detail}"
            yield _sse("error", {"error": holder["error"]})
            yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
            return
```

LLM 通用错（约 682 行）：

```python
        except Exception as e:
            holder["error"] = f"LLM 调用失败：{e}"
            yield _sse("error", {"error": holder["error"]})
            yield _sse("done", {"ok": False, "run_id": holder["run_id"]})
            return
```

（abort 出口 611/668/792 行不强制改 —— status 默认 error 已能反映「没成功」；如需更精确可置 `holder["error"] = "aborted"`，Phase 1 可选。）

- [ ] **Step 12: 新写 `run_agent` wrapper（紧贴 `_run_agent_inner` 之前，约 579 行上方插入）**

```python
async def run_agent(
    db: AsyncSession,
    session: AIChatSession,
    current_user_message: str,
    abort_event: asyncio.Event,
) -> AsyncIterator[dict]:
    """对外入口：包一层 run 生命周期（可观测），把事件原样透传。

    用 try/finally 保证 end_run 在所有正常退出点 + SSE 客户端中途断开
    （GeneratorExit）时都恰好触发一次。recorder 自身吞异常，这里不会反噬主流程。
    """
    holder: dict = {"run_id": None, "status": "error", "error": None}
    try:
        async for event in _run_agent_inner(
            db, session, current_user_message, abort_event, holder
        ):
            yield event
    finally:
        if holder["run_id"]:
            await recorder.end_run(
                holder["run_id"], status=holder["status"], error=holder["error"]
            )
```

- [ ] **Step 13: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_run_agent.py -v`
Expected: PASS（2 passed）

- [ ] **Step 14: 确认 import 不破 + 跑相邻既有测试无回归**

Run: `cd backend && .venv/bin/python -c "import app.ai_chat.agent; import app.main; print('ok')"`
Expected: `ok`

Run: `cd backend && .venv/bin/python -m pytest tests/ -k "ai_chat or agent" -q`
Expected: 不引入新失败（与改前同基线；已知 6 个 SQLite 预存失败与本任务无关）

- [ ] **Step 15: 提交**

```bash
git add backend/app/ai_chat/agent.py backend/tests/test_agent_observability_run_agent.py
git commit -m "feat(observability): instrument ai-builder run_agent with run/step recording"
```

---

## Task 5: 读 API（租户作用域）

**Files:**
- Create: `backend/app/routes/agent_observability.py`
- Modify: `backend/app/main.py:11-53`（import 块）+ `:155`（include_router）
- Test: `backend/tests/test_agent_observability_api.py`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/test_agent_observability_api.py`:

```python
"""读 API：租户隔离 + trace 详情有序 steps。直接调路由函数（不走 HTTP，沿用本仓约定）。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import User
from app.models.agent_observability import AgentRun, AgentStep
from app.routes.agent_observability import list_agent_runs, get_agent_run_detail


def _ctx(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={})


async def _seed_run(db, *, run_id, tenant_id, agent_type="ai_builder", session_id="1"):
    db.add(AgentRun(run_id=run_id, agent_type=agent_type, tenant_id=tenant_id,
                    user_id=1, session_id=session_id, status="success",
                    total_tokens=10, total_prompt_tokens=8, total_completion_tokens=2))
    await db.commit()


@pytest.mark.asyncio
async def test_list_is_tenant_scoped(db_session):
    user = User(username="u1", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    await _seed_run(db_session, run_id="r_t7", tenant_id=7)
    await _seed_run(db_session, run_id="r_t9", tenant_id=9)

    out = await list_agent_runs(_ctx(user, 7), db_session)
    ids = [r["run_id"] for r in out["runs"]]
    assert ids == ["r_t7"]          # 只看到自己租户的
    assert "r_t9" not in ids


@pytest.mark.asyncio
async def test_detail_cross_tenant_404(db_session):
    user = User(username="u2", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    await _seed_run(db_session, run_id="r_other", tenant_id=9)

    with pytest.raises(HTTPException) as ei:
        await get_agent_run_detail("r_other", _ctx(user, 7), db_session)
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_detail_returns_ordered_steps(db_session):
    user = User(username="u3", hashed_password="x")
    db_session.add(user)
    await db_session.flush()
    await _seed_run(db_session, run_id="r_ok", tenant_id=7)
    for seq, st in [(2, "tool"), (1, "llm"), (3, "llm")]:
        db_session.add(AgentStep(run_id="r_ok", seq=seq, step_type=st))
    await db_session.commit()

    out = await get_agent_run_detail("r_ok", _ctx(user, 7), db_session)
    assert out["run"]["run_id"] == "r_ok"
    assert [s["seq"] for s in out["steps"]] == [1, 2, 3]   # 按 seq 升序
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routes.agent_observability'`

- [ ] **Step 3: 写路由**

Create `backend/app/routes/agent_observability.py`:

```python
"""Agent 可观测读 API（Phase 1：租户只看自己）。

- GET /api/agent-runs            当前租户的 run 列表（倒序，支持 agent_type / session_id 过滤）
- GET /api/agent-runs/{run_id}   单次 run 的 trace：run + 有序 steps（强制租户隔离）
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.models.agent_observability import AgentRun, AgentStep

router = APIRouter(prefix="/agent-runs", tags=["agent-observability"])


def _run_to_dict(r: AgentRun) -> dict:
    return {
        "run_id": r.run_id,
        "agent_type": r.agent_type,
        "status": r.status,
        "model": r.model,
        "session_id": r.session_id,
        "app_id": r.app_id,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
        "duration_ms": r.duration_ms,
        "total_prompt_tokens": r.total_prompt_tokens,
        "total_completion_tokens": r.total_completion_tokens,
        "total_tokens": r.total_tokens,
        "turn_count": r.turn_count,
        "error_message": r.error_message,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _step_to_dict(s: AgentStep) -> dict:
    return {
        "seq": s.seq,
        "step_type": s.step_type,
        "tool_name": s.tool_name,
        "args_json": s.args_json,
        "result_text": s.result_text,
        "status": s.status,
        "duration_ms": s.duration_ms,
        "prompt_tokens": s.prompt_tokens,
        "completion_tokens": s.completion_tokens,
        "ts": s.ts.isoformat() if s.ts else None,
    }


@router.get("")
async def list_agent_runs(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    agent_type: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """当前租户的 run 列表（按创建时间倒序）。"""
    q = select(AgentRun).where(AgentRun.tenant_id == ctx.tenant_id)
    if agent_type:
        q = q.where(AgentRun.agent_type == agent_type)
    if session_id:
        q = q.where(AgentRun.session_id == session_id)
    q = q.order_by(desc(AgentRun.created_at)).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return {"runs": [_run_to_dict(r) for r in rows]}


@router.get("/{run_id}")
async def get_agent_run_detail(
    run_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """单次 run 的 trace：run + 有序 steps。强制租户隔离。"""
    run = (
        await db.execute(
            select(AgentRun).where(
                AgentRun.run_id == run_id,
                AgentRun.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="trace 不存在")
    steps = (
        await db.execute(
            select(AgentStep)
            .where(AgentStep.run_id == run_id)
            .order_by(AgentStep.seq.asc())
        )
    ).scalars().all()
    return {"run": _run_to_dict(run), "steps": [_step_to_dict(s) for s in steps]}
```

- [ ] **Step 4: 注册路由**

`backend/app/main.py` 的 `from app.routes import (...)`（11-53 行）按字母序加 `agent_observability,`（紧跟 `agents_config,` 之后即可）：

```python
    agent_prompts,
    agents_config,
    agent_observability,
    ai_chat,
```

在 `app.include_router(ai_chat.router, prefix="/api")`（154 行）之后加：

```python
app.include_router(ai_chat.router, prefix="/api")
app.include_router(agent_observability.router, prefix="/api")
```

- [ ] **Step 5: 跑测试确认通过 + import 不破**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_observability_api.py -v`
Expected: PASS（3 passed）

Run: `cd backend && .venv/bin/python -c "import app.main; print('ok')"`
Expected: `ok`

- [ ] **Step 6: 提交**

```bash
git add backend/app/routes/agent_observability.py backend/app/main.py backend/tests/test_agent_observability_api.py
git commit -m "feat(observability): add tenant-scoped agent-runs read API"
```

---

## Task 6: 前端 API 客户端

**Files:**
- Create: `frontend/src/api/agentObservability.ts`

> 沿用 `frontend/src/api/agents.ts` 的 `request` 包装模式；token / baseURL 由 `utils/request.ts` 拦截器自动带上。

- [ ] **Step 1: 写 API 客户端**

Create `frontend/src/api/agentObservability.ts`:

```typescript
import request from '@/utils/request'

export interface AgentRunSummary {
  run_id: string
  agent_type: string
  status: string
  model: string | null
  session_id: string | null
  app_id: string | null
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  total_prompt_tokens: number
  total_completion_tokens: number
  total_tokens: number
  turn_count: number
  error_message: string | null
  created_at: string | null
}

export interface AgentStep {
  seq: number
  step_type: 'llm' | 'tool' | 'error' | 'artifact'
  tool_name: string | null
  args_json: Record<string, any> | null
  result_text: string | null
  status: string | null
  duration_ms: number | null
  prompt_tokens: number | null
  completion_tokens: number | null
  ts: string | null
}

export interface AgentRunDetail {
  run: AgentRunSummary
  steps: AgentStep[]
}

export const agentObservabilityApi = {
  listRuns(params: { session_id?: string; agent_type?: string; limit?: number } = {}): Promise<{ runs: AgentRunSummary[] }> {
    return request({ url: '/agent-runs', method: 'get', params }) as unknown as Promise<{ runs: AgentRunSummary[] }>
  },
  getRunDetail(runId: string): Promise<AgentRunDetail> {
    return request({ url: `/agent-runs/${runId}`, method: 'get' }) as unknown as Promise<AgentRunDetail>
  },
}
```

- [ ] **Step 2: 类型检查（仅本文件不应引入错误）**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep agentObservability || echo "no new errors in agentObservability"`
Expected: 打印 `no new errors in agentObservability`（仓库整体 vue-tsc 预存坏，只看本文件无新错）

- [ ] **Step 3: 提交**

```bash
git add frontend/src/api/agentObservability.ts
git commit -m "feat(observability): add frontend agent-runs api client"
```

---

## Task 7: Trace 抽屉组件 + 两个入口（会话级 + 每条回复）

**Files:**
- Create: `frontend/src/components/common/AgentRunTraceDrawer.vue`
- Modify: `backend/app/routes/ai_chat.py:105`（`_message_to_dict` 透出 run_id）
- Modify: `frontend/src/api/aiChat.ts`（`AIChatMessage` 加 run_id）
- Modify: `frontend/src/views/AIChatPage.vue`（状态 + run_id 捕获 + `agentMessages` meta + 会话级入口 + `@open-trace` + 挂抽屉）
- Modify: `frontend/src/components/common/AgentConversation.vue`（assistant 脚注加「查看本次 trace」+ `emit('open-trace')`）
- 验证：preview（无前端单测基建，用类型检查 + 浏览器行为验证）

> 两个入口：①**会话级**——会话头部「Agent 活动」按钮，抽屉拉本会话所有 run（`listRuns({session_id})`），刷新后历史会话也能看；②**每条回复**——assistant 消息脚注「查看本次 trace」，开抽屉并预选该消息的 run。后者刷新后仍可用，因为 run_id 持久化在 `AIChatMessage.extra_meta`（Task 4 Step 8 已落），经 `_message_to_dict` 透到前端。实时 SSE 的 `run_started.run_id` 也存着，会话级入口默认选中最新一条。

- [ ] **Step 1: 后端 `_message_to_dict` 透出 run_id**

`backend/app/routes/ai_chat.py:105` 的 `_message_to_dict`：

把：

```python
def _message_to_dict(m: AIChatMessage) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "extra_meta": m.extra_meta or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
```

改为：

```python
def _message_to_dict(m: AIChatMessage) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        # 从 extra_meta 透出 run_id，让刷新后的历史 assistant 消息也能挂「查看本次 trace」
        "run_id": (m.extra_meta or {}).get("run_id"),
        "extra_meta": m.extra_meta or {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
```

- [ ] **Step 2: 写抽屉组件**

Create `frontend/src/components/common/AgentRunTraceDrawer.vue`:

```vue
<template>
  <el-drawer
    v-model="open"
    title="Agent 活动 / Trace"
    direction="rtl"
    size="640px"
    :append-to-body="true"
    :destroy-on-close="true"
  >
    <div class="trace-wrap" v-loading="loading">
      <!-- run 列表 -->
      <div class="run-list">
        <div
          v-for="r in runs"
          :key="r.run_id"
          class="run-item"
          :class="{ active: r.run_id === selectedRunId }"
          @click="selectRun(r.run_id)"
        >
          <span class="run-status" :data-status="r.status">{{ statusLabel(r.status) }}</span>
          <span class="run-meta">{{ r.turn_count }} 轮 · {{ r.total_tokens }} tok</span>
          <span class="run-dur">{{ fmtMs(r.duration_ms) }}</span>
          <span class="run-time">{{ fmtTime(r.created_at) }}</span>
        </div>
        <div v-if="!runs.length && !loading" class="empty">本会话还没有 agent 运行记录</div>
      </div>

      <!-- 选中 run 的 step 时间线 -->
      <div v-if="detail" class="timeline">
        <div class="timeline-head">
          <span :data-status="detail.run.status" class="run-status">{{ statusLabel(detail.run.status) }}</span>
          <span>{{ detail.run.model || '—' }}</span>
          <span>{{ detail.run.total_prompt_tokens }} in / {{ detail.run.total_completion_tokens }} out</span>
          <span>{{ fmtMs(detail.run.duration_ms) }}</span>
        </div>
        <div v-if="detail.run.error_message" class="err-banner">{{ detail.run.error_message }}</div>

        <div v-for="s in detail.steps" :key="s.seq" class="step" :data-type="s.step_type">
          <div class="step-head">
            <span class="step-badge">{{ s.step_type }}</span>
            <span v-if="s.tool_name" class="step-tool">{{ s.tool_name }}</span>
            <span v-if="s.step_type === 'llm'" class="step-tok">
              {{ s.prompt_tokens ?? '?' }} in / {{ s.completion_tokens ?? '?' }} out
            </span>
            <span v-if="s.status" class="step-st" :data-status="s.status">{{ s.status }}</span>
            <span v-if="s.duration_ms != null" class="step-dur">{{ fmtMs(s.duration_ms) }}</span>
          </div>
          <pre v-if="s.args_json" class="step-body">{{ pretty(s.args_json) }}</pre>
          <pre v-if="s.result_text" class="step-body result">{{ truncate(s.result_text) }}</pre>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { agentObservabilityApi, type AgentRunSummary, type AgentRunDetail } from '@/api/agentObservability'

const props = defineProps<{
  modelValue: boolean
  sessionId: number | null
  preferRunId?: string | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const open = ref(props.modelValue)
const loading = ref(false)
const runs = ref<AgentRunSummary[]>([])
const detail = ref<AgentRunDetail | null>(null)
const selectedRunId = ref<string | null>(null)

watch(() => props.modelValue, (v) => {
  open.value = v
  if (v) void load()
})
watch(open, (v) => emit('update:modelValue', v))

async function load() {
  if (!props.sessionId) { runs.value = []; detail.value = null; return }
  loading.value = true
  try {
    const res = await agentObservabilityApi.listRuns({ session_id: String(props.sessionId), limit: 50 })
    runs.value = res.runs || []
    const target = props.preferRunId && runs.value.some(r => r.run_id === props.preferRunId)
      ? props.preferRunId
      : (runs.value[0]?.run_id ?? null)
    if (target) await selectRun(target)
    else detail.value = null
  } catch (e: any) {
    ElMessage.error('加载 trace 失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function selectRun(runId: string) {
  selectedRunId.value = runId
  loading.value = true
  try {
    detail.value = await agentObservabilityApi.getRunDetail(runId)
  } catch (e: any) {
    ElMessage.error('加载 trace 详情失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

function statusLabel(s: string) { return ({ success: '成功', error: '失败', running: '运行中' } as any)[s] || s }
function fmtMs(ms: number | null) { return ms == null ? '—' : ms >= 1000 ? (ms / 1000).toFixed(1) + 's' : ms + 'ms' }
function fmtTime(t: string | null) { return t ? new Date(t).toLocaleString() : '—' }
function pretty(o: any) { try { return JSON.stringify(o, null, 2) } catch { return String(o) } }
function truncate(t: string) { return t.length > 4000 ? t.slice(0, 4000) + '\n…（已截断）' : t }
</script>

<style scoped>
.trace-wrap { display: flex; flex-direction: column; gap: 12px; height: 100%; overflow: hidden; }
.run-list { max-height: 30%; overflow-y: auto; border-bottom: 1px solid var(--t-border-soft, #e5e7eb); }
.run-item { display: flex; gap: 10px; align-items: center; padding: 7px 8px; font-size: 12.5px;
  cursor: pointer; border-radius: 6px; }
.run-item:hover { background: var(--t-bg-soft, #f3f4f6); }
.run-item.active { background: var(--t-bg-soft, #eef2ff); }
.run-meta, .run-dur, .run-time { color: var(--t-text-muted, #6b7280); }
.run-time { margin-left: auto; }
.run-status { font-weight: 600; }
.run-status[data-status="success"] { color: #16a34a; }
.run-status[data-status="error"] { color: #dc2626; }
.run-status[data-status="running"] { color: #3b82f6; }
.timeline { flex: 1; overflow-y: auto; }
.timeline-head { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px;
  color: var(--t-text-secondary, #4b5563); padding: 6px 2px 10px; }
.err-banner { background: #fef2f2; color: #b91c1c; padding: 8px 10px; border-radius: 6px;
  font-size: 12.5px; margin-bottom: 10px; }
.step { border: 1px solid var(--t-border-soft, rgba(116,128,171,0.14)); border-radius: 8px;
  padding: 8px 10px; margin-bottom: 8px; }
.step[data-type="tool"] { border-left: 3px solid #3b82f6; }
.step[data-type="llm"] { border-left: 3px solid #8b5cf6; }
.step-head { display: flex; gap: 10px; align-items: center; font-size: 12.5px; flex-wrap: wrap; }
.step-badge { text-transform: uppercase; font-size: 10.5px; letter-spacing: .04em;
  color: var(--t-text-muted, #6b7280); }
.step-tool { font-weight: 600; }
.step-tok, .step-dur, .step-st { color: var(--t-text-muted, #6b7280); }
.step-st[data-status="error"] { color: #dc2626; }
.step-dur { margin-left: auto; }
.step-body { margin: 6px 0 0; padding: 6px 8px; background: var(--t-bg-soft, #f6f7f9);
  border-radius: 6px; font-size: 11.5px; white-space: pre-wrap; word-break: break-all;
  max-height: 220px; overflow-y: auto; }
.step-body.result { color: var(--t-text-secondary, #374151); }
.empty { color: var(--t-text-muted, #9ca3af); font-size: 12.5px; padding: 12px 4px; }
</style>
```

- [ ] **Step 3: `aiChat.ts` 的 `AIChatMessage` 加 run_id**

`frontend/src/api/aiChat.ts` 的 `AIChatMessage` 接口（约 15-22 行）加一个可选字段：

```typescript
export interface AIChatMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  run_id?: string | null
  extra_meta?: Record<string, any>
  created_at: string | null
}
```

（实际字段以本接口现有为准，只**新增** `run_id?: string | null` 一行；其余保持不动。）

- [ ] **Step 4: AIChatPage 状态 + 捕获 run_id**

`frontend/src/views/AIChatPage.vue` 的 `<script setup>` 状态区（约 313 行附近，跟 `currentSession` 等同级）加三个 ref：

```typescript
const currentRunId = ref<string | null>(null)       // 最近一次实时 run（会话级入口默认选中）
const traceDrawerVisible = ref(false)
const tracePreferRunId = ref<string | null>(null)    // 抽屉打开时希望预选的 run
```

在 `handleSseEvent`（约 1411 行起）加 `run_started` 分支（紧挨 `thinking` 分支即可）：

```typescript
} else if (eventName === 'run_started') {
  currentRunId.value = data.run_id || null
}
```

- [ ] **Step 5: `agentMessages` 把 run_id 带进 `meta`**

`frontend/src/views/AIChatPage.vue` 的 `agentMessages` computed（约 1038-1041 行）assistant 分支：

把：

```typescript
    } else if (item.kind === 'msg' && item.msg.role === 'assistant') {
      if (item.msg.content) {
        out.push({ id: 'm' + item.msg.id, kind: 'assistant', content: item.msg.content })
      }
```

改为（把 run_id 放进 `AgentMessage.meta`，模板里就能拿到）：

```typescript
    } else if (item.kind === 'msg' && item.msg.role === 'assistant') {
      if (item.msg.content) {
        out.push({
          id: 'm' + item.msg.id,
          kind: 'assistant',
          content: item.msg.content,
          meta: (item.msg as any).run_id ? { run_id: (item.msg as any).run_id } : undefined,
        })
      }
```

- [ ] **Step 6: AgentConversation 脚注加「查看本次 trace」+ emit**

`frontend/src/components/common/AgentConversation.vue` 的 assistant 反馈区（约 73-81 行 `.ac-feedback`）：

把：

```vue
    <div
      v-if="item.kind === 'assistant' && !item.streaming && (item.content || '').trim().length > 0"
      class="ac-feedback"
    >
      <button class="ac-fb-btn" :title="'复制'" @click="onCopyMessage(item)">
        {{ copiedId === (item.id ?? '') ? '✓' : '📋' }}
      </button>
      <button class="ac-fb-btn" :title="'反馈：回复不准确'" @click="$emit('feedback', item)">👎</button>
    </div>
```

改为（多一个 trace 按钮，仅当该消息带 run_id 时显示）：

```vue
    <div
      v-if="item.kind === 'assistant' && !item.streaming && (item.content || '').trim().length > 0"
      class="ac-feedback"
    >
      <button class="ac-fb-btn" :title="'复制'" @click="onCopyMessage(item)">
        {{ copiedId === (item.id ?? '') ? '✓' : '📋' }}
      </button>
      <button class="ac-fb-btn" :title="'反馈：回复不准确'" @click="$emit('feedback', item)">👎</button>
      <button
        v-if="item.meta?.run_id"
        class="ac-fb-btn"
        :title="'查看本次 trace'"
        @click="$emit('open-trace', item)"
      >🔍 trace</button>
    </div>
```

并在该组件的 `defineEmits` 里加上 `open-trace`（与现有 `feedback` / `answer-ask` 同级；按本组件实际写法补一项，例如 `(e: 'open-trace', item: AgentMessage): void`）。

- [ ] **Step 7: AIChatPage 接 `@open-trace` + 会话级入口 + 挂抽屉**

(a) `<AgentConversation>` 上加监听（约 59-65 行，跟 `@answer-ask` 同级）：

```vue
  @answer-ask="onAgentAnswerAsk"
  @open-trace="onOpenTrace"
```

(b) `<script setup>` import 区加组件 import：

```typescript
import AgentRunTraceDrawer from '@/components/common/AgentRunTraceDrawer.vue'
```

(c) 加两个打开抽屉的处理（会话级 + 每条回复）：

```typescript
// 每条回复脚注点「查看本次 trace」
function onOpenTrace(message: any) {
  const rid = message?.meta?.run_id
  if (!rid) return
  tracePreferRunId.value = rid
  traceDrawerVisible.value = true
}
// 会话头部「Agent 活动」入口（默认选最近一次 run）
function openSessionTrace() {
  tracePreferRunId.value = currentRunId.value
  traceDrawerVisible.value = true
}
```

(d) 会话头部/工具条区域（靠近标题或右上角动作区，跟现有按钮同级）加会话级入口：

```vue
<button
  class="trace-entry-btn"
  title="查看本次会话的 Agent 活动 / Trace"
  @click="openSessionTrace"
>
  Agent 活动
</button>
```

(e) 模板末尾（跟其它 drawer/dialog 同级）挂抽屉：

```vue
<AgentRunTraceDrawer
  v-model="traceDrawerVisible"
  :session-id="currentSession?.id ?? null"
  :prefer-run-id="tracePreferRunId"
/>
```

（`currentSession` 为 AIChatPage 已有的当前会话 ref；若实际命名不同，用本页已存在的「当前会话对象」替换，取其 `.id`。）

- [ ] **Step 8: 类型检查无新错**

Run: `cd frontend && npx vue-tsc --noEmit -p tsconfig.json 2>&1 | grep -E "AgentRunTraceDrawer|AIChatPage|AgentConversation" | grep -v "预存" || echo "checked"`
Expected: 不出现由本次改动新引入的类型错误（仓库 vue-tsc 整体预存坏，重点确认新文件/新增片段无新错）

- [ ] **Step 9: 提交**

```bash
git add backend/app/routes/ai_chat.py frontend/src/api/aiChat.ts frontend/src/components/common/AgentRunTraceDrawer.vue frontend/src/components/common/AgentConversation.vue frontend/src/views/AIChatPage.vue
git commit -m "feat(observability): add agent trace drawer with session + per-message entries"
```

---

## Task 8: 端到端验证（preview）

**Files:** 无（纯验证）。本任务用 preview 工具确认实时链路 + token 真的采到。

- [ ] **Step 1: 起服务**

用 `preview_start` 起前后端（后端改了模型/路由，必须重启 backend 才会 `init_db()` 建新表）。

- [ ] **Step 2: 触发一次 ai-builder run**

在 `/ai-chat` 用一个有 LLM 配置的租户（本地 SQLite，参考记忆：测试租户 57 / 产品租户有 dolphin gpt-5.5 模型 + 通用 B2B CRM）登录，发一条会触发工具的消息（例如「帮我看看有哪些应用」）。用 `preview_network` 确认 SSE 流里出现 `run_started` 事件且带 `run_id`。

- [ ] **Step 3: 断言落库 + token 必采**

查本地库确认 run 行写进去且 token 非空（这是 Task 3 那个「网关是否真的回 usage」的现实校验）：

```bash
cd backend && .venv/bin/python -c "
import asyncio
from sqlalchemy import select, desc
from app.database import AsyncSessionLocal
from app.models.agent_observability import AgentRun, AgentStep
async def main():
    async with AsyncSessionLocal() as db:
        run = (await db.execute(select(AgentRun).order_by(desc(AgentRun.id)).limit(1))).scalar_one_or_none()
        print('run:', run and (run.run_id, run.agent_type, run.status, run.turn_count,
              run.total_prompt_tokens, run.total_completion_tokens, run.total_tokens))
        if run:
            steps = (await db.execute(select(AgentStep).where(AgentStep.run_id==run.run_id).order_by(AgentStep.seq))).scalars().all()
            print('steps:', [(s.seq, s.step_type, s.tool_name, s.prompt_tokens, s.completion_tokens) for s in steps])
asyncio.run(main())
"
```

Expected: 打印出最近一条 run，`status` 为 `success`，`turn_count >= 1`；steps 里有 `llm` 与 `tool` 两类。

判定 token：
- 若 `total_tokens > 0` 且 llm step 的 `prompt_tokens` 非空 → **token 必采达成**，Phase 1 完成。
- 若 `total_tokens == 0` 且 llm step token 全为 None → 说明 omnigate / gpt-5.5 网关**没有**透传 usage（`stream_options.include_usage` 被网关吞了）。这是已知风险点，处理：先 `preview_network` 抓 `/chat/completions` 上游原始 SSE，看最后一个 data chunk 有没有 `usage` 字段确诊；若确为网关不回 usage，记一条 follow-up（Phase 1.5：网关侧补透传，或退而用 tiktoken 估算），**不阻塞**底座 / trace 视图本身的交付。

- [ ] **Step 4: 验证 Trace 抽屉（两个入口）**

会话级：`preview_click` 点开会话头部「Agent 活动」，`preview_snapshot` 确认抽屉里 run 列表有刚跑的那条、点进去 step 时间线按 llm/tool 顺序展示、token 与耗时显示正常。
每条回复：`preview_click` 点最近一条 assistant 回复脚注的「🔍 trace」，确认抽屉打开并预选了该回复对应的 run。再刷新页面（`preview_eval: window.location.reload()`）后重点验证脚注「🔍 trace」仍在、仍能打开（证明 run_id 走 `extra_meta` 持久化、reload 路径透传成功）。`preview_screenshot` 留证。

- [ ] **Step 5: 验证租户隔离**

切到另一个无该 run 的租户（或直接 `curl` 带其它租户 token 打 `GET /api/agent-runs`），确认看不到上一步那条 run 的 run_id。

- [ ] **Step 6: 全量回归基线对比**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: 新增 11 个 observability 测试全绿；既有失败数与改前基线一致（已知 6 个 SQLite 预存失败，不应新增）。

---

## Self-Review（对照 spec 核查）

**1. Spec 覆盖：**
- 表 1 `agent_run`（全部列 + status/token/turn_count/duration）→ Task 1 ✓（额外加 `model`/`created_at`，已注释理由）。
- 表 2 `agent_step`（seq/step_type/tool/args/result/status/duration/tokens/ts）→ Task 1 ✓。
- 写入门面 `recorder.py`（start_run/record_step/end_run + usage 取 token + 容错吞异常）→ Task 2 ✓。
- 埋点位置 ai-builder `run_agent`（run 起止 + 每轮 LLM 记 usage + 每个工具）→ Task 4 ✓。
- 现有 `AIChatToolCall` 保留、埋点处双写 → Task 4 Step 9 双写 ✓（不动既有写入）。
- token 必采 → Task 3（`include_usage` + 捕获）+ Task 8 Step 3 现实校验 ✓。
- Trace 下钻视图（放大版 ToolCard 流；入口在对话里）→ Task 7 ✓。两个入口：会话级「Agent 活动」按钮 + 每条回复脚注「查看本次 trace」（run_id 持久化进 `extra_meta`，刷新后仍可用）。
- 权限分级 — 租户看自己（`where tenant_id=当前租户`，普通用户）→ Task 5 ✓。平台管理员全局 = Phase 2，本期不做（spec 分期一致）✓。
- 分期：Phase 1 = 底座 + ai-builder 一条链路 + trace（租户）→ 全覆盖；config/coding/builder 三条链路、dashboard、平台全局页留 Phase 2 ✓。
- 不在范围：老数据不迁、成本估算、告警、留存清理 → 计划均未触碰 ✓。

**2. Placeholder 扫描：** 无 TBD / 「按需补充」/ 空泛「加错误处理」；每个代码步骤都有完整代码或精确 old→new 锚点。

**3. 类型一致性：** `run_id` 全链路为 `str`（uuid hex）；`recorder.record_step(run_id, *, step_type, seq, ...)` 与 Task 4 各调用点签名一致；`_run_to_dict`/`_step_to_dict` 字段与前端 `AgentRunSummary`/`AgentStep` interface 对齐；`holder` 三键 `run_id/status/error` 在 wrapper 与 inner 间一致。

## 风险 / 注意

- **token 必采取决于网关**：`stream_options.include_usage` 需 omnigate/gpt-5.5 真的透传 usage chunk。Task 8 Step 3 是现实校验关口；若网关不回，底座/trace 仍可交付，token 透传作为 Phase 1.5 follow-up，不阻塞。
- **共享内存库测试约定**：recorder 用 `app.database.AsyncSessionLocal` 自开会话，所以 recorder/run_agent 测试必须用 `StaticPool` 的共享内存 engine 并 monkeypatch `AsyncSessionLocal`（已在 Task 2/4 测试里写明），不能直接用默认 `db_session` fixture，否则查不到 recorder 写的行。
- **重启 backend 才建表**：本地 SQLite 无 Alembic，新表靠重启时 `init_db()` 的 `create_all`。改完模型/路由务必重启 preview backend（记忆里的老坑）。
- **AIChatPage 命名核对**：Task 7 用到的「当前会话对象」按本页实际命名取（计划假设为 `currentSession`，执行时以实际为准），`handleSseEvent` 的事件名匹配风格按本页既有写法对齐。
- **abort 出口**：中途 abort 记为 `status="error"`（spec status 枚举只有 running/success/error），可选补 `error="aborted"`，不影响主交付。
