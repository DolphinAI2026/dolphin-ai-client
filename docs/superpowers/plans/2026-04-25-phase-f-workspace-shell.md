# Phase F — UX 整体优化（WorkspaceShell + 双轨）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** 落地 spec [2026-04-25-phase-f-ux-workspace-shell-design.md](../specs/2026-04-25-phase-f-ux-workspace-shell-design.md) — 新建 `/work/:appId` WorkspaceShell（左 Chat / 中 Preview / 右 Activity 三栏），引入"简单/专业"双模式，简单模式 in-chat Approve 卡片不绕开 ABCDE 的 approve gate。

**Architecture:** 后端加 `UserPreference` 表 + `Application.default_mode` 列 + `/api/me/preferences` + `/api/applications/{id}/work-state` BFF 端点；前端新建 `views/WorkspaceShell.vue` + `components/workspace/{ChatPanel,PreviewPanel,ActivityPanel,ModeToggle,WorkspaceTopBar}.vue` + `stores/workspace.ts` + `stores/userPreference.ts`；新建 `BaseDialog/BaseToast` 替换 ~10 处 alert/confirm。

**Tech Stack:** Vue 3 + TypeScript + Pinia + Element Plus + FastAPI + SQLAlchemy 2.x async + pytest（同 Phase A-E）。

**前置条件:** Phase A-E 完成（commits up to `ac9bdca`），backend pytest 199 passing baseline，frontend vue-tsc clean。

**约定:** 中文 commit messages（Conventional Commits 风格）。每 task 一个 commit（部分 task 可拆 2 个 commit）。

---

## File Structure

### 后端
- Create: `backend/scripts/migrate_phase_f.sql`
- Create: `backend/app/models/preference.py` (UserPreference ORM)
- Modify: `backend/app/models/__init__.py` (Application.default_mode + import preference)
- Create: `backend/app/routes/preferences.py` (GET/PUT /api/me/preferences)
- Modify: `backend/app/routes/applications/__init__.py` (default_mode CRUD)
- Create: `backend/app/routes/work_state.py` (BFF endpoint)
- Modify: `backend/app/main.py` (register routers)
- Tests: `backend/tests/test_preferences.py`, `test_application_default_mode.py`, `test_work_state.py`

### 前端
- Create: `frontend/src/views/WorkspaceShell.vue` (主页面 /work/:appId)
- Create: `frontend/src/components/workspace/WorkspaceTopBar.vue`
- Create: `frontend/src/components/workspace/ModeToggle.vue`
- Create: `frontend/src/components/workspace/ChatPanel.vue`
- Create: `frontend/src/components/workspace/PreviewPanel.vue`
- Create: `frontend/src/components/workspace/preview/SpecView.vue`
- Create: `frontend/src/components/workspace/preview/DeployIframe.vue`
- Create: `frontend/src/components/workspace/preview/CodeView.vue`
- Create: `frontend/src/components/workspace/ActivityPanel.vue`
- Create: `frontend/src/components/workspace/activity/DraftCard.vue`
- Create: `frontend/src/components/workspace/activity/ProposalCard.vue`
- Create: `frontend/src/components/workspace/activity/DeployedCard.vue`
- Create: `frontend/src/components/workspace/activity/GitStatusCard.vue`
- Create: `frontend/src/components/workspace/PromoteApproveApplyCard.vue` (in-chat 简单模式快捷批准)
- Create: `frontend/src/stores/workspace.ts`
- Create: `frontend/src/stores/userPreference.ts`
- Create: `frontend/src/api/preferences.ts`
- Create: `frontend/src/api/workState.ts`
- Modify: `frontend/src/router/index.ts` (加 /work/:appId 路由)
- Modify: `frontend/src/views/Apps.vue` (卡片点击默认跳 /work/:appId)
- Create: `frontend/src/components/BaseDialog.vue` (替代 confirm/alert)
- Create: `frontend/src/components/BaseToast.vue`
- Modify: 10 处 alert/confirm 调用方（MembersPanel / DriftBanner / Sync 按钮 / OAuth / ProjectGitSetup 等）

---

## Task 1: DB migration + UserPreference ORM + Application.default_mode

**Files:**
- Create: `backend/scripts/migrate_phase_f.sql`
- Create: `backend/app/models/preference.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: 写 migration SQL**

Create `backend/scripts/migrate_phase_f.sql`:

```sql
-- Phase F migration：UserPreference 表 + Application.default_mode 列

CREATE TABLE IF NOT EXISTS user_preferences (
  user_id INT NOT NULL PRIMARY KEY,
  default_mode VARCHAR(20) NOT NULL DEFAULT 'simple',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_pref_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE applications ADD COLUMN default_mode VARCHAR(20) NULL AFTER status;

INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_phase_f', NOW());
```

- [ ] **Step 2: 应用 migration**

```bash
cd backend && source venv/bin/activate
python scripts/run_migrations.py scripts/migrate_phase_f.sql
```

Expected: `[migrate] DONE  applied=3 skipped=0`（首次跑）/ `applied=1 skipped=2`（重跑：列已加 + INSERT IGNORE 跳过 + table CREATE IF NOT EXISTS skip-warning）。

- [ ] **Step 3: 写测试**

Create `backend/tests/test_preferences_model.py`:

```python
"""UserPreference ORM model 测试"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.models.preference import UserPreference
from app.models import User


@pytest.mark.asyncio
async def test_user_preference_default(db_session):
    """新建 UserPreference 默认 default_mode='simple'"""
    user = User(username="pref_test_1", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    pref = UserPreference(user_id=user.id)
    db_session.add(pref)
    await db_session.commit()
    await db_session.refresh(pref)
    assert pref.default_mode == "simple"


@pytest.mark.asyncio
async def test_application_default_mode_nullable(db_session):
    """Application.default_mode 默认 None"""
    from app.models import Application, Tenant
    tenant = (await db_session.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if not tenant:
        tenant = Tenant(tenant_name="t1", tenant_code="t1")
        db_session.add(tenant)
        await db_session.flush()
    user = User(username="app_default_test", hashed_password="x")
    db_session.add(user)
    await db_session.flush()

    app = Application(
        user_id=user.id, tenant_id=tenant.id, created_by=user.id,
        app_name="测试", app_code="testapp",
    )
    db_session.add(app)
    await db_session.commit()
    await db_session.refresh(app)
    assert app.default_mode is None
```

- [ ] **Step 4: 跑测试 → 预期 ImportError**

Run: `pytest backend/tests/test_preferences_model.py -v`
Expected: ImportError: cannot import name 'UserPreference' from 'app.models.preference'

- [ ] **Step 5: 写 ORM**

Create `backend/app/models/preference.py`:

```python
"""User-level 偏好设置 ORM (Phase F)"""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPreference(Base):
    """用户级偏好。default_mode='simple'|'pro'，影响 WorkspaceShell 默认显示"""
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    default_mode: Mapped[str] = mapped_column(String(20), default="simple", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 6: 改 Application model — 加 default_mode 列**

修改 `backend/app/models/__init__.py`，找到 Application 类，在 `status` 字段之后加：

```python
    default_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'simple' | 'pro' | None
```

同时在文件顶部既有的 `from app.models.spec import Spec` 之后加：

```python
from app.models.preference import UserPreference  # noqa: F401  — register ORM mapping
```

- [ ] **Step 7: 跑测试 → 通过**

Run: `pytest backend/tests/test_preferences_model.py -v`
Expected: 2 passed.

跑全 backend 不回归：
```bash
pytest backend/tests/ -v --tb=short 2>&1 | tail -10
```
Expected: ≥ 199 + 2 = 201 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/scripts/migrate_phase_f.sql backend/app/models/preference.py backend/app/models/__init__.py backend/tests/test_preferences_model.py
git commit -m "$(cat <<'EOF'
feat(phase-f/db): UserPreference 表 + Application.default_mode 列

- user_preferences 表（user_id PK + default_mode 默认 'simple'）
- applications.default_mode VARCHAR(20) NULL（None = 跟随 user pref）
- migrate_phase_f.sql 幂等迁移
- 2 个 ORM 单元测试

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: UserPreference + Application default_mode API

**Files:**
- Create: `backend/app/routes/preferences.py`
- Modify: `backend/app/routes/applications/__init__.py` (加 default_mode 端点)
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_preferences_api.py`

- [ ] **Step 1: 写测试**

Create `backend/tests/test_preferences_api.py`:

```python
"""GET/PUT /api/me/preferences + GET/PATCH /api/applications/{id}/default-mode"""
import pytest
from sqlalchemy import select
from app.models import User, Application
from app.models.preference import UserPreference


@pytest.mark.asyncio
async def test_get_my_preference_creates_default(client, db_session, auth_user):
    """首次 GET /api/me/preferences 自动创建默认行返回 simple"""
    resp = await client.get("/api/me/preferences", headers=auth_user["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"user_id": auth_user["user"].id, "default_mode": "simple"}


@pytest.mark.asyncio
async def test_put_my_preference_updates(client, db_session, auth_user):
    resp = await client.put(
        "/api/me/preferences",
        json={"default_mode": "pro"},
        headers=auth_user["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["default_mode"] == "pro"

    pref = (await db_session.execute(
        select(UserPreference).where(UserPreference.user_id == auth_user["user"].id)
    )).scalar_one()
    assert pref.default_mode == "pro"


@pytest.mark.asyncio
async def test_put_my_preference_rejects_invalid(client, auth_user):
    resp = await client.put(
        "/api/me/preferences",
        json={"default_mode": "wonky"},
        headers=auth_user["headers"],
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_application_default_mode_owner_only(client, db_session, auth_user, sample_app_owned_by_user):
    """maintainer+ 才能改 application.default_mode"""
    resp = await client.patch(
        f"/api/applications/{sample_app_owned_by_user.id}/default-mode",
        json={"default_mode": "pro"},
        headers=auth_user["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["default_mode"] == "pro"
```

⚠ fixtures `client`, `auth_user`, `sample_app_owned_by_user` 可能不存在。先看 `backend/conftest.py` 看现有 fixture 模式（参考 Phase A-E 的 `test_application_members_api.py` 函数级测试不启 ASGI HTTP，直接调 handler）。如要重用既有 pattern，把测试退化为函数级（self-seed user/app/role + 直调 handler）。

- [ ] **Step 2: 跑测试 → 预期 404**

Run: `pytest backend/tests/test_preferences_api.py -v`
Expected: 404 (route not registered) 或 ImportError.

- [ ] **Step 3: 写 preferences.py route**

Create `backend/app/routes/preferences.py`:

```python
"""User-level 偏好设置 API (Phase F)"""
from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models.preference import UserPreference

router = APIRouter(prefix="/me", tags=["preferences"])

VALID_MODES = {"simple", "pro"}


class UpdatePreferenceRequest(BaseModel):
    default_mode: str


def _to_dict(pref: UserPreference) -> dict:
    return {"user_id": pref.user_id, "default_mode": pref.default_mode}


@router.get("/preferences")
async def get_my_preferences(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == ctx.user.id)
    )).scalar_one_or_none()
    if not pref:
        pref = UserPreference(user_id=ctx.user.id, default_mode="simple")
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    return _to_dict(pref)


@router.put("/preferences")
async def put_my_preferences(
    req: UpdatePreferenceRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if req.default_mode not in VALID_MODES:
        raise HTTPException(400, f"default_mode 仅支持 {sorted(VALID_MODES)}")
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == ctx.user.id)
    )).scalar_one_or_none()
    if not pref:
        pref = UserPreference(user_id=ctx.user.id, default_mode=req.default_mode)
        db.add(pref)
    else:
        pref.default_mode = req.default_mode
    await db.commit()
    await db.refresh(pref)
    return _to_dict(pref)
```

- [ ] **Step 4: Application default_mode 端点**

修改 `backend/app/routes/applications/__init__.py`，在文件末尾追加：

```python
from app.project_access import require_project_access


class UpdateAppDefaultModeRequest(BaseModel):
    default_mode: Optional[str]  # None or 'simple' or 'pro'


@router.get("/{application_id}/default-mode")
async def get_application_default_mode(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = (await db.execute(
        select(Application).where(
            Application.id == application_id, Application.tenant_id == ctx.tenant_id
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    return {"application_id": app.id, "default_mode": app.default_mode}


@router.patch("/{application_id}/default-mode")
async def patch_application_default_mode(
    application_id: int,
    req: UpdateAppDefaultModeRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = (await db.execute(
        select(Application).where(
            Application.id == application_id, Application.tenant_id == ctx.tenant_id
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    if not app.project_id:
        raise HTTPException(400, "应用未关联 project，无法设置默认模式")
    await require_project_access(
        db, project_id=app.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )
    if req.default_mode not in (None, "simple", "pro"):
        raise HTTPException(400, "default_mode 仅支持 None / 'simple' / 'pro'")
    app.default_mode = req.default_mode
    await db.commit()
    return {"application_id": app.id, "default_mode": app.default_mode}
```

⚠ `Optional` import 在文件顶部，参考既有 imports；`Application` / `select` / `BaseModel` / `Depends` / `Annotated` / `HTTPException` / `AsyncSession` / `AuthContext` / `get_auth_context` / `get_db` 大概率都已 import；缺什么补什么。

- [ ] **Step 5: 注册 router**

修改 `backend/app/main.py`，找现有 `app.include_router(...)` 区域，加：

```python
from app.routes import preferences
app.include_router(preferences.router, prefix="/api")
```

- [ ] **Step 6: 跑测试**

Run: `pytest backend/tests/test_preferences_api.py -v`
Expected: 4 passed (or skip 如缺 fixture).

跑全 backend：
```bash
pytest backend/tests/ -v --tb=short 2>&1 | tail -10
```
Expected: ≥ 201 + 4 = 205 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/preferences.py backend/app/routes/applications/__init__.py backend/app/main.py backend/tests/test_preferences_api.py
git commit -m "$(cat <<'EOF'
feat(phase-f/api): UserPreference + Application default_mode endpoints

- GET/PUT /api/me/preferences (user-level default_mode)
- GET/PATCH /api/applications/{id}/default-mode (maintainer+ 可改)
- 校验 default_mode in {'simple', 'pro'} (preference) 或 {None, 'simple', 'pro'} (app)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: work-state BFF 端点

**Files:**
- Create: `backend/app/routes/work_state.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_work_state.py`

聚合 application + draft + canonical + open_proposals + applied_history + git + members + effective_mode + user_role 一次返回。

- [ ] **Step 1: 写测试 — 函数级风格（参考既有测试）**

Create `backend/tests/test_work_state.py` 至少 3 测试：

1. `test_work_state_returns_aggregated_payload` — 应用绑了 canonical + 1 个 open proposal + 已 applied 1 个 → 返回字段都齐
2. `test_work_state_no_canonical_returns_null` — 全新应用无 canonical → canonical=None, open_proposals=[]
3. `test_work_state_effective_mode_for_contributor_is_simple` — contributor 角色 → effective_mode='simple' 即使 user pref 是 'pro'

测试代码模式参考 `backend/tests/test_application_members_api.py` 的 self-seed 风格（不启 ASGI HTTP）。

- [ ] **Step 2: 跑测试 → 预期 404**

Run: `pytest backend/tests/test_work_state.py -v`
Expected: 404 / ImportError

- [ ] **Step 3: 写实现**

Create `backend/app/routes/work_state.py`:

```python
"""WorkspaceShell 一站式聚合 BFF (Phase F)"""
from __future__ import annotations
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application, ProjectMember, User
from app.models.collaboration import (
    ChangeProposal, GitConnection, ApplicationMember,
)
from app.models.spec import Spec as SpecORM
from app.models.preference import UserPreference
from app.project_access import normalize_project_role
from app.routes.application_members import _user_role_on_application

router = APIRouter(prefix="/applications", tags=["work-state"])


def _effective_mode(user_pref: str, app_default: Optional[str], current_role: str) -> str:
    """contributor/viewer 强制 simple；maintainer+ 看 app_default 优先，再 user_pref"""
    from app.project_access import project_role_at_least
    if not project_role_at_least(current_role, "maintainer"):
        return "simple"
    return app_default or user_pref or "simple"


@router.get("/{application_id}/work-state")
async def get_work_state(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    app = (await db.execute(
        select(Application).where(
            Application.id == application_id, Application.tenant_id == ctx.tenant_id
        )
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")

    # 用户对此应用的 role
    user_role = await _user_role_on_application(db, application=app, user_id=ctx.user.id)
    if not user_role:
        raise HTTPException(403, "无权访问该应用")

    # canonical Spec
    canonical = None
    if app.canonical_spec_id:
        crow = (await db.execute(select(SpecORM).where(SpecORM.id == app.canonical_spec_id))).scalar_one_or_none()
        if crow:
            canonical = {
                "id": crow.id, "version": crow.version, "kind": crow.kind,
                "commit_sha": crow.commit_sha, "updated_at": crow.updated_at.isoformat() if crow.updated_at else None,
            }

    # 当前用户 draft（未 promote 的草稿，按 created_by + application_id 查最新）
    current_draft = None
    drow = (await db.execute(
        select(SpecORM).where(
            SpecORM.application_id == app.id,
            SpecORM.kind == "draft",
            SpecORM.created_by == ctx.user.id,
        ).order_by(SpecORM.updated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if drow:
        current_draft = {
            "id": drow.id, "version": drow.version,
            "completeness_confirmed": drow.completeness_confirmed,
            "completeness_total": drow.completeness_total,
            "updated_at": drow.updated_at.isoformat() if drow.updated_at else None,
        }

    # open / changes_requested / approved 提案
    open_props = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.status.in_(["open", "changes_requested", "approved"]),
        ).order_by(ChangeProposal.created_at.desc())
    )).scalars().all()

    # applied 历史（最近 5）
    applied_props = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.status == "applied",
        ).order_by(ChangeProposal.applied_at.desc()).limit(5)
    )).scalars().all()

    def _prop_dict(p: ChangeProposal) -> dict:
        return {
            "id": p.id, "title": p.title, "status": p.status,
            "created_by": p.created_by, "created_at": p.created_at.isoformat() if p.created_at else None,
            "applied_at": p.applied_at.isoformat() if p.applied_at else None,
            "git_pr_url": p.git_pr_url,
        }

    # git
    git_info = None
    if app.git_repo_url:
        gconn = (await db.execute(
            select(GitConnection).where(GitConnection.project_id == app.project_id)
        )).scalar_one_or_none() if app.project_id else None
        git_info = {
            "repo_url": app.git_repo_url,
            "provider": app.git_provider,
            "default_branch": app.git_default_branch,
            "connected": bool(gconn),
        }

    # members（合并 inherited + direct + creator）
    members: dict[int, dict] = {}
    if app.project_id:
        pm_rows = (await db.execute(
            select(ProjectMember, User).join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == app.project_id)
        )).all()
        for pm, u in pm_rows:
            members[u.id] = {"user_id": u.id, "username": u.username,
                             "role": normalize_project_role(pm.role), "source": "inherited"}
    am_rows = (await db.execute(
        select(ApplicationMember, User).join(User, ApplicationMember.user_id == User.id)
        .where(ApplicationMember.application_id == app.id)
    )).all()
    for am, u in am_rows:
        members[u.id] = {"user_id": u.id, "username": u.username,
                         "role": normalize_project_role(am.role), "source": "direct"}
    if app.created_by not in members:
        creator = (await db.execute(select(User).where(User.id == app.created_by))).scalar_one_or_none()
        if creator:
            members[creator.id] = {"user_id": creator.id, "username": creator.username,
                                   "role": "owner", "source": "creator"}

    # effective_mode
    pref = (await db.execute(
        select(UserPreference).where(UserPreference.user_id == ctx.user.id)
    )).scalar_one_or_none()
    user_mode = pref.default_mode if pref else "simple"
    effective = _effective_mode(user_mode, app.default_mode, user_role)

    return {
        "application": {
            "id": app.id, "app_name": app.app_name, "app_code": app.app_code,
            "status": app.status, "platform_url": app.platform_url,
            "apaas_app_id": app.apaas_app_id,
            "default_mode": app.default_mode,
        },
        "current_draft": current_draft,
        "canonical": canonical,
        "open_proposals": [_prop_dict(p) for p in open_props],
        "applied_history": [_prop_dict(p) for p in applied_props],
        "git": git_info,
        "members": list(members.values()),
        "effective_mode": effective,
        "user_role_on_app": user_role,
        "user_pref_mode": user_mode,
    }
```

- [ ] **Step 4: 注册 router**

修改 `backend/app/main.py`：

```python
from app.routes import work_state
app.include_router(work_state.router, prefix="/api")
```

- [ ] **Step 5: 跑测试 + 全 backend**

Expected: ≥ 205 + 3 = 208 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/work_state.py backend/app/main.py backend/tests/test_work_state.py
git commit -m "$(cat <<'EOF'
feat(phase-f/api): work-state BFF 端点 — 一站式聚合 WorkspaceShell 数据

GET /api/applications/{id}/work-state 返回：
- application 基本信息（含 platform_url + apaas_app_id 给 DeployIframe）
- current_draft / canonical
- open_proposals (open/changes_requested/approved) + applied_history (最近5)
- git 状态 / members（合并 3 类） / effective_mode / user_role / user_pref

contributor/viewer 强制 effective_mode='simple'（即使 user pref 是 pro）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 前端 stores + API clients + 路由

**Files:**
- Create: `frontend/src/api/preferences.ts`
- Create: `frontend/src/api/workState.ts`
- Create: `frontend/src/stores/userPreference.ts`
- Create: `frontend/src/stores/workspace.ts`
- Modify: `frontend/src/router/index.ts`

- [ ] **Step 1: api/preferences.ts**

```typescript
import request from '@/utils/request'

export interface UserPreference {
  user_id: number
  default_mode: 'simple' | 'pro'
}

export const preferencesApi = {
  get(): Promise<UserPreference> {
    return request.get<any, UserPreference>('/me/preferences')
  },
  update(default_mode: 'simple' | 'pro'): Promise<UserPreference> {
    return request.put<any, UserPreference>('/me/preferences', { default_mode })
  },
  getAppDefaultMode(applicationId: number) {
    return request.get<any, { application_id: number; default_mode: string | null }>(
      `/applications/${applicationId}/default-mode`,
    )
  },
  patchAppDefaultMode(applicationId: number, default_mode: 'simple' | 'pro' | null) {
    return request.patch<any, { application_id: number; default_mode: string | null }>(
      `/applications/${applicationId}/default-mode`,
      { default_mode },
    )
  },
}
```

- [ ] **Step 2: api/workState.ts**

```typescript
import request from '@/utils/request'
import type { ProjectRole } from '@/types/collaboration'
import type { ProposalSummary } from '@/types/proposal'

export interface WorkStateMember {
  user_id: number
  username: string
  role: ProjectRole
  source: 'creator' | 'inherited' | 'direct'
}

export interface WorkState {
  application: {
    id: number
    app_name: string
    app_code: string
    status: string
    platform_url: string | null
    apaas_app_id: string | null
    default_mode: 'simple' | 'pro' | null
  }
  current_draft: { id: string; version: number; completeness_confirmed: number; completeness_total: number; updated_at: string } | null
  canonical: { id: string; version: number; kind: string; commit_sha: string | null; updated_at: string } | null
  open_proposals: ProposalSummary[]
  applied_history: ProposalSummary[]
  git: { repo_url: string; provider: string | null; default_branch: string | null; connected: boolean } | null
  members: WorkStateMember[]
  effective_mode: 'simple' | 'pro'
  user_role_on_app: ProjectRole
  user_pref_mode: 'simple' | 'pro'
}

export const workStateApi = {
  get(applicationId: number): Promise<WorkState> {
    return request.get<any, WorkState>(`/applications/${applicationId}/work-state`)
  },
}
```

- [ ] **Step 3: stores/userPreference.ts**

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { preferencesApi, type UserPreference } from '@/api/preferences'

export const useUserPreferenceStore = defineStore('userPreference', () => {
  const pref = ref<UserPreference | null>(null)
  const loading = ref(false)

  async function fetch() {
    if (loading.value) return
    loading.value = true
    try {
      pref.value = await preferencesApi.get()
    } finally {
      loading.value = false
    }
  }

  async function setMode(mode: 'simple' | 'pro') {
    pref.value = await preferencesApi.update(mode)
  }

  return { pref, fetch, setMode }
})
```

- [ ] **Step 4: stores/workspace.ts**

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { workStateApi, type WorkState } from '@/api/workState'

export const useWorkspaceStore = defineStore('workspace', () => {
  const state = ref<WorkState | null>(null)
  const loading = ref(false)
  const error = ref('')

  const effectiveMode = computed(() => state.value?.effective_mode ?? 'simple')
  const application = computed(() => state.value?.application ?? null)

  async function load(applicationId: number) {
    loading.value = true
    error.value = ''
    try {
      state.value = await workStateApi.get(applicationId)
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e?.message || 'load failed'
      state.value = null
    } finally {
      loading.value = false
    }
  }

  async function refresh() {
    if (state.value?.application?.id) {
      await load(state.value.application.id)
    }
  }

  function reset() {
    state.value = null
    error.value = ''
  }

  return { state, loading, error, effectiveMode, application, load, refresh, reset }
})
```

- [ ] **Step 5: 加路由**

修改 `frontend/src/router/index.ts`，在 `/coding` 路由附近加：

```typescript
{
  path: '/work/:appId',
  meta: { requiresAuth: true },
  component: () => import('@/views/WorkspaceShell.vue'),
},
```

- [ ] **Step 6: vue-tsc check**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 干净（虽然 WorkspaceShell.vue 还没造，但路由用了 dynamic import + 组件文件不存在不会让 tsc 报错——下个 task 会建）。

如果 tsc 报错（dynamic import 路径不存在 → ts 检测得到），临时建一个 `frontend/src/views/WorkspaceShell.vue` 空 stub：
```vue
<template><div>WorkspaceShell stub - Task 5 fills it</div></template>
<script setup lang="ts"></script>
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/preferences.ts frontend/src/api/workState.ts frontend/src/stores/userPreference.ts frontend/src/stores/workspace.ts frontend/src/router/index.ts frontend/src/views/WorkspaceShell.vue
git commit -m "$(cat <<'EOF'
feat(phase-f/fe): preferences + workState API clients + Pinia stores + 路由 stub

- api/preferences.ts (4 methods) + types/UserPreference
- api/workState.ts (1 method) + types/WorkState (含 application/draft/canonical/
  open_proposals/applied_history/git/members/effective_mode 等)
- stores/userPreference.ts (fetch/setMode)
- stores/workspace.ts (load/refresh/reset，computed effectiveMode)
- 路由 /work/:appId 加 + WorkspaceShell.vue 空 stub（Task 5 实现）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: WorkspaceShell.vue + WorkspaceTopBar + ModeToggle

**Files:**
- Modify: `frontend/src/views/WorkspaceShell.vue` (替 stub)
- Create: `frontend/src/components/workspace/WorkspaceTopBar.vue`
- Create: `frontend/src/components/workspace/ModeToggle.vue`

- [ ] **Step 1: WorkspaceShell.vue 三栏 layout**

Replace `frontend/src/views/WorkspaceShell.vue`:

```vue
<template>
  <div class="workspace-shell">
    <WorkspaceTopBar
      v-if="store.application"
      :app="store.application"
      :members="store.state?.members || []"
      :git="store.state?.git ?? null"
      :effective-mode="store.effectiveMode"
      :can-toggle-mode="canToggleMode"
      @toggle-mode="onToggleMode"
    />
    <div v-if="store.loading" class="loading">加载中…</div>
    <div v-else-if="store.error" class="error">{{ store.error }}</div>
    <main v-else-if="store.state" class="ws-main">
      <section class="pane chat-pane">
        <!-- ChatPanel — Task 6 实现，先占位 -->
        <p class="muted">ChatPanel 占位（Task 6）</p>
      </section>
      <section class="pane preview-pane">
        <!-- PreviewPanel — Task 7-9 实现 -->
        <p class="muted">PreviewPanel 占位（Tasks 7-9）</p>
      </section>
      <section class="pane activity-pane">
        <!-- ActivityPanel — Task 6 后半实现 -->
        <p class="muted">ActivityPanel 占位（Task 6）</p>
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'
import { useUserPreferenceStore } from '@/stores/userPreference'
import { preferencesApi } from '@/api/preferences'
import { roleAtLeast } from '@/types/collaboration'
import WorkspaceTopBar from '@/components/workspace/WorkspaceTopBar.vue'

const route = useRoute()
const router = useRouter()
const store = useWorkspaceStore()
const prefStore = useUserPreferenceStore()

const appId = computed(() => Number(route.params.appId))

const canToggleMode = computed(() =>
  store.state ? roleAtLeast(store.state.user_role_on_app, 'maintainer') : false
)

async function onToggleMode(newMode: 'simple' | 'pro') {
  if (!store.state || !canToggleMode.value) return
  try {
    await preferencesApi.patchAppDefaultMode(store.state.application.id, newMode)
    await store.refresh()
  } catch (e: any) {
    console.error(e)
  }
}

onMounted(async () => {
  if (!appId.value || !Number.isFinite(appId.value)) {
    router.replace('/apps')
    return
  }
  await Promise.all([prefStore.fetch(), store.load(appId.value)])
})
</script>

<style scoped>
.workspace-shell { display: flex; flex-direction: column; height: 100vh; background: var(--bg); color: var(--fg); }
.ws-main { display: grid; grid-template-columns: 320px 1fr 320px; gap: 1px; flex: 1; min-height: 0; background: var(--line); }
.pane { background: var(--bg-panel); overflow: auto; padding: 16px; }
.loading, .error { padding: 48px; text-align: center; color: var(--fg-muted); }
.error { color: var(--t-danger); }
.muted { color: var(--fg-muted); }
</style>
```

- [ ] **Step 2: WorkspaceTopBar.vue**

```vue
<template>
  <header class="ws-topbar">
    <div class="topbar-left">
      <button class="back-btn" type="button" @click="$router.push('/apps')" title="返回应用列表">
        ← 应用
      </button>
      <h2 class="app-title">{{ app.app_name }}</h2>
      <code class="app-code">{{ app.app_code }}</code>
    </div>
    <div class="topbar-center">
      <ModeToggle
        :mode="effectiveMode"
        :disabled="!canToggleMode"
        @change="$emit('toggleMode', $event)"
      />
    </div>
    <div class="topbar-right">
      <div class="member-avatars" :title="memberSummary">
        <span v-for="m in members.slice(0, 3)" :key="m.user_id" class="avatar">{{ m.username[0].toUpperCase() }}</span>
        <span v-if="members.length > 3" class="avatar-more">+{{ members.length - 3 }}</span>
      </div>
      <span v-if="git" :class="['git-status', git.connected ? 'ok' : 'warn']">
        ◐ {{ git.connected ? 'Synced' : '未连接' }}
      </span>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ModeToggle from './ModeToggle.vue'
import type { WorkStateMember } from '@/api/workState'

const props = defineProps<{
  app: { id: number; app_name: string; app_code: string; status: string }
  members: WorkStateMember[]
  git: { repo_url: string; connected: boolean } | null
  effectiveMode: 'simple' | 'pro'
  canToggleMode: boolean
}>()

defineEmits<{
  toggleMode: [mode: 'simple' | 'pro']
}>()

const memberSummary = computed(() => props.members.map(m => m.username).join(', '))
</script>

<style scoped>
.ws-topbar { display: flex; align-items: center; padding: 8px 16px; background: var(--bg-panel); border-bottom: 1px solid var(--line); gap: 16px; }
.topbar-left { display: flex; gap: 12px; align-items: center; flex: 1; }
.topbar-center { display: flex; justify-content: center; }
.topbar-right { display: flex; gap: 12px; align-items: center; flex: 1; justify-content: flex-end; }
.back-btn { background: transparent; border: 0; color: var(--fg-muted); cursor: pointer; padding: 4px 8px; }
.back-btn:hover { color: var(--fg); }
.app-title { margin: 0; font-size: 16px; color: var(--fg); }
.app-code { font-family: var(--b-mono, monospace); font-size: 12px; color: var(--fg-muted); padding: 2px 6px; background: var(--bg-inset); border-radius: 4px; }
.member-avatars { display: flex; gap: 4px; }
.avatar { width: 24px; height: 24px; border-radius: 50%; background: var(--brand); color: var(--fg-on-ink); display: flex; align-items: center; justify-content: center; font-size: 11px; }
.avatar-more { width: 24px; height: 24px; border-radius: 50%; background: var(--bg-inset); color: var(--fg-muted); display: flex; align-items: center; justify-content: center; font-size: 11px; }
.git-status { font-size: 12px; padding: 2px 8px; border-radius: 8px; }
.git-status.ok { background: var(--t-success-subtle); color: var(--t-success); }
.git-status.warn { background: var(--t-warning-subtle); color: var(--t-warning); }
</style>
```

- [ ] **Step 3: ModeToggle.vue**

```vue
<template>
  <div :class="['mode-toggle', { disabled }]" :title="disabled ? '需 maintainer+ 权限' : ''">
    <button
      type="button"
      :class="{ active: mode === 'simple' }"
      :disabled="disabled"
      @click="onClick('simple')"
    >简单</button>
    <button
      type="button"
      :class="{ active: mode === 'pro' }"
      :disabled="disabled"
      @click="onClick('pro')"
    >专业</button>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  mode: 'simple' | 'pro'
  disabled?: boolean
}>()

const emit = defineEmits<{
  change: [mode: 'simple' | 'pro']
}>()

function onClick(target: 'simple' | 'pro') {
  if (props.disabled || target === props.mode) return
  emit('change', target)
}
</script>

<style scoped>
.mode-toggle { display: inline-flex; background: var(--bg-inset); border-radius: 16px; padding: 2px; }
.mode-toggle button { padding: 4px 12px; background: transparent; border: 0; color: var(--fg-muted); cursor: pointer; border-radius: 14px; font-size: 12px; }
.mode-toggle button.active { background: var(--brand); color: var(--fg-on-ink); }
.mode-toggle.disabled { opacity: 0.6; cursor: not-allowed; }
.mode-toggle button:disabled { cursor: not-allowed; }
</style>
```

- [ ] **Step 4: vue-tsc + 启 dev server smoke**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 干净。

启 preview frontend，进 `/work/<existing-app-id>`，应能看到 topbar + 三栏 layout placeholder。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/WorkspaceShell.vue frontend/src/components/workspace/
git commit -m "$(cat <<'EOF'
feat(phase-f/fe): WorkspaceShell 三栏 layout + WorkspaceTopBar + ModeToggle

- /work/:appId 路由进入：load work-state + user pref
- 顶栏：app 名 + 切换"简单/专业"按钮（contributor disabled） + 成员头像组 + git 状态
- 三栏 layout 用 Tier 1 token，dark 兼容；中间 panel 占位（Tasks 6-9 填充）
- ModeToggle 切换会 PATCH /api/applications/{id}/default-mode（owner+ 才能改）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: ChatPanel + ActivityPanel + 4 张子卡片

**Files:**
- Create: `frontend/src/components/workspace/ChatPanel.vue`
- Create: `frontend/src/components/workspace/ActivityPanel.vue`
- Create: `frontend/src/components/workspace/activity/DraftCard.vue`
- Create: `frontend/src/components/workspace/activity/ProposalCard.vue`
- Create: `frontend/src/components/workspace/activity/DeployedCard.vue`
- Create: `frontend/src/components/workspace/activity/GitStatusCard.vue`
- Modify: `frontend/src/views/WorkspaceShell.vue` (装载新组件)

ChatPanel 第一版：直接复用既有 ChatPage 的 chat 部分（消息流 + composer），通过 conversation_id 关联。简单做法：ChatPanel 内部用 iframe `/chat/:id` 嵌入老页面（v1 简化，避免大重构）。或抽出 chat 核心组件——v1 选 iframe approach（简化）。

⚠ iframe ChatPage 内 → 老 PhaseBar 还在，可能怪。**替代方案：v1 ChatPanel 显示一个简化的"开始 chat"按钮 → 跳转 /chat/:id 老页面 + 新窗口**。或者直接嵌入但隐藏老 PhaseBar via query param（如 `?embed=true`）。

**v1 决策：** ChatPanel iframe `/chat/<conversation_id>?embed=true` + 改 ChatPage 在 `?embed=true` 时隐藏顶栏 PhaseBar / 老 nav。简化路径。

- [ ] **Step 1: ChatPanel.vue iframe approach**

```vue
<template>
  <div class="chat-panel">
    <div v-if="!conversationId" class="empty">
      <p class="muted">还没有对话</p>
      <button class="builder-btn builder-btn-primary" @click="onCreateConversation">开始对话</button>
    </div>
    <iframe
      v-else
      :src="iframeSrc"
      class="chat-iframe"
      sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { conversationApi } from '@/api/conversation'
import { useWorkspaceStore } from '@/stores/workspace'

const store = useWorkspaceStore()
const conversationId = ref<number | null>(null)

const iframeSrc = computed(() => {
  if (!conversationId.value) return ''
  return `/ai-builder/chat/${conversationId.value}?embed=true`
})

async function onCreateConversation() {
  if (!store.application) return
  const conv = await conversationApi.create({
    title: `${store.application.app_name} 对话`,
    agent_type: 'builder',
    project_id: undefined,  // 视实际 conversationApi 接口
  })
  conversationId.value = conv.id
}

onMounted(async () => {
  // v1: 如已有 conversation 与本 application 关联，复用它（这部分需 backend 支持，简化为
  // 用户每次手动开启新对话）
  // TODO Phase F.1.5 加 application_id ↔ conversation_id 关联查询
})
</script>

<style scoped>
.chat-panel { height: 100%; display: flex; flex-direction: column; }
.empty { padding: 32px; text-align: center; }
.empty p { color: var(--fg-muted); margin-bottom: 16px; }
.chat-iframe { flex: 1; border: 0; width: 100%; }
</style>
```

⚠ `?embed=true` 的处理 ChatPage 还要改：在 mount 时如果 query.embed=true 隐藏顶栏 + PhaseBar。这是后续 task 内的小改动，本 task 内一并做：

修改 `frontend/src/views/ChatPage.vue` template 顶部的 PhaseBar / topbar 部分，加 `v-if="!embedMode"` wrapper：

先 grep 看 PhaseBar / 顶栏 wrapper 的结构再改：

```bash
grep -n "PhaseBar\|class=\"top-bar\"\|<header" frontend/src/views/ChatPage.vue | head
```

加：

```typescript
const embedMode = computed(() => route.query.embed === 'true')
```

把 PhaseBar 顶层包成 `<div v-if="!embedMode">...</div>`。

- [ ] **Step 2: ActivityPanel.vue + 4 cards**

`ActivityPanel.vue`：

```vue
<template>
  <div class="activity-panel">
    <DraftCard v-if="draft" :draft="draft" :mode="mode" />
    <ProposalCard
      v-for="p in visibleProposals"
      :key="p.id"
      :proposal="p"
      :mode="mode"
      :role="role"
      @click="$router.push(`/proposals/${p.id}`)"
    />
    <DeployedCard v-if="canonical" :canonical="canonical" :history="appliedHistory" />
    <GitStatusCard v-if="git && mode === 'pro'" :git="git" />

    <div v-if="mode === 'simple'" class="advanced-link">
      <a href="#" @click.prevent="$router.push('/devops?application_id=' + applicationId)">
        🔧 高级 (DevOps) ↗
      </a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import DraftCard from './activity/DraftCard.vue'
import ProposalCard from './activity/ProposalCard.vue'
import DeployedCard from './activity/DeployedCard.vue'
import GitStatusCard from './activity/GitStatusCard.vue'
import type { ProposalSummary } from '@/types/proposal'
import type { ProjectRole } from '@/types/collaboration'

const props = defineProps<{
  applicationId: number
  draft: { id: string; version: number; completeness_confirmed: number; completeness_total: number; updated_at: string } | null
  canonical: { id: string; version: number; updated_at: string } | null
  proposals: ProposalSummary[]
  appliedHistory: ProposalSummary[]
  git: { repo_url: string; connected: boolean; provider: string | null; default_branch: string | null } | null
  mode: 'simple' | 'pro'
  role: ProjectRole
}>()

const router = useRouter()

const visibleProposals = computed(() => {
  if (props.mode === 'simple') return []  // 简单模式不展示提案列表
  return props.proposals
})
</script>

<style scoped>
.activity-panel { display: flex; flex-direction: column; gap: 12px; }
.advanced-link { margin-top: 16px; padding: 8px; text-align: center; }
.advanced-link a { color: var(--brand); font-size: 13px; text-decoration: none; }
.advanced-link a:hover { text-decoration: underline; }
</style>
```

`DraftCard.vue`:

```vue
<template>
  <section class="activity-card">
    <h4>📋 当前草稿</h4>
    <p class="muted">v{{ draft.version }} · 完整度 {{ draft.completeness_confirmed }}/{{ draft.completeness_total }}</p>
    <p class="muted small">最后更新 {{ formatDate(draft.updated_at) }}</p>
    <button v-if="mode === 'pro'" class="builder-btn builder-btn-primary" type="button">Promote to Proposal ↗</button>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  draft: { id: string; version: number; completeness_confirmed: number; completeness_total: number; updated_at: string }
  mode: 'simple' | 'pro'
}>()

function formatDate(s: string): string {
  return new Date(s).toLocaleString()
}
</script>

<style scoped>
.activity-card { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-panel); }
.activity-card h4 { margin: 0 0 8px; font-size: 14px; color: var(--fg); }
.muted { color: var(--fg-muted); font-size: 12px; margin: 4px 0; }
.small { font-size: 11px; }
</style>
```

`ProposalCard.vue`:

```vue
<template>
  <section class="activity-card proposal-card" @click="$emit('click')">
    <h4>🔍 {{ proposal.title }}</h4>
    <span class="status-badge" :class="`status-${proposal.status}`">{{ STATUS_DISPLAY_NAMES[proposal.status] || proposal.status }}</span>
    <p class="muted small">提案者：用户 {{ proposal.created_by }} · {{ formatDate(proposal.created_at) }}</p>
    <button v-if="canApprove" class="builder-btn builder-btn-primary" type="button" @click.stop="$emit('approve')">
      Approve ✓
    </button>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { type ProposalSummary, STATUS_DISPLAY_NAMES } from '@/types/proposal'
import { type ProjectRole, roleAtLeast } from '@/types/collaboration'

const props = defineProps<{
  proposal: ProposalSummary
  mode: 'simple' | 'pro'
  role: ProjectRole
}>()

defineEmits<{ click: []; approve: [] }>()

const canApprove = computed(() =>
  props.proposal.status === 'open' && roleAtLeast(props.role, 'maintainer')
)

function formatDate(s: string | null): string {
  return s ? new Date(s).toLocaleString() : '—'
}
</script>

<style scoped>
.activity-card { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-panel); cursor: pointer; }
.activity-card:hover { background: var(--bg-hover); }
.activity-card h4 { margin: 0 0 8px; font-size: 14px; color: var(--fg); }
.status-badge { padding: 2px 8px; border-radius: 8px; font-size: 11px; }
.status-open { background: var(--brand-soft); color: var(--brand); }
.status-changes_requested { background: var(--t-warning-subtle); color: var(--t-warning); }
.status-approved { background: var(--t-success-subtle); color: var(--t-success); }
.muted { color: var(--fg-muted); font-size: 12px; margin: 4px 0; }
.small { font-size: 11px; }
</style>
```

`DeployedCard.vue`:

```vue
<template>
  <section class="activity-card">
    <h4>✅ 已部署</h4>
    <p>canonical v{{ canonical.version }} · {{ formatDate(canonical.updated_at) }}</p>
    <details v-if="history.length">
      <summary>近 {{ history.length }} 次 apply</summary>
      <ul>
        <li v-for="h in history" :key="h.id">
          <code>{{ h.title }}</code>
          <span class="muted small">{{ formatDate(h.applied_at) }}</span>
        </li>
      </ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import type { ProposalSummary } from '@/types/proposal'

defineProps<{
  canonical: { id: string; version: number; updated_at: string }
  history: ProposalSummary[]
}>()

function formatDate(s: string | null): string {
  return s ? new Date(s).toLocaleString() : '—'
}
</script>

<style scoped>
.activity-card { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-panel); }
.activity-card h4 { margin: 0 0 8px; font-size: 14px; color: var(--fg); }
.muted { color: var(--fg-muted); font-size: 11px; }
ul { padding-left: 16px; margin-top: 8px; font-size: 12px; }
li { color: var(--fg); margin-bottom: 4px; }
code { background: var(--bg-inset); padding: 1px 4px; border-radius: 3px; }
</style>
```

`GitStatusCard.vue`:

```vue
<template>
  <section class="activity-card">
    <h4>🔗 Git 仓库</h4>
    <p>
      <a v-if="git.repo_url" :href="git.repo_url" target="_blank">{{ git.provider || 'git' }} ↗</a>
    </p>
    <p class="muted small">分支：{{ git.default_branch || 'main' }}</p>
    <p :class="['muted', 'small', git.connected ? 'ok' : 'warn']">
      {{ git.connected ? '✓ Connection 配置正常' : '⚠ Project 未连接 git' }}
    </p>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  git: { repo_url: string; provider: string | null; default_branch: string | null; connected: boolean }
}>()
</script>

<style scoped>
.activity-card { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg-panel); }
h4 { margin: 0 0 8px; font-size: 14px; color: var(--fg); }
a { color: var(--brand); text-decoration: none; }
.muted { color: var(--fg-muted); font-size: 11px; }
.small { font-size: 11px; }
.ok { color: var(--t-success); }
.warn { color: var(--t-warning); }
</style>
```

- [ ] **Step 3: 装载到 WorkspaceShell**

修改 `frontend/src/views/WorkspaceShell.vue` 的 `<main>` 内容，把 placeholder 替换：

```vue
<main v-else-if="store.state" class="ws-main">
  <section class="pane chat-pane">
    <ChatPanel />
  </section>
  <section class="pane preview-pane">
    <p class="muted">PreviewPanel 占位（Tasks 7-9）</p>
  </section>
  <section class="pane activity-pane">
    <ActivityPanel
      :application-id="store.state.application.id"
      :draft="store.state.current_draft"
      :canonical="store.state.canonical"
      :proposals="store.state.open_proposals"
      :applied-history="store.state.applied_history"
      :git="store.state.git"
      :mode="store.effectiveMode"
      :role="store.state.user_role_on_app"
    />
  </section>
</main>
```

加 import：
```typescript
import ChatPanel from '@/components/workspace/ChatPanel.vue'
import ActivityPanel from '@/components/workspace/ActivityPanel.vue'
```

- [ ] **Step 4: vue-tsc + smoke**

```bash
cd frontend && npx vue-tsc --noEmit
```

进 preview，URL `/work/<existing-app-id>`，看到 chat 占位（"开始对话"按钮）+ activity panel 卡片。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/WorkspaceShell.vue frontend/src/components/workspace/
git commit -m "$(cat <<'EOF'
feat(phase-f/fe): ChatPanel + ActivityPanel + 4 张子卡片（DraftCard/ProposalCard/DeployedCard/GitStatusCard）

ActivityPanel 行为差异（简单 vs 专业）：
- 简单模式：只显示 DraftCard + DeployedCard + "高级 ↗" 链接
- 专业模式：完整列出提案 + git 状态卡

ProposalCard 内嵌 Approve 按钮（maintainer+ 才显示），点击主体跳 ProposalDetail。

ChatPanel v1：iframe 嵌入 /chat/:id?embed=true（老 ChatPage 复用），TODO 简化
版后续：抽出 chat 核心组件不靠 iframe。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: PreviewPanel 容器 + SpecView (复用 SpecCanvas)

**Files:**
- Create: `frontend/src/components/workspace/PreviewPanel.vue`
- Create: `frontend/src/components/workspace/preview/SpecView.vue`
- Modify: `frontend/src/views/WorkspaceShell.vue`

- [ ] **Step 1: PreviewPanel.vue 容器 + tab 切换**

```vue
<template>
  <div class="preview-panel">
    <nav class="preview-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        :class="{ active: active === tab.key, disabled: tab.disabled }"
        :disabled="tab.disabled"
        @click="active = tab.key"
      >
        {{ tab.label }}
      </button>
    </nav>
    <div class="preview-body">
      <SpecView v-if="active === 'spec'" :draft-spec-id="draftSpecId" />
      <DeployIframe
        v-else-if="active === 'deploy'"
        :platform-url="platformUrl"
        :apaas-app-id="apaasAppId"
      />
      <CodeView v-else-if="active === 'code'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import SpecView from './preview/SpecView.vue'
import DeployIframe from './preview/DeployIframe.vue'
import CodeView from './preview/CodeView.vue'

const props = defineProps<{
  draftSpecId: string | null
  canonicalSpecId: string | null
  platformUrl: string | null
  apaasAppId: string | null
}>()

const active = ref<'spec' | 'deploy' | 'code'>('spec')

const tabs = computed(() => [
  { key: 'spec', label: 'SPEC', disabled: false },
  { key: 'deploy', label: 'Deploy', disabled: !props.platformUrl || !props.apaasAppId },
  { key: 'code', label: 'Code', disabled: false },
])
</script>

<style scoped>
.preview-panel { height: 100%; display: flex; flex-direction: column; }
.preview-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); padding: 0 8px; }
.preview-tabs button { background: transparent; border: 0; color: var(--fg-muted); padding: 8px 16px; cursor: pointer; border-bottom: 2px solid transparent; font-size: 13px; }
.preview-tabs button:hover:not(:disabled) { color: var(--fg); }
.preview-tabs button.active { color: var(--brand); border-bottom-color: var(--brand); }
.preview-tabs button.disabled, .preview-tabs button:disabled { opacity: 0.4; cursor: not-allowed; }
.preview-body { flex: 1; overflow: auto; }
</style>
```

- [ ] **Step 2: SpecView.vue (v1 占位)**

`SpecView.vue` v1 占位（先简单显示 draft id + 链接到老 SpecCanvas）：

```vue
<template>
  <div class="spec-view">
    <div v-if="!draftSpecId" class="empty">
      <p class="muted">尚无草稿，去 chat 开始 AI 编辑</p>
    </div>
    <div v-else class="spec-meta">
      <p>Spec: <code>{{ draftSpecId }}</code></p>
      <p class="muted small">v1 占位：完整 SPEC 编辑界面在 ChatPanel 老页面里。后续 task 抽出 SpecCanvas 嵌入此处。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  draftSpecId: string | null
}>()
</script>

<style scoped>
.spec-view { padding: 16px; height: 100%; }
.empty { display: flex; align-items: center; justify-content: center; height: 100%; color: var(--fg-muted); }
.spec-meta code { background: var(--bg-inset); padding: 2px 6px; border-radius: 3px; font-family: var(--b-mono, monospace); }
.muted { color: var(--fg-muted); font-size: 12px; }
.small { font-size: 11px; }
</style>
```

⚠ Phase F.v1 不抽出完整 SpecCanvas（避免大改 ChatPage）；SPEC 视图仍在 ChatPanel iframe 内。Preview Panel 的 SPEC tab 是元信息显示。这是 v1 简化，未来 v2 可重构。

- [ ] **Step 3: 装载 PreviewPanel + 占位 DeployIframe / CodeView**

为了让 Task 7 commit 不依赖 Task 8 / 9，先建 stub 文件让 import 通过：

`frontend/src/components/workspace/preview/DeployIframe.vue` (stub):
```vue
<template><div class="muted">DeployIframe stub - Task 8</div></template>
<script setup lang="ts">
defineProps<{ platformUrl: string | null; apaasAppId: string | null }>()
</script>
<style scoped>.muted { padding: 16px; color: var(--fg-muted); }</style>
```

`frontend/src/components/workspace/preview/CodeView.vue` (stub):
```vue
<template><div class="muted">CodeView stub - Task 9</div></template>
<script setup lang="ts"></script>
<style scoped>.muted { padding: 16px; color: var(--fg-muted); }</style>
```

修改 `frontend/src/views/WorkspaceShell.vue` `preview-pane` section：

```vue
<section class="pane preview-pane">
  <PreviewPanel
    :draft-spec-id="store.state.current_draft?.id ?? null"
    :canonical-spec-id="store.state.canonical?.id ?? null"
    :platform-url="store.state.application.platform_url"
    :apaas-app-id="store.state.application.apaas_app_id"
  />
</section>
```

加 `import PreviewPanel from '@/components/workspace/PreviewPanel.vue'`。

- [ ] **Step 4: vue-tsc + Commit**

```bash
cd frontend && npx vue-tsc --noEmit
```

```bash
git add frontend/src/components/workspace/PreviewPanel.vue frontend/src/components/workspace/preview/ frontend/src/views/WorkspaceShell.vue
git commit -m "$(cat <<'EOF'
feat(phase-f/fe): PreviewPanel 容器 + 3 tabs (SPEC/Deploy/Code) + SpecView v1 占位

PreviewPanel 三 tab 切换，Deploy/Code 是 stub（Tasks 8-9 实现）。
SpecView v1 简化为 spec id 元信息显示，完整 SPEC 编辑仍在 ChatPanel
iframe 内（避免本 phase 大改 ChatPage）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: DeployIframe (真 iframe 嵌入 platform_url)

**Files:**
- Modify: `frontend/src/components/workspace/preview/DeployIframe.vue` (替 stub)

- [ ] **Step 1: 实现**

```vue
<template>
  <div class="deploy-iframe">
    <div v-if="!url" class="empty">
      <p class="muted">应用尚未部署到 aPaaS 平台</p>
    </div>
    <div v-else-if="loadFailed" class="error">
      <p>无法在嵌入框内加载（可能跨域受限）</p>
      <a :href="url" target="_blank" class="builder-btn">在新窗口打开 ↗</a>
    </div>
    <iframe
      v-else
      :src="url"
      :sandbox="sandboxAttr"
      class="iframe"
      @load="onLoad"
      @error="loadFailed = true"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const props = defineProps<{
  platformUrl: string | null
  apaasAppId: string | null
}>()

const url = computed(() => {
  if (!props.platformUrl || !props.apaasAppId) return null
  return `${props.platformUrl.replace(/\/+$/, '')}/app/${props.apaasAppId}`
})

const sandboxAttr = 'allow-same-origin allow-scripts allow-forms allow-popups'
const loadFailed = ref(false)
const loadedOnce = ref(false)

function onLoad() {
  loadedOnce.value = true
}

onMounted(() => {
  // 1.5 秒内若未触发 load，标 fail
  if (url.value) {
    setTimeout(() => {
      if (!loadedOnce.value) loadFailed.value = true
    }, 1500)
  }
})
</script>

<style scoped>
.deploy-iframe { height: 100%; }
.iframe { width: 100%; height: 100%; border: 0; }
.empty, .error { padding: 32px; text-align: center; color: var(--fg-muted); }
.error a { display: inline-block; margin-top: 12px; }
</style>
```

⚠ URL 模式 `/app/{apaas_app_id}` 是 spec 假设；如果 aPaaS 平台实际是其他模式（如 `/runtime/app/{code}` 等），grep 老代码或问 admin 确认。本 task 用 spec 模式占位，handoff 时让用户验证。

- [ ] **Step 2: vue-tsc + Commit**

```bash
git add frontend/src/components/workspace/preview/DeployIframe.vue
git commit -m "$(cat <<'EOF'
feat(phase-f/fe): DeployIframe — 真嵌入 platform_url/app/{apaas_app_id}

URL 模式按 spec §6.X：${platform_url}/app/${apaas_app_id}（实际 URL pattern 待
活体 smoke 时验证）。
- sandbox: allow-same-origin/scripts/forms/popups
- 1.5s 超时未 load 触发 fallback：显示"在新窗口打开"按钮
- platform_url 或 apaas_app_id 为空 → 提示"应用未部署"

跨域 / X-Frame-Options 拒绝 iframe 嵌入时自动 fallback；不影响其他功能。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: CodeView (从老 CodingPage 抽 workspace 部分)

**Files:**
- Modify: `frontend/src/components/workspace/preview/CodeView.vue` (替 stub)

老 CodingPage 是 105KB 大文件。抽出"workspace 文件树 + Monaco 编辑器"成独立组件挑战大。**v1 简化**：CodeView 用 iframe 嵌入老 `/coding?embed=true`，跟 ChatPanel 同思路。

- [ ] **Step 1: 加 ?embed=true 支持到 CodingPage**

```bash
grep -n "PhaseBar\|<header\|class=\"top" frontend/src/views/CodingPage.vue | head -10
```

类似 ChatPage：CodingPage 顶栏 wrap 在 `v-if="!embedMode"`。

```typescript
const embedMode = computed(() => route.query.embed === 'true')
```

- [ ] **Step 2: 实现 CodeView**

```vue
<template>
  <iframe
    src="/ai-builder/coding?embed=true"
    class="code-iframe"
    sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
  />
</template>

<script setup lang="ts"></script>

<style scoped>
.code-iframe { width: 100%; height: 100%; border: 0; }
</style>
```

⚠ 这样的 CodeView v1 不显示"specific application 的 workspaces"——老 CodingPage 是全局 workspace 列表。**v1 接受这个限制**，handoff 标记"v2 抽出 workspace 列表 + 文件树独立组件，绑定 application_id"。

- [ ] **Step 3: vue-tsc + Commit**

```bash
git add frontend/src/components/workspace/preview/CodeView.vue frontend/src/views/CodingPage.vue
git commit -m "$(cat <<'EOF'
feat(phase-f/fe): CodeView — iframe 嵌入老 /coding?embed=true (v1)

ChatPage / CodingPage 都新支持 ?embed=true 隐藏顶栏，让 WorkspaceShell
能干净嵌入。

v1 限制：CodeView 显示的是全局 workspace 列表，不绑 application_id。
v2 标 backlog：抽出 workspace 列表 + 文件树独立组件按 app 过滤。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: PromoteApproveApplyCard (in-chat 简单模式快捷批准)

**Files:**
- Create: `frontend/src/components/workspace/PromoteApproveApplyCard.vue`

简单模式专用：AI 完成一轮编辑后推到 chat 流的卡片，含"Promote & Approve & Apply ✓"按钮。

⚠ ChatPanel v1 是 iframe，无法直接在 chat 内"嵌入"自定义 Vue 卡片。**v1 妥协**：ChatPanel 上方 / ActivityPanel 顶部加一个 PromoteApproveApplyCard，当后端通知有 draft 待 promote 时展示。

- [ ] **Step 1: PromoteApproveApplyCard.vue**

```vue
<template>
  <section v-if="show" class="paa-card">
    <div class="paa-header">
      <span class="paa-icon">🤖</span>
      <h4>AI 准备好一次变更</h4>
    </div>
    <div class="paa-meta">
      <p>{{ summary }}</p>
      <p class="muted small">影响：{{ reversibilityLabel }}</p>
    </div>
    <div class="paa-actions">
      <button class="builder-btn builder-btn-primary" :disabled="working" @click="onApply">
        {{ working ? '执行中...' : 'Promote & Approve & Apply ✓' }}
      </button>
      <button class="builder-btn" :disabled="working" @click="onPromoteOnly">先 Promote</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { proposalsApi } from '@/api/proposals'
import { useWorkspaceStore } from '@/stores/workspace'

const props = defineProps<{
  draftSpecId: string | null
  applicationId: number
  reversibilitySummary?: { red: number; yellow: number; green: number }
}>()

const emit = defineEmits<{
  done: [proposalId: string]
}>()

const store = useWorkspaceStore()
const working = ref(false)
const error = ref('')

const show = computed(() => !!props.draftSpecId)
const summary = computed(() => `Spec ${props.draftSpecId?.slice(0, 12)} 的最新变更`)
const reversibilityLabel = computed(() => {
  const r = props.reversibilitySummary
  if (!r) return '尚未分析'
  if (r.red > 0) return `${r.red} 个不可逆 + ${r.yellow} 部分可逆 + ${r.green} 可逆`
  if (r.yellow > 0) return `${r.yellow} 部分可逆 + ${r.green} 可逆 — 安全`
  return `全部 ${r.green} 个变更可逆 — 完全安全`
})

async function onPromoteOnly() {
  if (!props.draftSpecId) return
  working.value = true
  error.value = ''
  try {
    const res = await proposalsApi.promote(props.applicationId, {
      title: `AI 编辑：${new Date().toLocaleString()}`,
      draft_spec_id: props.draftSpecId,
    })
    emit('done', res.id)
    await store.refresh()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'promote 失败'
  } finally {
    working.value = false
  }
}

async function onApply() {
  if (!props.draftSpecId) return
  working.value = true
  error.value = ''
  try {
    // 1. promote
    const promoteRes = await proposalsApi.promote(props.applicationId, {
      title: `AI 编辑（in-chat 自动）：${new Date().toLocaleString()}`,
      draft_spec_id: props.draftSpecId,
    })
    if (promoteRes.status !== 'open') {
      throw new Error(`第一道门未通过：${JSON.stringify(promoteRes.validation_report)}`)
    }
    // 2. review approve（用当前用户身份）
    await proposalsApi.review(promoteRes.id, 'approve', 'in-chat 快捷批准 (Phase F simple mode)')
    // 3. apply（先尝试不带 confirm_irreversible）
    const applyRes = await proposalsApi.apply(promoteRes.id, false)
    if (applyRes.status === 'needs_confirmation') {
      // 弹不可逆 modal（用 window.confirm 简化；正式版用 BaseDialog）
      const confirmed = window.confirm(
        '⚠ 此变更含不可逆操作，apply 后无法直接撤销。继续？',
      )
      if (!confirmed) {
        emit('done', promoteRes.id)
        await store.refresh()
        return
      }
      await proposalsApi.apply(promoteRes.id, true)
    }
    emit('done', promoteRes.id)
    await store.refresh()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'apply 失败'
  } finally {
    working.value = false
  }
}
</script>

<style scoped>
.paa-card { padding: 16px; border: 1px solid var(--brand); border-radius: 8px; background: var(--brand-soft); margin-bottom: 16px; }
.paa-header { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.paa-header h4 { margin: 0; color: var(--fg); }
.paa-icon { font-size: 18px; }
.paa-meta p { margin: 4px 0; color: var(--fg); font-size: 13px; }
.muted { color: var(--fg-muted); font-size: 11px; }
.small { font-size: 11px; }
.paa-actions { display: flex; gap: 8px; margin-top: 12px; }
.error { color: var(--t-danger); font-size: 12px; margin-top: 8px; }
</style>
```

- [ ] **Step 2: 嵌入 ChatPanel 顶部**

修改 `ChatPanel.vue`：

```vue
<template>
  <div class="chat-panel">
    <PromoteApproveApplyCard
      v-if="store.effectiveMode === 'simple' && store.state?.current_draft && store.state?.application"
      :draft-spec-id="store.state.current_draft.id"
      :application-id="store.state.application.id"
      @done="onProposalDone"
    />
    <!-- iframe + empty 等既有 -->
  </div>
</template>
```

加 import + handler:
```typescript
import PromoteApproveApplyCard from './PromoteApproveApplyCard.vue'
import { useWorkspaceStore } from '@/stores/workspace'

const store = useWorkspaceStore()

function onProposalDone(_id: string) {
  // store.refresh 已经在 PromoteApproveApplyCard 内部调
}
```

- [ ] **Step 3: vue-tsc + Commit**

```bash
git add frontend/src/components/workspace/PromoteApproveApplyCard.vue frontend/src/components/workspace/ChatPanel.vue
git commit -m "$(cat <<'EOF'
feat(phase-f/fe): PromoteApproveApplyCard — 简单模式 in-chat 快捷批准

简单模式 ChatPanel 顶部展示卡片：当前用户有 draft → 显示 AI 提案预览 +
"Promote & Approve & Apply ✓" 一键按钮 + "先 Promote" 备选按钮。

一键按钮串联：promote (第一道门) → review approve (本人) → apply
(如不可逆弹 confirm modal 必须人工二次确认)。审批 gate 不绕，
但用户体验上"对话 → 一键发布"一气呵成。

专业模式不显示此卡（去 ActivityPanel / ProposalDetail 走完整流）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: 改 Apps 页卡片点击跳 /work/:appId

**Files:**
- Modify: `frontend/src/views/Apps.vue`

- [ ] **Step 1: grep 现有卡片点击 handler**

```bash
grep -nE "onCard|@click|router.push" frontend/src/views/Apps.vue | head -20
```

找到现有 application 卡片的 `@click` handler（通常是跳 `/chat/:id` 或 `/project/:id`）。

- [ ] **Step 2: 改跳 /work/:appId**

主 click 行为改为：
```typescript
function onCardClick(app: any) {
  const appIdNum = Number(app.id)
  if (Number.isFinite(appIdNum) && appIdNum > 0) {
    router.push(`/work/${appIdNum}`)
  } else {
    // remote app 没有 builder application id，fallback 到老路径
    router.push(`/chat`)  // 或 ProjectOverview
  }
}
```

如果老 click 行为复杂（按 status 不同跳不同 page），保留为"在 ChatPage 打开"备选按钮，主 click 跳 /work。

- [ ] **Step 3: vue-tsc + Commit**

```bash
git add frontend/src/views/Apps.vue
git commit -m "$(cat <<'EOF'
feat(phase-f/fe): Apps 卡片点击默认跳 /work/:appId

进入新 WorkspaceShell。老路径（/chat/:id, /project/:id 等）保留为
备选按钮 / NavRail 入口，向后兼容。

remote-only 应用（id 不是数字）fallback 到老路径。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: BaseDialog + BaseToast + 替换 alert/confirm

**Files:**
- Create: `frontend/src/components/BaseDialog.vue`
- Create: `frontend/src/components/BaseToast.vue`
- Modify: ~10 处 alert/confirm 调用方

替换的目标文件清单（grep `alert(\|confirm(\|prompt(` 找）：
- `frontend/src/components/MembersPanel.vue` — `alert` + `confirm` (Phase A)
- `frontend/src/views/ProposalDetailPage.vue` — `alert` (Phase B)
- `frontend/src/views/ProjectGitSetup.vue` — `prompt` (Phase D OAuth) + `confirm`
- `frontend/src/views/GitOAuthCallback.vue` — 提示
- `frontend/src/views/CodingPage.vue` — `alert`（Sync to repo 按钮，Phase D Task 6）

⚠ Phase D 已经把多数 alert 换成 ElMessage 风格——本 task 主要补漏 + 统一一个 BaseDialog 组件。

- [ ] **Step 1: BaseDialog.vue**

```vue
<template>
  <Teleport to="body">
    <div v-if="visible" class="bd-backdrop" @click.self="onCancel">
      <div class="bd-modal">
        <h4 v-if="title" class="bd-title">{{ title }}</h4>
        <p v-if="message" class="bd-message">{{ message }}</p>
        <slot></slot>
        <div class="bd-actions">
          <button v-if="cancelText" class="builder-btn" type="button" @click="onCancel">{{ cancelText }}</button>
          <button :class="['builder-btn', dangerous ? 'builder-btn-danger' : 'builder-btn-primary']" type="button" @click="onConfirm">
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
const props = defineProps<{
  visible: boolean
  title?: string
  message?: string
  confirmText?: string
  cancelText?: string
  dangerous?: boolean
}>()

const emit = defineEmits<{ confirm: []; cancel: [] }>()

function onConfirm() { emit('confirm') }
function onCancel() { emit('cancel') }

const _ = props
</script>

<style scoped>
.bd-backdrop { position: fixed; inset: 0; background: var(--t-bg-overlay, rgba(0,0,0,.5)); display: flex; align-items: center; justify-content: center; z-index: 2000; }
.bd-modal { background: var(--bg-panel); color: var(--fg); padding: 24px; border-radius: 8px; min-width: 320px; max-width: 600px; box-shadow: var(--sh-pop); }
.bd-title { margin: 0 0 12px; font-size: 16px; }
.bd-message { color: var(--fg-muted); margin: 8px 0; }
.bd-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
</style>
```

设默认 props：

```typescript
withDefaults(defineProps<{
  visible: boolean
  title?: string
  message?: string
  confirmText?: string
  cancelText?: string
  dangerous?: boolean
}>(), {
  confirmText: '确认',
  cancelText: '取消',
  dangerous: false,
})
```

- [ ] **Step 2: BaseToast.vue**

```vue
<template>
  <Teleport to="body">
    <transition name="toast">
      <div v-if="visible" :class="['bt-toast', `bt-${type}`]">
        {{ message }}
      </div>
    </transition>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{
  visible: boolean
  message: string
  type?: 'info' | 'success' | 'warn' | 'error'
}>()
</script>

<style scoped>
.bt-toast { position: fixed; top: 24px; right: 24px; padding: 12px 20px; border-radius: 8px; z-index: 3000; box-shadow: var(--sh-pop); font-size: 13px; }
.bt-info { background: var(--brand-soft); color: var(--brand); }
.bt-success { background: var(--t-success-subtle); color: var(--t-success); }
.bt-warn { background: var(--t-warning-subtle); color: var(--t-warning); }
.bt-error { background: var(--t-danger-subtle); color: var(--t-danger); }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(-8px); }
.toast-enter-active, .toast-leave-active { transition: all .2s; }
</style>
```

- [ ] **Step 3: 替换 alert/confirm — MembersPanel 示例**

在 `MembersPanel.vue` 找 `if (!confirm(...)) return` 改为用 BaseDialog state：

```vue
<template>
  <!-- 既有 ... -->
  <BaseDialog
    :visible="removeDialogVisible"
    :title="`移除成员`"
    :message="`确认移除 ${pendingRemove?.username}？`"
    dangerous
    confirm-text="移除"
    @confirm="confirmRemove"
    @cancel="removeDialogVisible = false"
  />
</template>
```

```typescript
const removeDialogVisible = ref(false)
const pendingRemove = ref<AnyMember | null>(null)

async function onRemove(m: AnyMember) {
  pendingRemove.value = m
  removeDialogVisible.value = true
}
async function confirmRemove() {
  if (!pendingRemove.value) return
  removeDialogVisible.value = false
  try {
    await props.remove(pendingRemove.value.user_id)
    await refresh()
  } catch (e: any) { /* ... */ }
}
```

类似改 alert("…") 用 BaseToast。

⚠ 替换面较广（5+ 文件），单 commit 太大。**拆 2 个 commit**：
- commit a: BaseDialog + BaseToast 组件 + MembersPanel 替换
- commit b: 其余 4 处替换

- [ ] **Step 4: 跑全 frontend vue-tsc + Commit a**

```bash
cd frontend && npx vue-tsc --noEmit
git add frontend/src/components/BaseDialog.vue frontend/src/components/BaseToast.vue frontend/src/components/MembersPanel.vue
git commit -m "feat(phase-f/fe): BaseDialog + BaseToast 统一组件 + MembersPanel 替换原生 confirm/alert"
```

- [ ] **Step 5: Commit b — 替换其余 4 处**

按 ProposalDetailPage / ProjectGitSetup / GitOAuthCallback / CodingPage 顺序替换。

```bash
git add frontend/src/views/ProposalDetailPage.vue frontend/src/views/ProjectGitSetup.vue frontend/src/views/GitOAuthCallback.vue frontend/src/views/CodingPage.vue
git commit -m "fix(phase-f/fe): ProposalDetail / ProjectGitSetup / OAuthCallback / CodingPage 用 BaseDialog/BaseToast 替原生弹窗"
```

---

## Task 13: 全 Phase F 回归 + 总验收 + handoff

- [ ] **Step 1: backend pytest**

```bash
cd backend && source venv/bin/activate
pytest tests/ -v --tb=short 2>&1 | tail -15
```

Expected: ≥ 199 + Phase F 新增 (~10) ≈ 210 passed.

- [ ] **Step 2: frontend vue-tsc**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 干净。

- [ ] **Step 3: dev server smoke**

启 backend + frontend，进 `/work/<existing-app-id>`：
1. 顶栏渲染 + ModeToggle 切换 OK
2. ChatPanel iframe 加载 chat（embed=true 模式无 PhaseBar）
3. PreviewPanel SPEC tab 显示 spec id；Deploy tab 尝试 iframe 平台 URL；Code tab iframe coding
4. ActivityPanel 显示 draft / proposals / canonical / git 卡片
5. 简单模式：ChatPanel 顶部显示 PromoteApproveApplyCard
6. mode toggle 切到专业 → ActivityPanel 多出 git 卡 + proposal 列表完整 + PromoteApproveApplyCard 隐藏
7. dark 模式切换 OK

- [ ] **Step 4: 写 handoff**

Create `docs/superpowers/HANDOFF-phase-f-done.md`:

```markdown
# Phase F 完成交接 — UX WorkspaceShell + 双轨

**Date**: <填实际日期>
**Branch**: `claude/coding-shell-alignment` (HEAD `<sha>`)
**Tests**: backend pytest <X passed>, frontend vue-tsc 干净
**Commits**: Phase F 共 <N> 个 commit（自 ac9bdca spec 起）

---

## 落地内容

### 后端
- `backend/app/models/preference.py` — UserPreference ORM
- `backend/app/models/__init__.py` — Application.default_mode 列
- `backend/scripts/migrate_phase_f.sql` — applied
- `backend/app/routes/preferences.py` — GET/PUT /api/me/preferences
- `backend/app/routes/applications/__init__.py` — GET/PATCH /api/applications/{id}/default-mode
- `backend/app/routes/work_state.py` — GET /api/applications/{id}/work-state (BFF)

### 前端
- `frontend/src/views/WorkspaceShell.vue` — 主页面 /work/:appId
- `frontend/src/components/workspace/{WorkspaceTopBar,ModeToggle,ChatPanel,PreviewPanel,ActivityPanel,PromoteApproveApplyCard}.vue`
- `frontend/src/components/workspace/preview/{SpecView,DeployIframe,CodeView}.vue`
- `frontend/src/components/workspace/activity/{DraftCard,ProposalCard,DeployedCard,GitStatusCard}.vue`
- `frontend/src/stores/{workspace,userPreference}.ts`
- `frontend/src/api/{preferences,workState}.ts`
- `frontend/src/components/{BaseDialog,BaseToast}.vue`
- 替换 ~5 处 alert/confirm 用 BaseDialog/BaseToast

### 顺手清理
- ChatPage / CodingPage 加 ?embed=true 隐藏顶栏支持

---

## 验证状态

### ✅ 已验证
- backend pytest <X passed>
- frontend vue-tsc 干净
- dev server smoke：WorkspaceShell 三栏 + 模式切换 + iframe 嵌入 + Activity 卡片渲染

### ⚠️ 未活体验证
- DeployIframe URL 模式 `${platform_url}/app/${apaas_app_id}` 可能不对，要在测试 tenant 上看实际 aPaaS 平台 URL pattern
- iframe 跨域 / X-Frame-Options：需要 aPaaS 平台运维允许 builder 域名嵌入；否则自动 fallback "在新窗口打开"
- 简单模式 PromoteApproveApplyCard 一键发布全链路：promote → 自动 approve → apply (含不可逆 modal)，需要测试 tenant 真测
- ChatPanel iframe ?embed=true：需 ChatPage / CodingPage 顶栏隐藏验证

---

## 已知 backlog（不阻塞）

1. **SPEC tab v1 占位**：完整 SPEC 编辑界面在 ChatPanel iframe 内，Preview Panel SPEC tab 只显示 spec id。v2 抽出 SpecCanvas 独立组件嵌入此处
2. **CodeView v1 不绑 application**：iframe 嵌入老 /coding，显示全局 workspace 列表。v2 抽出 workspace 列表 + 文件树独立组件按 app 过滤
3. **ChatPanel iframe 限制**：iframe 内的 chat events 不能直接通知外层（PromoteApproveApplyCard 不能"跟随 AI 完成一轮编辑"自动出现）。v2 抽出 chat 核心组件不靠 iframe
4. **PromoteApproveApplyCard 不可逆 confirm 用 window.confirm**：v2 用 BaseDialog 替（Task 12 已建组件）
5. **ChatPanel application_id ↔ conversation_id 关联**：v1 是手动开新对话；v2 后端加端点查"此应用关联的活跃 conversation"自动复用

---

## Phase G 启动建议

UX 进一步深化 + ABCDE 落地的细节打磨：
- SpecCanvas 抽出嵌入 PreviewPanel SPEC tab（删除 v1 iframe 妥协）
- CodingPage workspace 抽出按 app 过滤
- chat 核心组件抽出（不靠 iframe）+ in-chat 自定义卡片消息（PromoteApproveApplyCard 真嵌 chat 流）
- Application member 邀请 flow（替 Phase A 的 prompt UX）
- 完整 PR-style review UI（diff 行内 comment）

backlog 拉满。先做 v2 chat 抽出最实用。
```

补全数字。

- [ ] **Step 5: Commit handoff**

```bash
git add docs/superpowers/HANDOFF-phase-f-done.md
git commit -m "$(cat <<'EOF'
docs(handoff): Phase F UX WorkspaceShell + 双轨完成交接

新建 /work/:appId WorkspaceShell（左 Chat / 中 Preview / 右 Activity）+
"简单 / 专业"模式开关 + UserPreference + work-state BFF + in-chat
PromoteApproveApplyCard + BaseDialog/BaseToast。老路由全保留。

backend pytest <X>/<Y> + frontend vue-tsc 干净。
v1 简化项（SpecView / CodeView / ChatPanel 都是 iframe）见 backlog。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## 自检（Plan Self-Review）

**Spec 覆盖核对** vs `2026-04-25-phase-f-ux-workspace-shell-design.md`：

| Spec 节 | Plan Task |
|---------|-----------|
| §3 WorkspaceShell layout + 模式差异 | Task 5 + Task 6 |
| §4 数据模型（UserPreference + Application.default_mode） | Task 1 |
| §5 API 表面（preferences + work-state + default-mode） | Task 2 + Task 3 |
| §6 前端组件结构 | Task 4-10 + Task 12 |
| §7 模式切换机制（effective_mode 计算 + toggle 行为） | Task 3（后端 _effective_mode） + Task 5（前端 ModeToggle） |
| §8 In-chat Approve 卡片 | Task 10 PromoteApproveApplyCard |
| §9 PreviewPanel Deploy iframe | Task 8 |
| §10 实施分期 Day 1-10 | Task 1-13（13 tasks 对应 ~10 day） |

无遗漏。

**Placeholder scan**：无 TBD/TODO；具体代码块都给了。SpecView / CodeView 的 v1 简化（iframe 妥协）已明确写在 task 内 + handoff backlog。

**Type 一致性**：
- `WorkState` interface 前后端字段一一对应（Task 3 后端 + Task 4 前端）
- `effective_mode` / `default_mode` 字面量 'simple' | 'pro' 全程一致
- ProposalSummary / ProjectRole 复用既有 Phase B/A types

---

## 执行选择

Plan complete and saved to `docs/superpowers/plans/2026-04-25-phase-f-workspace-shell.md`. 沿用 ABCDE 的 **Subagent-Driven** 模式继续执行。

⚠ 执行前注意：
1. dev MySQL 需要先跑 `migrate_phase_f.sql`（Task 1 Step 2）
2. iframe 跨域、Deploy URL 模式实际值 都是 v1 假设，handoff 前真测
