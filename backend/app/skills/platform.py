"""aPaaS 平台基础原子操作

每个函数是一个独立的 Skill，可以单独调用。
所有函数接收 APaaSClient 实例和必要参数，返回操作结果。
"""
from __future__ import annotations
import random
import re
import string
import logging
from typing import Dict, List, Optional, Tuple

from app.apaas_client import APaaSClient

logger = logging.getLogger(__name__)


# ── 工具函数 ──

def _rand(n: int = 4) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


_RESERVED_WORDS = {
    'name', 'status', 'type', 'order', 'group', 'key', 'value', 'index',
    'table', 'column', 'select', 'insert', 'update', 'delete', 'create',
    'drop', 'alter', 'from', 'where', 'join', 'on', 'in', 'is', 'not',
    'null', 'and', 'or', 'like', 'between', 'having', 'limit', 'offset',
    'desc', 'asc', 'set', 'into', 'values', 'as', 'by', 'all', 'any',
    'exists', 'case', 'when', 'then', 'else', 'end', 'if', 'for', 'each',
    'action', 'result', 'level', 'role', 'user', 'date', 'time', 'timestamp',
    'comment', 'location', 'email', 'phone', 'address', 'account', 'model',
    'unit', 'category', 'manager', 'priority', 'amount', 'currency',
    'operator', 'spec', 'id',
}


def _safe_code(code: str) -> str:
    """清理编码：只保留字母数字下划线，保留字加前缀。"""
    c = re.sub(r'[^a-zA-Z0-9_]', '_', code)
    if c.lower() in _RESERVED_WORDS:
        c = f"f_{c}"
    return c


# 字段类型映射：预览类型 → 数据模型字段类型
FIELD_TYPE_MAP = {
    '单据号': 'STRING', '单行输入': 'STRING', '多行输入': 'BIG_TEXT',
    '手机号码': 'STRING', '电子邮箱': 'STRING', '下拉单选': 'STRING',
    '下拉多选': 'STRING', '数据单选': 'STRING', '日期时间': 'DATE',
    '金额': 'NUM', '数字': 'NUM', '附件上传': 'STRING',
    '开关': 'STRING', '布尔': 'STRING', '人员选择': 'STRING',
    '地理位置': 'STRING',
}


# ── Skill 1: 登录 ──

async def login(
    client: APaaSClient,
    account: str,
    password: str,
) -> dict:
    """登录得帆云平台，获取 token。

    Args:
        client: APaaSClient 实例
        account: 登录账号（手机号或邮箱）
        password: 登录密码（明文，函数内部 RSA 加密）

    Returns:
        {"token": "...", "user": {...}}
    """
    result = await client.login(account, password)
    logger.info(f"登录成功，user_id={client.user_id}")
    return result


# ── Skill 2: 创建应用 ──

async def create_app(
    client: APaaSClient,
    app_name: str,
    app_code: Optional[str] = None,
    description: str = "",
) -> str:
    """创建 aPaaS 应用。

    Args:
        client: 已登录的 APaaSClient
        app_name: 应用名称
        app_code: 应用编码（可选，自动生成）。只能包含字母、数字、连字符。
        description: 应用描述

    Returns:
        app_id (str)
    """
    if not app_code:
        # 自动生成：拼音首字母 + 随机后缀，只用连字符
        app_code = f"app-{_rand(6)}"

    # appCode 不能有下划线，替换为连字符
    app_code = app_code.replace('_', '-')

    result = await client.create_app(app_name, app_code, description)
    app_id = str(result) if isinstance(result, str) else str(result.get("id", result.get("appId", "")))
    logger.info(f"应用创建成功: {app_name} (id={app_id})")
    return app_id


# ── Skill 3: 创建数据模型 ──

def _build_model_payload(
    app_id: str,
    models: List[Dict],
    suffix: Optional[str] = None,
) -> Tuple[Dict, Dict]:
    """将预览格式的模型定义转换为 API payload。

    Args:
        app_id: 应用 ID
        models: 预览格式模型列表
        suffix: 随机后缀（可选，自动生成）

    Returns:
        (payload, code_map)
        - payload: API 请求体
        - code_map: 原始编码 → 带后缀编码的映射
    """
    if not suffix:
        suffix = _rand(4)

    data_models = []
    code_map = {}

    for m in models:
        base_code = _safe_code(m.get("code") or "model")
        model_code = f"{base_code}_{suffix}"
        code_map[base_code] = model_code

        # 先处理子表 → 生成子表模型
        for f in m.get("fields", []):
            if f.get("type") == "子表" and f.get("sub_fields"):
                sub_code = f.get("sub_code") or f"{base_code}_sub"
                sub_model_code = f"{sub_code}_{suffix}"
                code_map[sub_code] = sub_model_code

                sub_fields = []
                for si, sf in enumerate(f["sub_fields"]):
                    sft = FIELD_TYPE_MAP.get(sf.get("type", ""), "STRING")
                    if sft is None:
                        continue
                    sf_code = _safe_code(sf.get("code") or f"sf{si}_{_rand()}")
                    sub_fields.append({
                        "fieldName": sf["name"],
                        "fieldCode": sf_code,
                        "fieldType": sft,
                        "fieldDescription": sf.get("type", ""),
                    })
                data_models.append({
                    "appId": app_id,
                    "modelName": f["name"],
                    "modelCode": sub_model_code,
                    "modelDescription": f["name"],
                    "fields": sub_fields,
                })

        # 主模型字段（排除子表）
        fields = []
        for fi, f in enumerate(m.get("fields", [])):
            ft = FIELD_TYPE_MAP.get(f.get("type", ""), "STRING")
            if ft is None:
                continue
            field_code = _safe_code(f.get("code") or f"f{fi}_{_rand()}")
            fields.append({
                "fieldName": f["name"],
                "fieldCode": field_code,
                "fieldType": ft,
                "fieldDescription": f.get("type", ""),
            })

        data_models.append({
            "appId": app_id,
            "modelName": m["name"],
            "modelCode": model_code,
            "modelDescription": m.get("description", m["name"]),
            "fields": fields,
        })

    payload = {"appId": app_id, "datasourceId": "", "dataModels": data_models}
    return payload, code_map


async def create_models(
    client: APaaSClient,
    app_id: str,
    models: List[Dict],
    suffix: Optional[str] = None,
) -> Tuple[list, Dict, Dict]:
    """创建数据模型（支持子表）。

    Args:
        client: 已登录的 APaaSClient
        app_id: 应用 ID
        models: 预览格式模型列表，每个模型包含 name, code, fields
        suffix: 随机后缀（可选）

    Returns:
        (model_results, model_payload, code_map)
    """
    payload, code_map = _build_model_payload(app_id, models, suffix)
    result = await client.create_models(app_id, payload)
    logger.info(f"创建了 {len(payload['dataModels'])} 个数据模型")
    return result, payload, code_map


# ── Skill 4: 创建数据字典 ──

def _build_dict_payload(
    app_id: str,
    dicts: List[Dict],
    suffix: Optional[str] = None,
) -> Tuple[List[Dict], Dict[str, str]]:
    """将预览格式的字典定义转换为 API payload。"""
    if not suffix:
        suffix = _rand(4)

    result = []
    dict_code_map: Dict[str, str] = {}

    for d in dicts:
        base_code = _safe_code(d.get("code", "dict"))
        dict_code = f"{base_code}_{suffix}"
        dict_code_map[d.get("code", base_code)] = dict_code

        options = d.get("options", [])
        dict_options = []
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                opt_name = opt
                opt_code = f"{base_code}_{i+1}_{suffix}"
            elif isinstance(opt, dict):
                raw_opt_code = _safe_code(opt.get("code", opt.get("id", f"{base_code}_{i+1}")))
                opt_name = opt.get("name", opt.get("label", str(opt)))
                opt_code = f"{raw_opt_code}_{suffix}"
            else:
                opt_name = str(opt)
                opt_code = f"{base_code}_{i+1}_{suffix}"

            dict_options.append({
                "optionName": opt_name,
                "optionCode": opt_code,
                "displayOrder": i + 1,
                "remarks": "",
            })

        result.append({
            "appId": app_id,
            "dictionaryCode": dict_code,
            "dictionaryName": d["name"],
            "dictionaryOptions": dict_options,
        })

    return result, dict_code_map


async def create_dicts(
    client: APaaSClient,
    app_id: str,
    dicts: List[Dict],
    suffix: Optional[str] = None,
) -> Dict[str, str]:
    """创建数据字典。

    Args:
        client: 已登录的 APaaSClient
        app_id: 应用 ID
        dicts: 预览格式字典列表，每个字典包含 name, code, options

    Returns:
        dict_code_map: 原始编码 → 带后缀编码的映射
    """
    payload, dict_code_map = _build_dict_payload(app_id, dicts, suffix)
    await client.create_dicts(app_id, payload)
    logger.info(f"创建了 {len(payload)} 个数据字典")
    return dict_code_map


# ── Skill 5: 创建角色 ──

def _build_role_payload(app_id: str, roles: List[Dict]) -> List[Dict]:
    """将预览格式的角色定义转换为 API payload。"""
    return [
        {
            "appId": app_id,
            "roleCode": f"R_{r.get('code', r['name'])}_{_rand()}",
            "roleName": r["name"],
        }
        for r in roles
    ]


async def create_roles(
    client: APaaSClient,
    app_id: str,
    roles: List[Dict],
) -> None:
    """创建角色（重复时跳过，不阻断流程）。

    Args:
        client: 已登录的 APaaSClient
        app_id: 应用 ID
        roles: 预览格式角色列表，每个角色包含 name, code
    """
    payload = _build_role_payload(app_id, roles)
    try:
        await client.create_roles(app_id, payload)
        logger.info(f"创建了 {len(payload)} 个角色")
    except Exception as e:
        logger.warning(f"角色创建跳过（可能已存在）: {e}")


# ── Skill 6: 创建表单配置 ──

async def create_form(
    client: APaaSClient,
    app_id: str,
    models: List[Dict],
    dicts: List[Dict],
    model_results: Optional[list] = None,
    model_payload: Optional[Dict] = None,
    code_map: Optional[Dict] = None,
    dict_code_map: Optional[Dict] = None,
) -> list:
    """创建表单配置。

    Args:
        client: 已登录的 APaaSClient
        app_id: 应用 ID
        models: 预览格式模型列表
        dicts: 预览格式字典列表
        model_results: create_models 返回的结果
        model_payload: create_models 使用的 payload
        code_map: 模型编码映射
        dict_code_map: 字典编码映射

    Returns:
        表单创建结果列表
    """
    from app.skills.components import build_form_config

    form_payload = build_form_config(
        models, dicts, model_results, model_payload, code_map, dict_code_map
    )
    result = await client.create_form_config(app_id, form_payload)
    logger.info(f"创建了 {len(form_payload)} 个表单")
    return result
