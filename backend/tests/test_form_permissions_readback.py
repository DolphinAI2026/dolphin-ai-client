"""GET 表单权限矩阵：aPaaS detailPageConfig 读回角色主体是 ROLE_USER，
矩阵必须为该角色建出权限格子（历史 _cell 只认 ROLE → 角色权限全空的回归）。
直接调路由函数（本仓约定），monkeypatch _safe_call_mcp_tool 喂 apaas 读回结构。
"""
from __future__ import annotations

import pytest

from app.deps import AuthContext
from app.models import Application, PlatformEnv, User
from app.routes.applications import section_content
from app.routes.applications.section_content import get_form_permissions


def _ctx(user, tenant_id):
    return AuthContext(user=user, tenant_id=tenant_id, tenant_role="tenant_admin", org_permissions={})


async def _seed_deployed_app(db, *, tenant_id=7):
    user = User(username="u_perm", hashed_password="x")
    db.add(user)
    await db.flush()
    env = PlatformEnv(
        tenant_id=tenant_id, env_name="dev", base_url="https://apaas.example.com/backend",
        platform_tenant_id="TID9", token="tok", status="connected",
    )
    db.add(env)
    await db.flush()
    app = Application(
        user_id=user.id, tenant_id=tenant_id, created_by=user.id,
        app_name="报销申请", app_code="expense", apaas_app_id="AP1", platform_env_id=env.id,
    )
    db.add(app)
    await db.flush()
    return user, app


@pytest.mark.asyncio
async def test_role_user_subject_builds_matrix_cell(db_session, monkeypatch):
    """apaas 读回 subject_type=ROLE_USER 的角色权限，矩阵应建出该角色行的格子。"""
    user, app = await _seed_deployed_app(db_session)
    await db_session.commit()

    async def fake_mcp(tool_name, env_id=None, apaas_app_id=None, extra_args=None, *, use_cache=True):
        if tool_name == "list_apaas_app_roles":
            return True, {"roles": [{"role_id": "R1", "role_name": "销售"}]}
        if tool_name == "list_apaas_form_permissions":
            return True, {
                "data_permissions": [
                    {
                        "subject": {"subject_type": "ROLE_USER", "subject_value": "R1", "range_type": "ALL"},
                        "can_view": True, "can_edit": True, "can_delete": False,
                    },
                ],
                "operation_permissions": [
                    {
                        "subject": {"subject_type": "ROLE_USER", "subject_value": "R1"},
                        "can_add": True, "can_import": False,
                    },
                ],
            }
        return False, {"error_code": "UNEXPECTED", "message": tool_name}

    monkeypatch.setattr(section_content, "_safe_call_mcp_tool", fake_mcp)

    out = await get_form_permissions(app.id, "F1", _ctx(user, 7), db_session)

    assert out.ok is True
    assert "R1" in out.matrix, "ROLE_USER 角色主体应建出矩阵格子，不能被当成非角色丢弃"
    cell = out.matrix["R1"]
    assert cell["view"] is True
    assert cell["edit"] is True
    assert cell["add"] is True
    assert cell["delete"] is False
    assert cell["range"] == "ALL"
