"""apaas token 失效识别 — 覆盖 httpx 401 这条历史漏掉的路径。

背景: apaas_client.query_menus 等走 response.raise_for_status(), token 过期时
httpx 抛 "Client error '401 ...' for url ..." (纯英文, 无中文 token 标记)。
自愈核心 call_apaas_with_relogin 用 is_apaas_token_error 判定是否重登 —
历史上该函数只认中文标记 → 菜单等读接口对 401 不自愈, 反复报 "拉取菜单失败 401"。
本测试锁住: is_apaas_token_error 必须认得 httpx 401 / Unauthorized。
"""
from app.error_messages import is_apaas_token_error


def test_recognizes_httpx_401_raise_for_status_message():
    # query_menus 撞 token 过期时 httpx raise_for_status() 抛的真实消息形态
    msg = ("Client error '401 ' for url "
           "'https://apaas-trial.definesys.cn/backend/xdap-app/menu/query/manageAppMenu'")
    assert is_apaas_token_error(msg) is True


def test_recognizes_unauthorized_word():
    assert is_apaas_token_error("401 Unauthorized") is True
    assert is_apaas_token_error("Unauthorized") is True


def test_still_recognizes_legacy_chinese_markers():
    assert is_apaas_token_error("Token已过期或无效") is True
    assert is_apaas_token_error("请重新连接APaaS平台") is True


def test_unrelated_errors_not_flagged_as_token_error():
    # 不含 401/Unauthorized/中文标记的普通业务错误不应被误判
    assert is_apaas_token_error("应用编码重复") is False
    assert is_apaas_token_error("500 Internal Server Error") is False
    assert is_apaas_token_error("connection timeout") is False
    assert is_apaas_token_error(None) is False
    assert is_apaas_token_error("") is False
