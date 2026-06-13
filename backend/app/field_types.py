"""字段类型注册表 — 单一数据源

所有字段类型相关的映射、图标、prompt 文本均从此处派生。
新增字段类型只需在 FIELD_TYPES 中加一行即可。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Set


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


# ── 数据库字段类型 → aPaaS 字段类型（兜底映射）────────────────
# 当文档/LLM 输出了数据库类型（varchar / int / date 等）而非 aPaaS
# 类型时，用这张表做兜底翻译。
_DB_TYPE_MAP: Dict[str, str] = {
    "varchar": "单行输入",
    "char": "单行输入",
    "text": "多行输入",
    "longtext": "多行输入",
    "clob": "多行输入",
    "int": "数字",
    "integer": "数字",
    "bigint": "数字",
    "smallint": "数字",
    "float": "数字",
    "double": "数字",
    "decimal": "数字",
    "numeric": "数字",
    "date": "日期时间",
    "datetime": "日期时间",
    "timestamp": "日期时间",
    "boolean": "开关",
    "bool": "开关",
    "tinyint": "开关",
    "blob": "附件上传",
}

# "字典绑定"类字段类型（字段上需要/可选 dict code）
_DICT_FIELD_TYPES: Set[str] = {"下拉单选", "下拉多选", "单选框", "复选框"}

# "关联模型"类字段类型（字段上需要/可选 ref code）
_REF_FIELD_TYPES: Set[str] = {"数据单选", "数据选择", "关联表单"}


# ── 容错别名表（非标准名 → 标准名）────────────────────────────
# 这些是 LLM / 文档可能误写的类型名，只用于规范化修正，
# 不会被 get_valid_type_names / get_comp_type_map 等"正向查询" API 列入。
# 新增别名只需在此追加。
_TYPE_ALIASES: Dict[str, str] = {
    "文本": "单行输入", "文本输入": "单行输入", "文本框": "单行输入",
    "长文本": "多行输入", "多行文本": "多行输入", "备注": "多行输入",
    "手机": "手机号码", "电话": "手机号码", "手机号": "手机号码",
    "邮箱": "电子邮箱", "电邮": "电子邮箱",
    "单选": "下拉单选", "下拉": "下拉单选", "选择": "下拉单选",
    "多选": "下拉多选",
    "数据选择": "数据单选", "关联": "数据单选", "数据选择器": "数据单选",
    "日期": "日期时间", "时间": "日期时间",
    "金额输入": "金额", "价格": "金额", "费用": "金额",
    "数字输入": "数字", "数量": "数字", "数值": "数字",
    "附件": "附件上传", "文件": "附件上传", "上传": "附件上传",
    "开关选择": "开关", "是否": "开关", "布尔": "开关",
    "人员": "人员选择", "用户选择": "人员选择",
    "部门": "部门选择", "部门选择": "部门选择",
    "地址": "地理位置", "位置": "地理位置", "定位": "地理位置",
    "明细": "子表", "子表格": "子表", "明细行": "子表",
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


def is_status_semantic_field(field: Any) -> bool:
    """判断字段/组件是否是业务状态类字段。"""
    if not isinstance(field, dict):
        return False

    values: List[str] = []
    for key in (
        "label",
        "name",
        "field_name",
        "fieldName",
        "code",
        "field_code",
        "fieldCode",
        "modelField",
        "model_field",
        "dict",
        "dictCode",
        "dict_code",
        "dictionaryCode",
    ):
        value = field.get(key)
        if value in (None, ""):
            continue
        text = str(value).strip()
        if not text:
            continue
        values.append(text)
        if key in {"modelField", "model_field"} and "." in text:
            values.append(text.rsplit(".", 1)[-1])

    for text in values:
        if "状态" in text:
            return True
        normalized = (
            text.lower()
            .replace("~", "_")
            .replace(".", "_")
            .replace("-", "_")
        )
        tokens = [part for part in normalized.split("_") if part]
        if "status" in tokens or normalized.endswith("status"):
            return True
    return False


def select_choose_type_for_component(
    component_type: str,
    component: Any = None,
    *,
    multi_value: str = "MULTI",
) -> str:
    """根据组件类型和字段语义返回下拉 chooseType。

    aPaaS 有些链路统一用 FORM_SELECT_INPUT 表示下拉，再靠 chooseType
    区分单选/多选。状态字段在业务上只能单选，不能仅因组件类型被误判成多选。
    """
    if is_status_semantic_field(component):
        return "SINGLE"
    return multi_value if str(component_type or "").strip() == "FORM_SELECT_INPUT" else "SINGLE"


def get_icon_map() -> Dict[str, str]:
    """字段类型 → 图标（替代 ai_doc_parser._ICON_MAP）"""
    all_types = get_all_types()
    return {name: info.icon for name, info in all_types.items()}


def get_valid_type_names() -> Set[str]:
    """所有有效的字段类型名集合"""
    return set(get_all_types().keys())


def get_type_aliases() -> Dict[str, str]:
    """非标准类型名 → 标准类型名（容错别名表）。

    注意：这里的别名**不在** get_valid_type_names() / get_comp_type_map() 里,
    仅用于校验/规范化场景做模糊匹配兜底。调用方通常先判断 ftype in
    get_valid_type_names()，落空再查这里。
    """
    return dict(_TYPE_ALIASES)


def get_db_type_map() -> Dict[str, str]:
    """数据库字段类型名 → aPaaS 字段类型。"""
    return dict(_DB_TYPE_MAP)


def get_dict_field_types() -> Set[str]:
    """"字典绑定"类字段类型集合。"""
    return set(_DICT_FIELD_TYPES)


def get_ref_field_types() -> Set[str]:
    """"关联模型"类字段类型集合。"""
    return set(_REF_FIELD_TYPES)


def build_prompt_field_types_compact() -> str:
    """生成 chat prompt 中的紧凑字段类型列表（替代 chat.py 中的硬编码行）"""
    parts = []
    for name, info in FIELD_TYPES.items():
        parts.append(f"{name}={info.icon}")
    return ", ".join(parts)
