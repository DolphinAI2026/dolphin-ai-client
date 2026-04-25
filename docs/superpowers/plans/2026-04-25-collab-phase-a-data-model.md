# 协作 Phase A — 数据模型 + Project 协作（实施计划）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地协作式 SPEC 管理的数据底座 —— 改造 Project/ProjectMember 的 role 体系（统一为 owner/maintainer/contributor/viewer），新建 5 张协作相关空表（ApplicationMember/ChangeProposal/ProposalReview/GitConnection/PlatformDriftLog），扩展 Spec 模型支持 draft/canonical 区分 + 乐观锁，新增 ApplicationMember 邀请 API + 前端 Apps 页成员入口。

**Architecture:**
- 后端：扩展 ORM models + 新建 collaboration.py + 升级 spec persistence 加乐观锁；改造 routes/projects.py 的 role 校验；新增 routes/application_members.py。
- 前端：新增 collaboration types + API client + 可复用 MembersPanel 组件，挂到 Apps 页和 ProjectOverview。
- 迁移：单一 SQL DDL 脚本（幂等）+ Python seed 脚本回填遗留 Application 的 Project 关联。
- 不在范围：ChangeProposal 创建/校验/apply 流程（Phase B）；git 同步（Phase C/D）；UI 变更中心改写（Phase B/C）。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.x async + aiomysql; Vue 3 + TypeScript + Pinia + Element Plus; pytest + asyncio。

**预设上下文路径基准**：项目根 = `/Users/mars/Vibe Coding/apaas-builder-ai`。后端工作目录 `backend/`，前端 `frontend/`。

**约定**：所有 git commit message 使用中文 + Conventional Commits 风格，与现有 git log 一致（参考 `7a9d808 docs(handoff): 2026-04-25 SPEC 状态机 + CodingPage 重设交接`）。每个 task 末尾的 commit 步骤是必须的。

---

## Task 1: 创建数据库迁移 SQL 脚本

**Files:**
- Create: `backend/scripts/migrate_collab_v1.sql`

- [ ] **Step 1: 写迁移 DDL**

Create file `backend/scripts/migrate_collab_v1.sql` with content:

```sql
-- 协作 Phase A 迁移：数据模型扩展 + role 命名统一 + 5 张新表
-- 幂等可重跑

-- 1. specs 表扩展：kind / commit_sha / version 已存在但要确保 NOT NULL
ALTER TABLE specs
  ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'draft' AFTER version,
  ADD COLUMN IF NOT EXISTS commit_sha VARCHAR(64) NULL AFTER kind;

-- specs.tenant_id 之前默认 1，删除默认值（不直接改 NOT NULL 因为旧数据可能无 tenant 关联）
-- 先确保无 NULL 值
UPDATE specs SET tenant_id = 1 WHERE tenant_id IS NULL;
ALTER TABLE specs MODIFY COLUMN tenant_id INT NOT NULL;

-- 2. applications.module_owners JSON nullable
ALTER TABLE applications
  ADD COLUMN IF NOT EXISTS module_owners JSON NULL AFTER canonical_spec_id;

-- 3. project_members.role 值迁移：admin → maintainer，member → contributor
UPDATE project_members SET role = 'maintainer' WHERE role = 'admin';
UPDATE project_members SET role = 'contributor' WHERE role = 'member';
-- owner 保持

-- 4. application_members 新建（应用级外部协作者）
CREATE TABLE IF NOT EXISTS application_members (
  id INT NOT NULL AUTO_INCREMENT,
  application_id INT NOT NULL,
  user_id INT NOT NULL,
  role VARCHAR(20) NOT NULL DEFAULT 'contributor',
  invited_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_app_member (application_id, user_id),
  KEY idx_app_member_user (user_id),
  CONSTRAINT fk_app_member_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
  CONSTRAINT fk_app_member_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_app_member_invited FOREIGN KEY (invited_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. change_proposals 空表（Phase B 才会写入数据，先建表）
CREATE TABLE IF NOT EXISTS change_proposals (
  id VARCHAR(40) NOT NULL,
  application_id INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  description TEXT NULL,
  draft_spec_id VARCHAR(40) NOT NULL,
  base_canonical_spec_id VARCHAR(40) NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'draft',
  validation_report JSON NULL,
  apply_plan JSON NULL,
  apply_log JSON NULL,
  git_branch VARCHAR(255) NULL,
  git_pr_url VARCHAR(500) NULL,
  created_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  applied_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_proposal_app_status (application_id, status),
  KEY idx_proposal_draft (draft_spec_id),
  CONSTRAINT fk_proposal_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
  CONSTRAINT fk_proposal_draft FOREIGN KEY (draft_spec_id) REFERENCES specs(id),
  CONSTRAINT fk_proposal_base FOREIGN KEY (base_canonical_spec_id) REFERENCES specs(id),
  CONSTRAINT fk_proposal_created_by FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. proposal_reviews 空表
CREATE TABLE IF NOT EXISTS proposal_reviews (
  id INT NOT NULL AUTO_INCREMENT,
  proposal_id VARCHAR(40) NOT NULL,
  reviewer_id INT NOT NULL,
  action VARCHAR(20) NOT NULL,
  body TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_review_proposal (proposal_id),
  CONSTRAINT fk_review_proposal FOREIGN KEY (proposal_id) REFERENCES change_proposals(id) ON DELETE CASCADE,
  CONSTRAINT fk_review_reviewer FOREIGN KEY (reviewer_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. git_connections 空表（项目级 git 凭证）
CREATE TABLE IF NOT EXISTS git_connections (
  id INT NOT NULL AUTO_INCREMENT,
  project_id INT NOT NULL,
  provider VARCHAR(20) NOT NULL,
  host VARCHAR(255) NOT NULL,
  access_token_enc TEXT NOT NULL,
  group_id_or_org VARCHAR(255) NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'connected',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_git_conn_project (project_id),
  CONSTRAINT fk_git_conn_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. platform_drift_logs 空表
CREATE TABLE IF NOT EXISTS platform_drift_logs (
  id INT NOT NULL AUTO_INCREMENT,
  application_id INT NOT NULL,
  detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  git_sha VARCHAR(64) NULL,
  builder_canonical_sha VARCHAR(64) NULL,
  kind VARCHAR(30) NOT NULL,
  resolution_direction VARCHAR(30) NULL,
  resolved_by INT NULL,
  resolved_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_drift_app (application_id),
  CONSTRAINT fk_drift_app FOREIGN KEY (application_id) REFERENCES applications(id) ON DELETE CASCADE,
  CONSTRAINT fk_drift_resolved_by FOREIGN KEY (resolved_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. 标记迁移完成（用于幂等检查）
INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_collab_v1', NOW());
```

注意：`__builder_migrations` 表如不存在则需先创建——下一步处理。

- [ ] **Step 2: 加 migrations 元表（如不存在）**

在脚本顶部追加：

```sql
-- 0. 迁移记录表（幂等保障）
CREATE TABLE IF NOT EXISTS __builder_migrations (
  name VARCHAR(100) NOT NULL,
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

将这段 SQL 插入到脚本最顶部（在 `-- 1. specs 表扩展` 之前）。

- [ ] **Step 3: 在 dev MySQL 上跑一遍验证**

Run:
```bash
cd backend && source venv/bin/activate
python -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def run():
    engine = create_async_engine(os.environ.get('DATABASE_URL', 'mysql+aiomysql://root:Marscaden123@localhost/apaas_builder'))
    with open('scripts/migrate_collab_v1.sql') as f:
        sql = f.read()
    async with engine.begin() as conn:
        for stmt in sql.split(';'):
            stmt = stmt.strip()
            if stmt and not stmt.startswith('--'):
                await conn.execute(text(stmt))
    print('migration applied')
    await engine.dispose()

asyncio.run(run())
"
```

Expected: 输出 `migration applied`，无报错。

- [ ] **Step 4: 验证 schema 正确性**

Run:
```bash
mysql -u root -pMarscaden123 apaas_builder -e "
DESCRIBE specs;
DESCRIBE application_members;
DESCRIBE change_proposals;
DESCRIBE git_connections;
SELECT name FROM __builder_migrations;
SELECT DISTINCT role FROM project_members;
"
```

Expected:
- `specs` 含 `kind`, `commit_sha` 列；`tenant_id` 是 NOT NULL
- `application_members` / `change_proposals` / `git_connections` 表存在
- `__builder_migrations` 含 `migrate_collab_v1`
- `project_members.role` 现在的值都是 `owner` / `maintainer` / `contributor` 之一（看具体数据）

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/migrate_collab_v1.sql
git commit -m "$(cat <<'EOF'
feat(collab/db): Phase A migration — role 重命名 + 5 张协作空表 + Spec.kind/commit_sha

- project_members.role: admin→maintainer, member→contributor
- new tables: application_members, change_proposals, proposal_reviews,
  git_connections, platform_drift_logs
- specs: kind (canonical|draft) + commit_sha + tenant_id NOT NULL
- applications: module_owners JSON nullable

幂等可重跑（用 __builder_migrations 表追踪）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 新增 5 个协作 ORM models

**Files:**
- Create: `backend/app/models/collaboration.py`
- Modify: `backend/app/models/__init__.py`（在文件顶部 import 新 models）

- [ ] **Step 1: 写测试 — 验证 5 个 model 能正确创建/查询**

Create `backend/tests/test_collaboration_models.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.collaboration import (
    ApplicationMember, ChangeProposal, ProposalReview,
    GitConnection, PlatformDriftLog,
)
from app.models import User, Application, Project, Tenant


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_application_member_crud(db):
    # 找一个真实 application + user 组合
    app_row = (await db.execute(select(Application).limit(1))).scalar_one_or_none()
    user_row = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if not app_row or not user_row:
        pytest.skip("dev db has no application or user")

    member = ApplicationMember(
        application_id=app_row.id,
        user_id=user_row.id,
        role="contributor",
        invited_by=user_row.id,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    assert member.id is not None
    assert member.role == "contributor"

    # cleanup
    await db.delete(member)
    await db.commit()


@pytest.mark.asyncio
async def test_change_proposal_minimal_create(db):
    app_row = (await db.execute(select(Application).limit(1))).scalar_one_or_none()
    user_row = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    from app.models.spec import Spec as SpecORM
    spec_row = (await db.execute(select(SpecORM).limit(1))).scalar_one_or_none()
    if not (app_row and user_row and spec_row):
        pytest.skip("dev db missing prerequisites")

    proposal = ChangeProposal(
        id="cp_test_phase_a",
        application_id=app_row.id,
        title="测试提案",
        description="phase a smoke",
        draft_spec_id=spec_row.id,
        status="draft",
        created_by=user_row.id,
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)

    assert proposal.id == "cp_test_phase_a"
    assert proposal.status == "draft"

    await db.delete(proposal)
    await db.commit()


@pytest.mark.asyncio
async def test_proposal_review_cascade(db):
    """proposal 删除时 reviews 应被级联删除"""
    app_row = (await db.execute(select(Application).limit(1))).scalar_one_or_none()
    user_row = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    from app.models.spec import Spec as SpecORM
    spec_row = (await db.execute(select(SpecORM).limit(1))).scalar_one_or_none()
    if not (app_row and user_row and spec_row):
        pytest.skip("dev db missing prerequisites")

    proposal = ChangeProposal(
        id="cp_test_cascade",
        application_id=app_row.id,
        title="cascade test",
        draft_spec_id=spec_row.id,
        status="draft",
        created_by=user_row.id,
    )
    db.add(proposal)
    await db.flush()

    review = ProposalReview(
        proposal_id=proposal.id,
        reviewer_id=user_row.id,
        action="comment",
        body="lgtm",
    )
    db.add(review)
    await db.commit()
    review_id = review.id

    # 删除 proposal — review 应消失（DB CASCADE）
    await db.delete(proposal)
    await db.commit()

    # 重新查 review
    leftover = await db.execute(select(ProposalReview).where(ProposalReview.id == review_id))
    assert leftover.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_git_connection_unique_per_project(db):
    project_row = (await db.execute(select(Project).limit(1))).scalar_one_or_none()
    if not project_row:
        pytest.skip("dev db has no project")

    conn1 = GitConnection(
        project_id=project_row.id,
        provider="gitlab",
        host="https://gitlab.com",
        access_token_enc="enc1",
        status="connected",
    )
    db.add(conn1)
    await db.commit()

    # 第二次插入同 project_id 应失败（unique constraint）
    conn2 = GitConnection(
        project_id=project_row.id,
        provider="github",
        host="https://github.com",
        access_token_enc="enc2",
        status="connected",
    )
    db.add(conn2)
    with pytest.raises(Exception):
        await db.commit()
    await db.rollback()

    # cleanup
    await db.delete(conn1)
    await db.commit()


@pytest.mark.asyncio
async def test_platform_drift_log_create(db):
    app_row = (await db.execute(select(Application).limit(1))).scalar_one_or_none()
    if not app_row:
        pytest.skip("dev db has no application")

    log = PlatformDriftLog(
        application_id=app_row.id,
        kind="drift_detected",
        git_sha="abc123",
        builder_canonical_sha="def456",
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    assert log.id is not None
    assert log.detected_at is not None

    await db.delete(log)
    await db.commit()
```

- [ ] **Step 2: 跑测试，预期 ImportError（model 还没写）**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_collaboration_models.py -v
```

Expected: ImportError: cannot import name 'ApplicationMember' from 'app.models.collaboration'

- [ ] **Step 3: 写 collaboration.py 实现 5 个 model**

Create `backend/app/models/collaboration.py`:

```python
"""协作 Phase A — 5 张新表的 ORM models"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, ForeignKey, JSON, DateTime, Text, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApplicationMember(Base):
    """应用级外部协作者（在 Project member 之外的额外邀请）"""
    __tablename__ = "application_members"
    __table_args__ = (
        UniqueConstraint("application_id", "user_id", name="uq_app_member"),
        Index("idx_app_member_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="contributor", nullable=False)
    invited_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChangeProposal(Base):
    """变更提案（Phase B 起会写入数据，本 Phase 只建表）"""
    __tablename__ = "change_proposals"
    __table_args__ = (
        Index("idx_proposal_app_status", "application_id", "status"),
        Index("idx_proposal_draft", "draft_spec_id"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    draft_spec_id: Mapped[str] = mapped_column(String(40), ForeignKey("specs.id"), nullable=False)
    base_canonical_spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("specs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False)
    validation_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    apply_plan: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    apply_log: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    git_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    git_pr_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ProposalReview(Base):
    """提案的多人评审记录"""
    __tablename__ = "proposal_reviews"
    __table_args__ = (Index("idx_review_proposal", "proposal_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(String(40), ForeignKey("change_proposals.id", ondelete="CASCADE"), nullable=False)
    reviewer_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GitConnection(Base):
    """项目级 git 平台凭证"""
    __tablename__ = "git_connections"
    __table_args__ = (UniqueConstraint("project_id", name="uq_git_conn_project"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    group_id_or_org: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="connected", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlatformDriftLog(Base):
    """漂移检测日志"""
    __tablename__ = "platform_drift_logs"
    __table_args__ = (Index("idx_drift_app", "application_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    git_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    builder_canonical_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    resolution_direction: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    resolved_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 4: 在 `backend/app/models/__init__.py` 顶部 import**

Modify `backend/app/models/__init__.py` after the existing `from app.models.spec import Spec  # noqa: F401  — register ORM mapping` line, add:

```python
from app.models.collaboration import (  # noqa: F401  — register ORM mapping
    ApplicationMember,
    ChangeProposal,
    ProposalReview,
    GitConnection,
    PlatformDriftLog,
)
```

- [ ] **Step 5: 跑测试**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_collaboration_models.py -v
```

Expected: 全部 pass（如 dev db 没数据某些用例会 skip，正常）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/collaboration.py backend/app/models/__init__.py backend/tests/test_collaboration_models.py
git commit -m "$(cat <<'EOF'
feat(collab/models): 新增 5 个协作 ORM models

ApplicationMember / ChangeProposal / ProposalReview / GitConnection /
PlatformDriftLog — Phase A 阶段空表骨架，Phase B/C/D 起会写入数据。

附 e2e 模型 smoke 测试覆盖：基础 crud、级联删除、unique 约束。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 扩展 Spec ORM model（kind / commit_sha / tenant_id NOT NULL）

**Files:**
- Modify: `backend/app/models/spec.py`

- [ ] **Step 1: 写测试 — 验证 kind 字段默认 + commit_sha 可空**

Create `backend/tests/test_spec_orm_phase_a.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.spec import Spec as SpecORM
from app.models import User


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_spec_has_kind_field(db):
    user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if not user:
        pytest.skip("no user")

    s = SpecORM(
        id="spec_test_phase_a_kind",
        version=1,
        payload={},
        phase="gathering",
        created_by=user.id,
        tenant_id=1,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    # 默认 kind 应该是 'draft'
    assert s.kind == "draft"
    assert s.commit_sha is None
    await db.delete(s)
    await db.commit()


@pytest.mark.asyncio
async def test_spec_kind_can_be_canonical(db):
    user = (await db.execute(select(User).limit(1))).scalar_one_or_none()
    if not user:
        pytest.skip("no user")

    s = SpecORM(
        id="spec_test_phase_a_canonical",
        version=1,
        payload={},
        phase="ready",
        kind="canonical",
        commit_sha="abc123def456",
        created_by=user.id,
        tenant_id=1,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    assert s.kind == "canonical"
    assert s.commit_sha == "abc123def456"
    await db.delete(s)
    await db.commit()
```

- [ ] **Step 2: 跑测试，预期失败（field 不存在）**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_spec_orm_phase_a.py -v
```

Expected: AttributeError 或 InstrumentedAttribute error — Spec model 缺 `kind` / `commit_sha`。

- [ ] **Step 3: 修改 `backend/app/models/spec.py`**

Read current content first then rewrite:

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
    kind: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # 'canonical' | 'draft'
    commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    parent_spec_id: Mapped[Optional[str]] = mapped_column(String(40), ForeignKey("specs.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    phase: Mapped[str] = mapped_column(String(20), default="gathering")
    completeness_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    completeness_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    tenant_id: Mapped[int] = mapped_column(Integer, nullable=False)
```

变更点：
- 新增 `kind` 列（默认 'draft'，对应 DB DDL）
- 新增 `commit_sha` 列（nullable）
- `tenant_id` 移除 `default=1`，改成 `nullable=False`（消除"硬编码 default"那条 backlog）

- [ ] **Step 4: 跑测试**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_spec_orm_phase_a.py -v
```

Expected: 2 passed.

- [ ] **Step 5: 也跑现有 spec 测试确保没回归**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_spec_*.py -v
```

Expected: 已有 36 个 test 全过（除 phase_a 新增的 2 个，共 38+ 个 pass）。

- [ ] **Step 6: 修复 `persistence.py` 的 to_orm 兼容**

读 `backend/app/spec/persistence.py:33-47` 的 `to_orm`，**不需要改**——`SpecORM(...)` 不传 `kind` / `commit_sha` 时使用默认值。但要确保 `bootstrap_from_legacy_config` 等场景产生的 spec 默认 `kind='draft'` 是 OK 的（旧应用反推出来的应该是 draft 不是 canonical，OK）。

如果 `to_orm` 调用方需要显式传 kind，新增可选 kwarg：

修改 `backend/app/spec/persistence.py:33`：

```python
def to_orm(spec: Spec, *, tenant_id: int, kind: str = "draft", commit_sha: Optional[str] = None) -> SpecORM:
    return SpecORM(
        id=spec.id,
        application_id=spec.application_id,
        version=spec.version,
        kind=kind,
        commit_sha=commit_sha,
        parent_spec_id=spec.parent_spec_id,
        payload=spec.model_dump(mode="json"),
        phase=spec.phase.value,
        completeness_confirmed=spec.completeness.confirmed,
        completeness_total=spec.completeness.total,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
        created_by=spec.created_by,
        tenant_id=tenant_id,
    )
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/spec.py backend/app/spec/persistence.py backend/tests/test_spec_orm_phase_a.py
git commit -m "$(cat <<'EOF'
feat(collab/spec): Spec ORM 加 kind/commit_sha + tenant_id NOT NULL

- kind: 'canonical' | 'draft'（默认 draft）— 区分 personal draft 和已 apply 的 canonical
- commit_sha: nullable — apply 后绑定的 git commit
- tenant_id: 去掉 default=1，nullable=False（清 backlog M2）

to_orm() 加 kind/commit_sha kwarg 默认值兼容老调用方。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Spec 持久化加乐观锁（Spec.version 并发保护）

**Files:**
- Modify: `backend/app/spec/persistence.py`
- Create: `backend/tests/test_spec_optimistic_locking.py`

**为什么这个 task 在 Phase A**：spec 章节 10 推荐 Phase 0 与 A 并行，且 Phase B 的 ChangeProposal 流程依赖 spec 并发安全。这里用最小改动（compare-and-swap 风格）落地。

- [ ] **Step 1: 写测试 — 模拟并发 save，第二个应失败**

Create `backend/tests/test_spec_optimistic_locking.py`:

```python
import pytest
import pytest_asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.spec.schema import Spec, Phase, Completeness
from app.spec.persistence import save_spec, load_spec, new_spec_id
from app.models import User
from app.models.spec import Spec as SpecORM
from datetime import datetime, timezone


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


def _make_spec(user_id: int) -> Spec:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return Spec(
        id=new_spec_id(),
        version=1,
        phase=Phase.GATHERING,
        completeness=Completeness(),
        created_at=now,
        updated_at=now,
        created_by=user_id,
    )


@pytest.mark.asyncio
async def test_optimistic_lock_first_save_succeeds(db):
    user = (await db.execute(select(User).limit(1))).scalar_one()
    spec = _make_spec(user.id)
    row = await save_spec(db, spec, tenant_id=1)
    assert row.version == 1

    # 取出再 save 一次 — version 自增
    fresh = await load_spec(db, spec.id, tenant_id=1)
    fresh.version = 1  # 老 version
    fresh.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    saved = await save_spec(db, fresh, tenant_id=1)
    assert saved.version == 2  # 自增到 2

    # cleanup
    await db.execute(SpecORM.__table__.delete().where(SpecORM.id == spec.id))
    await db.commit()


@pytest.mark.asyncio
async def test_optimistic_lock_stale_version_rejects(db):
    """两个会话从同一 v=1 取出后并发 save，第二个应被拒绝（OptimisticLockError）"""
    from app.spec.persistence import OptimisticLockError

    user = (await db.execute(select(User).limit(1))).scalar_one()
    spec = _make_spec(user.id)
    await save_spec(db, spec, tenant_id=1)

    # session A 拉到 v=1
    spec_a = await load_spec(db, spec.id, tenant_id=1)
    spec_a.version = 1
    spec_a.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # session B 也拉到 v=1
    spec_b = await load_spec(db, spec.id, tenant_id=1)
    spec_b.version = 1
    spec_b.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # A 先 save → v=2
    await save_spec(db, spec_a, tenant_id=1)

    # B 还以为自己是 v=1，再 save → 应失败
    with pytest.raises(OptimisticLockError):
        await save_spec(db, spec_b, tenant_id=1)

    # cleanup
    await db.execute(SpecORM.__table__.delete().where(SpecORM.id == spec.id))
    await db.commit()
```

- [ ] **Step 2: 跑测试，预期失败**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_spec_optimistic_locking.py -v
```

Expected: ImportError: OptimisticLockError 不存在。

- [ ] **Step 3: 修改 `save_spec` 加乐观锁**

Modify `backend/app/spec/persistence.py`：

a. 在文件顶部 import 区下方加：

```python
class OptimisticLockError(Exception):
    """触发场景：save_spec 时发现 DB 中的 version 比传入的 spec.version 大或不一致。
    意味着有并发会话已先一步保存。调用方应重新 load_spec → 合并 → 再 save。"""
    pass
```

b. 重写 `save_spec`（替换 `backend/app/spec/persistence.py:141-158`）：

```python
async def save_spec(db: AsyncSession, spec: Spec, *, tenant_id: int) -> SpecORM:
    """Upsert Spec by id with optimistic locking.

    新建（DB 无此 id）：直接插入，version=spec.version 或 1。
    已存在：DB row 的 version 必须等于 spec.version（即"我看到的版本"），
            否则 raise OptimisticLockError。成功时 row.version 自增 1。
    """
    existing = await db.execute(select(SpecORM).where(SpecORM.id == spec.id))
    row = existing.scalar_one_or_none()
    if row is None:
        row = to_orm(spec, tenant_id=tenant_id)
        # 新建场景 version 至少 1
        if not row.version:
            row.version = 1
        db.add(row)
    else:
        # 乐观锁：传入 spec.version 必须等于当前 DB row.version
        if row.version != spec.version:
            raise OptimisticLockError(
                f"Spec {spec.id} version mismatch: db={row.version}, incoming={spec.version}"
            )
        row.payload = spec.model_dump(mode="json")
        row.phase = spec.phase.value
        row.completeness_confirmed = spec.completeness.confirmed
        row.completeness_total = spec.completeness.total
        row.application_id = spec.application_id
        row.parent_spec_id = spec.parent_spec_id
        row.updated_at = spec.updated_at
        row.version = row.version + 1  # CAS 自增
    await db.commit()
    return row
```

注意：把 `row.version = spec.version` 那行删掉，改成 `row.version = row.version + 1`（CAS 模式）。

- [ ] **Step 4: 跑测试**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_spec_optimistic_locking.py -v
```

Expected: 2 passed.

- [ ] **Step 5: 跑全部 spec 测试确保不回归**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_spec_*.py -v
```

Expected: 全部 pass（38+ 个）。

如果某些既有测试失败（如 `test_spec_persistence.py` 假设 version 不变），那是因为新的 CAS 行为——读测试代码看是不是测试本身要更新（一般来说，每次 save 后 version+1 是正确行为）。如果是测试错误的假设，更新测试。

- [ ] **Step 6: Commit**

```bash
git add backend/app/spec/persistence.py backend/tests/test_spec_optimistic_locking.py
git commit -m "$(cat <<'EOF'
feat(collab/spec): save_spec 加乐观锁（Spec.version CAS 自增）

并发 save 同一 Spec 时，旧 version 会触发 OptimisticLockError，
调用方需重新 load + 合并 + 再 save。这是 Phase B 多人 draft 协作
和 ChangeProposal apply 串行化的基础。

清 backlog I2（α 安全 follow）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 更新 project_access role 体系（4 档：owner/maintainer/contributor/viewer）

**Files:**
- Modify: `backend/app/project_access.py`
- Create: `backend/tests/test_project_role_levels.py`

- [ ] **Step 1: 写测试 — 4 档 role 比较**

Create `backend/tests/test_project_role_levels.py`:

```python
import pytest
from app.project_access import (
    PROJECT_ROLE_LEVELS,
    normalize_project_role,
    project_role_at_least,
    project_role_permissions,
)


def test_role_levels_ordering():
    assert PROJECT_ROLE_LEVELS["viewer"] < PROJECT_ROLE_LEVELS["contributor"]
    assert PROJECT_ROLE_LEVELS["contributor"] < PROJECT_ROLE_LEVELS["maintainer"]
    assert PROJECT_ROLE_LEVELS["maintainer"] < PROJECT_ROLE_LEVELS["owner"]


def test_normalize_legacy_role_names_mapped():
    """旧 'admin' / 'member' 应自动映射到新名称"""
    assert normalize_project_role("admin") == "maintainer"
    assert normalize_project_role("member") == "contributor"
    assert normalize_project_role("owner") == "owner"
    # 完全未知的值降级到最低 'viewer'（更安全）
    assert normalize_project_role("foo") == "viewer"
    assert normalize_project_role(None) == "viewer"


def test_role_at_least_with_new_names():
    assert project_role_at_least("owner", "maintainer") is True
    assert project_role_at_least("contributor", "maintainer") is False
    assert project_role_at_least("viewer", "contributor") is False
    assert project_role_at_least("contributor", "viewer") is True


def test_role_at_least_with_legacy_names():
    """legacy admin should still satisfy maintainer requirement"""
    assert project_role_at_least("admin", "maintainer") is True
    assert project_role_at_least("member", "contributor") is True


def test_permissions_viewer_read_only():
    perms = project_role_permissions("viewer")
    assert perms["can_view"] is True
    assert perms["can_edit"] is False
    assert perms["can_manage_members"] is False


def test_permissions_contributor_can_edit():
    perms = project_role_permissions("contributor")
    assert perms["can_edit"] is True
    assert perms["can_manage_members"] is False


def test_permissions_maintainer_can_manage_members():
    perms = project_role_permissions("maintainer")
    assert perms["can_edit"] is True
    assert perms["can_manage_members"] is True
    assert perms["can_delete"] is False


def test_permissions_owner_full():
    perms = project_role_permissions("owner")
    assert all(perms.values())
```

- [ ] **Step 2: 跑测试，预期 fail**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_project_role_levels.py -v
```

Expected: 多个失败（'maintainer' / 'contributor' / 'viewer' 不在 PROJECT_ROLE_LEVELS）。

- [ ] **Step 3: 改 `project_access.py`**

Replace `backend/app/project_access.py:13-43` with:

```python
PROJECT_ROLE_LEVELS = {
    "viewer": 1,
    "contributor": 2,
    "maintainer": 3,
    "owner": 4,
}

# 旧名称到新名称的映射（向后兼容，DB 已通过 migration 改了，但 API 入参可能还是旧名称）
LEGACY_ROLE_ALIASES = {
    "member": "contributor",
    "admin": "maintainer",
}


def normalize_project_role(role: Optional[str]) -> str:
    if role in LEGACY_ROLE_ALIASES:
        return LEGACY_ROLE_ALIASES[role]
    if role in PROJECT_ROLE_LEVELS:
        return role
    return "viewer"


def project_role_at_least(role: Optional[str], required: str) -> bool:
    actual = PROJECT_ROLE_LEVELS.get(normalize_project_role(role), 0)
    expected = PROJECT_ROLE_LEVELS.get(normalize_project_role(required), 0)
    return actual >= expected


def project_role_permissions(role: Optional[str]) -> dict[str, bool]:
    normalized = normalize_project_role(role)
    return {
        "can_view": True,  # viewer 起就能看
        "can_edit": project_role_at_least(normalized, "contributor"),
        "can_manage_project": project_role_at_least(normalized, "maintainer"),
        "can_manage_platform": project_role_at_least(normalized, "maintainer"),
        "can_manage_members": project_role_at_least(normalized, "maintainer"),
        "can_manage_member_roles": normalized == "owner",
        "can_delete": normalized == "owner",
        "can_publish": project_role_at_least(normalized, "maintainer"),
    }
```

- [ ] **Step 4: 改 `require_project_access` 默认 minimum_role**

`backend/app/project_access.py:97` 处 `minimum_role: str = "member"` 改为 `minimum_role: str = "contributor"`。

也要改 `backend/app/project_access.py:23` 处 `return "member"` → `return "viewer"`（已在上一步替换中处理）。

- [ ] **Step 5: 跑测试**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_project_role_levels.py -v
```

Expected: 全部 pass。

- [ ] **Step 6: Commit**

```bash
git add backend/app/project_access.py backend/tests/test_project_role_levels.py
git commit -m "$(cat <<'EOF'
feat(collab/role): 统一 4 档 role 体系（owner/maintainer/contributor/viewer）

- PROJECT_ROLE_LEVELS 改成 4 档（新增 viewer 最低档）
- 旧 'admin' / 'member' 在 normalize_project_role 中映射兼容
- permissions 向 GitLab 对齐：maintainer 起可管成员，owner 独占删除
- require_project_access 默认 minimum_role 从 'member' 改 'contributor'

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 改造 routes/projects.py 接受新 role 名

**Files:**
- Modify: `backend/app/routes/projects.py`
- Create: `backend/tests/test_projects_routes_phase_a.py`

- [ ] **Step 1: 写 API 测试 — 新 role 名提交应成功**

Create `backend/tests/test_projects_routes_phase_a.py`:

```python
"""Phase A — projects routes 接受新 role 名"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.main import app
from app.models import User, Project, ProjectMember
from app.models.tenant import UserTenant


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login_token(client: AsyncClient, username: str, password: str = "Test1234!") -> str:
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.mark.asyncio
async def test_add_member_with_new_role_name_contributor(client):
    """POST /api/projects/{id}/members 提交 role='contributor' 应成功"""
    async with AsyncSessionLocal() as db:
        # 找两个真实 user — 一个当 owner，一个当目标
        users = (await db.execute(select(User).limit(5))).scalars().all()
        if len(users) < 2:
            pytest.skip("need 2+ users in dev db")
        owner = users[0]
        target = users[1]
        # 找 owner 拥有的 project
        proj = (await db.execute(
            select(Project).where(Project.user_id == owner.id).limit(1)
        )).scalar_one_or_none()
        if not proj:
            pytest.skip("owner has no project")
        tenant_id = proj.tenant_id

        # 确保 target 在同 tenant
        ut = (await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == target.id,
                UserTenant.tenant_id == tenant_id,
                UserTenant.status == 1,
            )
        )).scalar_one_or_none()
        if not ut:
            pytest.skip("target not in same tenant")

        # 先清掉如果已经是成员
        existing = (await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj.id,
                ProjectMember.user_id == target.id,
            )
        )).scalar_one_or_none()
        if existing:
            await db.delete(existing)
            await db.commit()

    token = await _login_token(client, owner.username)
    resp = await client.post(
        f"/api/projects/{proj.id}/members",
        json={"user_id": target.id, "role": "contributor"},
        headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tenant_id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "contributor"

    # cleanup
    async with AsyncSessionLocal() as db:
        m = (await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj.id,
                ProjectMember.user_id == target.id,
            )
        )).scalar_one_or_none()
        if m:
            await db.delete(m)
            await db.commit()


@pytest.mark.asyncio
async def test_add_member_legacy_role_name_member_aliased(client):
    """旧 role='member' 应自动映射到 contributor（向后兼容）"""
    # 复用 test_add_member_with_new_role_name_contributor 的思路
    # 此处用 role='member' 期待 200 + role='contributor' 返回
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).limit(5))).scalars().all()
        if len(users) < 2:
            pytest.skip("need 2+ users")
        owner, target = users[0], users[1]
        proj = (await db.execute(
            select(Project).where(Project.user_id == owner.id).limit(1)
        )).scalar_one_or_none()
        if not proj:
            pytest.skip()
        tenant_id = proj.tenant_id
        ut = (await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == target.id,
                UserTenant.tenant_id == tenant_id,
                UserTenant.status == 1,
            )
        )).scalar_one_or_none()
        if not ut:
            pytest.skip()
        existing = (await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj.id,
                ProjectMember.user_id == target.id,
            )
        )).scalar_one_or_none()
        if existing:
            await db.delete(existing)
            await db.commit()

    token = await _login_token(client, owner.username)
    resp = await client.post(
        f"/api/projects/{proj.id}/members",
        json={"user_id": target.id, "role": "member"},  # 旧名称
        headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tenant_id)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "contributor"  # 自动 normalize 到新名

    # cleanup
    async with AsyncSessionLocal() as db:
        m = (await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == proj.id,
                ProjectMember.user_id == target.id,
            )
        )).scalar_one_or_none()
        if m:
            await db.delete(m)
            await db.commit()
```

- [ ] **Step 2: 跑测试，预期失败**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_projects_routes_phase_a.py -v
```

Expected: 失败（`projects.py` 还在用旧 role 名 hardcode）。

- [ ] **Step 3: 修改 `routes/projects.py`**

a. `backend/app/routes/projects.py:108-110` 处 `UpdateMemberRoleRequest`：

```python
class UpdateMemberRoleRequest(BaseModel):
    role: str  # owner | maintainer | contributor | viewer (legacy admin/member 自动映射)
```

b. `backend/app/routes/projects.py:102-105` 处 `AddMemberRequest`：

```python
class AddMemberRequest(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: str = "contributor"  # 默认值改成新名称
```

c. `backend/app/routes/projects.py:450-452` 处 add_member 的 role 校验：

```python
from app.project_access import normalize_project_role

requested = normalize_project_role(req.role)
if requested == "owner":
    raise HTTPException(status_code=400, detail="不能直接邀请为 owner，仅项目创建者拥有该角色")
if requested == "maintainer" and access.role != "owner":
    raise HTTPException(status_code=403, detail="仅项目所有者可添加 maintainer")
role = requested
```

d. `backend/app/routes/projects.py:496-501` 处 remove_member 的检查：

```python
if member.role == "owner":
    raise HTTPException(status_code=400, detail="无法移除项目所有者")
if member.user_id == ctx.user.id:
    raise HTTPException(status_code=400, detail="请勿通过项目设置移除自己")
member_normalized = normalize_project_role(member.role)
if member_normalized == "maintainer" and access.role != "owner":
    raise HTTPException(status_code=403, detail="仅项目所有者可移除 maintainer")
```

e. `backend/app/routes/projects.py:534-538` 处 update_member_role：

```python
new_role = normalize_project_role(req.role)
if new_role == "owner":
    raise HTTPException(status_code=400, detail="不能改成 owner（owner 由项目创建者持有）")
if new_role not in ("maintainer", "contributor", "viewer"):
    raise HTTPException(status_code=400, detail="角色只能是 maintainer / contributor / viewer")
member.role = new_role
```

f. 顶部 import 加上：

```python
from app.project_access import normalize_project_role
```

(如果已 import 跳过)

- [ ] **Step 4: 跑测试**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_projects_routes_phase_a.py -v
```

Expected: 2 passed (or skipped if dev db lacks data — accept skips).

- [ ] **Step 5: 跑全 backend 测试**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/ -v --tb=short
```

Expected: 之前 36 + Phase A 新增 = 至少 40+ pass。允许 skip（dev db 数据不齐）。

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/projects.py backend/tests/test_projects_routes_phase_a.py
git commit -m "$(cat <<'EOF'
feat(collab/route): projects 接受新 role 名 + 旧名称自动映射

- AddMemberRequest 默认 role='contributor'
- add_member / remove_member / update_member_role 都用 normalize_project_role
- 旧客户端传 'admin' / 'member' 仍能成功（normalize 映射）
- 拒绝邀请为 owner（owner 由项目创建者持有）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 新增 ApplicationMember 邀请 API

**Files:**
- Create: `backend/app/routes/application_members.py`
- Modify: `backend/app/main.py`（注册新 router）
- Create: `backend/tests/test_application_members_api.py`

- [ ] **Step 1: 写 API 测试**

Create `backend/tests/test_application_members_api.py`:

```python
"""Phase A — Application 级外部协作者邀请 API"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.main import app
from app.models import User, Application
from app.models.collaboration import ApplicationMember
from app.models.tenant import UserTenant


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login_token(client: AsyncClient, username: str, password: str = "Test1234!") -> str:
    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.mark.asyncio
async def test_invite_application_member_then_list(client):
    async with AsyncDriver() if False else AsyncSessionLocal() as db:
        users = (await db.execute(select(User).limit(5))).scalars().all()
        if len(users) < 2:
            pytest.skip("need 2+ users")
        owner = users[0]
        target = users[1]
        # 找 owner 创建的 application
        appdb = (await db.execute(
            select(Application).where(Application.created_by == owner.id).limit(1)
        )).scalar_one_or_none()
        if not appdb:
            pytest.skip("no application owned by owner")
        tenant_id = appdb.tenant_id
        ut = (await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == target.id,
                UserTenant.tenant_id == tenant_id,
                UserTenant.status == 1,
            )
        )).scalar_one_or_none()
        if not ut:
            pytest.skip("target not in app tenant")
        # 清残留
        existing = (await db.execute(
            select(ApplicationMember).where(
                ApplicationMember.application_id == appdb.id,
                ApplicationMember.user_id == target.id,
            )
        )).scalar_one_or_none()
        if existing:
            await db.delete(existing)
            await db.commit()

    token = await _login_token(client, owner.username)
    headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tenant_id)}

    # 1. invite
    resp = await client.post(
        f"/api/applications/{appdb.id}/members",
        json={"user_id": target.id, "role": "contributor"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "contributor"
    assert resp.json()["user_id"] == target.id

    # 2. list — should contain both owner (inherited) + the new contributor
    resp = await client.get(f"/api/applications/{appdb.id}/members", headers=headers)
    assert resp.status_code == 200
    members = resp.json()
    user_ids = {m["user_id"] for m in members}
    assert target.id in user_ids
    # 应该标明来源（"inherited" vs "direct"）
    sources = {m["source"] for m in members}
    assert "direct" in sources

    # 3. delete invite
    resp = await client.delete(
        f"/api/applications/{appdb.id}/members/{target.id}",
        headers=headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invite_duplicate_returns_400(client):
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).limit(5))).scalars().all()
        if len(users) < 2:
            pytest.skip()
        owner, target = users[0], users[1]
        appdb = (await db.execute(
            select(Application).where(Application.created_by == owner.id).limit(1)
        )).scalar_one_or_none()
        if not appdb:
            pytest.skip()
        tenant_id = appdb.tenant_id
        ut = (await db.execute(
            select(UserTenant).where(
                UserTenant.user_id == target.id,
                UserTenant.tenant_id == tenant_id,
                UserTenant.status == 1,
            )
        )).scalar_one_or_none()
        if not ut:
            pytest.skip()
        # 预先建一条
        existing = (await db.execute(
            select(ApplicationMember).where(
                ApplicationMember.application_id == appdb.id,
                ApplicationMember.user_id == target.id,
            )
        )).scalar_one_or_none()
        if not existing:
            db.add(ApplicationMember(
                application_id=appdb.id,
                user_id=target.id,
                role="contributor",
                invited_by=owner.id,
            ))
            await db.commit()

    token = await _login_token(client, owner.username)
    resp = await client.post(
        f"/api/applications/{appdb.id}/members",
        json={"user_id": target.id, "role": "viewer"},
        headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": str(tenant_id)},
    )
    assert resp.status_code == 400  # 已是成员

    # cleanup
    async with AsyncSessionLocal() as db:
        m = (await db.execute(
            select(ApplicationMember).where(
                ApplicationMember.application_id == appdb.id,
                ApplicationMember.user_id == target.id,
            )
        )).scalar_one_or_none()
        if m:
            await db.delete(m)
            await db.commit()
```

- [ ] **Step 2: 跑测试，预期 404**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_application_members_api.py -v
```

Expected: 404（route 还没挂）或 ImportError。

- [ ] **Step 3: 写 `application_members.py` route**

Create `backend/app/routes/application_members.py`:

```python
"""Application 级成员管理 — 外部协作者（在 Project member 之外的额外邀请）"""
from __future__ import annotations
from typing import Annotated, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application, Project, ProjectMember, User
from app.models.collaboration import ApplicationMember
from app.models.tenant import UserTenant
from app.project_access import normalize_project_role, project_role_at_least

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/applications", tags=["application-members"])


class InviteAppMemberRequest(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: str = "contributor"


class UpdateAppMemberRoleRequest(BaseModel):
    role: str


async def _resolve_application_or_404(
    db: AsyncSession, application_id: int, tenant_id: int
) -> Application:
    result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.tenant_id == tenant_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    return app


async def _user_role_on_application(
    db: AsyncSession,
    *,
    application: Application,
    user_id: int,
) -> Optional[str]:
    """返回用户对 application 的 effective role（inherited from project + direct）

    优先级：取两者中的最高 role。
    """
    direct_role: Optional[str] = None
    inherited_role: Optional[str] = None

    # 1. direct: ApplicationMember
    am = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application.id,
            ApplicationMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if am:
        direct_role = normalize_project_role(am.role)

    # 2. inherited: ProjectMember (if application has project_id)
    if application.project_id:
        pm = (await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == application.project_id,
                ProjectMember.user_id == user_id,
            )
        )).scalar_one_or_none()
        if pm:
            inherited_role = normalize_project_role(pm.role)

    # 3. application.created_by 是 owner（fallback）
    if application.created_by == user_id:
        return "owner"

    # 取最高
    candidates = [r for r in (direct_role, inherited_role) if r]
    if not candidates:
        return None
    return max(candidates, key=lambda r: {
        "viewer": 1, "contributor": 2, "maintainer": 3, "owner": 4
    }.get(r, 0))


async def _require_application_access(
    db: AsyncSession,
    *,
    application_id: int,
    user_id: int,
    tenant_id: int,
    minimum_role: str = "contributor",
) -> tuple[Application, str]:
    app = await _resolve_application_or_404(db, application_id, tenant_id)
    role = await _user_role_on_application(db, application=app, user_id=user_id)
    if not role:
        raise HTTPException(404, "应用不存在或无权访问")
    if not project_role_at_least(role, minimum_role):
        raise HTTPException(403, "无权访问该应用")
    return app, role


@router.get("/{application_id}/members")
async def list_application_members(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """列出应用的所有成员（包括 project 继承 + application 直接邀请）"""
    app, _role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
    )

    members: dict[int, dict] = {}

    # 1. project 继承
    if app.project_id:
        pm_rows = (await db.execute(
            select(ProjectMember, User)
            .join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == app.project_id)
        )).all()
        for pm, u in pm_rows:
            members[u.id] = {
                "user_id": u.id,
                "username": u.username,
                "role": normalize_project_role(pm.role),
                "source": "inherited",
                "created_at": pm.created_at.isoformat() if pm.created_at else None,
            }

    # 2. application 直接邀请（覆盖 inherited if 有）
    am_rows = (await db.execute(
        select(ApplicationMember, User)
        .join(User, ApplicationMember.user_id == User.id)
        .where(ApplicationMember.application_id == application_id)
    )).all()
    for am, u in am_rows:
        members[u.id] = {
            "user_id": u.id,
            "username": u.username,
            "role": normalize_project_role(am.role),
            "source": "direct",
            "created_at": am.created_at.isoformat() if am.created_at else None,
        }

    # 3. application.created_by 是 owner（fallback）
    if app.created_by not in members:
        owner_user = (await db.execute(
            select(User).where(User.id == app.created_by)
        )).scalar_one_or_none()
        if owner_user:
            members[owner_user.id] = {
                "user_id": owner_user.id,
                "username": owner_user.username,
                "role": "owner",
                "source": "creator",
                "created_at": app.created_at.isoformat() if app.created_at else None,
            }

    return list(members.values())


@router.post("/{application_id}/members")
async def invite_application_member(
    application_id: int,
    req: InviteAppMemberRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """邀请用户加入应用（外部协作者）"""
    app, role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )

    # 找目标用户
    if req.user_id:
        target = (await db.execute(select(User).where(User.id == req.user_id))).scalar_one_or_none()
    elif req.username:
        target = (await db.execute(select(User).where(User.username == req.username))).scalar_one_or_none()
    else:
        raise HTTPException(400, "请提供 username 或 user_id")
    if not target:
        raise HTTPException(404, "用户不存在")
    if not target.is_active:
        raise HTTPException(400, "目标用户已被禁用")

    ut = (await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == target.id,
            UserTenant.tenant_id == ctx.tenant_id,
            UserTenant.status == 1,
        )
    )).scalar_one_or_none()
    if not ut:
        raise HTTPException(400, "目标用户不是当前组织的有效成员")

    requested = normalize_project_role(req.role)
    if requested == "owner":
        raise HTTPException(400, "不能直接邀请为 owner（只有创建者持有）")
    if requested == "maintainer" and role != "owner":
        raise HTTPException(403, "仅应用 owner 可添加 maintainer")

    # 已有 record？
    existing = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application_id,
            ApplicationMember.user_id == target.id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "该用户已是应用成员")

    member = ApplicationMember(
        application_id=application_id,
        user_id=target.id,
        role=requested,
        invited_by=ctx.user.id,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    return {
        "id": member.id,
        "user_id": member.user_id,
        "username": target.username,
        "role": member.role,
        "source": "direct",
        "created_at": member.created_at.isoformat() if member.created_at else None,
    }


@router.patch("/{application_id}/members/{user_id}")
async def update_application_member_role(
    application_id: int,
    user_id: int,
    req: UpdateAppMemberRoleRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """改 application 直接成员的 role（不影响 inherited）"""
    _app, role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="owner",
    )
    am = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application_id,
            ApplicationMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not am:
        raise HTTPException(404, "应用直接成员不存在（如是 inherited 请到 Project 修改）")

    new_role = normalize_project_role(req.role)
    if new_role == "owner":
        raise HTTPException(400, "不能改成 owner")
    if new_role not in ("maintainer", "contributor", "viewer"):
        raise HTTPException(400, "角色只能是 maintainer/contributor/viewer")

    am.role = new_role
    await db.commit()
    await db.refresh(am)
    return {"id": am.id, "user_id": am.user_id, "role": am.role}


@router.delete("/{application_id}/members/{user_id}")
async def remove_application_member(
    application_id: int,
    user_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """移除 application 直接成员"""
    _app, role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )
    am = (await db.execute(
        select(ApplicationMember).where(
            ApplicationMember.application_id == application_id,
            ApplicationMember.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not am:
        raise HTTPException(404, "应用直接成员不存在")
    if user_id == ctx.user.id:
        raise HTTPException(400, "请勿通过应用设置移除自己")
    if normalize_project_role(am.role) == "maintainer" and role != "owner":
        raise HTTPException(403, "仅 owner 可移除 maintainer")

    await db.delete(am)
    await db.commit()
    return {"status": "ok"}
```

- [ ] **Step 4: 注册 router 到 `backend/app/main.py`**

Read `backend/app/main.py`，找到其他 `app.include_router(...)` 的位置，加上：

```python
from app.routes import application_members
app.include_router(application_members.router, prefix="/api")
```

注意 prefix 是 `/api`，因为 application_members.router 自身已经有 `prefix="/applications"`。

- [ ] **Step 5: 跑测试**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/test_application_members_api.py -v
```

Expected: 2 passed (or skip 如缺数据)。

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/application_members.py backend/app/main.py backend/tests/test_application_members_api.py
git commit -m "$(cat <<'EOF'
feat(collab/route): ApplicationMember 邀请 API

- GET /api/applications/{id}/members — 列出（合并 inherited + direct + creator）
- POST /api/applications/{id}/members — 邀请（maintainer+ 可邀请，仅 owner 可指派 maintainer）
- PATCH /api/applications/{id}/members/{uid} — 改 role（owner only）
- DELETE /api/applications/{id}/members/{uid}

每条 member 带 source 标识：creator | inherited（来自 Project）| direct（应用级邀请）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Seed 脚本回填遗留数据

**Files:**
- Create: `backend/scripts/seed_default_projects.py`

**用途**：为没有 `project_id` 的 Application 自动创建同名 Project + ProjectMember(owner)。幂等可重跑。

- [ ] **Step 1: 写脚本**

Create `backend/scripts/seed_default_projects.py`:

```python
"""为遗留 Application 自动创建 Project + ProjectMember(owner) 关联。

迁移逻辑（幂等）：
- 找出所有 application_id=NULL or project_id=NULL 的 Application
- 为每个建一个 Project（name=Application.app_name + " (project)"，user_id=created_by）
- 在 ProjectMember 加 owner record（target_user=created_by）
- 把 Application.project_id 指过去

跑法：
    cd backend && source venv/bin/activate
    python scripts/seed_default_projects.py [--dry-run]
"""
from __future__ import annotations
import asyncio
import sys
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Application, Project, ProjectMember, User


async def run(dry_run: bool = False):
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Application).where(Application.project_id.is_(None))
        )
        orphans = result.scalars().all()
        print(f"Found {len(orphans)} orphan applications without project_id")

        created = 0
        for app in orphans:
            print(f"  - app id={app.id} name='{app.app_name}' tenant={app.tenant_id} created_by={app.created_by}")
            if dry_run:
                continue

            project = Project(
                name=f"{app.app_name}",
                description=f"自动创建（来自应用 {app.app_name} 迁移）",
                user_id=app.created_by,
                tenant_id=app.tenant_id,
            )
            db.add(project)
            await db.flush()  # 拿 project.id

            existing_mem = (await db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == app.created_by,
                )
            )).scalar_one_or_none()
            if not existing_mem:
                db.add(ProjectMember(
                    project_id=project.id,
                    user_id=app.created_by,
                    role="owner",
                ))

            await db.execute(
                update(Application)
                .where(Application.id == app.id)
                .values(project_id=project.id)
            )
            created += 1

        if not dry_run:
            await db.commit()
        print(f"{'[DRY-RUN]' if dry_run else '[DONE]'} created {created} projects")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    asyncio.run(run(dry_run=dry))
```

- [ ] **Step 2: 先 dry-run 看影响范围**

Run:
```bash
cd backend && source venv/bin/activate
python scripts/seed_default_projects.py --dry-run
```

Expected: 输出"Found N orphan applications" + 列表，不写 DB。

- [ ] **Step 3: 实际跑**

Run:
```bash
cd backend && source venv/bin/activate
python scripts/seed_default_projects.py
```

Expected: 输出 "[DONE] created N projects"。

验证：
```bash
mysql -u root -pMarscaden123 apaas_builder -e "
SELECT COUNT(*) FROM applications WHERE project_id IS NULL;
SELECT COUNT(*) FROM projects WHERE description LIKE '%自动创建%';
"
```

期望：第一个 = 0；第二个 > 0。

- [ ] **Step 4: 重跑一次确认幂等**

Run:
```bash
python scripts/seed_default_projects.py
```

Expected: "Found 0 orphan applications" + "[DONE] created 0 projects"。

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/seed_default_projects.py
git commit -m "$(cat <<'EOF'
feat(collab/seed): 遗留 Application 自动建 Project + owner ProjectMember

幂等可重跑。dry-run 模式预览影响范围。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 前端 — collaboration types + API client

**Files:**
- Create: `frontend/src/types/collaboration.ts`
- Create: `frontend/src/api/applicationMembers.ts`
- Modify: `frontend/src/api/projects.ts`（如有 role 类型，更新）

- [ ] **Step 1: 写 types**

Create `frontend/src/types/collaboration.ts`:

```typescript
export type ProjectRole = 'owner' | 'maintainer' | 'contributor' | 'viewer'

// 兼容老 UI 中可能仍出现的旧名称
export type LegacyProjectRole = 'admin' | 'member' | ProjectRole

export const ROLE_LEVELS: Record<ProjectRole, number> = {
  viewer: 1,
  contributor: 2,
  maintainer: 3,
  owner: 4,
}

export function normalizeRole(role: string | null | undefined): ProjectRole {
  if (!role) return 'viewer'
  if (role === 'admin') return 'maintainer'
  if (role === 'member') return 'contributor'
  if (role in ROLE_LEVELS) return role as ProjectRole
  return 'viewer'
}

export function roleAtLeast(role: string | null | undefined, required: ProjectRole): boolean {
  return ROLE_LEVELS[normalizeRole(role)] >= ROLE_LEVELS[required]
}

export interface ApplicationMember {
  user_id: number
  username: string
  role: ProjectRole
  source: 'creator' | 'inherited' | 'direct'
  created_at: string | null
}

export interface ProjectMember {
  id: number
  user_id: number
  username: string
  role: ProjectRole
  created_at: string | null
}

export const ROLE_DISPLAY_NAMES: Record<ProjectRole, string> = {
  owner: '所有者',
  maintainer: '管理员',
  contributor: '协作者',
  viewer: '查看者',
}
```

- [ ] **Step 2: 写 API client**

Create `frontend/src/api/applicationMembers.ts`:

```typescript
import http from './http'  // 假设项目用统一的 http 客户端，如不存在请按现有 api/*.ts 模式调整
import type { ApplicationMember, ProjectRole } from '@/types/collaboration'

export interface InviteAppMemberRequest {
  username?: string
  user_id?: number
  role: ProjectRole
}

export const applicationMembersApi = {
  list(applicationId: number): Promise<ApplicationMember[]> {
    return http.get(`/api/applications/${applicationId}/members`).then(r => r.data)
  },
  invite(applicationId: number, req: InviteAppMemberRequest): Promise<ApplicationMember> {
    return http.post(`/api/applications/${applicationId}/members`, req).then(r => r.data)
  },
  updateRole(applicationId: number, userId: number, role: ProjectRole) {
    return http.patch(`/api/applications/${applicationId}/members/${userId}`, { role }).then(r => r.data)
  },
  remove(applicationId: number, userId: number) {
    return http.delete(`/api/applications/${applicationId}/members/${userId}`).then(r => r.data)
  },
}
```

注意：`http` 模块的 import 路径必须和 `frontend/src/api/projects.ts` 保持一致。打开 `frontend/src/api/projects.ts` 看它怎么 import 的，复用同一个：

如果是 `import { request } from '@/utils/request'` 这种模式，对应改写：
```typescript
import { request } from '@/utils/request'
// ... 把 http.get/post/patch/delete 改成对应的 request 调用
```

具体形式取决于项目现有约定（见 Step 3 验证）。

- [ ] **Step 3: 校准 import 路径**

Run:
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai/frontend"
head -20 src/api/projects.ts
```

观察 import 模式（如 `import http from './http'` 或 `import { fetchJson } from '@/lib/api'`），把 `applicationMembers.ts` 的 import 与之对齐。

- [ ] **Step 4: 校验前端编译**

Run:
```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无错误（或仅与 collaboration 无关的 pre-existing 错误）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/collaboration.ts frontend/src/api/applicationMembers.ts
git commit -m "$(cat <<'EOF'
feat(collab/fe): collaboration types + applicationMembers API client

- ProjectRole 4 档枚举 + roleAtLeast / normalizeRole helper（兼容旧名）
- ApplicationMember type 含 source 标识（creator/inherited/direct）
- API client：list / invite / updateRole / remove

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: 可复用 MembersPanel 组件

**Files:**
- Create: `frontend/src/components/MembersPanel.vue`

**用途**：列表 + 邀请表单 + role 改/删的可复用面板。在 Apps 页（per-app 弹窗）和 ProjectOverview 页（project members tab）都能用。

- [ ] **Step 1: 写组件**

Create `frontend/src/components/MembersPanel.vue`:

```vue
<template>
  <div class="members-panel">
    <div class="members-header">
      <h3>{{ title }}</h3>
      <button v-if="canManage" class="builder-btn builder-btn-primary" @click="showInvite = true">
        + 邀请成员
      </button>
    </div>

    <table class="members-table">
      <thead>
        <tr>
          <th>用户名</th>
          <th>角色</th>
          <th>来源</th>
          <th>加入时间</th>
          <th v-if="canManage">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="m in members" :key="m.user_id">
          <td>{{ m.username }}</td>
          <td>
            <select
              v-if="canManage && canEditRole(m)"
              :value="m.role"
              @change="onRoleChange(m, ($event.target as HTMLSelectElement).value)"
            >
              <option v-for="r in editableRoles(m)" :key="r" :value="r">
                {{ ROLE_DISPLAY_NAMES[r] }}
              </option>
            </select>
            <span v-else>{{ ROLE_DISPLAY_NAMES[m.role] || m.role }}</span>
          </td>
          <td>{{ sourceLabel(m) }}</td>
          <td>{{ m.created_at ? new Date(m.created_at).toLocaleString() : '—' }}</td>
          <td v-if="canManage">
            <button
              v-if="canRemove(m)"
              class="builder-btn builder-btn-danger"
              @click="onRemove(m)"
            >
              移除
            </button>
          </td>
        </tr>
        <tr v-if="!members.length">
          <td :colspan="canManage ? 5 : 4" class="empty">暂无成员</td>
        </tr>
      </tbody>
    </table>

    <!-- 邀请弹窗 -->
    <div v-if="showInvite" class="modal-backdrop" @click.self="showInvite = false">
      <div class="modal">
        <h4>邀请成员</h4>
        <label>
          用户名
          <input v-model="inviteUsername" type="text" placeholder="输入用户名" />
        </label>
        <label>
          角色
          <select v-model="inviteRole">
            <option v-for="r in inviteRoleOptions" :key="r" :value="r">
              {{ ROLE_DISPLAY_NAMES[r] }}
            </option>
          </select>
        </label>
        <p v-if="inviteError" class="error">{{ inviteError }}</p>
        <div class="modal-actions">
          <button class="builder-btn" @click="showInvite = false">取消</button>
          <button class="builder-btn builder-btn-primary" :disabled="!inviteUsername" @click="onInvite">
            邀请
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import {
  type ApplicationMember,
  type ProjectMember,
  type ProjectRole,
  ROLE_DISPLAY_NAMES,
  normalizeRole,
  roleAtLeast,
} from '@/types/collaboration'

type AnyMember = (ApplicationMember | ProjectMember) & { source?: string }

const props = defineProps<{
  title: string
  /** 当前用户在该资源上的 effective role */
  currentRole: ProjectRole
  /** 拉成员列表（loadMembers）+ 邀请/改/删 callbacks。让组件不与具体 API 耦合 */
  loadMembers: () => Promise<AnyMember[]>
  invite: (req: { username: string; role: ProjectRole }) => Promise<void>
  updateRole: (userId: number, role: ProjectRole) => Promise<void>
  remove: (userId: number) => Promise<void>
}>()

const members = ref<AnyMember[]>([])
const showInvite = ref(false)
const inviteUsername = ref('')
const inviteRole = ref<ProjectRole>('contributor')
const inviteError = ref('')

const canManage = computed(() => roleAtLeast(props.currentRole, 'maintainer'))

const inviteRoleOptions = computed<ProjectRole[]>(() => {
  // owner 才能邀请 maintainer
  if (props.currentRole === 'owner') return ['maintainer', 'contributor', 'viewer']
  return ['contributor', 'viewer']
})

function sourceLabel(m: AnyMember): string {
  if (!m.source) return '—'
  return { creator: '创建者', inherited: '项目继承', direct: '直接邀请' }[m.source as string] || m.source
}

function canEditRole(m: AnyMember): boolean {
  // creator (owner) 不能改 role；inherited 的成员要在 Project 改
  if (m.role === 'owner') return false
  if (m.source === 'inherited') return false
  return canManage.value
}

function editableRoles(m: AnyMember): ProjectRole[] {
  if (props.currentRole === 'owner') return ['maintainer', 'contributor', 'viewer']
  return ['contributor', 'viewer']
}

function canRemove(m: AnyMember): boolean {
  if (m.role === 'owner') return false
  if (m.source === 'inherited' || m.source === 'creator') return false
  return canManage.value
}

async function refresh() {
  members.value = await props.loadMembers()
}

async function onRoleChange(m: AnyMember, newRole: string) {
  const role = normalizeRole(newRole)
  await props.updateRole(m.user_id, role)
  await refresh()
}

async function onRemove(m: AnyMember) {
  if (!confirm(`确认移除 ${m.username}？`)) return
  await props.remove(m.user_id)
  await refresh()
}

async function onInvite() {
  inviteError.value = ''
  try {
    await props.invite({ username: inviteUsername.value.trim(), role: inviteRole.value })
    showInvite.value = false
    inviteUsername.value = ''
    inviteRole.value = 'contributor'
    await refresh()
  } catch (e: any) {
    inviteError.value = e?.response?.data?.detail || e?.message || '邀请失败'
  }
}

onMounted(refresh)
watch(() => props.title, refresh)
</script>

<style scoped>
.members-panel { padding: 16px; }
.members-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.members-table { width: 100%; border-collapse: collapse; }
.members-table th, .members-table td { padding: 8px 12px; border-bottom: 1px solid var(--b-border, #eee); text-align: left; }
.empty { text-align: center; color: var(--b-muted, #888); padding: 24px; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: var(--b-bg, #fff); padding: 24px; border-radius: 8px; min-width: 320px; }
.modal label { display: block; margin: 12px 0; }
.modal input, .modal select { width: 100%; padding: 6px 8px; margin-top: 4px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.error { color: #c00; font-size: 12px; }
.builder-btn-danger { background: #c00; color: #fff; }
</style>
```

- [ ] **Step 2: 校验前端编译**

Run:
```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无错误。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MembersPanel.vue
git commit -m "$(cat <<'EOF'
feat(collab/fe): MembersPanel 可复用组件

通过 props 注入 loadMembers/invite/updateRole/remove callbacks，
不与具体 API 耦合。同时支撑 Project member 和 Application member 两种场景。

支持：
- 列表 + 来源标识（创建者/继承/直接邀请）
- inline role 修改（select），inherited 成员只读
- maintainer+ 可邀请，仅 owner 可指派 maintainer
- creator/inherited 不可移除（提示去 Project 操作）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Apps 页加成员入口

**Files:**
- Modify: `frontend/src/views/Apps.vue`

**说明**：Apps.vue 当前是 28KB 应用列表页。加一个"成员"按钮 / 弹窗，点开调 MembersPanel + applicationMembersApi。

- [ ] **Step 1: 阅读 Apps.vue 结构找插入点**

Run:
```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai" && grep -n "template\|应用\|app-card\|app.id\|<template" frontend/src/views/Apps.vue | head -40
```

找到应用卡片渲染结构（如 `v-for="app in apps"` 的位置）。

- [ ] **Step 2: 在卡片上加"成员"按钮**

在每个应用卡片操作区（已有"打开"/"删除"等按钮的位置）后追加：

```vue
<button
  class="builder-btn"
  type="button"
  @click="openMembersDialog(app)"
  :title="`管理 ${app.app_name} 的成员`"
>
  成员
</button>
```

- [ ] **Step 3: 加 dialog 的 template + script**

在 `<template>` 末尾（紧挨结束标签前）加：

```vue
<!-- 成员管理弹窗 -->
<div v-if="membersDialogApp" class="modal-backdrop" @click.self="membersDialogApp = null">
  <div class="modal modal-large">
    <div class="modal-header">
      <h3>{{ membersDialogApp.app_name }} — 成员管理</h3>
      <button class="builder-btn" @click="membersDialogApp = null">关闭</button>
    </div>
    <MembersPanel
      :title="`应用 ${membersDialogApp.app_name}`"
      :current-role="membersDialogRole"
      :load-members="loadAppMembers"
      :invite="inviteAppMember"
      :update-role="updateAppMemberRole"
      :remove="removeAppMember"
    />
  </div>
</div>
```

在 `<script setup>` 区加：

```typescript
import MembersPanel from '@/components/MembersPanel.vue'
import { applicationMembersApi } from '@/api/applicationMembers'
import { normalizeRole, type ProjectRole, type ApplicationMember } from '@/types/collaboration'

const membersDialogApp = ref<{ id: number; app_name: string; role?: string } | null>(null)
const membersDialogRole = ref<ProjectRole>('viewer')

async function openMembersDialog(app: any) {
  membersDialogApp.value = { id: app.id, app_name: app.app_name, role: app.role }
  // 拉一次自己的 role —— 可以从 list 里第一项是自己时取
  const list = await applicationMembersApi.list(app.id)
  const me = list.find(m => m.user_id === currentUser.value?.id)
  membersDialogRole.value = normalizeRole(me?.role)
}

async function loadAppMembers(): Promise<ApplicationMember[]> {
  if (!membersDialogApp.value) return []
  return applicationMembersApi.list(membersDialogApp.value.id)
}

async function inviteAppMember(req: { username: string; role: ProjectRole }) {
  if (!membersDialogApp.value) return
  await applicationMembersApi.invite(membersDialogApp.value.id, req)
}

async function updateAppMemberRole(userId: number, role: ProjectRole) {
  if (!membersDialogApp.value) return
  await applicationMembersApi.updateRole(membersDialogApp.value.id, userId, role)
}

async function removeAppMember(userId: number) {
  if (!membersDialogApp.value) return
  await applicationMembersApi.remove(membersDialogApp.value.id, userId)
}
```

注意：
- `currentUser` 应来自 user store（如 `useUserStore().user`）；如该 store 不暴露，从 `.../auth.ts` 等同等位置 import
- 如果 Apps.vue 中已有 modal-backdrop 样式，复用；如缺，加上面 MembersPanel 用到的 css

- [ ] **Step 4: 校验编译**

Run:
```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无错误。

- [ ] **Step 5: 启 dev server 真机点一遍**

Run:
```bash
cd frontend && npm run dev
```

打开浏览器 `http://localhost:5173/apps`，登录 admin 后：
1. 见列表里每个应用有"成员"按钮 → click → 弹窗打开
2. 列表至少含创建者（source=creator）
3. 点"邀请成员" → 输入用户名 → 选 contributor → 提交 → 看到列表新增一行 source=direct
4. 修改新成员 role 为 viewer → 列表更新
5. 点移除 → 确认 → 列表去掉该行

如有 bug，回到 Step 2/3 修。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/Apps.vue
git commit -m "$(cat <<'EOF'
feat(collab/fe): Apps 页应用卡片加成员入口

每个应用卡片新增 "成员" 按钮，点开调 MembersPanel 组件
管理 ApplicationMember（直接邀请的外部协作者）。

合并显示 inherited（来自 Project）+ direct（应用级邀请）+ creator
三类成员，按 source 标识区分。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: 全 Phase A 回归 + 总验收

**Files**：无新文件，仅运行回归测试。

- [ ] **Step 1: 后端单元测试全过**

Run:
```bash
cd backend && source venv/bin/activate
pytest tests/ -v --tb=short
```

Expected: 至少 36 + Phase A 新增 (~12) ≈ 48+ 个 test pass。允许少量 skip（dev db 数据缺）。

- [ ] **Step 2: 前端编译**

Run:
```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 无错误。

- [ ] **Step 3: 验证 schema 完整**

Run:
```bash
mysql -u root -pMarscaden123 apaas_builder -e "
SHOW TABLES LIKE 'application_members';
SHOW TABLES LIKE 'change_proposals';
SHOW TABLES LIKE 'proposal_reviews';
SHOW TABLES LIKE 'git_connections';
SHOW TABLES LIKE 'platform_drift_logs';
DESCRIBE specs;
SELECT COUNT(*) AS orphan_apps FROM applications WHERE project_id IS NULL;
SELECT DISTINCT role FROM project_members;
"
```

Expected:
- 5 张新表都存在
- specs 含 kind, commit_sha
- orphan_apps = 0
- project_members.role 仅含 owner / maintainer / contributor / viewer（无 admin/member 残留）

- [ ] **Step 4: 真机端到端冒烟（最低限度）**

启动 backend 和 frontend，用 admin 账号：
1. 进 Apps 页，点任一应用"成员" → 弹窗显示自己（source=creator, role=owner）
2. 邀请另一个同 tenant 用户为 contributor → 列表新增成功
3. 切换到另一用户登录，进 Apps 页 → 看到该应用（应可访问）+ 自己 role 是 contributor
4. 切回 owner，移除该成员 → 列表回到只剩自己

- [ ] **Step 5: 写 Phase A 总结提交**

```bash
git log --oneline main..HEAD | head -20
```

确认 Phase A 12 个 commit 都在分支上。

- [ ] **Step 6: 写 handoff 给下一 Phase**

Create `docs/superpowers/HANDOFF-collab-phase-a-done.md`:

```markdown
# Phase A 完成交接 — 协作 SPEC + Git 集成

**Date**: <填实际完成日期>
**Branch**: `claude/coding-shell-alignment` (HEAD <git rev-parse HEAD>)
**Tests**: backend pytest 通过 X / Y；frontend vue-tsc 干净

## 落地内容

- 数据库 5 张新表（empty schema for Phase B/C/D）
- Spec 模型加 kind/commit_sha + 乐观锁
- Project role 4 档（owner/maintainer/contributor/viewer），向后兼容旧名
- ApplicationMember 邀请 API + Apps 页成员管理 UI

## Phase B 开始指引

读 [`docs/superpowers/specs/2026-04-25-collab-spec-git-integration-design.md`](specs/2026-04-25-collab-spec-git-integration-design.md) §10 Phase B 范围，
按相同流程产出 `docs/superpowers/plans/2026-04-25-collab-phase-b-proposal-flow.md` 后开始执行。

## 已知 backlog（不阻塞 Phase B）

- ProjectOverview 页的"成员" tab 还没用 MembersPanel（v1 走老 UI），Phase B 时可顺手切换
- ApplicationMember 邀请提示词等 i18n 文案待完善
```

- [ ] **Step 7: 最后一个 commit**

```bash
git add docs/superpowers/HANDOFF-collab-phase-a-done.md
git commit -m "$(cat <<'EOF'
docs(handoff): 协作 Phase A 完成交接

数据模型 + Project 协作能力全部落地。下一步 Phase B 开始
ChangeProposal 完整提案制流程。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## 自检（Plan Self-Review）

**Spec 覆盖核对**（vs `2026-04-25-collab-spec-git-integration-design.md` §10 Phase A 范围）：

| Spec 条目 | Plan Task |
|----------|-----------|
| 改 Project / ProjectMember 统一 role | Task 1（DB）+ Task 5（access）+ Task 6（routes） |
| 新建 ApplicationMember/ChangeProposal/ProposalReview/GitConnection/PlatformDriftLog 空表 | Task 1（DDL）+ Task 2（ORM） |
| 改 Spec.kind 列 + draft fork 逻辑 | Task 1（DDL）+ Task 3（ORM）；fork 逻辑留给 Phase B（Task 3 只加列） |
| API：/api/projects/* member 管理 | Task 6（已有 + role 名升级） |
| 前端 Apps 页加 "成员" tab | Task 9-11 |
| 迁移脚本 | Task 1（SQL）+ Task 8（seed） |
| Phase 0 合并：Spec.tenant_id default=1 修复 | Task 3（已含） |
| Phase 0 合并：Spec.version 乐观锁 | Task 4（已含） |

无遗漏。`/api/applications/{id}/members` 是 Phase A 必须的（spec §7.1），已在 Task 7。

**Placeholder 扫描**：无 TBD/TODO；每个 step 都有具体代码或命令。

**Type/方法名一致性**：
- `ProjectRole` 在 backend `PROJECT_ROLE_LEVELS` 和 frontend `ROLE_LEVELS` 名字略不同但语义一致，文档解释了 alias 行为。
- `ApplicationMember.source` 字段三种值：`'creator' | 'inherited' | 'direct'` 在 backend (Task 7) 和 frontend (Task 9, 10) 一致。
- `OptimisticLockError` 名字 Task 4 写测试和实现使用一致。

**Scope check**：12 个 task 紧扣 Phase A，未越界到 Phase B 提案制。

---

## 执行选择

Plan complete and saved to `docs/superpowers/plans/2026-04-25-collab-phase-a-data-model.md`. Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
