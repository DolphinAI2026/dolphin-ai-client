"""platform_proxy 单元测试：验证 iframe 注入不会误隐藏页面头部。"""
import os
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.routes.platform_proxy import _inject_sso_script


def test_inject_sso_script_only_injects_auth_script():
    html = "<html><head><title>demo</title></head><body><header class='app-top-header'>应用详情</header></body></html>"

    injected = _inject_sso_script(html, '{"token":"abc"}')

    assert "localStorage.setItem('__vuex__local'" in injected
    assert "iframe-overrides" not in injected
    assert "display: none !important" not in injected
    assert "querySelectorAll('header,[class*=header]')" not in injected
    assert "<header class='app-top-header'>应用详情</header>" in injected
