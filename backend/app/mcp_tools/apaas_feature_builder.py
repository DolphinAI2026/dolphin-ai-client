"""SPEC-driven aPaaS feature scaffolding MCP tool."""
from __future__ import annotations

from datetime import datetime

from app.field_types import select_choose_type_for_component
from app.mcp_tools.apaas_form_tools import _build_perm_payload_from_simple_rules
from app.step_executor import _apply_dictionary_binding_to_component


class _StaticToolMarker:
    """No-op decorator used so static registry tests can see tool functions."""

    def tool(self):
        def _decorate(fn):
            return fn

        return _decorate


mcp = _StaticToolMarker()

_with_client = None
set_apaas_app_process = None

# ═══════════════════════════════════════════════════════════════════════════
# 2026-05-25: SPEC 驱动的"加新表单+流程"一键工具.
# 借鉴 super-agents-dev AIAssistantService.formDesign — AI 先生 SPEC 给用户审,
# 用户同意后调本工具一把建好 模型+表单+菜单+(可选)流程. 不走全量 SPEC 重新部署,
# 只增量加这一个 feature.
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_field_type(field: dict) -> tuple[str, str]:
    """从字段规格里反推 (component_type, data_model_type).

    走 app.field_types 单一真相源 — 跟 Builder 创建应用同款 SPEC 规范.
    返回值:
      - component_type: FORM_TEXT_INPUT / FORM_TEXTAREA_INPUT / FORM_NUMBER_INPUT / ...
      - data_model_type: STRING / BIG_TEXT / NUM / DATE / ... (平台 fieldType 字段)

    支持的输入形式:
      - {"type": "单行输入" | "多行输入" | "数字" | ... } — 标准中文 (FIELD_TYPES key)
      - {"type": "长文本" | "备注" | ... } — 别名 (_TYPE_ALIASES) 自动规范化
      - {"componentType": "FORM_TEXT_INPUT"} — 直给组件类型
      - {"database_field_type": "varchar" | "text" | ...} — DB 类型兜底 (_DB_TYPE_MAP)
      - 默认 单行输入 (FORM_TEXT_INPUT + STRING)
    """
    from app.field_types import (
        FIELD_TYPES, get_all_types, get_type_aliases, get_db_type_map,
    )
    all_types = get_all_types()  # FIELD_TYPES + _COMPAT_TYPES
    aliases = get_type_aliases()
    db_map = get_db_type_map()

    # 1. 显式中文 type — 最常用
    t = (field.get("type") or "").strip()
    if t:
        # 直接命中
        if t in all_types:
            info = all_types[t]
            return info.component_type, info.data_model_type
        # 别名表 → 规范化
        if t in aliases:
            std = aliases[t]
            if std in all_types:
                info = all_types[std]
                return info.component_type, info.data_model_type
        # DB 类型兜底 (varchar / int / etc)
        tl = t.lower()
        if tl in db_map:
            std = db_map[tl]
            if std in all_types:
                info = all_types[std]
                return info.component_type, info.data_model_type

    # 2. componentType 反查
    comp = (field.get("componentType") or field.get("component_type") or "").strip()
    if comp:
        for info in all_types.values():
            if info.component_type == comp:
                return comp, info.data_model_type

    # 3. database_field_type DB 类型 (varchar / longtext / int / ...)
    dbt = (field.get("database_field_type") or field.get("databaseFieldType") or "").strip().lower()
    if dbt and dbt in db_map:
        std = db_map[dbt]
        if std in all_types:
            info = all_types[std]
            return info.component_type, info.data_model_type

    # fallback 单行输入
    info = FIELD_TYPES["单行输入"]
    return info.component_type, info.data_model_type


def _model_field_suffix(model_field: str) -> str:
    text = str(model_field or "").strip()
    return text.split(".", 1)[1] if "." in text else text


def _find_component_by_field_or_label(components: list, *, field_code: str = "", label: str = "") -> dict | None:
    field_code = str(field_code or "").strip()
    label = str(label or "").strip()
    for comp in components or []:
        if not isinstance(comp, dict):
            continue
        model_field = str(comp.get("modelField") or "").strip()
        if field_code and (
            model_field.endswith(f".{field_code}")
            or _model_field_suffix(model_field) == field_code
            or str(comp.get("fieldCode") or comp.get("code") or "").strip() == field_code
        ):
            return comp
        if label and str(comp.get("label") or comp.get("name") or "").strip() == label:
            return comp
    return None


def _iter_form_components(form_config: dict) -> list:
    groups = []
    for candidate in (
        (form_config.get("detailPage") or {}).get("formComponents"),
        form_config.get("components"),
        form_config.get("formComponents"),
    ):
        if isinstance(candidate, list):
            groups.append(candidate)
    return groups


def _build_display_component_refs(target_components: list, display_field_codes: list[str]) -> list[dict]:
    refs: list[dict] = []
    for field_code in display_field_codes:
        comp = _find_component_by_field_or_label(target_components, field_code=field_code)
        if not comp:
            continue
        comp_id = str(comp.get("uuid") or comp.get("id") or "").strip()
        if not comp_id:
            continue
        refs.append({
            "id": comp_id,
            "name": comp.get("label") or comp.get("name") or field_code,
            "componentType": comp.get("componentType") or "FORM_TEXT_INPUT",
        })
    return refs


def _extract_ref_target(field: dict) -> tuple[str, str]:
    ref = field.get("ref") or {}
    target_model = (
        field.get("ref_model_code") or field.get("refModelCode")
        or field.get("target_model_code") or field.get("targetModelCode")
        or (ref.get("model") if isinstance(ref, dict) else "")
        or ""
    )
    target_field = (
        field.get("ref_display_field_code") or field.get("refDisplayFieldCode")
        or field.get("target_field_code") or field.get("targetFieldCode")
        or (ref.get("field") if isinstance(ref, dict) else "")
        or ""
    )
    return str(target_model).strip(), str(target_field).strip()


def _default_feature_permission_rules(roles: list) -> list[dict]:
    rules = [{
        "subject_type": "ALL_USER",
        "subject_name": "全部人员",
        "actions": ["all"],
        "range_type": "ALL",
    }]
    for role in roles or []:
        if not isinstance(role, dict):
            continue
        role_name = str(role.get("roleName") or role.get("role_name") or role.get("name") or "").strip()
        role_code = str(role.get("roleCode") or role.get("role_code") or role.get("code") or "").strip()
        role_id = str(role.get("id") or role.get("roleId") or "").strip()
        marker = f"{role_name} {role_code}".lower()
        if role_id and any(token in marker for token in ("admin", "管理员", "管理")):
            rules.append({
                "subject_type": "ROLE_USER",
                "subject_value": role_id,
                "subject_name": role_name or role_code or "管理员",
                "actions": ["all"],
                "range_type": "ALL",
            })
    return rules


async def _post_configure_feature_form_quality(
    client,
    *,
    app_id: str,
    form_id: str,
    form_code: str,
    fields: list,
    field_to_dict_code: dict,
) -> dict:
    result = {
        "dict_bound": 0,
        "data_selector_bound": 0,
        "permissions_configured": False,
        "warnings": [],
    }
    if not form_id:
        result["warnings"].append("form_id 为空，无法后处理表单配置")
        return result

    dict_codes = {code for code in field_to_dict_code.values() if code}
    for field in fields:
        if isinstance(field, dict):
            direct_dict = str(field.get("dict_code") or field.get("dictCode") or field.get("dictionaryCode") or "").strip()
            if direct_dict:
                dict_codes.add(direct_dict)
    if dict_codes:
        try:
            all_dicts = await client.query_dicts(app_id)
            dict_by_code = {
                str(d.get("dictionaryCode") or "").strip(): d
                for d in (all_dicts or [])
                if isinstance(d, dict)
            }
            options_by_code: dict[str, list] = {}
            for dict_code in dict_codes:
                dict_id = str((dict_by_code.get(dict_code) or {}).get("id") or "").strip()
                if dict_id:
                    options_by_code[dict_code] = await client.query_dict_options(app_id, dict_id)

            form_config = await client.query_form_config(app_id, form_id)
            updated = False
            for field in fields:
                if not isinstance(field, dict):
                    continue
                fcode = str(field.get("code") or "").strip()
                dict_code = field_to_dict_code.get(fcode) or str(field.get("dict_code") or field.get("dictCode") or "").strip()
                dict_id = str((dict_by_code.get(dict_code) or {}).get("id") or "").strip()
                if not dict_code or not dict_id:
                    continue
                for group in _iter_form_components(form_config):
                    comp = _find_component_by_field_or_label(
                        group,
                        field_code=fcode,
                        label=str(field.get("name") or ""),
                    )
                    if comp and _apply_dictionary_binding_to_component(
                        comp,
                        dict_code,
                        dict_id,
                        options_by_code.get(dict_code, []),
                    ):
                        updated = True
                        result["dict_bound"] += 1
            if updated:
                await client.save_form_config(app_id, form_config)
        except Exception as exc:
            result["warnings"].append(f"字典选项回写失败: {exc}")

    ref_fields: list[dict] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        comp_type, _ = _normalize_field_type(field)
        if comp_type in {"FORM_DATA_SELECTOR_SINGLE", "FORM_DATA_SELECTOR"}:
            ref_fields.append(field)

    if ref_fields:
        try:
            form_menus = await client.list_form_menus_for_event(app_id)
            target_by_model: dict[str, dict] = {}
            for menu in form_menus or []:
                target_form_id = str((menu or {}).get("form_id") or "").strip()
                if not target_form_id or target_form_id == form_id:
                    continue
                try:
                    detail = await client.query_detail_page_config(app_id, target_form_id)
                except Exception:
                    continue
                target_model_code = str(detail.get("modelCode") or detail.get("mainModelCode") or "").strip()
                if target_model_code:
                    target_by_model[target_model_code] = {
                        "form_id": target_form_id,
                        "form_name": detail.get("formName") or (menu or {}).get("menu_name") or "",
                        "detail": detail,
                    }
                for model_code in detail.get("allModelCodes") or []:
                    if model_code and model_code not in target_by_model:
                        target_by_model[str(model_code)] = {
                            "form_id": target_form_id,
                            "form_name": detail.get("formName") or (menu or {}).get("menu_name") or "",
                            "detail": detail,
                        }

            current_detail = await client.query_detail_page_config(app_id, form_id)
            current_components = (current_detail.get("detailPage") or {}).get("formComponents") or []
            updated = False
            for field in ref_fields:
                fcode = str(field.get("code") or "").strip()
                fname = str(field.get("name") or "").strip()
                target_model, target_field = _extract_ref_target(field)
                target = target_by_model.get(target_model)
                if not target:
                    result["warnings"].append(f"字段「{fname}」未找到目标表单: {target_model}")
                    continue
                target_components = (target["detail"].get("detailPage") or {}).get("formComponents") or []
                target_component = _find_component_by_field_or_label(target_components, field_code=target_field)
                if not target_component:
                    result["warnings"].append(f"字段「{fname}」未找到目标显示字段: {target_model}.{target_field}")
                    continue
                component = _find_component_by_field_or_label(current_components, field_code=fcode, label=fname)
                if not component:
                    result["warnings"].append(f"字段「{fname}」未找到当前表单组件")
                    continue
                target_comp_id = str(target_component.get("uuid") or target_component.get("id") or "").strip()
                desired_selector = {
                    "type": "LOV_CHOOSE",
                    "otherFormId": target["form_id"],
                    "otherFormName": target["form_name"],
                    "otherComponent": target_comp_id,
                    "otherComponentName": target_component.get("label") or target_field,
                    "otherComponentType": target_component.get("componentType") or "FORM_TEXT_INPUT",
                    "displayComponents": _build_display_component_refs(target_components, [target_field]) or [{
                        "id": target_comp_id,
                        "name": target_component.get("label") or target_field,
                        "componentType": target_component.get("componentType") or "FORM_TEXT_INPUT",
                    }],
                }
                comp_type, _ = _normalize_field_type(field)
                changed = False
                if component.get("componentType") != comp_type:
                    component["componentType"] = comp_type
                    changed = True
                if component.get("dataSelector") != desired_selector:
                    component["dataSelector"] = desired_selector
                    changed = True
                bof_type = "BOF_SINGLE_DATA_SELECTOR" if comp_type == "FORM_DATA_SELECTOR_SINGLE" else "BOF_DATA_SELECTOR"
                if component.get("businessObjectComponentType") != bof_type:
                    component["businessObjectComponentType"] = bof_type
                    changed = True
                if component.get("placeholder") != "请选择":
                    component["placeholder"] = "请选择"
                    changed = True
                for stale_key in (
                    "associationFormId", "associationField", "displayFields", "displayStyle",
                    "quoteViewType", "assocAllowNew", "assocTabId", "tableOrders",
                    "formAssociationConfig", "dataSelectorConfig",
                ):
                    if stale_key in component:
                        component.pop(stale_key, None)
                        changed = True
                if changed:
                    updated = True
                    result["data_selector_bound"] += 1
            if updated:
                await client.save_form_config(app_id, current_detail)
        except Exception as exc:
            result["warnings"].append(f"数据选择回写失败: {exc}")

    try:
        roles = await client.query_roles(app_id)
        permission_rules = _default_feature_permission_rules(roles)
        payload = _build_perm_payload_from_simple_rules(app_id, form_code, form_id, permission_rules)
        await client.create_form_permissions(app_id, [payload])
        result["permissions_configured"] = True
        result["permission_rules_count"] = len(permission_rules)
    except Exception as exc:
        result["warnings"].append(f"默认权限配置失败: {exc}")

    return result


@mcp.tool()
async def build_apaas_feature_from_spec(
    env_id: int,
    apaas_app_id: str,
    feature_name: str,
    feature_code: str,
    fields: list,
    process_stages: list | None = None,
    parent_menu_id: str = "",
) -> dict:
    """⭐ 一键建新表单+流程 (走 SPEC 驱动). 用户最高频"加新功能"场景.

    AI 先生 SPEC 给用户看 → 用户同意 → AI 调本工具 → 一次性串
    建模型 → 建表单 → 建菜单 → (可选) 配审批流程. 不走全量重新部署.

    Args:
      feature_name: 功能/表单显示名, 譬如 "借书申请"
      feature_code: 英文标识 (modelCode + formCode 用), snake_case, 譬如 "borrow_apply"
      fields: 字段数组. 每项:
        {"name": "申请人", "code": "applicant",
         "type": "单行输入" | "数字" | "日期" | "人员选择" | "部门选择" | "数据单选" | "下拉单选" | "多行输入" | ...
                 (或 "componentType": "FORM_TEXT_INPUT")
                 (或 "database_field_type": "BOF_TEXT"),
         "required": true | false (默认 false),
         "max_length": 200 (单行/多行用),
         "show_in_list": true | false (默认 true),
         "searchable": true | false (默认 false),
         "ref": {"model": "customer_profile", "field": "customer_name"}  # 数据选择必填,
         "dict_options": [{"name": "草稿", "code": "draft"}]              # 下拉/单选必填, 或传已有 dict_code}
      约束:
        - 客户/供应商/员工档案/部门/项目/产品等业务对象选择字段，必须用 数据单选/数据选择 + ref，不能建成单行输入。
        - 状态/类型/等级/是否等固定枚举字段，必须传 dict_options 或已有 dict_code；工具会绑定数据字典。
        - 申请人/负责人/经办人/审批人用人员选择，申请部门/归属部门用部门选择。
      process_stages: 可选审批流程节点 [{"name":"管理员审批","approver_type":"ROLE","approver_code":"admin"}]
      parent_menu_id: 可选父分组 id (从 list_apaas_app_menus 拿). 不传挂根级.

    返回: {ok, model_id, form_id, menu_id, process_id?, urls{}}
    """
    if not (apaas_app_id.strip() and feature_name.strip() and feature_code.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id + feature_name + feature_code 必填"}
    if not isinstance(fields, list) or not fields:
        return {"ok": False, "error_code": "INVALID_FIELDS",
                "message": "fields 必须非空数组 (至少 1 个字段)"}

    feature_code = feature_code.strip()
    feature_name = feature_name.strip()

    _DICT_BOUND_COMPONENTS = {
        "FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT",
        "FORM_RADIO_INPUT", "FORM_CHECKBOX_INPUT",
    }
    _REF_BOUND_COMPONENTS = {
        "FORM_DATA_SELECTOR_SINGLE", "FORM_DATA_SELECTOR", "FORM_ASSOCIATION",
    }

    # 先做完整性校验，避免先创建字典/模型后才发现表单字段缺来源。
    for f in fields:
        if not isinstance(f, dict):
            continue
        fname = (f.get("name") or "").strip()
        fcode = (f.get("code") or "").strip()
        if not fname or not fcode:
            return {"ok": False, "error_code": "FIELD_MISSING_NAME_OR_CODE",
                    "message": f"字段缺 name/code: {f}"}
        comp_type, _ = _normalize_field_type(f)
        if comp_type in _DICT_BOUND_COMPONENTS:
            has_dict = bool(f.get("dict_options") or f.get("dictOptions") or f.get("dict_code") or f.get("dictCode"))
            if not has_dict:
                return {
                    "ok": False,
                    "error_code": "SELECT_FIELD_NEEDS_DICTIONARY",
                    "message": (
                        f"字段「{fname}」是下拉/单选类字段，必须提供 dict_options "
                        "或已有 dict_code，不能创建空下拉控件。"
                    ),
                }
        if comp_type in _REF_BOUND_COMPONENTS:
            target_model, target_field = _extract_ref_target(f)
            if not target_model or not target_field:
                return {
                    "ok": False,
                    "error_code": "DATA_SELECTOR_NEEDS_REF",
                    "message": (
                        f"字段「{fname}」是数据选择/关联表单字段，必须提供 "
                        "ref.model 和 ref.field，不能创建无数据来源的选择控件。"
                    ),
                }

    # ─── Step 0: 先把含 dict_options 的字段抽出来建字典 ────
    # 字典必须先建好, 字段绑定才能引用 dictionaryCode. 字典字段类型: 下拉单选/下拉多选/
    # 单选框/复选框 4 种 (跟 field_types._DICT_FIELD_TYPES 对齐).
    dict_payloads = []
    field_to_dict_code: dict = {}  # fcode → dictionaryCode (after creation)
    for f in fields:
        if not isinstance(f, dict):
            continue
        opts = f.get("dict_options") or f.get("dictOptions")
        if not opts or not isinstance(opts, list):
            continue
        dict_code = (f.get("dict_code") or f.get("dictCode") or f.get("code") + "_dict").strip()
        dict_name = (f.get("dict_name") or f.get("dictName") or f.get("name") or dict_code).strip()
        options_payload = []
        for i, opt in enumerate(opts):
            if isinstance(opt, str):
                options_payload.append({"optionName": opt, "optionCode": f"{dict_code}_{i+1}",
                                         "displayOrder": i + 1, "remarks": ""})
            elif isinstance(opt, dict):
                options_payload.append({
                    "optionName": opt.get("name") or opt.get("label") or str(opt),
                    "optionCode": opt.get("code") or opt.get("id") or f"{dict_code}_{i+1}",
                    "displayOrder": i + 1, "remarks": opt.get("desc", ""),
                })
        dict_payloads.append({
            "appId": apaas_app_id.strip(),
            "dictionaryCode": dict_code,
            "dictionaryName": dict_name,
            "dictionaryOptions": options_payload,
        })
        field_to_dict_code[(f.get("code") or "").strip()] = dict_code

    created_dicts_result = None
    if dict_payloads:
        ok_d, dict_result = await _with_client(env_id, "建字典",
            lambda c: c.create_dicts(apaas_app_id.strip(), dict_payloads))
        if not ok_d:
            return {**dict_result, "step": "create_dicts",
                    "rollback_hint": "字典建失败, 后续 模型/表单/菜单/流程 都没建"}
        created_dicts_result = dict_result
        # 平台可能给字典 code 加 _ 后缀 (重名), 更新映射
        if isinstance(dict_result, list):
            for i, item in enumerate(dict_result):
                if isinstance(item, dict) and i < len(dict_payloads):
                    actual_code = item.get("dictionaryCode") or item.get("code")
                    if actual_code:
                        original_code = dict_payloads[i]["dictionaryCode"]
                        # 找回是哪个 field
                        for fc, dc in list(field_to_dict_code.items()):
                            if dc == original_code:
                                field_to_dict_code[fc] = actual_code

    # ─── Step 1: 建模型 (含字段) ─────────────────────────────
    # 字段类型映射用 field_types.py 单一真相 (Builder 创建应用同款 SPEC):
    #   STRING (varchar) — 单行输入/手机/邮箱/单据号/超链接/身份证/字典选项/人员/部门
    #   BIG_TEXT (longtext) — 多行输入/富文本
    #   NUM (decimal) — 数字/金额
    #   DATE (datetime) — 日期时间
    model_fields = []
    form_components = []
    referenced_model_codes: list[str] = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        fname = (f.get("name") or "").strip()
        fcode = (f.get("code") or "").strip()
        comp_type, data_model_type = _normalize_field_type(f)
        max_length = int(f.get("max_length") or f.get("maxLength") or 200)
        required = bool(f.get("required", False))
        # 模型字段 — fieldType 用平台 data_model_type (STRING/BIG_TEXT/NUM/DATE)
        mf = {
            "fieldName": fname, "fieldCode": fcode,
            "fieldType": data_model_type, "required": required,
        }
        # 仅 STRING 类型加 maxLength (BIG_TEXT/NUM/DATE 无意义)
        if data_model_type == "STRING":
            mf["maxLength"] = max_length
        model_fields.append(mf)
        # 表单组件
        comp = {
            "componentType": comp_type, "label": fname,
            "modelField": f"{feature_code}.{fcode}",
            "required": required, "hidden": False, "readOnly": False,
            "showInList": bool(f.get("show_in_list", f.get("showInList", True))),
            "searchable": bool(f.get("searchable", False)),
        }
        if comp_type == "FORM_TEXT_INPUT" and max_length:
            comp["lengthLimit"] = max_length
        # 字典绑定字段: 加 dictionarySelectConfig
        if comp_type in _DICT_BOUND_COMPONENTS:
            actual_dict_code = field_to_dict_code.get(fcode) or f.get("dict_code") or f.get("dictCode")
            if not actual_dict_code:
                return {
                    "ok": False,
                    "error_code": "SELECT_FIELD_NEEDS_DICTIONARY",
                    "message": (
                        f"字段「{fname}」是下拉/单选类字段，必须提供 dict_options "
                        "或已有 dict_code，不能创建空下拉控件。"
                    ),
                }
            # 收集选项 (从 dict_payloads 找到对应)
            dict_opts_for_field = []
            for dp in dict_payloads:
                if dp["dictionaryCode"] in (actual_dict_code, field_to_dict_code.get(fcode)):
                    dict_opts_for_field = [
                        {"optionName": o["optionName"], "optionCode": o["optionCode"]}
                        for o in dp["dictionaryOptions"]
                    ]
                    break
            comp["dictionarySelectConfig"] = {
                "dictionaryCode": actual_dict_code,
                "dictionarySelectOptions": dict_opts_for_field,
            }
            comp["chooseType"] = (
                "MULTI"
                if comp_type == "FORM_CHECKBOX_INPUT"
                else select_choose_type_for_component(comp_type, comp, multi_value="MULTI")
            )

        if comp_type in _REF_BOUND_COMPONENTS:
            target_model, target_field = _extract_ref_target(f)
            if comp_type in {"FORM_DATA_SELECTOR_SINGLE", "FORM_DATA_SELECTOR"}:
                comp["dataSelectorConfig"] = {
                    "type": "LOV_CHOOSE",
                    "otherModelCode": target_model,
                    "otherFieldCode": target_field,
                }
            else:
                comp["formAssociationConfig"] = {
                    "originFieldCode": fcode,
                    "targetModelCode": target_model,
                    "targetFieldCode": target_field,
                }
            if target_model not in referenced_model_codes:
                referenced_model_codes.append(target_model)
        form_components.append(comp)

    # 反查应用名 — 模型 useScope 字段需要这个 (否则模型显"全部应用" 而非"图书借阅管理系统")
    ok_app, app_detail = await _with_client(env_id, "查应用",
        lambda c: c.query_app_detail(apaas_app_id.strip()))
    app_name_for_scope = ""
    if ok_app and isinstance(app_detail, dict):
        app_name_for_scope = str(app_detail.get("appName") or "").strip()
    # 兜底: 拿 feature_name 当 scope (但更可能撞限制)
    if not app_name_for_scope:
        app_name_for_scope = feature_name

    model_payload = {
        "appId": apaas_app_id.strip(),
        "dataModels": [{
            "appId": apaas_app_id.strip(),
            "modelName": feature_name, "modelCode": feature_code,
            "modelDescription": f"{feature_name} 数据模型",
            "useScope": app_name_for_scope,   # 关键: 锚定到当前应用, 否则显"全部应用"
            "internalResource": True,
            "fields": model_fields,
        }],
    }
    ok_m, model_result = await _with_client(env_id, "建模型",
        lambda c: c.create_models(apaas_app_id.strip(), model_payload))
    if not ok_m:
        return {**model_result, "step": "create_models",
                "rollback_hint": "模型建失败, 后续 form/menu/process 都没建"}

    # 拿 modelCode (平台可能加 _ 后缀去重)
    actual_model_code = feature_code
    if isinstance(model_result, list) and model_result:
        first = model_result[0] if isinstance(model_result[0], dict) else {}
        actual_model_code = first.get("modelCode") or feature_code

    # ─── Step 2: 建表单 config (会自动创建关联菜单) ──────────
    # 如果平台加了 _ 后缀, 表单组件 modelField 也要更新
    if actual_model_code != feature_code:
        for comp in form_components:
            if comp.get("modelField", "").startswith(f"{feature_code}."):
                comp["modelField"] = comp["modelField"].replace(
                    f"{feature_code}.", f"{actual_model_code}.", 1)

    all_model_codes = [actual_model_code]
    for ref_code in referenced_model_codes:
        if ref_code and ref_code not in all_model_codes:
            all_model_codes.append(ref_code)

    form_payload = [{
        "formName": feature_name,
        "formCode": f"{feature_code}_form",
        "allModelCodes": all_model_codes,
        "formComponents": form_components,
    }]
    ok_f, form_result = await _with_client(env_id, "建表单",
        lambda c: c.create_form_config(apaas_app_id.strip(), form_payload))
    if not ok_f:
        return {**form_result, "step": "create_form_config",
                "partial_built": {"model_code": actual_model_code},
                "rollback_hint": "表单建失败, 模型已建但表单/菜单/流程没建"}

    form_id = ""
    menu_id = ""
    actual_form_code = f"{feature_code}_form"
    if isinstance(form_result, list) and form_result:
        first = form_result[0] if isinstance(form_result[0], dict) else {}
        form_id = str(first.get("id") or first.get("formId") or "")
        menu_id = str(first.get("menuId") or "")
        actual_form_code = str(first.get("formCode") or actual_form_code)

    # ─── Step 2b: 创建后强制回写下拉值、数据选择真实目标和默认权限 ───
    post_config_result = None
    if form_id:
        ok_post, post_raw = await _with_client(
            env_id,
            "表单质量后处理",
            lambda c: _post_configure_feature_form_quality(
                c,
                app_id=apaas_app_id.strip(),
                form_id=form_id,
                form_code=actual_form_code,
                fields=fields,
                field_to_dict_code=field_to_dict_code,
            ),
        )
        post_config_result = post_raw if ok_post else post_raw

    # ─── Step 3: (可选) 移到 parent_menu_id 分组下 ──────────
    moved_to_parent = False
    if parent_menu_id.strip() and menu_id:
        try:
            ok_mv, _ = await _with_client(env_id, "移菜单",
                lambda c: c.update_menu_parent(
                    apaas_app_id.strip(), menu_id, parent_menu_id.strip()))
            moved_to_parent = ok_mv
        except Exception:
            pass  # 移分组失败不阻断主流程

    # ─── Step 4: (可选) 配审批流程 ──────────────────────────
    process_result = None
    if process_stages and isinstance(process_stages, list) and menu_id:
        try:
            process_result = await set_apaas_app_process(
                env_id=env_id, apaas_app_id=apaas_app_id.strip(),
                menu_id=menu_id,
                process_name=f"{feature_name}审批流程",
                process_code=f"{feature_code}_process",
                stages=process_stages,
            )
        except Exception as exc:
            process_result = {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "feature_name": feature_name,
        "feature_code": feature_code,
        "actual_model_code": actual_model_code,
        "model_id": (model_result[0].get("id") if isinstance(model_result, list)
                     and model_result and isinstance(model_result[0], dict) else None),
        "form_id": form_id,
        "form_code": actual_form_code,
        "menu_id": menu_id,
        "fields_count": len(model_fields),
        "moved_to_parent": moved_to_parent,
        "post_config_result": post_config_result,
        "process_result": process_result,
        "message": (f"功能「{feature_name}」已建好: "
                    f"模型 {actual_model_code} ({len(model_fields)} 字段) → 表单 → "
                    f"菜单 (menu_id={menu_id})"
                    + (f" → 流程 ({len(process_stages)} 节点)"
                       if process_stages else "")),
        "next_step": "刷新平台 iframe 看新菜单, 或调 republish_apaas_app 让运行时生效",
    }



def register(mcp, with_client, set_app_process):
    global _with_client, set_apaas_app_process
    tools = [build_apaas_feature_from_spec]
    _with_client = with_client
    set_apaas_app_process = set_app_process
    for tool in tools:
        mcp.tool()(tool)
    return {tool.__name__: tool for tool in tools}
