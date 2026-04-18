"""
Convert AnalysisResult (from requirements generate-doc) → AppConfig (for builder/deploy).

This eliminates the need for the markdown roundtrip + LLM re-parse that was previously
required when handing off from RequirementsPage to ChatPage.
"""
from __future__ import annotations
import re
import logging
from typing import Any

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
    if not raw_type:
        return "单行输入"

    t = raw_type.strip()

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
    name_lower = field_name.lower()
    if any(k in name_lower for k in ("日期", "时间", "date", "time")):
        return "日期时间"
    if any(k in name_lower for k in ("金额", "价格", "费用", "amount", "price", "cost")):
        return "金额"
    if any(k in name_lower for k in ("手机", "电话", "phone")):
        return "手机号码"
    if any(k in name_lower for k in ("邮箱", "email")):
        return "电子邮箱"
    if any(k in name_lower for k in ("备注", "描述", "说明", "remark", "desc", "note")):
        return "多行输入"

    # Fallback
    return "单行输入"


def _normalize_database_field_type(raw_db_type: str, platform_field_type: str) -> str:
    raw = str(raw_db_type or "").strip()
    if raw:
        upper = re.sub(r"\(.*\)", "", raw).strip().upper()
        return upper or raw
    return PLATFORM_TO_DB_TYPE_MAP.get(platform_field_type, "VARCHAR")


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
    mapping = {
        "单行输入": "FORM_TEXT_INPUT",
        "多行输入": "FORM_TEXTAREA",
        "富文本": "FORM_RICH_TEXT",
        "日期时间": "FORM_DATE_PICKER",
        "金额": "FORM_NUMBER_INPUT",
        "数字": "FORM_NUMBER_INPUT",
        "下拉单选": "FORM_SELECT",
        "下拉多选": "FORM_SELECT_MULTI",
        "单选框": "FORM_RADIO",
        "复选框": "FORM_CHECKBOX",
        "人员选择": "FORM_USER_SELECT",
        "部门选择": "FORM_DEPT_SELECT",
        "附件上传": "FORM_UPLOAD",
        "开关": "FORM_SWITCH",
        "单据号": "FORM_SERIAL",
        "数据选择": "FORM_DATA_SELECT",
        "关联表单": "FORM_DATA_SELECT",
        "地理位置": "FORM_LOCATION",
        "地区地址": "FORM_ADDRESS",
        "手机号码": "FORM_PHONE",
        "电子邮箱": "FORM_EMAIL",
        "超链接": "FORM_LINK",
        "身份证号": "FORM_ID_CARD",
        "子表": "FORM_WIDGET_SON_TABLE",
    }
    return mapping.get(str(field_type or "").strip(), "FORM_TEXT_INPUT")


def _build_forms_from_models(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    forms: list[dict[str, Any]] = []
    for idx, model in enumerate(models):
        if str(model.get("table_type", model.get("type", ""))).strip().lower() in {"子表", "sub", "child"}:
            continue
        model_code = model.get("code", f"model_{idx + 1}")
        form_code = model.get("form_code", model.get("code", f"form_{idx + 1}"))
        form_name = model.get("form_name", model.get("name", form_code))
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
                    table_columns.append({
                        "label": sub_field_name,
                        "componentType": _field_type_to_component_type(sub_field_type),
                        "modelField": f"{sub_code}.{sub_field_code}",
                        "required": bool(sub_field.get("required", False)),
                    })
                components.append({
                    "label": field_name,
                    "componentType": component_type,
                    "tableModelCode": sub_code,
                    "tableColumn": table_columns,
                    "required": bool(field.get("required", False)),
                })
                continue

            components.append({
                "label": field_name,
                "componentType": component_type,
                "modelField": f"{model_code}.{field_code}",
                "required": bool(field.get("required", False)),
            })

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
    flows_raw = doc_result.get("flows", [])
    mappings_raw = doc_result.get("role_table_mapping", [])

    # Build dict code set for field type inference
    dict_codes = {d.get("dict_code", "") for d in dicts_raw}

    # ── appName & appCode ──
    app_name = app_info.get("name", "新应用")
    app_code = _normalize_code(app_info.get("code", "app"))

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

            raw_type = f.get("data_type", "")
            raw_db_type = f.get("database_field_type") or f.get("databaseFieldType") or raw_type
            raw_length = f.get("length") or f.get("max_length") or f.get("maxLength") or ""
            desc = f.get("description", "")

            # Check if this field references a dict
            field_dict = None
            for dc in dict_codes:
                if dc and (dc in f_code or dc in desc.lower()):
                    field_dict = dc
                    break

            # Infer dict from description hints
            if not field_dict and ("字典" in desc or "枚举" in desc or "选项" in desc):
                # Try to match by field name
                for dc, d_obj in dict_by_code.items():
                    if d_obj["name"] in f_name or f_name in d_obj["name"]:
                        field_dict = dc
                        break

            has_dict = field_dict is not None
            field_type = _normalize_type(raw_type, f_name, has_dict)

            # If type is select-like but no dict, try to find one
            if field_type in ("下拉单选", "下拉多选", "单选框", "复选框") and not field_dict:
                # Try matching by field code/name
                for dc, d_obj in dict_by_code.items():
                    if dc in f_code or d_obj["name"] in f_name:
                        field_dict = dc
                        break

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
                if field_type not in ("下拉单选", "下拉多选", "单选框", "复选框"):
                    field_entry["type"] = "下拉单选"
                    field_entry["icon"] = "▼"

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

    # ── workflows (from flows) ──
    workflows = []
    # Build role name → code map
    role_name_to_code = {}
    for r in roles_raw:
        role_name_to_code[r.get("role_name", "")] = _normalize_code(r.get("role_code", ""))

    for flow in flows_raw:
        flow_name = flow.get("flow_name", "")
        steps = flow.get("steps", [])
        if not flow_name or not steps:
            continue

        # Try to match flow to a form/model
        form_name = ""
        for m in models:
            if m["name"] in flow_name or flow_name in m["name"]:
                form_name = m["name"]
                break
        if not form_name and models:
            form_name = models[0]["name"]

        nodes = [{"name": "发起申请", "role": "", "type": "start"}]
        for step in steps:
            role_name = step.get("role", "")
            role_code = role_name_to_code.get(role_name, _normalize_code(role_name))
            action = step.get("action", "")
            if "审批" in action or "审核" in action:
                nodes.append({
                    "name": action[:20],
                    "role": role_code,
                    "type": "approve",
                })
        nodes.append({"name": "结束", "role": "", "type": "end"})

        # Only add if there are actual approval nodes
        if len(nodes) > 2:
            workflows.append({
                "name": flow_name,
                "form": form_name,
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
        "workflows": workflows,
        "permissions": permissions,
    }
