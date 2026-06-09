"""
Convert AnalysisResult (from requirements generate-doc) → AppConfig (for builder/deploy).

This eliminates the need for the markdown roundtrip + LLM re-parse that was previously
required when handing off from RequirementsPage to ChatPage.
"""
from __future__ import annotations
import re
import logging
from typing import Any

from app.app_code import coerce_app_code
from app.field_types import get_comp_type_map
from app.lowcode_standards import normalize_database_field_type, safe_field_code

logger = logging.getLogger(__name__)

# ── Field type mapping ─────────────────────────────────────────────────────
# AnalysisResult uses DB types (VARCHAR, BIGINT, etc.) or platform types (单行输入, 日期, etc.)
# AppConfig expects platform field types only.

DB_TYPE_MAP: dict[str, str] = {
    "VARCHAR":   "单行输入",
    "CHAR":      "单行输入",
    "STRING":    "单行输入",
    "TEXT":      "多行输入",
    "LONGTEXT":  "富文本",
    "BIGINT":    "数字",
    "INT":       "数字",
    "INTEGER":   "数字",
    "SMALLINT":  "数字",
    "TINYINT":   "开关",
    "BOOLEAN":   "开关",
    "BOOL":      "开关",
    "DECIMAL":   "金额",
    "FLOAT":     "数字",
    "DOUBLE":    "数字",
    "DATE":      "日期时间",
    "DATETIME":  "日期时间",
    "TIMESTAMP": "日期时间",
}

# Chinese aliases → canonical platform type
ALIAS_TYPE_MAP: dict[str, str] = {
    "单行":      "单行输入",
    "文本":      "单行输入",
    "多行":      "多行输入",
    "文本域":    "多行输入",
    "日期":      "日期时间",
    "时间":      "日期时间",
    "金额":      "金额",
    "数字":      "数字",
    "整数":      "数字",
    "手机":      "手机号码",
    "手机号":    "手机号码",
    "电话":      "手机号码",
    "邮箱":      "电子邮箱",
    "邮件":      "电子邮箱",
    "附件":      "附件上传",
    "文件":      "附件上传",
    "图片":      "附件上传",
    "开关":      "开关",
    "布尔":      "开关",
    "下拉":      "下拉单选",
    "单选":      "下拉单选",
    "多选":      "下拉多选",
    "复选":      "复选框",
    "人员":      "人员选择",
    "部门":      "部门选择",
    "地址":      "地区地址",
    "位置":      "地理位置",
    "富文本":    "富文本",
    "链接":      "超链接",
    "身份证":    "身份证号",
    "子表":      "子表",
}

# All valid platform types
VALID_TYPES = {
    "单据号", "单行输入", "多行输入", "手机号码", "电子邮箱",
    "下拉单选", "下拉多选", "数据单选", "日期时间", "金额",
    "数字", "附件上传", "开关", "人员选择", "部门选择",
    "地理位置", "子表", "单选框", "复选框", "富文本",
    "超链接", "身份证号", "地区地址", "数据选择", "关联表单",
}

TYPE_ICON_MAP: dict[str, str] = {
    "单据号": "#", "单行输入": "T", "多行输入": "¶", "手机号码": "P",
    "电子邮箱": "@", "下拉单选": "▼", "下拉多选": "☰", "数据单选": "⇢",
    "日期时间": "D", "金额": "¥", "数字": "N", "附件上传": "⊕",
    "开关": "⊘", "人员选择": "⊙", "部门选择": "⊙", "地理位置": "◎",
    "子表": "▦", "单选框": "○", "复选框": "☑", "富文本": "R",
    "超链接": "🔗", "身份证号": "ID", "地区地址": "◎", "数据选择": "⇢",
    "关联表单": "≡",
}

# System/PK fields to skip (not needed in platform models)
SKIP_FIELDS = {"id", "created_at", "updated_at", "deleted_at", "created_by", "updated_by",
               "create_time", "update_time", "creator", "modifier", "tenant_id", "org_id"}

SELECT_FIELD_TYPES = {"下拉单选", "下拉多选", "单选框", "复选框"}
REFERENCE_FIELD_TYPES = {"数据单选", "数据选择", "关联表单"}
MULTI_SELECT_NAME_TOKENS = ("多选", "复选", "标签", "技能标签", "多个", "多值", "tags", "labels")
MULTI_SELECT_TYPE_TOKENS = ("下拉多选", "多选", "复选", "multi", "multiple", "checkbox", "array")
GENERIC_FORM_NAMES = {
    "", "表单", "测试表单", "新增表单", "编辑表单", "查看表单", "维护表单",
    "用户表", "用户信息表", "用户信息", "数据表", "业务表", "主表",
}
GENERIC_FORM_SUFFIXES = ("表单", "新增", "编辑", "查看", "维护")

COMP_TYPE_MAP = get_comp_type_map()

PLATFORM_TO_DB_TYPE_MAP: dict[str, str] = {
    "单据号": "VARCHAR",
    "单行输入": "VARCHAR",
    "多行输入": "TEXT",
    "富文本": "TEXT",
    "手机号码": "VARCHAR",
    "电子邮箱": "VARCHAR",
    "身份证号": "VARCHAR",
    "超链接": "VARCHAR",
    "下拉单选": "VARCHAR",
    "下拉多选": "VARCHAR",
    "单选框": "VARCHAR",
    "复选框": "VARCHAR",
    "数据单选": "VARCHAR",
    "数据选择": "VARCHAR",
    "关联表单": "VARCHAR",
    "日期时间": "DATETIME",
    "数字": "INT",
    "金额": "DECIMAL",
    "附件上传": "TEXT",
    "开关": "BOOLEAN",
    "人员选择": "VARCHAR",
    "部门选择": "VARCHAR",
    "地理位置": "VARCHAR",
    "地区地址": "VARCHAR",
    "子表": "",
}


def _normalize_type(raw_type: str, field_name: str = "", has_dict: bool = False) -> str:
    """Map a raw data_type string to a valid platform field type."""
    raw_text = str(raw_type or "").strip()

    name_based_type = _semantic_type_from_field_name(field_name)
    if name_based_type:
        return name_based_type
    if has_dict and raw_text and not _has_explicit_multi_select_signal(raw_text, field_name):
        return "下拉单选"
    if not raw_text:
        return "下拉单选" if has_dict else "单行输入"

    t = raw_text

    # Already a valid platform type
    if t in VALID_TYPES:
        return t

    # Check DB type map (uppercase)
    upper = t.upper()
    if upper in DB_TYPE_MAP:
        return DB_TYPE_MAP[upper]

    # Strip length suffix: VARCHAR(100) → VARCHAR
    base = re.sub(r'\(.*\)', '', t).strip().upper()
    if base in DB_TYPE_MAP:
        return DB_TYPE_MAP[base]

    # Check Chinese alias map
    for alias, canonical in ALIAS_TYPE_MAP.items():
        if alias in t:
            return canonical

    # Heuristic: if the field references a dict, it's likely a select
    if has_dict:
        return "下拉单选"

    # Heuristic: common field name patterns
    if name_based_type:
        return name_based_type

    # Fallback
    return "单行输入"


def _semantic_type_from_field_name(field_name: str) -> str:
    name_lower = str(field_name or "").lower()
    if any(k in name_lower for k in ("手机", "手机号", "联系电话", "电话", "phone", "mobile", "tel")):
        return "手机号码"
    if any(k in name_lower for k in ("邮箱", "邮件", "email", "mail")):
        return "电子邮箱"
    if any(k in name_lower for k in ("日期", "时间", "date", "time")):
        return "日期时间"
    if any(k in name_lower for k in ("金额", "价格", "费用", "amount", "price", "cost")):
        return "金额"
    if any(k in name_lower for k in ("备注", "描述", "说明", "remark", "desc", "note")):
        return "多行输入"
    return ""


def _has_explicit_multi_select_signal(raw_type: object, field_name: str = "") -> bool:
    text = f"{raw_type or ''} {field_name or ''}".lower()
    return any(token.lower() in text for token in (*MULTI_SELECT_TYPE_TOKENS, *MULTI_SELECT_NAME_TOKENS))


def _select_type_for_options(raw_type: object, field_name: str = "") -> str:
    return "下拉多选" if _has_explicit_multi_select_signal(raw_type, field_name) else "下拉单选"


def _split_option_text(text: str) -> list[str]:
    parts = re.split(r"[,，、/|;；\n]+", text or "")
    return [part.strip() for part in parts if part.strip()]


def _extract_field_options(field: dict[str, Any]) -> list[dict[str, str]]:
    raw_options = (
        field.get("options")
        or field.get("items")
        or field.get("enum_values")
        or field.get("enumValues")
        or field.get("values")
        or field.get("dict_options")
        or field.get("dictOptions")
        or []
    )
    if isinstance(raw_options, str):
        raw_options = _split_option_text(raw_options)
    if not isinstance(raw_options, list):
        return []

    options: list[dict[str, str]] = []
    for idx, raw in enumerate(raw_options, start=1):
        if isinstance(raw, str):
            name = raw.strip()
            code = _normalize_code(name) or f"option_{idx}"
        elif isinstance(raw, dict):
            name = str(
                raw.get("item_name")
                or raw.get("name")
                or raw.get("label")
                or raw.get("value")
                or ""
            ).strip()
            code = _normalize_code(str(
                raw.get("item_code")
                or raw.get("code")
                or raw.get("id")
                or name
            ))
        else:
            name = str(raw).strip()
            code = _normalize_code(name) or f"option_{idx}"
        if name:
            options.append({"name": name, "code": code or f"option_{idx}"})
    return options


def _is_generic_form_name(name: str, model_name: str, model_code: str) -> bool:
    text = str(name or "").strip()
    model_text = str(model_name or "").strip()
    if text in GENERIC_FORM_NAMES:
        return True
    if model_text in GENERIC_FORM_NAMES and text == model_text:
        return True
    if text == str(model_code or "").strip():
        return True
    if not text:
        return True
    if text in {"form", "new_form", "test_form"}:
        return True
    return False


def _dedupe_form_name(raw_name: str, model_name: str, model_code: str, used_names: set[str]) -> str:
    candidate = str(raw_name or "").strip()
    model_label = str(model_name or "").strip() or str(model_code or "").strip() or "业务对象"
    if _is_generic_form_name(candidate, model_label, model_code):
        if model_label in GENERIC_FORM_NAMES:
            model_label = str(model_code or "").strip() or "业务对象"
        candidate = f"{model_label}-新增表单"
    if candidate in used_names:
        if not any(candidate.endswith(suffix) for suffix in GENERIC_FORM_SUFFIXES):
            candidate = f"{model_label}-新增表单"
        base = candidate
        seq = 2
        while candidate in used_names:
            candidate = f"{base}-{seq}"
            seq += 1
    used_names.add(candidate)
    return candidate


def _copy_field_business_meta(source: dict[str, Any], target: dict[str, Any]) -> None:
    """Keep dict/ref/options metadata alive when a model field becomes a form component."""
    for key in (
        "dict", "dictCode", "dict_code", "dictionaryCode",
        "ref", "ref_model_code", "refModelCode", "ref_display_field_code", "refDisplayFieldCode",
        "target_model_code", "targetModelCode", "target_field_code", "targetFieldCode",
        "selector_form_code", "selectorFormCode", "selector_field_code", "selectorFieldCode",
        "association_form_code", "associationFormCode",
        "association_origin_field_code", "associationOriginFieldCode",
        "association_target_field_code", "associationTargetFieldCode",
        "options", "items", "enum_values", "enumValues", "dict_options", "dictOptions",
    ):
        if source.get(key) not in (None, ""):
            target[key] = source.get(key)
    dict_code = target.get("dict") or target.get("dictCode") or target.get("dict_code")
    if dict_code:
        target["dict"] = dict_code
        target["dict_code"] = dict_code
        if str(target.get("componentType") or "") in {
            "FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT", "FORM_RADIO_INPUT", "FORM_CHECKBOX_INPUT",
        }:
            target["dictionarySelectConfig"] = {
                "dictionaryCode": dict_code,
                "dictionarySelectOptions": [],
            }
    ref = target.get("ref")
    if isinstance(ref, dict):
        target["ref_model_code"] = target.get("ref_model_code") or ref.get("model") or ref.get("target_model")
        target["ref_display_field_code"] = (
            target.get("ref_display_field_code")
            or ref.get("field")
            or ref.get("display_field")
            or ref.get("target_field")
        )


def _compact_business_name(name: str) -> str:
    text = str(name or "").strip().lower()
    text = re.sub(r"^t_", "", text)
    text = re.sub(r"(_?(info|profile|archive|record|records|table|form|apply|application|detail|details))$", "", text)
    text = re.sub(r"(档案|信息|资料|管理|台账|记录|表单|表|申请|明细)$", "", text)
    return text.strip("_- ")


def _table_display_field(table: dict[str, Any]) -> str:
    fields = [field for field in table.get("fields", []) or [] if isinstance(field, dict)]
    preferred_name_tokens = ("名称", "姓名", "标题", "编号", "编码", "name", "title", "no", "code")
    for token in preferred_name_tokens:
        for field in fields:
            field_code = _normalize_code(str(field.get("field_code") or ""))
            field_name = str(field.get("field_name") or "")
            if not field_code or field_code in SKIP_FIELDS or field.get("is_pk"):
                continue
            haystack = f"{field_code} {field_name}".lower()
            if token.lower() in haystack:
                return field_code
    for field in fields:
        field_code = _normalize_code(str(field.get("field_code") or ""))
        if field_code and field_code not in SKIP_FIELDS and not field.get("is_pk"):
            return field_code
    return ""


def _build_reference_candidates(tables_raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for table in tables_raw:
        if not isinstance(table, dict):
            continue
        table_type = str(table.get("table_type", "主表")).strip().lower()
        if table_type in {"子表", "sub", "child"}:
            continue
        code = _normalize_code(str(table.get("table_code") or ""))
        name = str(table.get("table_name") or "").strip()
        if not code or not name:
            continue
        aliases = {
            code,
            code.removeprefix("t_"),
            name,
            _compact_business_name(code),
            _compact_business_name(name),
        }
        candidates.append({
            "code": code,
            "name": name,
            "display_field": _table_display_field(table),
            "aliases": "|".join(alias for alias in aliases if alias),
        })
    return candidates


def _infer_reference_target(
    *,
    field_code: str,
    field_name: str,
    current_model_code: str,
    reference_candidates: list[dict[str, str]],
) -> dict[str, str] | None:
    haystack = f"{field_code} {field_name}".lower()
    for candidate in reference_candidates:
        target_code = candidate["code"]
        if target_code == current_model_code:
            continue
        aliases = [alias for alias in candidate.get("aliases", "").split("|") if alias]
        for alias in aliases:
            alias_l = alias.lower()
            if not alias_l or len(alias_l) < 2:
                continue
            if alias_l in haystack:
                return candidate
    return None


def _normalize_database_field_type(raw_db_type: str, platform_field_type: str) -> str:
    return normalize_database_field_type(raw_db_type, component_type=platform_field_type)


def _normalize_code(code: str) -> str:
    """Ensure code is lowercase alphanumeric with underscores."""
    if not code:
        return ""
    return re.sub(r'[^a-z0-9_]', '_', code.lower()).strip('_')


def _data_scope_to_app(scope: str) -> str:
    """Convert AnalysisResult data_scope to AppConfig data format."""
    mapping = {
        "self":    "SELF",
        "仅本人":  "SELF",
        "dept":    "CURRENT_USER_DEPT",
        "本部门":  "CURRENT_USER_DEPT",
        "all":     "ALL",
        "全公司":  "ALL",
        "全部":    "ALL",
        "none":    "SELF",
        "custom":  "CURRENT_USER_DEPT_LOW_LEVEL",
        "自定义":  "CURRENT_USER_DEPT_LOW_LEVEL",
    }
    return mapping.get(scope.lower() if scope else "self", "SELF")


def _ops_to_op(operations: list[str]) -> str:
    """Convert a list of operations to a single op value."""
    if not operations:
        return "view"
    # If many operations, treat as "all"
    critical = {"新增", "编辑", "删除", "查看"}
    has = set(operations) & critical
    if len(has) >= 3:
        return "all"
    if "新增" in operations and "编辑" in operations:
        return "all"
    if "编辑" in operations:
        return "edit"
    if "新增" in operations:
        return "add"
    if "删除" in operations:
        return "delete"
    return "view"


def _field_type_to_component_type(field_type: str) -> str:
    return COMP_TYPE_MAP.get(str(field_type or "").strip(), "FORM_TEXT_INPUT")


def _build_forms_from_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    forms: list[dict[str, Any]] = []
    used_form_names: set[str] = set()
    for idx, model in enumerate(models):
        if str(model.get("table_type", model.get("type", ""))).strip().lower() in {"子表", "sub", "child"}:
            continue
        model_code = model.get("code", f"model_{idx + 1}")
        form_code = model.get("form_code") or model.get("code", f"form_{idx + 1}")
        form_name = _dedupe_form_name(
            model.get("form_name") or model.get("name") or form_code,
            model.get("name", ""),
            model_code,
            used_form_names,
        )
        components: list[dict[str, Any]] = []

        for field_idx, field in enumerate(model.get("fields", []) or []):
            field_code = field.get("code", f"field_{field_idx + 1}")
            field_name = field.get("name", field_code)
            field_type = field.get("type", "单行输入")
            component_type = _field_type_to_component_type(field_type)

            if component_type == "FORM_WIDGET_SON_TABLE":
                sub_code = field.get("sub_code", field_code)
                table_columns = []
                for sub_idx, sub_field in enumerate(field.get("sub_fields", []) or []):
                    sub_field_code = sub_field.get("code", f"sub_field_{sub_idx + 1}")
                    sub_field_name = sub_field.get("name", sub_field_code)
                    sub_field_type = sub_field.get("type", "单行输入")
                    sub_component = {
                        "label": sub_field_name,
                        "componentType": _field_type_to_component_type(sub_field_type),
                        "modelField": f"{sub_code}.{sub_field_code}",
                        "required": bool(sub_field.get("required", False)),
                    }
                    _copy_field_business_meta(sub_field, sub_component)
                    table_columns.append(sub_component)
                components.append({
                    "label": field_name,
                    "componentType": component_type,
                    "tableModelCode": sub_code,
                    "tableColumn": table_columns,
                    "required": bool(field.get("required", False)),
                })
                continue

            component = {
                "label": field_name,
                "componentType": component_type,
                "modelField": f"{model_code}.{field_code}",
                "required": bool(field.get("required", False)),
            }
            if field.get("dict"):
                component["dict"] = field.get("dict")
                component["dict_code"] = field.get("dict")
            if field.get("ref"):
                component["ref"] = field.get("ref")
                if isinstance(field.get("ref"), dict):
                    component["ref_model_code"] = field["ref"].get("model")
                    component["ref_display_field_code"] = field["ref"].get("field")
            _copy_field_business_meta(field, component)
            components.append(component)

        forms.append({
            "name": form_name,
            "code": form_code,
            "formName": form_name,
            "formCode": form_code,
            "modelCode": model_code,
            "_auto_generated_from_model": True,
            "components": components,
        })
    return forms


def convert_analysis_to_app_config(doc_result: dict[str, Any]) -> dict[str, Any]:
    """
    Convert AnalysisResult (from requirements generate-doc) to AppConfig
    (for ChatPage builder / deploy).

    Pure Python transformation — no LLM calls.
    """
    app_info = doc_result.get("app_info", {})
    roles_raw = doc_result.get("roles", [])
    dicts_raw = doc_result.get("data_dictionary", [])
    tables_raw = doc_result.get("tables", [])
    flows_raw = doc_result.get("workflows") or doc_result.get("flows", [])
    mappings_raw = doc_result.get("role_table_mapping", [])

    # ── appName & appCode ──
    app_name = app_info.get("name", "新应用")
    app_code = coerce_app_code(app_info.get("code"), fallback="app-builder")

    # ── roles ──
    roles = []
    for r in roles_raw:
        code = _normalize_code(r.get("role_code", ""))
        name = r.get("role_name", "")
        if code and name:
            roles.append({"name": name, "code": code})

    # ── dicts ──
    dicts = []
    for d in dicts_raw:
        code = _normalize_code(d.get("dict_code", ""))
        name = d.get("dict_name", "")
        if not code or not name:
            continue
        options = []
        for item in d.get("items", []):
            opt_code = _normalize_code(item.get("item_code", ""))
            opt_name = item.get("item_name", "")
            if opt_name:
                if not opt_code:
                    opt_code = _normalize_code(opt_name)
                options.append({"name": opt_name, "code": opt_code})
        dicts.append({"name": name, "code": code, "options": options})

    # Build a map from dict_code → dict for field lookup
    dict_by_code = {d["code"]: d for d in dicts}
    dict_codes = set(dict_by_code.keys())
    reference_candidates = _build_reference_candidates(tables_raw)

    def ensure_field_dict(table_code: str, field_code: str, field_name: str, options: list[dict[str, str]]) -> str | None:
        if not options:
            return None
        base_code = _normalize_code(f"{table_code}_{field_code}_dict") or _normalize_code(f"{field_code}_dict")
        dict_code = base_code
        seq = 2
        while dict_code in dict_by_code:
            # Reuse an existing synthesized dict for the same field when possible.
            existing = dict_by_code[dict_code]
            if existing.get("options") == options:
                return dict_code
            dict_code = f"{base_code}_{seq}"
            seq += 1
        dict_name = f"{field_name}选项"
        dict_item = {"name": dict_name, "code": dict_code, "options": options}
        dicts.append(dict_item)
        dict_by_code[dict_code] = dict_item
        dict_codes.add(dict_code)
        return dict_code

    # ── models (from tables) ──
    models = []
    # Track subtable codes for linking
    subtable_map: dict[str, list[dict]] = {}  # parent_code → [subtable_fields_info]

    # First pass: collect all tables
    for t in tables_raw:
        t_code = _normalize_code(t.get("table_code", ""))
        t_name = t.get("table_name", "")
        t_type = t.get("table_type", "主表")
        parent = _normalize_code(t.get("parent_table", ""))

        if not t_code or not t_name:
            continue

        fields = []
        for f in t.get("fields", []):
            f_code = _normalize_code(f.get("field_code", ""))
            f_name = f.get("field_name", "")

            # Skip system fields
            if f_code in SKIP_FIELDS or f.get("is_pk"):
                continue
            if not f_code or not f_name:
                continue
            f_code = safe_field_code(f_code, model_code=t_code, field_name=f_name, used_codes={field.get("code", "") for field in fields})

            raw_type = f.get("data_type", "")
            raw_db_type = f.get("database_field_type") or f.get("databaseFieldType") or raw_type
            raw_length = f.get("length") or f.get("max_length") or f.get("maxLength") or ""
            desc = f.get("description", "")
            field_options = _extract_field_options(f)

            # Check if this field references a dict
            raw_field_dict = (
                f.get("dict")
                or f.get("dict_code")
                or f.get("dictCode")
                or f.get("dictionary_code")
                or f.get("dictionaryCode")
            )
            field_dict = _normalize_code(str(raw_field_dict or ""))
            if field_dict and field_dict not in dict_by_code:
                field_dict = None
            for dc in dict_codes:
                if not field_dict and dc and (dc in f_code or dc in desc.lower()):
                    field_dict = dc
                    break

            # Infer dict from description hints
            if not field_dict and ("字典" in desc or "枚举" in desc or "选项" in desc):
                # Try to match by field name
                for dc, d_obj in dict_by_code.items():
                    if d_obj["name"] in f_name or f_name in d_obj["name"]:
                        field_dict = dc
                        break

            has_dict = bool(field_dict)
            field_type = _normalize_type(raw_type, f_name, has_dict)

            if field_options and field_type not in REFERENCE_FIELD_TYPES:
                field_type = _select_type_for_options(raw_type, f_name)
                if not field_dict:
                    field_dict = ensure_field_dict(t_code, f_code, f_name, field_options)
                    has_dict = bool(field_dict)

            # If type is select-like but no dict, try to find one
            if field_type in SELECT_FIELD_TYPES and not field_dict:
                # Try matching by field code/name
                for dc, d_obj in dict_by_code.items():
                    if dc in f_code or d_obj["name"] in f_name:
                        field_dict = dc
                        break

            reference_target = None
            raw_ref = f.get("ref") or f.get("reference") or {}
            if isinstance(raw_ref, dict):
                target_model = _normalize_code(str(
                    raw_ref.get("model")
                    or raw_ref.get("target_model")
                    or raw_ref.get("targetModelCode")
                    or ""
                ))
                if target_model:
                    reference_target = next((item for item in reference_candidates if item["code"] == target_model), None)
            if not reference_target:
                reference_target = _infer_reference_target(
                    field_code=f_code,
                    field_name=f_name,
                    current_model_code=t_code,
                    reference_candidates=reference_candidates,
                )
            if reference_target:
                field_type = "数据单选"
                field_dict = None
            elif field_type == "单行输入":
                if any(token in f_name for token in ("申请人", "负责人", "经办人", "审批人", "员工", "人员")):
                    field_type = "人员选择"
                elif "部门" in f_name:
                    field_type = "部门选择"

            field_entry: dict[str, Any] = {
                "name": f_name,
                "code": f_code,
                "type": field_type,
                "database_field_type": _normalize_database_field_type(raw_db_type, field_type),
                "databaseFieldType": _normalize_database_field_type(raw_db_type, field_type),
                "icon": TYPE_ICON_MAP.get(field_type, "T"),
                "required": not f.get("nullable", True),
            }
            if raw_length not in (None, ""):
                field_entry["length"] = str(raw_length)
                field_entry["max_length"] = str(raw_length)
                field_entry["maxLength"] = str(raw_length)

            if field_dict:
                field_entry["dict"] = field_dict
                # Ensure type is select-like
                if field_type not in SELECT_FIELD_TYPES:
                    field_entry["type"] = "下拉单选"
                    field_entry["icon"] = "▼"
            if reference_target:
                field_entry["ref"] = {
                    "model": reference_target["code"],
                    "field": reference_target.get("display_field") or "",
                }
                field_entry["target_model_code"] = reference_target["code"]
                field_entry["target_field_code"] = reference_target.get("display_field") or ""

            fields.append(field_entry)

        if t_type == "子表" and parent:
            subtable_map.setdefault(parent, []).append({
                "code": t_code,
                "name": t_name,
                "fields": fields,
            })
        else:
            models.append({
                "name": t_name,
                "code": t_code,
                "form_name": t.get("form_name") or t.get("formName"),
                "form_code": _normalize_code(str(t.get("form_code") or t.get("formCode") or "")) or None,
                "fields": fields,
                "_subtables": [],  # will be filled in second pass
            })

    # Second pass: link subtables to parent models
    model_by_code = {m["code"]: m for m in models}
    for parent_code, subs in subtable_map.items():
        parent_model = model_by_code.get(parent_code)
        if parent_model:
            for sub in subs:
                # Add a subtable field to the parent model
                parent_model["fields"].append({
                    "name": sub["name"],
                    "code": sub["code"],
                    "type": "子表",
                    "icon": "▦",
                    "required": False,
                    "sub_code": sub["code"],
                    "sub_fields": sub["fields"],
                })

    # Clean up internal fields
    for m in models:
        m.pop("_subtables", None)

    # ── workflows (from flows/workflows) ──
    workflows = []
    # Build role name → code map
    role_name_to_code = {}
    for r in roles_raw:
        role_name_to_code[r.get("role_name", "")] = _normalize_code(r.get("role_code", ""))

    model_form_refs = []
    for m in models:
        model_form_refs.append({
            "model_name": str(m.get("name") or "").strip(),
            "model_code": str(m.get("code") or "").strip(),
            "form_name": str(m.get("form_name") or m.get("name") or "").strip(),
            "form_code": str(m.get("form_code") or m.get("code") or "").strip(),
        })

    def _resolve_flow_form_code(flow: dict[str, Any], flow_name: str) -> str:
        explicit_raw = str(
            flow.get("form_code")
            or flow.get("formCode")
            or flow.get("form")
            or flow.get("form_name")
            or flow.get("formName")
            or ""
        ).strip()
        explicit = _normalize_code(explicit_raw)
        if explicit_raw:
            for ref in model_form_refs:
                if explicit_raw in {ref["form_name"], ref["model_name"], ref["form_code"], ref["model_code"]}:
                    return ref["form_code"]
        if explicit:
            for ref in model_form_refs:
                if explicit in {ref["form_code"], _normalize_code(ref["form_name"]), ref["model_code"], _normalize_code(ref["model_name"])}:
                    return ref["form_code"]
            return explicit
        for ref in model_form_refs:
            labels = [ref["form_name"], ref["model_name"], ref["form_code"], ref["model_code"]]
            if any(label and (label in flow_name or flow_name in label) for label in labels):
                return ref["form_code"]
        return model_form_refs[0]["form_code"] if model_form_refs else ""

    def _normalize_workflow_nodes(flow: dict[str, Any]) -> list[dict[str, str]]:
        nodes: list[dict[str, str]] = []
        raw_nodes = flow.get("nodes")
        if isinstance(raw_nodes, list) and raw_nodes:
            for node in raw_nodes:
                if not isinstance(node, dict):
                    continue
                node_type = str(node.get("type") or "").strip().lower()
                if node_type in {"start", "end"}:
                    continue
                node_name = str(node.get("name") or node.get("node_name") or node.get("action") or "审批").strip()
                role_raw = str(node.get("role_code") or node.get("roleCode") or node.get("role") or "").strip()
                role_code = role_name_to_code.get(role_raw, _normalize_code(role_raw))
                if role_code:
                    nodes.append({"name": node_name[:20], "role_code": role_code})
            return nodes

        for step in flow.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            role_name = str(step.get("role") or step.get("role_name") or step.get("roleName") or "").strip()
            role_code = role_name_to_code.get(role_name, _normalize_code(role_name))
            action = str(step.get("action") or step.get("name") or step.get("step_name") or "审批").strip()
            if role_code and ("审批" in action or "审核" in action or "确认" in action):
                nodes.append({"name": action[:20], "role_code": role_code})
        return nodes

    for flow in flows_raw:
        if not isinstance(flow, dict):
            continue
        flow_name = str(flow.get("name") or flow.get("flow_name") or flow.get("flowName") or "").strip()
        if not flow_name:
            continue
        form_code = _resolve_flow_form_code(flow, flow_name)
        nodes = _normalize_workflow_nodes(flow)
        if form_code and nodes:
            workflows.append({
                "name": flow_name,
                "form_code": form_code,
                "nodes": nodes,
            })

    # ── permissions (from role_table_mapping) ──
    permissions = []
    table_code_to_name = {_normalize_code(t.get("table_code", "")): t.get("table_name", "") for t in tables_raw}

    for mapping in mappings_raw:
        t_code = _normalize_code(mapping.get("table_code", ""))
        t_name = mapping.get("table_name", "") or table_code_to_name.get(t_code, "")
        if not t_name:
            continue

        rules = []
        for perm in mapping.get("permissions", []):
            role_code = _normalize_code(perm.get("role_code", ""))
            ops = perm.get("operations", [])
            scope = perm.get("data_scope", "none")

            if not role_code:
                continue

            # all_employee → "all" special role
            if role_code == "all_employee":
                role_code = "all"

            op = _ops_to_op(ops)
            data = _data_scope_to_app(scope)

            if op != "view" or data != "SELF":  # Skip no-op rules
                rules.append({
                    "role": role_code,
                    "op": op,
                    "data": data,
                })

        if rules:
            permissions.append({
                "form": t_name,
                "rules": rules,
            })

    return {
        "appName": app_name,
        "appCode": app_code,
        "roles": roles,
        "dicts": dicts,
        "models": models,
        "forms": _build_forms_from_models(models),
        "flows": flows_raw,
        "workflows": workflows,
        "permissions": permissions,
    }
