"""exchange_apaas_token 的 apaas_base_url 白名单 — 堵 SSRF。

背景: POST /api/auth/exchange-apaas-token 无鉴权(设计上必须允许未登录调 — 拿 apaas
token 换本地 JWT), 且接受用户传任意 apaas_base_url 去发请求 → 未授权 SSRF(可探内网)。
端点不能加登录(破坏 SSO 换 token), 故用 URL 白名单: base_url 必须匹配 settings 配置的
apaas_base_url 或数据库已配置的 env base_url, 否则拒绝。

锁住白名单纯函数 _is_allowed_apaas_base_url 的行为。
"""
import pytest

from app.routes.auth import _is_allowed_apaas_base_url


def _allowed(url, allowlist):
    return _is_allowed_apaas_base_url(url, allowlist)


def test_exact_match_allowed():
    allow = ["https://apaas-trial.definesys.cn/backend"]
    assert _allowed("https://apaas-trial.definesys.cn/backend", allow) is True


def test_normalized_match_allowed():
    # 末尾斜杠 / 大小写 host 差异应归一后匹配
    allow = ["https://apaas-trial.definesys.cn/backend"]
    assert _allowed("https://apaas-trial.definesys.cn/backend/", allow) is True
    assert _allowed("https://APAAS-TRIAL.definesys.cn/backend", allow) is True


def test_arbitrary_url_rejected():
    # SSRF 核心: 任意外部/内网 URL 必须拒绝
    allow = ["https://apaas-trial.definesys.cn/backend"]
    assert _allowed("http://169.254.169.254/latest/meta-data", allow) is False  # 云元数据
    assert _allowed("http://localhost:8000/admin", allow) is False
    assert _allowed("http://10.0.0.1/internal", allow) is False
    assert _allowed("https://evil.example.com/backend", allow) is False


def test_host_substring_attack_rejected():
    # 防 host 前缀/子串绕过: evil 域名带上合法 host 当路径/子域不能过
    allow = ["https://apaas-trial.definesys.cn/backend"]
    assert _allowed("https://apaas-trial.definesys.cn.evil.com/backend", allow) is False
    assert _allowed("https://evil.com/apaas-trial.definesys.cn/backend", allow) is False


def test_empty_or_none_rejected():
    allow = ["https://apaas-trial.definesys.cn/backend"]
    assert _allowed("", allow) is False
    assert _allowed(None, allow) is False


def test_empty_allowlist_rejects_all():
    # 白名单为空(未配置任何 env)→ 拒绝一切, 不给 SSRF 留口子
    assert _allowed("https://apaas-trial.definesys.cn/backend", []) is False
