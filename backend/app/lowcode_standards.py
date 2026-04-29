"""Low-code design/config normalization rules.

The builder has two separate vocabularies:
- data model storage types: varchar/text/datetime/date/decimal/int/bigint
- form component types: 单行输入/部门选择/人员选择/下拉单选/...

LLM output and older configs sometimes mix those together. This module keeps the
normalization in one place so document rendering and deployment use the same
rules.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any

from app.field_types import get_comp_type_map, get_type_aliases, get_valid_type_names
from app.operations.identifiers import _RESERVED


ALLOWED_DATABASE_FIELD_TYPES = {
    "varchar",
    "text",
    "datetime",
    "date",
    "decimal",
    "int",
    "bigint",
}

_COMPONENT_ALIAS_MAP = {
    "text": "单行输入",
    "string": "单行输入",
    "varchar": "单行输入",
    "input": "单行输入",
    "textarea": "多行输入",
    "longtext": "多行输入",
    "big_text": "多行输入",
    "number": "数字",
    "numeric": "数字",
    "int": "数字",
    "integer": "数字",
    "bigint": "数字",
    "decimal": "金额",
    "money": "金额",
    "amount": "金额",
    "date": "日期时间",
    "datetime": "日期时间",
    "timestamp": "日期时间",
    "dict": "下拉单选",
    "select": "下拉单选",
    "radio": "单选框",
    "checkbox": "复选框",
    "ref": "数据单选",
    "reference": "数据单选",
    "data": "数据单选",
    "file": "附件上传",
    "upload": "附件上传",
    "attachment": "附件上传",
    "user": "人员选择",
    "people": "人员选择",
    "person": "人员选择",
    "department": "部门选择",
    "dept": "部门选择",
    "boolean": "开关",
    "bool": "开关",
    "switch": "开关",
}

_DB_TYPE_ALIAS_MAP = {
    "varchar": "varchar",
    "char": "varchar",
    "string": "varchar",
    "text": "text",
    "longtext": "text",
    "clob": "text",
    "textarea": "text",
    "richtext": "text",
    "date": "date",
    "datetime": "datetime",
    "timestamp": "datetime",
    "decimal": "decimal",
    "numeric": "decimal",
    "float": "decimal",
    "double": "decimal",
    "money": "decimal",
    "amount": "decimal",
    "int": "int",
    "integer": "int",
    "smallint": "int",
    "tinyint": "int",
    "number": "int",
    "bigint": "bigint",
    "boolean": "int",
    "bool": "int",
    "单据号": "varchar",
    "单行输入": "varchar",
    "手机号码": "varchar",
    "电子邮箱": "varchar",
    "身份证号": "varchar",
    "超链接": "varchar",
    "下拉单选": "varchar",
    "下拉多选": "varchar",
    "单选框": "varchar",
    "复选框": "varchar",
    "数据单选": "varchar",
    "数据选择": "varchar",
    "关联表单": "varchar",
    "人员选择": "varchar",
    "部门选择": "varchar",
    "地理位置": "varchar",
    "地区地址": "varchar",
    "开关": "int",
    "多行输入": "text",
    "富文本": "text",
    "附件上传": "text",
    "日期时间": "datetime",
    "金额": "decimal",
    "数字": "int",
}

_PLATFORM_COMPONENT_ALIASES = {
    "FORM_TEXT_INPUT": "单行输入",
    "FORM_TEXTAREA_INPUT": "多行输入",
    "FORM_TEXTAREA": "多行输入",
    "FORM_RICH_TEXT": "富文本",
    "FORM_PHONE_INPUT": "手机号码",
    "FORM_PHONE": "手机号码",
    "FORM_EMAIL_INPUT": "电子邮箱",
    "FORM_EMAIL": "电子邮箱",
    "FORM_SELECT_INPUT_SINGLE": "下拉单选",
    "FORM_SELECT": "下拉单选",
    "FORM_SELECT_INPUT": "下拉多选",
    "FORM_SELECT_MULTI": "下拉多选",
    "FORM_RADIO_INPUT": "单选框",
    "FORM_RADIO": "单选框",
    "FORM_CHECKBOX_INPUT": "复选框",
    "FORM_CHECKBOX": "复选框",
    "FORM_DATA_SELECTOR_SINGLE": "数据单选",
    "FORM_DATA_SELECT": "数据单选",
    "FORM_DATA_SELECTOR": "数据选择",
    "FORM_DATEPICK_INPUT": "日期时间",
    "FORM_DATE_PICKER": "日期时间",
    "FORM_NUMBER_INPUT": "数字",
    "FORM_MONEY_INPUT": "金额",
    "FORM_FILE_UPLOAD": "附件上传",
    "FORM_UPLOAD": "附件上传",
    "FORM_SWITCH_SELECT": "开关",
    "FORM_SWITCH": "开关",
    "FORM_PEOPLE_SELECT": "人员选择",
    "FORM_USER_SELECT": "人员选择",
    "FORM_DEPARTMENT_SELECT": "部门选择",
    "FORM_DEPT_SELECT": "部门选择",
    "FORM_WIDGET_LOCATION": "地理位置",
    "FORM_LOCATION": "地理位置",
    "FORM_WIDGET_AREA": "地区地址",
    "FORM_ADDRESS": "地区地址",
    "FORM_WIDGET_SON_TABLE": "子表",
    "FORM_ASSOCIATION": "关联表单",
    "FORM_DOCUMENT_NUMBER": "单据号",
    "FORM_SERIAL": "单据号",
    "FORM_HYPERLINK_INPUT": "超链接",
    "FORM_LINK": "超链接",
    "FORM_IDCARD_INPUT": "身份证号",
    "FORM_ID_CARD": "身份证号",
}

_RESERVED_FIELD_CODES = {
    *_RESERVED,
    "department",
    "employee",
    "period",
    "trainer",
    "course",
    "certificate",
}


def _strip_db_suffix(value: str) -> str:
    return re.sub(r"\(.*\)", "", str(value or "")).strip()


def _snake(value: Any) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw).lower()
    raw = raw.replace("-", "_").replace(".", "_")
    raw = re.sub(r"[^a-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw


def _hash_suffix(value: Any, length: int = 6) -> str:
    return hashlib.md5(str(value or "").encode("utf-8")).hexdigest()[:length]


def normalize_component_type(value: Any, *, field_name: str = "", has_dict: bool = False, has_ref: bool = False) -> str:
    """Return a standard Chinese form component type."""
    raw = str(value or "").strip()
    if raw in get_valid_type_names():
        return raw
    aliases = get_type_aliases()
    if raw in aliases:
        return aliases[raw]
    if raw in _PLATFORM_COMPONENT_ALIASES:
        return _PLATFORM_COMPONENT_ALIASES[raw]

    key = _strip_db_suffix(raw).lower()
    name = str(field_name or "")
    if key in {"text", "string", "varchar", "input"}:
        if any(token in name for token in ("手机", "电话")):
            return "手机号码"
        if any(token in name for token in ("邮箱", "邮件", "Email", "email")):
            return "电子邮箱"
        if any(token in name for token in ("备注", "描述", "说明", "内容", "职责", "要求", "原因", "评价", "目标", "建议", "风险")):
            return "多行输入"
    if key in _COMPONENT_ALIAS_MAP:
        return _COMPONENT_ALIAS_MAP[key]

    if has_ref:
        return "数据单选"
    if has_dict:
        return "下拉单选"

    if any(token in name for token in ("日期", "时间")):
        return "日期时间"
    if any(token in name for token in ("金额", "价格", "费用")):
        return "金额"
    if any(token in name for token in ("人数", "数量", "评分", "次数", "分数")):
        return "数字"
    if any(token in name for token in ("备注", "描述", "说明", "内容", "职责", "要求", "原因")):
        return "多行输入"
    if any(token in name for token in ("部门",)):
        return "部门选择"
    if any(token in name for token in ("负责人", "人员", "员工", "经理", "上级", "讲师")):
        return "人员选择"
    if any(token in name for token in ("附件", "简历", "证书", "文件")):
        return "附件上传"
    return "单行输入"


def normalize_database_field_type(
    raw_db_type: Any = "",
    *,
    component_type: Any = "",
    field_name: str = "",
) -> str:
    """Return a valid standard DB storage type in lowercase."""
    for candidate in (raw_db_type, component_type):
        key = _strip_db_suffix(str(candidate or ""))
        if not key:
            continue
        lower = key.lower()
        if lower in _DB_TYPE_ALIAS_MAP:
            normalized = _DB_TYPE_ALIAS_MAP[lower]
            break
        if key in _DB_TYPE_ALIAS_MAP:
            normalized = _DB_TYPE_ALIAS_MAP[key]
            break
    else:
        normalized = ""

    if normalized == "int" and any(token in str(field_name or "") for token in ("金额", "价格", "费用", "评分", "比例", "百分比")):
        normalized = "decimal"

    if normalized in ALLOWED_DATABASE_FIELD_TYPES:
        return normalized

    comp = normalize_component_type(component_type or raw_db_type, field_name=field_name)
    return _DB_TYPE_ALIAS_MAP.get(comp, "varchar")


def safe_field_code(
    code: Any,
    *,
    model_code: str = "",
    field_name: str = "",
    used_codes: set[str] | None = None,
) -> str:
    """Return a platform-safe field code, avoiding SQL/platform reserved words."""
    used_codes = used_codes if used_codes is not None else set()
    base = _snake(code)
    if not base:
        base = f"field_{_hash_suffix(field_name)}"
    if not re.match(r"^[a-z]", base):
        base = f"f_{base}"

    candidate = base
    if candidate in _RESERVED_FIELD_CODES:
        prefix = _snake(model_code).removeprefix("t_") or "biz"
        candidate = f"{prefix}_{base}" if prefix else f"{base}_value"
    if candidate in _RESERVED_FIELD_CODES:
        candidate = f"{candidate}_value"

    candidate = candidate[:48].strip("_") or f"field_{_hash_suffix(field_name)}"
    if not re.match(r"^[a-z]", candidate):
        candidate = f"f_{candidate}"

    root = candidate
    index = 2
    while candidate in used_codes or candidate in _RESERVED_FIELD_CODES:
        suffix = f"_{index}"
        candidate = f"{root[:48 - len(suffix)]}{suffix}"
        index += 1

    used_codes.add(candidate)
    return candidate


def platform_component_type(component_type: str) -> str:
    comp_map = get_comp_type_map()
    return comp_map.get(component_type, "FORM_TEXT_INPUT")


_TRUE_VALUES = {"1", "true", "yes", "y", "是", "有", "启用", "显示", "必填", "查询", "列表展示"}
_FALSE_VALUES = {"0", "false", "no", "n", "否", "无", "禁用", "隐藏", "不显示", "非必填"}

_DEFAULT_LIST_EXCLUDED_COMPONENTS = {
    "FORM_TEXTAREA_INPUT",
    "FORM_RICH_TEXT",
    "FORM_FILE_UPLOAD",
    "FORM_UPLOAD",
    "FORM_WIDGET_SON_TABLE",
}
_DEFAULT_QUERY_COMPONENTS = {
    "FORM_TEXT_INPUT",
    "FORM_PHONE_INPUT",
    "FORM_EMAIL_INPUT",
    "FORM_SELECT_INPUT_SINGLE",
    "FORM_SELECT_INPUT",
    "FORM_RADIO_INPUT",
    "FORM_CHECKBOX_INPUT",
    "FORM_DATEPICK_INPUT",
    "FORM_DEPARTMENT_SELECT",
    "FORM_PEOPLE_SELECT",
    "FORM_DATA_SELECTOR_SINGLE",
    "FORM_DATA_SELECTOR",
}
_DEFAULT_QUERY_KEYWORDS = (
    "编号",
    "名称",
    "姓名",
    "标题",
    "状态",
    "类型",
    "等级",
    "部门",
    "负责人",
    "经理",
    "员工",
    "岗位",
    "日期",
    "时间",
    "手机",
    "电话",
    "邮箱",
    "name",
    "title",
    "status",
    "type",
    "level",
    "department",
    "dept",
    "date",
    "time",
    "phone",
    "email",
)


def _coerce_bool(value: Any, default: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip()
    if not text:
        return default
    lowered = text.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    return default


def _set_bool(component: dict[str, Any], key: str, value: bool) -> bool:
    current = _coerce_bool(component.get(key), default=None)
    if current is value and isinstance(component.get(key), bool):
        return False
    if key in component and current is not None:
        if component.get(key) != current:
            component[key] = current
            return True
        return False
    component[key] = value
    return True


def _has_meaningful_value(component: dict[str, Any], key: str) -> bool:
    if key not in component:
        return False
    value = component.get(key)
    return value is not None and str(value).strip() != ""


def _component_list(form: dict[str, Any]) -> list:
    for key in ("components", "formComponents", "fields"):
        value = form.get(key)
        if isinstance(value, list):
            return value
    return []


def _component_field_ref(
    component: dict[str, Any],
    *,
    default_model: str,
) -> tuple[str, str]:
    model_field = str(component.get("modelField") or component.get("model_field") or "").strip()
    model_code = default_model
    field_code = str(component.get("code") or component.get("field_code") or "").strip()
    if "." in model_field:
        model_code, field_code = model_field.split(".", 1)
    return model_code, field_code


def _default_show_in_list(component: dict[str, Any], *, component_type: str, used_count: int) -> bool:
    if used_count >= 5:
        return False
    if _coerce_bool(component.get("hidden"), default=False):
        return False
    if component_type in _DEFAULT_LIST_EXCLUDED_COMPONENTS:
        return False
    section_type = str(component.get("sectionType") or component.get("section_type") or "main").strip()
    return section_type != "sub"


def _default_searchable(
    component: dict[str, Any],
    *,
    component_type: str,
    field_code: str,
    field_name: str,
    show_in_list: bool,
    used_count: int,
) -> bool:
    if not show_in_list or used_count >= 4:
        return False
    if component_type not in _DEFAULT_QUERY_COMPONENTS:
        return False
    text = f"{field_code} {field_name}".lower()
    return any(token.lower() in text for token in _DEFAULT_QUERY_KEYWORDS)


def normalize_preview_config(config: dict[str, Any]) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    """Normalize a preview config in memory.

    Returns (normalized_config, changed, meta). The meta includes
    ``field_code_map``: {model_code: {old_code: new_code}}.
    """
    normalized = deepcopy(config)
    data = normalized.get("data", normalized) if isinstance(normalized, dict) else {}
    if not isinstance(data, dict):
        return normalized, False, {"field_code_map": {}}

    changed = False
    field_code_map: dict[str, dict[str, str]] = {}

    for model in data.get("models") or []:
        if not isinstance(model, dict):
            continue
        model_code = str(model.get("code") or model.get("modelCode") or "").strip()
        used_codes: set[str] = set()
        model_map: dict[str, str] = {}

        for field in model.get("fields") or []:
            if not isinstance(field, dict):
                continue
            old_code = str(field.get("code") or field.get("field_code") or "").strip()
            field_name = str(field.get("name") or field.get("fieldName") or field.get("field_name") or old_code).strip()
            new_code = safe_field_code(old_code, model_code=model_code, field_name=field_name, used_codes=used_codes)
            if old_code and old_code != new_code:
                model_map[old_code] = new_code
                field["code"] = new_code
                changed = True
            elif not old_code:
                field["code"] = new_code
                changed = True

            raw_type = field.get("type") or field.get("componentType") or field.get("fieldType")
            component = normalize_component_type(
                raw_type,
                field_name=field_name,
                has_dict=bool(field.get("dict") or field.get("dict_code") or field.get("dictionaryCode")),
                has_ref=bool(field.get("ref") or field.get("targetModelCode") or field.get("target_model_code")),
            )
            if field.get("type") != component:
                field["type"] = component
                changed = True

            explicit_db_type = field.get("database_field_type") or field.get("databaseFieldType") or field.get("db_type")
            db_type = normalize_database_field_type(
                explicit_db_type,
                component_type=component,
                field_name=field_name,
            )
            if field.get("database_field_type") != db_type:
                field["database_field_type"] = db_type
                changed = True
            if field.get("databaseFieldType") != db_type:
                field["databaseFieldType"] = db_type
                changed = True

        if model_map:
            field_code_map[model_code] = model_map

    if field_code_map:
        if _normalize_model_field_refs(data, field_code_map):
            changed = True
        for form in data.get("forms") or []:
            if isinstance(form, dict) and _normalize_form_fields(form, field_code_map):
                changed = True
    elif _normalize_model_field_refs(data, field_code_map):
        changed = True

    for form in data.get("forms") or []:
        if isinstance(form, dict) and _normalize_form_component_types(form, data):
            changed = True

    return normalized, changed, {"field_code_map": field_code_map}


def _normalize_model_field_refs(data: dict[str, Any], field_code_map: dict[str, dict[str, str]]) -> bool:
    changed = False
    model_field_codes: dict[str, set[str]] = {}
    model_field_names: dict[str, dict[str, str]] = {}
    for model in data.get("models") or []:
        if not isinstance(model, dict):
            continue
        model_code = str(model.get("code") or model.get("modelCode") or "").strip()
        if not model_code:
            continue
        codes: set[str] = set()
        names: dict[str, str] = {}
        for field in model.get("fields") or []:
            if not isinstance(field, dict):
                continue
            code = str(field.get("code") or field.get("field_code") or "").strip()
            name = str(field.get("name") or field.get("fieldName") or "").strip()
            if code:
                codes.add(code)
            if name and code:
                names[name] = code
        model_field_codes[model_code] = codes
        model_field_names[model_code] = names

    for model in data.get("models") or []:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if not isinstance(field, dict):
                continue
            ref = field.get("ref")
            if not isinstance(ref, dict):
                continue
            target_model = str(ref.get("model") or ref.get("target_model") or "").strip()
            target_field = str(
                ref.get("field") or ref.get("target_field") or ref.get("display_field") or ""
            ).strip()
            if not target_model or not target_field:
                continue
            replacement = field_code_map.get(target_model, {}).get(target_field)
            if not replacement and target_field not in model_field_codes.get(target_model, set()):
                replacement = model_field_names.get(target_model, {}).get(target_field, "")
            if not replacement and target_field not in model_field_codes.get(target_model, set()):
                candidate = safe_field_code(target_field, model_code=target_model, field_name=target_field, used_codes=set())
                if candidate in model_field_codes.get(target_model, set()):
                    replacement = candidate
            if replacement and replacement != target_field:
                for key in ("field", "target_field", "display_field"):
                    if key in ref or key == "field":
                        ref[key] = replacement
                changed = True
    return changed


def _normalize_form_fields(form: dict[str, Any], field_code_map: dict[str, dict[str, str]]) -> bool:
    changed = False
    default_model = str(form.get("modelCode") or form.get("model_code") or form.get("bindModelCode") or "").strip()
    for component in _component_list(form):
        if not isinstance(component, dict):
            continue
        for target in [component] + [
            col for col in (component.get("tableColumn") or []) if isinstance(col, dict)
        ]:
            model_code, field_code = _component_field_ref(target, default_model=default_model)
            replacement = field_code_map.get(model_code, {}).get(field_code)
            if not replacement:
                continue
            target["code"] = replacement
            target["field_code"] = replacement
            target["modelField"] = f"{model_code}.{replacement}"
            changed = True
    return changed


def _normalize_form_component_types(form: dict[str, Any], data: dict[str, Any]) -> bool:
    changed = False
    model_fields: dict[str, dict[str, dict[str, Any]]] = {}
    for model in data.get("models") or []:
        if not isinstance(model, dict):
            continue
        model_code = str(model.get("code") or "").strip()
        model_fields[model_code] = {
            str(field.get("code") or "").strip(): field
            for field in (model.get("fields") or [])
            if isinstance(field, dict)
        }

    default_model = str(form.get("modelCode") or form.get("model_code") or form.get("bindModelCode") or "").strip()
    list_count = 0
    query_count = 0

    for component in _component_list(form):
        if not isinstance(component, dict):
            continue
        targets = [component] + [
            col for col in (component.get("tableColumn") or []) if isinstance(col, dict)
        ]
        for target in targets:
            model_code, field_code = _component_field_ref(target, default_model=default_model)
            changed_component, show_in_list, searchable = _normalize_single_form_component(
                target,
                data=data,
                model_fields=model_fields,
                model_code=model_code,
                field_code=field_code,
                list_count=list_count,
                query_count=query_count,
            )
            if changed_component:
                changed = True
            if target is component:
                if show_in_list:
                    list_count += 1
                if searchable:
                    query_count += 1
    return changed


def _normalize_single_form_component(
    component: dict[str, Any],
    *,
    data: dict[str, Any],
    model_fields: dict[str, dict[str, dict[str, Any]]],
    model_code: str,
    field_code: str,
    list_count: int,
    query_count: int,
) -> tuple[bool, bool, bool]:
    changed = False
    field_meta = model_fields.get(model_code, {}).get(field_code, {})
    field_name = str(component.get("label") or component.get("name") or field_meta.get("name") or "").strip()
    field_dict = (
        component.get("dict")
        or component.get("dict_code")
        or component.get("dictCode")
        or component.get("dictionaryCode")
        or field_meta.get("dict")
        or field_meta.get("dict_code")
        or field_meta.get("dictCode")
        or field_meta.get("dictionaryCode")
    )
    if field_dict and component.get("dict") != field_dict:
        component["dict"] = field_dict
        changed = True
    if field_dict and component.get("dict_code") != field_dict:
        component["dict_code"] = field_dict
        changed = True
    if field_dict and component.get("dictCode") != field_dict:
        component["dictCode"] = field_dict
        changed = True
    field_ref = field_meta.get("ref")
    if isinstance(field_ref, dict) and not component.get("ref"):
        component["ref"] = deepcopy(field_ref)
        changed = True
    component_type = normalize_component_type(
        component.get("componentType") or component.get("component_type") or field_meta.get("type"),
        field_name=field_name,
        has_dict=bool(field_dict),
        has_ref=bool(component.get("ref") or field_meta.get("ref")),
    )
    platform_type = platform_component_type(component_type)
    if component.get("componentType") != platform_type:
        component["componentType"] = platform_type
        changed = True
    if component.get("type") != component_type:
        component["type"] = component_type
        changed = True
    if field_code and component.get("code") != field_code:
        component["code"] = field_code
        changed = True

    required_default = bool(_coerce_bool(field_meta.get("required"), default=False))
    changed = _set_bool(component, "hidden", False) or changed
    changed = _set_bool(component, "readonly", False) or changed
    changed = _set_bool(component, "required", required_default) or changed

    if _has_meaningful_value(component, "showInList"):
        changed = _set_bool(component, "showInList", False) or changed
    else:
        changed = _set_bool(
            component,
            "showInList",
            _default_show_in_list(component, component_type=platform_type, used_count=list_count),
        ) or changed
    show_in_list = bool(_coerce_bool(component.get("showInList"), default=False))

    if _has_meaningful_value(component, "searchable"):
        changed = _set_bool(component, "searchable", False) or changed
    else:
        changed = _set_bool(
            component,
            "searchable",
            _default_searchable(
                component,
                component_type=platform_type,
                field_code=field_code,
                field_name=field_name,
                show_in_list=show_in_list,
                used_count=query_count,
            ),
        ) or changed
    searchable = bool(_coerce_bool(component.get("searchable"), default=False))
    return changed, show_in_list, searchable
