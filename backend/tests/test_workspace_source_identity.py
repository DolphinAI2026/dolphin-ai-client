from __future__ import annotations

import json

from app.coding.workspace import WorkspaceManager


def test_workspace_catalog_identity_prefers_source_config_when_meta_is_stale(tmp_path):
    ws_path = tmp_path / "form-page-plm-lifecycle-dashboard__1_dirty"
    ws_path.mkdir()
    (ws_path / "src" / "form-page-local" / "zh-CN").mkdir(parents=True)

    stale_meta = {
        "id": "1_dirty",
        "folder_name": ws_path.name,
        "project_id": 10,
        "project_type": "form-page",
        "project_name": "form-page-plm-lifecycle-dashboard",
        "display_name": "产品生命周期分析看板",
        "user_id": 1,
        "tenant_id": 64,
        "status": "ready",
    }
    (ws_path / ".workspace.json").write_text(json.dumps(stale_meta, ensure_ascii=False))
    (ws_path / "package.json").write_text(json.dumps({"name": "form-page-factory-twin-dashboard"}))
    (ws_path / "src" / "apaas.json").write_text(json.dumps({
        "templateType": "MENU_PAGE",
        "router": {
            "apaas-custom-factory-twin-dashboard": {
                "name": "apaas-custom-factory-twin-dashboard",
                "path": "apaas-custom-factory-twin-dashboard",
            },
        },
        "copyAssets": ["public/form-page/form-page-factory-twin-dashboard"],
        "outputName": "form-page-factory-twin-dashboard",
    }))
    (ws_path / "src" / "form-page-local" / "zh-CN" / "index.js").write_text(
        'export default { title: "数字孪生工厂总览" }\n',
        encoding="utf-8",
    )

    decorated = WorkspaceManager()._decorate_workspace_meta(ws_path, stale_meta)

    assert decorated["project_name"] == "form-page-factory-twin-dashboard"
    assert decorated["display_name"] == "数字孪生工厂总览"
    assert decorated["source_identity_mismatch"] is True
