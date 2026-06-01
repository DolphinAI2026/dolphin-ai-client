"""「查看应用详情」类接口的租户来源解析 — 统一以当前登录用户的 aPaaS 租户为准。

背景 (2026-06-01 bug): get_application 的 apaas_url 深链 (/platform/{tid}/admin/...) +
get_apaas_access_url 运行态链接, 原先用 env.platform_tenant_id / 默认环境 / 写死的
settings.apaas_tenant_id 当租户来源, 导致 A 用户看自己应用详情时, 链接/查询被发去
别家(写死的)租户 → 拉不到菜单 / 深链指向错租户。

锁住纯函数 _resolve_current_apaas_tenant 的行为: 当前登录用户的 apaas 租户优先,
app 绑定环境的租户兜底, **绝不回退到写死的 settings.apaas_tenant_id**。
"""
from app.config import settings
from app.routes.applications._helpers import _resolve_current_apaas_tenant


def test_prefers_current_user_tenant_over_env():
    # 核心 bug: 当前登录用户的真实租户必须压过 app 绑定环境里残留的(别家)租户
    assert (
        _resolve_current_apaas_tenant("828940713101099009", "743906758237356033")
        == "828940713101099009"
    )


def test_falls_back_to_env_when_user_missing():
    assert _resolve_current_apaas_tenant(None, "828940713101099009") == "828940713101099009"
    assert _resolve_current_apaas_tenant("", "828940713101099009") == "828940713101099009"


def test_never_falls_back_to_hardcoded_settings_tenant():
    # 两个来源都为空时返 None — 绝不能悄悄用写死的 settings.apaas_tenant_id
    assert _resolve_current_apaas_tenant(None, None) is None
    assert _resolve_current_apaas_tenant("", "") is None
    assert _resolve_current_apaas_tenant("   ", "   ") is None
    # 防回归: 结果绝不等于那个写死的全局租户 (历史上 = "743906758237356033")
    assert _resolve_current_apaas_tenant(None, None) != settings.apaas_tenant_id


def test_strips_whitespace():
    assert _resolve_current_apaas_tenant("  828940713101099009  ", None) == "828940713101099009"
