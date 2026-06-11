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
async def test_build_and_upload_backend_adds_runtime_when_missing(tmp_path):
    from app.routes import coding as coding_routes

    target = tmp_path / "target"
    target.mkdir()
    app_jar = target / "prd_task_kanban_summary-1.0.jar"
    runtime_jar = tmp_path / "runtime-5.0.0.jar"
    app_jar.write_bytes(b"app")
    runtime_jar.write_bytes(b"runtime")

    ws_mgr = MagicMock()
    ws_mgr.get_workspace_path.return_value = tmp_path
    ws_mgr._read_meta.return_value = {"project_type": "backend-api", "display_name": "Kanban"}
    ws_mgr.build_and_package = AsyncMock(return_value=str(tmp_path / "backend.zip"))
    ws_mgr._get_build_output_dir.return_value = target

    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok")
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"code": "ok"}

    async def _query(_app_id, file_name="", **_kwargs):
        return [
            {"id": "biz-1", "fileName": "prd_task_kanban_summary-1.0.jar", "fileType": "BACKENDENGINE"},
            {"id": "runtime-1", "fileName": "runtime-5.0.0.jar", "fileType": "BACKENDENGINE"},
        ]

    with patch.object(coding_routes, "_resolve_backend_runtime_jar", return_value=runtime_jar), \
         patch.object(coding_routes.httpx, "AsyncClient") as MockHttp, \
         patch.object(coding_routes, "APaaSClient") as MockClient:
        post = AsyncMock(return_value=resp)
        MockHttp.return_value.__aenter__.return_value.post = post
        MockClient.return_value.query_app_dev_kits = AsyncMock(side_effect=_query)

        result = await coding_routes._build_and_upload_kits(
            ws_mgr=ws_mgr, ws_id="ws1", env=env, db=AsyncMock(),
        )

    assert result["kit_ids"] == ["biz-1", "runtime-1"]
    assert result["file_names"] == ["prd_task_kanban_summary-1.0.jar", "runtime-5.0.0.jar"]
    assert result["skipped_existing_files"] == []
    assert post.await_count == 4  # 2 existence queries + 2 uploads


@pytest.mark.asyncio
async def test_build_and_upload_backend_skips_existing_runtime_upload(tmp_path):
    from app.routes import coding as coding_routes

    target = tmp_path / "target"
    target.mkdir()
    app_jar = target / "prd_task_kanban_summary-1.0.jar"
    runtime_jar = tmp_path / "runtime-5.0.0.jar"
    app_jar.write_bytes(b"app")
    runtime_jar.write_bytes(b"runtime")

    ws_mgr = MagicMock()
    ws_mgr.get_workspace_path.return_value = tmp_path
    ws_mgr._read_meta.return_value = {"project_type": "backend-api", "display_name": "Kanban"}
    ws_mgr.build_and_package = AsyncMock(return_value=str(tmp_path / "backend.zip"))
    ws_mgr._get_build_output_dir.return_value = target

    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok")
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"code": "ok"}

    async def _existing(_base_url, _tenant_id, _token, key_word):
        if key_word == "runtime-5.0.0.jar":
            return [{"id": "runtime-1", "fileName": "runtime-5.0.0.jar", "fileType": "BACKENDENGINE"}]
        return []

    async def _query(_app_id, file_name="", **_kwargs):
        return [
            {"id": "biz-1", "fileName": "prd_task_kanban_summary-1.0.jar", "fileType": "BACKENDENGINE"},
            {"id": "runtime-1", "fileName": "runtime-5.0.0.jar", "fileType": "BACKENDENGINE"},
        ]

    with patch.object(coding_routes, "_resolve_backend_runtime_jar", return_value=runtime_jar), \
         patch.object(coding_routes, "_query_existing_development_kits", AsyncMock(side_effect=_existing)), \
         patch.object(coding_routes.httpx, "AsyncClient") as MockHttp, \
         patch.object(coding_routes, "APaaSClient") as MockClient:
        post = AsyncMock(return_value=resp)
        MockHttp.return_value.__aenter__.return_value.post = post
        MockClient.return_value.query_app_dev_kits = AsyncMock(side_effect=_query)

        result = await coding_routes._build_and_upload_kits(
            ws_mgr=ws_mgr, ws_id="ws1", env=env, db=AsyncMock(),
        )

    assert result["kit_ids"] == ["biz-1", "runtime-1"]
    assert result["skipped_existing_files"] == ["runtime-5.0.0.jar"]
    assert post.await_count == 1


def test_resolve_page_register_name_prefers_apaas_custom_key():
    from app.routes.coding import _resolve_page_register_name

    assert _resolve_page_register_name({
        "outputName": "form-page-sec-risk-dashboard",
        "router": {
            "form-page-sec-risk-dashboard": {"name": "form-page-sec-risk-dashboard"},
            "apaas-custom-sec-risk-dashboard": {"name": "apaas-custom-sec-risk-dashboard"},
        },
    }, "fallback") == "apaas-custom-sec-risk-dashboard"


@pytest.mark.asyncio
async def test_deploy_to_app_bound_page_runs_full_chain():
    from app.routes import coding as coding_routes

    app_rec = MagicMock(id=10, apaas_app_id="84799", name="销售CRM")
    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok")
    client = MagicMock()
    client.enable_self_dev_config = AsyncMock(return_value={"code": "ok"})
    client.attach_apaas_source_relation = AsyncMock(return_value={"code": "ok"})
    client.query_menus = AsyncMock(return_value=[])
    client.create_self_dev_menu = AsyncMock(return_value={"code": "ok"})
    client.update_self_dev_menu_link_url = AsyncMock(return_value={"code": "ok"})
    client.query_app_detail = AsyncMock(return_value={"currentVersion": "1.0.0"})
    client.deploy_app = AsyncMock(return_value={"code": "ok"})
    up = {"kit_ids": ["999"], "file_type": "FRONTENGINE", "project_type": "form-page",
          "display_name": "Demo", "file_names": ["d.zip"], "register_name": "apaas-custom-demo"}

    # apaas write 现在走 call_apaas_with_relogin(token 自愈);测试里透传跑 fn(client)
    async def _selfheal(env_id, db, fn):
        return await fn(client)

    with patch.object(coding_routes, "WorkspaceManager"), \
         patch.object(coding_routes, "_build_and_upload_kits", AsyncMock(return_value=up)), \
         patch.object(coding_routes, "_load_app_and_env", AsyncMock(return_value=(app_rec, env))), \
         patch.object(coding_routes, "_ensure_env_token", AsyncMock(return_value="tok")), \
         patch.object(coding_routes, "call_apaas_with_relogin", _selfheal), \
         patch.object(coding_routes, "publish_extension_update", AsyncMock(return_value=1)):
        result = await coding_routes._deploy_to_app_impl(
            ws_id="ws1", local_app_id=10, ctx=MagicMock(tenant_id=1), db=AsyncMock())

    assert result["status"] == "installed"
    client.enable_self_dev_config.assert_awaited_once()
    client.attach_apaas_source_relation.assert_awaited_once()
    client.query_menus.assert_awaited_once()
    client.create_self_dev_menu.assert_awaited_once()   # 页面类才建菜单
    client.update_self_dev_menu_link_url.assert_not_awaited()
    client.deploy_app.assert_awaited_once()              # republish


@pytest.mark.asyncio
async def test_deploy_to_app_bound_page_updates_existing_menu_link():
    from app.routes import coding as coding_routes

    app_rec = MagicMock(id=10, apaas_app_id="84799", name="销售CRM")
    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok", id=7)
    client = MagicMock()
    client.enable_self_dev_config = AsyncMock(return_value={"code": "ok"})
    client.attach_apaas_source_relation = AsyncMock(return_value={"code": "ok"})
    client.query_menus = AsyncMock(return_value=[{
        "id": "m1",
        "menuName": "Demo",
        "menuType": "CUSTOM",
        "linkUrl": "apaas-custom-old-demo",
    }])
    client.create_self_dev_menu = AsyncMock(return_value={"code": "ok"})
    client.update_self_dev_menu_link_url = AsyncMock(return_value={"code": "ok"})
    client.query_app_detail = AsyncMock(return_value={"currentVersion": "1.0.0"})
    client.deploy_app = AsyncMock(return_value={"code": "ok"})
    up = {"kit_ids": ["999"], "file_type": "FRONTENGINE", "project_type": "form-page",
          "display_name": "Demo", "file_names": ["form-page-demo.zip"], "register_name": "apaas-custom-demo"}

    async def _selfheal(env_id, db, fn):
        return await fn(client)

    with patch.object(coding_routes, "WorkspaceManager"), \
         patch.object(coding_routes, "_build_and_upload_kits", AsyncMock(return_value=up)), \
         patch.object(coding_routes, "_load_app_and_env", AsyncMock(return_value=(app_rec, env))), \
         patch.object(coding_routes, "_ensure_env_token", AsyncMock(return_value="tok")), \
         patch.object(coding_routes, "call_apaas_with_relogin", _selfheal), \
         patch.object(coding_routes, "publish_extension_update", AsyncMock(return_value=1)):
        result = await coding_routes._deploy_to_app_impl(
            ws_id="ws1", local_app_id=10, ctx=MagicMock(tenant_id=1), db=AsyncMock())

    assert result["status"] == "installed"
    assert result["menu"]["action"] == "updated"
    assert result["menu"]["menu_id"] == "m1"
    client.create_self_dev_menu.assert_not_awaited()
    client.update_self_dev_menu_link_url.assert_awaited_once_with(
        "84799",
        "m1",
        "apaas-custom-demo",
        menu_type="CUSTOM",
        confirmed=True,
    )


@pytest.mark.asyncio
async def test_deploy_to_app_apaas_writes_go_through_self_heal():
    """装回的 apaas write 调用必须走 call_apaas_with_relogin(token 自愈),不能裸调。

    实测踩到:session 开久了 apaas token 过期,点「确认装回」→ enable/attach/menu/deploy
    裸调撞 401 → 「Unauthorized」直接抛给用户。包上自愈后 401 自动重登重试。
    """
    from app.routes import coding as coding_routes

    app_rec = MagicMock(id=10, apaas_app_id="84799", name="销售CRM")
    env = MagicMock(base_url="https://x", platform_tenant_id="t1", token="tok", id=7)
    client = MagicMock()
    client.enable_self_dev_config = AsyncMock(return_value={"code": "ok"})
    client.attach_apaas_source_relation = AsyncMock(return_value={"code": "ok"})
    client.query_menus = AsyncMock(return_value=[])
    client.create_self_dev_menu = AsyncMock(return_value={"code": "ok"})
    client.update_self_dev_menu_link_url = AsyncMock(return_value={"code": "ok"})
    client.query_app_detail = AsyncMock(return_value={"currentVersion": "1.0.0"})
    client.deploy_app = AsyncMock(return_value={"code": "ok"})
    up = {"kit_ids": ["999"], "file_type": "FRONTENGINE", "project_type": "form-page",
          "display_name": "Demo", "file_names": ["d.zip"], "register_name": "apaas-custom-demo"}

    seen_env_ids = []
    async def _selfheal(env_id, db, fn):
        seen_env_ids.append(env_id)
        return await fn(client)

    with patch.object(coding_routes, "WorkspaceManager"), \
         patch.object(coding_routes, "_build_and_upload_kits", AsyncMock(return_value=up)), \
         patch.object(coding_routes, "_load_app_and_env", AsyncMock(return_value=(app_rec, env))), \
         patch.object(coding_routes, "_ensure_env_token", AsyncMock(return_value="tok")), \
         patch.object(coding_routes, "APaaSClient", return_value=client), \
         patch.object(coding_routes, "call_apaas_with_relogin", _selfheal), \
         patch.object(coding_routes, "publish_extension_update", AsyncMock(return_value=1)):
        result = await coding_routes._deploy_to_app_impl(
            ws_id="ws1", local_app_id=10, ctx=MagicMock(tenant_id=1), db=AsyncMock())

    assert result["status"] == "installed"
    # enable + attach + menu + query_detail + deploy ≥ 4 个 apaas write 全经自愈包装,且用对 env_id
    assert len(seen_env_ids) >= 4
    assert all(eid == 7 for eid in seen_env_ids)
    client.enable_self_dev_config.assert_awaited_once()
    client.deploy_app.assert_awaited_once()


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
