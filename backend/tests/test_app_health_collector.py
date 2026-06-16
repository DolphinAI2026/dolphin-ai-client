import asyncio
from datetime import datetime
from types import SimpleNamespace

from app.services.app_health import collector

AS_OF = datetime(2026, 6, 16, 12, 0, 0)


class FakeClient:
    base_url = "x"

    async def query_menus(self, aid):
        return [{"menuName": "m"}]

    async def query_models(self, aid, with_fields=False):
        return [{"modelName": "ok", "fields": [{"x": 1}]}]

    async def query_dicts(self, aid):
        return [{"dictionaryName": "d"}]

    async def query_roles(self, aid):
        return [{"roleName": "r", "userCount": 1}]

    async def list_processes(self, aid):
        return [{"processName": "p", "nodes": [], "edges": []}]

    async def list_business_events(self, aid):
        raise RuntimeError("boom")  # 单源失败

    async def query_app_list(self):
        return [{"id": "AID", "statusName": "已上线"}]


def test_collector_partial_failure(monkeypatch):
    async def fake_call(env_id, db, fn):
        return await fn(FakeClient())

    monkeypatch.setattr(collector, "call_apaas_with_relogin", fake_call)
    app = SimpleNamespace(id=1, apaas_app_id="AID", platform_env_id=9)
    inp = asyncio.run(collector.collect_app_snapshot(app, 9, db=None, as_of=AS_OF))
    assert inp.coverage["menus"] is True
    assert inp.coverage["events"] is False  # 失败源标 False
    assert inp.events is None
    assert inp.app_entry["statusName"] == "已上线"
