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
from app.config import settings
from app.field_types import get_field_type_map

logger = logging.getLogger(__name__)


# ── 工具函数 ──

def _rand(n: int = 4) -> str:
    """生成随机字符串（仅在启用后缀时有效）"""
    if settings.enable_code_suffix:
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))
    return ""


def _generate_suffix() -> str:
    """根据配置决定是否生成随机后缀"""
    if settings.enable_code_suffix:
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return ""


def _apply_suffix(code: str, suffix: str) -> str:
    """为编码添加后缀（如果有）"""
    if suffix:
        return f"{code}_{suffix}"
    return code


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
# 统一从 field_types.py 获取，避免重复维护
FIELD_TYPE_MAP: Dict[str, str] = get_field_type_map()


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
        suffix: 随机后缀（可选，根据配置自动生成）

    Returns:
        (payload, code_map)
        - payload: API 请求体
        - code_map: 原始编码 → 最终编码的映射
    """
    if suffix is None:
        suffix = _generate_suffix()

    data_models = []
    code_map = {}

    for m in models:
        base_code = _safe_code(m.get("code") or "model")
        model_code = _apply_suffix(base_code, suffix)
        code_map[base_code] = model_code

        # 先处理子表 → 生成子表模型
        for f in m.get("fields", []):
            if f.get("type") == "子表" and f.get("sub_fields"):
                sub_code = f.get("sub_code") or f"{base_code}_sub"
                sub_model_code = _apply_suffix(sub_code, suffix)
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
    if suffix is None:
        suffix = _generate_suffix()

    result = []
    dict_code_map: Dict[str, str] = {}

    for d in dicts:
        base_code = _safe_code(d.get("code", "dict"))
        dict_code = _apply_suffix(base_code, suffix)
        dict_code_map[d.get("code", base_code)] = dict_code

        options = d.get("options", [])
        dict_options = []
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                opt_name = opt
                opt_base = f"{base_code}_{i+1}"
                opt_code = _apply_suffix(opt_base, suffix)
            elif isinstance(opt, dict):
                raw_opt_code = _safe_code(opt.get("code", opt.get("id", f"{base_code}_{i+1}")))
                opt_name = opt.get("name", opt.get("label", str(opt)))
                opt_code = _apply_suffix(raw_opt_code, suffix)
            else:
                opt_name = str(opt)
                opt_base = f"{base_code}_{i+1}"
                opt_code = _apply_suffix(opt_base, suffix)

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
    suffix = _generate_suffix()
    result = []
    for r in roles:
        base_code = f"R_{r.get('code', r['name'])}"
        role_code = _apply_suffix(base_code, suffix)
        result.append({
            "appId": app_id,
            "roleCode": role_code,
            "roleName": r["name"],
        })
    return result


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


# ── Skill 7: 配置权限 ──

async def create_permissions(
    client: APaaSClient,
    app_id: str,
    permissions: List[Dict],
    form_results: List[Dict],
    role_codes: Optional[Dict[str, dict]] = None,
) -> Dict:
    """为所有表单配置权限。

    基于角色和表单自动配置功能权限和数据权限。
    如果用户配置了 permissions 规则，按规则生成；否则使用默认全员权限。

    Args:
        client: 已登录的 APaaSClient
        app_id: 应用 ID
        permissions: 权限配置列表，每项 {"form": "表单名", "rules": [...]}
        form_results: 表单创建结果列表，每项含 formCode/formId/formName
        role_codes: 角色编码映射

    Returns:
        {"permissions_count": N}
    """
    from app.step_executor import (
        _build_form_permission_payload,
        _default_form_permission_payload,
    )

    role_codes = role_codes or {}
    perm_payloads = []

    for fr in form_results:
        form_code = fr.get("formCode", "")
        form_id = fr.get("formId", "")
        form_name = fr.get("formName", "")

        user_perm = next((p for p in permissions if p.get("form") == form_name), None)

        if user_perm and user_perm.get("rules"):
            perm_payloads.append(
                _build_form_permission_payload(
                    app_id=app_id,
                    form_code=form_code,
                    form_id=form_id,
                    rules=user_perm["rules"],
                    role_codes=role_codes,
                )
            )
        else:
            perm_payloads.append(_default_form_permission_payload(app_id, form_code, form_id))

    if perm_payloads:
        await client.create_form_permissions(app_id, perm_payloads)
        logger.info(f"配置了 {len(perm_payloads)} 个表单的权限")

    return {"permissions_count": len(perm_payloads)}


# ── Skill 8: 发布应用 ──

async def deploy_app(
    client: APaaSClient,
    app_id: str,
) -> Dict:
    """查询当前版本号并递增发布应用。

    流程：
    1. 查询当前应用详情获取版本号
    2. 递增 patch 版本号（如 1.0.0 → 1.0.1）
    3. 调用发布 API

    Args:
        client: 已登录的 APaaSClient
        app_id: 应用 ID

    Returns:
        {"version": "x.y.z", "app_id": "..."}
    """
    # 查询当前版本
    app_detail = await client.query_app_detail(app_id)
    current_version = app_detail.get("appVersion", app_detail.get("version", ""))

    # 递增版本号
    if current_version:
        parts = current_version.split(".")
        try:
            parts = [int(p) for p in parts]
            parts[-1] += 1
            new_version = ".".join(str(p) for p in parts)
        except (ValueError, IndexError):
            new_version = "1.0.1"
    else:
        new_version = "1.0.0"

    await client.deploy_app(app_id, new_version, abstract="智能搭建自动发布")
    logger.info(f"应用发布成功: app_id={app_id}, version={new_version}")
    return {"version": new_version, "app_id": app_id}
