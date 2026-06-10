from __future__ import annotations

from unittest.mock import patch

import pytest

from app.apaas_client import (
    APaaSClient,
    build_default_excel_export_config,
    build_default_excel_import_config,
)


def test_build_default_excel_io_configs_from_form_components():
    form_config = {
        "id": "form_1",
        "detailPage": {
            "formComponents": [
                {"uuid": "doc_no", "label": "单据号", "componentType": "FORM_DOCUMENT_NUMBER"},
                {"uuid": "status", "label": "状态", "componentType": "FORM_SELECT_INPUT"},
                {"uuid": "son", "label": "明细", "componentType": "FORM_WIDGET_SON_TABLE", "tableColumn": [
                    {"uuid": "qty", "label": "数量", "componentType": "FORM_NUMBER_INPUT"},
                ]},
            ],
        },
    }

    import_config = build_default_excel_import_config()
    export_config = build_default_excel_export_config(form_config)

    assert import_config["enableImport"] is True
    assert import_config["importStatus"] == "COMPLETED"
    assert export_config["enableExport"] is True
    template = export_config["exportTemplateDetailPojoList"][0]
    assert template["permissionObjects"][0]["permissionObjectType"] == "ALL_USER"
    assert template["exportComponentDetailPojoList"][:3] == [
        {"isChosen": True, "uuid": "doc_no", "label": "单据号", "componentType": "FORM_DOCUMENT_NUMBER", "chosen": True},
        {"isChosen": True, "uuid": "status", "label": "状态", "componentType": "FORM_SELECT_INPUT", "chosen": True},
        {"isChosen": True, "uuid": "qty", "label": "数量", "componentType": "FORM_NUMBER_INPUT", "chosen": True},
    ]
    assert {item["uuid"] for item in template["exportComponentDetailPojoList"]} >= {
        "createdBy",
        "lastUpdatedBy",
        "creationDate",
        "lastUpdateDate",
        "approverList",
    }


@pytest.mark.asyncio
async def test_save_form_config_updates_excel_import_and_export_configs():
    client = APaaSClient("https://fake.local/backend", "tenant_1", "token_1")
    calls: list[dict] = []

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"code": "ok", "data": {}}

        def raise_for_status(self):
            return None

    class _FakeHttp:
        async def __aenter__(self_):
            return self_

        async def __aexit__(self_, *args):
            return None

        async def post(self_, url, json=None, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _FakeResp()

    form_config = {
        "id": "form_1",
        "formName": "接口调用日志",
        "detailPage": {
            "formComponents": [
                {"uuid": "cmp_status", "label": "调用状态", "componentType": "FORM_SELECT_INPUT"},
            ],
        },
    }

    with patch("app.apaas_client.httpx.AsyncClient", lambda *args, **kwargs: _FakeHttp()):
        await client.save_form_config("app_1", form_config)

    assert [call["url"].split("?")[0] for call in calls] == [
        "https://fake.local/backend/xdap-app/formConfig/save/formConfigDetail",
        "https://fake.local/backend/xdap-app/formConfig/update/excelImportConfig",
        "https://fake.local/backend/xdap-app/formConfig/update/excelExportConfig",
    ]
    assert calls[1]["json"]["id"] == "form_1"
    assert calls[1]["json"]["excelImportConfig"]["enableImport"] is True
    assert calls[2]["json"]["id"] == "form_1"
    export_template = calls[2]["json"]["excelExportConfig"]["exportTemplateDetailPojoList"][0]
    assert export_template["enableExport"] is True
    assert export_template["exportComponentDetailPojoList"][0]["uuid"] == "cmp_status"
