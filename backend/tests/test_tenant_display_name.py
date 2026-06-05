from app.routes.auth import _tenant_item_name
from app.routes.mcp_platform import _pick_tenant_display_name


def test_auth_tenant_name_prefers_display_name_over_code_and_id():
    item = {
        "tenantId": "850079360340721665",
        "tenantName": "850079360340721665",
        "tenantCode": "dragonboat",
        "name": "dragonboat",
        "displayName": "龙舟项目",
    }

    assert _tenant_item_name(item, "850079360340721665") == "龙舟项目"


def test_platform_sync_tenant_name_prefers_display_name_over_code_and_id():
    row = {
        "tenantId": "850079360340721665",
        "tenantName": "850079360340721665",
        "tenantCode": "dragonboat",
        "name": "dragonboat",
        "displayName": "龙舟项目",
    }

    assert _pick_tenant_display_name(row, "850079360340721665") == "龙舟项目"


def test_tenant_name_falls_back_to_non_code_name():
    item = {
        "tenantId": "850079360340721665",
        "tenantCode": "dragonboat",
        "name": "龙舟项目",
    }

    assert _tenant_item_name(item, "850079360340721665") == "龙舟项目"
    assert _pick_tenant_display_name(item, "850079360340721665") == "龙舟项目"
