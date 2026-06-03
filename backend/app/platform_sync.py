"""平台反向同步模块

将平台 API 返回的数据转换回本地 preview config 格式，
并与本地配置做 diff 检测漂移。
支持两种模式：
- sync_from_platform(): 轻量同步（用于增量更新 diff）
- sync_from_platform_full(): 完整反向解析（用于导入已有应用）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from app.field_types import get_all_types
from app.apaas_client import APaaSClient
from app.incremental_executor import fetch_remote_data

logger = logging.getLogger(__name__)

# 反向映射：平台组件类型 → preview 字段类型
_REVERSE_COMP_MAP: Dict[str, str] = {}
for _name, _info in get_all_types().items():
    if _info.component_type not in _REVERSE_COMP_MAP:
        _REVERSE_COMP_MAP[_info.component_type] = _name

# 反向映射：平台数据模型类型 → preview 字段类型（优先级低于组件类型）
_REVERSE_DATA_TYPE_MAP: Dict[str, str] = {
    "STRING": "单行输入",
    "BIG_TEXT": "多行输入",
    "DATE": "日期时间",
    "NUM": "数字",
}

# 平台权限操作 → 可读名称
_OP_MAP: Dict[str, str] = {
    "addPermission": "新增",
    "updatePermission": "编辑",
    "deletePermission": "删除",
    "queryPermission": "查看",
    "importPermission": "导入",
    "copyAddPermission": "查看",
    "temporaryStoragePermission": "暂存",
    "shareFormPermission": "查看",
    "exportPermission": "导出",
    "commentPermission": "查看",
    "dataSharePermission": "查看",
    "logPermission": "查看",
    "printPermission": "查看",
    "queryApprovalInfoPermission": "查看",
}

# 数据范围 → config 格式
_RANGE_MAP: Dict[str, str] = {
    "ALL": "ALL",
    "SELF": "SELF",
    "CURRENT_USER_DEPT": "CURRENT_USER_DEPT",
    "CURRENT_USER_DEPT_LOW_LEVEL": "CURRENT_USER_DEPT_LOW_LEVEL",
}

# 系统字段，跳过
_SKIP_FIELDS: Set[str] = {
    "id", "created_by", "creation_date", "last_updated_by",
    "last_update_date", "object_version_number", "tenant_id",
    "status", "owner", "parent_id",
}


def _guess_field_type(comp_type: str = "", data_type: str = "",
                      choose_type: str = "") -> str:
    """从平台组件类型或数据类型推断 preview 字段类型

    对于 FORM_SELECT_INPUT，需要根据 chooseType 区分单选/多选。
    """
    # FORM_SELECT_INPUT 在 detailPageConfigById 中用 chooseType 区分
    if comp_type == "FORM_SELECT_INPUT":
        return "下拉多选" if choose_type == "MULTIPLE" else "下拉单选"
    if comp_type and comp_type in _REVERSE_COMP_MAP:
        return _REVERSE_COMP_MAP[comp_type]
    if data_type and data_type in _REVERSE_DATA_TYPE_MAP:
        return _REVERSE_DATA_TYPE_MAP[data_type]
    return "单行输入"


async def sync_from_platform(
    client: APaaSClient,
    app_id: str,
    app_name: str = "",
) -> Dict[str, Any]:
    """从平台拉取当前状态，转换为本地 preview config 格式。

    Returns:
        与 config_preview 相同结构的 dict：
        {"appName": ..., "roles": [...], "dicts": [...], "models": [...]}
    """
    remote = await fetch_remote_data(client, app_id)
    logger.info(
        f"平台同步: {len(remote.get('roles', []))} 角色, "
        f"{len(remote.get('dicts', []))} 字典, "
        f"{len(remote.get('models', []))} 模型"
    )

    config: Dict[str, Any] = {
        "appName": app_name,
        "roles": _convert_roles(remote.get("roles", [])),
        "dicts": _convert_dicts(remote.get("dicts", []), remote.get("dict_options", {})),
        "models": _convert_models(remote.get("models", [])),
        "workflows": [],
        "permissions": [],
    }
    return config


def _convert_roles(remote_roles: List[Dict]) -> List[Dict]:
    """平台角色 → preview 角色"""
    roles = []
    for r in remote_roles:
        roles.append({
            "name": r.get("roleName", ""),
            "code": r.get("roleCode", ""),
        })
    return roles


def _build_role_lookup(remote_roles: List[Dict]) -> Dict[str, Dict[str, str]]:
    """构建角色 id/code/name 的统一索引，便于权限回读时反查。"""
    lookup: Dict[str, Dict[str, str]] = {}
    for role in remote_roles:
        role_id = str(role.get("id", role.get("roleId", "")) or "").strip()
        role_code = str(role.get("roleCode", role.get("code", "")) or "").strip()
        role_name = str(role.get("roleName", role.get("name", "")) or "").strip()
        if not (role_id or role_code or role_name):
            continue
        entry = {
            "id": role_id,
            "code": role_code or role_id or role_name,
            "name": role_name or role_code or role_id,
        }
        for key in (role_id, role_code, role_name):
            if key:
                lookup[key] = entry
    return lookup


def _convert_dicts(remote_dicts: List[Dict], dict_options: Dict[str, List[Dict]]) -> List[Dict]:
    """平台字典 → preview 字典"""
    dicts = []
    for d in remote_dicts:
        dict_id = str(d.get("id", d.get("dictionaryId", "")))
        dict_code = d.get("dictionaryCode", d.get("code", ""))
        options = []
        # 从 dict_options 中取选项。
        # fetch_remote_data() 目前按 dictionaryCode 存储；这里兼容 code/id 两种 key。
        raw_options = (
            dict_options.get(dict_code, [])
            or dict_options.get(dict_id, [])
        )
        for opt in raw_options:
            options.append({
                "name": (
                    opt.get("valueName")
                    or opt.get("dictionaryValue")
                    or opt.get("name", "")
                ),
                "code": (
                    opt.get("valueCode")
                    or opt.get("dictionaryValueCode")
                    or opt.get("code", "")
                ),
            })
        dicts.append({
            "name": d.get("dictionaryName", d.get("name", "")),
            "code": dict_code,
            "options": options,
        })
    return dicts


def _convert_models(remote_models: List[Dict]) -> List[Dict]:
    """平台模型 → preview 模型"""
    models = []
    for m in remote_models:
        fields = []
        raw_fields = m.get("fields", m.get("dataModelFields", []))
        for f in raw_fields:
            field_name = (
                f.get("fieldName")
                or f.get("name")
                or f.get("columnName")
                or f.get("displayName")
                or ""
            )
            field_code = (
                f.get("fieldCode")
                or f.get("code")
                or f.get("columnCode")
                or field_name
            )
            database_field_type = (
                f.get("databaseFieldType")
                or f.get("database_field_type")
                or f.get("dbType")
                or ""
            )
            field_length = (
                f.get("maxLength")
                or f.get("length")
                or f.get("columnLength")
                or ""
            )
            field = {
                "name": field_name,
                "code": field_code,
                "type": _guess_field_type(
                    f.get("componentType", ""),
                    f.get("fieldType", ""),
                    f.get("chooseType", ""),
                ),
                "required": bool(f.get("required", False)),
                "hidden": bool(f.get("hidden", False)),
                "readonly": bool(f.get("readonly", f.get("readOnly", False))),
            }
            if database_field_type:
                field["databaseFieldType"] = str(database_field_type)
                field["database_field_type"] = str(database_field_type)
            if field_length not in (None, ""):
                field["maxLength"] = str(field_length)
                field["max_length"] = str(field_length)
                field["length"] = str(field_length)
            # 字典绑定
            if f.get("dictionaryCode"):
                field["dict"] = f["dictionaryCode"]
                field["dictCode"] = f["dictionaryCode"]
            # 关联模型
            if f.get("refModelCode"):
                field["ref"] = {
                    "model": f["refModelCode"],
                    "field": f.get("refFieldCode", ""),
                }
                field["refModelCode"] = f["refModelCode"]
                if f.get("refFieldCode"):
                    field["refFieldCode"] = f.get("refFieldCode", "")
                    field["refDisplayFieldCode"] = f.get("refFieldCode", "")
            if f.get("fieldComment") or f.get("comment") or f.get("description"):
                field["comment"] = f.get("fieldComment") or f.get("comment") or f.get("description")
                field["description"] = field["comment"]
            fields.append(field)

        models.append({
            "name": m.get("modelName", m.get("name", "")),
            "code": m.get("modelCode", m.get("code", "")),
            "description": m.get("modelDescription", m.get("description", "")),
            "table_type": m.get("tableType", m.get("table_type", "主表")),
            "tableType": m.get("tableType", m.get("table_type", "主表")),
            "parent_model_code": m.get("parentModelCode", m.get("parent_model_code", "")),
            "parentModelCode": m.get("parentModelCode", m.get("parent_model_code", "")),
            "fields": fields,
        })
    return models


# ---------------------------------------------------------------------------
# 完整反向解析（用于「从平台导入应用」功能）
# ---------------------------------------------------------------------------

async def sync_from_platform_full(
    client: APaaSClient,
    app_id: str,
    app_name: str = "",
) -> Dict[str, Any]:
    """从平台拉取完整状态（含表单配置），转为 config_preview 格式。

    相比 sync_from_platform()，额外调用 detailPageConfigById 获取：
    - 子表列定义、字段选项绑定、自动编号规则、required 状态
    - 角色权限配置
    """
    # 1. 基础数据
    remote = await fetch_remote_data(client, app_id)
    logger.info(
        f"完整反向解析: {len(remote.get('roles', []))} 角色, "
        f"{len(remote.get('dicts', []))} 字典, "
        f"{len(remote.get('models', []))} 模型"
    )

    # 2. 获取菜单列表 → formId
    menus = remote.get("forms", [])
    if not menus:
        menus = await client.query_menus(app_id)
    form_menus = [
        m for m in menus
        if m.get("menuType") == "MODEL" and m.get("formId")
    ]

    # 3. 逐个调用 detailPageConfigById
    form_configs: Dict[str, Dict] = {}
    for menu in form_menus:
        form_id = menu["formId"]
        try:
            fc = await client.query_detail_page_config(app_id, form_id)
            form_configs[form_id] = fc
            logger.info(f"获取表单配置: {menu.get('menuName', '')} formId={form_id}")
        except Exception as e:
            logger.warning(f"获取表单配置失败 formId={form_id}: {e}")

    # 4. 构建 config_preview
    roles = _convert_roles(remote.get("roles", []))
    role_lookup = _build_role_lookup(remote.get("roles", []))

    # 字典：优先从 detailPageConfigById 的 chooseOptions 提取（更完整），
    # 回退到 remote dicts
    dicts = _build_dicts_from_form_configs(
        form_configs, remote.get("dicts", []), remote.get("dict_options", {})
    )
    dict_id_to_code = _build_dict_id_map(form_configs, dicts)

    # 模型：直接走平台数据模型/字段接口，避免把表单结构误读成模型结构
    models = _convert_models(remote.get("models", []))
    forms = _build_forms_from_form_configs(form_configs, dict_id_to_code)

    # 权限
    permissions = _build_permissions_from_form_configs(form_configs, role_lookup)

    config: Dict[str, Any] = {
        "appName": app_name,
        "roles": roles,
        "dicts": dicts,
        "models": models,
        "forms": forms,
        "workflows": [],
        "permissions": permissions,
    }
    logger.info(
        f"完整反向解析完成: {len(roles)} 角色, {len(dicts)} 字典, "
        f"{len(models)} 模型, {len(forms)} 表单, {len(permissions)} 权限组"
    )
    return config


def _build_dict_id_map(
    form_configs: Dict[str, Dict],
    dicts: List[Dict],
) -> Dict[str, str]:
    """构建字典 source.id → dict_code 映射"""
    id_to_code: Dict[str, str] = {}
    # 从 form_configs 中提取 source.id → dictionaryCode 映射
    for fc in form_configs.values():
        components = fc.get("detailPage", {}).get("formComponents", [])
        for comp in components:
            _extract_dict_source_mapping(comp, id_to_code)
    return id_to_code


def _extract_dict_source_mapping(comp: Dict, id_to_code: Dict[str, str]):
    """递归提取组件中的 source.id → dict code 映射"""
    source = comp.get("source", {})
    if source.get("type") == "DICTIONARY_TYPE" and source.get("id"):
        # 从 boCode 中提取 dict code (e.g., "t_project~f_status" → 用 chooseOptions)
        bo_code = comp.get("boCode", "")
        model_field = comp.get("modelField", "")
        field_code = ""
        if "~" in bo_code:
            field_code = bo_code.split("~", 1)[1]
        elif "." in model_field:
            field_code = model_field.split(".", 1)[1]
        # 用 source.id 映射到字段名（后面用来关联字典 code）
        id_to_code[source["id"]] = field_code

    # 递归子表列
    for col in comp.get("tableColumn", []):
        _extract_dict_source_mapping(col, id_to_code)


def _build_dicts_from_form_configs(
    form_configs: Dict[str, Dict],
    remote_dicts: List[Dict],
    dict_options: Dict[str, List[Dict]],
) -> List[Dict]:
    """从 detailPageConfigById 的 chooseOptions 提取字典，合并 remote dicts。

    优先用 chooseOptions 中的选项（因为它已包含 label），
    remote_dicts 用于补充 code 信息。
    """
    # 先用基础 remote dicts 构建（有 dict code）
    seen_codes: Set[str] = set()
    dicts: List[Dict] = []
    remote_dict_id_to_code: Dict[str, str] = {}

    # 基础字典
    base_dicts = _convert_dicts(remote_dicts, dict_options)
    for raw in remote_dicts:
        raw_id = str(raw.get("id", raw.get("dictionaryId", ""))).strip()
        raw_code = str(raw.get("dictionaryCode", raw.get("code", ""))).strip()
        if raw_id and raw_code:
            remote_dict_id_to_code[raw_id] = raw_code
    for d in base_dicts:
        if d["code"] and d["code"] not in seen_codes:
            seen_codes.add(d["code"])
            dicts.append(d)
    dicts_by_code = {str(d.get("code", "")).strip(): d for d in dicts if str(d.get("code", "")).strip()}

    # 从 form_configs 补充：有些字典选项在 chooseOptions 里更完整
    for fc in form_configs.values():
        components = fc.get("detailPage", {}).get("formComponents", [])
        for comp in components:
            _enrich_dict_from_component(comp, dicts, dicts_by_code, remote_dict_id_to_code, seen_codes)

    return dicts


def _enrich_dict_from_component(
    comp: Dict,
    dicts: List[Dict],
    dicts_by_code: Dict[str, Dict],
    remote_dict_id_to_code: Dict[str, str],
    seen_codes: Set[str],
):
    """从组件的 chooseOptions 补充字典选项"""
    source = comp.get("source", {})
    choose_options = comp.get("chooseOptions", [])

    if source.get("type") == "DICTIONARY_TYPE" and choose_options:
        source_id = source.get("id", "")
        dict_code = remote_dict_id_to_code.get(str(source_id).strip(), "")
        if dict_code:
            target_dict = dicts_by_code.get(dict_code)
            if target_dict is None:
                target_dict = {
                    "name": comp.get("label", "") or dict_code,
                    "code": dict_code,
                    "options": [],
                }
                dicts.append(target_dict)
                dicts_by_code[dict_code] = target_dict
                seen_codes.add(dict_code)

            existing_codes = {str(o.get("code", "")).strip() for o in target_dict.get("options", [])}
            existing_names = {str(o.get("name", "")).strip() for o in target_dict.get("options", [])}
            for opt in choose_options:
                opt_code = str(
                    opt.get("valueCode")
                    or opt.get("code")
                    or opt.get("id")
                    or ""
                ).strip()
                opt_name = str(
                    opt.get("valueName")
                    or opt.get("label")
                    or opt.get("name")
                    or ""
                ).strip()
                if (opt_code and opt_code not in existing_codes) and (not opt_name or opt_name not in existing_names):
                    target_dict.setdefault("options", []).append({
                        "name": opt_name,
                        "code": opt_code,
                    })
                    if opt_code:
                        existing_codes.add(opt_code)
                    if opt_name:
                        existing_names.add(opt_name)

    # 递归子表列
    for col in comp.get("tableColumn", []):
        _enrich_dict_from_component(col, dicts, dicts_by_code, remote_dict_id_to_code, seen_codes)


def _resolve_component_model_code(comp: Dict, default_model_code: str = "") -> str:
    model_code = str(comp.get("modelCode", "")).strip()
    if model_code:
        return model_code
    model_field = str(comp.get("modelField", "")).strip()
    if "." in model_field:
        return model_field.split(".", 1)[0].strip()
    bo_code = str(comp.get("boCode", "")).strip()
    if "~" in bo_code:
        return bo_code.split("~", 1)[0].strip()
    return str(default_model_code or "").strip()


def _extract_field_code(comp: Dict) -> str:
    bo_code = str(comp.get("boCode", "")).strip()
    model_field = str(comp.get("modelField", "")).strip()
    if "~" in bo_code:
        return bo_code.split("~", 1)[1].strip()
    if "." in model_field:
        return model_field.split(".", 1)[1].strip()
    return ""


def _extract_field_length(
    comp: Dict,
    field_meta: Optional[Dict[str, Any]],
) -> Optional[str]:
    candidates = [
        field_meta.get("maxLength") if isinstance(field_meta, dict) else None,
        field_meta.get("length") if isinstance(field_meta, dict) else None,
        field_meta.get("dataLength") if isinstance(field_meta, dict) else None,
        comp.get("maxLength"),
        comp.get("length"),
        comp.get("lengthLimit"),
    ]
    for candidate in candidates:
        if candidate in (None, "", "-", "null"):
            continue
        return str(candidate)
    return None


def _extract_database_field_type(
    field_meta: Optional[Dict[str, Any]],
) -> str:
    if not isinstance(field_meta, dict):
        return ""
    return str(
        field_meta.get("databaseFieldType")
        or field_meta.get("database_field_type")
        or field_meta.get("dbType")
        or field_meta.get("fieldType")
        or ""
    ).strip()


def _extract_single_field(
    comp: Dict,
    dict_id_to_code: Dict[str, str],
    platform_field_meta: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
    model_code_override: str = "",
) -> Optional[Dict]:
    """从单个 formComponent 提取字段信息"""
    comp_type = comp.get("componentType", "")
    if not comp_type or comp_type == "FORM_WIDGET_SON_TABLE":
        return None

    field_code = _extract_field_code(comp)
    model_code = _resolve_component_model_code(comp, model_code_override)

    if not field_code:
        return None

    # 跳过系统字段
    if field_code.lower() in _SKIP_FIELDS:
        return None

    choose_type = comp.get("chooseType", "")
    field_type = _guess_field_type(comp_type, "", choose_type)
    field_meta = (
        (platform_field_meta or {}).get(model_code, {}).get(field_code, {})
        if model_code
        else {}
    )

    field: Dict[str, Any] = {
        "name": comp.get("label", ""),
        "code": field_code,
        "type": field_type,
        "required": comp.get("required", False),
        "hidden": comp.get("hidden", False),
        "readonly": comp.get("readOnly", False),
    }
    database_field_type = _extract_database_field_type(field_meta)
    if database_field_type:
        field["databaseFieldType"] = database_field_type
        field["database_field_type"] = database_field_type
    field_length = _extract_field_length(comp, field_meta)
    if field_length:
        field["maxLength"] = field_length
        field["max_length"] = field_length
        field["length"] = field_length

    # 字典绑定：从 source.type=DICTIONARY_TYPE 提取
    source = comp.get("source", {})
    if source.get("type") == "DICTIONARY_TYPE" and source.get("id"):
        # 查找字典 code（从 chooseOptions 中推断）
        dict_code = dict_id_to_code.get(source["id"], "")
        if dict_code:
            field["dict"] = dict_code

    # 人员选择的 bocCode
    boc_code = comp.get("bocCode", "")
    if boc_code == "boc_code_object_user":
        field["type"] = "人员选择"

    association = comp.get("formAssociationConfig", {})
    if comp_type == "FORM_ASSOCIATION" and isinstance(association, dict):
        target_model = association.get("targetModelCode", "")
        target_field = association.get("targetFieldCode", "")
        origin_field = association.get("originFieldCode", field_code)
        if target_model:
            field["formAssociationConfig"] = {
                "originFieldCode": origin_field,
                "targetModelCode": target_model,
                "targetFieldCode": target_field,
            }
            field["ref"] = {
                "model": target_model,
                "field": origin_field,
                "display_field": target_field,
                "target_field": target_field,
            }

    return field


def _build_form_component(
    comp: Dict,
    dict_id_to_code: Dict[str, str],
    model_code_override: str = "",
    section_type: str = "main",
    sub_table_label: str = "",
) -> Optional[Dict[str, Any]]:
    comp_type = str(comp.get("componentType", "")).strip()
    if not comp_type or comp_type == "FORM_WIDGET_SON_TABLE":
        return None

    field_code = _extract_field_code(comp)
    model_code = _resolve_component_model_code(comp, model_code_override)
    if not field_code or not model_code:
        return None

    component: Dict[str, Any] = {
        "code": field_code,
        "label": comp.get("label", "") or field_code,
        "componentType": comp_type,
        "modelField": f"{model_code}.{field_code}",
        "modelCode": model_code,
        "sectionType": section_type,
        "hidden": bool(comp.get("hidden", False)),
        "readonly": bool(comp.get("readOnly", False)),
        "required": bool(comp.get("required", False)),
        "showInList": bool(comp.get("showInList", False)),
        "searchable": bool(comp.get("queryable", comp.get("searchable", False))),
    }
    if section_type == "sub":
        component["tableModelCode"] = model_code
        if sub_table_label:
            component["subTableLabel"] = sub_table_label

    source = comp.get("source", {})
    if source.get("type") == "DICTIONARY_TYPE" and source.get("id"):
        dict_code = dict_id_to_code.get(str(source.get("id")), "")
        if dict_code:
            component["dict"] = dict_code
            component["dictCode"] = dict_code

    extracted = _extract_single_field(
        comp,
        dict_id_to_code,
        model_code_override=model_code,
    )
    if extracted and extracted.get("ref"):
        component["ref"] = extracted["ref"]
        ref = extracted["ref"]
        if ref.get("model"):
            component["ref_model_code"] = ref.get("model")
        display_field = ref.get("display_field") or ref.get("target_field") or ref.get("field")
        if display_field:
            component["ref_display_field_code"] = display_field
            component["selector_field_code"] = display_field
    if extracted and extracted.get("formAssociationConfig"):
        association = extracted["formAssociationConfig"]
        component["formAssociationConfig"] = association
        component["association_form_code"] = association.get("targetModelCode", "")
        component["association_origin_field_code"] = association.get("originFieldCode", "")
        component["association_target_field_code"] = association.get("targetFieldCode", "")

    if comp_type in {"FORM_DATA_SELECTOR", "FORM_DATA_SELECTOR_SINGLE"} and component.get("ref_model_code"):
        component["selector_form_code"] = component.get("ref_model_code")

    description = str(comp.get("titleDescription", "") or "").strip()
    if description:
        component["description"] = description

    return component


def _build_forms_from_form_configs(
    form_configs: Dict[str, Dict],
    dict_id_to_code: Dict[str, str],
) -> List[Dict]:
    forms: List[Dict] = []
    seen_form_codes: Set[str] = set()

    for fc in form_configs.values():
        form_name = str(fc.get("formName", "")).strip()
        form_code = str(fc.get("formCode", "") or fc.get("code", "") or fc.get("id", "")).strip()
        model_code = str(fc.get("modelCode", "")).strip()
        components = fc.get("detailPage", {}).get("formComponents", []) or []
        if not form_name or not model_code:
            continue

        resolved_form_code = form_code or model_code
        if resolved_form_code in seen_form_codes:
            continue
        seen_form_codes.add(resolved_form_code)

        built_components: List[Dict[str, Any]] = []
        for comp in components:
            if comp.get("componentType") == "FORM_WIDGET_SON_TABLE":
                sub_model_code = str(comp.get("tableModelCode", "")).strip()
                sub_table_label = str(comp.get("label", "")).strip()
                table_columns: List[Dict[str, Any]] = []
                for col in comp.get("tableColumn", []) or []:
                    built_col = _build_form_component(
                        col,
                        dict_id_to_code,
                        model_code_override=sub_model_code,
                        section_type="sub",
                        sub_table_label=sub_table_label,
                    )
                    if built_col:
                        table_columns.append(built_col)
                built_components.append({
                    "code": f"sub_{sub_model_code}" if sub_model_code else sub_table_label,
                    "label": sub_table_label or sub_model_code,
                    "componentType": "FORM_WIDGET_SON_TABLE",
                    "tableModelCode": sub_model_code,
                    "sectionType": "sub",
                    "required": bool(comp.get("required", False)),
                    "hidden": bool(comp.get("hidden", False)),
                    "readonly": bool(comp.get("readOnly", False)),
                    "showInList": False,
                    "searchable": False,
                    "subTableLabel": sub_table_label or sub_model_code,
                    "tableColumn": table_columns,
                })
                continue

            built = _build_form_component(
                comp,
                dict_id_to_code,
                model_code_override=model_code,
                section_type="main",
            )
            if built:
                built_components.append(built)

        forms.append({
            "name": form_name,
            "code": resolved_form_code,
            "formName": form_name,
            "formCode": resolved_form_code,
            "modelCode": model_code,
            "allModelCodes": list({
                model_code,
                *[
                    str(component.get("tableModelCode", "")).strip()
                    for component in built_components
                    if str(component.get("componentType", "")).strip() == "FORM_WIDGET_SON_TABLE"
                ],
            } - {""}),
            "components": built_components,
        })

    return forms


def _build_permissions_from_form_configs(
    form_configs: Dict[str, Dict],
    role_lookup: Dict[str, Dict[str, str]],
) -> List[Dict]:
    """从 advancedPermissionGroups + operationPermissionGroups 提取权限"""
    permissions: List[Dict] = []

    for form_id, fc in form_configs.items():
        form_name = fc.get("formName", "")
        model_code = fc.get("modelCode", "")
        if not form_name:
            form_name = model_code

        rules: List[Dict] = []

        # 数据权限
        for pg in fc.get("advancedPermissionGroups", []):
            ops = pg.get("permissionOperationType", {})
            enabled_ops = [
                _OP_MAP.get(k, k) for k, v in ops.items()
                if v is True and k in _OP_MAP
            ]
            if not enabled_ops:
                continue

            for po in pg.get("permissionObjects", []):
                obj_type = po.get("permissionObjectType", "")
                obj_value = po.get("permissionObjectValue", "")
                range_type = po.get("permissionRange", {}).get("rangeType", "ALL")

                role_code = ""
                role_name = ""
                if obj_type == "ALL_USER":
                    role_code = "ALL_USER"
                    role_name = "全部人员"
                elif obj_type in {"ROLE_USER", "ROLE"}:
                    role_info = _find_role_info(obj_value, role_lookup)
                    role_code = role_info.get("code", "")
                    role_name = role_info.get("name", role_code)

                if role_code:
                    op_str = "all" if len(enabled_ops) >= 4 else ",".join(enabled_ops)
                    rules.append({
                        "role": role_code,
                        "role_code": role_code,
                        "role_name": role_name or role_code,
                        "op": op_str,
                        "data": _RANGE_MAP.get(range_type, range_type),
                    })

        # 操作权限
        for pg in fc.get("operationPermissionGroups", []):
            ops = pg.get("permissionOperationType", {})
            enabled_ops = [
                _OP_MAP.get(k, k) for k, v in ops.items()
                if v is True and k in _OP_MAP
            ]
            if not enabled_ops:
                continue

            for po in pg.get("permissionObjects", []):
                obj_type = po.get("permissionObjectType", "")
                obj_value = po.get("permissionObjectValue", "")

                role_code = ""
                role_name = ""
                if obj_type == "ALL_USER":
                    role_code = "ALL_USER"
                    role_name = "全部人员"
                elif obj_type in {"ROLE_USER", "ROLE"}:
                    role_info = _find_role_info(obj_value, role_lookup)
                    role_code = role_info.get("code", "")
                    role_name = role_info.get("name", role_code)

                if role_code:
                    # 检查是否已有该角色的规则，合并
                    existing = next(
                        (r for r in rules if (r.get("role_code") or r.get("role")) == role_code), None
                    )
                    if existing:
                        existing_ops = set(existing["op"].split(","))
                        existing_ops.update(enabled_ops)
                        existing["op"] = ",".join(existing_ops)
                        if role_name and not existing.get("role_name"):
                            existing["role_name"] = role_name
                    else:
                        rules.append({
                            "role": role_code,
                            "role_code": role_code,
                            "role_name": role_name or role_code,
                            "op": ",".join(enabled_ops),
                            "data": "ALL",
                        })

        if rules:
            permissions.append({
                "form": form_name,
                "rules": rules,
            })

    return permissions


def _find_role_info(role_ref: str, role_lookup: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    """通过角色 id/code/name 查找角色信息，尽量还原为稳定的 code/name。"""
    normalized = str(role_ref or "").strip()
    if not normalized:
        return {}
    return role_lookup.get(normalized, {
        "id": normalized,
        "code": normalized,
        "name": normalized,
    })
