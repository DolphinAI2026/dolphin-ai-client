"""预置 UI Section 清单 — 供 BrainstormAgent 选型 + CodingAgent 渲染。

设计原则（见架构文档 § 3.5）：
- `UISection.type` 是**开放字符串**（不限制枚举）
- 本文件维护**推荐清单**，供 BrainstormAgent Prompt 插入 `SECTION_PROMPT_SECTION`
- 非清单内的 type 合法，但 `is_custom_type` 必须标为 True；
  此时 CodingAgent 需自选库实现（Element Plus / ECharts / 自写）

新增预置 section：在 BUILTIN_UI_SECTIONS 里塞一条即可，无需改 Spec schema。
"""
from __future__ import annotations

from typing import TypedDict


class UiSectionMeta(TypedDict):
    key: str
    """section type 名（snake_case，如 form / table / bar_chart）"""

    purpose: str
    """一句话用途描述"""

    typical_config_keys: list[str]
    """常见的 config 字段（给 LLM 提示该区块需要哪些配置）"""

    category: str
    """分类：form / list / detail / chart / layout / misc"""

    recommended_library: str
    """推荐的实现库（element-plus / echarts / native / ...）"""


# ══════════════════════════════════════════════════════════════
# 预置 section 清单
# ══════════════════════════════════════════════════════════════

BUILTIN_UI_SECTIONS: dict[str, UiSectionMeta] = {
    # ─── form —— 录入类 ───
    "form": {
        "key": "form",
        "purpose": "标准表单（字段列表 + 提交按钮）",
        "typical_config_keys": ["fields", "submit_text", "layout"],
        "category": "form",
        "recommended_library": "element-plus",
    },
    "search_form": {
        "key": "search_form",
        "purpose": "查询条件表单（常与 table 配合）",
        "typical_config_keys": ["fields", "collapse", "default_expanded"],
        "category": "form",
        "recommended_library": "element-plus",
    },

    # ─── list —— 列表类 ───
    "table": {
        "key": "table",
        "purpose": "数据表格（分页 / 排序 / 行操作）",
        "typical_config_keys": ["columns", "data_source", "pagination", "row_actions"],
        "category": "list",
        "recommended_library": "element-plus",
    },
    "card_group": {
        "key": "card_group",
        "purpose": "卡片列表（每条记录一张卡片）",
        "typical_config_keys": ["item_template", "data_source", "columns_count"],
        "category": "list",
        "recommended_library": "element-plus",
    },
    "tree": {
        "key": "tree",
        "purpose": "树形列表（层级数据展示）",
        "typical_config_keys": ["data_source", "node_template", "lazy_load"],
        "category": "list",
        "recommended_library": "element-plus",
    },

    # ─── detail —— 详情类 ───
    "descriptions": {
        "key": "descriptions",
        "purpose": "描述列表（key-value 展示，适合详情页）",
        "typical_config_keys": ["fields", "columns", "border"],
        "category": "detail",
        "recommended_library": "element-plus",
    },
    "tabs": {
        "key": "tabs",
        "purpose": "多标签页切换容器",
        "typical_config_keys": ["tabs", "default_active"],
        "category": "layout",
        "recommended_library": "element-plus",
    },
    "steps": {
        "key": "steps",
        "purpose": "步骤条（流程进度展示）",
        "typical_config_keys": ["steps", "active_index", "direction"],
        "category": "detail",
        "recommended_library": "element-plus",
    },

    # ─── chart —— 可视化 ───
    "bar_chart": {
        "key": "bar_chart",
        "purpose": "柱状图",
        "typical_config_keys": ["data_source", "x_field", "y_field", "stack"],
        "category": "chart",
        "recommended_library": "echarts",
    },
    "line_chart": {
        "key": "line_chart",
        "purpose": "折线图（趋势分析）",
        "typical_config_keys": ["data_source", "x_field", "y_field", "smooth"],
        "category": "chart",
        "recommended_library": "echarts",
    },
    "pie_chart": {
        "key": "pie_chart",
        "purpose": "饼图（占比分析）",
        "typical_config_keys": ["data_source", "name_field", "value_field", "donut"],
        "category": "chart",
        "recommended_library": "echarts",
    },
    "stat_card": {
        "key": "stat_card",
        "purpose": "数字指标卡（大数字 + 环比）",
        "typical_config_keys": ["value_source", "label", "compare_source"],
        "category": "chart",
        "recommended_library": "native",
    },

    # ─── layout —— 布局类 ───
    "grid": {
        "key": "grid",
        "purpose": "栅格容器（多列排列子 section）",
        "typical_config_keys": ["columns", "gap", "children"],
        "category": "layout",
        "recommended_library": "element-plus",
    },
    "header_bar": {
        "key": "header_bar",
        "purpose": "页面顶部标题栏（标题 + 主操作按钮）",
        "typical_config_keys": ["title", "actions"],
        "category": "layout",
        "recommended_library": "native",
    },
}


def is_builtin_section(section_type: str) -> bool:
    """判断一个 section type 是否在预置清单里"""
    return section_type in BUILTIN_UI_SECTIONS


# ══════════════════════════════════════════════════════════════
# LLM Prompt 片段
# ══════════════════════════════════════════════════════════════

def _render_builtin_section_table() -> str:
    by_cat: dict[str, list[UiSectionMeta]] = {}
    for meta in BUILTIN_UI_SECTIONS.values():
        by_cat.setdefault(meta["category"], []).append(meta)

    lines: list[str] = []
    cat_order = ["form", "list", "detail", "chart", "layout", "misc"]
    for cat in cat_order:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"**{cat}**：")
        for meta in items:
            cfg = f"（config: {', '.join(meta['typical_config_keys'])}）" if meta["typical_config_keys"] else ""
            lib = f" → 推荐 `{meta['recommended_library']}`"
            lines.append(f"- `{meta['key']}` — {meta['purpose']} {cfg}{lib}")
        lines.append("")
    return "\n".join(lines).rstrip()


SECTION_PROMPT_SECTION = f"""### UI Section 选型规则

PageSpec 必须至少有 1 个 `ui_sections[*]`，每个 section 指定 `type` + `config`。

**优先用预置 type**（is_custom_type=false）：

{_render_builtin_section_table()}

**选型参考**：
1. 纯录入场景 → `form`
2. 带查询条件的列表 → `search_form` + `table`
3. 详情页 → `descriptions` / `tabs`
4. 数据分析 → `bar_chart` / `line_chart` / `pie_chart` / `stat_card`（优先 echarts）
5. 多栏布局 → `grid` 嵌套其他 section

**自定义 type 的情况**（is_custom_type=true）：
- 预置清单里找不到合适语义（如地图、日历、甘特图）
- CodingAgent 会自行选库实现（优先 element-plus，再 echarts，最后自写）
- 命名用 snake_case，名字应自描述（如 `gantt_chart` / `map_picker` / `calendar`）
"""
