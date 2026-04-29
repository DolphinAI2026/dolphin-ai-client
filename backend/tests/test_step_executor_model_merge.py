import pytest

from app.step_executor import execute_create_model


class FakeModelClient:
    def __init__(self, model):
        self.model = model
        self.create_models_calls = []
        self.add_field_calls = []

    async def query_models(self, app_id):
        return [self.model]

    async def create_models(self, app_id, payload):
        self.create_models_calls.append((app_id, payload))
        raise AssertionError("existing model should be merged, not created again")

    async def _post_resource(self, path, payload, app_id=None):
        self.add_field_calls.append((path, payload, app_id))
        self.model.setdefault("fields", []).append(
            {
                "fieldName": payload["fieldName"],
                "fieldCode": payload["fieldCode"],
                "fieldType": payload["fieldType"],
            }
        )
        return {"ok": True}


@pytest.mark.asyncio
async def test_execute_create_model_merges_existing_model_by_code_and_adds_missing_fields():
    client = FakeModelClient(
        {
            "id": "m1",
            "modelCode": "t_candidate",
            "modelName": "候选人旧名",
            "fields": [
                {"fieldName": "姓名", "fieldCode": "name", "fieldType": "STRING"},
            ],
        }
    )

    result = await execute_create_model(
        client,
        "app-1",
        {
            "name": "候选人",
            "code": "t_candidate",
            "fields": [
                {"name": "姓名", "code": "name", "type": "单行输入"},
                {"name": "备注", "code": "remark", "type": "多行输入"},
            ],
        },
        0,
        "",
    )

    assert result["reused"] is True
    assert client.create_models_calls == []
    assert len(client.add_field_calls) == 1
    assert client.add_field_calls[0][1]["fieldCode"] == "candidate_remark"
    assert result["model_info_entries"]["0"]["code"] == "t_candidate"
    assert result["model_info_entries"]["0"]["fields"]["备注"] == "candidate_remark"


@pytest.mark.asyncio
async def test_execute_create_model_reuses_existing_field_by_code():
    client = FakeModelClient(
        {
            "id": "m1",
            "modelCode": "t_requisition",
            "modelName": "招聘需求",
            "fields": [
                {"fieldName": "招聘状态", "fieldCode": "status", "fieldType": "STRING"},
            ],
        }
    )

    result = await execute_create_model(
        client,
        "app-1",
        {
            "name": "招聘需求",
            "code": "t_requisition",
            "fields": [
                {"name": "状态", "code": "status", "type": "单行输入"},
            ],
        },
        0,
        "",
    )

    assert result["reused"] is True
    assert client.create_models_calls == []
    assert client.add_field_calls == []
    assert result["model_info_entries"]["0"]["fields"]["状态"] == "status"
