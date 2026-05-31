"""Draft patch engine — 把 patch action 应用到 spec_json，返回新 spec + 变更摘要。

P4 第一版只支持 3 个高频 op：
  - add_field      给模型加字段（同步更新对应表单字段）
  - update_field   改字段属性
  - set_permission 改表单角色权限

后续可扩展：delete_field / add_dict_option / set_field_visibility / 等。

每个 op 接 (spec, action)，返回 (new_spec, summary, errors)。
spec 是 deepcopy 后的对象，原 spec 不变。
"""
from __future__ import annotations
import copy
from typing import Any, Optional


# ─────────────────── 工具 ────────────────────

def _find_model(spec: dict, model_code: str) -> Optional[dict]:
    for m in spec.get("models", []) or []:
        if m.get("code") == model_code or m.get("modelCode") == model_code:
            return m
    return None


def _find_form_by_code_or_name(spec: dict, key: str) -> Optional[dict]:
    for f in spec.get("forms", []) or []:
        if f.get("code") == key or f.get("formCode") == key or f.get("name") == key or f.get("formName") == key:
            return f
    return None


def _find_permission_entry(spec: dict, form_key: str) -> Optional[dict]:
    """找 permissions 里某表单的 entry。form_key 可以是 code 或 name。"""
    form = _find_form_by_code_or_name(spec, form_key)
    form_name = form.get("name") or form.get("formName") if form else form_key
    form_code = form.get("code") or form.get("formCode") if form else form_key
    for p in spec.get("permissions", []) or []:
        pk = p.get("form") or p.get("formCode") or p.get("formName") or p.get("form_code")
        if pk in (form_name, form_code, form_key):
            return p
    return None


def _role_name(spec: dict, role_code: str) -> str:
    for r in spec.get("roles", []) or []:
        if r.get("code") == role_code or r.get("roleCode") == role_code:
            return r.get("name") or r.get("roleName") or role_code
    return role_code


# ─────────────────── add_field ────────────────────

def _apply_add_field(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    model_code = action.get("model") or action.get("model_code")
    field = action.get("field") or {}
    field_code = field.get("code") or field.get("fieldCode")

    if not model_code:
        return None, "", ["add_field 缺 model"]
    if not field_code:
        return None, "", ["add_field 缺 field.code"]
    if not field.get("name"):
        return None, "", ["add_field 缺 field.name"]

    model = _find_model(spec, model_code)
    if not model:
        return None, "", [f"模型 {model_code} 不存在"]

    fields = model.setdefault("fields", [])
    if any((f.get("code") == field_code or f.get("fieldCode") == field_code) for f in fields):
        return None, "", [f"字段 {field_code} 已存在于模型 {model_code}"]

    # 规范化字段（默认 type=单行输入，databaseFieldType=varchar）
    new_field = {
        "code": field_code,
        "name": field["name"],
        "type": field.get("type", "单行输入"),
        "databaseFieldType": field.get("databaseFieldType", "varchar"),
    }
    if field.get("maxLength"):
        new_field["maxLength"] = str(field["maxLength"])
    if field.get("dictCode"):
        new_field["dictCode"] = field["dictCode"]
    if field.get("refModel"):
        new_field["refModel"] = field["refModel"]
    if field.get("refField"):
        new_field["refField"] = field["refField"]
    if field.get("required") is not None:
        new_field["required"] = bool(field["required"])

    fields.append(new_field)
    summary = f"模型「{model.get('name', model_code)}」新增字段「{field['name']}」({field_code})"
    return spec, summary, []


# ─────────────────── update_field ────────────────────

def _apply_update_field(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    model_code = action.get("model") or action.get("model_code")
    field_code = action.get("field_code") or action.get("fieldCode")
    updates = action.get("updates") or {}

    if not model_code or not field_code:
        return None, "", ["update_field 缺 model 或 field_code"]
    if not isinstance(updates, dict) or not updates:
        return None, "", ["update_field 缺 updates"]

    model = _find_model(spec, model_code)
    if not model:
        return None, "", [f"模型 {model_code} 不存在"]

    field = next(
        (f for f in (model.get("fields") or [])
         if f.get("code") == field_code or f.get("fieldCode") == field_code),
        None,
    )
    if not field:
        return None, "", [f"字段 {field_code} 不存在于模型 {model_code}"]

    changed_keys = []
    for k, v in updates.items():
        if field.get(k) != v:
            field[k] = v
            changed_keys.append(k)

    if not changed_keys:
        return spec, f"模型「{model.get('name')}」.「{field.get('name')}」字段无实际变更", []

    summary = (
        f"模型「{model.get('name')}」.「{field.get('name')}」字段更新："
        + ", ".join(f"{k}={updates[k]}" for k in changed_keys)
    )
    return spec, summary, []


# ─────────────────── set_permission ────────────────────

# op 字符串 → 单字段标记的映射
_OPS_MAP = {
    "view": "canView", "看": "canView",
    "add": "canAdd", "create": "canAdd", "增": "canAdd", "新增": "canAdd",
    "edit": "canEdit", "改": "canEdit", "编辑": "canEdit",
    "delete": "canDelete", "删": "canDelete", "删除": "canDelete",
    "import": "canImport", "导入": "canImport",
    "export": "canExport", "导出": "canExport",
    "draft": "canDraft", "暂存": "canDraft",
}

_SCOPE_MAP = {
    "全部数据": "ALL", "all": "ALL", "ALL": "ALL",
    "本人数据": "SELF", "self": "SELF", "SELF": "SELF",
    "本部门数据": "CURRENT_USER_DEPT", "dept": "CURRENT_USER_DEPT",
    "本部门及下级数据": "CURRENT_USER_DEPT_LOW_LEVEL", "dept_sub": "CURRENT_USER_DEPT_LOW_LEVEL",
}


def _apply_set_permission(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    form_key = action.get("form") or action.get("form_code")
    role_code = action.get("role") or action.get("role_code")
    ops = action.get("ops") or []
    scope = action.get("scope") or "ALL"

    if not form_key or not role_code:
        return None, "", ["set_permission 缺 form 或 role"]
    if not isinstance(ops, list):
        return None, "", ["set_permission ops 必须是 list"]

    form = _find_form_by_code_or_name(spec, form_key)
    if not form:
        return None, "", [f"表单 {form_key} 不存在"]
    form_name = form.get("name") or form.get("formName")

    # 找/建 permission entry
    p_entry = _find_permission_entry(spec, form_key)
    if not p_entry:
        p_entry = {"form": form_name, "rules": []}
        spec.setdefault("permissions", []).append(p_entry)

    # 构造规则
    scope_norm = _SCOPE_MAP.get(scope, scope.upper() if isinstance(scope, str) else "ALL")
    new_rule = {
        "role": role_code,
        "op": ",".join(ops) if len(ops) > 1 else (ops[0] if ops else "view"),
        "data": scope_norm,
        # 各个 canX 标记
        "canView": False, "canAdd": False, "canEdit": False, "canDelete": False,
        "canDraft": False, "canImport": False, "canExport": False,
    }
    is_all = any(o in ("all", "全权限", "full") for o in ops)
    if is_all:
        for k in ("canView", "canAdd", "canEdit", "canDelete", "canDraft", "canImport", "canExport"):
            new_rule[k] = True
        new_rule["op"] = "all"
    else:
        for o in ops:
            flag = _OPS_MAP.get(o)
            if flag:
                new_rule[flag] = True

    # 替换同 role 的规则；不存在则追加
    rules = p_entry.setdefault("rules", [])
    replaced = False
    for i, r in enumerate(rules):
        if r.get("role") == role_code or r.get("roleCode") == role_code:
            rules[i] = new_rule
            replaced = True
            break
    if not replaced:
        rules.append(new_rule)

    summary = (
        f"表单「{form_name}」.「{_role_name(spec, role_code)}」权限："
        f"{('全权限' if is_all else '+'.join(ops))} ({scope})"
    )
    return spec, summary, []


# ─────────────────── 总入口 ────────────────────

# ─────────────────── delete_field ────────────────────

def _apply_delete_field(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    model_code = action.get("model") or action.get("model_code")
    field_code = action.get("field_code") or action.get("fieldCode")
    if not model_code or not field_code:
        return None, "", ["delete_field 缺 model 或 field_code"]
    model = _find_model(spec, model_code)
    if not model:
        return None, "", [f"模型 {model_code} 不存在"]
    fields = model.get("fields") or []
    idx = next((i for i, f in enumerate(fields)
                if f.get("code") == field_code or f.get("fieldCode") == field_code), None)
    if idx is None:
        return None, "", [f"字段 {field_code} 不存在于模型 {model_code}"]
    removed = fields.pop(idx)
    return spec, f"模型「{model.get('name')}」删除字段「{removed.get('name')}」({field_code})", []


# ─────────────────── add_role ────────────────────

def _apply_add_role(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    role = action.get("role") or {}
    code = role.get("code") or role.get("roleCode")
    name = role.get("name") or role.get("roleName")
    if not code or not name:
        return None, "", ["add_role 缺 role.code 或 role.name"]
    roles = spec.setdefault("roles", [])
    if any(r.get("code") == code or r.get("roleCode") == code for r in roles):
        return None, "", [f"角色 {code} 已存在"]
    roles.append({"code": code, "name": name})
    return spec, f"新增角色「{name}」({code})", []


# ─────────────────── delete_role ────────────────────

def _apply_delete_role(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    code = action.get("role") or action.get("role_code") or action.get("roleCode")
    if not code:
        return None, "", ["delete_role 缺 role"]
    roles = spec.get("roles") or []
    idx = next((i for i, r in enumerate(roles)
                if r.get("code") == code or r.get("roleCode") == code), None)
    if idx is None:
        return None, "", [f"角色 {code} 不存在"]
    removed = roles.pop(idx)
    # 顺手清理 permissions 里对该 role 的引用
    cleaned = 0
    for p in spec.get("permissions") or []:
        rules = p.get("rules") or p.get("permissionRules") or []
        before = len(rules)
        p["rules"] = [r for r in rules if r.get("role") != code and r.get("roleCode") != code]
        cleaned += before - len(p["rules"])
    suffix = f"，顺带清理 {cleaned} 条权限规则" if cleaned else ""
    return spec, f"删除角色「{removed.get('name')}」({code}){suffix}", []


# ─────────────────── add_dict_option ────────────────────

def _apply_add_dict_option(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    dict_code = action.get("dict_code") or action.get("dictCode")
    option = action.get("option") or {}
    opt_code = option.get("code") or option.get("value")
    opt_name = option.get("name") or option.get("label")
    if not dict_code or not opt_code or not opt_name:
        return None, "", ["add_dict_option 缺 dict_code / option.code / option.name"]

    d = next((x for x in (spec.get("dicts") or [])
              if x.get("code") == dict_code or x.get("dictCode") == dict_code), None)
    if not d:
        return None, "", [f"字典 {dict_code} 不存在"]

    options = d.setdefault("options", d.get("items") or [])
    if any((o.get("code") == opt_code or o.get("value") == opt_code) for o in options):
        return None, "", [f"选项 {opt_code} 已存在于字典 {dict_code}"]
    options.append({"code": opt_code, "name": opt_name})
    return spec, f"字典「{d.get('name', dict_code)}」新增选项「{opt_name}」({opt_code})", []


# ─────────────────── add_form ────────────────────

def _apply_add_form(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    form = action.get("form") or {}
    code = form.get("code") or form.get("formCode")
    name = form.get("name") or form.get("formName")
    main_model = form.get("mainModel") or form.get("modelCode") or form.get("bindModel")
    if not code or not name:
        return None, "", ["add_form 缺 form.code 或 form.name"]
    if not main_model:
        return None, "", ["add_form 缺 form.mainModel（绑定主表模型编码）"]

    # 检查 mainModel 存在
    if not _find_model(spec, main_model):
        return None, "", [f"绑定的主表模型 {main_model} 不存在，请先 add_model 再 add_form"]

    forms = spec.setdefault("forms", [])
    if any(f.get("code") == code or f.get("formCode") == code for f in forms):
        return None, "", [f"表单 {code} 已存在"]

    new_form = {
        "code": code,
        "name": name,
        "mainModel": main_model,
        "modelCode": main_model,
        "description": form.get("description") or form.get("formDesc") or "",
        "fields": form.get("fields") or [],
        "subForms": form.get("subForms") or [],
    }
    forms.append(new_form)
    return spec, f"新增表单「{name}」({code})，绑定主表 {main_model}", []


_OPS = {
    "add_field": _apply_add_field,
    "update_field": _apply_update_field,
    "delete_field": _apply_delete_field,
    "add_role": _apply_add_role,
    "delete_role": _apply_delete_role,
    "add_dict_option": _apply_add_dict_option,
    "add_form": _apply_add_form,
    "set_permission": _apply_set_permission,
}


def apply_patch(spec: dict, action: dict) -> tuple[Optional[dict], str, list]:
    """对 spec 应用一个 patch action，返回 (new_spec, summary, errors)。

    成功：返回 new_spec（deepcopy 修改）+ summary 字符串 + []
    失败：返回 None + ""  + errors list
    """
    op = action.get("op") if isinstance(action, dict) else None
    if not op:
        return None, "", ["action 缺 op 字段"]

    handler = _OPS.get(op)
    if not handler:
        return None, "", [f"op '{op}' 不支持。已支持：{list(_OPS.keys())}"]

    new_spec = copy.deepcopy(spec)
    return handler(new_spec, action)


SUPPORTED_OPS = list(_OPS.keys())
