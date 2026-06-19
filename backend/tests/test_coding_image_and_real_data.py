"""两个 live bug 的回归锁(2026-06-19):

1. 对话图片「加载失败」: 上传成功但 <img> GET 取 /raw 要 header 鉴权 → 401。
   /raw 端点必须用 auth_from_header_or_query(支持 ?token=), 与 serve-logs SSE 同款。
2. agent 误报「真实数据已接通」: 本地 preview 无平台运行时, build 成功 ≠ 真数据接通。
   _WORKFLOW_PAGE 必须明确这条铁律(代码段, 不走 DB, 对所有 page/mobile-page 产物即时生效)。
"""
from __future__ import annotations

from app.agents.coding import prompts as cp
from app.routes.coding import router
from app.deps import auth_from_header_or_query


def test_page_workflow_warns_build_success_is_not_real_data():
    seg = cp._WORKFLOW_PAGE
    assert "npm run build" in seg
    assert "≠" in seg                       # build 成功 ≠ 真实数据已接通
    assert "真实数据" in seg
    assert ("占位" in seg) or ("mock" in seg.lower())
    assert "平台运行态" in seg               # 真数据只在平台运行态验


def test_raw_endpoint_uses_query_token_auth():
    """/raw 必须走 auth_from_header_or_query —— 原生 <img> GET 带不了 Authorization header,
    只能靠 ?token= 后备; 否则对话里的图片必 401 → 显示「加载失败」。"""
    raw_routes = [r for r in router.routes if getattr(r, "path", "").endswith("/raw")]
    assert raw_routes, "/raw 路由没找到"
    deps = raw_routes[0].dependant.dependencies
    assert any(d.call is auth_from_header_or_query for d in deps), \
        "/raw 没用 auth_from_header_or_query(浏览器 <img> 带不了 header → 图片 401)"
