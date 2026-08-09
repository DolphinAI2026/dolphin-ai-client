"""P0 baseline diagnosis uses generic facts and never infers missing from unavailable."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import RegisteredWorkspace
from app.system_assistant.baseline_service import collect_baseline_facts
from app.system_assistant.baseline_service import build_baseline_snapshot
from app.system_assistant.policy import choose_recommended_action


def _facts(*, workspace="ready", templates="unavailable", validation="ready", complete=False):
    return {
        "workspace": {
            "status": workspace,
            "source_status": "ready",
            "items": ([{"id": "repo-1", "kind": "repository"}] if workspace == "ready" else []),
            "validation_status": validation,
        },
        "environment": {
            "status": "ready" if complete else "missing",
            "source_status": "ready",
            "items": ([{"id": "dev", "status": "connected"}] if complete else []),
        },
        "capability": {
            "status": "ready" if complete else "partial",
            "source_status": "ready" if complete else "partial",
            "items": ([{"id": "code_read"}] if complete else [{"id": "local_code_read"}]),
        },
        "knowledge": {
            "status": "ready" if complete else "missing",
            "source_status": "ready",
            "items": ([{"id": "coding-policy"}] if complete else []),
        },
        "skill": {
            "status": "ready" if complete else "partial",
            "source_status": "ready" if complete else "partial",
            "items": ([{"id": "repo-validation"}] if complete else []),
        },
        "governance": {
            "status": "ready",
            "source_status": "ready",
            "items": [{"id": "member", "permissions": ["read"]}],
        },
        "templates": {
            "status": templates,
            "source_status": templates,
            "items": ([{"id": "optional-template"}] if templates == "ready" else []),
        },
    }


def _by_id(snapshot):
    return {node["id"]: node for node in snapshot["baseline_snapshot"]["nodes"]}


def test_only_existing_repository_recommends_environment_without_fabricating_remote_sources():
    facts = _facts()
    facts["governance"]["items"] = [{"id": "tenant_admin", "permissions": []}]
    result = build_baseline_snapshot(facts, tenant_id=7)
    nodes = _by_id(result)

    assert nodes["workspace"]["status"] == "ready"
    assert nodes["environment"]["status"] == "missing"
    assert nodes["templates"]["status"] == "unavailable"
    assert result["source_status"]["templates"] == "unavailable"
    assert result["recommended_action"]["id"] == "configure_environment"


def test_optional_template_is_a_valid_generic_route_when_workspace_is_missing():
    result = build_baseline_snapshot(
        _facts(workspace="missing", templates="ready"), tenant_id=7
    )
    assert _by_id(result)["workspace"]["status"] == "missing"
    assert result["recommended_action"]["id"] == "select_template"
    assert result["available_actions"] == ["select_template"]


def test_existing_repository_with_expired_validation_recommends_validation():
    result = build_baseline_snapshot(_facts(validation="stale"), tenant_id=7)
    nodes = _by_id(result)
    assert nodes["workspace"]["status"] == "stale"
    assert result["recommended_action"]["id"] == "validate_workspace"


def test_complete_baseline_has_no_required_action():
    result = build_baseline_snapshot(
        _facts(templates="not_needed", complete=True), tenant_id=7
    )
    assert all(node["status"] in {"ready", "not_needed"} for node in result["baseline_snapshot"]["nodes"])
    assert result["recommended_action"]["status"] == "not_needed"
    assert result["available_actions"] == []


def test_policy_accepts_unavailable_as_distinct_from_missing():
    action = choose_recommended_action(
        {"workspace": {"status": "ready"}, "environment": {"status": "unavailable"}}
    )
    assert action["id"] == "inspect_environment_source"
    assert action["status"] == "partial"


def test_partial_or_unavailable_sources_never_report_no_action():
    facts = _facts(templates="unavailable", complete=True)
    result = build_baseline_snapshot(facts, tenant_id=7)

    assert result["recommended_action"]["id"] == "inspect_baseline"
    assert result["available_actions"] == ["inspect_baseline"]


def test_member_without_environment_access_gets_admin_request_action():
    facts = _facts()
    facts["environment"] = {
        "status": "unavailable",
        "source_status": "unavailable",
        "items": [],
        "metadata": {"reason": "tenant_admin_required"},
    }
    result = build_baseline_snapshot(facts, tenant_id=7)

    assert result["recommended_action"]["id"] == "request_environment_access"


@pytest.mark.asyncio
async def test_collection_is_tenant_scoped_for_registered_workspaces():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add_all([
            RegisteredWorkspace(ws_id="tenant-1", abs_path="/one", user_id=1, tenant_id=1, display_name="one"),
            RegisteredWorkspace(
                ws_id="same-tenant-other-user",
                abs_path="/other",
                user_id=2,
                tenant_id=1,
                display_name="other",
            ),
            RegisteredWorkspace(ws_id="tenant-2", abs_path="/two", user_id=2, tenant_id=2, display_name="two"),
        ])
        await session.commit()
        facts = await collect_baseline_facts(
            session,
            SimpleNamespace(
                user=SimpleNamespace(id=1),
                tenant_id=1,
                tenant_role="member",
                org_permissions={"workspace:view": True, "environment:edit": False},
            ),
        )
    await engine.dispose()

    assert [item["id"] for item in facts["workspace"]["items"]] == ["tenant-1"]
    assert facts["environment"]["metadata"]["reason"] == "tenant_admin_required"
    assert facts["governance"]["items"][0]["permissions"] == ["workspace:view"]


@pytest.mark.asyncio
async def test_admin_permissions_keep_only_granted_codes_and_environment_is_visible():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        facts = await collect_baseline_facts(
            session,
            SimpleNamespace(
                user=SimpleNamespace(id=1),
                tenant_id=1,
                tenant_role="tenant_admin",
                org_permissions={"*": True, "environment:edit": False},
            ),
        )
    await engine.dispose()

    assert facts["environment"]["status"] == "missing"
    assert facts["governance"]["items"][0]["permissions"] == ["*"]


@pytest.mark.asyncio
async def test_local_skills_and_knowledge_do_not_claim_full_workspace_authority(monkeypatch):
    class LocalSkill:
        name = "local-platform"
        source = "platform"
        description = "local"

    class UnverifiedUserSkill:
        name = "unverified-user"
        source = "user"
        description = "local user"

    monkeypatch.setattr(
        "app.system_assistant.baseline_service.SkillRegistry.scan",
        lambda _self: [LocalSkill(), UnverifiedUserSkill()],
    )
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        facts = await collect_baseline_facts(
            session,
            SimpleNamespace(
                user=SimpleNamespace(id=1),
                tenant_id=1,
                tenant_role="member",
                org_permissions={},
            ),
        )
    await engine.dispose()

    assert facts["skill"]["status"] == "partial"
    assert [item["id"] for item in facts["skill"]["items"]] == ["local-platform"]
    assert facts["skill"]["metadata"]["authoritative_source_status"] == "unavailable"
    assert facts["knowledge"]["source_status"] == "unavailable"
