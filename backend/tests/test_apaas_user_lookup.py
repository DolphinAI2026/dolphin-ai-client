import pytest

from app.apaas_client import _normalize_apaas_user_records


def test_normalize_user_records_from_top_level_array():
    resp = [
        {
            "id": "100169876816012509184",
            "account": "17621440039",
            "phone": "17621440039",
            "username": "萧轩",
            "status": "ENABLE",
            "accountType": "FORMAL",
        }
    ]

    records = _normalize_apaas_user_records(resp)

    assert len(records) == 1
    assert records[0]["id"] == "100169876816012509184"
    assert records[0]["username"] == "萧轩"


def test_normalize_user_records_from_wrapped_table():
    resp = {
        "code": "ok",
        "table": [
            {"userId": "u1", "userName": "张三"},
            "bad-row",
        ],
    }

    records = _normalize_apaas_user_records(resp)

    assert records == [{"userId": "u1", "userName": "张三"}]


def test_normalize_apaas_user_summary_handles_known_field_aliases():
    from app import mcp_server

    summary = mcp_server._normalize_apaas_user_summary(
        {
            "userId": "u1",
            "userName": "李四",
            "account": "lisi",
            "accountStatus": "ENABLE",
            "accountType": "FORMAL",
            "phone": "18800000000",
        }
    )

    assert summary == {
        "id": "u1",
        "user_name": "李四",
        "display_name": "李四",
        "account": "lisi",
        "status": "ENABLE",
        "account_type": "FORMAL",
    }


@pytest.mark.asyncio
async def test_get_apaas_user_name_calls_user_list_api_and_minimizes_output(monkeypatch):
    from app import mcp_server

    captured = {}

    async def fake_with_client(env_id, op, fn):
        class FakeClient:
            async def query_users_by_ids(self, user_ids, app_id=None):
                captured["env_id"] = env_id
                captured["op"] = op
                captured["user_ids"] = user_ids
                captured["app_id"] = app_id
                return [
                    {
                        "id": "100169876816012509184",
                        "username": "萧轩",
                        "account": "17621440039",
                        "phone": "17621440039",
                        "status": "ENABLE",
                        "accountType": "FORMAL",
                    }
                ]

        return True, await fn(FakeClient())

    monkeypatch.setattr(mcp_server, "_with_client", fake_with_client)

    out = await mcp_server.get_apaas_user_name(
        env_id=7,
        apaas_user_id=" 100169876816012509184 ",
        apaas_app_id=" app-1 ",
    )

    assert captured == {
        "env_id": 7,
        "op": "按用户ID查询用户名称",
        "user_ids": ["100169876816012509184"],
        "app_id": "app-1",
    }
    assert out["ok"] is True
    assert out["user_name"] == "萧轩"
    assert out["user"] == {
        "id": "100169876816012509184",
        "user_name": "萧轩",
        "display_name": "萧轩",
        "account": "17621440039",
        "status": "ENABLE",
        "account_type": "FORMAL",
    }
    assert "phone" not in out["user"]


@pytest.mark.asyncio
async def test_get_apaas_user_name_rejects_empty_user_id():
    from app import mcp_server

    out = await mcp_server.get_apaas_user_name(env_id=1, apaas_user_id=" ")

    assert out["ok"] is False
    assert out["error_code"] == "INVALID_APAAS_USER_ID"
