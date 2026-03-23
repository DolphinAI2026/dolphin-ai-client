"""Copilot 分步执行器

每个 execute_* 函数对应一个独立步骤，不 yield SSE，直接返回结果 dict 或抛异常。
复用 generator_v2 的工具函数和类型映射。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import httpx

from app.apaas_client import APaaSClient
from app.generator_v2 import (
    _rand, _sanitize_code, _safe_field_code, _extract_fields,
    _build_component, FIELD_TYPE_MAP, COMP_TYPE_MAP, _apply_suffix,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Step 1: 创建平台应用
# ------------------------------------------------------------------

async def execute_create_app(
    client: APaaSClient,
    app_name: str,
    app_code: str,
    description: str = "",
) -> dict:
    """在得帆云平台创建应用，返回 apaas_app_id 和 suffix。"""
    apaas_result = await client.create_app(app_name, app_code, description)
    apaas_app_id = str(apaas_result) if isinstance(apaas_result, str) else str(
        apaas_result.get("id", apaas_result.get("appId", ""))
    )
    suffix = _rand()
    return {
        "apaas_app_id": apaas_app_id,
        "suffix": suffix,
    }


# ------------------------------------------------------------------
# Step 2: 创建角色 + 字典
# ------------------------------------------------------------------

async def execute_create_roles_dicts(
    client: APaaSClient,
    app_id: str,
    roles: List[dict],
    dicts: List[dict],
    suffix: str,
) -> dict:
    """批量创建角色和字典，返回 dict_codes 和 role_codes 映射。"""
    dict_codes: Dict[str, str] = {}
    role_codes: Dict[str, dict] = {}  # {原始code: {"roleCode": 平台code, "roleName": 名称}}
    roles_created = 0
    dicts_created = 0
    options_created = 0
    messages: List[str] = []

    # --- 角色（逐个创建，跳过已存在的） ---
    if roles:
        for r in roles:
            original_code = r.get("code", r["name"])
            platform_code = _apply_suffix(f"R_{_sanitize_code(original_code)}", suffix)
            role_codes[original_code] = {"roleCode": platform_code, "roleName": r["name"]}
            try:
                await client.create_roles(app_id, [{
                    "appId": app_id,
                    "roleCode": platform_code,
                    "roleName": r["name"],
                }])
                roles_created += 1
            except Exception as e:
                if "已存在" in str(e) or "重复" in str(e):
                    messages.append(f"角色已存在: {r['name']}")
                else:
                    messages.append(f"角色创建失败 {r['name']}: {e}")
        if roles_created:
            messages.append(f"新建角色: {roles_created} 个")

    # --- 字典 ---
    if dicts:
        existing = {d.get("dictionaryName"): d for d in await client.query_dicts(app_id)}
        new_dicts = []
        dicts_needing_options = []  # 所有需要补选项的字典（包括复用的）

        for d in dicts:
            ed = existing.get(d["name"])
            if ed:
                pc = ed["dictionaryCode"]
                dict_codes[d["name"]] = pc
                dict_codes[d.get("code", d["name"])] = pc
                messages.append(f"复用字典: {d['name']}")
                # 复用的字典也可能需要补选项
                if d.get("options"):
                    dicts_needing_options.append(d)
            else:
                dc = _apply_suffix(_sanitize_code(d.get('code', 'dict')), suffix)
                dict_codes[d["name"]] = dc
                dict_codes[d.get("code", d["name"])] = dc
                new_dicts.append(d)
                if d.get("options"):
                    dicts_needing_options.append(d)

        if new_dicts:
            # 逐个创建字典，跳过已存在的（批量创建一个失败全失败）
            for d in new_dicts:
                try:
                    await client.create_dicts(app_id, [{
                        "appId": app_id,
                        "dictionaryCode": dict_codes[d["name"]],
                        "dictionaryName": d["name"],
                        "dictionaryOptions": [],
                    }])
                    dicts_created += 1
                except Exception as e:
                    if "重复" in str(e) or "已存在" in str(e):
                        messages.append(f"字典编码已存在: {d['name']}")
                    else:
                        raise

        # 添加选项（merge：跳过已有选项，对所有字典生效）
        if dicts_needing_options:
            all_platform_dicts = await client.query_dicts(app_id)
            dict_by_code = {d.get("dictionaryCode"): d for d in all_platform_dicts}
            async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
                headers = client._get_headers(app_id)
                for d in dicts_needing_options:
                    dc = dict_codes.get(d["name"])
                    if not dc:
                        continue
                    obj = dict_by_code.get(dc)
                    if not obj:
                        continue
                    dict_id = obj["id"]
                    # 查询已有选项，避免重复
                    try:
                        existing_opts = await client.query_dict_options(app_id, dict_id)
                        existing_opt_names = {o.get("valueName") for o in existing_opts}
                    except Exception:
                        existing_opt_names = set()
                    for idx, opt in enumerate(d["options"]):
                        opt_name = opt["name"] if isinstance(opt, dict) else str(opt)
                        if opt_name in existing_opt_names:
                            continue  # 跳过已存在的选项
                        opt_code_raw = opt.get("code", f"opt{idx}") if isinstance(opt, dict) else f"opt{idx}"
                        try:
                            await http.post(
                                f"{client.base_url}/xdap-app/dataDictionary/add/dictionaryValue",
                                headers=headers,
                                json={
                                    "appId": app_id,
                                    "dictionaryId": dict_id,
                                    "valueCode": _apply_suffix(_sanitize_code(opt_code_raw), suffix),
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
                            options_created += 1
                        except Exception as e:
                            logger.warning(f"选项创建失败 {d['name']}/{opt_name}: {e}")

    return {
        "dict_codes": dict_codes,
        "role_codes": role_codes,
        "roles_created": roles_created,
        "dicts_created": dicts_created,
        "options_created": options_created,
        "messages": messages,
    }


# ------------------------------------------------------------------
# Step 3: 创建单个数据模型
# ------------------------------------------------------------------

async def execute_create_model(
    client: APaaSClient,
    app_id: str,
    model: dict,
    model_index: int,
    suffix: str,
) -> dict:
    """创建单个数据模型（含子表），返回 model_info 条目。"""
    model_info_entries: Dict[str, dict] = {}

    # 检查是否已存在
    existing_models = await client.query_models(app_id)
    existing_by_name = {m.get("modelName"): m for m in existing_models}

    em = existing_by_name.get(model["name"])
    if em:
        model_info_entries[str(model_index)] = {
            "name": model["name"],
            "code": em["modelCode"],
            "fields": _extract_fields(em),
        }
        # 复用子表
        for f in model.get("fields", []):
            if f.get("type") == "子表" and f.get("sub_fields"):
                sub_em = existing_by_name.get(f["name"])
                if sub_em:
                    model_info_entries[f"{model_index}_sub_{f['name']}"] = {
                        "name": f["name"],
                        "code": sub_em["modelCode"],
                        "fields": _extract_fields(sub_em),
                    }
        return {
            "model_info_entries": model_info_entries,
            "reused": True,
            "message": f"复用已有模型: {model['name']}",
        }

    # 构建新模型
    mc = _apply_suffix(_sanitize_code(model.get('code', 'model')), suffix)
    fields_map = {}
    data_models = []

    # 子表模型
    for f in model.get("fields", []):
        if f.get("type") == "子表" and f.get("sub_fields"):
            sub_code = _apply_suffix(_sanitize_code(f.get('sub_code') or model.get('code', 'model') + '_sub'), suffix)
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
            model_info_entries[f"{model_index}_sub_{f['name']}"] = {
                "name": f["name"], "code": sub_code, "fields": sub_fields_map,
            }

    # 主模型字段
    main_fields = []
    for f in model.get("fields", []):
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
        "appId": app_id, "modelName": model["name"],
        "modelCode": mc, "modelDescription": model.get("description", model["name"]),
        "fields": main_fields,
    })
    model_info_entries[str(model_index)] = {
        "name": model["name"], "code": mc, "fields": fields_map,
    }

    payload = {"appId": app_id, "datasourceId": "", "dataModels": data_models}

    try:
        await client.create_models(app_id, payload)
    except Exception as e:
        if "编码重复" in str(e) or "已存在" in str(e):
            # 回退到复用模式
            refreshed = await client.query_models(app_id)
            ref_by_name = {rm.get("modelName"): rm for rm in refreshed}
            rm = ref_by_name.get(model["name"])
            if rm:
                model_info_entries[str(model_index)] = {
                    "name": model["name"], "code": rm["modelCode"], "fields": _extract_fields(rm),
                }
                for f in model.get("fields", []):
                    if f.get("type") == "子表":
                        srm = ref_by_name.get(f["name"])
                        if srm:
                            model_info_entries[f"{model_index}_sub_{f['name']}"] = {
                                "name": f["name"], "code": srm["modelCode"], "fields": _extract_fields(srm),
                            }
                return {
                    "model_info_entries": model_info_entries,
                    "reused": True,
                    "message": f"编码冲突，复用已有: {model['name']}",
                }
        raise

    # 刷新字段（平台可能追加后缀）
    refreshed = await client.query_models(app_id)
    ref_by_code = {rm.get("modelCode"): rm for rm in refreshed}
    mi = model_info_entries.get(str(model_index))
    if mi and mi["code"] in ref_by_code:
        mi["fields"] = _extract_fields(ref_by_code[mi["code"]])
    for f in model.get("fields", []):
        if f.get("type") == "子表":
            sub_key = f"{model_index}_sub_{f['name']}"
            sub_mi = model_info_entries.get(sub_key)
            if sub_mi and sub_mi["code"] in ref_by_code:
                sub_mi["fields"] = _extract_fields(ref_by_code[sub_mi["code"]])

    return {
        "model_info_entries": model_info_entries,
        "reused": False,
        "message": f"创建成功: {model['name']} ({len(main_fields)} 个字段)",
    }


# ------------------------------------------------------------------
# Step 4: 创建单个表单
# ------------------------------------------------------------------

async def execute_create_form(
    client: APaaSClient,
    app_id: str,
    model: dict,
    model_index: int,
    dict_codes: Dict[str, str],
    model_info: Dict[str, dict],
    all_models: List[dict],
) -> dict:
    """创建单个表单 + 绑定字典，返回 form 结果。"""
    mi = model_info.get(str(model_index))
    if not mi:
        raise ValueError(f"模型 {model['name']} 的 model_info 不存在，请先创建模型")

    # 检查是否已存在
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

    if model["name"] in existing_forms:
        return {
            "formId": existing_forms[model["name"]],
            "formName": model["name"],
            "formCode": "",
            "menuId": "",
            "reused": True,
            "message": f"复用已有表单: {model['name']}",
        }

    model_code = mi["code"]
    model_fields = mi["fields"]

    all_model_codes = [model_code]
    components = []
    query_conditions = []
    query_list = []
    listable = 0

    for f in model.get("fields", []):
        ftype = f.get("type", "单行输入")

        # 子表
        if ftype == "子表" and f.get("sub_fields"):
            sub_mi = model_info.get(f"{model_index}_sub_{f['name']}")
            if not sub_mi:
                continue
            all_model_codes.append(sub_mi["code"])
            sub_cols = []
            for sf in f["sub_fields"]:
                sfc = sub_mi["fields"].get(sf["name"])
                if not sfc:
                    continue
                sub_cols.append(_build_component(sf, sub_mi["code"], sfc, dict_codes, all_models, model_info))
            if sub_cols:
                components.append({
                    "componentType": "FORM_WIDGET_SON_TABLE",
                    "label": f["name"],
                    "tableColumn": sub_cols,
                })
            continue

        # 普通字段
        fc = model_fields.get(f["name"])
        if not fc:
            continue

        components.append(_build_component(f, model_code, fc, dict_codes, all_models, model_info))

        if listable < 8 and ftype not in ("附件上传", "多行输入", "子表"):
            mf = f"{model_code}.{fc}"
            if listable < 4:
                query_conditions.append(mf)
            query_list.append(mf)
            listable += 1

    if not components:
        raise ValueError(f"表单 {model['name']} 无可用字段组件")

    # formCode: 使用模型编码或生成唯一标识
    form_code_suffix = _rand(6)
    if form_code_suffix:
        form_code = f"form_{form_code_suffix}"
    else:
        # 后缀禁用时，使用模型编码作为表单编码基础
        form_code = f"form_{_sanitize_code(model.get('code', model['name']))}"

    form_payload = [{
        "formName": model["name"],
        "formCode": form_code,
        "allModelCodes": all_model_codes,
        "formComponents": components,
        "listPageView": {
            "queryConditions": query_conditions,
            "queryList": query_list,
        },
    }]

    result = await client.create_form_config(app_id, form_payload)
    form_result = {
        "formId": "", "formName": model["name"], "formCode": "", "menuId": "",
        "reused": False, "message": f"创建成功: {model['name']}",
    }

    if isinstance(result, list):
        for fr in result:
            if isinstance(fr, dict) and "id" in fr:
                form_result["formId"] = fr["id"]
                form_result["formCode"] = fr.get("formCode", "")
                form_result["menuId"] = fr.get("menuId", "")
                # 尝试创建菜单
                try:
                    await client.create_menu(app_id, model["name"], fr["id"], menu_order=model_index)
                except Exception as menu_err:
                    logger.warning(f"创建菜单失败（{model['name']}）: {menu_err}")

    # --- 绑定字典 ---
    if form_result["formId"] and dict_codes:
        try:
            all_platform_dicts = await client.query_dicts(app_id)
            dict_id_map = {d.get("dictionaryCode"): d.get("id") for d in all_platform_dicts}
            dict_options_map: Dict[str, list] = {}
            for dc, did in dict_id_map.items():
                if did:
                    dict_options_map[dc] = await client.query_dict_options(app_id, did)

            # 收集所有下拉字段的字典映射（包括子表字段）
            label_dict: Dict[str, str] = {}
            for f in model.get("fields", []):
                if f.get("type") in ("下拉单选", "下拉多选") and f.get("dict"):
                    label_dict[f["name"]] = dict_codes.get(f["dict"], "")
                # 子表内的下拉字段
                if f.get("type") == "子表":
                    for sf in f.get("sub_fields", []):
                        if sf.get("type") in ("下拉单选", "下拉多选") and sf.get("dict"):
                            label_dict[sf["name"]] = dict_codes.get(sf["dict"], "")

            def _bind_dict_to_comp(comp: dict) -> bool:
                """给单个组件绑定字典，返回是否有更新。"""
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

            fc = await client.query_form_config(app_id, form_result["formId"])
            comps = fc.get("detailPage", {}).get("formComponents", [])
            updated = False

            for comp in comps:
                # 顶层组件
                if _bind_dict_to_comp(comp):
                    updated = True
                # 子表内的列组件
                if comp.get("componentType") == "FORM_WIDGET_SON_TABLE":
                    for col in comp.get("tableColumn", []):
                        if _bind_dict_to_comp(col):
                            updated = True

            if updated:
                await client.save_form_config(app_id, fc)
                form_result["message"] += "（含字典绑定）"
        except Exception as e:
            logger.warning(f"字典绑定失败（不阻断）: {e}")

    return form_result


# ------------------------------------------------------------------
# Step 5: 创建审批流程
# ------------------------------------------------------------------

async def execute_create_workflow(
    client: APaaSClient,
    app_id: str,
    workflow: dict,
    form_results: List[dict],
    role_codes: Optional[Dict[str, dict]] = None,
) -> dict:
    """为单个表单创建审批流程。使用平台内部 save API（需要完整 nodes+edges+bpmn）。"""
    role_codes = role_codes or {}
    form_name = workflow.get("form", "")
    config_nodes = workflow.get("nodes", [])

    if not config_nodes:
        return {"message": f"流程 {workflow.get('name', '')} 无节点，跳过"}

    # 找对应表单的 menuId
    fr = next((f for f in form_results if f.get("formName") == form_name), None)
    if not fr:
        raise ValueError(f"未找到表单 {form_name}，无法创建流程")

    menu_id = fr.get("menuId", "")
    if not menu_id:
        raise ValueError(f"表单 {form_name} 没有 menuId，无法创建流程")

    # --- 标准按钮模板 ---
    approve_buttons = [
        {"buttonCode": "APPROVE", "buttonName": "同意", "buttonLabel": "同意", "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
        {"buttonCode": "REJECT", "buttonName": "拒绝", "buttonLabel": "拒绝", "buttonStatus": True, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
    ]
    start_buttons = [
        {"buttonCode": "NORMAL_TERMINATE", "buttonName": "终止", "buttonLabel": "终止", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
        {"buttonCode": "RESTART", "buttonName": "重新提交", "buttonLabel": "重新提交", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False},
        {"buttonCode": "WITHDRAW", "buttonName": "撤回", "buttonLabel": "撤回", "buttonStatus": False, "buttonStyle": "primary", "buttonLabelI18nAssociated": False, "withdrawalType": "NEXT_NODE", "withdrawalList": []},
    ]
    comment_config = {"required": False, "attachmentUpload": True, "requiredBtns": [], "show": True}
    phrase_config = {"handleType": "INPUT_TYPE", "phrase": "", "status": False}

    def _make_node(node_id: str, title: str, ntype: str, y: float, approvers=None):
        n = {
            "id": node_id, "nodeId": node_id, "timeBoudries": [],
            "width": "64.0" if ntype in ("START", "END") else "122.0",
            "height": "64.0" if ntype in ("START", "END") else "48.0",
            "x": 372.0, "y": y,
            "data": {
                "nodeId": node_id, "title": title, "type": ntype,
                "enableComponentPermission": True, "titleI18nAssociated": False,
                "approveCommentConfig": comment_config, "approvePhraseConfig": phrase_config,
                "remindList": [], "processEventStatus": False, "saveFlag": True,
            },
        }
        if ntype == "START":
            n["data"]["formButtons"] = start_buttons
        elif ntype == "APPROVE":
            n["data"]["approveType"] = "SINGLE"
            n["data"]["approveButtons"] = approve_buttons
            n["data"]["approvers"] = approvers or []
        return n

    # --- 构建节点 ---
    # 固定结构: START → START_HIDDEN(发起申请) → UserTask_1 → UserTask_2 → ... → END
    platform_nodes = [
        _make_node("START", "开始", "START", 32.0),
        _make_node("START_HIDDEN", "发起申请", "APPROVE", 128.0,
                    [{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}]),
    ]

    approve_idx = 0
    y_pos = 224.0
    for node in config_nodes:
        if node.get("type") in ("start", "end"):
            continue
        approvers = []
        if node.get("role"):
            role_code = node["role"]
            role_info = role_codes.get(role_code, {})
            platform_code = role_info.get("roleCode", role_code)
            platform_name = role_info.get("roleName", node.get("name", role_code))
            approvers.append({"approverType": "ROLE", "approverName": platform_name, "approverCode": platform_code})
        if not approvers:
            # 审批节点必须有审批人，默认用提交人
            approvers = [{"approverType": "SUBMITTER", "approverName": "表单提交人", "approverCode": "SUBMITTER"}]
        platform_nodes.append(_make_node(f"UserTask_{approve_idx + 1}", node["name"], "APPROVE", y_pos, approvers))
        approve_idx += 1
        y_pos += 96.0

    platform_nodes.append(_make_node("END", "结束", "END", y_pos))

    # --- 构建边 ---
    platform_edges = []
    for i in range(len(platform_nodes) - 1):
        src = platform_nodes[i]["id"]
        tgt = platform_nodes[i + 1]["id"]
        platform_edges.append({
            "id": f"SequenceFlow_{tgt}",
            "source": src,
            "target": tgt,
            "data": {"titleI18nAssociated": False},
        })

    # --- 最小 BPMN XML（平台会自动重建完整的 BPMN） ---
    bpmn = '<?xml version="1.0" encoding="UTF-8"?><definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:activiti="http://activiti.org/bpmn" id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn"><process id="Process_1" isExecutable="true"><startEvent id="START" name="开始"/><endEvent id="END" name="结束"/></process></definitions>'

    payload = {
        "appId": app_id,
        "menuId": menu_id,
        "bpmn": bpmn,
        "nodes": platform_nodes,
        "edges": platform_edges,
    }

    await client.save_process_config(app_id, payload)
    return {
        "message": f"流程创建成功: {workflow.get('name', '')}（{approve_idx} 个审批节点）",
    }


# ------------------------------------------------------------------
# Step 6: 配置权限
# ------------------------------------------------------------------

async def execute_configure_permissions(
    client: APaaSClient,
    app_id: str,
    permissions: List[dict],
    form_results: List[dict],
    role_codes: Optional[Dict[str, dict]] = None,
) -> dict:
    """为所有表单配置权限。"""
    role_codes = role_codes or {}
    perm_payloads = []
    for fr in form_results:
        form_code = fr.get("formCode", "")
        form_id = fr.get("formId", "")

        user_perm = next((p for p in permissions if p.get("form") == fr.get("formName")), None)

        if user_perm and user_perm.get("rules"):
            op_groups = []
            data_groups = []
            for rule in user_perm["rules"]:
                role_code = rule.get("role", "")
                perm_obj_type = "ALL_USER"
                perm_obj_value = ""
                perm_obj_name = "全部人员"
                if role_code and role_code != "all":
                    perm_obj_type = "ROLE"
                    # 使用平台实际的 roleCode，而非配置里的原始 code
                    role_info = role_codes.get(role_code, {})
                    perm_obj_value = role_info.get("roleCode", role_code)
                    perm_obj_name = role_info.get("roleName", role_code)

                op = rule.get("op", "all")
                # 支持逗号分隔的多操作，如 "add,edit,delete"
                ops = set(op.replace(" ", "").split(",")) if "," in op else {op}

                data_range = rule.get("data", "ALL")
                range_map = {
                    "all": "ALL", "self": "SELF", "dept": "CURRENT_USER_DEPT",
                    "dept_sub": "CURRENT_USER_DEPT_LOW_LEVEL",
                }
                range_type = range_map.get(data_range, data_range.upper() if isinstance(data_range, str) else "ALL")

                # 操作权限：view-only 不创建操作权限组
                has_write = "all" in ops or bool(ops - {"view"})
                if has_write:
                    perm_op = {
                        "addPermission": "all" in ops or "add" in ops or "edit" in ops,
                        "batchAgreePermission": "all" in ops or "approve" in ops,
                        "batchDeletePermission": "all" in ops or "delete" in ops,
                        "batchRejectPermission": "all" in ops or "approve" in ops,
                        "copyAddPermission": "all" in ops,
                        "importPermission": "all" in ops or "import" in ops,
                        "shareFormPermission": False,
                        "temporaryStoragePermission": "all" in ops or "add" in ops,
                    }
                    op_groups.append({
                        "permissionName": f"{perm_obj_name}操作权限",
                        "permissionDescribe": "",
                        "PermissionObjects": [{
                            "permissionObjectDisplayName": perm_obj_name,
                            "permissionObjectType": perm_obj_type,
                            "permissionObjectValue": perm_obj_value,
                            "permissionRange": {"rangeType": "ALL"},
                        }],
                        "permissionOperationType": perm_op,
                    })

                # 数据权限：始终创建（包括 view-only）
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
                        "queryPermission": True,
                        "deletePermission": "all" in ops or "delete" in ops,
                        "updatePermission": "all" in ops or "edit" in ops,
                    },
                })

            perm_payloads.append({
                "formCode": form_code, "appId": app_id, "tenantId": "",
                "formId": form_id,
                "operationPermissionGroups": op_groups,
                "dataPermissionGroups": data_groups,
            })
        else:
            # 默认权限
            perm_payloads.append({
                "formCode": form_code, "appId": app_id, "tenantId": "",
                "formId": form_id,
                "operationPermissionGroups": [{
                    "permissionName": "默认操作权限",
                    "permissionDescribe": "全部人员可操作",
                    "PermissionObjects": [{
                        "permissionObjectDisplayName": "全部人员",
                        "permissionObjectType": "ALL_USER",
                        "permissionObjectValue": "",
                        "permissionRange": {"rangeType": "ALL"},
                    }],
                    "permissionOperationType": {
                        "addPermission": True, "batchAgreePermission": False,
                        "batchDeletePermission": False, "batchRejectPermission": False,
                        "copyAddPermission": False, "importPermission": False,
                        "shareFormPermission": False, "temporaryStoragePermission": False,
                    },
                }],
                "dataPermissionGroups": [{
                    "permissionName": "默认数据权限",
                    "permissionDescribe": "全部人员可查看全部数据",
                    "permissionObjects": [{
                        "permissionObjectDisplayName": "全部人员",
                        "permissionObjectType": "ALL_USER",
                        "permissionObjectValue": "",
                        "permissionRange": {"rangeType": "ALL"},
                    }],
                    "permissionOperationType": {
                        "queryPermission": True, "deletePermission": False, "updatePermission": False,
                    },
                }],
            })

    if perm_payloads:
        await client.create_form_permissions(app_id, perm_payloads)

    return {"permissions_count": len(perm_payloads)}
