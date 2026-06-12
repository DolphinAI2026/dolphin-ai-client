"""mcp_server 写类工具改完配置后必须失效该 app 的 section_content 缓存。

否则前端面板刷新在 180s TTL 窗口内拿 stale 旧数据 (字典/角色/菜单改完 3 分钟刷不出)。
这里直接验证 mcp_server._invalidate_section_cache_after_write 真清掉对应 app 的缓存条目,
且不误清其它 app。
"""
from __future__ import annotations

import time

from app import mcp_server
from app.routes.applications import section_content


def _seed_cache(apaas_app_id: str, tool: str = "list_apaas_app_dicts") -> tuple:
    """直接往 section_content TTL 缓存塞一条 (绕过真实 MCP), 返 cache_key。"""
    key = section_content._cache_key(tool, env_id=1, apaas_app_id=apaas_app_id, extra_args=None)
    section_content._cache_set(key, {"ok": True, "dicts": []})
    return key


def test_invalidate_clears_only_target_app():
    section_content._section_cache.clear()
    key_a = _seed_cache("APP_A")
    key_b = _seed_cache("APP_B")
    # 命中确认两条都在
    assert section_content._cache_get(key_a) is not None
    assert section_content._cache_get(key_b) is not None

    mcp_server._invalidate_section_cache_after_write("APP_A")

    # APP_A 被清, APP_B 不受影响
    assert section_content._cache_get(key_a) is None, "写后必须失效 APP_A 缓存"
    assert section_content._cache_get(key_b) is not None, "不能误清别的 app"


def test_invalidate_clears_all_tools_of_app():
    section_content._section_cache.clear()
    k_dicts = _seed_cache("APP_C", tool="list_apaas_app_dicts")
    k_roles = _seed_cache("APP_C", tool="list_apaas_app_roles")
    k_menus = _seed_cache("APP_C", tool="list_apaas_app_menus")

    mcp_server._invalidate_section_cache_after_write("APP_C")

    for k in (k_dicts, k_roles, k_menus):
        assert section_content._cache_get(k) is None, "该 app 全部 section 工具缓存都要清"


def test_invalidate_blank_app_id_is_noop():
    section_content._section_cache.clear()
    key = _seed_cache("APP_D")
    # 空 / 空白 app_id 不应抛错也不该乱清
    mcp_server._invalidate_section_cache_after_write("")
    mcp_server._invalidate_section_cache_after_write("   ")
    assert section_content._cache_get(key) is not None, "空 app_id 是 no-op, 不动缓存"


def test_invalidate_survives_after_other_app_expired():
    """过期条目不影响目标 app 的失效逻辑 (回归: 失效按 app key 匹配, 与 TTL 无关)。"""
    section_content._section_cache.clear()
    key = section_content._cache_key("list_apaas_app_dicts", env_id=1, apaas_app_id="APP_E", extra_args=None)
    # 手动塞一条已过期的
    section_content._section_cache[key] = (time.time() - 1.0, {"ok": True})
    # 失效不应抛错
    mcp_server._invalidate_section_cache_after_write("APP_E")
    assert key not in section_content._section_cache
