"""Phase D Task 4 — 漂移检测测试

mock provider via unittest.mock.AsyncMock；测：
1. 应用未绑定 git → noop（drift=False, reason='no git binding'）
2. 应用无 project → noop
3. canonical 无 commit_sha → noop
4. git HEAD 与 builder canonical commit_sha 一致 → drift=False（不写日志）
5. git HEAD 与 builder canonical 不一致 → drift=True（写 PlatformDriftLog）
6. resolve_drift 写一条 drift_resolved 记录
"""
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import Application, Project, User
from app.models.collaboration import (
    GitConnection, PlatformDriftLog,
)
from app.models.spec import Spec as SpecORM
from app.models.tenant import Tenant, UserTenant
from app.git.connection import encrypt_token
from app.git.drift import check_drift, resolve_drift


def _full_spec_dict(*, app_id: int, user_id: int, spec_id: str) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "id": spec_id,
        "application_id": app_id,
        "version": 1,
        "phase": "ready",
        "goal": {"title": "测试", "summary": "s", "business_problem": "b", "confirmed": True},
        "roles": [{"code": "admin", "name": "管理员", "scope": "ALL", "confirmed": True}],
        "objects": [{
            "code": "t_order", "name": "订单",
            "fields": [{"code": "amount", "name": "金额", "type": "数字", "required": False, "confirmed": True}],
            "sub_objects": {}, "confirmed": True,
        }],
        "dicts": [], "permissions": [],
        "decisions_pending": [], "decisions_resolved": [],
        "completeness": {"confirmed": 0, "total": 0, "by_section": {}, "pending_decisions": 0, "blocking_decisions": 0},
        "created_at": now.isoformat(), "updated_at": now.isoformat(),
        "created_by": user_id,
    }


async def _seed(
    db_session, *,
    with_git_url: bool = True,
    with_project: bool = True,
    with_canonical: bool = True,
    canonical_commit_sha: str | None = "builder_sha_111",
    with_conn: bool = True,
):
    tenant = Tenant(tenant_name="t1", tenant_code="t1")
    db_session.add(tenant)
    await db_session.flush()

    owner = User(username="drift_owner", hashed_password="x")
    db_session.add(owner)
    await db_session.flush()
    db_session.add(UserTenant(user_id=owner.id, tenant_id=tenant.id, status=1))

    project = None
    if with_project:
        project = Project(name="p1", user_id=owner.id, tenant_id=tenant.id)
        db_session.add(project)
        await db_session.flush()

    app = Application(
        user_id=owner.id, tenant_id=tenant.id, created_by=owner.id,
        app_name="App1", app_code="app_drift",
        project_id=project.id if project else None,
    )
    if with_git_url:
        app.git_repo_url = "https://github.com/myorg/test_app"
        app.git_provider = "github"
        app.git_default_branch = "main"
    db_session.add(app)
    await db_session.flush()

    canonical = None
    if with_canonical:
        payload = _full_spec_dict(app_id=app.id, user_id=owner.id, spec_id="spec_canonical_drift")
        canonical = SpecORM(
            id=payload["id"], application_id=app.id, version=1,
            kind="canonical", payload=payload, phase="ready",
            created_by=owner.id, tenant_id=tenant.id,
            commit_sha=canonical_commit_sha,
        )
        db_session.add(canonical)
        app.canonical_spec_id = canonical.id

    if with_conn and project is not None:
        db_session.add(GitConnection(
            project_id=project.id,
            provider="github",
            host="https://github.com",
            access_token_enc=encrypt_token("ghp_fake"),
            group_id_or_org="myorg",
            status="connected",
        ))

    await db_session.commit()
    return {"tenant": tenant, "owner": owner, "project": project, "app": app, "canonical": canonical}


@pytest.mark.asyncio
async def test_check_drift_no_git_binding(db_session):
    """应用没绑 git → 立即返回 drift=False / reason='no git binding'"""
    s = await _seed(db_session, with_git_url=False, with_project=False, with_conn=False, with_canonical=False)
    result = await check_drift(db_session, application=s["app"])
    assert result == {"drift": False, "reason": "no git binding"}


@pytest.mark.asyncio
async def test_check_drift_no_project(db_session):
    """应用绑了 git_repo_url 但无 project → noop"""
    s = await _seed(db_session, with_project=False, with_conn=False, with_canonical=False)
    result = await check_drift(db_session, application=s["app"])
    assert result["drift"] is False
    assert result["reason"] == "no project"


@pytest.mark.asyncio
async def test_check_drift_no_canonical(db_session):
    """无 canonical_spec_id → noop"""
    s = await _seed(db_session, with_canonical=False)
    result = await check_drift(db_session, application=s["app"])
    assert result["drift"] is False
    assert result["reason"] == "no canonical"


@pytest.mark.asyncio
async def test_check_drift_canonical_without_commit_sha(db_session):
    """canonical 存在但 commit_sha=None（Phase C 之前的旧 spec）→ noop"""
    s = await _seed(db_session, canonical_commit_sha=None)
    result = await check_drift(db_session, application=s["app"])
    assert result["drift"] is False
    assert result["reason"] == "canonical without commit_sha"


@pytest.mark.asyncio
async def test_check_drift_match_no_drift(db_session):
    """git HEAD == builder canonical commit_sha → drift=False, 不写日志"""
    s = await _seed(db_session, canonical_commit_sha="abc123sha")

    fake_provider = AsyncMock()
    fake_provider.get_branch_head = AsyncMock(return_value="abc123sha")
    with patch("app.git.drift.make_provider", return_value=fake_provider):
        result = await check_drift(db_session, application=s["app"])

    assert result["drift"] is False
    assert result["git_sha"] == "abc123sha"
    assert result["builder_sha"] == "abc123sha"
    fake_provider.get_branch_head.assert_awaited_once_with(
        repo_full_path="myorg/test_app", branch="main",
    )

    drift_logs = (await db_session.execute(
        select(PlatformDriftLog).where(PlatformDriftLog.application_id == s["app"].id)
    )).scalars().all()
    assert drift_logs == []


@pytest.mark.asyncio
async def test_check_drift_mismatch_logs_drift(db_session):
    """git HEAD != builder canonical commit_sha → drift=True，写 PlatformDriftLog"""
    s = await _seed(db_session, canonical_commit_sha="builder_sha_111")

    fake_provider = AsyncMock()
    fake_provider.get_branch_head = AsyncMock(return_value="git_sha_222")
    with patch("app.git.drift.make_provider", return_value=fake_provider):
        result = await check_drift(db_session, application=s["app"])

    assert result["drift"] is True
    assert result["git_sha"] == "git_sha_222"
    assert result["builder_sha"] == "builder_sha_111"

    drift_logs = (await db_session.execute(
        select(PlatformDriftLog).where(PlatformDriftLog.application_id == s["app"].id)
    )).scalars().all()
    assert len(drift_logs) == 1
    assert drift_logs[0].kind == "drift_detected"
    assert drift_logs[0].git_sha == "git_sha_222"
    assert drift_logs[0].builder_canonical_sha == "builder_sha_111"


@pytest.mark.asyncio
async def test_check_drift_provider_error_returns_noop(db_session):
    """provider.get_branch_head 抛异常 → drift=False / reason='git read failed'"""
    s = await _seed(db_session, canonical_commit_sha="builder_sha_x")

    fake_provider = AsyncMock()
    fake_provider.get_branch_head = AsyncMock(side_effect=RuntimeError("404 branch not found"))
    with patch("app.git.drift.make_provider", return_value=fake_provider):
        result = await check_drift(db_session, application=s["app"])

    assert result["drift"] is False
    assert "git read failed" in result["reason"]


@pytest.mark.asyncio
async def test_resolve_drift_writes_log(db_session):
    """resolve_drift 写一条 drift_resolved 日志"""
    s = await _seed(db_session)
    result = await resolve_drift(
        db_session, application=s["app"],
        direction="git_to_builder", resolved_by=s["owner"].id,
    )
    assert result["status"] == "logged"
    assert result["direction"] == "git_to_builder"

    drift_logs = (await db_session.execute(
        select(PlatformDriftLog).where(
            PlatformDriftLog.application_id == s["app"].id,
            PlatformDriftLog.kind == "drift_resolved",
        )
    )).scalars().all()
    assert len(drift_logs) == 1
    assert drift_logs[0].resolution_direction == "git_to_builder"
    assert drift_logs[0].resolved_by == s["owner"].id
    assert drift_logs[0].resolved_at is not None


@pytest.mark.asyncio
async def test_resolve_drift_invalid_direction(db_session):
    s = await _seed(db_session)
    with pytest.raises(ValueError):
        await resolve_drift(
            db_session, application=s["app"],
            direction="bogus", resolved_by=s["owner"].id,
        )
