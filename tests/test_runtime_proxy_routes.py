"""自开发整页预览依赖的运行态反向代理路由 (/app, /apaas) 回归保护。

背景: e361c7bc「删 platform_proxy 反向代理」本意只删内嵌编辑器, 却连带删掉了
custom-page-host 自开发整页预览所依赖的两条运行态代理:
  - /app/{path}   → 转发到真 apaas 运行态主机, 取自开发组件 bundle (.umd.js / .css)
  - /apaas/{path} → 转发组件运行时数据请求 ($request)
丢了 /app 后, 预览拉 .umd.js 直接 404 → host 页弹「组件包加载失败 (404?)」。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.main import app  # noqa: E402
from app.routes.runtime_proxy import _extract_app_code  # noqa: E402


def test_runtime_proxy_routes_registered():
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/app/{path:path}" in paths, "缺 /app 运行态代理 → 自开发组件 .umd.js 404"
    assert "/apaas/{path:path}" in paths, "缺 /apaas 运行态数据代理 → 组件 $request 拿不到数据"


def test_extract_app_code_from_proxy_paths():
    # /app/{tenantCode}/{appCode}/...  — 静态 bundle 路径
    assert _extract_app_code("app/mars/leave-mgmt/form-page-x/form-page-x.umd.js") == "leave-mgmt"
    assert _extract_app_code("app/df-apaas/library-borrow/form-page-y/form-page-y.css") == "library-borrow"
    # /apaas/backend/{tenantCode}/{appCode}/...  — 组件 $request 数据路径(真实形态)
    assert _extract_app_code("apaas/backend/mars/leave-mgmt/xdap-app/model/data/query") == "leave-mgmt"
    # /apaas/{tenantCode}/{appCode}/...  — 退化形态
    assert _extract_app_code("apaas/mars/leave-mgmt/foo") == "leave-mgmt"
    # 段数不足 / 不认识 → 空(走 fallback host, 不注入 token)
    assert _extract_app_code("app/onlyonelevel") == ""
    assert _extract_app_code("") == ""
    assert _extract_app_code("something/else/entirely") == ""
