"""PR2c (SPEC v2 §1.2) — section-aware ConfigAssistant system_prompt 软引导单测.

测 `_build_section_hint(section)`:
  - 5 个白名单值 → 返非空 hint, 含焦点说明 + 工具优先级 + 跨 section 不拦
  - None / 空串 / 任意非白名单值 → 返空串
  - 大小写不一致 → 大小写不敏感 (内部 lower())
  - 前后空白 → strip
"""
from app.routes.applications import _build_section_hint, _CONFIG_CHAT_SECTION_HINTS


def test_all_five_sections_return_non_empty_hint():
    for section in ("data", "ui", "logic", "permission", "extension"):
        hint = _build_section_hint(section)
        assert hint, f"section={section} 返空串"
        assert "用户当前焦点" in hint, f"section={section} hint 缺标识"
        # 软引导核心 — 跨 section 不拦
        assert "不要拦" in hint or "不要拒" in hint, (
            f"section={section} hint 缺跨 section 兜底语"
        )


def test_none_returns_empty_string():
    assert _build_section_hint(None) == ""


def test_empty_string_returns_empty():
    assert _build_section_hint("") == ""


def test_unknown_section_returns_empty():
    """未知 section 安全降级 — 跟旧前端不传 section 行为一致."""
    assert _build_section_hint("xxx") == ""
    assert _build_section_hint("hacker") == ""


def test_case_insensitive():
    assert _build_section_hint("DATA") == _build_section_hint("data")
    assert _build_section_hint("Ui") == _build_section_hint("ui")


def test_whitespace_strip():
    assert _build_section_hint("  ui  ") == _build_section_hint("ui")
    assert _build_section_hint("\textension\n") == _build_section_hint("extension")


def test_hint_contains_section_specific_tools():
    """每个 section hint 应建议至少 2 个该 section 主打工具 (作为优先级提示).

    N2(2026-06-01): extension hint 改为引导语, 不再列 workspace 工具.
    改为验证引导语包含 'AI Coding' 关键字.
    """
    expectations = {
        "data": ["list_apaas_app_models", "list_apaas_app_dicts"],
        "ui": ["list_apaas_app_menus", "list_apaas_form_components"],
        "logic": ["list_apaas_app_processes", "list_apaas_business_events"],
        "permission": ["list_apaas_app_roles", "grant_app_access"],
    }
    for section, tools in expectations.items():
        hint = _build_section_hint(section)
        for tool in tools:
            assert tool in hint, f"section={section} hint 缺工具 {tool}"
    # extension hint 是引导去 AI Coding 的说明, 不再列 workspace 工具
    ext_hint = _build_section_hint("extension")
    assert "AI Coding" in ext_hint, "extension hint 应包含 AI Coding 引导语"
    assert "Builder 不做自定义代码开发" in ext_hint or "Builder 不做" in ext_hint, \
        "extension hint 应明确说明 Builder 不处理 codegen"


def test_module_level_hints_dict_has_all_five():
    """_CONFIG_CHAT_SECTION_HINTS 模块级字典确保 5 个 section 全在 (单一真相)."""
    assert set(_CONFIG_CHAT_SECTION_HINTS.keys()) == {
        "data", "ui", "logic", "permission", "extension",
    }
