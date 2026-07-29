from types import SimpleNamespace

import pytest

import app.routes.llm_configs as llm_config_routes


@pytest.mark.asyncio
async def test_control_plane_code_model_options_are_empty_without_local_tenant(
    db_session,
):
    ctx = SimpleNamespace(
        user=SimpleNamespace(
            id=17,
            is_platform_admin=False,
            account_source="control_plane",
        ),
        tenant_id=0,
        tenant_role="member",
        tenant_access_scope="control_plane_code",
        control_plane_tenant_id="2077284540335579137",
    )

    result = await llm_config_routes.list_llm_config_options(
        ctx,
        db_session,
        purpose="coding",
    )

    assert result == []
