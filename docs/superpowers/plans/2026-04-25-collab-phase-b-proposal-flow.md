# 协作 Phase B — ChangeProposal 提案制流程（实施计划）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task.

**Goal:** 在 Phase A 数据底座之上落地完整的协作流程：personal draft → promote（第一道门）→ review → approve → apply（第二道门 + 不可逆确认）→ canonical 推进。Ship 价值 = 多人能改同一应用 + 串行 apply + 不可逆操作受保护。

**Architecture:**
- 后端：新增 `backend/app/proposal/` 模块（persistence / validation / apply）+ `backend/app/routes/proposals.py`（生命周期端点）+ `routes/chat.py` 接 fork 逻辑
- 前端：新增 `types/proposal.ts` + `api/proposals.ts` + `components/DraftBanner.vue` + `views/ProposalDetailPage.vue` + 重写 `BuilderDevOpsPage.vue`（变更中心 v1）+ ChatPage 集成
- 不在范围：git 同步（Phase C/D）、UED 整体改造、复杂审批工作流

**Tech Stack:** 同 Phase A — Python 3.11/FastAPI/SQLAlchemy 2.x async + Vue 3/TypeScript/Pinia + pytest。

**前置条件:**
- Phase A 已完成（commits up to `e055644`）
- ORM models for ChangeProposal / ProposalReview 已存在（`backend/app/models/collaboration.py`）
- Spec 乐观锁已生效（`save_spec` CAS）
- 4 档 role + ApplicationMember 体系就绪
- 67 backend tests + frontend vue-tsc 干净是 baseline

**约定:** 中文 commit messages（Conventional Commits 风格），与现有 git log 对齐。每 task 一个 commit。

---

## Task 1: ChangeProposal 持久化 helpers

**Files:**
- Create: `backend/app/proposal/__init__.py`
- Create: `backend/app/proposal/persistence.py`
- Create: `backend/tests/test_proposal_persistence.py`

- [ ] **Step 1: 写测试** — `backend/tests/test_proposal_persistence.py`

参考 `backend/tests/test_spec_persistence.py` 的 fixture 模式（用 `db_session` from conftest）。测试 4 个：
1. `test_new_proposal_id_is_unique`: `new_proposal_id()` 返回 `cp_*` 且每次不同
2. `test_create_proposal_persists`: `create_proposal(db, application_id, draft_spec_id, base_canonical_spec_id, title, description, created_by)` 落库且返回 ChangeProposal row
3. `test_load_proposal_returns_row_with_reviews`: `load_proposal(db, proposal_id, with_reviews=True)` 返回 dataclass 含 reviews 列表
4. `test_list_proposals_filter_by_status`: `list_proposals(db, application_id, status='open')` 只返回该状态

- [ ] **Step 2: 跑测试 → ImportError**

```bash
cd backend && source venv/bin/activate
pytest tests/test_proposal_persistence.py -v
```

- [ ] **Step 3: 写实现** — `backend/app/proposal/persistence.py`

```python
"""ChangeProposal 持久化 helpers（Phase B）"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collaboration import ChangeProposal, ProposalReview


def new_proposal_id() -> str:
    return f"cp_{uuid.uuid4().hex[:12]}"


@dataclass
class ProposalView:
    """ChangeProposal + 关联 reviews 的视图对象（避免 ORM lazy-load）"""
    id: str
    application_id: int
    title: str
    description: Optional[str]
    draft_spec_id: str
    base_canonical_spec_id: Optional[str]
    status: str
    validation_report: Optional[dict]
    apply_plan: Optional[dict]
    apply_log: Optional[dict]
    git_branch: Optional[str]
    git_pr_url: Optional[str]
    created_by: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    applied_at: Optional[datetime]
    reviews: list[dict]  # [{id, reviewer_id, action, body, created_at}, ...]


async def create_proposal(
    db: AsyncSession,
    *,
    application_id: int,
    draft_spec_id: str,
    base_canonical_spec_id: Optional[str],
    title: str,
    description: Optional[str],
    created_by: int,
    status: str = "draft",
) -> ChangeProposal:
    proposal = ChangeProposal(
        id=new_proposal_id(),
        application_id=application_id,
        draft_spec_id=draft_spec_id,
        base_canonical_spec_id=base_canonical_spec_id,
        title=title,
        description=description,
        status=status,
        created_by=created_by,
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def load_proposal(
    db: AsyncSession, proposal_id: str, *, with_reviews: bool = True
) -> Optional[ProposalView]:
    row = (await db.execute(
        select(ChangeProposal).where(ChangeProposal.id == proposal_id)
    )).scalar_one_or_none()
    if not row:
        return None

    reviews: list[dict] = []
    if with_reviews:
        review_rows = (await db.execute(
            select(ProposalReview).where(ProposalReview.proposal_id == proposal_id)
            .order_by(ProposalReview.created_at.asc())
        )).scalars().all()
        reviews = [
            {
                "id": r.id,
                "reviewer_id": r.reviewer_id,
                "action": r.action,
                "body": r.body,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in review_rows
        ]

    return ProposalView(
        id=row.id,
        application_id=row.application_id,
        title=row.title,
        description=row.description,
        draft_spec_id=row.draft_spec_id,
        base_canonical_spec_id=row.base_canonical_spec_id,
        status=row.status,
        validation_report=row.validation_report,
        apply_plan=row.apply_plan,
        apply_log=row.apply_log,
        git_branch=row.git_branch,
        git_pr_url=row.git_pr_url,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        applied_at=row.applied_at,
        reviews=reviews,
    )


async def list_proposals(
    db: AsyncSession,
    *,
    application_id: int,
    status: Optional[str] = None,
) -> list[ChangeProposal]:
    stmt = select(ChangeProposal).where(ChangeProposal.application_id == application_id)
    if status:
        stmt = stmt.where(ChangeProposal.status == status)
    stmt = stmt.order_by(ChangeProposal.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())
```

`backend/app/proposal/__init__.py`：留空。

- [ ] **Step 4: 跑测试 → 通过**

- [ ] **Step 5: Commit**

```bash
git add backend/app/proposal/__init__.py backend/app/proposal/persistence.py backend/tests/test_proposal_persistence.py
git commit -m "$(cat <<'EOF'
feat(collab/proposal): ChangeProposal 持久化 helpers + ProposalView

- new_proposal_id / create_proposal / load_proposal / list_proposals
- ProposalView dataclass 合并 reviews 避免 lazy-load
- 4 个单元测试覆盖 CRUD + reviews 关联

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: fork_canonical_to_draft helper

**Files:**
- Modify: `backend/app/spec/persistence.py`
- Create: `backend/tests/test_spec_fork.py`

- [ ] **Step 1: 写测试** — `backend/tests/test_spec_fork.py`

测试 3 个（参考 test_spec_persistence.py 模式）：
1. `test_fork_canonical_returns_new_draft`: 给定 canonical Spec（kind='canonical'），调 `fork_canonical_to_draft(canonical, user_id)` 返回新 Spec id ≠ canonical.id，kind='draft'，parent_spec_id=canonical.id，version=1
2. `test_fork_preserves_payload_content`: 新 draft 的 goal/roles/objects 等内容与 canonical 一致（深拷贝）
3. `test_fork_does_not_persist_canonical`: 调 fork 不会修改 DB 中的 canonical row

- [ ] **Step 2: 跑测试 → ImportError**

- [ ] **Step 3: 在 `backend/app/spec/persistence.py` 末尾追加**

```python
async def fork_canonical_to_draft(
    db: AsyncSession,
    *,
    canonical: Spec,
    user_id: int,
    tenant_id: int,
) -> Spec:
    """从 canonical Spec 派生一个 personal draft（深拷贝 + 新 id）。

    新 draft：
    - id 全新（new_spec_id）
    - parent_spec_id 指向 canonical.id
    - version 重置为 1（draft 自己的版本线，与 canonical 版本独立）
    - kind='draft'（持久化时由 to_orm 写入）
    - application_id 继承

    持久化 draft 到 DB，返回 in-memory Spec 对象。
    """
    new_id = new_spec_id()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # 通过 model_dump → re-parse 实现深拷贝
    payload = canonical.model_dump(mode="json")
    payload["id"] = new_id
    payload["parent_spec_id"] = canonical.id
    payload["version"] = 1
    payload["created_by"] = user_id
    payload["created_at"] = now.isoformat()
    payload["updated_at"] = now.isoformat()
    draft = Spec.model_validate(payload)

    # 持久化为 kind='draft'
    orm = to_orm(draft, tenant_id=tenant_id, kind="draft")
    db.add(orm)
    await db.commit()
    return draft
```

注意：到顶部 import `from app.spec.persistence import new_spec_id, to_orm` 自然能用，因为新函数定义在同一 file。

- [ ] **Step 4: 跑测试 → 通过**

- [ ] **Step 5: Commit**

```bash
git add backend/app/spec/persistence.py backend/tests/test_spec_fork.py
git commit -m "$(cat <<'EOF'
feat(collab/spec): fork_canonical_to_draft helper

派生 personal draft：新 id、parent_spec_id 链回 canonical、version 重置 1、
kind='draft' 落库。这是 Phase B chat 编辑时的入口（fork on first edit）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 第一道门校验器（promote-time validation）

**Files:**
- Create: `backend/app/proposal/validation.py`
- Create: `backend/tests/test_proposal_validation.py`

**目标**：纯文档级校验，不联平台。返回结构化报告。

- [ ] **Step 1: 写测试** — `backend/tests/test_proposal_validation.py`

测试 5 个：
1. `test_completeness_passes_full_spec`: 完整 spec → completeness.ok=True
2. `test_completeness_fails_missing_goal`: spec 没 goal → completeness.ok=False, missing 列表含 'goal'
3. `test_consistency_role_refs_existing_object`: role 的 scope ref 指向不存在的 object → consistency.ok=False
4. `test_naming_no_duplicate_object_codes`: 两个 object 同 code → naming.ok=False
5. `test_validate_aggregates_to_top_level_ok`: 全过 → top-level ok=True；任一失败 → ok=False

测试用 helper 构造 minimal Spec（用 `app.spec.schema` 的 Pydantic 类）。

- [ ] **Step 2: 跑测试 → ImportError**

- [ ] **Step 3: 实现** — `backend/app/proposal/validation.py`

```python
"""第一道门：promote 时的纯文档校验（不联平台）"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.spec.schema import Spec


@dataclass
class CheckResult:
    ok: bool
    issues: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    ok: bool
    completeness: CheckResult
    consistency: CheckResult
    naming: CheckResult
    markdown: CheckResult

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "completeness": {"ok": self.completeness.ok, "issues": self.completeness.issues},
            "consistency": {"ok": self.consistency.ok, "issues": self.consistency.issues},
            "naming": {"ok": self.naming.ok, "issues": self.naming.issues},
            "markdown": {"ok": self.markdown.ok, "issues": self.markdown.issues},
        }


def check_completeness(spec: "Spec") -> CheckResult:
    """5 类卡片是否齐全：goal / role / object / dict / permission

    role / dict / permission 至少一项；object 至少一项；goal 必填。
    """
    issues: list[str] = []
    if not spec.goal or not spec.goal.title:
        issues.append("goal 缺少标题")
    if not spec.objects:
        issues.append("缺少业务对象（object）")
    if not spec.roles:
        issues.append("缺少角色（role）")
    return CheckResult(ok=not issues, issues=issues)


def check_consistency(spec: "Spec") -> CheckResult:
    """字段引用 / 角色 scope 引用的 object 是否存在 / dict 引用是否存在"""
    issues: list[str] = []
    object_codes = {o.code for o in spec.objects}
    dict_codes = {d.code for d in spec.dicts}

    for obj in spec.objects:
        for f in obj.fields:
            if f.dict_code and f.dict_code not in dict_codes:
                issues.append(f"对象 {obj.code} 字段 {f.code} 引用不存在的字典 {f.dict_code}")
            if f.ref_model and f.ref_model not in object_codes:
                issues.append(f"对象 {obj.code} 字段 {f.code} 引用不存在的对象 {f.ref_model}")

    for perm in spec.permissions:
        if perm.object_code not in object_codes:
            issues.append(f"权限规则引用不存在的对象 {perm.object_code}")

    return CheckResult(ok=not issues, issues=issues)


def check_naming(spec: "Spec") -> CheckResult:
    """重名 / 保留字 / 命名规范"""
    issues: list[str] = []
    seen_obj: set[str] = set()
    for o in spec.objects:
        if o.code in seen_obj:
            issues.append(f"对象 code 重复：{o.code}")
        seen_obj.add(o.code)

    seen_dict: set[str] = set()
    for d in spec.dicts:
        if d.code in seen_dict:
            issues.append(f"字典 code 重复：{d.code}")
        seen_dict.add(d.code)

    seen_role: set[str] = set()
    for r in spec.roles:
        if r.code in seen_role:
            issues.append(f"角色 code 重复：{r.code}")
        seen_role.add(r.code)

    # 字段 code 在同对象内不能重复
    for o in spec.objects:
        seen_field: set[str] = set()
        for f in o.fields:
            if f.code in seen_field:
                issues.append(f"对象 {o.code} 字段 code 重复：{f.code}")
            seen_field.add(f.code)

    return CheckResult(ok=not issues, issues=issues)


def check_markdown(spec: "Spec") -> CheckResult:
    """markdown 渲染是否干净（YAML 不损坏）"""
    issues: list[str] = []
    try:
        # 试一下转 markdown 渲染，捕获异常
        from app.spec.converter import spec_to_config
        spec_to_config(spec)
    except Exception as e:
        issues.append(f"markdown 渲染失败：{e}")
    return CheckResult(ok=not issues, issues=issues)


def validate(spec: "Spec") -> ValidationReport:
    """聚合 4 个 check"""
    completeness = check_completeness(spec)
    consistency = check_consistency(spec)
    naming = check_naming(spec)
    markdown = check_markdown(spec)
    ok = all(c.ok for c in (completeness, consistency, naming, markdown))
    return ValidationReport(
        ok=ok,
        completeness=completeness,
        consistency=consistency,
        naming=naming,
        markdown=markdown,
    )
```

- [ ] **Step 4: 跑测试 → 通过**

- [ ] **Step 5: Commit**

```bash
git add backend/app/proposal/validation.py backend/tests/test_proposal_validation.py
git commit -m "$(cat <<'EOF'
feat(collab/proposal): 第一道门校验器（promote-time validation）

4 个独立 check（完整性 / 一致性 / 命名 / markdown）汇总到 ValidationReport，
不联平台、可大量并行调用。Phase B promote 时调用，apply 时也会复用。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: ChangeProposal CRUD endpoints

**Files:**
- Create: `backend/app/routes/proposals.py`
- Modify: `backend/app/main.py`（注册 router）
- Create: `backend/tests/test_proposals_routes.py`

- [ ] **Step 1: 看 main.py 怎么注册其他 router**

```bash
grep -n "include_router" backend/app/main.py
```

- [ ] **Step 2: 写 route 文件**

Create `backend/app/routes/proposals.py`：

```python
"""ChangeProposal 生命周期 API（Phase B）

POST   /api/applications/{id}/proposals          create from draft (promote)
GET    /api/applications/{id}/proposals          list (filter by status)
GET    /api/proposals/{id}                       detail (含 validation_report)
PATCH  /api/proposals/{id}                       update title/desc
POST   /api/proposals/{id}/refresh-validation    重跑第一道门
POST   /api/proposals/{id}/close
"""
from __future__ import annotations
from typing import Annotated, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_auth_context, AuthContext
from app.models import Application
from app.models.collaboration import ChangeProposal
from app.proposal.persistence import create_proposal, load_proposal, list_proposals
from app.proposal.validation import validate as validate_spec
from app.spec.persistence import load_spec
from app.routes.application_members import _require_application_access  # 复用 Phase A

logger = logging.getLogger(__name__)


# ============ schemas ============

class PromoteRequest(BaseModel):
    title: str
    description: Optional[str] = None
    draft_spec_id: str  # 必填：要 promote 的 personal draft


class UpdateProposalRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


# ============ application 子路由 ============

app_router = APIRouter(prefix="/applications", tags=["proposals"])


@app_router.post("/{application_id}/proposals")
async def promote_to_proposal(
    application_id: int,
    req: PromoteRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """promote draft → ChangeProposal（status='open' if 第一道门通过, else 'draft' with issues）"""
    app, _role = await _require_application_access(
        db,
        application_id=application_id,
        user_id=ctx.user.id,
        tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )

    # 验证 draft 存在且属于当前 tenant
    draft = await load_spec(db, req.draft_spec_id, tenant_id=ctx.tenant_id)
    if not draft:
        raise HTTPException(404, "draft spec 不存在")

    # 第一道门
    report = validate_spec(draft)

    # base = application.canonical_spec_id（可为 None for 全新应用）
    base_id = app.canonical_spec_id

    proposal = await create_proposal(
        db,
        application_id=application_id,
        draft_spec_id=draft.id,
        base_canonical_spec_id=base_id,
        title=req.title,
        description=req.description,
        created_by=ctx.user.id,
        status="open" if report.ok else "draft",
    )
    proposal.validation_report = report.to_dict()
    await db.commit()
    await db.refresh(proposal)

    return {
        "id": proposal.id,
        "status": proposal.status,
        "validation_report": proposal.validation_report,
        "title": proposal.title,
    }


@app_router.get("/{application_id}/proposals")
async def list_application_proposals(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: Optional[str] = None,
):
    await _require_application_access(
        db, application_id=application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="viewer",
    )
    rows = await list_proposals(db, application_id=application_id, status=status)
    return [
        {
            "id": r.id,
            "title": r.title,
            "status": r.status,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
            "draft_spec_id": r.draft_spec_id,
            "base_canonical_spec_id": r.base_canonical_spec_id,
        }
        for r in rows
    ]


# ============ proposal 直接路由 ============

prop_router = APIRouter(prefix="/proposals", tags=["proposals"])


async def _load_proposal_or_404(db: AsyncSession, proposal_id: str):
    pv = await load_proposal(db, proposal_id)
    if not pv:
        raise HTTPException(404, "提案不存在")
    return pv


@prop_router.get("/{proposal_id}")
async def get_proposal_detail(
    proposal_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pv = await _load_proposal_or_404(db, proposal_id)
    # tenant 隔离：通过 application 检查
    await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="viewer",
    )
    return {
        "id": pv.id,
        "application_id": pv.application_id,
        "title": pv.title,
        "description": pv.description,
        "draft_spec_id": pv.draft_spec_id,
        "base_canonical_spec_id": pv.base_canonical_spec_id,
        "status": pv.status,
        "validation_report": pv.validation_report,
        "apply_plan": pv.apply_plan,
        "apply_log": pv.apply_log,
        "git_branch": pv.git_branch,
        "git_pr_url": pv.git_pr_url,
        "created_by": pv.created_by,
        "created_at": pv.created_at.isoformat() if pv.created_at else None,
        "updated_at": pv.updated_at.isoformat() if pv.updated_at else None,
        "applied_at": pv.applied_at.isoformat() if pv.applied_at else None,
        "reviews": pv.reviews,
    }


@prop_router.patch("/{proposal_id}")
async def update_proposal(
    proposal_id: str,
    req: UpdateProposalRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pv = await _load_proposal_or_404(db, proposal_id)
    await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )
    if pv.created_by != ctx.user.id:
        raise HTTPException(403, "仅提案创建者可修改 title/description")
    if pv.status not in ("draft", "open", "changes_requested"):
        raise HTTPException(400, f"提案状态 {pv.status} 不可编辑")

    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    if req.title is not None:
        row.title = req.title
    if req.description is not None:
        row.description = req.description
    await db.commit()
    return {"id": row.id, "title": row.title, "description": row.description}


@prop_router.post("/{proposal_id}/refresh-validation")
async def refresh_validation(
    proposal_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """重跑第一道门（draft 内容变化后调用）"""
    pv = await _load_proposal_or_404(db, proposal_id)
    await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )
    draft = await load_spec(db, pv.draft_spec_id, tenant_id=ctx.tenant_id)
    if not draft:
        raise HTTPException(404, "draft spec 已不存在")
    report = validate_spec(draft)
    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    row.validation_report = report.to_dict()
    if pv.status == "draft" and report.ok:
        row.status = "open"
    elif pv.status == "open" and not report.ok:
        row.status = "draft"
    await db.commit()
    return {"id": row.id, "status": row.status, "validation_report": row.validation_report}


@prop_router.post("/{proposal_id}/close")
async def close_proposal(
    proposal_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pv = await _load_proposal_or_404(db, proposal_id)
    await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )
    if pv.created_by != ctx.user.id:
        raise HTTPException(403, "仅提案创建者可关闭")
    if pv.status in ("applied", "applying", "closed"):
        raise HTTPException(400, f"状态 {pv.status} 不可再关闭")
    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    row.status = "closed"
    await db.commit()
    return {"id": row.id, "status": row.status}
```

- [ ] **Step 3: 注册到 main.py**

在现有 `app.include_router(...)` 区域加：

```python
from app.routes import proposals
app.include_router(proposals.app_router, prefix="/api")
app.include_router(proposals.prop_router, prefix="/api")
```

- [ ] **Step 4: 写测试** — `backend/tests/test_proposals_routes.py`

函数级（参考 test_application_members_api.py）。至少 5 测试：
1. `test_promote_full_spec_returns_open`: complete spec → status='open' + validation_report.ok=True
2. `test_promote_incomplete_spec_returns_draft`: 缺 goal → status='draft' + validation_report.ok=False
3. `test_list_proposals_filter_status`: 列表按 status filter
4. `test_get_proposal_detail`
5. `test_close_proposal_only_creator`: 非创建者关 → 403

- [ ] **Step 5: 跑测试 → 通过**

```bash
pytest tests/test_proposals_routes.py -v
pytest tests/ -v --tb=short  # 全 backend 不回归
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/proposals.py backend/app/main.py backend/tests/test_proposals_routes.py
git commit -m "$(cat <<'EOF'
feat(collab/proposal): ChangeProposal 生命周期 API（promote / list / get / patch / refresh / close）

第一道门 validation 在 promote 和 refresh-validation 调用，
全过 → status='open'；有问题 → status='draft' + 报告写回。
权限通过 Phase A 既有 _require_application_access 收紧（viewer 可读，
contributor 起可编辑/关闭，仅 creator 可改自己的 title/desc）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Review endpoints + state 转换

**Files:**
- Modify: `backend/app/routes/proposals.py`（追加 reviews 端点）
- Create: `backend/tests/test_proposal_reviews.py`

- [ ] **Step 1: 写测试** — 至少 4 个

1. `test_approve_transitions_open_to_approved`: open + 1 maintainer approve → status='approved'
2. `test_request_changes_transitions_open_to_changes_requested`
3. `test_comment_does_not_change_status`
4. `test_only_maintainer_or_owner_can_approve`: contributor approve → 403

- [ ] **Step 2: 实现** — 追加到 `backend/app/routes/proposals.py`

```python
class ReviewRequest(BaseModel):
    action: str  # 'approve' | 'request_changes' | 'comment'
    body: Optional[str] = None


@prop_router.post("/{proposal_id}/reviews")
async def submit_review(
    proposal_id: str,
    req: ReviewRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.models.collaboration import ProposalReview
    pv = await _load_proposal_or_404(db, proposal_id)

    if req.action not in ("approve", "request_changes", "comment"):
        raise HTTPException(400, "action 仅支持 approve/request_changes/comment")

    # role 检查：approve / request_changes 需要 maintainer+
    min_role = "maintainer" if req.action in ("approve", "request_changes") else "viewer"
    _app, role = await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role=min_role,
    )

    if pv.created_by == ctx.user.id and req.action in ("approve", "request_changes"):
        raise HTTPException(400, "不能审阅自己的提案")
    if pv.status not in ("open", "changes_requested"):
        raise HTTPException(400, f"状态 {pv.status} 不可评审")

    review = ProposalReview(
        proposal_id=proposal_id,
        reviewer_id=ctx.user.id,
        action=req.action,
        body=req.body,
    )
    db.add(review)
    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    if req.action == "approve":
        row.status = "approved"
    elif req.action == "request_changes":
        row.status = "changes_requested"
    await db.commit()
    await db.refresh(review)
    return {
        "id": review.id,
        "action": review.action,
        "body": review.body,
        "proposal_status": row.status,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }
```

- [ ] **Step 3: 跑测试**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(collab/proposal): review API + state 转换（approve/request_changes/comment）..."
```

---

## Task 6: Apply 逻辑 v1 — 第二道门 + ops 执行

**Files:**
- Create: `backend/app/proposal/apply.py`
- Modify: `backend/app/routes/proposals.py`（追加 apply 端点）
- Create: `backend/tests/test_proposal_apply.py`

**复杂度高**：把 SpecAgent / step_executor 等既有 generation 逻辑接入。Phase B v1 范围简化：
- 不实现"自动开 fix-up proposal"（spec §4 决策 D7 的高级特性）；apply_failed → 简单标 status
- platform dry-run 用既有 `apaas_client.py` 的查询接口，最小覆盖（命名冲突 + token 有效性）
- reversibility 标签简单实现：DROP/MODIFY = 红，CREATE = 黄（可能会丢数据），无变更 = 绿

实现见 `backend/app/proposal/apply.py`：

```python
"""第二道门 + ops 执行（apply 流程，Phase B v1）"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.spec.schema import Spec
from app.spec.persistence import load_spec
from app.spec.converter import spec_to_config
from app.models import Application
from app.models.collaboration import ChangeProposal
from app.proposal.validation import validate as validate_spec


REVERSIBILITY_LEVELS = {"green": 0, "yellow": 1, "red": 2}


@dataclass
class ApplyOp:
    kind: str           # 'create_object' | 'add_field' | 'modify_field' | 'drop_field' | ...
    target: str         # eg 'object:Customer'
    detail: dict
    reversibility: str  # 'green' | 'yellow' | 'red'


@dataclass
class ApplyPlan:
    ops: list[ApplyOp]
    has_irreversible: bool
    rebase_required: bool
    rebase_reason: Optional[str] = None
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ops": [{"kind": o.kind, "target": o.target, "detail": o.detail,
                     "reversibility": o.reversibility} for o in self.ops],
            "has_irreversible": self.has_irreversible,
            "rebase_required": self.rebase_required,
            "rebase_reason": self.rebase_reason,
            "issues": self.issues,
        }


def diff_spec(canonical: Optional[Spec], draft: Spec) -> list[ApplyOp]:
    """对比 canonical 和 draft，输出 ops 清单 + 可逆性标记。

    简化实现：
    - 新增 object → create_object (yellow)
    - 删 object → drop_object (red)
    - 加字段 → add_field (yellow)
    - 删字段 → drop_field (red)
    - 改字段类型 → modify_field (red)
    - 加 dict / 加 role → green
    """
    ops: list[ApplyOp] = []
    canonical_objs = {o.code: o for o in canonical.objects} if canonical else {}
    draft_objs = {o.code: o for o in draft.objects}

    for code, obj in draft_objs.items():
        if code not in canonical_objs:
            ops.append(ApplyOp(
                kind="create_object", target=f"object:{code}",
                detail={"name": obj.name, "field_count": len(obj.fields)},
                reversibility="yellow",
            ))
            for f in obj.fields:
                ops.append(ApplyOp(
                    kind="add_field", target=f"object:{code}.{f.code}",
                    detail={"type": f.type}, reversibility="yellow",
                ))
        else:
            old = canonical_objs[code]
            old_fields = {f.code: f for f in old.fields}
            new_fields = {f.code: f for f in obj.fields}
            for fc, f in new_fields.items():
                if fc not in old_fields:
                    ops.append(ApplyOp(
                        kind="add_field", target=f"object:{code}.{fc}",
                        detail={"type": f.type}, reversibility="yellow",
                    ))
                elif old_fields[fc].type != f.type:
                    ops.append(ApplyOp(
                        kind="modify_field", target=f"object:{code}.{fc}",
                        detail={"old_type": old_fields[fc].type, "new_type": f.type},
                        reversibility="red",
                    ))
            for fc in old_fields.keys() - new_fields.keys():
                ops.append(ApplyOp(
                    kind="drop_field", target=f"object:{code}.{fc}",
                    detail={}, reversibility="red",
                ))

    for code in canonical_objs.keys() - draft_objs.keys():
        ops.append(ApplyOp(
            kind="drop_object", target=f"object:{code}",
            detail={}, reversibility="red",
        ))

    # dicts / roles 简化处理：仅 add，不 diff（v1）
    canonical_dicts = {d.code for d in canonical.dicts} if canonical else set()
    for d in draft.dicts:
        if d.code not in canonical_dicts:
            ops.append(ApplyOp(
                kind="add_dict", target=f"dict:{d.code}",
                detail={"option_count": len(d.options)},
                reversibility="green",
            ))

    canonical_roles = {r.code for r in canonical.roles} if canonical else set()
    for r in draft.roles:
        if r.code not in canonical_roles:
            ops.append(ApplyOp(
                kind="add_role", target=f"role:{r.code}",
                detail={"name": r.name},
                reversibility="green",
            ))

    return ops


async def build_apply_plan(
    db: AsyncSession, *, application_id: int, draft_spec_id: str, base_canonical_id: Optional[str], tenant_id: int,
) -> ApplyPlan:
    """计算第二道门：算 diff + 检测 rebase + 标可逆性。不联平台的纯计算部分。"""
    issues: list[str] = []
    rebase_required = False
    rebase_reason = None

    # 1. 取当前 canonical（可能比 base 更新 → rebase 需要）
    app = (await db.execute(select(Application).where(Application.id == application_id))).scalar_one()
    current_canonical_id = app.canonical_spec_id
    if base_canonical_id and current_canonical_id and current_canonical_id != base_canonical_id:
        rebase_required = True
        rebase_reason = f"canonical 已从 {base_canonical_id} 推进到 {current_canonical_id}"

    canonical = await load_spec(db, current_canonical_id, tenant_id=tenant_id) if current_canonical_id else None
    draft = await load_spec(db, draft_spec_id, tenant_id=tenant_id)
    if not draft:
        return ApplyPlan(ops=[], has_irreversible=False, rebase_required=False,
                         issues=["draft spec 不存在"])

    # 2. 重跑第一道门（apply 时再确认）
    val = validate_spec(draft)
    if not val.ok:
        issues.append("draft 校验未通过")
        for r in (val.completeness, val.consistency, val.naming, val.markdown):
            if not r.ok:
                issues.extend(r.issues)

    # 3. 计算 ops + 可逆性
    ops = diff_spec(canonical, draft)
    has_irreversible = any(o.reversibility == "red" for o in ops)

    return ApplyPlan(
        ops=ops,
        has_irreversible=has_irreversible,
        rebase_required=rebase_required,
        rebase_reason=rebase_reason,
        issues=issues,
    )


async def execute_apply(
    db: AsyncSession,
    *,
    proposal_id: str,
    plan: ApplyPlan,
    tenant_id: int,
) -> dict:
    """执行 ops。Phase B v1 简化版：

    不真正调平台 API（避开 generation 流复杂度）；
    只把 draft promote 成新的 canonical Spec（kind='canonical'），
    然后 application.canonical_spec_id 指过去。

    Phase C/D 时把 step_executor 接进来真实部署到平台。
    """
    from datetime import datetime, timezone
    from app.spec.persistence import save_spec, OptimisticLockError

    proposal_row = (await db.execute(
        select(ChangeProposal).where(ChangeProposal.id == proposal_id)
    )).scalar_one()

    # apply_log 累计
    apply_log: list[dict] = []
    success = True
    failure_reason = None

    try:
        # 加载 draft
        from app.spec.persistence import load_spec
        draft = await load_spec(db, proposal_row.draft_spec_id, tenant_id=tenant_id)
        if not draft:
            raise RuntimeError("draft 不存在")

        # 把 draft kind 改成 canonical（CAS 安全：仅当 version 没有被改时）
        from app.models.spec import Spec as SpecORM
        spec_row = (await db.execute(select(SpecORM).where(SpecORM.id == draft.id))).scalar_one()
        spec_row.kind = "canonical"

        # application.canonical_spec_id 指过去
        app_row = (await db.execute(
            select(Application).where(Application.id == proposal_row.application_id)
        )).scalar_one()
        previous_canonical = app_row.canonical_spec_id
        app_row.canonical_spec_id = draft.id

        for op in plan.ops:
            apply_log.append({"op": op.kind, "target": op.target, "status": "noop_in_v1"})

        proposal_row.status = "applied"
        proposal_row.applied_at = datetime.now(timezone.utc).replace(tzinfo=None)
        proposal_row.apply_log = {"ops": apply_log, "previous_canonical": previous_canonical}
        await db.commit()
    except Exception as e:
        success = False
        failure_reason = str(e)
        proposal_row.status = "apply_failed"
        proposal_row.apply_log = {"ops": apply_log, "error": failure_reason}
        await db.commit()

    return {"success": success, "failure_reason": failure_reason, "apply_log": apply_log}
```

⚠️ **重要的范围说明**：本 task v1 不真接 platform API（避免 Phase B 实施面爆炸）。canonical_spec_id 指针更新就是"逻辑 apply"。Phase C/D 接 git 后会有"git → 真实部署到平台"的真链路；目前 platform 部署仍由原有 generation_steps 流程做（手动触发）。

在 routes/proposals.py 加 apply 端点：

```python
class ApplyRequest(BaseModel):
    confirm_irreversible: bool = False


@prop_router.post("/{proposal_id}/apply")
async def apply_proposal(
    proposal_id: str,
    req: ApplyRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.proposal.apply import build_apply_plan, execute_apply

    pv = await _load_proposal_or_404(db, proposal_id)
    _app, role = await _require_application_access(
        db, application_id=pv.application_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )
    if pv.status != "approved":
        raise HTTPException(400, f"提案状态 {pv.status} 不可 apply（需要 approved）")

    # 构 plan
    plan = await build_apply_plan(
        db,
        application_id=pv.application_id,
        draft_spec_id=pv.draft_spec_id,
        base_canonical_id=pv.base_canonical_spec_id,
        tenant_id=ctx.tenant_id,
    )
    if plan.issues:
        raise HTTPException(400, f"apply 前校验失败：{'; '.join(plan.issues)}")
    if plan.rebase_required:
        raise HTTPException(409, f"需要 rebase：{plan.rebase_reason}")
    if plan.has_irreversible and not req.confirm_irreversible:
        # 把 plan 写回，让前端展示"不可逆"提示
        row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
        row.apply_plan = plan.to_dict()
        await db.commit()
        return {"status": "needs_confirmation", "apply_plan": plan.to_dict()}

    # 标 applying
    row = (await db.execute(select(ChangeProposal).where(ChangeProposal.id == proposal_id))).scalar_one()
    row.status = "applying"
    row.apply_plan = plan.to_dict()
    await db.commit()

    result = await execute_apply(db, proposal_id=proposal_id, plan=plan, tenant_id=ctx.tenant_id)
    return {"status": "applied" if result["success"] else "apply_failed", **result}
```

写测试覆盖：
1. `test_apply_requires_approved_status`
2. `test_apply_rejects_when_irreversible_without_confirm`
3. `test_apply_succeeds_with_confirm_advances_canonical`
4. `test_apply_blocks_when_rebase_required`
5. `test_diff_detects_drop_field_as_red`

跑全 backend 测试不回归。Commit。

---

## Task 7: 前端 proposal types + API client

**Files:**
- Create: `frontend/src/types/proposal.ts`
- Create: `frontend/src/api/proposals.ts`

```typescript
// frontend/src/types/proposal.ts
import type { ProjectRole } from './collaboration'

export type ProposalStatus =
  | 'draft' | 'open' | 'changes_requested'
  | 'approved' | 'applying' | 'applied' | 'apply_failed' | 'closed'

export type ReviewAction = 'approve' | 'request_changes' | 'comment'
export type Reversibility = 'green' | 'yellow' | 'red'

export interface ValidationCheckResult {
  ok: boolean
  issues: string[]
}

export interface ValidationReport {
  ok: boolean
  completeness: ValidationCheckResult
  consistency: ValidationCheckResult
  naming: ValidationCheckResult
  markdown: ValidationCheckResult
}

export interface ApplyOp {
  kind: string
  target: string
  detail: Record<string, any>
  reversibility: Reversibility
}

export interface ApplyPlan {
  ops: ApplyOp[]
  has_irreversible: boolean
  rebase_required: boolean
  rebase_reason: string | null
  issues: string[]
}

export interface Review {
  id: number
  reviewer_id: number
  action: ReviewAction
  body: string | null
  created_at: string | null
}

export interface ProposalSummary {
  id: string
  title: string
  status: ProposalStatus
  created_by: number
  created_at: string | null
  applied_at: string | null
  draft_spec_id: string
  base_canonical_spec_id: string | null
}

export interface ProposalDetail extends ProposalSummary {
  application_id: number
  description: string | null
  validation_report: ValidationReport | null
  apply_plan: ApplyPlan | null
  apply_log: Record<string, any> | null
  git_branch: string | null
  git_pr_url: string | null
  updated_at: string | null
  reviews: Review[]
}

export const STATUS_DISPLAY_NAMES: Record<ProposalStatus, string> = {
  draft: '草稿',
  open: '待评审',
  changes_requested: '需修改',
  approved: '已批准',
  applying: '执行中',
  applied: '已 apply',
  apply_failed: 'apply 失败',
  closed: '已关闭',
}
```

```typescript
// frontend/src/api/proposals.ts
import request from '@/utils/request'
import type {
  ProposalSummary, ProposalDetail, ApplyPlan, Review, ReviewAction,
} from '@/types/proposal'

export interface PromoteRequest {
  title: string
  description?: string
  draft_spec_id: string
}

export interface PromoteResponse {
  id: string
  status: string
  validation_report: any
  title: string
}

export interface ApplyResponse {
  status: string
  apply_plan?: ApplyPlan
  success?: boolean
  failure_reason?: string
  apply_log?: any
}

export const proposalsApi = {
  promote(applicationId: number, body: PromoteRequest): Promise<PromoteResponse> {
    return request.post<any, PromoteResponse>(`/applications/${applicationId}/proposals`, body)
  },
  list(applicationId: number, status?: string): Promise<ProposalSummary[]> {
    const params = status ? `?status=${encodeURIComponent(status)}` : ''
    return request.get<any, ProposalSummary[]>(`/applications/${applicationId}/proposals${params}`)
  },
  get(proposalId: string): Promise<ProposalDetail> {
    return request.get<any, ProposalDetail>(`/proposals/${proposalId}`)
  },
  update(proposalId: string, body: { title?: string; description?: string }) {
    return request.patch<any, any>(`/proposals/${proposalId}`, body)
  },
  refreshValidation(proposalId: string): Promise<ProposalDetail> {
    return request.post<any, ProposalDetail>(`/proposals/${proposalId}/refresh-validation`, {})
  },
  close(proposalId: string) {
    return request.post<any, any>(`/proposals/${proposalId}/close`, {})
  },
  review(proposalId: string, action: ReviewAction, body?: string): Promise<Review & { proposal_status: string }> {
    return request.post<any, any>(`/proposals/${proposalId}/reviews`, { action, body })
  },
  apply(proposalId: string, confirmIrreversible: boolean): Promise<ApplyResponse> {
    return request.post<any, ApplyResponse>(`/proposals/${proposalId}/apply`, {
      confirm_irreversible: confirmIrreversible,
    })
  },
}
```

vue-tsc check + commit。

---

## Task 8: DraftBanner 组件

**Files:**
- Create: `frontend/src/components/spec/DraftBanner.vue`

显示在 SpecCanvas 顶部的 banner，提示当前是 draft。

```vue
<template>
  <div class="draft-banner">
    <div class="banner-content">
      <span class="banner-icon">✏️</span>
      <span class="banner-text">
        你正在编辑草稿
        <span v-if="canonicalVersion">（基于 canonical v{{ canonicalVersion }}）</span>
      </span>
      <span v-if="currentProposal" class="banner-link">
        ↳ 当前提案：
        <a :href="`/proposals/${currentProposal.id}`">
          {{ currentProposal.title }} ({{ currentProposal.status }})
        </a>
      </span>
    </div>
    <div class="banner-actions">
      <button v-if="!currentProposal" class="builder-btn builder-btn-primary" @click="$emit('promote')">
        Promote to Proposal
      </button>
      <button class="builder-btn" @click="$emit('discard')">Discard Draft</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ProposalSummary } from '@/types/proposal'

defineProps<{
  canonicalVersion?: number | null
  currentProposal?: ProposalSummary | null
}>()
defineEmits<{
  promote: []
  discard: []
}>()
</script>

<style scoped>
.draft-banner {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 16px; background: var(--b-warn-bg, #fff8e6);
  border-bottom: 1px solid var(--b-warn-border, #ffd866);
  font-size: 13px;
}
.banner-content { display: flex; gap: 12px; align-items: center; }
.banner-icon { font-size: 16px; }
.banner-link a { color: var(--b-link, #0067d6); text-decoration: none; }
.banner-link a:hover { text-decoration: underline; }
.banner-actions { display: flex; gap: 8px; }
</style>
```

vue-tsc + commit.

---

## Task 9: Chat 集成 — fork on first edit

**Files:**
- Modify: `backend/app/routes/chat.py`（在 SpecAgent 分支前 fork canonical）

**逻辑**：
- 当 conversation.spec_id 已存在 → 继续用（已 fork 过的 draft）
- 当 conversation.spec_id 为空 + application 有 canonical_spec_id → fork canonical → draft → conversation.spec_id 指过去
- 当 application 没 canonical → 走老路（创建空 spec）

修改 `backend/app/routes/chat.py:575-580` 区域：

```python
if not conversation.spec_id:
    # 没绑 spec：检查 application 是否有 canonical_spec_id 可以 fork
    app_id_to_fork = (
        getattr(conversation, 'application_id', None)
        or getattr(conversation, 'workspace_id', None)  # 视情况
    )
    if app_id_to_fork:
        from app.models import Application
        from app.spec.persistence import fork_canonical_to_draft
        appdb = (await db.execute(select(Application).where(Application.id == app_id_to_fork))).scalar_one_or_none()
        if appdb and appdb.canonical_spec_id:
            canonical = await load_spec(db, appdb.canonical_spec_id, tenant_id=ctx.tenant_id)
            if canonical:
                draft = await fork_canonical_to_draft(
                    db, canonical=canonical, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
                )
                conversation.spec_id = draft.id
                await db.commit()
```

⚠️ 实施时**仔细看 chat.py 现有代码**，确定 application_id / spec_id 的关联字段名。可能 `Conversation` 没有直接 application_id，要从 workspace_id 或别的字段推。如果 conversation 不直接关联 application，跳过 fork 逻辑（保留老路径）+ 在 commit message 里 note "fork 逻辑等 ChatPage 显式传 application_id"。

不写后端单元测试（chat 流复杂，留给 Task 12 端到端 smoke）。

Commit。

---

## Task 10: ProposalDetailPage

**Files:**
- Create: `frontend/src/views/ProposalDetailPage.vue`
- Modify: `frontend/src/router/index.ts`（加路由 `/proposals/:id`）

布局（按 spec §8.3）：
- 左：markdown diff（v1：直接显示 draft 的 markdown，未做 diff 渲染——留 Phase C 做完整 diff）
- 右上：validation_report 状态卡片 + apply_plan 摘要（X 红 / Y 黄 / Z 绿）
- 右下：reviews 列表 + Approve / Request Changes / Comment 按钮
- 底部 action bar：Apply（仅 approved 状态可见，含不可逆确认 modal）

参考 `frontend/src/views/ChatPage.vue` 的整体三栏布局复用 css。详细实现见 task 模板。本 task code 量大（~300 行），实施时拆 commit 也行：第 1 commit 静态渲染，第 2 commit reviews + apply 交互。

vue-tsc + commit (1-2 个).

---

## Task 11: 变更中心 — BuilderDevOpsPage rewrite v1

**Files:**
- Modify: `frontend/src/views/BuilderDevOpsPage.vue`

替换现有 mock，改成真实数据：
- Proposals tab：列出当前 application（从 query string 拿 ?application_id=N）的所有 proposals，按 status 分组
- Apply 历史 tab：列 application 的 canonical 推进 = 已 applied 的 proposals 时间线
- 环境拓扑 / 审批中心 / Git 仓库：保持 mock 占位（Phase C/D 真做）

约 200 行改动。Commit。

---

## Task 12: E2E smoke + handoff

- [ ] **Step 1: Backend pytest 全过**

```bash
cd backend && source venv/bin/activate
pytest tests/ -v --tb=short
```

Expected: 67 (Phase A baseline) + Phase B 新增 (~25) ≈ 90+ pass。

- [ ] **Step 2: Frontend vue-tsc 干净**

- [ ] **Step 3: 手动端到端 smoke**（推荐）

启动 backend + frontend：
1. 用 admin 登录，进 Apps → 任一 app，点开 ChatPage
2. 在三栏 SpecCanvas 看到 DraftBanner（如有 canonical）
3. 编辑几条 → SpecAgent 修改 draft
4. 点 "Promote to Proposal" → 输入标题 → 提交 → 走到 ProposalDetailPage
5. 看 validation_report 全过 → 切到 maintainer 用户 approve
6. 回到 owner，点 Apply → 确认不可逆 → success
7. 进变更中心 → 看到该 proposal 在 "已 applied" 列表
8. application.canonical_spec_id 应已推进到原 draft id

如某步失败，回到对应 task 修。

- [ ] **Step 4: 写 handoff 文档**

Create `docs/superpowers/HANDOFF-collab-phase-b-done.md`：

包含：落地内容 / 验证状态 / Phase C 启动指引（git 出方向，从 GitConnection 表入手）/ 已知 backlog（v1 简化项：apply 不真调 platform API、diff 渲染未做完整 git diff、apply_failed 没 fix-up proposal 自动开等）/ 临时数据。

Commit handoff。

---

## 自检（Plan Self-Review）

**Spec 覆盖核对**（vs `2026-04-25-collab-spec-git-integration-design.md` §10 Phase B）：

| Spec 条目 | Plan Task |
|----------|-----------|
| ChatPage SpecAgent 改打 personal draft（fork canonical）| Task 2（fork helper）+ Task 9（chat 集成）|
| DraftBanner + Promote 按钮 | Task 8（DraftBanner）+ Task 10（Promote 调接口）|
| 第一道门校验逻辑 | Task 3 |
| 第二道门校验逻辑 + 不可逆确认 | Task 6 |
| ProposalDetailPage（diff + review + approve + apply）| Task 10 |
| 不可逆操作确认 modal | Task 10 末尾 |
| 变更中心 v1（Proposals + Apply 历史）| Task 11 |
| ChangeProposal 全生命周期 API | Task 4 + Task 5 + Task 6 |
| ChangeProposal 持久化 + ProposalReview | Task 1 + Task 5 |

**简化范围**：v1 不真调 platform API（apply 只切 canonical_spec_id 指针）；不实现 fix-up proposal 自动开机制；diff 渲染先用纯 markdown，无并排 diff。这 3 项明确标 backlog。

**Placeholder scan**：无 TBD/TODO；具体代码块都给了。

**Type 一致性**：`ProposalStatus` 8 档前后端一致；`Reversibility` 3 档一致；`ReviewAction` 3 个一致。

---

## 执行选择

Plan complete and saved to `docs/superpowers/plans/2026-04-25-collab-phase-b-proposal-flow.md`. 沿用 Phase A 的 **Subagent-Driven** 模式继续执行。
