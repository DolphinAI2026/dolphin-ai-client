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
    "copyAddPermission": "复制新增",
    "batchDeletePermission": "批量删除",
    "batchRejectPermission": "批量拒绝",
    "batchAgreePermission": "批量同意",
    "temporaryStoragePermission": "暂存",
    "shareFormPermission": "分享",
    "exportPermission": "导出",
    "printPermission": "打印",
    "queryApprovalInfoPermission": "查看审批历史",
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


def _convert_dicts(remote_dicts: List[Dict], dict_options: Dict[str, List[Dict]]) -> List[Dict]:
    """平台字典 → preview 字典

    dict_options 的 key 可能是 dict_code 或 dict_id，两个都尝试匹配。
    """
    dicts = []
    for d in remote_dicts:
        dict_id = str(d.get("id", d.get("dictionaryId", "")))
        dict_code = d.get("dictionaryCode", d.get("code", ""))
        options = []
        # dict_options 的 key 可能是 code（fetch_remote_data 用 code 存）
        # 也可能是 id，两个都尝试
        raw_options = (
            dict_options.get(dict_code, [])
            or dict_options.get(dict_id, [])
        )
        for opt in raw_options:
            options.append({
                "name": opt.get("dictionaryValue", opt.get("name", "")),
                "code": opt.get("dictionaryValueCode", opt.get("code", "")),
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
            field = {
                "name": f.get("fieldName", ""),
                "code": f.get("fieldCode", f.get("code", "")),
                "type": _guess_field_type(
                    f.get("componentType", ""),
                    f.get("fieldType", ""),
                ),
                "required": f.get("required", False),
            }
            # 字典绑定
            if f.get("dictionaryCode"):
                field["dict"] = f["dictionaryCode"]
            # 关联模型
            if f.get("refModelCode"):
                field["ref"] = {
                    "model": f["refModelCode"],
                    "field": f.get("refFieldCode", ""),
                }
            fields.append(field)

        models.append({
            "name": m.get("modelName", m.get("name", "")),
            "code": m.get("modelCode", m.get("code", "")),
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
    role_code_map = {r.get("roleCode", ""): r.get("roleName", "") for r in remote.get("roles", [])}

    # 字典：优先从 detailPageConfigById 的 chooseOptions 提取（更完整），
    # 回退到 remote dicts
    dicts = _build_dicts_from_form_configs(
        form_configs, remote.get("dicts", []), remote.get("dict_options", {})
    )
    dict_id_to_code = _build_dict_id_map(form_configs, dicts)

    # 模型：从 detailPageConfigById 提取（含子表、required、选项绑定）
    models = _build_models_from_form_configs(form_configs, dict_id_to_code)

    # 权限
    permissions = _build_permissions_from_form_configs(form_configs, role_code_map)

    config: Dict[str, Any] = {
        "appName": app_name,
        "roles": roles,
        "dicts": dicts,
        "models": models,
        "workflows": [],
        "permissions": permissions,
    }
    logger.info(
        f"完整反向解析完成: {len(roles)} 角色, {len(dicts)} 字典, "
        f"{len(models)} 模型, {len(permissions)} 权限组"
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

    策略：
    1. 先从 remote_dicts + dict_options 构建基础字典列表
    2. 建立 source_id → dict_code 映射
    3. 遍历 form_configs 的组件，用 chooseOptions 补充空选项
    """
    # 1. 基础字典
    seen_codes: Set[str] = set()
    dicts: List[Dict] = []
    base_dicts = _convert_dicts(remote_dicts, dict_options)
    for d in base_dicts:
        if d["code"] and d["code"] not in seen_codes:
            seen_codes.add(d["code"])
            dicts.append(d)

    # 2. 建立 source_id → dict_code 映射（用于精准匹配 chooseOptions）
    source_id_to_dict: Dict[str, str] = {}
    for rd in remote_dicts:
        rid = str(rd.get("id", rd.get("dictionaryId", "")))
        rcode = rd.get("dictionaryCode", rd.get("code", ""))
        if rid and rcode:
            source_id_to_dict[rid] = rcode

    # 3. 遍历 form_configs 组件，用 chooseOptions 补充选项
    for fc in form_configs.values():
        components = fc.get("detailPage", {}).get("formComponents", [])
        for comp in components:
            _enrich_dict_from_component(comp, dicts, seen_codes, source_id_to_dict)

    return dicts


def _enrich_dict_from_component(
    comp: Dict, dicts: List[Dict], seen_codes: Set[str],
    source_id_to_dict: Dict[str, str],
):
    """从组件的 chooseOptions 补充字典选项。

    通过 source.id → dict_code 精准匹配到字典，再用 chooseOptions 填充选项。
    """
    source = comp.get("source", {})
    choose_options = comp.get("chooseOptions", [])

    if source.get("type") == "DICTIONARY_TYPE" and choose_options:
        source_id = str(source.get("id", ""))
        # 从 chooseOptions 提取选项列表
        new_options = [
            {"name": opt.get("label", ""), "code": opt.get("id", "")}
            for opt in choose_options
            if opt.get("id") and opt.get("label")
        ]
        if new_options:
            # 通过 source_id 精准匹配到 dict_code
            target_code = source_id_to_dict.get(source_id, "")
            matched = False
            for d in dicts:
                if target_code and d["code"] == target_code:
                    # 精准匹配 → 补充选项
                    if not d.get("options"):
                        d["options"] = new_options
                    else:
                        existing = {o["code"] for o in d["options"]}
                        for opt in new_options:
                            if opt["code"] not in existing:
                                d["options"].append(opt)
                                existing.add(opt["code"])
                    matched = True
                    break

            if not matched and target_code:
                # 字典列表里没有这个 code（不该发生），创建新的
                if target_code not in seen_codes:
                    seen_codes.add(target_code)
                    dicts.append({
                        "name": comp.get("label", target_code),
                        "code": target_code,
                        "options": new_options,
                    })

    # 递归子表列
    for col in comp.get("tableColumn", []):
        _enrich_dict_from_component(col, dicts, seen_codes, source_id_to_dict)


def _build_models_from_form_configs(
    form_configs: Dict[str, Dict],
    dict_id_to_code: Dict[str, str],
) -> List[Dict]:
    """从 detailPageConfigById 构建模型列表（含子表）"""
    models: List[Dict] = []
    seen_model_codes: Set[str] = set()

    for form_id, fc in form_configs.items():
        components = fc.get("detailPage", {}).get("formComponents", [])
        model_code = fc.get("modelCode", "")
        form_name = fc.get("formName", "")

        if not model_code or model_code in seen_model_codes:
            continue
        seen_model_codes.add(model_code)

        # 从 modelWithFieldVoList 找主模型信息
        model_vo_list = fc.get("modelWithFieldVoList", [])
        main_model_vo = None
        sub_model_map: Dict[str, Dict] = {}
        for mv in model_vo_list:
            if mv.get("mainModel"):
                main_model_vo = mv
            else:
                sub_model_map[mv.get("modelCode", "")] = mv

        model_name = ""
        if main_model_vo:
            model_name = main_model_vo.get("modelName", form_name)
        else:
            model_name = form_name

        # 构建主表字段 + 子表
        fields: List[Dict] = []
        for comp in components:
            if comp.get("componentType") == "FORM_WIDGET_SON_TABLE":
                # 子表 → sub_code + sub_fields
                sub_model_code = comp.get("tableModelCode", "")
                sub_fields = _extract_fields_from_components(
                    comp.get("tableColumn", []), dict_id_to_code
                )
                if sub_fields:
                    fields.append({
                        "name": comp.get("label", ""),
                        "code": f"sub_{sub_model_code}" if sub_model_code else comp.get("label", ""),
                        "type": "子表",
                        "icon": "▦",
                        "required": comp.get("required", False),
                        "sub_code": sub_model_code,
                        "sub_fields": sub_fields,
                    })
            else:
                field = _extract_single_field(comp, dict_id_to_code)
                if field:
                    fields.append(field)

        models.append({
            "name": model_name,
            "code": model_code,
            "fields": fields,
        })

    return models


def _extract_fields_from_components(
    components: List[Dict],
    dict_id_to_code: Dict[str, str],
) -> List[Dict]:
    """从组件列表提取字段列表"""
    fields: List[Dict] = []
    for comp in components:
        field = _extract_single_field(comp, dict_id_to_code)
        if field:
            fields.append(field)
    return fields


def _extract_single_field(
    comp: Dict,
    dict_id_to_code: Dict[str, str],
) -> Optional[Dict]:
    """从单个 formComponent 提取字段信息"""
    comp_type = comp.get("componentType", "")
    if not comp_type or comp_type == "FORM_WIDGET_SON_TABLE":
        return None

    # 提取 field code
    bo_code = comp.get("boCode", "")
    model_field = comp.get("modelField", "")
    field_code = ""
    if "~" in bo_code:
        field_code = bo_code.split("~", 1)[1]
    elif "." in model_field:
        field_code = model_field.split(".", 1)[1]

    if not field_code:
        return None

    # 跳过系统字段
    if field_code.lower() in _SKIP_FIELDS:
        return None

    choose_type = comp.get("chooseType", "")
    field_type = _guess_field_type(comp_type, "", choose_type)

    field: Dict[str, Any] = {
        "name": comp.get("label", ""),
        "code": field_code,
        "type": field_type,
        "required": comp.get("required", False),
    }

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

    return field


def _build_permissions_from_form_configs(
    form_configs: Dict[str, Dict],
    role_code_map: Dict[str, str],
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
                if obj_type == "ALL_USER":
                    role_code = "ALL_USER"
                elif obj_type == "ROLE_USER":
                    # 通过 role id 查找 role code
                    role_code = _find_role_code_by_id(obj_value, role_code_map)

                if role_code:
                    op_str = "all" if len(enabled_ops) >= 4 else ",".join(enabled_ops)
                    rules.append({
                        "role": role_code,
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
                if obj_type == "ALL_USER":
                    role_code = "ALL_USER"
                elif obj_type == "ROLE_USER":
                    role_code = _find_role_code_by_id(obj_value, role_code_map)

                if role_code:
                    # 检查是否已有该角色的规则，合并
                    existing = next(
                        (r for r in rules if r["role"] == role_code), None
                    )
                    if existing:
                        existing_ops = set(existing["op"].split(","))
                        existing_ops.update(enabled_ops)
                        existing["op"] = ",".join(existing_ops)
                    else:
                        rules.append({
                            "role": role_code,
                            "op": ",".join(enabled_ops),
                            "data": "ALL",
                        })

        if rules:
            permissions.append({
                "form": form_name,
                "rules": rules,
            })

    return permissions


def _find_role_code_by_id(role_id: str, role_code_map: Dict[str, str]) -> str:
    """通过角色 ID 查找角色 code（role_code_map key 是 roleCode，但权限中用的是 role ID）"""
    # advancedPermissionGroups 中 permissionObjectValue 是角色的 id（数字），
    # 不是 roleCode。我们需要在 roles 数据中做反向映射。
    # 由于我们没有 id→code 的直接映射，先返回 role_id 作为 fallback
    return role_id
