"""平台反向同步模块

将平台 API 返回的数据转换回本地 preview config 格式，
并与本地配置做 diff 检测漂移。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

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


def _guess_field_type(comp_type: str = "", data_type: str = "") -> str:
    """从平台组件类型或数据类型推断 preview 字段类型"""
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
    """平台字典 → preview 字典"""
    dicts = []
    for d in remote_dicts:
        dict_id = str(d.get("id", d.get("dictionaryId", "")))
        dict_code = d.get("dictionaryCode", d.get("code", ""))
        options = []
        # 从 dict_options 中取选项
        raw_options = dict_options.get(dict_id, [])
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
