"""AI Coding 装回应用 (deploy-to-app) 编排 — 单元测试。

锁住:
- _build_and_upload_kits: 构建 + 上传 developmentKit 后,用 fileName 反查到 kit_id。
- _deploy_to_app_impl: bound 页面类跑完整链(enable→attach→建菜单→republish);
  lib(无 app)只上传。
所有平台调用 mock 掉,不打真实 aPaaS。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_build_and_upload_kits_returns_kit_ids(tmp_path):
    from app.routes import coding as coding_routes

    zip_path = tmp_path / "form-page-demo.zip"
    zip_path.write_bytes(b"PK\x03\x04demo")

    ws_mgr = MagicMock()
    ws_mgr.get_workspace_path.return_value = tmp_path
    ws_mgr._read_meta.return_value = {"project_type": "form-page", "display_name": "Demo"}
    ws_mgr.build_and_package = AsyncMock(return_value=str(zip_path))

    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok",
                    username="u", password_enc=None)

    resp = MagicMock(status_code=200)
    resp.json.return_value = {"code": "ok"}

    with patch.object(coding_routes.httpx, "AsyncClient") as MockHttp, \
         patch.object(coding_routes, "APaaSClient") as MockClient:
        MockHttp.return_value.__aenter__.return_value.post = AsyncMock(return_value=resp)
        MockClient.return_value.query_app_dev_kits = AsyncMock(
            return_value=[{"id": "999", "fileName": "form-page-demo.zip", "fileType": "FRONTENGINE"}]
        )
        result = await coding_routes._build_and_upload_kits(
            ws_mgr=ws_mgr, ws_id="ws1", env=env, db=AsyncMock(),
        )

    assert result["kit_ids"] == ["999"]
    assert result["file_type"] == "FRONTENGINE"
    assert result["project_type"] == "form-page"
    assert result["file_names"] == ["form-page-demo.zip"]


@pytest.mark.asyncio
async def test_deploy_to_app_bound_page_runs_full_chain():
    from app.routes import coding as coding_routes

    app_rec = MagicMock(id=10, apaas_app_id="84799", name="销售CRM")
    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok")
    client = MagicMock()
    client.enable_self_dev_config = AsyncMock(return_value={"code": "ok"})
    client.attach_apaas_source_relation = AsyncMock(return_value={"code": "ok"})
    client.create_self_dev_menu = AsyncMock(return_value={"code": "ok"})
    client.query_app_detail = AsyncMock(return_value={"currentVersion": "1.0.0"})
    client.deploy_app = AsyncMock(return_value={"code": "ok"})
    up = {"kit_ids": ["999"], "file_type": "FRONTENGINE", "project_type": "form-page",
          "display_name": "Demo", "file_names": ["d.zip"], "register_name": "apaas-custom-demo"}

    with patch.object(coding_routes, "WorkspaceManager"), \
         patch.object(coding_routes, "_build_and_upload_kits", AsyncMock(return_value=up)), \
         patch.object(coding_routes, "_load_app_and_env", AsyncMock(return_value=(app_rec, env))), \
         patch.object(coding_routes, "_ensure_env_token", AsyncMock(return_value="tok")), \
         patch.object(coding_routes, "APaaSClient", return_value=client), \
         patch.object(coding_routes, "publish_extension_update", AsyncMock(return_value=1)):
        result = await coding_routes._deploy_to_app_impl(
            ws_id="ws1", local_app_id=10, ctx=MagicMock(tenant_id=1), db=AsyncMock())

    assert result["status"] == "installed"
    client.enable_self_dev_config.assert_awaited_once()
    client.attach_apaas_source_relation.assert_awaited_once()
    client.create_self_dev_menu.assert_awaited_once()   # 页面类才建菜单
    client.deploy_app.assert_awaited_once()              # republish


@pytest.mark.asyncio
async def test_deploy_to_app_lib_uploads_only():
    from app.routes import coding as coding_routes

    env = MagicMock(token="tok")
    up = {"kit_ids": ["1"], "file_type": "FRONTCOMPONENT", "project_type": "form-component",
          "display_name": "Tree", "file_names": ["c.zip"], "register_name": "apaas-custom-tree"}
    result_obj = MagicMock()
    result_obj.scalars.return_value.first.return_value = env
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_obj)

    with patch.object(coding_routes, "WorkspaceManager"), \
         patch.object(coding_routes, "_ensure_env_token", AsyncMock(return_value="tok")), \
         patch.object(coding_routes, "_build_and_upload_kits", AsyncMock(return_value=up)):
        result = await coding_routes._deploy_to_app_impl(
            ws_id="ws1", local_app_id=None, ctx=MagicMock(tenant_id=1), db=db)

    assert result["status"] == "uploaded_only"
    assert result["kits"] == ["c.zip"]
