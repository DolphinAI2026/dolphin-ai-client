"""403 文案应渲染权限码 (application:view)，而非 py3.13 str-enum 的 repr (Action.VIEW)。

f"{action}" 在 Python 3.13 的 class Action(str, Enum) 上返回 'Action.VIEW'，
导致用户看到 "你的角色没有 application:Action.VIEW 权限" 这种天书。应是 application:view。
"""
import pytest
from fastapi import HTTPException

from app.deps import AuthContext
from app.permissions import check_resource_permission, Action


class _Resource:
    created_by = 999
    team_id = None


class _User:
    id = 1


def _denied_ctx() -> AuthContext:
    # 无权限的普通成员 → Layer 1 直接拒(到不了 db / resource)。
    return AuthContext(user=_User(), tenant_id=1, tenant_role="member", org_permissions={})


@pytest.mark.asyncio
async def test_layer1_denial_message_uses_permission_code():
    with pytest.raises(HTTPException) as ei:
        await check_resource_permission(_denied_ctx(), None, _Resource(), "application", Action.VIEW)
    detail = ei.value.detail
    assert "application:view" in detail
    assert "Action.VIEW" not in detail
