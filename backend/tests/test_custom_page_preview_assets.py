from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_custom_page_host_prefers_local_workspace_assets(monkeypatch, tmp_path):
    from app.routes.applications import section_content as sc

    ctx = SimpleNamespace(user=SimpleNamespace(id=1), tenant_id=64)
    app = SimpleNamespace(id=10, platform_env_id=2, apaas_app_id="123456")
    bundle_dir = "form-page-factory-twin-dashboard"
    build_dir = tmp_path / bundle_dir
    build_dir.mkdir()
    (build_dir / f"{bundle_dir}.umd.js").write_text("window.ok=true")

    monkeypatch.setattr(sc, "_auth_context_from_custom_page_request", AsyncMock(return_value=ctx))
    monkeypatch.setattr(sc, "_load_app_and_check_view", AsyncMock(return_value=app))
    monkeypatch.setattr(sc, "_auto_bind_custom_page_workspace", AsyncMock(return_value="ws1"))
    monkeypatch.setattr(sc, "_resolve_local_custom_page_asset_dir", MagicMock(return_value=("ws1", build_dir)))

    from app.coding import apaas_tools

    monkeypatch.setattr(
        apaas_tools,
        "call_apaas_with_relogin",
        AsyncMock(side_effect=[
            {"tenantCode": "mars", "appCode": "factory-wms", "status": "STARTING", "statusName": "上线中", "tenantId": "t1"},
            [{"id": "m1", "linkUrl": "apaas-custom-factory-twin-dashboard"}],
        ]),
    )

    response = await sc.get_custom_page_host(
        10,
        menu_id="m1",
        request=SimpleNamespace(headers={}),
        db=MagicMock(),
        _auth="tok.123",
    )
    html = response.body.decode()

    assert "/api/applications/10/custom-page-assets-auth/tok.123/form-page-factory-twin-dashboard/form-page-factory-twin-dashboard.css" in html
    assert "C.appBase + C.bundleDir + '/' + C.bundleDir + '.umd.js' + (C.assetQuery || '')" in html
    assert '"/app/mars/factory-wms/"' not in html


@pytest.mark.asyncio
async def test_custom_page_asset_route_serves_only_build_dir(monkeypatch, tmp_path):
    from app.routes.applications import section_content as sc

    ctx = SimpleNamespace(user=SimpleNamespace(id=1), tenant_id=64)
    app = SimpleNamespace(id=10)
    bundle_dir = "form-page-factory-twin-dashboard"
    build_dir = tmp_path / bundle_dir
    build_dir.mkdir()
    asset = build_dir / f"{bundle_dir}.umd.js"
    asset.write_text("window.ok=true")

    monkeypatch.setattr(sc, "_auth_context_from_custom_page_request", AsyncMock(return_value=ctx))
    monkeypatch.setattr(sc, "_load_app_and_check_view", AsyncMock(return_value=app))
    monkeypatch.setattr(sc, "_resolve_local_custom_page_asset_dir", MagicMock(return_value=("ws1", build_dir)))

    response = await sc.get_custom_page_asset(
        10,
        bundle_dir=bundle_dir,
        asset_path=f"{bundle_dir}.umd.js",
        request=SimpleNamespace(headers={}),
        db=MagicMock(),
        _auth="tok",
    )
    assert response.path == str(asset)

    with pytest.raises(HTTPException) as exc:
        await sc.get_custom_page_asset(
            10,
            bundle_dir=bundle_dir,
            asset_path="../secret.txt",
            request=SimpleNamespace(headers={}),
            db=MagicMock(),
            _auth="tok",
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_custom_page_asset_auth_path_serves_nested_runtime_assets(monkeypatch, tmp_path):
    from app.routes.applications import section_content as sc

    ctx = SimpleNamespace(user=SimpleNamespace(id=1), tenant_id=64)
    app = SimpleNamespace(id=10)
    bundle_dir = "form-page-factory-twin-dashboard"
    build_dir = tmp_path / bundle_dir
    image_dir = build_dir / "img"
    image_dir.mkdir(parents=True)
    image = image_dir / "factory-twin-bg.c4656550.jpeg"
    image.write_bytes(b"jpeg")

    monkeypatch.setattr(sc, "_auth_context_from_custom_page_request", AsyncMock(return_value=ctx))
    monkeypatch.setattr(sc, "_load_app_and_check_view", AsyncMock(return_value=app))
    monkeypatch.setattr(sc, "_resolve_local_custom_page_asset_dir", MagicMock(return_value=("ws1", build_dir)))

    response = await sc.get_custom_page_asset_with_auth_path(
        10,
        asset_token="tok.123",
        bundle_dir=bundle_dir,
        asset_path="img/factory-twin-bg.c4656550.jpeg",
        request=SimpleNamespace(headers={}),
        db=MagicMock(),
    )
    assert response.path == str(image)
