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

    策略：统一加 f_ 前缀，彻底避免与任何保留字冲突。
    平台可能有比我们列表更多的保留字，最安全的做法是全部加前缀。
    """
    c = _sanitize_code(code)
    if c.startswith("f_"):
        return c
    return f"f_{c}"


# ---------------------------------------------------------------------------
# 类型映射
# ---------------------------------------------------------------------------

# 预览字段类型 → 数据模型字段类型
FIELD_TYPE_MAP = {
    "单据号": "STRING", "单行输入": "STRING", "多行输入": "BIG_TEXT",
    "手机号码": "STRING", "电子邮箱": "STRING", "下拉单选": "STRING",
    "下拉多选": "STRING", "数据单选": "STRING", "日期时间": "DATE",
    "金额": "NUM", "数字": "NUM", "附件上传": "STRING",
    "开关": "STRING", "布尔": "STRING", "人员选择": "STRING", "地理位置": "STRING",
}

# 预览字段类型 → 表单组件类型
COMP_TYPE_MAP = {
    "单据号": "FORM_DOCUMENT_NUMBER", "单行输入": "FORM_TEXT_INPUT",
    "多行输入": "FORM_TEXTAREA_INPUT", "手机号码": "FORM_PHONE_INPUT",
    "电子邮箱": "FORM_EMAIL_INPUT", "下拉单选": "FORM_SELECT_INPUT_SINGLE",
    "下拉多选": "FORM_SELECT_INPUT", "数据单选": "FORM_DATA_SELECTOR_SINGLE",
    "日期时间": "FORM_DATEPICK_INPUT", "金额": "FORM_MONEY_INPUT",
    "数字": "FORM_NUMBER_INPUT", "附件上传": "FORM_FILE_UPLOAD",
    "开关": "FORM_SWITCH_SELECT", "布尔": "FORM_SWITCH_SELECT",
    "人员选择": "FORM_PEOPLE_SELECT", "地理位置": "FORM_WIDGET_LOCATION",
    "子表": "FORM_WIDGET_SON_TABLE",
}


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

    # 字典绑定
    if ftype in ("下拉单选", "下拉多选") and field.get("dict"):
        dcode = dict_codes.get(field["dict"])
        if dcode:
            comp["dictionarySelectConfig"] = {
                "dictionaryCode": dcode,
                "dictionarySelectOptions": [],
            }

    # 数据选择器
    if ftype == "数据单选" and field.get("ref"):
        ref = field["ref"]
        ref_model = ref.get("model", "") if isinstance(ref, dict) else str(ref)
        ref_field = ref.get("field", "") if isinstance(ref, dict) else ""
        for ridx, rm in enumerate(models):
            if rm["name"] == ref_model:
                ref_mi = model_info.get(ridx)
                if ref_mi:
                    comp["dataSelectorConfig"] = {
                        "type": "LOV_CHOOSE",
                        "otherModelCode": ref_mi["code"],
                        "otherFieldCode": ref_field,
                    }
                break

    return comp


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

    # 支持选择性生成
    selected_indices = config.get("selected_model_indices")
    if selected_indices is not None and len(selected_indices) < len(all_models):
        models = [all_models[i] for i in selected_indices if i < len(all_models)]
    else:
        models = all_models

    # 过滤字典：只保留被选中模型引用的
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

    # --- 角色 ---
    if roles:
        try:
            roles_payload = [
                {
                    "appId": app_id,
                    "roleCode": f"R_{_sanitize_code(r.get('code', r['name']))}_{suffix}",
                    "roleName": r["name"],
                }
                for r in roles
            ]
            await client.create_roles(app_id, roles_payload)
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
            new_dicts = []
            for d in dicts:
                ed = existing.get(d["name"])
                if ed:
                    pc = ed["dictionaryCode"]
                    dict_codes[d["name"]] = pc
                    dict_codes[d.get("code", d["name"])] = pc
                    yield {"stage": 1, "status": "running", "step": f"复用字典: {d['name']}"}
                else:
                    dc = f"{_sanitize_code(d.get('code', 'dict'))}_{suffix}"
                    dict_codes[d["name"]] = dc
                    dict_codes[d.get("code", d["name"])] = dc
                    new_dicts.append(d)

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

                # 添加选项
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
        new_models_to_create: List[tuple] = []

        for idx, m in enumerate(models):
            em = existing_by_name.get(m["name"])
            if em:
                model_info[idx] = {"name": m["name"], "code": em["modelCode"], "fields": _extract_fields(em)}
                yield {"stage": 2, "status": "running", "step": f"复用: {m['name']}"}
                # 复用子表
                for f in m.get("fields", []):
                    if f.get("type") == "子表" and f.get("sub_fields"):
                        sub_em = existing_by_name.get(f["name"])
                        if sub_em:
                            model_info[f"{idx}_sub_{f['name']}"] = {
                                "name": f["name"], "code": sub_em["modelCode"], "fields": _extract_fields(sub_em),
                            }
            else:
                new_models_to_create.append((idx, m))

        if new_models_to_create:
            data_models = []
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

            payload = {"appId": app_id, "datasourceId": "", "dataModels": data_models}

            try:
                await client.create_models(app_id, payload)
                yield {"stage": 2, "status": "running", "step": f"新建: {'、'.join(m['name'] for _, m in new_models_to_create)}"}

                # 用平台实际的 fieldCode 覆盖（平台可能追加后缀）
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

            except Exception as e:
                if "编码重复" in str(e) or "已存在" in str(e):
                    yield {"stage": 2, "status": "running", "step": "编码冲突，回退到复用模式..."}
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
                else:
                    raise

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
        # 查询已有表单菜单
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

        for idx, m in enumerate(models):
            mi = model_info.get(idx)
            if not mi:
                yield {"stage": 3, "status": "running", "step": f"跳过 {m['name']}（无模型）"}
                continue

            if m["name"] in existing_forms:
                form_results.append({"formId": existing_forms[m["name"]], "formName": m["name"]})
                yield {"stage": 3, "status": "running", "step": f"复用: {m['name']}"}
                continue

            model_code = mi["code"]
            model_fields = mi["fields"]

            all_model_codes = [model_code]
            components = []
            query_conditions = []
            query_list = []
            listable = 0

            for f in m.get("fields", []):
                ftype = f.get("type", "单行输入")

                # 子表
                if ftype == "子表" and f.get("sub_fields"):
                    sub_mi = model_info.get(f"{idx}_sub_{f['name']}")
                    if not sub_mi:
                        continue
                    all_model_codes.append(sub_mi["code"])
                    sub_cols = []
                    for sf in f["sub_fields"]:
                        sfc = sub_mi["fields"].get(sf["name"])
                        if not sfc:
                            continue
                        sub_cols.append(_build_component(sf, sub_mi["code"], sfc, dict_codes, models, model_info))
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

                components.append(_build_component(f, model_code, fc, dict_codes, models, model_info))

                if listable < 8 and ftype not in ("附件上传", "多行输入", "子表"):
                    mf = f"{model_code}.{fc}"
                    if listable < 4:
                        query_conditions.append(mf)
                    query_list.append(mf)
                    listable += 1

            if not components:
                yield {"stage": 3, "status": "running", "step": f"跳过 {m['name']}（无可用字段）"}
                continue

            form_payload = [{
                "formName": m["name"],
                "formCode": f"form_{_rand(6)}",
                "allModelCodes": all_model_codes,
                "formComponents": components,
                "listPageView": {
                    "queryConditions": query_conditions,
                    "queryList": query_list,
                },
            }]

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
                yield {"stage": 3, "status": "running", "step": f"创建: {m['name']}"}
            except Exception as e:
                yield {"stage": 3, "status": "running", "step": f"失败 {m['name']}: {e}"}

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
            for fr in form_results:
                form_code = fr.get("formCode", "")
                form_id = fr.get("formId", "")
                menu_id = fr.get("menuId", "")

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
                            perm_obj_type = "ROLE"
                            perm_obj_value = role_code
                            perm_obj_name = role_code

                        op = rule.get("op", "all")
                        perm_op = {
                            "addPermission": op in ("all", "add", "edit"),
                            "batchAgreePermission": False,
                            "batchDeletePermission": op in ("all", "delete"),
                            "batchRejectPermission": False,
                            "copyAddPermission": False,
                            "importPermission": op in ("all", "import"),
                            "shareFormPermission": False,
                            "temporaryStoragePermission": False,
                        }

                        data_range = rule.get("data", "ALL")
                        range_map = {
                            "all": "ALL", "self": "SELF", "dept": "CURRENT_USER_DEPT",
                            "dept_sub": "CURRENT_USER_DEPT_LOW_LEVEL",
                        }
                        range_type = range_map.get(data_range, data_range.upper() if isinstance(data_range, str) else "ALL")

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
                                "deletePermission": op in ("all", "delete"),
                                "updatePermission": op in ("all", "edit"),
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
                else:
                    # 默认权限：全员可新增，全员可查看全部数据
                    perm_payloads.append({
                        "formCode": form_code,
                        "appId": app_id,
                        "tenantId": "",
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
                            },
                        }],
                    })

            if perm_payloads:
                await client.create_form_permissions(app_id, perm_payloads)
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
