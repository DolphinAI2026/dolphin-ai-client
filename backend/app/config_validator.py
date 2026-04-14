"""配置校验层

在 AI 输出进入系统前拦截无效数据。
校验策略：尽可能自动修复，不可修复时报 warning，只有结构性错误才 raise。
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.field_types import get_valid_type_names

logger = logging.getLogger(__name__)

# ── 已知字段类型（从注册表派生）──
VALID_FIELD_TYPES = get_valid_type_names()

# ── 平台系统字段（自动维护，业务字段不得使用）──
# 来源：platform_sync._SKIP_FIELDS + 平台常见内置字段变体
RESERVED_FIELD_CODES: set = {
    "id",
    "created_by", "creation_date", "create_by", "create_date", "create_time",
    "created_at", "created_time",
    "last_updated_by", "last_update_by", "updated_by", "update_by",
    "last_update_date", "last_updated_at", "updated_at", "update_time",
    "object_version_number", "version", "version_number",
    "tenant_id", "tenant",
    "status",
    "owner", "owner_id",
    "parent_id", "parent",
    "deleted", "is_deleted", "del_flag",
}

# 近似映射：AI 可能输出的非标准名称 → 标准名称
_TYPE_ALIAS = {
    "文本": "单行输入", "文本输入": "单行输入", "文本框": "单行输入",
    "长文本": "多行输入", "多行文本": "多行输入", "备注": "多行输入",
    "手机": "手机号码", "电话": "手机号码", "手机号": "手机号码",
    "邮箱": "电子邮箱", "电邮": "电子邮箱",
    "单选": "下拉单选", "下拉": "下拉单选", "选择": "下拉单选",
    "多选": "下拉多选",
    "数据选择": "数据单选", "关联": "数据单选", "数据选择器": "数据单选",
    "日期": "日期时间", "时间": "日期时间",
    "金额输入": "金额", "价格": "金额", "费用": "金额",
    "数字输入": "数字", "数量": "数字", "数值": "数字",
    "附件": "附件上传", "文件": "附件上传", "上传": "附件上传",
    "开关选择": "开关", "是否": "开关", "布尔": "开关",
    "人员": "人员选择", "用户选择": "人员选择",
    "部门": "部门选择", "部门选择": "部门选择",
    "地址": "地理位置", "位置": "地理位置", "定位": "地理位置",
    "明细": "子表", "子表格": "子表", "明细行": "子表",
}

# 需要 dict 字段的类型
_DICT_REQUIRED_TYPES = {"下拉单选", "下拉多选"}
# 需要 ref 字段的类型
_REF_REQUIRED_TYPES = {"数据单选", "数据多选"}

# ── Patch 操作白名单 ──
VALID_PATCH_OPS = {
    "add_dict", "update_dict", "remove_dict",
    "add_field", "update_field", "remove_field",
    "add_model", "remove_model",
    "add_role", "remove_role",
    "add_workflow", "update_workflow", "remove_workflow",
}


# ==================================================================
# 工具函数
# ==================================================================

def _generate_code(name: str) -> str:
    """从中文名生成 code（fallback：md5 hash）"""
    if not name:
        return "c_" + hashlib.md5(b"unknown").hexdigest()[:7]
    # 尝试提取英文部分
    ascii_part = re.sub(r'[^a-zA-Z0-9_]', '', name).lower()
    if len(ascii_part) >= 2:
        return ascii_part
    return "c_" + hashlib.md5(name.encode()).hexdigest()[:7]


def _fix_code(code: Optional[str], name: str = "") -> Tuple[str, Optional[str]]:
    """修复 code 字段，返回 (fixed_code, warning_or_none)"""
    if code and re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', code):
        return code.lower(), None
    if code:
        # 尝试清理
        cleaned = re.sub(r'[^a-zA-Z0-9_]', '', code).lower()
        if len(cleaned) >= 2:
            return cleaned, f"code '{code}' 已自动修复为 '{cleaned}'"
    # 从 name 生成
    generated = _generate_code(name)
    return generated, f"缺失 code，已从 name '{name}' 自动生成 '{generated}'"


def _normalize_field_type(ftype: str) -> Tuple[str, Optional[str]]:
    """规范化字段类型名，返回 (normalized_type, warning_or_none)"""
    if ftype in VALID_FIELD_TYPES:
        return ftype, None
    # 尝试别名映射
    alias = _TYPE_ALIAS.get(ftype)
    if alias:
        return alias, f"字段类型 '{ftype}' 已自动映射为 '{alias}'"
    # 未知类型，降级为单行输入
    return "单行输入", f"未知字段类型 '{ftype}'，已降级为 '单行输入'"


# ==================================================================
# 全量配置校验
# ==================================================================

def validate_full_config(data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """校验并修复完整的 preview 配置。

    返回 (cleaned_data, warnings)。
    只有结构完全不可用时才 raise ValueError。
    """
    warnings: List[str] = []

    if not isinstance(data, dict):
        raise ValueError(f"配置必须是字典类型，实际收到: {type(data).__name__}")

    # 解包可能的 {"data": {...}} 包装
    if "data" in data and isinstance(data["data"], dict) and "models" in data["data"]:
        data = data["data"]

    # ── appName ──
    if not data.get("appName"):
        data.setdefault("appName", "未命名应用")
        warnings.append("缺失 appName，已设为 '未命名应用'")

    # ── roles ──
    roles = data.get("roles")
    if roles is None:
        data["roles"] = []
    elif isinstance(roles, list):
        data["roles"] = _validate_roles(roles, warnings)

    # ── dicts ──
    dicts = data.get("dicts")
    if dicts is None:
        data["dicts"] = []
    elif isinstance(dicts, list):
        data["dicts"] = _validate_dicts(dicts, warnings)

    # ── models ──
    models = data.get("models")
    if not models or not isinstance(models, list):
        # models 是核心，不能缺
        if not models:
            warnings.append("配置中没有 models，应用可能不完整")
            data["models"] = []
        else:
            raise ValueError(f"models 必须是数组，实际收到: {type(models).__name__}")
    else:
        dict_codes = {d.get("code") for d in data.get("dicts", []) if d.get("code")}
        model_codes = {m.get("code") for m in models if m.get("code")}
        data["models"] = _validate_models(models, dict_codes, model_codes, warnings)

    # ── workflows ──
    wfs = data.get("workflows")
    if wfs is None:
        data["workflows"] = []

    # ── permissions ──
    perms = data.get("permissions")
    if perms is None:
        data["permissions"] = []

    return data, warnings


def _validate_roles(roles: List[Dict], warnings: List[str]) -> List[Dict]:
    """校验角色列表"""
    validated = []
    seen_codes = set()
    for r in roles:
        if not isinstance(r, dict):
            warnings.append(f"跳过非字典类型的角色: {r}")
            continue
        if not r.get("name"):
            warnings.append(f"跳过缺失 name 的角色: {r}")
            continue
        code, w = _fix_code(r.get("code"), r["name"])
        if w:
            warnings.append(f"角色 '{r['name']}': {w}")
        r["code"] = code
        if code in seen_codes:
            warnings.append(f"角色 code '{code}' 重复，已跳过")
            continue
        seen_codes.add(code)
        validated.append(r)
    return validated


def _validate_dicts(dicts: List[Dict], warnings: List[str]) -> List[Dict]:
    """校验字典列表"""
    validated = []
    seen_codes = set()
    for d in dicts:
        if not isinstance(d, dict):
            warnings.append(f"跳过非字典类型的 dict: {d}")
            continue
        if not d.get("name"):
            warnings.append(f"跳过缺失 name 的字典: {d}")
            continue
        code, w = _fix_code(d.get("code"), d["name"])
        if w:
            warnings.append(f"字典 '{d['name']}': {w}")
        d["code"] = code
        if code in seen_codes:
            warnings.append(f"字典 code '{code}' 重复，已跳过")
            continue
        seen_codes.add(code)
        # 校验选项
        options = d.get("options", [])
        if not options or not isinstance(options, list):
            warnings.append(f"字典 '{d['name']}' 没有选项")
            d["options"] = []
        else:
            d["options"] = _validate_dict_options(options, d["name"], warnings)
        validated.append(d)
    return validated


def _validate_dict_options(options: List[Dict], dict_name: str, warnings: List[str]) -> List[Dict]:
    """校验字典选项"""
    validated = []
    seen_codes = set()
    for opt in options:
        if not isinstance(opt, dict) or not opt.get("name"):
            continue
        code, w = _fix_code(opt.get("code"), opt["name"])
        if w:
            warnings.append(f"字典 '{dict_name}' 选项 '{opt['name']}': {w}")
        opt["code"] = code
        if code in seen_codes:
            continue
        seen_codes.add(code)
        validated.append(opt)
    return validated


def _validate_models(
    models: List[Dict],
    dict_codes: set,
    model_codes: set,
    warnings: List[str],
) -> List[Dict]:
    """校验模型列表"""
    validated = []
    seen_codes = set()
    for m in models:
        if not isinstance(m, dict):
            warnings.append(f"跳过非字典类型的模型: {m}")
            continue
        if not m.get("name"):
            warnings.append(f"跳过缺失 name 的模型: {m}")
            continue
        code, w = _fix_code(m.get("code"), m["name"])
        if w:
            warnings.append(f"模型 '{m['name']}': {w}")
        m["code"] = code
        if code in seen_codes:
            warnings.append(f"模型 code '{code}' 重复，已跳过")
            continue
        seen_codes.add(code)
        # 校验字段
        fields = m.get("fields", [])
        if not fields or not isinstance(fields, list):
            warnings.append(f"模型 '{m['name']}' 没有字段")
            m["fields"] = []
        else:
            m["fields"] = _validate_fields(fields, m["name"], dict_codes, model_codes, warnings)
        validated.append(m)
    return validated


def _validate_fields(
    fields: List[Dict],
    model_name: str,
    dict_codes: set,
    model_codes: set,
    warnings: List[str],
) -> List[Dict]:
    """校验字段列表"""
    validated = []
    seen_codes = set()
    for f in fields:
        if not isinstance(f, dict):
            continue
        if not f.get("name"):
            warnings.append(f"模型 '{model_name}' 中跳过缺失 name 的字段")
            continue

        # code
        code, w = _fix_code(f.get("code"), f["name"])
        if w:
            warnings.append(f"模型 '{model_name}' 字段 '{f['name']}': {w}")
        f["code"] = code

        # 系统保留字段：平台自动维护，业务字段不得使用
        if code in RESERVED_FIELD_CODES:
            warnings.append(
                f"模型 '{model_name}' 字段 '{f['name']}' 编码 '{code}' 是平台系统字段，已自动移除"
            )
            continue

        if code in seen_codes:
            warnings.append(f"模型 '{model_name}' 字段 code '{code}' 重复，已跳过")
            continue
        seen_codes.add(code)

        # type
        ftype = f.get("type", "单行输入")
        normalized, tw = _normalize_field_type(ftype)
        if tw:
            warnings.append(f"模型 '{model_name}' 字段 '{f['name']}': {tw}")
        f["type"] = normalized

        # dict 引用检查
        if normalized in _DICT_REQUIRED_TYPES and not f.get("dict"):
            warnings.append(
                f"模型 '{model_name}' 字段 '{f['name']}' 类型为 '{normalized}' 但未设 dict"
            )
        if f.get("dict") and f["dict"] not in dict_codes and dict_codes:
            warnings.append(
                f"模型 '{model_name}' 字段 '{f['name']}' 引用的字典 '{f['dict']}' 不存在"
            )

        # ref 引用检查
        if normalized in _REF_REQUIRED_TYPES and not f.get("ref"):
            warnings.append(
                f"模型 '{model_name}' 字段 '{f['name']}' 类型为 '{normalized}' 但未设 ref"
            )

        # 子表校验
        if normalized == "子表":
            if not f.get("sub_code"):
                warnings.append(f"模型 '{model_name}' 字段 '{f['name']}' 是子表但未设 sub_code")
            sub_fields = f.get("sub_fields", [])
            if sub_fields and isinstance(sub_fields, list):
                f["sub_fields"] = _validate_fields(
                    sub_fields, f"{model_name}.{f['name']}", dict_codes, model_codes, warnings
                )

        validated.append(f)
    return validated


# ==================================================================
# Patch 操作校验
# ==================================================================

def validate_patch_actions(actions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """校验 patch 操作列表。

    返回 (validated_actions, warnings)。
    无效的 action 会被跳过并加入 warnings。
    """
    warnings: List[str] = []
    validated = []

    if not isinstance(actions, list):
        warnings.append(f"actions 必须是数组，实际收到: {type(actions).__name__}")
        return [], warnings

    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            warnings.append(f"action[{i}]: 不是字典类型，已跳过")
            continue

        op = action.get("op")
        if not op:
            warnings.append(f"action[{i}]: 缺失 op 字段，已跳过")
            continue

        if op not in VALID_PATCH_OPS:
            warnings.append(f"action[{i}]: 未知操作 '{op}'，已跳过")
            continue

        # 按操作类型校验
        w = _validate_single_action(i, action)
        if w:
            warnings.extend(w)

        # 自动修复 code
        _auto_fix_action_codes(action)

        validated.append(action)

    return validated, warnings


def _validate_single_action(idx: int, action: Dict) -> List[str]:
    """校验单个 patch action，返回 warnings"""
    warnings = []
    op = action["op"]

    # remove 操作需要 target
    if op.startswith("remove_") and not action.get("target"):
        warnings.append(f"action[{idx}] ({op}): 缺失 target 字段")

    # add 操作需要 value
    if op.startswith("add_") and not action.get("value"):
        warnings.append(f"action[{idx}] ({op}): 缺失 value 字段")

    # add_field / update_field / remove_field 需要 model
    if op in ("add_field", "update_field", "remove_field") and not action.get("model"):
        warnings.append(f"action[{idx}] ({op}): 缺失 model 字段")

    # update 操作需要 target 或 value
    if op.startswith("update_"):
        if not action.get("target") and not action.get("value"):
            warnings.append(f"action[{idx}] ({op}): 需要 target 或 value")

    # value 中的 name 检查（add 操作）
    if op.startswith("add_") and action.get("value"):
        value = action["value"]
        if isinstance(value, dict) and not value.get("name") and op != "add_field":
            # add_field 的 value 可以只有部分字段
            if op in ("add_dict", "add_model", "add_role", "add_workflow"):
                warnings.append(f"action[{idx}] ({op}): value 中缺失 name")

    return warnings


def _auto_fix_action_codes(action: Dict):
    """自动修复 patch action 中的 code 字段"""
    value = action.get("value")
    if not isinstance(value, dict):
        return

    # 如果 value 有 name 但没 code，自动生成
    if value.get("name") and not value.get("code"):
        op = action["op"]
        if op in ("add_dict", "add_model", "add_role"):
            value["code"] = _generate_code(value["name"])

    # 修复字段的 type
    if action["op"] in ("add_field", "update_field") and value.get("type"):
        normalized, _ = _normalize_field_type(value["type"])
        value["type"] = normalized

    # 递归修复 fields
    if value.get("fields") and isinstance(value["fields"], list):
        for f in value["fields"]:
            if isinstance(f, dict) and f.get("name") and not f.get("code"):
                f["code"] = _generate_code(f["name"])
            if isinstance(f, dict) and f.get("type"):
                normalized, _ = _normalize_field_type(f["type"])
                f["type"] = normalized

    # options
    if value.get("options") and isinstance(value["options"], list):
        for opt in value["options"]:
            if isinstance(opt, dict) and opt.get("name") and not opt.get("code"):
                opt["code"] = _generate_code(opt["name"])
