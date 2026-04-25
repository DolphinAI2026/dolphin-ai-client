# 协作 Phase D — Git 入方向 + Workspace + Webhook（实施计划）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** 完整双向同步链路：webhook 接收 git push → 同步 repo → Builder 自动创建 ChangeProposal；拦截直连 merge（必经 Builder apply）；漂移检测 + 解决流；workspace ↔ repo 子目录双向同步；OAuth 完整流（替代 Phase C v1 的 PAT 直连）。

**Architecture:**
- 后端：`backend/app/git/webhook.py`（验签 + dispatcher）+ `app/git/inbound.py`（push/MR 事件 → draft / proposal）+ `app/git/drift.py`（漂移检测）+ `app/git/workspace_sync.py`（workspace ↔ repo）+ `app/routes/git_webhook.py` 接收端点 + `app/routes/git_oauth.py` 完整 OAuth 流
- 前端：DriftBanner（漂移提示）+ ProjectGitSetup OAuth 按钮 + CodingPage workspace 同步控件

**前置条件:**
- Phase A+B+C 完成（commits up to `613f24e`），backend 144 tests passing baseline
- `GitConnection` 表已存在；`ChangeProposal.git_*` 字段就绪
- `BUILDER_FERNET_KEY` 配在 `.env`
- Phase C v1 的 PAT 直连模式 OK（OAuth 是补充，不是替代）

**Tech Stack:** httpx + hmac + Fernet + 既有 git provider 抽象。

**约定:** 中文 commit messages（Conventional Commits 风格）。每 task 一个 commit。

---

## ⚠ 启动前 deps 检查

需要 OAuth 完整流必须有：
- GitHub OAuth App（`GITHUB_CLIENT_ID` + `GITHUB_CLIENT_SECRET` + redirect URI = `http://localhost:5173/git/callback/github`）
- GitLab OAuth App（同结构 GITLAB_*）
- Webhook secret per repo（创建 webhook 时 GitHub/GitLab 给生成）

如果**只配 GitHub**：跳过 GitLab OAuth UI 路径，但 webhook 处理代码同时支持双方。

---

## Task 1: Webhook 验签 + dispatcher 骨架

**Files:**
- Create: `backend/app/git/webhook.py`
- Create: `backend/app/routes/git_webhook.py`
- Modify: `backend/app/main.py`（注册 router）
- Create: `backend/scripts/migrate_collab_phase_d.sql`（GitConnection 加 webhook_secret_enc 列）
- Create: `backend/tests/test_webhook_verify.py`

### Migration

`migrate_collab_phase_d.sql`：

```sql
-- 协作 Phase D 迁移：GitConnection 加 webhook_secret_enc + 新增 platform_drift_logs 解决记录字段
-- 幂等：runner 把 errno 1060 视为已应用

ALTER TABLE git_connections
  ADD COLUMN webhook_secret_enc TEXT NULL AFTER access_token_enc;

INSERT IGNORE INTO __builder_migrations (name, applied_at) VALUES ('migrate_collab_phase_d', NOW());
```

跑：`python scripts/run_migrations.py scripts/migrate_collab_phase_d.sql`。

### webhook.py — 验签 + dispatcher

```python
"""Webhook 入口处理：验签 + provider-specific event 解析"""
from __future__ import annotations
import hmac
import hashlib
import json
from dataclasses import dataclass
from typing import Optional

from app.models.collaboration import GitConnection
from app.git.connection import decrypt_token


@dataclass
class WebhookEvent:
    """规整化的 webhook 事件（跨 provider 抽象）"""
    provider: str       # 'github' | 'gitlab'
    event_type: str     # 'push' | 'pr_opened' | 'pr_synchronized' | 'pr_review' | 'pr_merged' | 'unknown'
    repo_full_path: str
    branch: Optional[str] = None         # for push events
    pr_number: Optional[int] = None      # for pr events
    pr_title: Optional[str] = None
    pr_description: Optional[str] = None
    pr_source_branch: Optional[str] = None
    pr_target_branch: Optional[str] = None
    review_action: Optional[str] = None  # 'approve' | 'request_changes' | 'comment'
    review_body: Optional[str] = None
    actor_username: Optional[str] = None
    raw_payload: Optional[dict] = None


def verify_signature_github(payload_bytes: bytes, signature_header: str, secret: str) -> bool:
    """验证 X-Hub-Signature-256 header（GitHub webhook 签名）"""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    given_sig = signature_header[len("sha256="):]
    return hmac.compare_digest(expected_sig, given_sig)


def verify_signature_gitlab(payload_bytes: bytes, token_header: str, secret: str) -> bool:
    """GitLab 用 X-Gitlab-Token header（明文 secret 比对）"""
    if not token_header:
        return False
    return hmac.compare_digest(token_header, secret)


def parse_github_event(headers: dict, payload: dict) -> WebhookEvent:
    event = headers.get("x-github-event") or headers.get("X-GitHub-Event") or ""
    repo = payload.get("repository", {}).get("full_name", "")
    actor = payload.get("sender", {}).get("login")

    if event == "push":
        ref = payload.get("ref", "")  # e.g. 'refs/heads/main'
        branch = ref.split("/")[-1] if "/" in ref else ref
        return WebhookEvent(provider="github", event_type="push", repo_full_path=repo,
                            branch=branch, actor_username=actor, raw_payload=payload)

    if event == "pull_request":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        et = "unknown"
        if action == "opened":
            et = "pr_opened"
        elif action == "synchronize":
            et = "pr_synchronized"
        elif action == "closed" and pr.get("merged"):
            et = "pr_merged"
        return WebhookEvent(
            provider="github", event_type=et, repo_full_path=repo,
            pr_number=pr.get("number"),
            pr_title=pr.get("title"),
            pr_description=pr.get("body"),
            pr_source_branch=pr.get("head", {}).get("ref"),
            pr_target_branch=pr.get("base", {}).get("ref"),
            actor_username=actor, raw_payload=payload,
        )

    if event == "pull_request_review":
        review = payload.get("review", {})
        state = review.get("state", "").lower()
        review_action = "approve" if state == "approved" else "request_changes" if state == "changes_requested" else "comment"
        return WebhookEvent(
            provider="github", event_type="pr_review", repo_full_path=repo,
            pr_number=payload.get("pull_request", {}).get("number"),
            review_action=review_action,
            review_body=review.get("body"),
            actor_username=actor, raw_payload=payload,
        )

    return WebhookEvent(provider="github", event_type="unknown", repo_full_path=repo,
                        actor_username=actor, raw_payload=payload)


def parse_gitlab_event(headers: dict, payload: dict) -> WebhookEvent:
    event_kind = payload.get("object_kind", "") or headers.get("x-gitlab-event", "").lower()
    repo = payload.get("project", {}).get("path_with_namespace", "")
    actor = (payload.get("user") or {}).get("username") or payload.get("user_username")

    if event_kind == "push":
        ref = payload.get("ref", "")
        branch = ref.split("/")[-1] if "/" in ref else ref
        return WebhookEvent(provider="gitlab", event_type="push", repo_full_path=repo,
                            branch=branch, actor_username=actor, raw_payload=payload)

    if event_kind == "merge_request":
        attrs = payload.get("object_attributes", {})
        action = attrs.get("action")
        et = "unknown"
        if action == "open":
            et = "pr_opened"
        elif action == "update":
            et = "pr_synchronized"
        elif action == "merge":
            et = "pr_merged"
        return WebhookEvent(
            provider="gitlab", event_type=et, repo_full_path=repo,
            pr_number=attrs.get("iid"),
            pr_title=attrs.get("title"),
            pr_description=attrs.get("description"),
            pr_source_branch=attrs.get("source_branch"),
            pr_target_branch=attrs.get("target_branch"),
            actor_username=actor, raw_payload=payload,
        )

    if event_kind == "note":  # GitLab review comments come as notes
        attrs = payload.get("object_attributes", {})
        if attrs.get("noteable_type") == "MergeRequest":
            return WebhookEvent(
                provider="gitlab", event_type="pr_review", repo_full_path=repo,
                pr_number=(payload.get("merge_request") or {}).get("iid"),
                review_action="comment",  # GitLab 区分 approval 走另一个 event，简化
                review_body=attrs.get("note"),
                actor_username=actor, raw_payload=payload,
            )

    return WebhookEvent(provider="gitlab", event_type="unknown", repo_full_path=repo,
                        actor_username=actor, raw_payload=payload)


def parse_event(provider: str, headers: dict, payload: dict) -> WebhookEvent:
    if provider == "github":
        return parse_github_event(headers, payload)
    if provider == "gitlab":
        return parse_gitlab_event(headers, payload)
    return WebhookEvent(provider=provider, event_type="unknown", repo_full_path="", raw_payload=payload)
```

### git_webhook.py — 路由

```python
"""Webhook 接收端点：POST /api/webhooks/git/{provider}

入口设计：
- URL path 含 provider（github/gitlab）
- header 带签名 / token，body 是 JSON
- 找匹配的 GitConnection（通过 repo_full_path → host → 找用此 host 的 connection 之一）
- 验签 → 通过 → 异步 dispatch event handler
- 失败：返 401（验签失败）或 404（无匹配 connection）
"""
from __future__ import annotations
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.collaboration import GitConnection
from app.git.connection import decrypt_token
from app.git.webhook import (
    verify_signature_github, verify_signature_gitlab, parse_event,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/git", tags=["git-webhook"])


@router.post("/{provider}")
async def receive_webhook(
    provider: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if provider not in ("github", "gitlab"):
        raise HTTPException(400, f"unsupported provider: {provider}")

    payload_bytes = await request.body()
    try:
        payload = (await request.json())
    except Exception:
        raise HTTPException(400, "invalid JSON payload")

    # 找 repo_full_path → 找 GitConnection
    headers = {k.lower(): v for k, v in request.headers.items()}
    event = parse_event(provider, headers, payload)
    repo = event.repo_full_path
    if not repo:
        raise HTTPException(400, "cannot extract repo from payload")

    # 找 connection：在所有 GitConnection 里找 webhook_secret_enc 配过的且 provider/host 匹配
    # （简化版：repo path 含 group/org 名，跟 GitConnection.group_id_or_org 前缀匹配）
    repo_owner = repo.split("/")[0]
    conn = (await db.execute(
        select(GitConnection).where(
            GitConnection.provider == provider,
            GitConnection.group_id_or_org == repo_owner,
        )
    )).scalar_one_or_none()
    if not conn or not conn.webhook_secret_enc:
        raise HTTPException(404, f"no connection or webhook secret for {repo}")

    secret = decrypt_token(conn.webhook_secret_enc)
    if provider == "github":
        sig = headers.get("x-hub-signature-256", "")
        if not verify_signature_github(payload_bytes, sig, secret):
            raise HTTPException(401, "signature verification failed")
    else:  # gitlab
        token = headers.get("x-gitlab-token", "")
        if not verify_signature_gitlab(payload_bytes, token, secret):
            raise HTTPException(401, "signature verification failed")

    # dispatch（Phase D 后续 task 加 handler）
    from app.git.inbound import dispatch_webhook_event
    try:
        await dispatch_webhook_event(db, conn=conn, event=event)
    except Exception as e:
        logger.exception(f"webhook dispatch failed for {repo}: {e}")
        # 不 raise — 返 200 让 git 平台不重投
    return {"status": "ok", "event_type": event.event_type}
```

注意：`app.git.inbound.dispatch_webhook_event` 会在 Task 2/3 实现，这里 stub call 不能让 import 失败 → 实施时先建一个空的 inbound.py 含 `dispatch_webhook_event` async 函数（pass）。

### Tests for Task 1

`test_webhook_verify.py` 至少 4 测试：
1. `test_github_signature_verify_pass`
2. `test_github_signature_verify_fail_wrong_secret`
3. `test_gitlab_token_compare_pass`
4. `test_parse_github_push_event`

不测路由（涉及多 fixture），只测纯函数（verify + parse）。

### Step 1-N: 应用 migration → 写文件 → 测试 → 注册路由 → commit

Commit message：

```
feat(collab/git): webhook 验签 + dispatcher 骨架

- WebhookEvent 数据类规整跨 provider 事件结构（push/pr_opened/synchronized/merged/review）
- verify_signature_github (HMAC SHA256 X-Hub-Signature-256)
- verify_signature_gitlab (X-Gitlab-Token 比对)
- parse_github_event / parse_gitlab_event 抽出通用字段
- POST /api/webhooks/git/{provider} 路由：找 connection → 验签 → dispatch
- GitConnection 加 webhook_secret_enc 列（migration_collab_phase_d）

dispatch_webhook_event 当前是 stub，Task 2/3 接 handler。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## Task 2: Inbound event handlers — push + PR 同步

**Files:**
- Modify: `backend/app/git/inbound.py`（实现 dispatch_webhook_event + 各 handler）
- Create: `backend/tests/test_webhook_inbound.py`

### inbound.py 实现

```python
"""Webhook 事件 → Builder 状态变更"""
from __future__ import annotations
import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, User
from app.models.collaboration import (
    GitConnection, ChangeProposal, ProposalReview,
)
from app.git.webhook import WebhookEvent
from app.git.connection import make_provider
from app.git.provider.base import GitFile

logger = logging.getLogger(__name__)


async def dispatch_webhook_event(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """根据 event_type 路由到对应 handler"""
    if event.event_type == "push":
        return await handle_push(db, conn=conn, event=event)
    if event.event_type in ("pr_opened", "pr_synchronized"):
        return await handle_pr_open_or_update(db, conn=conn, event=event)
    if event.event_type == "pr_review":
        return await handle_pr_review(db, conn=conn, event=event)
    if event.event_type == "pr_merged":
        # Task 3 处理（拦截）
        from app.git.inbound_intercept import handle_direct_merge
        return await handle_direct_merge(db, conn=conn, event=event)
    logger.info(f"webhook event {event.event_type} ignored (no handler)")


async def _resolve_application(
    db: AsyncSession, *, conn: GitConnection, repo_full_path: str,
) -> Optional[Application]:
    """根据 repo_full_path 找对应 Application"""
    return (await db.execute(
        select(Application).where(
            Application.git_repo_url.like(f"%{repo_full_path}%"),
        )
    )).scalar_one_or_none()


async def handle_push(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """push 事件：

    - main 分支 push：仅记日志（应该来自 Builder 自身的 apply→merge；外部 push 由 drift detection 抓）
    - feature 分支（spec/proposal-*）push：找对应 ChangeProposal，更新 draft_spec_id 指向的 Spec（重新 parse repo 的 spec/canonical.json）

    简化版：v1 只处理 spec/proposal-* 分支的 push（其他分支 noop）。
    """
    if not (event.branch and event.branch.startswith("spec/proposal-")):
        logger.info(f"push to {event.branch} ignored (not a proposal branch)")
        return

    app = await _resolve_application(db, conn=conn, repo_full_path=event.repo_full_path)
    if not app:
        logger.warning(f"no Application bound to {event.repo_full_path}")
        return

    # 找对应 proposal（git_branch 匹配）
    proposal = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.git_branch == event.branch,
        )
    )).scalar_one_or_none()
    if not proposal:
        logger.info(f"push to {event.branch} but no matching proposal; skip")
        return

    # 拉 spec/canonical.json from repo
    provider = make_provider(conn)
    # provider 接口需 expose get_file → 在 base.py + impl 加（Task 1 的 stub 跳过；Task 2 补）
    try:
        # 这里假设 provider.read_file(repo_full_path, path, ref) 已实现（Task 2 同时给 base.py 加方法）
        content = await provider.read_file(
            repo_full_path=event.repo_full_path,
            path="spec/canonical.json",
            ref=event.branch,
        )
        spec_dict = json.loads(content)
    except Exception as e:
        logger.error(f"failed to read spec/canonical.json from {event.branch}: {e}")
        return

    # 用 spec_dict 替换 proposal.draft_spec_id 指向的 Spec.payload
    from app.spec.persistence import load_spec, save_spec
    from app.spec.schema import Spec
    draft = await load_spec(db, proposal.draft_spec_id, tenant_id=app.tenant_id)
    if not draft:
        logger.warning(f"draft spec {proposal.draft_spec_id} not found")
        return

    # spec_dict 是 SPEC 的 model_dump 形式
    new_draft = Spec.model_validate(spec_dict)
    new_draft.id = draft.id          # 保持原 id
    new_draft.version = draft.version  # 让 save_spec 走 CAS
    new_draft.parent_spec_id = draft.parent_spec_id
    new_draft.created_by = draft.created_by
    new_draft.application_id = draft.application_id
    await save_spec(db, new_draft, tenant_id=app.tenant_id)

    # 重跑第一道门 → 更新 proposal.validation_report
    from app.proposal.validation import validate as validate_spec
    report = validate_spec(new_draft)
    proposal.validation_report = report.to_dict()
    if proposal.status == "draft" and report.ok:
        proposal.status = "open"
    elif proposal.status == "open" and not report.ok:
        proposal.status = "draft"
    await db.commit()

    logger.info(f"synced push to proposal {proposal.id} (status={proposal.status})")


async def handle_pr_open_or_update(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """PR 创建/更新：

    - 如来自 Builder 自身的 promote（git_pr_url 已设到某 ChangeProposal）：noop
    - 否则（外部新建 PR）：自动创建 ChangeProposal 关联到现有 application
    """
    app = await _resolve_application(db, conn=conn, repo_full_path=event.repo_full_path)
    if not app:
        logger.warning(f"no Application bound to {event.repo_full_path}")
        return

    # 检查是否已有 proposal 关联此 PR
    pr_url_pattern = f"%{event.repo_full_path}%/{event.pr_number}"  # 粗匹配
    existing = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.git_pr_url.like(pr_url_pattern),
        )
    )).scalar_one_or_none()

    if existing:
        # Builder 已知此 PR；更新 title/description（如有改）
        existing.title = event.pr_title or existing.title
        existing.description = event.pr_description or existing.description
        await db.commit()
        return

    # 外部新建 PR — 创建新 ChangeProposal
    # 找 actor 对应的 builder user（按 username 匹配，简化）
    actor_user = None
    if event.actor_username:
        actor_user = (await db.execute(
            select(User).where(User.username == event.actor_username)
        )).scalar_one_or_none()
    creator_id = actor_user.id if actor_user else app.created_by

    # 拉 source_branch 的 spec/canonical.json 作为 draft 内容
    provider = make_provider(conn)
    try:
        content = await provider.read_file(
            repo_full_path=event.repo_full_path,
            path="spec/canonical.json",
            ref=event.pr_source_branch,
        )
        spec_dict = json.loads(content)
    except Exception as e:
        logger.error(f"cannot read spec from {event.pr_source_branch}: {e}")
        return

    # 创建 draft Spec + proposal
    from app.spec.schema import Spec
    from app.spec.persistence import save_spec, new_spec_id, fork_canonical_to_draft, load_spec
    from datetime import datetime, timezone

    canonical = await load_spec(db, app.canonical_spec_id, tenant_id=app.tenant_id) if app.canonical_spec_id else None
    new_draft = Spec.model_validate(spec_dict)
    new_draft.id = new_spec_id()
    new_draft.parent_spec_id = canonical.id if canonical else None
    new_draft.version = 1
    new_draft.created_by = creator_id
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    new_draft.created_at = now
    new_draft.updated_at = now
    new_draft.application_id = app.id
    await save_spec(db, new_draft, tenant_id=app.tenant_id)

    from app.proposal.persistence import create_proposal
    proposal = await create_proposal(
        db,
        application_id=app.id,
        draft_spec_id=new_draft.id,
        base_canonical_spec_id=app.canonical_spec_id,
        title=event.pr_title or f"External PR #{event.pr_number}",
        description=event.pr_description or "（来自 git 平台外部创建）",
        created_by=creator_id,
        status="open",
    )
    proposal.git_branch = event.pr_source_branch
    proposal.git_pr_url = (event.raw_payload.get("pull_request") or event.raw_payload.get("object_attributes") or {}).get("html_url") or \
                         (event.raw_payload.get("object_attributes") or {}).get("url", "")

    # 第一道门
    from app.proposal.validation import validate as validate_spec
    report = validate_spec(new_draft)
    proposal.validation_report = report.to_dict()
    if not report.ok:
        proposal.status = "draft"
    await db.commit()

    logger.info(f"created proposal {proposal.id} from external PR #{event.pr_number}")


async def handle_pr_review(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    """PR review (comment / approve / request_changes) → 同步到 ProposalReview"""
    app = await _resolve_application(db, conn=conn, repo_full_path=event.repo_full_path)
    if not app:
        return

    pr_url_pattern = f"%/{event.pr_number}"
    proposal = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.git_pr_url.like(pr_url_pattern),
        )
    )).scalar_one_or_none()
    if not proposal:
        return

    actor_user = None
    if event.actor_username:
        actor_user = (await db.execute(
            select(User).where(User.username == event.actor_username)
        )).scalar_one_or_none()

    review = ProposalReview(
        proposal_id=proposal.id,
        reviewer_id=actor_user.id if actor_user else app.created_by,
        action=event.review_action or "comment",
        body=event.review_body,
    )
    db.add(review)

    if event.review_action == "approve":
        proposal.status = "approved"
    elif event.review_action == "request_changes":
        proposal.status = "changes_requested"
    await db.commit()
```

### Provider base.py 加 read_file

修改 `backend/app/git/provider/base.py` 在 GitProvider Protocol 加：

```python
    async def read_file(self, *, repo_full_path: str, path: str, ref: str) -> str:
        """读 repo 中指定 ref（branch/tag/sha）的文件内容"""
        ...
```

GitLab 实现（追加到 gitlab.py）：

```python
    async def read_file(self, *, repo_full_path: str, path: str, ref: str) -> str:
        from urllib.parse import quote
        import base64
        resp = await self._request(
            "GET",
            f"/projects/{quote(repo_full_path, safe='')}/repository/files/{quote(path, safe='')}",
            params={"ref": ref},
        )
        data = resp.json()
        return base64.b64decode(data["content"]).decode()
```

GitHub 实现（追加到 github.py）：

```python
    async def read_file(self, *, repo_full_path: str, path: str, ref: str) -> str:
        import base64
        owner, repo = repo_full_path.split("/", 1)
        resp = await self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
        data = resp.json()
        return base64.b64decode(data["content"]).decode()
```

补对应单元测试到既有 provider 测试文件（each: 1 test for read_file）。

### Tests for Task 2

`test_webhook_inbound.py` 至少 4 测试，全 mock provider：
1. `test_handle_push_to_proposal_branch_syncs_draft`
2. `test_handle_push_to_main_ignored`
3. `test_handle_pr_opened_creates_new_proposal`
4. `test_handle_pr_review_approve_transitions_status`

Commit message：

```
feat(collab/git): webhook 入方向 — push 同步 draft + 自动建 proposal + review 同步

- handle_push (spec/proposal-* 分支)：拉 repo 的 spec/canonical.json
  替换 draft Spec.payload + 重跑第一道门
- handle_pr_open_or_update：来自 Builder promote 的 PR 跳过；外部新建
  PR 自动创建 ChangeProposal 关联到 Application
- handle_pr_review：approve/request_changes/comment 同步到 ProposalReview，
  对应 status 转换

Provider 抽象加 read_file（GitLab + GitHub 各实现）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## Task 3: 直连 merge 拦截

**Files:**
- Create: `backend/app/git/inbound_intercept.py`
- Modify: `backend/app/git/provider/base.py`（加 revert_commit）+ gitlab.py / github.py 实现
- Create: `backend/tests/test_inbound_intercept.py`

### inbound_intercept.py

```python
"""拦截直连 merge — apply 必须经 Builder

策略：
- pr_merged event 触达
- 找对应 ChangeProposal
- 如 ChangeProposal.status != 'applied'（即 Builder 还没 apply）：
  ⇒ 直连绕过了 Builder 第二道门
  ⇒ revert merge commit + comment 提示
"""
from __future__ import annotations
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Application
from app.models.collaboration import GitConnection, ChangeProposal
from app.git.webhook import WebhookEvent
from app.git.connection import make_provider

logger = logging.getLogger(__name__)


async def handle_direct_merge(
    db: AsyncSession, *, conn: GitConnection, event: WebhookEvent,
) -> None:
    app = (await db.execute(
        select(Application).where(Application.git_repo_url.like(f"%{event.repo_full_path}%"))
    )).scalar_one_or_none()
    if not app:
        return

    # 找对应 proposal
    pr_url_pattern = f"%/{event.pr_number}"
    proposal = (await db.execute(
        select(ChangeProposal).where(
            ChangeProposal.application_id == app.id,
            ChangeProposal.git_pr_url.like(pr_url_pattern),
        )
    )).scalar_one_or_none()

    if proposal and proposal.status == "applied":
        # 这是 Builder 自己 apply 触发的 merge —— 正常完成路径
        logger.info(f"merge of PR #{event.pr_number} matches applied proposal {proposal.id}; OK")
        return

    # 直连 merge：拦截
    logger.warning(f"direct merge detected for PR #{event.pr_number} on {event.repo_full_path}; reverting")
    provider = make_provider(conn)
    try:
        merge_commit = (event.raw_payload.get("pull_request") or event.raw_payload.get("object_attributes") or {}).get("merge_commit_sha", "")
        if merge_commit:
            await provider.revert_commit(
                repo_full_path=event.repo_full_path,
                branch=event.pr_target_branch or "main",
                commit_sha=merge_commit,
            )
        await provider.add_pr_comment(
            repo_full_path=event.repo_full_path, pr_number=event.pr_number,
            body="⚠️ 此 MR/PR 被 aPaaS Builder 自动 revert：直连 merge 绕过了 Builder 的不可逆操作确认。请回到 Builder 中通过 ChangeProposal 流程 apply。",
        )
        if proposal:
            from datetime import datetime, timezone
            from app.models.collaboration import PlatformDriftLog
            db.add(PlatformDriftLog(
                application_id=app.id,
                kind="direct_merge_reverted",
                git_sha=merge_commit,
                builder_canonical_sha=app.canonical_spec_id,
            ))
            await db.commit()
    except Exception as e:
        logger.exception(f"revert failed for PR #{event.pr_number}: {e}")
```

### Provider 加 revert_commit

base.py Protocol 加：

```python
    async def revert_commit(self, *, repo_full_path: str, branch: str, commit_sha: str) -> None:
        ...
```

GitLab 实现（追加 gitlab.py）：

```python
    async def revert_commit(self, *, repo_full_path: str, branch: str, commit_sha: str) -> None:
        from urllib.parse import quote
        await self._request(
            "POST",
            f"/projects/{quote(repo_full_path, safe='')}/repository/commits/{commit_sha}/revert",
            json={"branch": branch},
        )
```

GitHub 实现（追加 github.py）：GitHub 没有原生 revert API。simplification：用 `git reset` 风格（POST `/repos/{owner}/{repo}/git/refs/heads/{branch}` PATCH 把 ref 移回 parent commit）。或更简单的 v1：仅 add_pr_comment 通知，不真 revert。

```python
    async def revert_commit(self, *, repo_full_path: str, branch: str, commit_sha: str) -> None:
        # GitHub 没有 revert API；v1 简化：移 branch ref 到 commit_sha 的 parent
        owner, repo = repo_full_path.split("/", 1)
        # 取 commit 的 parents
        commit_resp = await self._request("GET", f"/repos/{owner}/{repo}/commits/{commit_sha}")
        parent_sha = commit_resp.json()["parents"][0]["sha"]
        # 强推 branch ref 到 parent
        await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
            json={"sha": parent_sha, "force": True},
        )
```

⚠ GitHub 强推到 main 需要 branch protection 关掉或有 admin perm。文档化为 "production-ready 需配 webhook 用户为 admin / 或用 PR revert 工作流"。

### Tests for Task 3

`test_inbound_intercept.py` 至少 3 测试：
1. `test_applied_proposal_merge_skips_intercept`
2. `test_unknown_merge_reverts_and_comments`
3. `test_intercept_logs_drift`

Commit message：

```
feat(collab/git): 直连 merge 拦截 — 自动 revert + comment + drift log

apply 必经 Builder 第二道门（不可逆操作确认）。pr_merged event：
- 找对应 proposal；status='applied' 跳过（Builder 自己 merge 的）
- 否则：调 provider.revert_commit + add_pr_comment + 写 PlatformDriftLog
- GitLab 用原生 revert API；GitHub 用强推 ref 到 parent（需 admin perm）

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## Task 4: 漂移检测 + 解决端点

**Files:**
- Create: `backend/app/git/drift.py`
- Modify: `backend/app/proposal/apply.py`（apply 前漂移检测）
- Modify: `backend/app/routes/git_connection.py`（追加 drift status / resolve 端点）
- Create: `backend/tests/test_git_drift.py`

### drift.py

```python
"""漂移检测：git main HEAD vs Builder canonical commit_sha"""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application
from app.models.collaboration import GitConnection, PlatformDriftLog
from app.git.connection import make_provider


async def check_drift(
    db: AsyncSession, *, application: Application,
) -> dict:
    """对比 git main HEAD 和 Builder 的 application.canonical_spec_id 关联的 commit_sha

    返回 {drift: bool, git_sha, builder_sha, reason?}
    """
    if not application.git_repo_url or not application.project_id:
        return {"drift": False, "reason": "no git binding"}

    conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == application.project_id)
    )).scalar_one_or_none()
    if not conn:
        return {"drift": False, "reason": "no git connection"}

    # 取 builder canonical Spec 的 commit_sha
    from app.models.spec import Spec as SpecORM
    canonical_row = (await db.execute(
        select(SpecORM).where(SpecORM.id == application.canonical_spec_id)
    )).scalar_one_or_none() if application.canonical_spec_id else None
    builder_sha = canonical_row.commit_sha if canonical_row else None

    # 取 git main HEAD
    provider = make_provider(conn)
    try:
        repo_full_path = application.git_repo_url.rsplit("/", 2)[-2] + "/" + application.git_repo_url.rsplit("/", 1)[-1]
        # provider 加 get_branch_head 方法
        git_sha = await provider.get_branch_head(
            repo_full_path=repo_full_path, branch=application.git_default_branch or "main",
        )
    except Exception as e:
        return {"drift": False, "reason": f"git read failed: {e}"}

    drift = bool(builder_sha) and git_sha != builder_sha
    if drift:
        db.add(PlatformDriftLog(
            application_id=application.id,
            kind="drift_detected",
            git_sha=git_sha,
            builder_canonical_sha=builder_sha,
        ))
        await db.commit()

    return {
        "drift": drift, "git_sha": git_sha, "builder_sha": builder_sha,
    }


async def resolve_drift(
    db: AsyncSession, *, application: Application, direction: str, resolved_by: int,
) -> dict:
    """direction: 'git_to_builder' | 'builder_to_git'

    git_to_builder: 拉 git main 内容覆盖 Builder canonical（建新 canonical Spec）
    builder_to_git: 强推 Builder canonical Spec 到 git main（高危）
    """
    if direction not in ("git_to_builder", "builder_to_git"):
        raise ValueError("direction 必须是 git_to_builder 或 builder_to_git")

    # v1 简化：仅记录 PlatformDriftLog 解决记录，真实数据迁移留 v2
    # （真做 git_to_builder 需要 fork + replace canonical_spec_id；real builder_to_git 需要强推 git）
    db.add(PlatformDriftLog(
        application_id=application.id,
        kind="drift_resolved",
        resolution_direction=direction,
        resolved_by=resolved_by,
        resolved_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    await db.commit()
    return {"status": "logged", "direction": direction, "note": "v1 仅记录解决意图，实际数据迁移留 v2"}
```

### Provider 加 get_branch_head

base.py / gitlab.py / github.py 各加：

```python
# base.py
async def get_branch_head(self, *, repo_full_path: str, branch: str) -> str:
    ...

# gitlab.py
async def get_branch_head(self, *, repo_full_path: str, branch: str) -> str:
    from urllib.parse import quote
    resp = await self._request(
        "GET",
        f"/projects/{quote(repo_full_path, safe='')}/repository/branches/{quote(branch, safe='')}",
    )
    return resp.json()["commit"]["id"]

# github.py
async def get_branch_head(self, *, repo_full_path: str, branch: str) -> str:
    owner, repo = repo_full_path.split("/", 1)
    resp = await self._request("GET", f"/repos/{owner}/{repo}/branches/{branch}")
    return resp.json()["commit"]["sha"]
```

### apply.py 集成漂移检测

`build_apply_plan` 末尾，在 return 之前加：

```python
    # 漂移检测：apply 前确保 Builder 视图和 git 一致
    from app.git.drift import check_drift
    if app.git_repo_url:
        drift = await check_drift(db, application=app)
        if drift.get("drift"):
            issues.append(f"git 漂移：git={drift['git_sha'][:8]} vs builder={(drift['builder_sha'] or 'none')[:8]}，需先解决")
```

### 端点

`git_connection.py` 末尾追加（在 app_router）：

```python
@app_router.get("/{application_id}/drift-status")
async def drift_status(
    application_id: int,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.git.drift import check_drift
    app = (await db.execute(
        select(Application).where(Application.id == application_id, Application.tenant_id == ctx.tenant_id)
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    return await check_drift(db, application=app)


class ResolveDriftRequest(BaseModel):
    direction: str  # 'git_to_builder' | 'builder_to_git'


@app_router.post("/{application_id}/resolve-drift")
async def resolve_drift_endpoint(
    application_id: int,
    req: ResolveDriftRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.git.drift import resolve_drift
    app = (await db.execute(
        select(Application).where(Application.id == application_id, Application.tenant_id == ctx.tenant_id)
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    if not app.project_id:
        raise HTTPException(400, "应用未关联 project，无法解决漂移")
    await require_project_access(
        db, project_id=app.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="owner",
    )
    return await resolve_drift(db, application=app, direction=req.direction, resolved_by=ctx.user.id)
```

### Tests for Task 4

`test_git_drift.py` 至少 3 测试：mock get_branch_head：
1. `test_check_drift_no_git_binding`
2. `test_check_drift_match_no_drift`
3. `test_check_drift_mismatch_logs_drift`

Commit message：

```
feat(collab/git): 漂移检测 + 解决端点 + apply 前自动检查

- check_drift: 对比 git main HEAD 和 Builder canonical Spec.commit_sha
- 漂移检测到自动写 PlatformDriftLog
- apply 前在 build_apply_plan 调一次（drift 时把 issue 加到 plan.issues）
- POST /api/applications/{id}/resolve-drift (owner only) 记录解决意图
- Provider 加 get_branch_head（GitLab + GitHub）

v1 简化：resolve 仅 log，实际数据迁移留 v2。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## Task 5: Workspace ↔ repo 双向同步（后端）

**Files:**
- Create: `backend/app/git/workspace_sync.py`
- Modify: `backend/app/git/repo_init.py`（init 时建 workspaces/ 目录）
- Modify: `backend/app/routes/git_connection.py`（追加 workspace sync 端点）
- Create: `backend/tests/test_workspace_sync.py`

简化版：v1 只做"workspace 推到 repo workspaces/<name>/" + 反向 pull 留 v2 webhook 自动同步。

### workspace_sync.py

```python
"""Workspace ↔ repo workspaces/<name>/ 子目录同步"""
from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Application
from app.models.collaboration import GitConnection
from app.git.connection import make_provider
from app.git.provider.base import GitFile


async def push_workspace_to_repo(
    db: AsyncSession, *, application: Application, workspace_id: str,
    workspace_root: Path = Path("workspace_data"),
) -> dict:
    """从 workspace_data/<workspace_id>/ 收集所有文件，推到 repo workspaces/<name>/ 子目录"""
    if not application.git_repo_url:
        raise RuntimeError("应用未绑定 git")

    from sqlalchemy import select
    conn = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == application.project_id)
    )).scalar_one_or_none()
    if not conn:
        raise RuntimeError("project 未连接 git")

    ws_dir = workspace_root / workspace_id
    if not ws_dir.exists():
        raise RuntimeError(f"workspace {workspace_id} not found at {ws_dir}")

    # 收集文件（仅文本类，跳过 node_modules / dist 等）
    SKIP = {"node_modules", "dist", ".git", "__pycache__", ".cache"}
    files: list[GitFile] = []
    for root, dirs, fnames in os.walk(ws_dir):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for fn in fnames:
            full = Path(root) / fn
            try:
                content = full.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # 跳过二进制
            rel = full.relative_to(ws_dir)
            files.append(GitFile(
                path=f"workspaces/{workspace_id}/{rel.as_posix()}",
                content=content,
            ))

    if not files:
        return {"status": "noop", "reason": "no text files found"}

    provider = make_provider(conn)
    repo_full_path = application.git_repo_url.rsplit("/", 2)[-2] + "/" + application.git_repo_url.rsplit("/", 1)[-1]
    branch = f"code/workspace-{workspace_id}"
    commit = await provider.commit_files(
        repo_full_path=repo_full_path, branch=branch,
        message=f"workspace {workspace_id} sync from Builder",
        files=files,
    )
    return {"status": "ok", "branch": branch, "commit_sha": commit.sha, "file_count": len(files)}
```

### 端点

`git_connection.py` `app_router` 加：

```python
@app_router.post("/{application_id}/workspaces/{workspace_id}/sync-to-repo")
async def sync_workspace_to_repo(
    application_id: int,
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.git.workspace_sync import push_workspace_to_repo
    app = (await db.execute(
        select(Application).where(Application.id == application_id, Application.tenant_id == ctx.tenant_id)
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "应用不存在")
    await require_project_access(
        db, project_id=app.project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="contributor",
    )
    try:
        result = await push_workspace_to_repo(db, application=app, workspace_id=workspace_id)
        return result
    except Exception as e:
        raise HTTPException(400, str(e))
```

### Tests

`test_workspace_sync.py` 2 测试，mock provider + tmp_path 写假 workspace 文件：
1. `test_push_workspace_collects_files_and_commits`
2. `test_push_workspace_skips_node_modules`

Commit message：

```
feat(collab/git): workspace → repo 子目录同步（v1 单向 push）

push_workspace_to_repo：
- 从 workspace_data/<workspace_id>/ 收集所有 utf-8 文本（跳过
  node_modules/dist/__pycache__）
- commit 到 repo code/workspace-<workspace_id> 分支的 workspaces/<workspace_id>/ 路径
- 端点 POST /api/applications/{id}/workspaces/{ws_id}/sync-to-repo

反向（repo push → workspace）留 v2，靠 webhook 触发。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## Task 6: 前端 — DriftBanner + ProposalDetailPage + CodingPage 同步按钮

**Files:**
- Create: `frontend/src/components/DriftBanner.vue`
- Modify: `frontend/src/views/ProposalDetailPage.vue`（顶部加 DriftBanner）
- Modify: `frontend/src/views/CodingPage.vue`（workspace 操作区加 "Sync to repo" 按钮）
- Modify: `frontend/src/api/gitConnection.ts`（加 driftStatus / resolveDrift / syncWorkspace methods）

### gitConnection.ts 追加

```typescript
export interface DriftStatus {
  drift: boolean
  git_sha?: string
  builder_sha?: string
  reason?: string
}

driftStatus(applicationId: number): Promise<DriftStatus> {
  return request.get<any, DriftStatus>(`/applications/${applicationId}/drift-status`)
},
resolveDrift(applicationId: number, direction: 'git_to_builder' | 'builder_to_git') {
  return request.post<any, any>(`/applications/${applicationId}/resolve-drift`, { direction })
},
syncWorkspace(applicationId: number, workspaceId: string) {
  return request.post<any, any>(`/applications/${applicationId}/workspaces/${workspaceId}/sync-to-repo`, {})
},
```

### DriftBanner.vue

类似 DraftBanner，但是 warning 风格：显示 "Git main 比 Builder 状态新（git=abc1234 vs builder=def5678）" + "解决" 按钮（跳到 /project/:id/git）。

约 80 行 Vue。token 化（dark 适配）。

### ProposalDetailPage.vue 集成

`onMounted` 后加 `loadDriftStatus(application_id)`，如果 `drift=true` 则在顶部 render `<DriftBanner :status="..." />`。

### CodingPage.vue 加 Sync 按钮

CodingPage 的 workspace 操作区加：
```vue
<button v-if="currentWorkspace && app.git_repo_url" @click="onSyncToRepo">
  Sync to repo
</button>
```

绑 method：
```typescript
async function onSyncToRepo() {
  try {
    const result = await gitConnectionApi.syncWorkspace(app.id, currentWorkspace.value.id)
    alert(`Sync 成功：commit ${result.commit_sha?.slice(0, 7)} on branch ${result.branch}`)
  } catch (e: any) {
    alert(e?.response?.data?.detail || e?.message || 'Sync 失败')
  }
}
```

⚠ CodingPage 是大文件，**仅插入 1 个按钮 + 1 个方法**，不要破坏其他逻辑。先 grep `currentWorkspace\|workspace_id` 找合适注入点。

vue-tsc 干净 + commit。

Commit message：

```
feat(collab/fe): DriftBanner + ProposalDetail 漂移提示 + CodingPage Sync 按钮

- DriftBanner.vue：警告风横幅（git_sha vs builder_sha 显示），点解决
  跳转 ProjectGitSetup
- ProposalDetailPage 加载 drift status，drift 时顶部 render DriftBanner
- CodingPage workspace 区加 "Sync to repo" 按钮（绑定 git 时显示）
- gitConnectionApi 加 driftStatus / resolveDrift / syncWorkspace 三 methods

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## Task 7: OAuth 完整流（GitHub + GitLab 启动 + 回调 endpoints + UI）

**Files:**
- Modify: `backend/app/routes/git_connection.py`（追加 oauth start/callback）
- Modify: `frontend/src/views/ProjectGitSetup.vue`（加 OAuth 按钮）
- Create: `frontend/src/views/GitOAuthCallback.vue`（回调中转页）
- Modify: `frontend/src/router/index.ts`

### 后端 OAuth start/callback

`git_connection.py` `router` 加：

```python
@router.get("/{project_id}/git-oauth/start")
async def oauth_start(
    project_id: int, provider: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """返回 OAuth authorize URL（前端 redirect）"""
    await require_project_access(
        db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )
    if provider == "github":
        client_id = os.environ.get("GITHUB_CLIENT_ID")
        if not client_id:
            raise HTTPException(500, "GITHUB_CLIENT_ID 未配置")
        redirect_uri = f"http://localhost:5173/git/callback/github"
        scope = "repo,admin:repo_hook"
        # state 简化：用 project_id（生产应加 nonce 防 CSRF）
        url = f"https://github.com/login/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&scope={scope}&state={project_id}"
        return {"authorize_url": url}
    if provider == "gitlab":
        client_id = os.environ.get("GITLAB_CLIENT_ID")
        host = os.environ.get("GITLAB_DEFAULT_HOST", "https://gitlab.com")
        if not client_id:
            raise HTTPException(500, "GITLAB_CLIENT_ID 未配置")
        redirect_uri = f"http://localhost:5173/git/callback/gitlab"
        scope = "api%20read_repository%20write_repository"
        url = f"{host}/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope={scope}&state={project_id}"
        return {"authorize_url": url}
    raise HTTPException(400, "unsupported provider")


class OAuthCallbackRequest(BaseModel):
    provider: str
    code: str
    state: str  # project_id
    group_id_or_org: str  # 用户在前端选填的 org/group


@router.post("/{project_id}/git-oauth/callback")
async def oauth_callback(
    project_id: int, req: OAuthCallbackRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """前端 callback 页面把 code 提交过来"""
    import httpx
    await require_project_access(
        db, project_id=project_id, user_id=ctx.user.id, tenant_id=ctx.tenant_id,
        minimum_role="maintainer",
    )

    if req.provider == "github":
        client_id = os.environ.get("GITHUB_CLIENT_ID")
        client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                "https://github.com/login/oauth/access_token",
                data={"client_id": client_id, "client_secret": client_secret,
                      "code": req.code, "redirect_uri": "http://localhost:5173/git/callback/github"},
                headers={"Accept": "application/json"},
            )
            tok_data = resp.json()
        access_token = tok_data.get("access_token")
        host = "https://github.com"
    elif req.provider == "gitlab":
        client_id = os.environ.get("GITLAB_CLIENT_ID")
        client_secret = os.environ.get("GITLAB_CLIENT_SECRET")
        host = os.environ.get("GITLAB_DEFAULT_HOST", "https://gitlab.com")
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"{host}/oauth/token",
                data={"client_id": client_id, "client_secret": client_secret,
                      "code": req.code, "grant_type": "authorization_code",
                      "redirect_uri": "http://localhost:5173/git/callback/gitlab"},
            )
            tok_data = resp.json()
        access_token = tok_data.get("access_token")
    else:
        raise HTTPException(400, "unsupported provider")

    if not access_token:
        raise HTTPException(400, f"OAuth token 交换失败: {tok_data}")

    # upsert connection
    existing = (await db.execute(
        select(GitConnection).where(GitConnection.project_id == project_id)
    )).scalar_one_or_none()
    if existing:
        existing.provider = req.provider
        existing.host = host
        existing.access_token_enc = encrypt_token(access_token)
        existing.group_id_or_org = req.group_id_or_org
        existing.status = "connected"
        await db.commit()
        return _to_dict(existing)
    else:
        conn = GitConnection(
            project_id=project_id, provider=req.provider, host=host,
            access_token_enc=encrypt_token(access_token),
            group_id_or_org=req.group_id_or_org, status="connected",
        )
        db.add(conn)
        await db.commit()
        await db.refresh(conn)
        return _to_dict(conn)
```

### 前端 ProjectGitSetup OAuth 按钮

在原 PAT 表单上方加：

```vue
<div class="oauth-buttons">
  <button class="builder-btn" @click="oauthConnect('github')">用 GitHub OAuth 连接</button>
  <button class="builder-btn" @click="oauthConnect('gitlab')">用 GitLab OAuth 连接</button>
</div>

<details>
  <summary>或者用 PAT 手动连接</summary>
  <!-- 既有 PAT 表单 -->
</details>
```

```typescript
async function oauthConnect(provider: 'github' | 'gitlab') {
  const groupOrOrg = prompt(`输入 ${provider === 'github' ? 'GitHub Org/Username' : 'GitLab Group path'}：`)
  if (!groupOrOrg) return
  // 缓存到 sessionStorage 让 callback 拿
  sessionStorage.setItem(`git-oauth-${provider}-org`, groupOrOrg)
  sessionStorage.setItem(`git-oauth-project`, String(projectId.value))
  const res = await request.get<any, { authorize_url: string }>(`/projects/${projectId.value}/git-oauth/start?provider=${provider}`)
  window.location.href = res.authorize_url
}
```

### GitOAuthCallback.vue

`/git/callback/:provider` 路由：

```vue
<template>
  <div class="oauth-callback">
    <p v-if="loading">正在完成 OAuth 连接...</p>
    <p v-else-if="error" class="error">连接失败：{{ error }}</p>
    <p v-else class="success">连接成功！3 秒后跳回 Project 设置页...</p>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '@/utils/request'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    const provider = String(route.params.provider)
    const code = String(route.query.code || '')
    const state = String(route.query.state || '')
    const projectId = sessionStorage.getItem('git-oauth-project') || state
    const groupOrOrg = sessionStorage.getItem(`git-oauth-${provider}-org`) || ''
    if (!code || !projectId) throw new Error('缺少 code 或 project_id')
    await request.post(`/projects/${projectId}/git-oauth/callback`, {
      provider, code, state, group_id_or_org: groupOrOrg,
    })
    loading.value = false
    setTimeout(() => router.push(`/project/${projectId}/git`), 3000)
  } catch (e: any) {
    loading.value = false
    error.value = e?.response?.data?.detail || e?.message || '未知错误'
  }
})
</script>

<style scoped>
.oauth-callback { padding: 48px; text-align: center; color: var(--fg); }
.error { color: var(--t-danger); }
.success { color: var(--t-success); }
</style>
```

router 加 `/git/callback/:provider`。

vue-tsc 干净 + commit。

Commit message：

```
feat(collab/git): OAuth 完整流（GitHub + GitLab）替代 Phase C v1 PAT

- GET /api/projects/{id}/git-oauth/start?provider= 返 authorize URL
- POST /api/projects/{id}/git-oauth/callback 用 code 换 access_token，
  upsert GitConnection
- 前端 ProjectGitSetup 加两个 OAuth 按钮 + PAT 退化到 details 折叠
- 新增 /git/callback/:provider 路由：GitOAuthCallback.vue 中转页

state 简化为 project_id；生产应加 nonce 防 CSRF（标 backlog）。
PAT 模式保留作为自建 GitLab / 不愿走 OAuth 的备选。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## Task 8: E2E smoke + handoff

- Backend pytest 全过（≥160 期望，Phase C 144 + Phase D 新增 ~16）
- Frontend vue-tsc 干净
- 应用 `migrate_collab_phase_d.sql`
- 真机 smoke（如条件允许）：webhook → push → proposal 同步 / 直连 merge → 拦截 / drift → banner / workspace → sync
- 写 `docs/superpowers/HANDOFF-collab-phase-d-done.md`
- Commit handoff

---

## 自检（Plan Self-Review）

**Spec 覆盖核对** vs §10 Phase D：

| Spec 条目 | Plan Task |
|----------|-----------|
| Webhook 入口 + 验签 | Task 1 |
| push 事件 → 同步 draft | Task 2 |
| MR/PR opened → 自动建 ChangeProposal | Task 2 |
| review event 同步到 ProposalReview | Task 2 |
| 直连 merge 拦截 + revert + comment | Task 3 |
| 漂移检测 + UI banner + 解决流 | Task 4 + Task 6 |
| Workspace ↔ repo 双向同步 | Task 5（v1 单向 push）+ Task 6（前端按钮）|
| OAuth 完整流 | Task 7 |
| Sync to repo 按钮 / 分支切换 | Task 6 |

**Placeholder scan**：无 TBD/TODO；具体代码块都给了。

**简化范围 backlog**：
- Workspace 反向 sync（repo push → workspace 文件）留 v2，靠 webhook 触发
- GitHub revert 用强推 ref（需 admin perm），生产 production 用 PR revert 工作流更安全
- OAuth state 用 project_id 简化，生产应加 nonce 防 CSRF
- drift resolve 仅 log，实际数据迁移留 v2
- review event GitLab 区分 approval 是另一个 event（system note），简化为 comment

**Type 一致性**：`WebhookEvent` 字段在 webhook.py 定义后被 inbound.py + intercept.py 使用，名字一致。`DriftStatus` interface 前后端名字一致。

---

## 执行选择

Plan complete and saved to `docs/superpowers/plans/2026-04-25-collab-phase-d-git-in.md`. 沿用 Phase A/B/C 的 **Subagent-Driven** 模式继续执行。

⚠ **执行前先确认**：
1. 用户已配 `BUILDER_FERNET_KEY`（Phase C 已配过 ✓）
2. 用户配 OAuth credentials 才能走 Task 7 真接 OAuth；只 PAT 可跑 Task 1-6
3. webhook 在 dev 环境需要 ngrok 或类似工具暴露 localhost；生产部署有公网域名即可
