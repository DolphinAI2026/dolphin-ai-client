"""Copilot 分步执行器

每个 execute_* 函数对应一个独立步骤，不 yield SSE，直接返回结果 dict 或抛异常。
复用 generator_v2 的工具函数和类型映射。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.apaas_client import APaaSClient
from app.generator_v2 import (
    _rand, _sanitize_code, _safe_field_code, _extract_fields,
    _build_component, FIELD_TYPE_MAP, COMP_TYPE_MAP, _apply_suffix,
)

logger = logging.getLogger(__name__)


def _field_value(field: dict, *keys: str, default=None):
    for key in keys:
        if key in field and field.get(key) not in (None, ""):
            return field.get(key)
    return default


def _normalize_database_field_type(field: dict) -> str:
    raw = _field_value(field, "database_field_type", "databaseFieldType", "db_type", "dbType")
    if raw:
        return str(raw).strip().lower()

    raw_type = str(_field_value(field, "type", default="")).strip().lower()
    if raw_type in {"int", "integer", "bigint", "smallint", "tinyint"}:
        return raw_type
    if raw_type in {"date", "datetime", "timestamp"}:
        return raw_type
    if raw_type in {"decimal", "double", "float"}:
        return raw_type
    return "varchar"


def _resolve_platform_field_type(field: dict) -> str:
    """把字段定义映射到 APaaS 平台字段类型（STRING / NUM / DATE）。

    ⚠️ 与 app.config_validator._normalize_field_type 不要混淆：
        - 这里：input=dict，output=平台字段类型（发给 APaaS 的 fieldType）
        - config_validator：input=中文语义类型字符串，output=校验过的 schema 类型
    两者功能完全不同，历史上同名导致 import 时容易踩坑，已改名消歧义。
    """
    semantic = str(_field_value(field, "type", default="")).strip()
    mapped = FIELD_TYPE_MAP.get(semantic)
    if mapped:
        return mapped

    db_type = _normalize_database_field_type(field).lower()
    if db_type in {"date", "datetime", "timestamp"}:
        return "DATE"
    if db_type in {"int", "integer", "bigint", "smallint", "tinyint", "decimal", "double", "float"}:
        return "NUM"
    return "STRING"


def _normalize_field_comment(field: dict) -> str:
    return str(_field_value(field, "comment", "description", "fieldComment", "fieldDescription", default="") or "")


def _normalize_field_length(field: dict):
    raw = _field_value(field, "max_length", "maxLength", "length")
    if raw in (None, ""):
        return None
    return raw


def _build_model_field_payload(field: dict) -> dict:
    raw_field_code = str(field.get("code") or "").strip()
    payload = {
        "fieldName": field["name"],
        "fieldCode": raw_field_code or _safe_field_code(field["name"]),
        "fieldType": _resolve_platform_field_type(field),
        "databaseFieldType": _normalize_database_field_type(field),
        "fieldDescription": _normalize_field_comment(field),
        "fieldComment": _normalize_field_comment(field),
    }
    max_length = _normalize_field_length(field)
    if max_length is not None:
        payload["maxLength"] = max_length
    return payload


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
    platform_app_code = ""
    if isinstance(apaas_result, dict):
        platform_app_code = str(apaas_result.get("appCode") or apaas_result.get("code") or "").strip()
    suffix = _rand()
    return {
        "apaas_app_id": apaas_app_id,
        "platform_app_code": platform_app_code,
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
            platform_code = _apply_suffix(_sanitize_code(original_code), suffix)
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
        try:
            remote_roles = await client.query_roles(app_id)
            for r in roles:
                original_code = r.get("code", r["name"])
                local_info = role_codes.setdefault(original_code, {})
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
                            err_msg = str(e)
                            if "重复" in err_msg or "已存在" in err_msg:
                                logger.info(f"选项已存在，跳过: {d['name']}/{opt_name}")
                            else:
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

def _is_model_keyword_conflict(err: object) -> bool:
    msg = str(err)
    return "数据库关键词" in msg or "关键词重复" in msg


def _make_keyword_safe_model_name(name: str) -> str:
    if name.endswith(("模型", "数据", "记录", "配置表")):
        return f"{name}业务"
    return f"{name}模型"


def _make_keyword_safe_model_code(code: str) -> str:
    if code.startswith("biz_"):
        return _sanitize_code(f"{code}_m")
    return _sanitize_code(f"biz_{code}")


def _build_keyword_safe_models(data_models: List[dict]) -> tuple[List[dict], Dict[str, str]]:
    safe_models: List[dict] = []
    code_map: Dict[str, str] = {}

    for dm in data_models:
        old_code = dm["modelCode"]
        new_code = _make_keyword_safe_model_code(old_code)
        code_map[old_code] = new_code
        safe_models.append({
            **dm,
            "modelName": _make_keyword_safe_model_name(dm["modelName"]),
            "modelCode": new_code,
        })

    return safe_models, code_map


def _remap_model_info_codes(model_info_entries: Dict[str, dict], code_map: Dict[str, str]) -> None:
    for info in model_info_entries.values():
        current_code = info.get("code", "")
        if current_code in code_map:
            info["code"] = code_map[current_code]


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
        existing_fields = _extract_fields(em)
        model_id = em.get("id") or em.get("modelId")
        model_info_entries[str(model_index)] = {
            "name": model["name"],
            "code": em["modelCode"],
            "fields": existing_fields,
            "remote_id": model_id,
        }
        # 补齐缺失字段
        added_count = 0
        if model_id:
            for f in model.get("fields", []):
                if f.get("type") == "子表":
                    continue
                if f["name"] not in existing_fields:
                    try:
                        field_payload = _build_model_field_payload(f)
                        await client._post_resource(
                            "/modelField/add",
                            {"modelId": model_id, "appId": app_id,
                             "fieldCode": field_payload["fieldCode"], "fieldName": f["name"],
                             "fieldType": field_payload["fieldType"],
                             "databaseFieldType": field_payload["databaseFieldType"], "fieldStatus": "ENABLE",
                             "fieldComment": field_payload["fieldComment"],
                             **({"maxLength": field_payload["maxLength"]} if "maxLength" in field_payload else {})},
                            app_id=app_id)
                        existing_fields[f["name"]] = field_payload["fieldCode"]
                        added_count += 1
                        logger.info(f"模型 {model['name']} 补齐字段: {f['name']} ({field_payload['fieldCode']})")
                    except Exception as add_err:
                        logger.warning(f"模型 {model['name']} 补齐字段 {f['name']} 失败: {add_err}")
        if added_count:
            # 刷新字段编码
            refreshed = await client.query_models(app_id)
            for rm in refreshed:
                if rm.get("modelCode") == em["modelCode"]:
                    model_info_entries[str(model_index)]["fields"] = _extract_fields(rm)
                    break
        # 复用子表
        for f in model.get("fields", []):
            if f.get("type") == "子表" and f.get("sub_fields"):
                sub_em = existing_by_name.get(f["name"])
                if sub_em:
                    model_info_entries[f"{model_index}_sub_{f['name']}"] = {
                        "name": f["name"],
                        "code": sub_em["modelCode"],
                        "fields": _extract_fields(sub_em),
                        "remote_id": sub_em.get("id") or sub_em.get("modelId"),
                    }
        msg = f"复用已有模型: {model['name']}"
        if added_count:
            msg += f" (补齐 {added_count} 个字段)"
        return {
            "model_info_entries": model_info_entries,
            "reused": True,
            "message": msg,
        }

    # 构建新模型
    raw_model_code = str(model.get("code") or "").strip()
    mc = raw_model_code or _apply_suffix(_sanitize_code(model.get('code', 'model')), suffix)
    keyword_retry_applied = False
    fields_map = {}
    data_models = []

    # 子表模型
    for f in model.get("fields", []):
        if f.get("type") == "子表" and f.get("sub_fields"):
            raw_sub_code = str(f.get("sub_code") or "").strip()
            sub_code = raw_sub_code or _apply_suffix(_sanitize_code(f.get('sub_code') or model.get('code', 'model') + '_sub'), suffix)
            sub_fields = []
            sub_fields_map = {}
            for sf in f["sub_fields"]:
                field_payload = _build_model_field_payload(sf)
                sfc = field_payload["fieldCode"]
                sub_fields.append(field_payload)
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
        field_payload = _build_model_field_payload(f)
        main_fields.append(field_payload)
        fields_map[f["name"]] = field_payload["fieldCode"]

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
            # 先确认模型是否真的已存在 — 如果刚创建成功但平台误报，直接当成功处理
            logger.info(f"模型 {model['name']} 报编码冲突，检查是否实际已创建...")
            # 回退到复用模式 — 优先按编码匹配，同名时选字段最多的
            refreshed = await client.query_models(app_id)
            ref_by_code = {rm.get("modelCode"): rm for rm in refreshed}
            ref_by_name = {}
            for rm in refreshed:
                name = rm.get("modelName")
                # 同名模型保留字段最多的（避免误匹配到子表）
                if name not in ref_by_name or len(rm.get("fields", [])) > len(ref_by_name[name].get("fields", [])):
                    ref_by_name[name] = rm
            current_main_code = model_info_entries.get(str(model_index), {}).get("code", mc)
            rm = ref_by_code.get(current_main_code) or ref_by_name.get(model["name"])
            if rm:
                existing_fields = _extract_fields(rm)
                model_info_entries[str(model_index)] = {
                    "name": model["name"], "code": rm["modelCode"], "fields": existing_fields,
                }
                # 补齐缺失字段
                model_id = rm.get("id") or rm.get("modelId")
                if model_id:
                    missing = []
                    for f in model.get("fields", []):
                        if f.get("type") == "子表":
                            continue
                        if f["name"] not in existing_fields:
                            missing.append(f)
                            try:
                                field_payload = _build_model_field_payload(f)
                                await client._post_resource(
                                    "/modelField/add",
                                    {"modelId": model_id, "appId": app_id,
                                     "fieldCode": field_payload["fieldCode"], "fieldName": f["name"],
                                     "fieldType": field_payload["fieldType"],
                                     "databaseFieldType": field_payload["databaseFieldType"], "fieldStatus": "ENABLE",
                                     "fieldComment": field_payload["fieldComment"],
                                     **({"maxLength": field_payload["maxLength"]} if "maxLength" in field_payload else {})},
                                    app_id=app_id)
                                existing_fields[f["name"]] = field_payload["fieldCode"]
                                logger.info(f"模型 {model['name']} 补齐字段: {f['name']} ({field_payload['fieldCode']})")
                            except Exception as add_err:
                                logger.warning(f"模型 {model['name']} 补齐字段 {f['name']} 失败: {add_err}")
                    if missing:
                        # 刷新字段编码（平台可能改了编码）
                        refreshed2 = await client.query_models(app_id)
                        for rm2 in refreshed2:
                            if rm2.get("modelCode") == rm["modelCode"]:
                                model_info_entries[str(model_index)]["fields"] = _extract_fields(rm2)
                                break

                for f in model.get("fields", []):
                    if f.get("type") == "子表":
                        srm = ref_by_code.get(
                            model_info_entries.get(f"{model_index}_sub_{f['name']}", {}).get("code")
                        ) or ref_by_name.get(f["name"])
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
        "message": f"创建成功: {model['name']} ({len(main_fields)} 个字段)" + ("，已自动规避数据库关键词" if keyword_retry_applied else ""),
    }


async def _update_existing_form(
    client: APaaSClient, app_id: str, form_id: str,
    model: dict, model_index: int, mi: dict,
    dict_codes: Dict[str, str], all_models: List[dict],
    model_info: Dict[str, dict],
):
    """已有表单：查询当前配置，补齐缺失的字段组件。"""
    form_config = await client.query_form_config(app_id, form_id)
    if not form_config:
        return

    # 收集已有组件的 modelField（形如 "model_code.field_code"）
    existing_mfs = set()
    def _collect_mfs(comps: list):
        for c in comps:
            mf = c.get("modelField", "")
            if mf:
                existing_mfs.add(mf)
            # 子表列
            for col in c.get("tableColumn", []):
                cmf = col.get("modelField", "")
                if cmf:
                    existing_mfs.add(cmf)
    _collect_mfs(form_config.get("components", []))

    model_code = mi["code"]
    model_fields = mi["fields"]
    new_components = []

    for f in model.get("fields", []):
        ftype = f.get("type", "单行输入")
        if ftype == "子表":
            continue
        fc = model_fields.get(f["name"])
        if not fc:
            continue
        mf = f"{model_code}.{fc}"
        if mf not in existing_mfs:
            new_components.append(_build_component(f, model_code, fc, dict_codes, all_models, model_info))

    if not new_components:
        return  # 没有需要补齐的组件

    # 追加到已有配置
    form_config.setdefault("components", []).extend(new_components)
    logger.info(
        "save_form_config reason: 补齐已有表单缺失组件 (form=%s, added=%s)",
        model["name"],
        len(new_components),
    )
    await client.save_form_config(app_id, form_config)
    logger.info(f"表单 {model['name']} 补齐 {len(new_components)} 个组件")


# ------------------------------------------------------------------
# Step 4: 创建单个表单
# ------------------------------------------------------------------

def _resolve_form_main_model(
    form: dict,
    model_info: Dict[str, dict],
) -> tuple[str, str, List[str], dict]:
    """从 form + model_info 里解析主模型上下文。

    返回 (form_name, main_model_code, all_model_codes, main_model_info)。
    主模型未找到时 raise ValueError，跟原有行为一致。
    """
    form_name = form.get("name") or form.get("formName") or "未命名表单"
    main_model_code = str(form.get("modelCode", form.get("model_code", ""))).strip()
    all_model_codes_raw = [
        str(code).strip()
        for code in (form.get("allModelCodes") or form.get("all_model_codes") or [])
        if str(code).strip()
    ]
    all_model_codes = list(dict.fromkeys(
        ([main_model_code] if main_model_code else []) + all_model_codes_raw
    ))

    model_info_by_code = {
        str(info.get("code", "")).strip(): info
        for info in model_info.values()
        if isinstance(info, dict) and str(info.get("code", "")).strip()
    }
    mi = model_info_by_code.get(main_model_code)
    if not mi:
        raise ValueError(f"表单 {form_name} 的主模型 {main_model_code or '-'} 尚未创建")
    return form_name, main_model_code, all_model_codes, mi


async def _find_existing_form_reuse(
    client: APaaSClient,
    app_id: str,
    form_name: str,
) -> Optional[dict]:
    """查平台已有菜单，若 form_name 已存在则返回复用用的 form_result，否则返回 None。

    query_menus 失败时按原逻辑静默忽略（视为"没有已存在表单"），不中断流程。
    """
    existing_forms: Dict[str, dict] = {}
    try:
        menus = await client.query_menus(app_id)

        def _collect(items: list):
            for item in items:
                if item.get("formId"):
                    existing_forms[item.get("menuName", "")] = {
                        "formId": item["formId"],
                        "menuId": item.get("id", ""),
                    }
                _collect(item.get("submenus", []) or item.get("children", []) or [])

        _collect(menus)
    except Exception:
        pass

    if form_name not in existing_forms:
        return None
    ef = existing_forms[form_name]
    return {
        "formId": ef["formId"],
        "formName": form_name,
        "formCode": "",
        "menuId": ef["menuId"],
        "reused": True,
        "message": f"复用已有表单: {form_name}",
    }


def _resolve_form_code(form: dict, form_name: str) -> str:
    """生成或取出 form_code。

    优先级：form.formCode > form.form_code > 随机 `form_XXXXXX` > 基于 form.code/name 的 sanitize。
    """
    form_code = str(form.get("formCode", form.get("form_code", ""))).strip()
    if form_code:
        return form_code
    form_code_suffix = _rand(6)
    if form_code_suffix:
        return f"form_{form_code_suffix}"
    return f"form_{_sanitize_code(form.get('code', form_name))}"


async def execute_create_form(
    client: APaaSClient,
    app_id: str,
    form: dict,
    form_index: int,
    dict_codes: Dict[str, str],
    model_info: Dict[str, dict],
    all_models: List[dict],
    all_forms: Optional[List[dict]] = None,
    form_results: Optional[List[dict]] = None,
) -> dict:
    """创建单个表单 + 绑定字典，返回 form 结果。"""
    form_name, main_model_code, all_model_codes, mi = _resolve_form_main_model(form, model_info)

    reuse_result = await _find_existing_form_reuse(client, app_id, form_name)
    if reuse_result is not None:
        return reuse_result

    model_code = mi["code"]
    components = []
    query_conditions = []
    query_list = []
    listable = 0
    form_components = form.get("components", []) or []
    sub_groups: Dict[str, dict] = {}
    for comp in form_components:
        section_type = str(comp.get("sectionType", comp.get("section_type", "main"))).strip() or "main"
        component_model_code = str(comp.get("modelCode", comp.get("model_code", ""))).strip() or model_code
        table_model_code = str(comp.get("tableModelCode", comp.get("table_model_code", ""))).strip() or component_model_code
        model_field = str(comp.get("modelField", comp.get("model_field", ""))).strip()
        field_code = model_field.split(".", 1)[1] if "." in model_field else str(comp.get("code", "")).strip()
        label = comp.get("label") or comp.get("name") or field_code
        component_type = comp.get("componentType") or comp.get("component_type") or "FORM_TEXT_INPUT"
        built = {
            "componentType": component_type,
            "label": label,
            "modelField": f"{component_model_code}.{field_code}" if field_code else model_field,
        }
        for key in ("hidden", "readonly", "required", "showInList", "searchable"):
            if key in comp:
                built[key] = bool(comp.get(key))

        desired_component_type = str(component_type).strip()
        target_model_code, target_field, origin_field = _resolve_component_reference(comp, _form_identity_map(all_forms or []))
        if desired_component_type in ("FORM_DATA_SELECTOR_SINGLE", "FORM_DATA_SELECTOR") and target_model_code:
            built["componentType"] = desired_component_type
            built["dataSelectorConfig"] = {
                "type": "LOV_CHOOSE",
                "otherModelCode": target_model_code,
                "otherFieldCode": target_field,
            }
        elif desired_component_type == "FORM_ASSOCIATION" and target_model_code:
            built["componentType"] = "FORM_ASSOCIATION"
            built["formAssociationConfig"] = {
                "originFieldCode": origin_field or field_code,
                "targetModelCode": target_model_code,
                "targetFieldCode": target_field,
            }

        if section_type == "sub":
            group = sub_groups.setdefault(table_model_code, {
                "componentType": "FORM_WIDGET_SON_TABLE",
                "label": comp.get("subTableLabel") or label or table_model_code,
                "tableColumn": [],
            })
            if comp.get("subTableLabel"):
                group["label"] = comp.get("subTableLabel")
            group["tableColumn"].append(built)
            continue

        components.append(built)
        if built.get("showInList") and listable < 8 and field_code:
            mf = built["modelField"]
            if built.get("searchable") and len(query_conditions) < 4:
                query_conditions.append(mf)
            query_list.append(mf)
            listable += 1

    components.extend(sub_groups.values())

    if not components:
        model_fields = mi["fields"]
        logger.warning(f"表单 {form_name}: 配置组件为空, 降级使用平台实际字段: {list(model_fields.keys())}")
        for field_name, field_code in model_fields.items():
            fallback_field = {"name": field_name, "type": "单行输入", "required": False}
            components.append(_build_component(fallback_field, model_code, field_code, dict_codes, all_models, model_info))
            if listable < 8:
                mf = f"{model_code}.{field_code}"
                if listable < 4:
                    query_conditions.append(mf)
                query_list.append(mf)
                listable += 1

    if not components:
        raise ValueError(f"表单 {form_name} 无可用字段组件")

    # formCode: 使用模型编码或生成唯一标识
    form_code = _resolve_form_code(form, form_name)

    form_payload = [{
        "formName": form_name,
        "formCode": form_code,
        "allModelCodes": all_model_codes,
        "formComponents": components,
        "listPageView": {
            "queryConditions": query_conditions,
            "queryList": query_list,
        },
    }]

    logger.info(
        "execute_create_form payload (%s):\n%s",
        form_name,
        json.dumps(form_payload, ensure_ascii=False, indent=2),
    )

    result = await client.create_form_config(app_id, form_payload)
    form_result = {
        "formId": "", "formName": form_name, "formCode": "", "menuId": "",
        "reused": False, "message": f"创建成功: {form_name}",
    }

    if isinstance(result, list):
        for fr in result:
            if isinstance(fr, dict) and "id" in fr:
                form_result["formId"] = fr["id"]
                form_result["formCode"] = fr.get("formCode", "")
                form_result["menuId"] = fr.get("menuId", "")
                # 平台 formConfig API 会自动创建菜单，但菜单名可能是默认值（如"我的待办"）
                # 需要用返回的 menuId 更新菜单名为实际的模型名称
                menu_id = fr.get("menuId", "")
                try:
                    if menu_id:
                        # 有 menuId：更新已有菜单名称
                        await client.create_menu(app_id, form_name, fr["id"], menu_order=form_index, menu_id=menu_id)
                        logger.info(f"更新菜单名称: {form_name} (menuId={menu_id})")
                    else:
                        # 没有 menuId：创建新菜单
                        await client.create_menu(app_id, form_name, fr["id"], menu_order=form_index)
                except Exception as menu_err:
                    logger.warning(f"创建/更新菜单失败（{form_name}）: {menu_err}")

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
            for comp in form_components:
                ct = str(comp.get("componentType", comp.get("component_type", "")))
                if ct in ("FORM_SELECT_INPUT_SINGLE", "FORM_SELECT_INPUT"):
                    dict_code = comp.get("dict") or comp.get("dictCode") or comp.get("dict_code")
                    if dict_code:
                        label_dict[comp.get("label", "")] = dict_codes.get(dict_code, dict_code)

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
                logger.info("save_form_config reason: 字典绑定回写 (form=%s)", form_name)
                await client.save_form_config(app_id, fc)
                form_result["message"] += "（含字典绑定）"
        except Exception as e:
            logger.warning(f"字典绑定失败（不阻断）: {e}")

    # --- 回写数据选择 / 关联表单引用 ---
    if form_result["formId"]:
        try:
            await _sync_form_component_references(
                client=client,
                app_id=app_id,
                form_id=form_result["formId"],
                form_def=form,
                all_forms=all_forms or [],
                form_results=form_results or [],
            )
        except Exception as e:
            logger.warning(f"表单引用回写失败（不阻断）: {e}")

    return form_result


def _form_identity_map(forms: List[dict]) -> Dict[str, dict]:
    mapping: Dict[str, dict] = {}
    for form in forms:
        for key in (
            form.get("formCode"), form.get("form_code"), form.get("code"),
            form.get("formName"), form.get("name"),
            form.get("modelCode"), form.get("model_code"),
        ):
            value = str(key or "").strip()
            if value:
                mapping.setdefault(value, form)
    return mapping


def _form_result_identity_map(form_results: List[dict]) -> Dict[str, dict]:
    mapping: Dict[str, dict] = {}
    for result in form_results:
        for key in (result.get("formCode"), result.get("formName"), result.get("modelCode")):
            value = str(key or "").strip()
            if value:
                mapping.setdefault(value, result)
    return mapping


def _component_definition_map(components: List[dict]) -> Dict[str, dict]:
    mapping: Dict[str, dict] = {}
    for comp in components or []:
        code = str(comp.get("code", "")).strip()
        if code and code not in mapping:
            mapping[code] = comp
        model_field = str(comp.get("modelField", comp.get("model_field", ""))).strip()
        if model_field and model_field not in mapping:
            mapping[model_field] = comp
        label = str(comp.get("label", "")).strip()
        if label and label not in mapping:
            mapping[label] = comp
    return mapping


def _resolve_component_reference(comp_def: dict, form_map: Dict[str, dict]) -> tuple[str, str, str]:
    association = comp_def.get("formAssociationConfig") or comp_def.get("form_association_config") or {}
    ref = comp_def.get("ref") or {}
    target = (
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
    origin_field = str(association.get("originFieldCode") or comp_def.get("association_origin_field_code") or "").strip()

    resolved_form = form_map.get(target)
    if resolved_form:
        target_model_code = str(resolved_form.get("modelCode", resolved_form.get("model_code", target))).strip() or target
        return target_model_code, target_field, origin_field
    return target, target_field, origin_field


def _resolve_target_form_result(
    comp_def: dict,
    form_map: Dict[str, dict],
    form_results: List[dict],
    target_model_code: str,
) -> Optional[dict]:
    ref = comp_def.get("ref") or {}
    for value in (
        comp_def.get("selector_form_code"),
        comp_def.get("association_form_code"),
        comp_def.get("formCode"),
        comp_def.get("form_code"),
        comp_def.get("code"),
        ref.get("formCode") if isinstance(ref, dict) else "",
    ):
        candidate = str(value or "").strip()
        if not candidate:
            continue
        form_def = form_map.get(candidate)
        if not form_def:
            continue
        for form_result in form_results:
            if (
                form_result.get("formCode") == form_def.get("formCode")
                or form_result.get("formCode") == form_def.get("code")
                or form_result.get("formName") == form_def.get("formName")
                or form_result.get("formName") == form_def.get("name")
                or form_result.get("modelCode") == form_def.get("modelCode")
            ):
                return form_result

    for form_result in form_results:
        if str(form_result.get("modelCode", "")).strip() == target_model_code:
            return form_result
    return None


def _iter_form_components(form_components: List[dict]) -> List[dict]:
    items: List[dict] = []
    for component in form_components or []:
        items.append(component)
        if component.get("componentType") == "FORM_WIDGET_SON_TABLE":
            items.extend(component.get("tableColumn", []) or [])
    return items


def _component_field_code(component: dict) -> str:
    model_field = str(component.get("modelField", "")).strip()
    if "." in model_field:
        return model_field.split(".", 1)[1]
    return str(component.get("code", "")).strip()


def _find_component_by_field(
    form_components: List[dict],
    field_code: str,
    *,
    label: str = "",
) -> Optional[dict]:
    normalized_field = str(field_code or "").strip()
    normalized_label = str(label or "").strip()
    for component in _iter_form_components(form_components):
        if normalized_field and _component_field_code(component) == normalized_field:
            return component
        if normalized_label and str(component.get("label", "")).strip() == normalized_label:
            return component
    return None


def _build_display_component_refs(form_components: List[dict], field_codes: List[str]) -> List[dict]:
    refs: List[dict] = []
    seen: set[str] = set()
    for field_code in field_codes:
        component = _find_component_by_field(form_components, field_code)
        component_uuid = str(component.get("uuid", "")).strip() if component else ""
        if not component_uuid or component_uuid in seen:
            continue
        seen.add(component_uuid)
        item = {
            "id": component_uuid,
            "componentType": component.get("componentType", "FORM_TEXT_INPUT"),
            "name": component.get("label", "") or component.get("modelFieldName", "") or field_code,
        }
        if component.get("chooseOptions"):
            item["chooseOptions"] = component.get("chooseOptions")
        if "multicolor" in component:
            item["multicolor"] = bool(component.get("multicolor"))
        refs.append(item)
    return refs


def _build_form_assignment(current_component: dict, target_component: dict, target_form_id: str) -> dict:
    return {
        "currentFormComponent": current_component.get("uuid", ""),
        "currentFormComponentType": current_component.get("componentType", "FORM_TEXT_INPUT"),
        "otherFormComponent": target_component.get("uuid", ""),
        "otherFormComponentType": target_component.get("componentType", "FORM_TEXT_INPUT"),
        "otherFormId": target_form_id,
    }


def _build_permission_groups_for_form_config(
    rules: List[dict],
    role_codes: Dict[str, dict],
) -> tuple[List[dict], List[dict], List[dict]]:
    permission_groups: List[dict] = []
    advanced_groups: List[dict] = []
    operation_groups: List[dict] = []

    for index, rule in enumerate(rules, start=1):
        role_code = str(rule.get("roleCode") or rule.get("role") or "").strip()
        role_info = role_codes.get(role_code, {}) if role_code else {}
        perm_obj = _resolve_permission_object(rule, role_codes)
        resolved_role_name = str(role_info.get("roleName") or "").strip()
        raw_role_name = str(rule.get("roleName") or "").strip()
        role_name = (
            resolved_role_name
            or (raw_role_name if raw_role_name and raw_role_name != role_code else "")
            or str(perm_obj["permissionObjectDisplayName"] or role_code).strip()
        )
        range_type = _normalize_permission_range(rule.get("data", "ALL"))
        ops = _parse_permission_ops(rule.get("op", "all"))
        can_view = "all" in ops or "view" in ops
        can_add = "all" in ops or "add" in ops
        can_edit = "all" in ops or "edit" in ops
        can_delete = "all" in ops or "delete" in ops
        can_import = bool(rule.get("canImport"))
        can_draft = bool(rule.get("canDraft"))
        can_export = bool(rule.get("canExport"))

        if perm_obj["permissionObjectType"] == "ROLE":
            role_id = str(role_info.get("id") or "").strip()
            role_code_value = (
                str(role_info.get("roleCode") or "").strip()
                or role_code
                or perm_obj["permissionObjectValue"]
            )
            object_type = "ROLE"
            object_value = role_id or role_code_value
            object_name = role_name
        else:
            object_type = "ALL_USER"
            object_value = "ALL_USER"
            object_name = "全部人员"

        permission_groups.append({
            "groupConditions": [],
            "selectorFilterConditionList": [],
            "dataPermissions": [{
                "permissionType": object_type,
                "permissionValue": object_value,
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


async def _sync_form_component_references(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    form_def: dict,
    all_forms: List[dict],
    form_results: List[dict],
) -> None:
    if not form_id:
        return

    form_map = _form_identity_map(all_forms)
    comp_def_map = _component_definition_map(form_def.get("components", []) or [])
    form_config = await client.query_detail_page_config(app_id, form_id)
    components = form_config.get("detailPage", {}).get("formComponents", [])
    updated = False

    def _match_comp_def(component: dict) -> Optional[dict]:
        label = str(component.get("label", "")).strip()
        if label and label in comp_def_map:
            return comp_def_map[label]
        field_code = _component_field_code(component)
        if field_code and field_code in comp_def_map:
            return comp_def_map[field_code]
        model_field = str(component.get("modelField", "")).strip()
        if model_field and model_field in comp_def_map:
            return comp_def_map[model_field]
        return None

    target_form_cache: Dict[str, dict] = {}

    async def _get_target_form_payload(target_form_result: dict) -> dict:
        target_form_id = str(target_form_result.get("formId", "")).strip()
        if not target_form_id:
            return {}
        if target_form_id not in target_form_cache:
            target_form_cache[target_form_id] = await client.query_detail_page_config(app_id, target_form_id)
        return target_form_cache[target_form_id]

    async def _apply_reference(component: dict, comp_def: dict) -> bool:
        desired_component_type = str(
            comp_def.get("componentType") or comp_def.get("component_type") or ""
        ).strip()
        target_model_code, target_field, origin_field = _resolve_component_reference(comp_def, form_map)
        if not target_model_code:
            return False

        target_form_result = _resolve_target_form_result(comp_def, form_map, form_results, target_model_code)
        if not target_form_result:
            return False

        target_form_payload = await _get_target_form_payload(target_form_result)
        target_components = target_form_payload.get("detailPage", {}).get("formComponents", [])
        target_component = _find_component_by_field(target_components, target_field)
        if not target_component:
            return False

        changed = False
        if desired_component_type in ("FORM_DATA_SELECTOR_SINGLE", "FORM_DATA_SELECTOR"):
            if component.get("componentType") != desired_component_type:
                component["componentType"] = desired_component_type
                changed = True
            display_field_codes: List[str] = []
            target_form_def = _form_identity_map(all_forms).get(
                str(target_form_result.get("formCode") or target_form_result.get("formName") or target_form_result.get("modelCode") or "")
            )
            if target_form_def:
                for target_comp_def in target_form_def.get("components", []) or []:
                    if bool(target_comp_def.get("showInList")):
                        model_field = str(target_comp_def.get("modelField", target_comp_def.get("model_field", ""))).strip()
                        display_code = model_field.split(".", 1)[1] if "." in model_field else str(target_comp_def.get("code", "")).strip()
                        if display_code:
                            display_field_codes.append(display_code)
            if target_field and target_field not in display_field_codes:
                display_field_codes.append(target_field)
            display_components = _build_display_component_refs(target_components, display_field_codes) or [{
                "id": target_component.get("uuid", ""),
                "name": target_component.get("label", "") or target_field,
                "componentType": target_component.get("componentType", "FORM_TEXT_INPUT"),
            }]
            desired_selector = {
                "type": "LOV_CHOOSE",
                "otherFormId": str(target_form_result.get("formId", "")).strip(),
                "otherFormName": target_form_result.get("formName", ""),
                "otherComponent": target_component.get("uuid", ""),
                "otherComponentName": target_component.get("label", "") or target_field,
                "otherComponentType": target_component.get("componentType", "FORM_TEXT_INPUT"),
                "displayComponents": display_components,
            }
            if component.get("dataSelector") != desired_selector:
                component["dataSelector"] = desired_selector
                changed = True
            desired_bof_type = "BOF_SINGLE_DATA_SELECTOR" if desired_component_type == "FORM_DATA_SELECTOR_SINGLE" else "BOF_DATA_SELECTOR"
            if component.get("businessObjectComponentType") != desired_bof_type:
                component["businessObjectComponentType"] = desired_bof_type
                changed = True
            if component.get("placeholder") != "请选择":
                component["placeholder"] = "请选择"
                changed = True
            for key in ("associationFormId", "associationField", "displayFields", "displayStyle", "quoteViewType", "assocAllowNew", "assocTabId", "tableOrders", "formAssociationConfig"):
                if key in component:
                    component.pop(key, None)
                    changed = True
        elif desired_component_type == "FORM_ASSOCIATION":
            if component.get("componentType") != "FORM_ASSOCIATION":
                component["componentType"] = "FORM_ASSOCIATION"
                changed = True
            desired_origin = origin_field or str(component.get("modelField", "")).split(".", 1)[-1]
            origin_component = _find_component_by_field(components, desired_origin)
            if not origin_component:
                return False
            target_form_def = _form_identity_map(all_forms).get(
                str(target_form_result.get("formCode") or target_form_result.get("formName") or target_form_result.get("modelCode") or "")
            )
            display_field_codes: List[str] = []
            if target_form_def:
                for target_comp_def in target_form_def.get("components", []) or []:
                    if bool(target_comp_def.get("showInList")):
                        model_field = str(target_comp_def.get("modelField", target_comp_def.get("model_field", ""))).strip()
                        display_code = model_field.split(".", 1)[1] if "." in model_field else str(target_comp_def.get("code", "")).strip()
                        if display_code:
                            display_field_codes.append(display_code)
            if target_field and target_field not in display_field_codes:
                display_field_codes.append(target_field)
            display_refs = _build_display_component_refs(target_components, display_field_codes) or [{
                "id": target_component.get("uuid", ""),
                "componentType": target_component.get("componentType", "FORM_TEXT_INPUT"),
            }]
            desired_association_field = {
                "originUuid": origin_component.get("uuid", ""),
                "targetUuid": target_component.get("uuid", ""),
            }
            if component.get("associationField") != desired_association_field:
                component["associationField"] = desired_association_field
                changed = True
            if component.get("associationFormId") != target_form_result.get("formId", ""):
                component["associationFormId"] = target_form_result.get("formId", "")
                changed = True
            display_field_ids = [item["id"] for item in display_refs if item.get("id")]
            if component.get("displayFields") != display_field_ids:
                component["displayFields"] = display_field_ids
                changed = True
            if component.get("displayStyle") != "PAGE_TABLE":
                component["displayStyle"] = "PAGE_TABLE"
                changed = True
            if component.get("quoteViewType") != "LIST_VIEW":
                component["quoteViewType"] = "LIST_VIEW"
                changed = True
            if component.get("assocAllowNew") is not False:
                component["assocAllowNew"] = False
                changed = True
            if component.get("assocTabId") != "":
                component["assocTabId"] = ""
                changed = True
            if component.get("tableOrders") != []:
                component["tableOrders"] = []
                changed = True
            if component.get("businessObjectComponentType") != "BOF_ASSOCIATION":
                component["businessObjectComponentType"] = "BOF_ASSOCIATION"
                changed = True
        return changed

    for component in components:
        if component.get("componentType") == "FORM_WIDGET_SON_TABLE":
            for column in component.get("tableColumn", []) or []:
                comp_def = _match_comp_def(column)
                if comp_def and await _apply_reference(column, comp_def):
                    updated = True
            continue

        comp_def = _match_comp_def(component)
        if comp_def and await _apply_reference(component, comp_def):
            updated = True

    if updated:
        logger.info(
            "save_form_config reason: 回写表单引用 (form=%s, formId=%s)",
            form_def.get("name") or form_def.get("formName") or form_id,
            form_id,
        )
        await client.save_form_config(app_id, form_config)


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

def _parse_permission_ops(op: object) -> set[str]:
    if isinstance(op, str):
        raw_ops = op.replace(" ", "").split(",") if "," in op else [op]
    elif isinstance(op, (list, tuple, set)):
        raw_ops = list(op)
    else:
        raw_ops = ["all"]
    return {str(item).strip() for item in raw_ops if str(item).strip()}


def _resolve_permission_object(rule: dict, role_codes: Dict[str, dict]) -> dict:
    role_code = rule.get("role", "")
    if role_code and role_code != "all":
        role_info = role_codes.get(role_code, {})
        role_name = role_info.get("roleName") or rule.get("roleName") or role_code
        role_value = role_info.get("id") or role_info.get("roleCode", role_code)
        return {
            "permissionObjectType": "ROLE",
            "permissionObjectValue": role_value,
            "permissionObjectDisplayName": role_name,
        }
    return {
        "permissionObjectType": "ALL_USER",
        "permissionObjectValue": "",
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


def _default_form_permission_payload(app_id: str, form_code: str, form_id: str) -> dict:
    return {
        "formCode": form_code,
        "appId": app_id,
        "tenantId": "",
        "formId": form_id,
        "operationPermissionGroups": [{
            "permissionName": "默认操作权限",
            "permissionDescribe": "全部人员可操作",
            "permissionObjects": [{
                "permissionObjectDisplayName": "全部人员",
                "permissionObjectType": "ALL_USER",
                "permissionObjectValue": "",
                "permissionRange": {"rangeType": "ALL"},
            }],
            "permissionOperationType": {
                "addPermission": True,
                "batchAgreePermission": False,
                "batchDeletePermission": False,
                "batchRejectPermission": False,
                "copyAddPermission": False,
                "importPermission": False,
                "shareFormPermission": False,
                "temporaryStoragePermission": False,
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
                "queryPermission": True,
                "deletePermission": False,
                "updatePermission": False,
                "commentPermission": True,
                "dataSharePermission": True,
                "exportPermission": False,
                "logPermission": True,
                "printPermission": True,
                "queryApprovalInfoPermission": True,
            },
        }],
    }


def _build_form_permission_payload(
    app_id: str,
    form_code: str,
    form_id: str,
    rules: List[dict],
    role_codes: Dict[str, dict],
) -> dict:
    operation_groups: Dict[tuple, dict] = {}
    data_groups: Dict[tuple, dict] = {}

    for rule in rules:
        perm_obj = _resolve_permission_object(rule, role_codes)
        perm_obj_type = perm_obj["permissionObjectType"]
        perm_obj_value = perm_obj["permissionObjectValue"]
        perm_obj_name = perm_obj["permissionObjectDisplayName"]
        ops = _parse_permission_ops(rule.get("op", "all"))
        range_type = _normalize_permission_range(rule.get("data", "ALL"))
        can_view = "all" in ops or "view" in ops
        can_add = "all" in ops or "add" in ops
        can_edit = "all" in ops or "edit" in ops
        can_delete = "all" in ops or "delete" in ops
        can_import = bool(rule.get("canImport"))
        can_draft = bool(rule.get("canDraft"))
        can_export = bool(rule.get("canExport"))

        has_operation = any((can_add, can_import, can_draft))
        if has_operation:
            op_key = (perm_obj_type, perm_obj_value)
            if op_key not in operation_groups:
                operation_groups[op_key] = {
                    "permissionName": f"{perm_obj_name}操作权限",
                    "permissionDescribe": "",
                    "permissionObjects": [{
                        "permissionObjectDisplayName": perm_obj_name,
                        "permissionObjectType": perm_obj_type,
                        "permissionObjectValue": perm_obj_value,
                        "permissionRange": {"rangeType": "ALL"},
                    }],
                    "permissionOperationType": {
                        "addPermission": False,
                        "batchAgreePermission": False,
                        "batchDeletePermission": False,
                        "batchRejectPermission": False,
                        "copyAddPermission": False,
                        "importPermission": False,
                        "shareFormPermission": False,
                        "temporaryStoragePermission": False,
                    },
                }

            perm_op = operation_groups[op_key]["permissionOperationType"]
            perm_op["addPermission"] = perm_op["addPermission"] or can_add
            perm_op["importPermission"] = perm_op["importPermission"] or can_import
            perm_op["temporaryStoragePermission"] = perm_op["temporaryStoragePermission"] or can_draft

        data_key = (perm_obj_type, perm_obj_value, range_type)
        if data_key not in data_groups:
            data_groups[data_key] = {
                "permissionName": f"{perm_obj_name}数据权限",
                "permissionDescribe": "",
                "permissionObjects": [{
                    "permissionObjectDisplayName": perm_obj_name,
                    "permissionObjectType": perm_obj_type,
                    "permissionObjectValue": perm_obj_value,
                    "permissionRange": {"rangeType": range_type},
                }],
                "permissionOperationType": {
                    "queryPermission": False,
                    "deletePermission": False,
                    "updatePermission": False,
                    "commentPermission": False,
                    "dataSharePermission": False,
                    "exportPermission": False,
                    "logPermission": False,
                    "printPermission": False,
                    "queryApprovalInfoPermission": False,
                },
            }

        data_perm = data_groups[data_key]["permissionOperationType"]
        data_perm["queryPermission"] = data_perm["queryPermission"] or can_view
        data_perm["deletePermission"] = data_perm["deletePermission"] or can_delete
        data_perm["updatePermission"] = data_perm["updatePermission"] or can_edit
        data_perm["commentPermission"] = data_perm["commentPermission"] or can_view
        data_perm["dataSharePermission"] = data_perm["dataSharePermission"] or can_view
        data_perm["exportPermission"] = data_perm["exportPermission"] or can_export
        data_perm["logPermission"] = data_perm["logPermission"] or can_view
        data_perm["printPermission"] = data_perm["printPermission"] or can_view
        data_perm["queryApprovalInfoPermission"] = data_perm["queryApprovalInfoPermission"] or can_view

    return {
        "formCode": form_code,
        "appId": app_id,
        "tenantId": "",
        "formId": form_id,
        "operationPermissionGroups": list(operation_groups.values()),
        "dataPermissionGroups": list(data_groups.values()),
    }


async def _sync_form_permissions_to_form_config(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    rules: List[dict],
    role_codes: Dict[str, dict],
) -> None:
    """将权限同步回表单详情配置，确保平台页面权限设置能读到业务权限组。"""
    form_config = await client.query_detail_page_config(app_id, form_id)
    permission_groups, advanced_groups, operation_groups = _build_permission_groups_for_form_config(
        rules,
        role_codes,
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


async def execute_configure_permissions(
    client: APaaSClient,
    app_id: str,
    permissions: List[dict],
    form_results: List[dict],
    role_codes: Optional[Dict[str, dict]] = None,
    all_forms: Optional[List[dict]] = None,
) -> dict:
    """为所有表单配置权限。"""
    role_codes = role_codes or {}
    perm_payloads = []
    permission_sync_jobs: List[dict] = []
    form_defs_by_identity = _form_identity_map(all_forms or [])
    for fr in form_results:
        form_code = fr.get("formCode", "")
        form_id = fr.get("formId", "")
        form_name = fr.get("formName", "")
        model_code = fr.get("modelCode", "")
        form_def = (
            form_defs_by_identity.get(form_code)
            or form_defs_by_identity.get(form_name)
            or form_defs_by_identity.get(model_code)
        )

        if form_def:
            try:
                await _sync_form_component_references(
                    client=client,
                    app_id=app_id,
                    form_id=form_id,
                    form_def=form_def,
                    all_forms=all_forms or [],
                    form_results=form_results,
                )
            except Exception as exc:
                logger.warning("最终表单引用回写失败（%s）: %s", form_name or form_id, exc)

        user_perm = next((
            p for p in permissions
            if p.get("form") == form_name
            or p.get("formName") == form_name
            or p.get("formCode") == form_code
            or p.get("form_code") == form_code
        ), None)

        if user_perm and user_perm.get("rules"):
            rules = user_perm["rules"]
            perm_payloads.append(
                _build_form_permission_payload(
                    app_id=app_id,
                    form_code=form_code,
                    form_id=form_id,
                    rules=rules,
                    role_codes=role_codes,
                )
            )
            permission_sync_jobs.append({
                "form_id": form_id,
                "rules": rules,
            })
    if perm_payloads:
        await client.create_form_permissions(app_id, perm_payloads)
        for job in permission_sync_jobs:
            await _sync_form_permissions_to_form_config(
                client=client,
                app_id=app_id,
                form_id=job["form_id"],
                rules=job["rules"],
                role_codes=role_codes,
            )
    return {"permissions_count": len(perm_payloads)}
