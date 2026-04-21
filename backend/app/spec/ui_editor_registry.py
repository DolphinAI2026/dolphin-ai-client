"""预置 UI Editor 清单 — 供 BrainstormAgent 选型 + CodingAgent 渲染。

设计原则（见架构文档 § 3.5）：
- `ConfigProperty.ui_editor` 是**开放字符串**（只做正则校验），不是枚举
- 本文件维护**推荐清单**，BrainstormAgent Prompt 会插入 `EDITOR_PROMPT_SECTION`
- 未在清单里的 editor name 合法，但 `is_custom_editor` 必须标为 True，
  此时 CodingAgent 会自行生成对应 Vue 组件到
  `form-editor/components/{editor_name}.vue`

新增预置 editor：往 BUILTIN_UI_EDITORS 里塞一条即可，无需改 Spec schema。
"""
from __future__ import annotations

from typing import TypedDict


class UiEditorMeta(TypedDict):
    """一个预置 editor 的元信息"""
    key: str
    """editor 名称（如 form-custom-input-editor）"""

    purpose: str
    """一句话用途描述，给 LLM 看"""

    value_type: str
    """值类型（string/number/boolean/array/object），供 ConfigProperty.type 对齐"""

    typical_props: list[str]
    """常见的 editor_props（如 placeholder / min / max / options）"""

    category: str
    """分类：basic / date / color / business / misc —— 用于 prompt 分组"""


# ══════════════════════════════════════════════════════════════
# 预置 editor 清单
# ══════════════════════════════════════════════════════════════

BUILTIN_UI_EDITORS: dict[str, UiEditorMeta] = {
    # ─── basic —— form-component scaffold 默认附带 ───
    "form-custom-input-editor": {
        "key": "form-custom-input-editor",
        "purpose": "单行文本输入（替代 el-input）",
        "value_type": "string",
        "typical_props": ["placeholder", "maxlength"],
        "category": "basic",
    },
    "form-custom-textarea-editor": {
        "key": "form-custom-textarea-editor",
        "purpose": "多行文本输入（替代 el-input type=textarea）",
        "value_type": "string",
        "typical_props": ["placeholder", "rows", "maxlength"],
        "category": "basic",
    },
    "form-custom-select-editor": {
        "key": "form-custom-select-editor",
        "purpose": "下拉单选（替代 el-select + el-option）",
        "value_type": "string",
        "typical_props": ["options", "placeholder", "clearable"],
        "category": "basic",
    },
    "form-custom-switch-editor": {
        "key": "form-custom-switch-editor",
        "purpose": "开关（替代 el-switch）",
        "value_type": "boolean",
        "typical_props": ["activeText", "inactiveText"],
        "category": "basic",
    },
    "form-custom-number-editor": {
        "key": "form-custom-number-editor",
        "purpose": "数字输入（替代 el-input-number）",
        "value_type": "number",
        "typical_props": ["min", "max", "step", "precision"],
        "category": "basic",
    },

    # ─── date —— 语义化日期/时间选择 ───
    "form-custom-date-editor": {
        "key": "form-custom-date-editor",
        "purpose": "日期选择（YYYY-MM-DD）",
        "value_type": "string",
        "typical_props": ["format", "placeholder"],
        "category": "date",
    },
    "form-custom-date-time-editor": {
        "key": "form-custom-date-time-editor",
        "purpose": "日期时间选择（YYYY-MM-DD HH:mm:ss）",
        "value_type": "string",
        "typical_props": ["format", "placeholder"],
        "category": "date",
    },
    "form-custom-time-editor": {
        "key": "form-custom-time-editor",
        "purpose": "仅时间选择（HH:mm:ss）",
        "value_type": "string",
        "typical_props": ["format", "placeholder"],
        "category": "date",
    },

    # ─── color —— 颜色 ───
    "form-custom-color-editor": {
        "key": "form-custom-color-editor",
        "purpose": "颜色选择（#RRGGBB 或 rgba）",
        "value_type": "string",
        "typical_props": ["showAlpha", "predefine"],
        "category": "color",
    },

    # ─── business —— 业务类 ───
    "form-custom-field-assign-editor": {
        "key": "form-custom-field-assign-editor",
        "purpose": (
            "主表字段赋值：组件产出 1~N 个派生值，用户为每个派生值选一个主表字段接收。"
            "典型：时间差/总分/选中数据回填主表"
        ),
        "value_type": "object",
        "typical_props": ["otherFields"],
        "category": "business",
    },
    "form-custom-table-field-assign-editor": {
        "key": "form-custom-table-field-assign-editor",
        "purpose": (
            "子表字段赋值（仅子表场景）：组件产出的是整张子表的多行数据，"
            "批量写到目标子表。只有 otherFields/源字段是 FORM_WIDGET_SON_TABLE 时才用"
        ),
        "value_type": "object",
        "typical_props": ["otherFields", "targetTableCode"],
        "category": "business",
    },
}


def is_builtin_editor(editor_key: str) -> bool:
    """判断一个 editor 名是否在预置清单里"""
    return editor_key in BUILTIN_UI_EDITORS


# ══════════════════════════════════════════════════════════════
# LLM Prompt 片段（BrainstormAgent / CodingAgent 共用）
# ══════════════════════════════════════════════════════════════

def _render_builtin_editor_table() -> str:
    """按 category 分组渲染预置 editor 列表，给 LLM 看"""
    by_cat: dict[str, list[UiEditorMeta]] = {}
    for meta in BUILTIN_UI_EDITORS.values():
        by_cat.setdefault(meta["category"], []).append(meta)

    lines: list[str] = []
    cat_order = ["basic", "date", "color", "business", "misc"]
    for cat in cat_order:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"**{cat}**：")
        for meta in items:
            props = f"（props: {', '.join(meta['typical_props'])}）" if meta["typical_props"] else ""
            lines.append(f"- `{meta['key']}` — {meta['purpose']} {props}")
        lines.append("")
    return "\n".join(lines).rstrip()


EDITOR_PROMPT_SECTION = f"""### UI Editor 选型规则

每个 ConfigProperty 必须指定 `ui_editor`，命名格式 `form-custom-{{semantic}}-editor`。

**优先用预置 editor**（is_custom_editor=false）：

{_render_builtin_editor_table()}

**选型硬规则**：
1. 日期类字段 → 用 `form-custom-date-editor` / `form-custom-date-time-editor`，**禁止**用 input
2. 单个布尔 → 用 `form-custom-switch-editor`，**禁止**用 select 做 Yes/No
3. 派生值是单一数值/字符串 → 用 `form-custom-field-assign-editor`（主表版）
4. 派生值是整个子表的多行数据 → 才用 `form-custom-table-field-assign-editor`
5. 颜色 → 用 `form-custom-color-editor`
6. 有限枚举（含 options 列表）→ 用 `form-custom-select-editor`

**需要自定义 editor 的情况**（is_custom_editor=true）：
- 预置清单里找不到合适语义
- 需要复杂交互（如图片裁剪、代码编辑器、富文本）
- 需要业务联动（如依赖外部接口填充选项）

自定义时：
- 名字仍遵守正则 `^form-custom-[a-z][a-z0-9-]*-editor$`
- CodingAgent 会生成 `form-editor/components/{{editor_name}}.vue`
- 设计时尽量复用 Element UI 基础组件

**`validation` 字段填写规则**（按 prop `type` 选对应字段，其余留 null）：

| prop type | 可用字段 | 示例 |
|---|---|---|
| `number` | `min` / `max` / `step` | `{{"min": 1, "max": 10}}` |
| `string` | `min_length` / `max_length` / `pattern` | `{{"max_length": 50}}` 或 `{{"pattern": "^#[0-9A-Fa-f]{{3,6}}$"}}` |
| `array` | `min_items` / `max_items` | `{{"min_items": 1, "max_items": 5}}` |
| `boolean` | —（无需 validation） | 留 `null` |

- **能推断范围的就填**：如最大分值 1~10 → `{{"min": 1, "max": 10}}`；颜色 hex → `{{"pattern": "^#[0-9A-Fa-f]{{3,6}}$"}}`
- **不确定时留 null**：不要强行填无意义的 validation（如 string 无最大长度限制就留 null）
"""
