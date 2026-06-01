"""call_apaas_with_relogin 自愈契约测试。

锁住核心行为: fn 撞 token 失效(401) → 自动重登 → fn 用新 client 重试一次。
401 发生在认证层(请求没到业务), 故重试对读写接口都安全(无重复副作用)。

这是把全仓 15 处 apaas 裸调统一接到此自愈机制前的基线保护:
确认机制本身在 (a)401重登成功重试 (b)401但无凭据重登失败 (c)非401直接抛 (d)首次就成功
四种情形下行为正确。
"""
import pytest

from app.coding import apaas_tools


@pytest.mark.asyncio
async def test_relogin_retry_on_401_then_succeeds(monkeypatch):
    """fn 第一次抛 401 → relogin 成功 → fn 第二次成功。返第二次结果。"""
    clients = ["client-old", "client-new"]
    get_calls = []

    async def fake_get_client(env_id, db):
        c = clients[len(get_calls)]
        get_calls.append(c)
        return c

    relogin_calls = []

    async def fake_relogin(env_id, db):
        relogin_calls.append(env_id)
        return True  # 有凭据, 重登成功

    monkeypatch.setattr(apaas_tools, "_get_apaas_client", fake_get_client)
    monkeypatch.setattr(apaas_tools, "_relogin_apaas_env", fake_relogin)

    fn_clients_seen = []

    async def fn(client):
        fn_clients_seen.append(client)
        if client == "client-old":
            raise RuntimeError("Client error '401 Unauthorized' for url '.../xdap-app/x'")
        return {"ok": True, "data": "from-" + client}

    result = await apaas_tools.call_apaas_with_relogin(42, object(), fn)

    assert result == {"ok": True, "data": "from-client-new"}
    assert relogin_calls == [42]                       # 重登被触发一次
    assert fn_clients_seen == ["client-old", "client-new"]  # 旧 client 失败 → 新 client 重试


@pytest.mark.asyncio
async def test_relogin_when_initial_token_is_empty(monkeypatch):
    """首次拿 client 就发现 token 为空 → 先重登拿新 client, 再执行 fn。"""
    get_calls = []

    async def fake_get_client(env_id, db):
        get_calls.append(env_id)
        if len(get_calls) == 1:
            raise ValueError("platform_env_id=59 未登录 aPaaS（token 为空），先在「平台环境」配置")
        return "client-after-login"

    relogin_calls = []

    async def fake_relogin(env_id, db):
        relogin_calls.append(env_id)
        return True

    monkeypatch.setattr(apaas_tools, "_get_apaas_client", fake_get_client)
    monkeypatch.setattr(apaas_tools, "_relogin_apaas_env", fake_relogin)

    async def fn(client):
        return {"client": client}

    result = await apaas_tools.call_apaas_with_relogin(59, object(), fn)

    assert result == {"client": "client-after-login"}
    assert get_calls == [59, 59]
    assert relogin_calls == [59]


@pytest.mark.asyncio
async def test_no_retry_when_relogin_fails(monkeypatch):
    """fn 抛 401 但 env 无凭据(relogin 返 False) → 不重试, 原样抛 401。"""
    async def fake_get_client(env_id, db):
        return "client-old"

    async def fake_relogin(env_id, db):
        return False  # 无凭据

    monkeypatch.setattr(apaas_tools, "_get_apaas_client", fake_get_client)
    monkeypatch.setattr(apaas_tools, "_relogin_apaas_env", fake_relogin)

    async def fn(client):
        raise RuntimeError("Client error '401 ' for url '.../xdap-app/x'")

    with pytest.raises(RuntimeError, match="401"):
        await apaas_tools.call_apaas_with_relogin(1, object(), fn)


@pytest.mark.asyncio
async def test_non_token_error_propagates_without_relogin(monkeypatch):
    """fn 抛非 token 错(如 500) → 不重登, 直接抛。"""
    relogin_called = []

    async def fake_get_client(env_id, db):
        return "client"

    async def fake_relogin(env_id, db):
        relogin_called.append(env_id)
        return True

    monkeypatch.setattr(apaas_tools, "_get_apaas_client", fake_get_client)
    monkeypatch.setattr(apaas_tools, "_relogin_apaas_env", fake_relogin)

    async def fn(client):
        raise RuntimeError("500 Internal Server Error")

    with pytest.raises(RuntimeError, match="500"):
        await apaas_tools.call_apaas_with_relogin(1, object(), fn)
    assert relogin_called == []  # 非 token 错不触发重登


@pytest.mark.asyncio
async def test_success_first_try_no_relogin(monkeypatch):
    """fn 首次就成功 → 不重登, 返结果。"""
    relogin_called = []

    async def fake_get_client(env_id, db):
        return "client"

    async def fake_relogin(env_id, db):
        relogin_called.append(env_id)
        return True

    monkeypatch.setattr(apaas_tools, "_get_apaas_client", fake_get_client)
    monkeypatch.setattr(apaas_tools, "_relogin_apaas_env", fake_relogin)

    async def fn(client):
        return "ok"

    assert await apaas_tools.call_apaas_with_relogin(1, object(), fn) == "ok"
    assert relogin_called == []
