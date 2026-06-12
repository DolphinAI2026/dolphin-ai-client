"""app.apaas_session 共享设施最小测试。

跟 test_call_apaas_with_relogin.py 互补: 那个桩 _get_apaas_client/_relogin 验「编排」;
这里桩一个真 client 形状的对象(先 401 后成功 / 持续 401), 验「自愈重试」对调用方可见的效果。
"""
import pytest

from app import apaas_session


class _FakeClient:
    """模拟 APaaSClient: query_app_list 在 token 失效时抛 401-风格异常。"""

    def __init__(self, token: str, fail_tokens: set[str]):
        self.token = token
        self._fail_tokens = fail_tokens
        self.calls = 0

    async def query_app_list(self):
        self.calls += 1
        if self.token in self._fail_tokens:
            raise RuntimeError(
                f"Client error '401 Unauthorized' for url '.../xdap-app/list' token={self.token}"
            )
        return [{"id": "app-1"}]


@pytest.mark.asyncio
async def test_relogin_then_retry_succeeds(monkeypatch):
    """旧 client(stale token)首调 401 → 重登换新 token → 新 client 重试成功。"""
    # 第一次拿到的是 stale-token client（会 401），重登后拿到 fresh-token client。
    clients = iter([
        _FakeClient(token="stale", fail_tokens={"stale"}),
        _FakeClient(token="fresh", fail_tokens={"stale"}),
    ])

    async def fake_get_client(env_id, db):
        return next(clients)

    relogins = []

    async def fake_relogin(env_id, db):
        relogins.append(env_id)
        return True  # env 有账密, 重登成功

    monkeypatch.setattr(apaas_session, "_get_apaas_client", fake_get_client)
    monkeypatch.setattr(apaas_session, "_relogin_apaas_env", fake_relogin)

    result = await apaas_session.call_apaas_with_relogin(
        7, object(), lambda c: c.query_app_list()
    )

    assert result == [{"id": "app-1"}]
    assert relogins == [7]  # 重登被触发恰好一次


@pytest.mark.asyncio
async def test_persistent_401_raises(monkeypatch):
    """持续 401(重登也换不来有效 token / 无凭据) → 自愈无能为力, 401 透出给调用方。"""
    async def fake_get_client(env_id, db):
        return _FakeClient(token="stale", fail_tokens={"stale"})

    async def fake_relogin(env_id, db):
        return False  # 无凭据 → 重登失败, 不重试

    monkeypatch.setattr(apaas_session, "_get_apaas_client", fake_get_client)
    monkeypatch.setattr(apaas_session, "_relogin_apaas_env", fake_relogin)

    with pytest.raises(RuntimeError, match="401"):
        await apaas_session.call_apaas_with_relogin(
            7, object(), lambda c: c.query_app_list()
        )
