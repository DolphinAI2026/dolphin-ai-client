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
