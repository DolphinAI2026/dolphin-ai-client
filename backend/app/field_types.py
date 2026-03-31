"""字段类型注册表 — 单一数据源

所有字段类型相关的映射、图标、prompt 文本均从此处派生。
新增字段类型只需在 FIELD_TYPES 中加一行即可。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set


@dataclass(frozen=True)
class FieldTypeInfo:
    """单个字段类型的完整定义"""
    display_name: str       # 界面显示名："单行输入"
    data_model_type: str    # 平台数据模型类型："STRING"
    component_type: str     # 平台表单组件类型："FORM_TEXT_INPUT"
    icon: str               # 预览图标："T"
    prompt_icon: str        # LLM prompt 中的图标（可与 icon 不同）
    description: str        # 使用场景说明


# ══════════════════════════════════════════════════════════════
# 核心注册表 — 新增字段类型只需在此追加
# ══════════════════════════════════════════════════════════════

FIELD_TYPES: Dict[str, FieldTypeInfo] = {
    "单据号": FieldTypeInfo(
        display_name="单据号", data_model_type="STRING",
        component_type="FORM_DOCUMENT_NUMBER", icon="#", prompt_icon="#",
        description="唯一编号，自动生成",
    ),
    "单行输入": FieldTypeInfo(
        display_name="单行输入", data_model_type="STRING",
        component_type="FORM_TEXT_INPUT", icon="T", prompt_icon="T",
        description="普通文本：名称、标题",
    ),
    "多行输入": FieldTypeInfo(
        display_name="多行输入", data_model_type="BIG_TEXT",
        component_type="FORM_TEXTAREA_INPUT", icon="¶", prompt_icon="¶",
        description="长文本：描述、备注",
    ),
    "手机号码": FieldTypeInfo(
        display_name="手机号码", data_model_type="STRING",
        component_type="FORM_PHONE_INPUT", icon="P", prompt_icon="📱",
        description="手机号",
    ),
    "电子邮箱": FieldTypeInfo(
        display_name="电子邮箱", data_model_type="STRING",
        component_type="FORM_EMAIL_INPUT", icon="@", prompt_icon="✉",
        description="邮箱",
    ),
    "下拉单选": FieldTypeInfo(
        display_name="下拉单选", data_model_type="STRING",
        component_type="FORM_SELECT_INPUT_SINGLE", icon="▼", prompt_icon="▼",
        description="固定选项单选，必须绑定字典（设 dict 字段）",
    ),
    "下拉多选": FieldTypeInfo(
        display_name="下拉多选", data_model_type="STRING",
        component_type="FORM_SELECT_INPUT", icon="☰", prompt_icon="☰",
        description="固定选项多选，必须绑定字典",
    ),
    "数据单选": FieldTypeInfo(
        display_name="数据单选", data_model_type="STRING",
        component_type="FORM_DATA_SELECTOR_SINGLE", icon="⇢", prompt_icon="🔗",
        description="关联其他表单数据，必须设 ref",
    ),
    "日期时间": FieldTypeInfo(
        display_name="日期时间", data_model_type="DATE",
        component_type="FORM_DATEPICK_INPUT", icon="D", prompt_icon="📅",
        description="日期、时间",
    ),
    "金额": FieldTypeInfo(
        display_name="金额", data_model_type="NUM",
        component_type="FORM_MONEY_INPUT", icon="¥", prompt_icon="💰",
        description="金额",
    ),
    "数字": FieldTypeInfo(
        display_name="数字", data_model_type="NUM",
        component_type="FORM_NUMBER_INPUT", icon="N", prompt_icon="123",
        description="数量、数值",
    ),
    "附件上传": FieldTypeInfo(
        display_name="附件上传", data_model_type="STRING",
        component_type="FORM_FILE_UPLOAD", icon="⊕", prompt_icon="📎",
        description="文件上传",
    ),
    "开关": FieldTypeInfo(
        display_name="开关", data_model_type="STRING",
        component_type="FORM_SWITCH_SELECT", icon="⊘", prompt_icon="⊘",
        description="是/否",
    ),
    "人员选择": FieldTypeInfo(
        display_name="人员选择", data_model_type="STRING",
        component_type="FORM_PEOPLE_SELECT", icon="⊙", prompt_icon="👤",
        description="选择系统用户",
    ),
    "部门选择": FieldTypeInfo(
        display_name="部门选择", data_model_type="STRING",
        component_type="FORM_DEPARTMENT_SELECT", icon="⊙", prompt_icon="🏢",
        description="选择部门",
    ),
    "地理位置": FieldTypeInfo(
        display_name="地理位置", data_model_type="STRING",
        component_type="FORM_WIDGET_LOCATION", icon="◎", prompt_icon="📍",
        description="地址定位",
    ),
    "子表": FieldTypeInfo(
        display_name="子表", data_model_type="STRING",
        component_type="FORM_WIDGET_SON_TABLE", icon="▦", prompt_icon="▦",
        description="明细行（订单行、配件清单等）",
    ),
    "单选框": FieldTypeInfo(
        display_name="单选框", data_model_type="STRING",
        component_type="FORM_RADIO_INPUT", icon="○", prompt_icon="○",
        description="单选框，必须绑定字典",
    ),
    "复选框": FieldTypeInfo(
        display_name="复选框", data_model_type="STRING",
        component_type="FORM_CHECKBOX_INPUT", icon="☑", prompt_icon="☑",
        description="复选框（多选），必须绑定字典",
    ),
    "富文本": FieldTypeInfo(
        display_name="富文本", data_model_type="BIG_TEXT",
        component_type="FORM_RICH_TEXT", icon="R", prompt_icon="R",
        description="富文本编辑器，支持图文排版",
    ),
    "超链接": FieldTypeInfo(
        display_name="超链接", data_model_type="STRING",
        component_type="FORM_HYPERLINK_INPUT", icon="🔗", prompt_icon="🔗",
        description="URL 超链接",
    ),
    "身份证号": FieldTypeInfo(
        display_name="身份证号", data_model_type="STRING",
        component_type="FORM_IDCARD_INPUT", icon="ID", prompt_icon="ID",
        description="身份证号，自带格式校验",
    ),
    "地区地址": FieldTypeInfo(
        display_name="地区地址", data_model_type="STRING",
        component_type="FORM_WIDGET_AREA", icon="◎", prompt_icon="◎",
        description="省市区联动地址选择",
    ),
    "数据选择": FieldTypeInfo(
        display_name="数据选择", data_model_type="STRING",
        component_type="FORM_DATA_SELECTOR", icon="⇢", prompt_icon="⇢",
        description="关联其他表单数据（多选），必须设 ref",
    ),
    "关联表单": FieldTypeInfo(
        display_name="关联表单", data_model_type="STRING",
        component_type="FORM_ASSOCIATION", icon="≡", prompt_icon="≡",
        description="通过字段关联显示另一张表的数据",
    ),
}

# ── 兼容 / 别名类型（映射到标准类型）──

_COMPAT_TYPES: Dict[str, FieldTypeInfo] = {
    "布尔": FIELD_TYPES["开关"],
    "多选框": FIELD_TYPES["复选框"],
    "数据多选": FIELD_TYPES["数据选择"],
    "证件号": FIELD_TYPES["身份证号"],
    "签名": FieldTypeInfo(
        display_name="签名", data_model_type="STRING",
        component_type="FORM_TEXT_INPUT", icon="S", prompt_icon="S",
        description="签名",
    ),
}


# ══════════════════════════════════════════════════════════════
# 派生视图 — 各模块直接导入使用
# ══════════════════════════════════════════════════════════════

def get_all_types() -> Dict[str, FieldTypeInfo]:
    """返回所有类型（含兼容类型）"""
    return {**FIELD_TYPES, **_COMPAT_TYPES}


def get_field_type_map() -> Dict[str, str]:
    """preview 字段类型 → 数据模型字段类型（替代 generator_v2.FIELD_TYPE_MAP）"""
    all_types = get_all_types()
    return {name: info.data_model_type for name, info in all_types.items()}


def get_comp_type_map() -> Dict[str, str]:
    """preview 字段类型 → 表单组件类型（替代 generator_v2.COMP_TYPE_MAP）"""
    all_types = get_all_types()
    return {name: info.component_type for name, info in all_types.items()}


def get_icon_map() -> Dict[str, str]:
    """字段类型 → 图标（替代 ai_doc_parser._ICON_MAP）"""
    all_types = get_all_types()
    return {name: info.icon for name, info in all_types.items()}


def get_valid_type_names() -> Set[str]:
    """所有有效的字段类型名集合"""
    return set(get_all_types().keys())


def build_prompt_field_types_table() -> str:
    """生成 LLM prompt 中的字段类型表格（替代 ai_doc_parser._FIELD_TYPES）"""
    lines = [
        "## 字段类型及图标（只能使用以下类型）",
        "",
        "| type | icon | 使用场景 |",
        "|------|------|----------|",
    ]
    for name, info in FIELD_TYPES.items():
        lines.append(f"| {name} | {info.prompt_icon} | {info.description} |")
    return "\n".join(lines)


def build_prompt_field_types_compact() -> str:
    """生成 chat prompt 中的紧凑字段类型列表（替代 chat.py 中的硬编码行）"""
    parts = []
    for name, info in FIELD_TYPES.items():
        parts.append(f"{name}={info.icon}")
    return ", ".join(parts)
