"""Phase 2D — deployment_status_service 七级真相归一(契约见 docs/architecture/deployment-truth.md)。

核心价值 = 归一逻辑杜绝越级宣称:
  铁律1  build 过(级2)≠ 已发布(级6/7)
  铁律2  上传资产库(级4)≠ republish 可见(级7)
  铁律3  aPaaS 侧真相(级6-7)绝不信缓存 —— 要 live 核实才能断言"已发布"

七级独立(逐级独立, 不可跳级), 每级 tri-state: confirmed / denied / unknown。
"""
import pytest

from app.models import Application, Project, ProjectMember, User
from app.models.deploy_history import DeployRecord
from app.models.tenant import Tenant, UserTenant
from app.services.deployment_status_service import (
    DeploymentLevel,
    DeploymentStatus,
    Observation,
    gather_deployment_status,
)


# ---------------------------------------------------------------------------
# 纯核心:归一逻辑(无 db / 无 mock)
# ---------------------------------------------------------------------------

def test_build_passed_is_not_published():
    """铁律1:本地 build 过 + 出包, 但 aPaaS 侧未观测 → 绝不能宣称已发布。"""
    s = DeploymentStatus(
        workspace_changed=Observation.CONFIRMED,
        build_passed=Observation.CONFIRMED,
        package_exists=Observation.CONFIRMED,
    )
    assert s.can_claim_published() is False
    assert s.highest_confirmed_level() == DeploymentLevel.PACKAGE_EXISTS
    assert "未发布" in s.summary_phrase() or "尚未发布" in s.summary_phrase()


def test_uploaded_to_library_is_not_republished():
    """铁律2:上传资产库 + 绑定 app, 但未部署 → 不能宣称 republish 可见。"""
    s = DeploymentStatus(
        build_passed=Observation.CONFIRMED,
        package_exists=Observation.CONFIRMED,
        uploaded_to_asset_library=Observation.CONFIRMED,
        bound_to_app=Observation.CONFIRMED,
    )
    assert s.can_claim_published() is False
    assert s.highest_confirmed_level() == DeploymentLevel.BOUND_TO_APP
    assert s.republished_visible == Observation.UNKNOWN


def test_cached_deploy_is_not_trusted_as_published():
    """铁律3:级6/7 即便 confirmed, 若来自缓存(非 live)→ 不能宣称已发布。"""
    s = DeploymentStatus(
        deployed_to_apaas=Observation.CONFIRMED,
        republished_visible=Observation.CONFIRMED,
        apaas_truth_is_live=False,  # 来自 DB 历史记录 / 缓存
    )
    assert s.can_claim_published() is False


def test_live_confirmed_deploy_can_claim_published():
    """级6 live 核实 → 可以宣称已发布。"""
    s = DeploymentStatus(
        workspace_changed=Observation.CONFIRMED,
        build_passed=Observation.CONFIRMED,
        deployed_to_apaas=Observation.CONFIRMED,
        apaas_truth_is_live=True,
    )
    assert s.can_claim_published() is True
    assert "已发布" in s.summary_phrase()
    assert s.highest_confirmed_level() == DeploymentLevel.DEPLOYED_TO_APAAS


def test_live_republished_visible_can_claim_published():
    """级7 live 核实 → 最强宣称。"""
    s = DeploymentStatus(
        deployed_to_apaas=Observation.CONFIRMED,
        republished_visible=Observation.CONFIRMED,
        apaas_truth_is_live=True,
    )
    assert s.can_claim_published() is True
    assert s.highest_confirmed_level() == DeploymentLevel.REPUBLISHED_VISIBLE


def test_unknown_apaas_truth_does_not_claim_published():
    """没观测 aPaaS 侧 → 默认 unknown → 不宣称。"""
    s = DeploymentStatus(build_passed=Observation.CONFIRMED)
    assert s.can_claim_published() is False
    assert s.deployed_to_apaas == Observation.UNKNOWN


def test_levels_are_independent_no_skip_inference():
    """逐级独立:确认了级6不自动把级2/3当 confirmed。"""
    s = DeploymentStatus(
        deployed_to_apaas=Observation.CONFIRMED,
        apaas_truth_is_live=True,
    )
    # 没观测过本地 build/package → 仍 unknown, 不被级6倒推
    assert s.build_passed == Observation.UNKNOWN
    assert s.package_exists == Observation.UNKNOWN


def test_to_payload_is_single_source_for_ui_and_agent():
    """给 UI 和 agent 同一个 payload: 七级 + provenance + 可宣称态 + 人话摘要。"""
    s = DeploymentStatus(
        workspace_changed=Observation.CONFIRMED,
        build_passed=Observation.CONFIRMED,
        deployed_to_apaas=Observation.CONFIRMED,
        apaas_truth_is_live=True,
    )
    p = s.to_payload()
    assert p["can_claim_published"] is True
    assert p["highest_confirmed_level"] == 6
    assert p["levels"]["build_passed"] == "confirmed"
    assert p["levels"]["uploaded_to_asset_library"] == "unknown"
    assert p["levels"]["deployed_to_apaas"] == "confirmed"
    assert p["apaas_truth_is_live"] is True
    assert isinstance(p["summary"], str) and p["summary"]


def test_nothing_observed_is_none_level():
    s = DeploymentStatus()
    assert s.highest_confirmed_level() == DeploymentLevel.NONE
    assert s.can_claim_published() is False


# ---------------------------------------------------------------------------
# gather:从现有真相源(db / 工作区 / aPaaS live)组装
# ---------------------------------------------------------------------------

async def _seed_app(db, *, status="completed", apaas_app_id="apaas_d1"):
    tenant = Tenant(tenant_name="dt", tenant_code="dt")
    db.add(tenant)
    await db.flush()
    user = User(username="dep_owner", hashed_password="x")
    db.add(user)
    await db.flush()
    db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, status=1))
    project = Project(name="dp", user_id=user.id, tenant_id=tenant.id)
    db.add(project)
    await db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
    app = Application(
        user_id=user.id, tenant_id=tenant.id, created_by=user.id, project_id=project.id,
        app_name="Dep App", app_code="dep_app", status=status, apaas_app_id=apaas_app_id,
    )
    db.add(app)
    await db.commit()
    return tenant, user, app


@pytest.mark.asyncio
async def test_gather_bound_when_apaas_app_id_present(db_session):
    _, _, app = await _seed_app(db_session, apaas_app_id="apaas_bound_1")
    s = await gather_deployment_status(app_id=app.id, db=db_session)
    assert s.bound_to_app == Observation.CONFIRMED


@pytest.mark.asyncio
async def test_gather_unbound_when_no_apaas_app_id(db_session):
    _, _, app = await _seed_app(db_session, apaas_app_id=None)
    s = await gather_deployment_status(app_id=app.id, db=db_session)
    assert s.bound_to_app == Observation.DENIED


@pytest.mark.asyncio
async def test_gather_deploy_record_is_cached_not_live(db_session):
    """有成功 DeployRecord → deployed_to_apaas confirmed, 但来自 DB = 缓存,
    无 live fetcher 时 apaas_truth_is_live 仍 False → 不能宣称已发布。"""
    tenant, user, app = await _seed_app(db_session, apaas_app_id="apaas_dep_1")
    db_session.add(DeployRecord(
        app_id=app.id, tenant_id=tenant.id, user_id=user.id,
        status="success", deploy_type="deploy", version_label="v1",
    ))
    await db_session.commit()

    s = await gather_deployment_status(app_id=app.id, db=db_session)
    assert s.deployed_to_apaas == Observation.CONFIRMED
    assert s.apaas_truth_is_live is False
    assert s.can_claim_published() is False


@pytest.mark.asyncio
async def test_gather_live_fetcher_confirms_published(db_session):
    """注入 live fetcher 返回平台仍发布 → apaas_truth_is_live True → 可宣称。"""
    _, _, app = await _seed_app(db_session, apaas_app_id="apaas_live_1")

    async def fake_live(apaas_app_id: str) -> dict:
        assert apaas_app_id == "apaas_live_1"
        return {"deployed": True, "republished_visible": True}

    s = await gather_deployment_status(
        app_id=app.id, db=db_session, apaas_live_fetcher=fake_live
    )
    assert s.apaas_truth_is_live is True
    assert s.deployed_to_apaas == Observation.CONFIRMED
    assert s.republished_visible == Observation.CONFIRMED
    assert s.can_claim_published() is True


@pytest.mark.asyncio
async def test_gather_live_fetcher_reports_not_deployed(db_session):
    """live 核实平台已下线/未发布 → denied, 即便本地有成功记录也不宣称。"""
    tenant, user, app = await _seed_app(db_session, apaas_app_id="apaas_gone_1")
    db_session.add(DeployRecord(
        app_id=app.id, tenant_id=tenant.id, user_id=user.id,
        status="success", deploy_type="deploy", version_label="v1",
    ))
    await db_session.commit()

    async def fake_live(apaas_app_id: str) -> dict:
        return {"deployed": False, "republished_visible": False}

    s = await gather_deployment_status(
        app_id=app.id, db=db_session, apaas_live_fetcher=fake_live
    )
    assert s.apaas_truth_is_live is True
    assert s.deployed_to_apaas == Observation.DENIED
    assert s.can_claim_published() is False


@pytest.mark.asyncio
async def test_gather_workspace_observer_fills_local_levels(db_session):
    """注入 workspace_observer → 填级1-4 本地真相。"""
    _, _, app = await _seed_app(db_session, apaas_app_id="apaas_ws_1")

    def fake_ws() -> dict:
        return {
            "workspace_changed": True,
            "build_passed": True,
            "package_exists": True,
            "uploaded_to_asset_library": False,
        }

    s = await gather_deployment_status(
        app_id=app.id, db=db_session, workspace_observer=fake_ws
    )
    assert s.workspace_changed == Observation.CONFIRMED
    assert s.build_passed == Observation.CONFIRMED
    assert s.package_exists == Observation.CONFIRMED
    assert s.uploaded_to_asset_library == Observation.DENIED
