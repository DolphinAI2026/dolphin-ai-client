"""Copilot 分步执行器

每个 execute_* 函数对应一个独立步骤，不 yield SSE，直接返回结果 dict 或抛异常。
复用 generator_v2 的工具函数和类型映射。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from app.apaas_client import APaaSClient
from app.app_code import coerce_app_code, normalize_app_code
from app.generator_v2 import (
    _rand, _sanitize_code, _extract_fields,
    _build_component, FIELD_TYPE_MAP, COMP_TYPE_MAP, _apply_suffix,
)
from app.lowcode_standards import normalize_component_type, normalize_database_field_type, safe_field_code

logger = logging.getLogger(__name__)


def _field_value(field: dict, *keys: str, default=None):
    for key in keys:
        if key in field and field.get(key) not in (None, ""):
            return field.get(key)
    return default


def _first_non_empty(*values, default=""):
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        return value
    return default


def _normalize_database_field_type(field: dict) -> str:
    raw = _field_value(field, "database_field_type", "databaseFieldType", "db_type", "dbType")
    raw_type = _field_value(field, "type", "componentType", "fieldType", default="")
    return normalize_database_field_type(
        raw,
        component_type=raw_type,
        field_name=str(_field_value(field, "name", "fieldName", "label", default="")),
    )


def _resolve_platform_field_type(field: dict) -> str:
    """把字段定义映射到 APaaS 平台字段类型（STRING / NUM / DATE）。

    ⚠️ 与 app.config_validator._normalize_field_type 不要混淆：
        - 这里：input=dict，output=平台字段类型（发给 APaaS 的 fieldType）
        - config_validator：input=中文语义类型字符串，output=校验过的 schema 类型
    两者功能完全不同，历史上同名导致 import 时容易踩坑，已改名消歧义。
    """
    semantic = normalize_component_type(
        _field_value(field, "type", "componentType", "fieldType", default=""),
        field_name=str(_field_value(field, "name", "fieldName", "label", default="")),
        has_dict=bool(_field_value(field, "dict", "dict_code", "dictionaryCode", default="")),
        has_ref=bool(_field_value(field, "ref", "targetModelCode", "target_model_code", default="")),
    )
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
    model_code = str(field.get("_model_code") or field.get("modelCode") or field.get("model_code") or "").strip()
    payload = {
        "fieldName": field["name"],
        "fieldCode": safe_field_code(
            raw_field_code or field["name"],
            model_code=model_code,
            field_name=str(field.get("name") or raw_field_code),
        ),
        "fieldType": _resolve_platform_field_type(field),
        "databaseFieldType": _normalize_database_field_type(field),
        "fieldDescription": _normalize_field_comment(field),
        "fieldComment": _normalize_field_comment(field),
    }
    max_length = _normalize_field_length(field)
    if max_length is not None:
        payload["maxLength"] = max_length
    return payload


def _extract_field_codes(platform_model: dict) -> set[str]:
    return {
        str(f.get("fieldCode") or "").strip()
        for f in platform_model.get("fields", [])
        if str(f.get("fieldCode") or "").strip()
    }


async def _ensure_model_fields(
    client: APaaSClient,
    app_id: str,
    model_id: str,
    model_name: str,
    model_code: str,
    fields: List[dict],
    existing_fields: Dict[str, str],
    existing_field_codes: set[str],
) -> int:
    """给当前应用里的已有模型补齐缺失字段。

    判重同时看字段名和字段编码：同编码字段已存在时复用，不再重复创建；
    只有字段名和字段编码都不存在时才调用平台新增字段接口。
    """
    if not model_id:
        return 0

    added_count = 0
    for f in fields:
        if f.get("type") == "子表":
            continue
        raw_field_code = str(f.get("code") or f.get("field_code") or "").strip()
        field_name = str(f.get("name") or f.get("fieldName") or raw_field_code).strip()
        if field_name in existing_fields:
            continue
        if raw_field_code and raw_field_code in existing_field_codes:
            existing_fields[field_name] = raw_field_code
            logger.info("模型 %s 复用已有原始字段编码: %s (%s)", model_name, field_name, raw_field_code)
            continue
        field_payload = _build_model_field_payload({**f, "_model_code": model_code})
        field_code = str(field_payload["fieldCode"] or "").strip()
        if field_code and field_code in existing_field_codes:
            existing_fields[field_name] = field_code
            logger.info("模型 %s 复用已有字段编码: %s (%s)", model_name, field_name, field_code)
            continue
        try:
            await client._post_resource(
                "/modelField/add",
                {
                    "modelId": model_id,
                    "appId": app_id,
                    "fieldCode": field_payload["fieldCode"],
                    "fieldName": field_name,
                    "fieldType": field_payload["fieldType"],
                    "databaseFieldType": field_payload["databaseFieldType"],
                    "fieldStatus": "ENABLE",
                    "fieldComment": field_payload["fieldComment"],
                    **({"maxLength": field_payload["maxLength"]} if "maxLength" in field_payload else {}),
                },
                app_id=app_id,
            )
            existing_fields[field_name] = field_payload["fieldCode"]
            existing_field_codes.add(field_payload["fieldCode"])
            added_count += 1
            logger.info("模型 %s 补齐字段: %s (%s)", model_name, field_name, field_payload["fieldCode"])
        except Exception as add_err:
            logger.warning("模型 %s 补齐字段 %s 失败: %s", model_name, field_name, add_err)
    return added_count


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
    app_code = coerce_app_code(app_code, fallback="app-builder")
    apaas_result = await client.create_app(app_name, app_code, description)
    apaas_app_id = str(apaas_result) if isinstance(apaas_result, str) else str(
        apaas_result.get("id", apaas_result.get("appId", ""))
    )
    platform_app_code = ""
    if isinstance(apaas_result, dict):
        platform_app_code = normalize_app_code(apaas_result.get("appCode") or apaas_result.get("code")) or app_code
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


async def _lazy_model_fields(client: APaaSClient, app_id: str, model_id: str) -> dict:
    """懒加载单个模型的字段，返回 {"fields":[...]} 形状（喂给 _extract_fields/_extract_field_codes）。

    2026-05-28 性能修复：替代"从 query_models(全量含字段) 结果里取某个模型字段"——
    query_models 默认会给应用里**每个**模型都并发拉一次字段，建第 N 个模型时重复拉前面
    所有模型的字段 = O(N²)（实测 112 模型生成打了 1.3 万次 modelField/query，~6.5h）。
    改成只在真需要的那个 model_id 上单查。查重（模型编码唯一性）逻辑不受影响。
    """
    if not model_id:
        return {"fields": []}
    try:
        return {"fields": await client.query_model_fields(app_id, model_id)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("懒加载模型字段失败 (model_id=%s): %s", model_id, exc)
        return {"fields": []}


async def execute_create_model(
    client: APaaSClient,
    app_id: str,
    model: dict,
    model_index: int,
    suffix: str,
) -> dict:
    """创建单个数据模型（含子表），返回 model_info 条目。"""
    model_info_entries: Dict[str, dict] = {}

    # 检查是否已存在 —— with_fields=False: 只要模型列表做编码/名称查重，不给每个模型捞字段
    # （避免 O(N²)）。命中已存在模型后，才按 model_id 懒加载它的字段做字段级去重。
    existing_models = await client.query_models(app_id, with_fields=False)
    existing_by_name = {m.get("modelName"): m for m in existing_models}
    existing_by_code = {
        str(m.get("modelCode") or "").strip(): m
        for m in existing_models
        if str(m.get("modelCode") or "").strip()
    }
    raw_model_code = str(model.get("code") or "").strip()
    mc = raw_model_code or _apply_suffix(_sanitize_code(model.get("code", "model")), suffix)

    em = existing_by_code.get(mc) or existing_by_name.get(model["name"])
    if em:
        model_id = em.get("id") or em.get("modelId")
        # 懒加载命中模型的字段做字段级去重（existing_models 已不含字段，避免 O(N²)）
        em_fields = await _lazy_model_fields(client, app_id, model_id)
        existing_fields = _extract_fields(em_fields)
        existing_field_codes = _extract_field_codes(em_fields)
        model_info_entries[str(model_index)] = {
            "name": model["name"],
            "code": em["modelCode"],
            "fields": existing_fields,
            "remote_id": model_id,
        }
        # 补齐缺失字段
        added_count = await _ensure_model_fields(
            client,
            app_id,
            model_id,
            model["name"],
            em["modelCode"],
            model.get("fields", []),
            existing_fields,
            existing_field_codes,
        )
        if added_count:
            # 刷新字段编码 — 只查这一个模型（懒加载，避免全量 O(N²)）
            model_info_entries[str(model_index)]["fields"] = _extract_fields(
                await _lazy_model_fields(client, app_id, model_id)
            )
        # 复用子表
        for f in model.get("fields", []):
            if f.get("type") == "子表" and f.get("sub_fields"):
                raw_sub_code = str(f.get("sub_code") or "").strip()
                sub_code = raw_sub_code or _apply_suffix(_sanitize_code(f.get("sub_code") or model.get("code", "model") + "_sub"), suffix)
                sub_em = existing_by_code.get(sub_code) or existing_by_name.get(f["name"])
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
                field_payload = _build_model_field_payload({**sf, "_model_code": sub_code})
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
        field_payload = _build_model_field_payload({**f, "_model_code": mc})
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
                existing_field_codes = _extract_field_codes(rm)
                model_info_entries[str(model_index)] = {
                    "name": model["name"], "code": rm["modelCode"], "fields": existing_fields,
                }
                # 补齐缺失字段
                model_id = rm.get("id") or rm.get("modelId")
                added_count = await _ensure_model_fields(
                    client,
                    app_id,
                    model_id,
                    model["name"],
                    rm["modelCode"],
                    model.get("fields", []),
                    existing_fields,
                    existing_field_codes,
                )
                if added_count:
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

    # 刷新字段（平台可能追加后缀）— with_fields=False 找 id, 再按需单查（避免全量 O(N²)）
    refreshed = await client.query_models(app_id, with_fields=False)
    ref_by_code = {rm.get("modelCode"): rm for rm in refreshed}
    mi = model_info_entries.get(str(model_index))
    if mi and mi["code"] in ref_by_code:
        _mid = ref_by_code[mi["code"]].get("id") or ref_by_code[mi["code"]].get("modelId")
        mi["fields"] = _extract_fields(await _lazy_model_fields(client, app_id, _mid))
    for f in model.get("fields", []):
        if f.get("type") == "子表":
            sub_key = f"{model_index}_sub_{f['name']}"
            sub_mi = model_info_entries.get(sub_key)
            if sub_mi and sub_mi["code"] in ref_by_code:
                _smid = ref_by_code[sub_mi["code"]].get("id") or ref_by_code[sub_mi["code"]].get("modelId")
                sub_mi["fields"] = _extract_fields(await _lazy_model_fields(client, app_id, _smid))

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
    _apply_form_identity_to_form_config(form_config, form_name=model["name"])
    await client.save_form_config(app_id, form_config)
    logger.info(f"表单 {model['name']} 补齐 {len(new_components)} 个组件")


async def _merge_existing_form_components(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    form_name: str,
    desired_components: List[dict],
    query_conditions: Optional[List[str]] = None,
    query_list: Optional[List[str]] = None,
) -> int:
    if not form_id or not desired_components:
        return 0

    form_config = await client.query_form_config(app_id, form_id)
    if not form_config:
        return 0

    def _component_groups() -> List[list]:
        groups: List[list] = []
        for group in (
            form_config.get("components"),
            form_config.get("formComponents"),
            form_config.get("detailPage", {}).get("formComponents", [])
            if isinstance(form_config.get("detailPage"), dict)
            else [],
        ):
            if isinstance(group, list):
                groups.append(group)
        if not groups:
            groups.append(form_config.setdefault("components", []))
        return groups

    def _iter_components(comps: list):
        for c in comps or []:
            if not isinstance(c, dict):
                continue
            yield c
            for col in c.get("tableColumn", []) or []:
                if isinstance(col, dict):
                    yield col

    def _copy_component_props(target: dict, desired: dict) -> bool:
        changed = False
        for key in (
            "componentType",
            "label",
            "hidden",
            "readonly",
            "required",
            "showInList",
            "searchable",
            "dict",
            "dictCode",
            "dict_code",
            "dictionarySelectConfig",
            "dataSelectorConfig",
            "formAssociationConfig",
        ):
            if key not in desired:
                continue
            value = desired.get(key)
            if value is None or value == "":
                continue
            if target.get(key) != value:
                target[key] = value
                changed = True
        return changed

    existing_by_mf: dict[str, dict] = {}
    groups = _component_groups()
    for group in groups:
        for component in _iter_components(group):
            model_field = str(component.get("modelField") or "").strip()
            if model_field and model_field not in existing_by_mf:
                existing_by_mf[model_field] = component

    new_components: List[dict] = []
    updated_count = 0
    for component in desired_components:
        model_field = str(component.get("modelField") or "").strip()
        if model_field and model_field in existing_by_mf:
            if _copy_component_props(existing_by_mf[model_field], component):
                updated_count += 1
            continue
        new_components.append(component)
        if model_field:
            existing_by_mf[model_field] = component

    if new_components:
        groups[0].extend(new_components)

    list_view_changed = _sync_existing_form_list_page_view(
        form_config,
        query_conditions or [],
        query_list or [],
    )

    if not new_components and not updated_count and not list_view_changed:
        return 0

    changed_count = len(new_components) + updated_count
    logger.info(
        "save_form_config reason: 同步已有表单组件/列表页配置 (form=%s, added=%s, updated=%s, list_view=%s)",
        form_name,
        len(new_components),
        updated_count,
        list_view_changed,
    )
    _apply_form_identity_to_form_config(form_config, form_name=form_name)
    await client.save_form_config(app_id, form_config)
    return changed_count or 1


def _sync_existing_form_list_page_view(
    form_config: dict,
    query_conditions: List[str],
    query_list: List[str],
) -> bool:
    """Keep reused forms' list/search fields aligned with the normalized spec."""
    desired_conditions = [
        str(item).strip()
        for item in query_conditions
        if str(item).strip()
    ]
    desired_list = [
        str(item).strip()
        for item in query_list
        if str(item).strip()
    ]
    if not desired_conditions and not desired_list:
        return False

    changed = False
    targets = [form_config]
    simple = form_config.get("simpleFormConfig")
    if isinstance(simple, dict):
        targets.append(simple)

    for target in targets:
        list_page = target.setdefault("listPageView", {})
        if desired_conditions and list_page.get("queryConditions") != desired_conditions:
            list_page["queryConditions"] = desired_conditions
            changed = True
        if desired_list and list_page.get("queryList") != desired_list:
            list_page["queryList"] = desired_list
            changed = True
    return changed


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
    form_name = _first_non_empty(
        form.get("formName"),
        form.get("form_name"),
        form.get("name"),
        form.get("title"),
        default="未命名表单",
    )
    main_model_code = str(_first_non_empty(
        form.get("modelCode"),
        form.get("model_code"),
        form.get("mainModelCode"),
        form.get("main_model_code"),
        form.get("main_model"),
        default="",
    )).strip()
    all_model_source = form.get("allModelCodes") or form.get("all_model_codes") or []
    if isinstance(all_model_source, str):
        all_model_source = [all_model_source]
    all_model_codes_raw = [
        str(code).strip()
        for code in all_model_source
        if str(code).strip()
    ]
    if not main_model_code and all_model_codes_raw:
        main_model_code = all_model_codes_raw[0]
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

    优先级：form.formCode > form.form_code > form.code > 随机 `form_XXXXXX` > 基于 form.name 的 sanitize。
    """
    form_code = str(_first_non_empty(
        form.get("formCode"),
        form.get("form_code"),
        form.get("code"),
        default="",
    )).strip()
    if form_code:
        return form_code
    form_code_suffix = _rand(6)
    if form_code_suffix:
        return f"form_{form_code_suffix}"
    return f"form_{_sanitize_code(form.get('code', form_name))}"


def _build_create_form_payload(
    form_name: str,
    form_code: str,
    all_model_codes: List[str],
    components: List[dict],
    query_conditions: List[str],
    query_list: List[str],
) -> List[dict]:
    """组装传给 client.create_form_config 的 payload（单元素 list）。"""
    return [{
        "formName": form_name,
        "formCode": form_code,
        "allModelCodes": all_model_codes,
        "formComponents": components,
        "listPageView": {
            "queryConditions": query_conditions,
            "queryList": query_list,
        },
    }]


def _apply_form_identity_to_form_config(
    form_config: dict,
    *,
    form_name: str,
    form_code: str = "",
    all_model_codes: Optional[List[str]] = None,
    app_id: str = "",
    form_id: str = "",
    menu_id: str = "",
) -> bool:
    """Ensure queried platform form config keeps the business form identity.

    The platform may return a default form name such as "我的待办" in later
    query/save flows. Any save after creation must carry the intended formName,
    otherwise the default name can overwrite the correct one in form management.
    """
    if not isinstance(form_config, dict):
        return False

    changed = False
    desired_name = str(form_name or "").strip()
    desired_code = str(form_code or "").strip()
    desired_app_id = str(app_id or "").strip()
    desired_form_id = str(form_id or "").strip()
    desired_menu_id = str(menu_id or "").strip()
    desired_models = [
        str(code).strip()
        for code in (all_model_codes or [])
        if str(code).strip()
    ]

    def _apply(target: dict) -> None:
        nonlocal changed
        if not isinstance(target, dict):
            return
        if desired_name and target.get("formName") != desired_name:
            target["formName"] = desired_name
            changed = True
        if desired_code and target.get("formCode") != desired_code:
            target["formCode"] = desired_code
            changed = True
        if desired_models and target.get("allModelCodes") != desired_models:
            target["allModelCodes"] = desired_models
            changed = True
        if desired_app_id and target.get("appId") != desired_app_id:
            target["appId"] = desired_app_id
            changed = True
        if desired_form_id and not target.get("id"):
            target["id"] = desired_form_id
            changed = True
        if desired_menu_id and target.get("menuId") != desired_menu_id:
            target["menuId"] = desired_menu_id
            changed = True

    _apply(form_config)
    _apply(form_config.get("simpleFormConfig", {}))
    if not isinstance(form_config.get("detailPage"), dict):
        form_config["detailPage"] = {}
        changed = True
    detail_page = form_config["detailPage"]
    _apply(detail_page)
    for required_key, default_value in (
        ("webFormSettings", {}),
        ("mobileFormSettings", {}),
        ("previewLanguage", "zh-CN"),
        ("formVersionConfig", {}),
    ):
        if required_key not in detail_page:
            detail_page[required_key] = default_value
            changed = True
    if "formModelType" not in form_config:
        form_config["formModelType"] = "DATABASE"
        changed = True
    return changed


def _is_form_save_conflict(exc: Exception) -> bool:
    text = str(exc)
    return any(token in text for token in ("当前页面状态已改变", "页面状态已改变", "乐观锁", "版本", "version", "stale"))


async def _query_saveable_form_config(client: APaaSClient, app_id: str, form_id: str) -> dict:
    query_context = getattr(client, "query_form_context_config", None)
    if callable(query_context):
        try:
            return await query_context(app_id, form_id)
        except Exception as exc:
            logger.warning("query_form_context_config 失败，回退 detailPageConfigById (formId=%s): %s", form_id, exc)
    return await client.query_detail_page_config(app_id, form_id)


async def _save_form_config_with_retry(
    client: APaaSClient,
    app_id: str,
    form_config: dict,
    *,
    form_id: str,
    apply_latest=None,
    reason: str = "",
) -> dict:
    try:
        return await client.save_form_config(app_id, form_config)
    except Exception as exc:
        if not _is_form_save_conflict(exc) or not form_id:
            raise
        logger.warning("save_form_config 冲突，重新查询后重试 (formId=%s, reason=%s): %s", form_id, reason, exc)
        latest = await _query_saveable_form_config(client, app_id, form_id)
        if apply_latest:
            apply_latest(latest)
        return await client.save_form_config(app_id, latest)


async def _finalize_created_form_config(
    client: APaaSClient,
    app_id: str,
    form_id: str,
    *,
    form_name: str,
    form_code: str,
    all_model_codes: List[str],
    menu_id: str = "",
) -> None:
    if not form_id:
        return

    def _apply_latest(config: dict) -> None:
        _apply_form_identity_to_form_config(
            config,
            form_name=form_name,
            form_code=form_code,
            all_model_codes=all_model_codes,
            app_id=app_id,
            form_id=form_id,
            menu_id=menu_id,
        )

    form_config = await _query_saveable_form_config(client, app_id, form_id)
    _apply_latest(form_config)
    logger.info("save_form_config reason: 创建后固化表单详情 (form=%s, formId=%s)", form_name, form_id)
    await _save_form_config_with_retry(
        client,
        app_id,
        form_config,
        form_id=form_id,
        apply_latest=_apply_latest,
        reason="创建后固化表单详情",
    )


async def _create_form_and_menu(
    client: APaaSClient,
    app_id: str,
    form_payload: List[dict],
    form_name: str,
    form_index: int,
    form_code: str,
    all_model_codes: List[str],
) -> dict:
    """调 create_form_config 创建表单并按返回 id 创建/更新菜单。

    行为契约：
      - form_result 初始为占位（formId/formCode/menuId='', reused=False, message="创建成功: ..."）
      - client.create_form_config 返回 list 时，对每个带 id 的 fr 填 form_result
      - 菜单创建失败 logger.warning 但**不中断**，继续返回 form_result
    """
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
                try:
                    await _finalize_created_form_config(
                        client,
                        app_id,
                        str(fr.get("id") or ""),
                        form_name=form_name,
                        form_code=str(fr.get("formCode") or form_code or ""),
                        all_model_codes=all_model_codes,
                        menu_id=str(fr.get("menuId") or ""),
                    )
                except Exception as save_err:
                    logger.warning("创建后固化表单详情失败（%s）: %s", form_name, save_err)
    return form_result


_DICT_BIND_COMPONENT_TYPES = {
    "FORM_SELECT_INPUT_SINGLE",
    "FORM_SELECT_INPUT",
    "FORM_RADIO_INPUT",
    "FORM_CHECKBOX_INPUT",
}
_DICT_MULTI_COMPONENT_TYPES = {"FORM_SELECT_INPUT", "FORM_CHECKBOX_INPUT"}


def _normalize_dict_code(raw_code: Any, dict_codes: Dict[str, str]) -> str:
    code = str(raw_code or "").strip()
    if not code:
        return ""
    return str(dict_codes.get(code, code) or "").strip()


def _component_dict_code(component: dict) -> str:
    direct = _first_non_empty(
        component.get("dict"),
        component.get("dictCode"),
        component.get("dict_code"),
        component.get("dictionaryCode"),
        default="",
    )
    if direct:
        return str(direct).strip()
    select_config = component.get("dictionarySelectConfig")
    if isinstance(select_config, dict):
        return str(select_config.get("dictionaryCode") or "").strip()
    return ""


def _component_lookup_keys(component: dict) -> List[str]:
    keys: List[str] = []
    for value in (
        component.get("modelField"),
        component.get("model_field"),
        component.get("code"),
        component.get("field_code"),
        component.get("label"),
        component.get("name"),
    ):
        text = str(value or "").strip()
        if text and text not in keys:
            keys.append(text)
    return keys


def _field_dict_code(field: dict) -> str:
    return str(_first_non_empty(
        field.get("dict"),
        field.get("dictCode"),
        field.get("dict_code"),
        field.get("dictionaryCode"),
        default="",
    ) or "").strip()


def _model_info_at(model_info: Dict[str, dict], key: Any) -> dict:
    if not isinstance(model_info, dict):
        return {}
    for candidate in (key, str(key)):
        value = model_info.get(candidate)
        if isinstance(value, dict):
            return value
    return {}


def _collect_component_dict_lookup(
    form_components: List[dict],
    all_models: Optional[List[dict]],
    model_info: Optional[Dict[str, dict]],
    dict_codes: Dict[str, str],
) -> Dict[str, str]:
    """收集表单组件可用的字典映射。

    设计文档里字典通常挂在模型字段上，而 form.components 可能只保留
    modelField。这里先按模型字段建立精确映射，再允许组件自身声明覆盖。
    """
    lookup: Dict[str, str] = {}

    def _put(key: Any, dict_code: str) -> None:
        text = str(key or "").strip()
        if text and dict_code:
            lookup[text] = dict_code

    def _register_model_field(
        *,
        raw_model_code: str,
        platform_model_code: str,
        platform_fields: dict,
        field: dict,
    ) -> None:
        raw_dict = _field_dict_code(field)
        dict_code = _normalize_dict_code(raw_dict, dict_codes)
        if not dict_code:
            return
        field_name = str(field.get("name") or field.get("fieldName") or "").strip()
        raw_field_code = str(field.get("code") or field.get("field_code") or "").strip()
        platform_field_code = str(
            platform_fields.get(field_name)
            or platform_fields.get(raw_field_code)
            or raw_field_code
            or ""
        ).strip()

        for key in (
            f"{platform_model_code}.{platform_field_code}" if platform_model_code and platform_field_code else "",
            f"{platform_model_code}.{raw_field_code}" if platform_model_code and raw_field_code else "",
            f"{raw_model_code}.{raw_field_code}" if raw_model_code and raw_field_code else "",
            platform_field_code,
            raw_field_code,
            field_name,
        ):
            _put(key, dict_code)

    if all_models:
        for index, model in enumerate(all_models):
            if not isinstance(model, dict):
                continue
            raw_model_code = str(model.get("code") or model.get("modelCode") or "").strip()
            mi = _model_info_at(model_info or {}, index)
            platform_model_code = str(mi.get("code") or raw_model_code).strip()
            platform_fields = mi.get("fields") if isinstance(mi.get("fields"), dict) else {}

            for field in model.get("fields", []) or []:
                if not isinstance(field, dict):
                    continue
                if field.get("type") == "子表":
                    sub_key = f"{index}_sub_{field.get('name')}"
                    sub_mi = _model_info_at(model_info or {}, sub_key)
                    sub_platform_code = str(
                        sub_mi.get("code") or field.get("code") or field.get("modelCode") or ""
                    ).strip()
                    sub_platform_fields = (
                        sub_mi.get("fields") if isinstance(sub_mi.get("fields"), dict) else {}
                    )
                    for sub_field in field.get("sub_fields", []) or []:
                        if isinstance(sub_field, dict):
                            _register_model_field(
                                raw_model_code=str(field.get("code") or "").strip(),
                                platform_model_code=sub_platform_code,
                                platform_fields=sub_platform_fields,
                                field=sub_field,
                            )
                    continue

                _register_model_field(
                    raw_model_code=raw_model_code,
                    platform_model_code=platform_model_code,
                    platform_fields=platform_fields,
                    field=field,
                )

    def _collect_from_component(component: dict) -> None:
        dict_code = _normalize_dict_code(_component_dict_code(component), dict_codes)
        if dict_code:
            for key in _component_lookup_keys(component):
                _put(key, dict_code)
        for column in component.get("tableColumn", []) or []:
            if isinstance(column, dict):
                _collect_from_component(column)

    for component in form_components or []:
        if isinstance(component, dict):
            _collect_from_component(component)

    return lookup


def _lookup_component_dict_code(component: dict, lookup: Dict[str, str]) -> str:
    direct_code = _component_dict_code(component)
    direct = lookup.get(direct_code, direct_code)
    if direct:
        return direct
    for key in _component_lookup_keys(component):
        if key in lookup:
            return lookup[key]
    return ""


def _make_dictionary_choose_options(options: list) -> list:
    choose = []
    for index, option in enumerate(options or []):
        if not isinstance(option, dict):
            continue
        value_code = _first_non_empty(
            option.get("valueCode"),
            option.get("optionCode"),
            option.get("code"),
            option.get("id"),
            default="",
        )
        label = _first_non_empty(
            option.get("valueName"),
            option.get("optionName"),
            option.get("label"),
            option.get("name"),
            default=value_code,
        )
        choose.append({
            "id": value_code,
            "label": label,
            "labelI18nAssociated": False,
            "color": option.get("valueMulticolor") or option.get("color") or "#027AFF",
            "status": option.get("valueStatus") or option.get("status") or "ENABLE",
            "checked": bool(option.get("checked", False)),
            "displayOrder": option.get("displayOrder", index),
        })
    return choose


def _apply_dictionary_binding_to_component(
    component: dict,
    dict_code: str,
    dict_id: str,
    options: list,
) -> bool:
    component_type = str(component.get("componentType") or "").strip()
    if component_type not in _DICT_BIND_COMPONENT_TYPES or not dict_code or not dict_id:
        return False

    before = {
        "source": component.get("source"),
        "chooseOptions": component.get("chooseOptions"),
        "dictionaryChooseOptions": component.get("dictionaryChooseOptions"),
        "chooseType": component.get("chooseType"),
        "multicolor": component.get("multicolor"),
        "dictionaryMulticolorStatus": component.get("dictionaryMulticolorStatus"),
        "dictionarySelectConfig": component.get("dictionarySelectConfig"),
        "componentType": component.get("componentType"),
    }
    choose = _make_dictionary_choose_options(options)
    component["source"] = {"type": "DICTIONARY_TYPE", "id": dict_id}
    component["chooseOptions"] = choose
    component["dictionaryChooseOptions"] = choose
    component["chooseType"] = "MULTIPLE" if component_type in _DICT_MULTI_COMPONENT_TYPES else "SINGLE"
    component["multicolor"] = True
    component["dictionaryMulticolorStatus"] = "ENABLE"
    component["dictionarySelectConfig"] = {
        "dictionaryCode": dict_code,
        "dictionarySelectOptions": choose,
    }
    after = {
        "source": component.get("source"),
        "chooseOptions": component.get("chooseOptions"),
        "dictionaryChooseOptions": component.get("dictionaryChooseOptions"),
        "chooseType": component.get("chooseType"),
        "multicolor": component.get("multicolor"),
        "dictionaryMulticolorStatus": component.get("dictionaryMulticolorStatus"),
        "dictionarySelectConfig": component.get("dictionarySelectConfig"),
        "componentType": component.get("componentType"),
    }
    return before != after


async def _bind_dicts_to_form(
    client: APaaSClient,
    app_id: str,
    form_result: dict,
    form_components: List[dict],
    dict_codes: Dict[str, str],
    form_name: str,
    all_models: Optional[List[dict]] = None,
    model_info: Optional[Dict[str, dict]] = None,
) -> None:
    """给已创建表单的下拉组件回写字典绑定配置。

    行为契约（跟原直线代码完全一致）：
      - 失败 logger.warning 不阻断，原函数继续返回 form_result
      - 成功且有组件更新 → form_result["message"] 追加 "（含字典绑定）"
      - 直接在 form_result dict 原地修改 message；不返回任何值
    """
    try:
        all_platform_dicts = await client.query_dicts(app_id)
        dict_id_map = {d.get("dictionaryCode"): d.get("id") for d in all_platform_dicts}

        dict_lookup = _collect_component_dict_lookup(
            form_components=form_components,
            all_models=all_models,
            model_info=model_info,
            dict_codes=dict_codes,
        )

        # 只查实际被本表单组件用到的字典；不查的字典一个 round-trip 都不打。
        # 然后把剩下的查询并发跑（asyncio.gather）—— 平台对该接口没限流，
        # 串行循环 N 个字典×~1s/次 是经典浪费。
        used_dict_codes: set[str] = set()
        for fc in (form_components or []):
            dc = _lookup_component_dict_code(fc, dict_lookup)
            if dc and dc in dict_id_map and dict_id_map.get(dc):
                used_dict_codes.add(dc)
        ordered_codes = [dc for dc in used_dict_codes]
        dict_options_map: Dict[str, list] = {}
        if ordered_codes:
            results = await asyncio.gather(
                *(client.query_dict_options(app_id, dict_id_map[dc]) for dc in ordered_codes),
                return_exceptions=True,
            )
            # 失败的字典 code 不进 dict_options_map → 对应下拉组件渲染缺选项。
            # 逐条 warning 容易被淹没，这里额外汇总一条「N 中 M 个绑定失败」日志，
            # 把失败的 dict codes 列清楚，便于排查表单部分坏掉的根因。
            failed_codes: List[str] = []
            for dc, opts in zip(ordered_codes, results):
                if isinstance(opts, Exception):
                    logger.warning(f"query_dict_options 失败 (dict={dc}): {opts}")
                    failed_codes.append(dc)
                    continue
                dict_options_map[dc] = opts
            if failed_codes:
                logger.error(
                    "字典选项绑定汇总 (form=%s): %d 个字典中 %d 个查询失败，"
                    "对应下拉组件将缺选项；失败 dict codes: %s",
                    form_name,
                    len(ordered_codes),
                    len(failed_codes),
                    ", ".join(failed_codes),
                )

        def _bind_dict_to_comp(comp: dict) -> bool:
            """给单个组件绑定字典，返回是否有更新。"""
            dc = _lookup_component_dict_code(comp, dict_lookup)
            if not dc or dc not in dict_id_map:
                return False
            did = dict_id_map[dc]
            opts = dict_options_map.get(dc, [])
            return _apply_dictionary_binding_to_component(comp, dc, did, opts)

        fc = await client.query_form_config(app_id, form_result["formId"])
        updated = False

        component_groups = [
            fc.get("detailPage", {}).get("formComponents", []),
            fc.get("components", []),
            fc.get("formComponents", []),
        ]
        for comps in component_groups:
            for comp in comps or []:
                # 顶层组件
                if _bind_dict_to_comp(comp):
                    updated = True
                # 子表内的列组件
                if comp.get("componentType") == "FORM_WIDGET_SON_TABLE":
                    for col in comp.get("tableColumn", []) or []:
                        if _bind_dict_to_comp(col):
                            updated = True

        if updated:
            _apply_form_identity_to_form_config(
                fc,
                form_name=form_name,
                form_code=str(form_result.get("formCode") or ""),
            )
            logger.info("save_form_config reason: 字典绑定回写 (form=%s)", form_name)
            await client.save_form_config(app_id, fc)
            message = str(form_result.get("message") or f"创建成功: {form_name}")
            if "含字典绑定" not in message:
                message += "（含字典绑定）"
            form_result["message"] = message
    except Exception as e:
        logger.warning(f"字典绑定失败（不阻断）: {e}")


def _build_form_components(
    form: dict,
    model_code: str,
    mi: dict,
    dict_codes: Dict[str, str],
    model_info: Dict[str, dict],
    all_models: List[dict],
    all_forms: Optional[List[dict]],
    form_name: str,
) -> tuple[List[dict], List[str], List[str]]:
    """根据 form.components 组装平台组件列表 + 列表页查询字段。

    返回 (components, query_conditions, query_list)。

    行为契约（跟原直线代码完全一致）：
      - 遍历 form.components，每项转成 platform 组件 dict
      - 识别 FORM_DATA_SELECTOR(_SINGLE) / FORM_ASSOCIATION 类型并补配置
      - sectionType == "sub" 的归到 sub_groups（按 tableModelCode 分组）
      - 其他组件进 components；同时维护 query_conditions(<=4) / query_list(<=8) / listable 计数
      - components 空时：用 mi["fields"] 降级构造默认组件（logger.warning）
      - 降级后仍为空时：**不抛** ValueError——保留给主函数决定
    """
    components: List[dict] = []
    query_conditions: List[str] = []
    query_list: List[str] = []
    listable = 0
    form_components = form.get("components", []) or []
    sub_groups: Dict[str, dict] = {}
    form_identity = _form_identity_map(all_forms or [])
    dict_lookup = _collect_component_dict_lookup(
        form_components=form_components,
        all_models=all_models,
        model_info=model_info,
        dict_codes=dict_codes,
    )

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
        target_model_code, target_field, origin_field = _resolve_component_reference(comp, form_identity)
        # 平台要求"数据选择/关联表单"组件指向一张实际的【表单】（不是模型本身）。
        # AI 生成的 ref 经常出现这两种坏情况：
        #   1) 引用了一个根本不存在的实体（比如 "customer"）
        #   2) 引用了存在的模型但没建对应表单（比如 "supplier" 只有 supplier_performance 表单）
        # 两种情况发到平台都会被拒（bizCode 4291 "目标表单为空"）。所以真正的存在性
        # 检查必须落在 form_identity（_form_identity_map(all_forms)）上，而非 model_info。
        target_exists = bool(target_model_code) and (target_model_code in form_identity)
        if desired_component_type in ("FORM_DATA_SELECTOR_SINGLE", "FORM_DATA_SELECTOR"):
            if target_exists:
                built["componentType"] = desired_component_type
                built["dataSelectorConfig"] = {
                    "type": "LOV_CHOOSE",
                    "otherModelCode": target_model_code,
                    "otherFieldCode": target_field,
                }
            else:
                # 防御：SPEC 把字段配成了"数据选择"，但目标模型/表单不存在
                # （典型场景：AI 生成的"适用客户"字段引用 customer_V1，但 SPEC 没建客户表）。
                # 直接发 payload 平台会回 bizCode=4291"目标表单为空"，整张表单建不出来。
                # 降级为普通文本输入，让表单先建出来；用户后续可在 SPEC 补建客户表，
                # 走更新流程重新接上数据选择。
                logger.warning(
                    f"表单 {form_name} 字段 {field_code}: 数据选择目标模型 "
                    f"'{target_model_code or '(空)'}' 在本应用 SPEC 中不存在，"
                    f"降级为 FORM_TEXT_INPUT 以避免平台拒绝。"
                )
                built["componentType"] = "FORM_TEXT_INPUT"
                desired_component_type = "FORM_TEXT_INPUT"
        elif desired_component_type == "FORM_ASSOCIATION":
            if target_exists:
                built["componentType"] = "FORM_ASSOCIATION"
                built["formAssociationConfig"] = {
                    "originFieldCode": origin_field or field_code,
                    "targetModelCode": target_model_code,
                    "targetFieldCode": target_field,
                }
            else:
                # 同上：关联表单的目标若不在本应用，平台同样拒。降级为文本。
                logger.warning(
                    f"表单 {form_name} 字段 {field_code}: 关联表单目标模型 "
                    f"'{target_model_code or '(空)'}' 在本应用 SPEC 中不存在，"
                    f"降级为 FORM_TEXT_INPUT 以避免平台拒绝。"
                )
                built["componentType"] = "FORM_TEXT_INPUT"
                desired_component_type = "FORM_TEXT_INPUT"
        dict_code = _lookup_component_dict_code({**comp, **built}, dict_lookup)
        if dict_code and str(built.get("componentType") or "") in _DICT_BIND_COMPONENT_TYPES:
            built["dict"] = dict_code
            built["dictionarySelectConfig"] = {
                "dictionaryCode": dict_code,
                "dictionarySelectOptions": [],
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

    # 原直线代码里的降级分支：components 空时用 mi["fields"] 生成默认组件
    if not components:
        model_fields = mi["fields"]
        logger.warning(
            f"表单 {form_name}: 配置组件为空, 降级使用平台实际字段: {list(model_fields.keys())}"
        )
        for field_name, field_code in model_fields.items():
            fallback_field = {"name": field_name, "type": "单行输入", "required": False}
            components.append(_build_component(fallback_field, model_code, field_code, dict_codes, all_models, model_info))
            if listable < 8:
                mf = f"{model_code}.{field_code}"
                if listable < 4:
                    query_conditions.append(mf)
                query_list.append(mf)
                listable += 1

    return components, query_conditions, query_list


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

    model_code = mi["code"]
    components, query_conditions, query_list = _build_form_components(
        form=form,
        model_code=model_code,
        mi=mi,
        dict_codes=dict_codes,
        model_info=model_info,
        all_models=all_models,
        all_forms=all_forms,
        form_name=form_name,
    )

    reuse_result = await _find_existing_form_reuse(client, app_id, form_name)
    if reuse_result is not None:
        if reuse_result.get("formId"):
            try:
                await _sync_form_component_references(
                    client=client,
                    app_id=app_id,
                    form_id=str(reuse_result.get("formId") or ""),
                    form_def=form,
                    all_forms=all_forms or [],
                    form_results=form_results or [],
                )
            except Exception as e:
                logger.warning(f"复用表单引用预同步失败（不阻断）: {e}")
        added_count = await _merge_existing_form_components(
            client,
            app_id,
            str(reuse_result.get("formId") or ""),
            form_name,
            components,
            query_conditions,
            query_list,
        )
        if added_count:
            reuse_result["message"] = f"复用已有表单: {form_name}，同步 {added_count} 项配置"
        if reuse_result.get("formId") and dict_codes:
            await _bind_dicts_to_form(
                client=client,
                app_id=app_id,
                form_result=reuse_result,
                form_components=components,
                dict_codes=dict_codes,
                form_name=form_name,
                all_models=all_models,
                model_info=model_info,
            )
        if reuse_result.get("formId"):
            try:
                await _sync_form_component_references(
                    client=client,
                    app_id=app_id,
                    form_id=str(reuse_result.get("formId") or ""),
                    form_def=form,
                    all_forms=all_forms or [],
                    form_results=form_results or [],
                )
            except Exception as e:
                logger.warning(f"复用表单引用回写失败（不阻断）: {e}")
        return reuse_result

    if not components:
        raise ValueError(f"表单 {form_name} 无可用字段组件")

    # formCode: 使用模型编码或生成唯一标识
    form_code = _resolve_form_code(form, form_name)

    form_payload = _build_create_form_payload(
        form_name=form_name,
        form_code=form_code,
        all_model_codes=all_model_codes,
        components=components,
        query_conditions=query_conditions,
        query_list=query_list,
    )

    logger.info(
        "execute_create_form payload (%s):\n%s",
        form_name,
        json.dumps(form_payload, ensure_ascii=False, indent=2),
    )

    form_result = await _create_form_and_menu(
        client=client,
        app_id=app_id,
        form_payload=form_payload,
        form_name=form_name,
        form_index=form_index,
        form_code=form_code,
        all_model_codes=all_model_codes,
    )

    # --- 绑定字典 ---
    if form_result["formId"] and dict_codes:
        await _bind_dicts_to_form(
            client=client,
            app_id=app_id,
            form_result=form_result,
            form_components=components,
            dict_codes=dict_codes,
            form_name=form_name,
            all_models=all_models,
            model_info=model_info,
        )

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
            form.get("formName"), form.get("form_name"), form.get("name"),
            form.get("modelCode"), form.get("model_code"),
            form.get("mainModelCode"), form.get("main_model_code"), form.get("main_model"),
        ):
            value = str(key or "").strip()
            if value:
                mapping.setdefault(value, form)
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
        target_model_code = str(_first_non_empty(
            resolved_form.get("modelCode"),
            resolved_form.get("model_code"),
            resolved_form.get("mainModelCode"),
            resolved_form.get("main_model_code"),
            resolved_form.get("main_model"),
            default=target,
        )).strip() or target
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
        comp_def.get("formName"),
        comp_def.get("form_name"),
        comp_def.get("name"),
        ref.get("formCode") if isinstance(ref, dict) else "",
        ref.get("form_code") if isinstance(ref, dict) else "",
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
                or form_result.get("formCode") == form_def.get("form_code")
                or form_result.get("formName") == form_def.get("formName")
                or form_result.get("formName") == form_def.get("name")
                or form_result.get("formName") == form_def.get("form_name")
                or form_result.get("modelCode") == form_def.get("modelCode")
                or form_result.get("modelCode") == form_def.get("model_code")
                or form_result.get("modelCode") == form_def.get("mainModelCode")
                or form_result.get("modelCode") == form_def.get("main_model_code")
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
            # 与 formPermission API payload 对齐：ALL_USER 时 permissionObjectValue
            # 必须是空字符串，不能写成 "ALL_USER"（平台会当成具体用户 ID 去查，
            # 查不到就降级成"本人"）
            object_value = ""
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

        # dataPermissionGroups 按标准 API：permissionOperationType 只含 3 个字段
        # （query/update/delete）。平台 response 也印证只保留这 3 个。
        advanced_groups.append({
            "permissionName": f"{object_name}权限",
            "permissionDescribe": "",
            "permissionOperationType": {
                "queryPermission": can_view,
                "updatePermission": can_edit,
                "deletePermission": can_delete,
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
            # operationPermissionGroups 按标准 API：去掉 processAnalysisPermission
            # （不在标准字段里），保留 8 项
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
                },
                "permissionObjects": [{
                    "permissionObjectType": object_type,
                    "permissionObjectValue": object_value,
                    "permissionObjectDisplayName": object_name,
                    "permissionRange": {"rangeType": range_type},
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
    form_config = await _query_saveable_form_config(client, app_id, form_id)
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

    # 预热：把本表单所有 ref 组件需要的"目标表单 detail page"一次性并发拉好，
    # 避免下面 _apply_reference 里串行 await 一个个查（每次 1-3s），
    # 一张表单里 5 个不同目标 ref 串行能直接吃掉 10 多秒。
    target_form_ids_to_prefetch: set[str] = set()
    for comp_def in comp_def_map.values():
        try:
            tmc, _, _ = _resolve_component_reference(comp_def, form_map)
            if not tmc:
                continue
            target_form_result = _resolve_target_form_result(comp_def, form_map, form_results, tmc)
            tfid = str((target_form_result or {}).get("formId", "")).strip()
            if tfid:
                target_form_ids_to_prefetch.add(tfid)
        except Exception:
            continue
    if target_form_ids_to_prefetch:
        ids = list(target_form_ids_to_prefetch)
        prefetched = await asyncio.gather(
            *(client.query_detail_page_config(app_id, tid) for tid in ids),
            return_exceptions=True,
        )
        for tid, payload in zip(ids, prefetched):
            if isinstance(payload, Exception):
                logger.warning(f"预拉目标表单 detail page 失败 (formId={tid}): {payload}")
                continue
            target_form_cache[tid] = payload

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
        form_name = str(
            form_def.get("formName")
            or form_def.get("form_name")
            or form_def.get("name")
            or form_def.get("title")
            or ""
        ).strip()
        form_code = str(
            form_def.get("formCode")
            or form_def.get("form_code")
            or form_def.get("code")
            or ""
        ).strip()
        all_model_codes = form_def.get("allModelCodes") or form_def.get("all_model_codes") or []
        if isinstance(all_model_codes, str):
            all_model_codes = [all_model_codes]
        _apply_form_identity_to_form_config(
            form_config,
            form_name=form_name,
            form_code=form_code,
            all_model_codes=list(all_model_codes) if isinstance(all_model_codes, list) else [],
        )
        logger.info(
            "save_form_config reason: 回写表单引用 (form=%s, formId=%s)",
            form_name or form_id,
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


def _build_form_permission_payload(
    app_id: str,
    form_code: str,
    form_id: str,
    rules: List[dict],
    role_codes: Dict[str, dict],
) -> dict:
    """构造 create_form_permissions API 的 payload。

    按标准 API 规范（skills/apaas-create-permission.md）只发 2 个顶层组：
    - operationPermissionGroups — 功能权限（新增/导入/暂存/批量/复制/分享等）
    - dataPermissionGroups      — 数据权限（查看/编辑/删除/导出/评论/日志/打印等）

    之前额外发的 permissionGroups + advancedPermissionGroups 非标准，
    平台不识别（response 里这两个 key 不存在），已移除。
    """
    _permission_groups, advanced_groups, operation_groups_list = (
        _build_permission_groups_for_form_config(rules, role_codes)
    )
    # 去掉非标准字段，贴合标准 payload
    cleaned_ops = []
    for g in operation_groups_list:
        cleaned = {k: v for k, v in g.items() if k != "uuid"}
        cleaned_ops.append(cleaned)
    cleaned_data = []
    for g in advanced_groups:
        cleaned = {k: v for k, v in g.items() if k != "filterConditionGroups"}
        cleaned_data.append(cleaned)
    return {
        "formCode": form_code,
        "appId": app_id,
        "tenantId": "",
        "formId": form_id,
        "operationPermissionGroups": cleaned_ops,
        "dataPermissionGroups": cleaned_data,
    }


def _clone_for_form_config_permissions(value):
    if isinstance(value, list):
        return [_clone_for_form_config_permissions(item) for item in value]
    if isinstance(value, dict):
        cloned = {k: _clone_for_form_config_permissions(v) for k, v in value.items()}
        for type_key, value_key in (
            ("permissionObjectType", "permissionObjectValue"),
            ("permissionType", "permissionValue"),
        ):
            if cloned.get(type_key) == "ROLE":
                cloned[type_key] = "ROLE_USER"
            if cloned.get(type_key) == "ALL_USER":
                cloned[value_key] = ""
        return cloned
    return value


async def _sync_form_permissions_to_form_config(
    client: APaaSClient,
    app_id: str,
    *,
    form_id: str,
    form_name: str,
    form_code: str,
    rules: List[dict],
    role_codes: Dict[str, dict],
) -> None:
    if not form_id:
        return
    permission_groups, advanced_groups, operation_groups = _build_permission_groups_for_form_config(rules, role_codes)
    permission_groups = _clone_for_form_config_permissions(permission_groups)
    advanced_groups = _clone_for_form_config_permissions(advanced_groups)
    operation_groups = _clone_for_form_config_permissions(operation_groups)

    def _apply_latest(config: dict) -> None:
        _apply_form_identity_to_form_config(
            config,
            form_name=form_name,
            form_code=form_code,
            app_id=app_id,
            form_id=form_id,
        )
        config["permissionGroups"] = permission_groups
        config["advancedPermissionGroups"] = advanced_groups
        config["operationPermissionGroups"] = operation_groups
        detail_page = config.setdefault("detailPage", {})
        if isinstance(detail_page, dict):
            detail_page["permissionGroups"] = permission_groups
            detail_page["advancedPermissionGroups"] = advanced_groups
            detail_page["operationPermissionGroups"] = operation_groups

    form_config = await client.query_detail_page_config(app_id, form_id)
    _apply_latest(form_config)
    logger.info("save_form_config reason: 权限页面配置回写 (form=%s, formId=%s)", form_name or form_code, form_id)
    await _save_form_config_with_retry(
        client,
        app_id,
        form_config,
        form_id=form_id,
        apply_latest=_apply_latest,
        reason="权限页面配置回写",
    )


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

        user_perm = next((p for p in permissions if p.get("formCode") == form_code or p.get("form_code") == form_code), None)
        if not user_perm:
            user_perm = next((p for p in permissions if p.get("form") == form_name or p.get("formName") == form_name), None)
        if not user_perm:
            user_perm = next((p for p in permissions if p.get("modelCode") == model_code or p.get("model_code") == model_code), None)

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
                "form_name": form_name,
                "form_code": form_code,
                "rules": rules,
            })
    if perm_payloads:
        # 创建权限的专属 API：POST /common/resource/formPermission
        # 平台靠这个接口做运行时权限判定；UI 页面也从这里读权限数据。
        await client.create_form_permissions(app_id, perm_payloads)
        for job in permission_sync_jobs:
            try:
                await _sync_form_permissions_to_form_config(
                    client,
                    app_id,
                    form_id=str(job.get("form_id") or ""),
                    form_name=str(job.get("form_name") or ""),
                    form_code=str(job.get("form_code") or ""),
                    rules=job.get("rules") or [],
                    role_codes=role_codes,
                )
            except Exception as exc:
                logger.warning("权限页面配置回写失败（%s）: %s", job.get("form_name") or job.get("form_id"), exc)
    return {"permissions_count": len(perm_payloads)}
