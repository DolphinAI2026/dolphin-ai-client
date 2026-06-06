from __future__ import annotations

import pytest

from app import mcp_server


def test_form_perms_to_rules_accepts_simplified_subject_keys():
    perms = {
        "data_permissions": [
            {
                "permission_name": "测试人员权限",
                "subject": {
                    "subject_type": "ROLE_USER",
                    "subject_value": "r_tester",
                    "subject_name": "测试人员",
                    "range_type": "ALL",
                },
                "can_view": True,
                "can_edit": False,
                "can_delete": False,
            },
            {
                "permission_name": "管理员权限",
                "subject": {
                    "subject_type": "ROLE_USER",
                    "subject_value": "r_admin",
                    "subject_name": "管理员",
                    "range_type": "SELF",
                },
                "can_view": True,
                "can_edit": True,
                "can_delete": False,
            },
        ],
        "operation_permissions": [
            {
                "permission_name": "管理员操作权限",
                "subject": {
                    "subject_type": "ROLE_USER",
                    "subject_value": "r_admin",
                    "subject_name": "管理员",
                    "range_type": "SELF",
                },
                "can_add": True,
                "can_import": False,
                "can_draft": False,
            }
        ],
    }

    rules = mcp_server._form_perms_to_rules(perms, exclude_role_id="r_tester")

    assert rules == [
        {
            "subject_type": "ROLE_USER",
            "subject_value": "r_admin",
            "subject_name": "管理员",
            "actions": ["add", "edit", "view"],
            "range_type": "SELF",
        }
    ]


def test_build_perm_payload_writes_role_subject_type_for_form_permission_api():
    payload = mcp_server._build_perm_payload_from_simple_rules(
        app_id="app_1",
        form_code="customer",
        form_id="form_1",
        rules=[
            {
                "subject_type": "ROLE_USER",
                "subject_value": "r_tester",
                "subject_name": "测试人员",
                "actions": ["view"],
                "range_type": "ALL",
            }
        ],
    )

    data_obj = payload["dataPermissionGroups"][0]["permissionObjects"][0]
    assert data_obj["permissionObjectType"] == "ROLE"
    assert data_obj["permissionObjectValue"] == "r_tester"


@pytest.mark.asyncio
async def test_set_role_resource_permission_resolves_missing_menu_form_code(monkeypatch):
    captured: dict = {}

    async def fake_list_menus(env_id: int, apaas_app_id: str) -> dict:
        return {
            "ok": True,
            "menus": [
                {
                    "menu_id": "menu_1",
                    "menu_name": "客户主数据",
                    "menu_type": "MODEL",
                    "form_id": "form_1",
                    "form_code": "",
                    "menu_code": "",
                }
            ],
        }

    async def fake_get_detail(env_id: int, apaas_app_id: str, form_id: str) -> dict:
        return {
            "ok": True,
            "form_id": form_id,
            "main_model_code": "customer_master",
        }

    async def fake_list_permissions(env_id: int, apaas_app_id: str, form_id: str) -> dict:
        return {
            "ok": True,
            "data_permissions": [
                {
                    "permission_name": "管理员权限",
                    "subject": {
                        "subject_type": "ROLE_USER",
                        "subject_value": "r_admin",
                        "subject_name": "管理员",
                        "range_type": "ALL",
                    },
                    "can_view": True,
                    "can_edit": True,
                    "can_delete": True,
                }
            ],
            "operation_permissions": [],
        }

    async def fake_set_permissions(
        env_id: int,
        apaas_app_id: str,
        form_id: str,
        form_code: str,
        rules: list,
    ) -> dict:
        captured.update(
            env_id=env_id,
            apaas_app_id=apaas_app_id,
            form_id=form_id,
            form_code=form_code,
            rules=rules,
        )
        return {"ok": True}

    monkeypatch.setattr(mcp_server, "list_apaas_app_menus", fake_list_menus)
    monkeypatch.setattr(mcp_server, "get_apaas_form_detail", fake_get_detail)
    monkeypatch.setattr(mcp_server, "list_apaas_form_permissions", fake_list_permissions)
    monkeypatch.setattr(mcp_server, "set_apaas_form_permissions", fake_set_permissions)

    resp = await mcp_server.set_role_resource_permission(
        env_id=1,
        apaas_app_id="app_1",
        role_id="r_tester",
        resource_type="form",
        resource_id="menu_1",
        permission="r",
    )

    assert resp["ok"] is True
    assert resp["form_id"] == "form_1"
    assert resp["form_code"] == "customer_master"
    assert captured["form_code"] == "customer_master"
    assert captured["rules"] == [
        {
            "subject_type": "ROLE_USER",
            "subject_value": "r_admin",
            "subject_name": "管理员",
            "actions": ["delete", "edit", "view"],
            "range_type": "ALL",
        },
        {
            "subject_type": "ROLE_USER",
            "subject_value": "r_tester",
            "subject_name": "角色tester",
            "actions": ["view"],
            "range_type": "ALL",
        },
    ]
