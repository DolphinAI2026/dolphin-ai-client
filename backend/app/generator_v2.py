"""aPaaS 应用生成器

执行流程:
  Phase 0  解析配置
  Phase 1  创建公共资源（角色 + 数据字典）
  Phase 2  创建数据模型
  Phase 3  创建表单 + 绑定字典
  Phase 4  配置权限
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import string
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from app.apaas_client import APaaSClient
from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _rand(n: int = 4) -> str:
    """根据配置决定是否生成随机后缀"""
    if settings.enable_code_suffix:
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))
    return ""


def _apply_suffix(code: str, suffix: str) -> str:
    """为编码添加后缀（如果有）"""
    if suffix:
        return f"{code}_{suffix}"
    return code


def _sanitize_code(code: str) -> str:
    """确保 code 纯 ASCII、字母开头、无保留字冲突"""
    if not code:
        return f"c{_rand(6)}"
    c = re.sub(r"[^a-zA-Z0-9_]", "", code)
    if len(c) < 2:
        c = "c" + hashlib.md5(code.encode()).hexdigest()[:7]
    if c[0].isdigit():
        c = "f_" + c
    return c.lower()


_RESERVED = {
    # SQL 关键字（MySQL + PostgreSQL + 通用 SQL）
    "add", "all", "alter", "and", "any", "as", "asc", "between", "by",
    "call", "case", "check", "column", "constraint", "create", "cross",
    "current", "database", "default", "delete", "desc", "describe",
    "distinct", "drop", "each", "else", "end", "escape", "exists",
    "explain", "false", "for", "foreign", "from", "full", "function",
    "grant", "group", "having", "if", "in", "index", "inner", "insert",
    "into", "is", "join", "key", "left", "like", "limit", "lock",
    "not", "null", "offset", "on", "or", "order", "outer", "primary",
    "procedure", "references", "replace", "return", "revoke", "right",
    "rollback", "row", "rows", "schema", "select", "set", "show",
    "table", "then", "to", "trigger", "true", "union", "unique",
    "unlock", "update", "use", "using", "values", "view", "when",
    "where", "with",
    # SQL 函数 / 聚合
    "avg", "count", "max", "min", "sum", "rank", "abs", "cast",
    "coalesce", "convert", "extract", "length", "lower", "upper",
    "trim", "substring", "position",
    # MySQL 特有保留字
    "accessible", "analyze", "asensitive", "before", "bigint", "binary",
    "blob", "both", "cascade", "change", "char", "character", "collate",
    "condition", "continue", "databases", "day_hour", "day_microsecond",
    "day_minute", "day_second", "dec", "decimal", "declare", "delayed",
    "deterministic", "div", "double", "dual", "elseif", "enclosed",
    "escaped", "exit", "fetch", "float", "float4", "float8", "force",
    "fulltext", "generated", "get", "grouping", "groups", "high_priority",
    "hour_microsecond", "hour_minute", "hour_second", "ignore", "infile",
    "int", "int1", "int2", "int3", "int4", "int8", "integer", "interval",
    "iterate", "keys", "kill", "leading", "leave", "linear", "lines",
    "load", "localtime", "localtimestamp", "long", "longblob", "longtext",
    "loop", "low_priority", "master_bind", "master_ssl_verify_server_cert",
    "match", "maxvalue", "mediumblob", "mediumint", "mediumtext",
    "middleint", "minute_microsecond", "minute_second", "mod", "modifies",
    "natural", "no_write_to_binlog", "numeric", "optimize", "optimizer_costs",
    "option", "optionally", "out", "outfile", "partition", "precision",
    "purge", "range", "read", "reads", "real", "recursive", "regexp",
    "release", "rename", "repeat", "require", "resignal", "restrict",
    "rlike", "second_microsecond", "sensitive", "separator", "signal",
    "smallint", "spatial", "specific", "sql", "sqlexception", "sqlstate",
    "sqlwarning", "ssl", "straight_join", "stored", "system",
    "terminated", "text", "tinyblob", "tinyint", "tinytext", "trailing",
    "undo", "unsigned", "usage", "utc_date", "utc_time", "utc_timestamp",
    "varbinary", "varchar", "varcharacter", "varying", "virtual",
    "while", "window", "write", "xor", "year_month", "zerofill",
    # 常见短名 / 业务名（平台可能保留）
    "id", "no", "name", "type", "status", "state", "value", "data",
    "code", "date", "time", "timestamp", "number", "level", "action",
    "result", "role", "user", "label", "field", "fields", "file",
    "size", "start", "stop", "open", "close", "source", "scope",
    "method", "language", "comment", "location", "email", "phone",
    "address", "account", "model", "unit", "category", "manager",
    "priority", "amount", "currency", "operator", "spec", "begin",
    "commit", "password", "subject", "title", "description", "content",
    "note", "notes", "remark", "remarks", "company", "customer",
    "contact", "product", "service", "price", "total", "quantity",
    "region", "area", "domain", "mode", "version", "class", "object",
    "event", "process", "rule", "policy", "plan", "task", "job",
    "session", "token", "hash", "link", "path", "url", "list",
    "map", "array", "queue", "stack", "tree", "node", "page",
    "form", "menu", "input", "output", "error", "log", "audit",
    "archive", "backup", "cache", "temp", "test", "debug", "admin",
    "root", "owner", "parent", "child", "master", "slave", "host",
    "port", "server", "client", "local", "global", "public", "private",
    "static", "dynamic", "abstract", "virtual", "super", "self", "this",
    "new", "old",
}


def _safe_field_code(code: str) -> str:
    """确保字段编码不与数据库关键字冲突。

    策略：优先保留原始编码，仅在没有编码时再兜底生成。
    """
    raw = str(code or "").strip()
    if raw:
        return raw
    return _sanitize_code(code)


# ---------------------------------------------------------------------------
# 类型映射（从集中注册表派生）
# ---------------------------------------------------------------------------

from app.field_types import get_field_type_map, get_comp_type_map

FIELD_TYPE_MAP = get_field_type_map()
COMP_TYPE_MAP = get_comp_type_map()


# ---------------------------------------------------------------------------
# 辅助：解析平台模型 → fields 字典
# ---------------------------------------------------------------------------

def _extract_fields(platform_model: dict) -> Dict[str, str]:
    """从平台返回的模型数据中提取 {fieldName: fieldCode}"""
    return {
        f.get("fieldName"): f.get("fieldCode")
        for f in platform_model.get("fields", [])
        if f.get("fieldName") and f.get("fieldCode")
    }


def _permission_object_for_form_config(rule: dict, role_code_map: Dict[str, dict]) -> dict:
    role_code = str(rule.get("roleCode") or rule.get("role") or "").strip()
    if role_code and role_code != "all":
        role_info = role_code_map.get(role_code, {})
        role_id = str(role_info.get("id") or "").strip()
        role_code_value = str(role_info.get("roleCode") or role_code).strip()
        role_name = str(role_info.get("roleName") or rule.get("roleName") or role_code).strip()
        return {
            "permissionObjectType": "ROLE",
            "permissionObjectValue": role_id or role_code_value,
            "permissionObjectDisplayName": role_name,
        }
    return {
        "permissionObjectType": "ALL_USER",
        "permissionObjectValue": "ALL_USER",
        "permissionObjectDisplayName": "全部人员",
    }


def _normalize_permission_range(data_range: object) -> str:
    range_map = {
        "all": "ALL",
        "self": "SELF",
        "dept": "CURRENT_USER_DEPT",
        "dept_sub": "CURRENT_USER_DEPT_LOW_LEVEL",
    }
    if isinstance(data_range, str):
        return range_map.get(data_range, data_range.upper())
    return "ALL"


def _parse_permission_ops(op_value: object) -> set[str]:
    if isinstance(op_value, str):
        return {part.strip() for part in op_value.split(",") if part.strip()}
    return {"all"}


def _build_permission_groups_for_form_config(
    rules: List[dict],
    role_code_map: Dict[str, dict],
) -> tuple[List[dict], List[dict], List[dict]]:
    permission_groups: List[dict] = []
    advanced_groups: List[dict] = []
    operation_groups: List[dict] = []

    for index, rule in enumerate(rules, start=1):
        perm_obj = _permission_object_for_form_config(rule, role_code_map)
        object_type = perm_obj["permissionObjectType"]
        object_value = perm_obj["permissionObjectValue"]
        object_name = perm_obj["permissionObjectDisplayName"]
        range_type = _normalize_permission_range(rule.get("data", "ALL"))
        ops = _parse_permission_ops(rule.get("op", "all"))
        can_view = "all" in ops or "view" in ops
        can_add = "all" in ops or "add" in ops
        can_edit = "all" in ops or "edit" in ops
        can_delete = "all" in ops or "delete" in ops
        can_import = bool(rule.get("canImport"))
        can_draft = bool(rule.get("canDraft"))
        can_export = bool(rule.get("canExport"))

        permission_groups.append({
            "groupConditions": [],
            "selectorFilterConditionList": [],
            "dataPermissions": [{
                "permissionType": "ALL_USER",
                "permissionValue": "ALL_USER",
                "queryPermission": can_view,
                "updatePermission": can_edit,
                "deletePermission": can_delete,
                "addPermission": can_add,
            }],
        })

        advanced_groups.append({
            "permissionName": f"{object_name}权限",
            "permissionDescribe": "",
            "permissionOperationType": {
                "queryPermission": can_view,
                "updatePermission": can_edit,
                "deletePermission": can_delete,
                "commentPermission": can_view,
                "dataSharePermission": can_view,
                "exportPermission": can_export,
                "logPermission": can_view,
                "printPermission": can_view,
                "queryApprovalInfoPermission": can_view,
            },
            "filterConditionGroups": [],
            "permissionObjects": [{
                "permissionObjectType": object_type,
                "permissionObjectValue": object_value,
                "permissionObjectDisplayName": object_name,
                "permissionRange": {"rangeType": range_type},
            }],
        })

        if any((can_add, can_import, can_draft)):
            operation_groups.append({
                "uuid": f"perm-op-{index}",
                "permissionName": f"{object_name}操作权限",
                "permissionDescribe": "",
                "permissionOperationType": {
                    "temporaryStoragePermission": can_draft,
                    "addPermission": can_add,
                    "importPermission": can_import,
                    "copyAddPermission": False,
                    "batchDeletePermission": False,
                    "batchRejectPermission": False,
                    "batchAgreePermission": False,
                    "shareFormPermission": False,
                    "processAnalysisPermission": False,
                },
                "permissionObjects": [{
                    "permissionObjectType": object_type,
                    "permissionObjectValue": object_value,
                    "permissionObjectDisplayName": object_name,
                }],
            })

    return permission_groups, advanced_groups, operation_groups


async def _sync_form_permissions_to_form_config(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    rules: List[dict],
    role_code_map: Dict[str, dict],
) -> None:
    form_config = await client.query_detail_page_config(app_id, form_id)
    permission_groups, advanced_groups, operation_groups = _build_permission_groups_for_form_config(
        rules,
        role_code_map,
    )
    form_config["permissionGroups"] = permission_groups
    form_config["advancedPermissionGroups"] = advanced_groups
    form_config["operationPermissionGroups"] = operation_groups
    logger.info(
        "save_form_config reason: 回写表单权限 (formId=%s, permissionGroups=%s, advanced=%s, operation=%s)",
        form_id,
        len(permission_groups),
        len(advanced_groups),
        len(operation_groups),
    )
    await client.save_form_config(app_id, form_config)


# ---------------------------------------------------------------------------
# 辅助：构建单个表单组件
# ---------------------------------------------------------------------------

def _build_component(
    field: dict,
    model_code: str,
    field_code: str,
    dict_codes: Dict[str, str],
    models: List[dict],
    model_info: dict,
) -> dict:
    ftype = field.get("type", "单行输入")
    comp: dict = {
        "componentType": COMP_TYPE_MAP.get(ftype, "FORM_TEXT_INPUT"),
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}",
    }

    # 必填属性
    if field.get("required"):
        comp["required"] = True
        comp["validators"] = [{"type": "REQUIRED", "message": f"{field['name']}不能为空"}]

    # 字典绑定
    if ftype in ("下拉单选", "下拉多选") and field.get("dict"):
        dcode = dict_codes.get(field["dict"])
        if dcode:
            comp["dictionarySelectConfig"] = {
                "dictionaryCode": dcode,
                "dictionarySelectOptions": [],
            }

    # 数据选择器
    if ftype in ("数据单选", "数据选择", "数据多选") and field.get("ref"):
        ref = field["ref"]
        ref_model = ref.get("model", "") if isinstance(ref, dict) else str(ref)
        ref_field = ref.get("field", "") if isinstance(ref, dict) else ""
        # 按 code 和 name 都尝试匹配
        for ridx, rm in enumerate(models):
            if rm.get("name") == ref_model or rm.get("code") == ref_model:
                ref_mi = model_info.get(ridx)
                if ref_mi:
                    # 解析显示字段的平台编码
                    display_field_code = ref_field
                    if ref_mi.get("fields") and ref_field:
                        display_field_code = ref_mi["fields"].get(ref_field, ref_field)
                    comp["dataSelectorConfig"] = {
                        "type": "LOV_CHOOSE",
                        "otherModelCode": ref_mi["code"],
                        "otherFieldCode": display_field_code,
                    }
                    if ftype in ("数据选择", "数据多选"):
                        comp["componentType"] = "FORM_DATA_SELECTOR"
                break

    if ftype == "关联表单":
        comp["componentType"] = "FORM_ASSOCIATION"
        association = field.get("formAssociationConfig") or {}
        ref = field.get("ref") or {}
        target_model = (
            association.get("targetModelCode")
            or (ref.get("model") if isinstance(ref, dict) else "")
            or ""
        )
        target_field = (
            association.get("targetFieldCode")
            or (ref.get("target_field") if isinstance(ref, dict) else "")
            or (ref.get("display_field") if isinstance(ref, dict) else "")
            or (ref.get("field") if isinstance(ref, dict) else "")
            or ""
        )
        origin_field = association.get("originFieldCode") or field_code
        for ridx, rm in enumerate(models):
            if rm.get("name") == target_model or rm.get("code") == target_model:
                ref_mi = model_info.get(ridx)
                if ref_mi:
                    resolved_target_field = target_field
                    if ref_mi.get("fields") and target_field:
                        resolved_target_field = ref_mi["fields"].get(target_field, target_field)
                    comp["formAssociationConfig"] = {
                        "originFieldCode": origin_field,
                        "targetModelCode": ref_mi["code"],
                        "targetFieldCode": resolved_target_field,
                    }
                break

    return comp


def _build_model_lookup(models: List[dict], model_info: Dict) -> Dict[str, dict]:
    lookup: Dict[str, dict] = {}
    for idx, model in enumerate(models):
        mi = model_info.get(idx)
        if not mi:
            continue
        for key in (model.get("code"), model.get("name"), mi.get("code"), mi.get("name")):
            key = str(key or "").strip()
            if key:
                lookup[key] = mi
    return lookup


def _resolve_reference_component(
    comp_def: dict,
    built: dict,
    model_lookup: Dict[str, dict],
) -> None:
    component_type = str(comp_def.get("componentType") or comp_def.get("component_type") or built.get("componentType") or "").strip()
    association = comp_def.get("formAssociationConfig") or comp_def.get("form_association_config") or {}
    ref = comp_def.get("ref") or {}
    target_model = (
        str(association.get("targetModelCode") or "").strip()
        or str(comp_def.get("selector_form_code") or "").strip()
        or str(comp_def.get("association_form_code") or "").strip()
        or str(comp_def.get("ref_model_code") or "").strip()
        or (str(ref.get("model") or "").strip() if isinstance(ref, dict) else str(ref or "").strip())
    )
    target_field = (
        str(association.get("targetFieldCode") or "").strip()
        or str(comp_def.get("selector_field_code") or "").strip()
        or str(comp_def.get("association_target_field_code") or "").strip()
        or str(comp_def.get("ref_display_field_code") or "").strip()
        or (str(ref.get("target_field") or ref.get("display_field") or ref.get("field") or "").strip() if isinstance(ref, dict) else "")
    )
    if not target_model:
        return

    target_info = model_lookup.get(target_model)
    resolved_model_code = target_info.get("code", target_model) if target_info else target_model
    resolved_field_code = target_field
    if target_info and target_field:
        resolved_field_code = target_info.get("fields", {}).get(target_field, target_field)

    if component_type in ("FORM_DATA_SELECTOR_SINGLE", "FORM_DATA_SELECTOR"):
        built["componentType"] = component_type
        built["dataSelectorConfig"] = {
            "type": "LOV_CHOOSE",
            "otherModelCode": resolved_model_code,
            "otherFieldCode": resolved_field_code,
        }
        built.pop("formAssociationConfig", None)
    elif component_type == "FORM_ASSOCIATION":
        origin_field = str(association.get("originFieldCode") or "").strip()
        if not origin_field:
            model_field = str(comp_def.get("modelField", comp_def.get("model_field", ""))).strip()
            origin_field = model_field.split(".", 1)[1] if "." in model_field else str(comp_def.get("code", "")).strip()
        built["formAssociationConfig"] = {
            "originFieldCode": origin_field,
            "targetModelCode": resolved_model_code,
            "targetFieldCode": resolved_field_code,
        }


def _build_form_components_from_definition(
    form: dict,
    default_model_code: str,
    model_lookup: Dict[str, dict],
) -> tuple[List[dict], List[str], List[str]]:
    components: List[dict] = []
    query_conditions: List[str] = []
    query_list: List[str] = []
    listable = 0
    sub_groups: Dict[str, dict] = {}

    for comp in form.get("components", []) or []:
        section_type = str(comp.get("sectionType", comp.get("section_type", "main"))).strip() or "main"
        component_model_code = str(comp.get("modelCode", comp.get("model_code", ""))).strip() or default_model_code
        resolved_model_code = model_lookup.get(component_model_code, {}).get("code", component_model_code)
        table_model_code = str(comp.get("tableModelCode", comp.get("table_model_code", ""))).strip() or component_model_code
        resolved_table_model_code = model_lookup.get(table_model_code, {}).get("code", table_model_code)
        model_field = str(comp.get("modelField", comp.get("model_field", ""))).strip()
        field_code = model_field.split(".", 1)[1] if "." in model_field else str(comp.get("code", "")).strip()
        if not field_code and str(comp.get("componentType", "")).strip() != "FORM_ASSOCIATION":
            continue

        built = {
            "componentType": comp.get("componentType") or comp.get("component_type") or "FORM_TEXT_INPUT",
            "label": comp.get("label") or comp.get("name") or field_code,
        }
        if field_code:
            built["modelField"] = f"{resolved_model_code}.{field_code}"
        for key in ("hidden", "readonly", "required", "showInList", "searchable"):
            if key in comp:
                built[key] = bool(comp.get(key))

        _resolve_reference_component(comp, built, model_lookup)

        if section_type == "sub":
            group = sub_groups.setdefault(resolved_table_model_code, {
                "componentType": "FORM_WIDGET_SON_TABLE",
                "label": comp.get("subTableLabel") or built["label"] or resolved_table_model_code,
                "tableColumn": [],
            })
            if comp.get("subTableLabel"):
                group["label"] = comp.get("subTableLabel")
            group["tableColumn"].append(built)
            continue

        components.append(built)
        if built.get("showInList") and listable < 8 and built.get("modelField"):
            mf = built["modelField"]
            if built.get("searchable") and len(query_conditions) < 4:
                query_conditions.append(mf)
            query_list.append(mf)
            listable += 1

    components.extend(sub_groups.values())
    return components, query_conditions, query_list


# ---------------------------------------------------------------------------
# Phase 0 预处理
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 2 数据模型辅助
# ---------------------------------------------------------------------------

def _classify_models_reuse_vs_new(
    models: List[dict],
    existing_by_name: Dict[str, dict],
    model_info: Dict,
) -> tuple[List[dict], List[tuple]]:
    """把 models 拆成 (reused, new_models_to_create)。

    副作用：为复用模型（含子表）原地写入 model_info。
    new_models_to_create 形如 [(idx, model_dict), ...]，子表登记留给 _build_model_payload_with_subs。
    """
    reused: List[dict] = []
    new_models_to_create: List[tuple] = []
    for idx, m in enumerate(models):
        em = existing_by_name.get(m["name"])
        if em:
            model_info[idx] = {"name": m["name"], "code": em["modelCode"], "fields": _extract_fields(em)}
            reused.append(m)
            for f in m.get("fields", []):
                if f.get("type") == "子表" and f.get("sub_fields"):
                    sub_em = existing_by_name.get(f["name"])
                    if sub_em:
                        model_info[f"{idx}_sub_{f['name']}"] = {
                            "name": f["name"], "code": sub_em["modelCode"], "fields": _extract_fields(sub_em),
                        }
        else:
            new_models_to_create.append((idx, m))
    return reused, new_models_to_create


def _build_model_payload_with_subs(
    new_models_to_create: List[tuple],
    app_id: str,
    suffix: str,
    model_info: Dict,
) -> dict:
    """构造 create_models 的 payload，同时登记 model_info（主模型 + 子表）。"""
    data_models: List[dict] = []
    for idx, m in new_models_to_create:
        mc = f"{_sanitize_code(m.get('code', 'model'))}_{suffix}"
        fields_map = {}

        # 子表模型
        for f in m.get("fields", []):
            if f.get("type") == "子表" and f.get("sub_fields"):
                sub_code = f"{_sanitize_code(f.get('sub_code') or m.get('code', 'model') + '_sub')}_{suffix}"
                sub_fields = []
                sub_fields_map = {}
                for sf in f["sub_fields"]:
                    sfc = _safe_field_code(sf.get("code") or sf["name"])
                    sub_fields.append({
                        "fieldName": sf["name"], "fieldCode": sfc,
                        "fieldType": FIELD_TYPE_MAP.get(sf.get("type", ""), "STRING"),
                        "fieldDescription": sf.get("type", ""),
                    })
                    sub_fields_map[sf["name"]] = sfc
                data_models.append({
                    "appId": app_id, "modelName": f["name"],
                    "modelCode": sub_code, "modelDescription": f["name"],
                    "fields": sub_fields,
                })
                model_info[f"{idx}_sub_{f['name']}"] = {"name": f["name"], "code": sub_code, "fields": sub_fields_map}

        # 主模型字段
        main_fields = []
        for f in m.get("fields", []):
            if f.get("type") == "子表":
                continue
            fc = _safe_field_code(f.get("code") or f["name"])
            main_fields.append({
                "fieldName": f["name"], "fieldCode": fc,
                "fieldType": FIELD_TYPE_MAP.get(f.get("type", ""), "STRING"),
                "fieldDescription": f.get("type", ""),
            })
            fields_map[f["name"]] = fc

        data_models.append({
            "appId": app_id, "modelName": m["name"],
            "modelCode": mc, "modelDescription": m.get("description", m["name"]),
            "fields": main_fields,
        })
        model_info[idx] = {"name": m["name"], "code": mc, "fields": fields_map}

    return {"appId": app_id, "datasourceId": "", "dataModels": data_models}


async def _refresh_model_codes_from_platform(
    client: APaaSClient,
    app_id: str,
    new_models_to_create: List[tuple],
    model_info: Dict,
) -> None:
    """创建后回查，用平台真实 fieldCode 覆盖 model_info（平台可能追加后缀）。"""
    refreshed = await client.query_models(app_id)
    ref_by_code = {rm.get("modelCode"): rm for rm in refreshed}
    for idx, m in new_models_to_create:
        mi = model_info.get(idx)
        if mi and mi["code"] in ref_by_code:
            mi["fields"] = _extract_fields(ref_by_code[mi["code"]])
        for f in m.get("fields", []):
            if f.get("type") == "子表":
                sub_key = f"{idx}_sub_{f['name']}"
                sub_mi = model_info.get(sub_key)
                if sub_mi and sub_mi["code"] in ref_by_code:
                    sub_mi["fields"] = _extract_fields(ref_by_code[sub_mi["code"]])


async def _rollback_models_to_reuse_by_name(
    client: APaaSClient,
    app_id: str,
    new_models_to_create: List[tuple],
    model_info: Dict,
) -> None:
    """编码冲突时回退：按 modelName 匹配平台已有模型覆盖 model_info。"""
    refreshed = await client.query_models(app_id)
    ref_by_name = {rm.get("modelName"): rm for rm in refreshed}
    for idx, m in new_models_to_create:
        rm = ref_by_name.get(m["name"])
        if rm:
            model_info[idx] = {"name": m["name"], "code": rm["modelCode"], "fields": _extract_fields(rm)}
            for f in m.get("fields", []):
                if f.get("type") == "子表":
                    srm = ref_by_name.get(f["name"])
                    if srm:
                        model_info[f"{idx}_sub_{f['name']}"] = {
                            "name": f["name"], "code": srm["modelCode"], "fields": _extract_fields(srm),
                        }


# ---------------------------------------------------------------------------
# Phase 3 表单辅助
# ---------------------------------------------------------------------------

async def _load_existing_form_menus(client: APaaSClient, app_id: str) -> Dict[str, str]:
    """查询应用已有表单菜单，返回 {menuName: formId}。异常吞掉返回空表。"""
    existing_forms: Dict[str, str] = {}
    try:
        menus = await client.query_menus(app_id)

        def _collect(items: list):
            for item in items:
                if item.get("formId"):
                    existing_forms[item.get("menuName", "")] = item["formId"]
                _collect(item.get("submenus", []) or item.get("children", []) or [])

        _collect(menus)
    except Exception:
        pass
    return existing_forms


def _resolve_forms_to_build(all_forms: List[dict], models: List[dict]) -> List[dict]:
    """用户提供 all_forms 则用之；否则按 models 自动生成每模型一份空 form。"""
    forms_to_build = all_forms or []
    if not forms_to_build:
        forms_to_build = [
            {
                "name": m["name"],
                "modelCode": m.get("code"),
                "allModelCodes": [m.get("code")],
                "components": [],
            }
            for m in models
        ]
    return forms_to_build


def _build_form_create_payload(
    form: dict,
    form_name: str,
    all_model_codes: List[str],
    components: List[dict],
    query_conditions: List[str],
    query_list: List[str],
) -> List[dict]:
    """构造单表单的 create_form_config 请求体（list 包裹一个 dict）。"""
    return [{
        "formName": form_name,
        "formCode": str(form.get("formCode") or form.get("code") or f"form_{_rand(6)}"),
        "allModelCodes": all_model_codes,
        "formComponents": components,
        "listPageView": {
            "queryConditions": query_conditions,
            "queryList": query_list,
        },
    }]


# ---------------------------------------------------------------------------
# Phase 1 字典辅助
# ---------------------------------------------------------------------------

def _classify_dicts(
    dicts: List[dict],
    existing: Dict[str, dict],
    dict_codes: Dict[str, str],
    suffix: str,
) -> tuple[List[dict], List[str]]:
    """把 dicts 拆成 (new_dicts, reused_names)。

    副作用：写入 dict_codes 映射（复用用平台已有 code，新建用本地生成 code）。
    """
    new_dicts: List[dict] = []
    reused_names: List[str] = []
    for d in dicts:
        ed = existing.get(d["name"])
        if ed:
            pc = ed["dictionaryCode"]
            dict_codes[d["name"]] = pc
            dict_codes[d.get("code", d["name"])] = pc
            reused_names.append(d["name"])
        else:
            dc = f"{_sanitize_code(d.get('code', 'dict'))}_{suffix}"
            dict_codes[d["name"]] = dc
            dict_codes[d.get("code", d["name"])] = dc
            new_dicts.append(d)
    return new_dicts, reused_names


async def _seed_dict_options(
    client: APaaSClient,
    app_id: str,
    new_dicts: List[dict],
    dict_codes: Dict[str, str],
    suffix: str,
) -> int:
    """为新建字典灌入选项（直连 httpx，因 client 未封装该接口）。

    返回写入的选项总数。
    """
    all_platform_dicts = await client.query_dicts(app_id)
    dict_by_code = {d.get("dictionaryCode"): d for d in all_platform_dicts}
    total_opts = 0
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        headers = client._get_headers(app_id)
        for d in new_dicts:
            dc = dict_codes[d["name"]]
            obj = dict_by_code.get(dc)
            if not obj or not d.get("options"):
                continue
            dict_id = obj["id"]
            for idx, opt in enumerate(d["options"]):
                opt_name = opt["name"] if isinstance(opt, dict) else str(opt)
                opt_code_raw = opt.get("code", f"opt{idx}") if isinstance(opt, dict) else f"opt{idx}"
                await http.post(
                    f"{client.base_url}/xdap-app/dataDictionary/add/dictionaryValue",
                    headers=headers,
                    json={
                        "appId": app_id,
                        "dictionaryId": dict_id,
                        "valueCode": f"{_sanitize_code(opt_code_raw)}_{suffix}",
                        "valueName": opt_name,
                        "valueNameI18nAssociated": False,
                        "valueNameI18nResourceCode": "",
                        "valueNameI18n": {},
                        "displayOrder": idx,
                        "valueDescribe": "",
                        "valueStatus": "ENABLE",
                        "valueMulticolor": "#027AFF",
                    },
                )
                total_opts += 1
    return total_opts


def _select_models_and_dicts(
    all_models: List[dict],
    dicts: List[dict],
    selected_indices: Optional[List[int]],
) -> tuple[List[dict], List[dict]]:
    """根据 selected_model_indices 过滤模型与字典。

    字典只保留被选中模型（含子字段）引用的。
    """
    if selected_indices is not None and len(selected_indices) < len(all_models):
        models = [all_models[i] for i in selected_indices if i < len(all_models)]
    else:
        models = all_models

    if selected_indices is not None:
        used = set()
        for m in models:
            for f in m.get("fields", []):
                if f.get("dict"):
                    used.add(f["dict"])
                for sf in f.get("sub_fields", []):
                    if sf.get("dict"):
                        used.add(sf["dict"])
        if used:
            dicts = [d for d in dicts if d.get("code") in used]

    return models, dicts


# ---------------------------------------------------------------------------
# 主生成流程
# ---------------------------------------------------------------------------

async def run_complete_generation(
    client: APaaSClient,
    app_id: str,
    config: dict,
) -> AsyncGenerator[Dict, None]:
    """完整的应用生成流程，通过 SSE yield 进度事件"""

    data = config.get("data", config)
    app_name = data.get("appName", "应用")
    roles = data.get("roles", [])
    dicts = data.get("dicts", [])
    all_models = data.get("models", [])
    all_forms = data.get("forms", [])

    models, dicts = _select_models_and_dicts(
        all_models, dicts, config.get("selected_model_indices")
    )

    suffix = _rand()

    # ==================================================================
    # Phase 0: 解析配置
    # ==================================================================
    yield {"stage": 0, "status": "running", "step": f"{len(models)} 个表单、{len(dicts)} 个字典、{len(roles)} 个角色"}
    yield {"stage": 0, "status": "done", "step": "配置解析完成"}

    # ==================================================================
    # Phase 1: 公共资源（角色 + 字典）
    # ==================================================================
    yield {"stage": 1, "status": "running", "step": "创建公共资源..."}
    dict_codes: Dict[str, str] = {}  # {原始name或code: 平台dictCode}
    role_code_map: Dict[str, dict] = {}

    # --- 角色 ---
    if roles:
        try:
            roles_payload = []
            for r in roles:
                original_code = str(r.get("code", r["name"]))
                platform_code = _apply_suffix(_sanitize_code(original_code), suffix)
                role_code_map[original_code] = {"roleCode": platform_code, "roleName": r["name"]}
                roles_payload.append({
                    "appId": app_id,
                    "roleCode": platform_code,
                    "roleName": r["name"],
                })
            await client.create_roles(app_id, roles_payload)
            try:
                remote_roles = await client.query_roles(app_id)
                for r in roles:
                    original_code = str(r.get("code", r["name"]))
                    local_info = role_code_map.setdefault(original_code, {})
                    platform_code = local_info.get("roleCode")
                    matched = next((
                        item for item in remote_roles
                        if item.get("roleCode") == platform_code
                        or item.get("roleName") == r.get("name")
                    ), None)
                    if matched:
                        local_info["id"] = matched.get("id", "")
                        local_info["roleCode"] = matched.get("roleCode", platform_code)
                        local_info["roleName"] = matched.get("roleName", r.get("name", original_code))
            except Exception as exc:
                logger.warning("查询平台角色ID失败，权限下发将退回角色编码: %s", exc)
            yield {"stage": 1, "status": "running", "step": f"角色: {', '.join(r['name'] for r in roles)}"}
        except Exception as e:
            if "已存在" in str(e) or "重复" in str(e):
                yield {"stage": 1, "status": "running", "step": "角色已存在，跳过"}
            else:
                yield {"stage": 1, "status": "running", "step": f"角色创建失败（继续）: {e}"}

    # --- 字典 ---
    if dicts:
        try:
            existing = {d.get("dictionaryName"): d for d in await client.query_dicts(app_id)}
            new_dicts, reused_names = _classify_dicts(dicts, existing, dict_codes, suffix)
            for name in reused_names:
                yield {"stage": 1, "status": "running", "step": f"复用字典: {name}"}

            if new_dicts:
                payload = [
                    {
                        "appId": app_id,
                        "dictionaryCode": dict_codes[d["name"]],
                        "dictionaryName": d["name"],
                        "dictionaryOptions": [],
                    }
                    for d in new_dicts
                ]
                await client.create_dicts(app_id, payload)
                total_opts = await _seed_dict_options(client, app_id, new_dicts, dict_codes, suffix)
                yield {"stage": 1, "status": "running", "step": f"新建 {len(new_dicts)} 个字典，{total_opts} 个选项"}
        except Exception as e:
            logger.error(f"字典创建失败: {e}", exc_info=True)
            yield {"stage": 1, "status": "error", "step": f"字典创建失败: {e}"}
            return

    yield {"stage": 1, "status": "done", "step": "公共资源完成"}

    # ==================================================================
    # Phase 2: 数据模型
    # ==================================================================
    yield {"stage": 2, "status": "running", "step": "创建数据模型..."}

    if not models:
        yield {"stage": 2, "status": "error", "step": "没有数据模型"}
        return

    # model_info: {idx: {name, code, fields: {fieldName: fieldCode}}}
    # 子表 key 格式: "{idx}_sub_{子表名}"
    model_info: Dict = {}

    try:
        existing_models = await client.query_models(app_id)
        existing_by_name = {m.get("modelName"): m for m in existing_models}
        reused, new_models_to_create = _classify_models_reuse_vs_new(
            models, existing_by_name, model_info
        )
        for m in reused:
            yield {"stage": 2, "status": "running", "step": f"复用: {m['name']}"}

        if new_models_to_create:
            payload = _build_model_payload_with_subs(
                new_models_to_create, app_id, suffix, model_info
            )

            try:
                await client.create_models(app_id, payload)
                yield {"stage": 2, "status": "running", "step": f"新建: {'、'.join(m['name'] for _, m in new_models_to_create)}"}
                await _refresh_model_codes_from_platform(
                    client, app_id, new_models_to_create, model_info
                )
            except Exception as e:
                if "编码重复" in str(e) or "已存在" in str(e):
                    yield {"stage": 2, "status": "running", "step": "编码冲突，回退到复用模式..."}
                    await _rollback_models_to_reuse_by_name(
                        client, app_id, new_models_to_create, model_info
                    )
                else:
                    raise

        # 兼容：原 Phase 2 for-loop 的循环变量 `m` 会泄漏进 Phase 3 作用域被读取
        # （见 Phase 3 create_menu 处的 m["name"]，属历史 bug，批 4 清理）
        if new_models_to_create:
            m = new_models_to_create[-1][1]
        elif models:
            m = models[-1]

        yield {"stage": 2, "status": "done", "step": f"模型完成（{len(model_info)} 个）"}

    except Exception as e:
        logger.error(f"模型创建失败: {e}", exc_info=True)
        yield {"stage": 2, "status": "error", "step": f"模型创建失败: {e}"}
        return

    # ==================================================================
    # Phase 3: 表单 + 字典绑定
    # ==================================================================
    yield {"stage": 3, "status": "running", "step": "创建表单..."}

    form_results: List[dict] = []  # [{formId, formCode, formName, menuId}]
    try:
        model_lookup = _build_model_lookup(models, model_info)
        existing_forms = await _load_existing_form_menus(client, app_id)
        forms_to_build = _resolve_forms_to_build(all_forms, models)

        for idx, form in enumerate(forms_to_build):
            form_name = form.get("name") or form.get("formName") or form.get("modelCode") or f"表单{idx+1}"
            model_code = str(form.get("modelCode", form.get("model_code", ""))).strip()
            mi = model_lookup.get(model_code) if model_code else None
            if not mi and idx < len(models):
                mi = model_info.get(idx)
            if not mi:
                yield {"stage": 3, "status": "running", "step": f"跳过 {form_name}（无模型）"}
                continue

            if form_name in existing_forms:
                form_results.append({"formId": existing_forms[form_name], "formName": form_name})
                yield {"stage": 3, "status": "running", "step": f"复用: {form_name}"}
                continue

            all_model_codes = []
            for raw_code in form.get("allModelCodes", []) or [model_code]:
                resolved_code = model_lookup.get(str(raw_code).strip(), {}).get("code", raw_code)
                if resolved_code:
                    all_model_codes.append(resolved_code)
            all_model_codes = list(dict.fromkeys(all_model_codes or [mi["code"]]))

            components, query_conditions, query_list = _build_form_components_from_definition(
                form=form,
                default_model_code=mi["code"],
                model_lookup=model_lookup,
            )

            if not components:
                model_fields = mi["fields"]
                for field_name, field_code in model_fields.items():
                    fallback_field = {"name": field_name, "type": "单行输入", "required": False}
                    components.append(_build_component(fallback_field, mi["code"], field_code, dict_codes, models, model_info))
                    if len(query_list) < 8:
                        mf = f"{mi['code']}.{field_code}"
                        if len(query_conditions) < 4:
                            query_conditions.append(mf)
                        query_list.append(mf)

            if not components:
                yield {"stage": 3, "status": "running", "step": f"跳过 {form_name}（无可用字段）"}
                continue

            form_payload = _build_form_create_payload(
                form=form,
                form_name=form_name,
                all_model_codes=all_model_codes,
                components=components,
                query_conditions=query_conditions,
                query_list=query_list,
            )

            try:
                result = await client.create_form_config(app_id, form_payload)
                if isinstance(result, list):
                    for fr in result:
                        if isinstance(fr, dict) and "id" in fr:
                            form_id = fr["id"]
                            form_results.append({
                                "formId": form_id,
                                "formName": fr.get("formName", m["name"]),
                                "formCode": fr.get("formCode", ""),
                                "menuId": fr.get("menuId", ""),
                            })
                            # formConfig API 创建的菜单不可见，需要额外创建菜单
                            try:
                                await client.create_menu(app_id, m["name"], form_id, menu_order=idx)
                            except Exception as menu_err:
                                logger.warning(f"创建菜单失败（{m['name']}）: {menu_err}")
                yield {"stage": 3, "status": "running", "step": f"创建: {form_name}"}
            except Exception as e:
                yield {"stage": 3, "status": "running", "step": f"失败 {form_name}: {e}"}

        # --- 绑定字典到表单（第二遍：用平台真实选项回写） ---
        form_ids = [fr["formId"] for fr in form_results if fr.get("formId")]
        if dicts and form_ids:
            try:
                all_platform_dicts = await client.query_dicts(app_id)
                dict_id_map = {d.get("dictionaryCode"): d.get("id") for d in all_platform_dicts if d.get("dictionaryCode") and d.get("id")}
                dict_options_map: Dict[str, list] = {}
                for dc, did in dict_id_map.items():
                    dict_options_map[dc] = await client.query_dict_options(app_id, did)

                # 收集所有下拉字段字典映射（含子表）
                label_dict: Dict[str, str] = {}
                for m in models:
                    for f in m.get("fields", []):
                        if f.get("type") in ("下拉单选", "下拉多选") and f.get("dict"):
                            label_dict[f["name"]] = dict_codes.get(f["dict"], "")
                        if f.get("type") == "子表":
                            for sf in f.get("sub_fields", []):
                                if sf.get("type") in ("下拉单选", "下拉多选") and sf.get("dict"):
                                    label_dict[sf["name"]] = dict_codes.get(sf["dict"], "")

                def _bind_dict(comp: dict) -> bool:
                    ct = comp.get("componentType")
                    if ct not in ("FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT"):
                        return False
                    dc = label_dict.get(comp.get("label", ""), "")
                    if not dc or dc not in dict_id_map:
                        return False
                    did = dict_id_map[dc]
                    opts = dict_options_map.get(dc, [])
                    choose = [
                        {
                            "id": o.get("valueCode"),
                            "label": o.get("valueName"),
                            "labelI18nAssociated": False,
                            "color": o.get("valueMulticolor", "#027AFF"),
                            "status": o.get("valueStatus", "ENABLE"),
                            "checked": False,
                            "displayOrder": o.get("displayOrder", 0),
                        }
                        for o in opts
                    ]
                    comp["source"] = {"type": "DICTIONARY_TYPE", "id": did}
                    comp["chooseOptions"] = choose
                    comp["dictionaryChooseOptions"] = choose
                    comp["chooseType"] = "SINGLE" if ct == "FORM_SELECT_INPUT_SINGLE" else "MULTIPLE"
                    comp["multicolor"] = True
                    if ct == "FORM_SELECT_INPUT_SINGLE":
                        comp["componentType"] = "FORM_SELECT_INPUT"
                    return True

                bound_count = 0
                for form_id in form_ids:
                    try:
                        fc = await client.query_form_config(app_id, form_id)
                        comps = fc.get("detailPage", {}).get("formComponents", [])
                        updated = False

                        for comp in comps:
                            if _bind_dict(comp):
                                updated = True
                            # 子表内的列组件
                            if comp.get("componentType") == "FORM_WIDGET_SON_TABLE":
                                for col in comp.get("tableColumn", []):
                                    if _bind_dict(col):
                                        updated = True

                        if updated:
                            await client.save_form_config(app_id, fc)
                            bound_count += 1
                    except Exception as e:
                        logger.warning(f"绑定表单 {form_id} 字典失败: {e}")

                if bound_count:
                    yield {"stage": 3, "status": "running", "step": f"字典绑定: {bound_count} 个表单"}
            except Exception as e:
                logger.warning(f"字典绑定阶段失败（不阻断）: {e}")

        yield {"stage": 3, "status": "done", "step": f"表单完成（{len(form_results)} 个）"}

    except Exception as e:
        logger.error(f"表单创建失败: {e}", exc_info=True)
        yield {"stage": 3, "status": "error", "step": f"表单创建失败: {e}"}
        return

    # ==================================================================
    # Phase 4: 权限配置
    # ==================================================================
    permissions = data.get("permissions", [])
    if permissions or form_results:
        yield {"stage": 4, "status": "running", "step": "配置权限..."}
        try:
            # 如果用户没有指定权限规则，生成默认权限：全员可访问
            perm_payloads = []
            permission_sync_jobs = []
            for fr in form_results:
                form_code = fr.get("formCode", "")
                form_id = fr.get("formId", "")

                # 查找用户是否为该表单指定了权限
                user_perm = next((p for p in permissions if p.get("form") == fr.get("formName")), None)

                if user_perm and user_perm.get("rules"):
                    # 用户指定了权限规则 → 转换为平台格式
                    op_groups = []
                    data_groups = []
                    for rule in user_perm["rules"]:
                        role_code = rule.get("role", "")
                        # 找到对应角色的平台编码
                        perm_obj_type = "ALL_USER"
                        perm_obj_value = ""
                        perm_obj_name = "全部人员"
                        if role_code and role_code != "all":
                            role_info = role_code_map.get(role_code, {})
                            perm_obj_type = "ROLE"
                            perm_obj_value = role_info.get("id") or role_info.get("roleCode", role_code)
                            perm_obj_name = role_info.get("roleName", role_code)

                        op = rule.get("op", "all")
                        op_set = {part.strip() for part in str(op).split(",") if part.strip()} if isinstance(op, str) else {"all"}
                        can_view = "all" in op_set or "view" in op_set
                        can_add = "all" in op_set or "add" in op_set
                        can_edit = "all" in op_set or "edit" in op_set
                        can_delete = "all" in op_set or "delete" in op_set
                        can_import = bool(rule.get("canImport"))
                        can_draft = bool(rule.get("canDraft"))
                        can_export = bool(rule.get("canExport"))
                        perm_op = {
                            "addPermission": can_add,
                            "batchAgreePermission": False,
                            "batchDeletePermission": False,
                            "batchRejectPermission": False,
                            "copyAddPermission": False,
                            "importPermission": can_import,
                            "shareFormPermission": False,
                            "temporaryStoragePermission": can_draft,
                        }

                        data_range = rule.get("data", "ALL")
                        range_map = {
                            "all": "ALL", "self": "SELF", "dept": "CURRENT_USER_DEPT",
                            "dept_sub": "CURRENT_USER_DEPT_LOW_LEVEL",
                        }
                        range_type = range_map.get(data_range, data_range.upper() if isinstance(data_range, str) else "ALL")

                        if any((can_add, can_import, can_draft)):
                            op_groups.append({
                                "permissionName": f"{perm_obj_name}操作权限",
                                "permissionDescribe": "",
                                "permissionObjects": [{
                                    "permissionObjectDisplayName": perm_obj_name,
                                    "permissionObjectType": perm_obj_type,
                                    "permissionObjectValue": perm_obj_value,
                                    "permissionRange": {"rangeType": "ALL"},
                                }],
                                "permissionOperationType": perm_op,
                            })
                        data_groups.append({
                            "permissionName": f"{perm_obj_name}数据权限",
                            "permissionDescribe": "",
                            "permissionObjects": [{
                                "permissionObjectDisplayName": perm_obj_name,
                                "permissionObjectType": perm_obj_type,
                                "permissionObjectValue": perm_obj_value,
                                "permissionRange": {"rangeType": range_type},
                            }],
                            "permissionOperationType": {
                                "queryPermission": can_view,
                                "deletePermission": can_delete,
                                "updatePermission": can_edit,
                                "commentPermission": can_view,
                                "dataSharePermission": can_view,
                                "exportPermission": can_export,
                                "logPermission": can_view,
                                "printPermission": can_view,
                                "queryApprovalInfoPermission": can_view,
                            },
                        })

                    perm_payloads.append({
                        "formCode": form_code,
                        "appId": app_id,
                        "tenantId": "",
                        "formId": form_id,
                        "operationPermissionGroups": op_groups,
                        "dataPermissionGroups": data_groups,
                    })
                    permission_sync_jobs.append({
                        "form_id": form_id,
                        "rules": user_perm["rules"],
                    })
            if perm_payloads:
                await client.create_form_permissions(app_id, perm_payloads)
                for job in permission_sync_jobs:
                    await _sync_form_permissions_to_form_config(
                        client=client,
                        app_id=app_id,
                        form_id=job["form_id"],
                        rules=job["rules"],
                        role_code_map=role_code_map,
                    )
                yield {"stage": 4, "status": "running", "step": f"配置 {len(perm_payloads)} 个表单权限"}

            yield {"stage": 4, "status": "done", "step": "权限配置完成"}
        except Exception as e:
            # 权限失败不阻断整体流程
            logger.warning(f"权限配置失败: {e}")
            yield {"stage": 4, "status": "done", "step": f"权限配置跳过: {e}"}
    else:
        yield {"stage": 4, "status": "done", "step": "无权限配置"}

    # ==================================================================
    # 完成
    # ==================================================================
    yield {
        "type": "complete",
        "message": f"应用 {app_name} 生成完成！共 {len(form_results)} 个表单",
    }
