# SP1: 堵住 Code 会话漏进 Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Builder 的会话列表与所有 per-session 路由不再列出/接受 `mode='code'` 会话,当场堵住 Code 会话漏进 Builder。

**Architecture:** 两处服务端 chokepoint 各加一条 `AIChatSession.mode != "code"` 谓词:`list_sessions`(列表)与 `_load_session_or_404`(13 个 per-session 路由的唯一加载点)。纯后端、零数据迁移、零前端改动。Code 端走 `/harness/coding/*` 与 `/coding/*`,且 cutover 取会话用 `db.get` 绕过本加载点,故不受影响。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async;pytest + pytest-asyncio;根 `conftest.py` 的 `db_session` async fixture。

**Spec:** [docs/superpowers/specs/2026-06-25-unify-code-into-builder-sp1-session-layer-design.md](../specs/2026-06-25-unify-code-into-builder-sp1-session-layer-design.md)

## Global Constraints

- 后端 `reload=False`:改后端代码后必须重启进程才生效(`cd backend && .venv/bin/python run.py`)。跑测试不需重启。
- Python 解释器固定用 venv:`cd backend && .venv/bin/python -m pytest`(.venv 是 py3.13)。
- 收口必须在 SQL where 子句里(不是 load 后判),让「不存在」与「是 code」返回同一个 404,不泄露存在性。
- 谓词固定字面量 `AIChatSession.mode != "code"`;不要引入新枚举/常量(YAGNI,SP2 再抽象 kind)。
- 只动 `backend/app/routes/ai_chat.py` 两处 + 新增一个测试文件。不碰前端、不碰 CodingPage、不碰引擎、不加 DB 列。

---

### Task 1: `_load_session_or_404` 拒绝 code 会话(覆盖 13 个 per-session 路由)

**Files:**
- Modify: `backend/app/routes/ai_chat.py:427-440`(`_load_session_or_404`)
- Test: `backend/tests/test_ai_chat_mode_scoping.py`(新建)

**Interfaces:**
- Consumes: `db_session`(根 conftest async fixture);`AuthContext`(app/deps.py:19,字段 `user/tenant_id/tenant_role/org_permissions`);`AIChatSession`(app/models/ai_chat.py,列 `tenant_id/user_id/title/mode`)。
- Produces: `_load_session_or_404(db, session_id, ctx)` 对 `mode='code'` 会话抛 `HTTPException(404)`;对 `mode IN ('chat','cowork')` 正常返回 `AIChatSession`。Task 2 的测试复用本文件的 `_seed_session` / `_ctx_for` 辅助。

- [ ] **Step 1: 写失败测试(新建测试文件)**

创建 `backend/tests/test_ai_chat_mode_scoping.py`:

```python
"""SP1: Builder 会话路由按 mode 收口 —— Code(mode='code')会话不得漏进 Builder。"""
import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.models import User
from app.models.tenant import Tenant
from app.models.ai_chat import AIChatSession
from app.routes.ai_chat import _load_session_or_404, list_sessions


async def _make_user(db, username: str) -> User:
    u = User(username=username, hashed_password="x")
    db.add(u)
    await db.flush()
    return u


def _ctx_for(user: User, tenant_id: int) -> AuthContext:
    return AuthContext(
        user=user, tenant_id=tenant_id, tenant_role="member", org_permissions={}
    )


async def _seed_session(db, *, username: str, mode: str):
    """建 tenant+user+一个指定 mode 的 AIChatSession,返回 (ctx, session)。"""
    tenant = Tenant(tenant_name="t_scope", tenant_code=f"t_scope_{username[:8]}")
    db.add(tenant)
    await db.flush()
    user = await _make_user(db, username)
    s = AIChatSession(tenant_id=tenant.id, user_id=user.id, title="t", mode=mode)
    db.add(s)
    await db.flush()
    return _ctx_for(user, tenant.id), s


@pytest.mark.asyncio
async def test_load_session_rejects_code(db_session):
    ctx, s = await _seed_session(db_session, username="scopecode", mode="code")
    with pytest.raises(HTTPException) as exc:
        await _load_session_or_404(db_session, s.id, ctx)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_load_session_allows_chat(db_session):
    ctx, s = await _seed_session(db_session, username="scopechat", mode="chat")
    out = await _load_session_or_404(db_session, s.id, ctx)
    assert out.id == s.id


@pytest.mark.asyncio
async def test_load_session_other_user_still_404(db_session):
    """回归:他人的 chat 会话仍 404(收口不破坏既有 user 作用域)。"""
    ctx, s = await _seed_session(db_session, username="scopeowner", mode="chat")
    thief = await _make_user(db_session, "scopethief")
    thief_ctx = _ctx_for(thief, ctx.tenant_id)
    with pytest.raises(HTTPException) as exc:
        await _load_session_or_404(db_session, s.id, thief_ctx)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_ai_chat_mode_scoping.py::test_load_session_rejects_code -v`
Expected: FAIL —— 当前 `_load_session_or_404` 无 mode 谓词,会**返回**该 code 会话(不抛 404),断言失败。

- [ ] **Step 3: 加 mode 谓词**

修改 `backend/app/routes/ai_chat.py` 的 `_load_session_or_404`(427-440),在 where 中加 `AIChatSession.mode != "code"`:

```python
async def _load_session_or_404(
    db: AsyncSession, session_id: int, ctx: AuthContext
) -> AIChatSession:
    res = await db.execute(
        select(AIChatSession).where(
            AIChatSession.id == session_id,
            AIChatSession.user_id == ctx.user.id,
            AIChatSession.tenant_id == ctx.tenant_id,
            AIChatSession.mode != "code",  # SP1: Code 会话不经 Builder per-session 路由(止血,见 spec §3.2)
        )
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在或无权限")
    return s
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_ai_chat_mode_scoping.py -v -k load_session`
Expected: PASS(3 个 load_session 测试全绿)。

- [ ] **Step 5: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/routes/ai_chat.py backend/tests/test_ai_chat_mode_scoping.py
git commit -m "fix(ai-chat): _load_session_or_404 拒绝 mode=code — Code 会话不得经 Builder per-session 路由

SP1 收口点 B:13 个 Builder per-session 路由(send/abort/attach/delete/...)
唯一加载点加 mode!=code 谓词 → Code 会话在 Builder 不可 open/send/操作。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `list_sessions` 排除 code 会话

**Files:**
- Modify: `backend/app/routes/ai_chat.py:452-465`(`list_sessions` 查询)
- Test: `backend/tests/test_ai_chat_mode_scoping.py`(追加,复用 Task 1 辅助)

**Interfaces:**
- Consumes: Task 1 文件里的 `_make_user` / `_ctx_for`;`list_sessions(ctx, db, limit=50, app_id=None)` 返回 `{"sessions": [ {"id", "mode", ...}, ... ]}`。
- Produces: `list_sessions` 不再返回 `mode='code'` 会话(所有 Builder 列表消费者随之干净)。

- [ ] **Step 1: 写失败测试(追加到同文件末尾)**

在 `backend/tests/test_ai_chat_mode_scoping.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_list_sessions_excludes_code(db_session):
    """同一 user 的 chat + code 两会话,列表只返回 chat。"""
    tenant = Tenant(tenant_name="t_list", tenant_code="t_list_scope")
    db_session.add(tenant)
    await db_session.flush()
    user = await _make_user(db_session, "listscopeuser")
    chat = AIChatSession(tenant_id=tenant.id, user_id=user.id, title="chat one", mode="chat")
    code = AIChatSession(tenant_id=tenant.id, user_id=user.id, title="code one", mode="code")
    db_session.add_all([chat, code])
    await db_session.flush()
    chat_id, code_id = chat.id, code.id

    out = await list_sessions(_ctx_for(user, tenant.id), db_session)
    ids = {s["id"] for s in out["sessions"]}
    assert chat_id in ids, "chat 会话应出现在 Builder 列表"
    assert code_id not in ids, "code 会话不应出现在 Builder 列表"


@pytest.mark.asyncio
async def test_list_sessions_keeps_cowork(db_session):
    """回归:cowork 会话照常出现在列表。"""
    tenant = Tenant(tenant_name="t_cowork", tenant_code="t_cowork_scope")
    db_session.add(tenant)
    await db_session.flush()
    user = await _make_user(db_session, "coworkuser")
    cw = AIChatSession(tenant_id=tenant.id, user_id=user.id, title="cw", mode="cowork")
    db_session.add(cw)
    await db_session.flush()
    cw_id = cw.id

    out = await list_sessions(_ctx_for(user, tenant.id), db_session)
    assert cw_id in {s["id"] for s in out["sessions"]}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_ai_chat_mode_scoping.py::test_list_sessions_excludes_code -v`
Expected: FAIL —— 当前 `list_sessions` 无 mode 谓词,`code_id` 出现在返回里,`assert code_id not in ids` 失败。

- [ ] **Step 3: 加 mode 谓词**

修改 `backend/app/routes/ai_chat.py` 的 `list_sessions`(452-465),在 `.where(...)` 里加 `AIChatSession.mode != "code"`:

```python
    query = (
        select(AIChatSession)
        .where(
            AIChatSession.user_id == ctx.user.id,
            AIChatSession.tenant_id == ctx.tenant_id,
            AIChatSession.mode != "code",  # SP1: Code 会话不进 Builder 会话列表(止血,见 spec §3.1)
        )
    )
    if app_id is not None:
        query = query.where(AIChatSession.app_id == app_id)
    query = query.order_by(desc(AIChatSession.updated_at)).limit(limit)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_ai_chat_mode_scoping.py -v`
Expected: PASS(全文件 5 个测试全绿)。

- [ ] **Step 5: 全量后端测试不退化**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: 与改前一致(本仓有若干预存失败与本改无关;关键是不新增失败、`test_ai_chat_mode_scoping.py` 全绿)。

- [ ] **Step 6: 提交**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/routes/ai_chat.py backend/tests/test_ai_chat_mode_scoping.py
git commit -m "fix(ai-chat): list_sessions 排除 mode=code — Code 会话不进 Builder 会话列表

SP1 收口点 A:Builder 会话列表查询加 mode!=code 谓词 → AIChatPage/RailSidebar/
useAiChatSession 等所有 Builder 列表面不再混入 Code 会话。配合 Task 1 收口点 B,
用户报的「Code 会话漏进 Builder」当场消失。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- Spec §3.1(列表收口)→ Task 2 ✓
- Spec §3.2(per-session 加载收口)→ Task 1 ✓
- Spec §6 测试策略(load 拒 code / load 放行 chat / 跨 user 回归 / list 排除 code / cowork 回归)→ Task 1 三测 + Task 2 两测,逐条覆盖 ✓
- Spec §3.4 三项明确移到 SP2 → 本计划不含,符合非目标 ✓
- Spec §3.5 零迁移 → 本计划无迁移任务 ✓

**2. Placeholder scan:** 无 TBD/TODO;每步含可运行命令与完整代码。✓

**3. Type consistency:** `_seed_session`/`_ctx_for`/`_make_user` 在 Task 1 定义,Task 2 复用同签名;`list_sessions(ctx, db, ...)` 与 `_load_session_or_404(db, session_id, ctx)` 与源码签名一致;谓词字面量两处均为 `AIChatSession.mode != "code"`。✓

## Execution Handoff

两个 Task 顺序执行(Task 2 复用 Task 1 的测试辅助)。建议 subagent-driven-development:每个 Task 一个 fresh subagent + 任务间评审。
