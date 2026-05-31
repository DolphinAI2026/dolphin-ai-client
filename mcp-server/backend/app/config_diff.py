"""
配置差异检测模块

对比新旧配置，生成差异报告，支持：
- 角色 (roles)
- 字典 (dicts) 及字典选项 (dict_values)
- 模型 (models) 及模型字段 (fields)
- 表单配置 (forms)
- 流程配置 (processes)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class ChangeType(str, Enum):
    """变更类型"""
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass
class BaseChange:
    """变更基类"""
    name: str
    code: str
    change_type: ChangeType
    old_value: Optional[Dict[str, Any]] = None
    new_value: Optional[Dict[str, Any]] = None


@dataclass
class RoleChange(BaseChange):
    """角色变更"""
    remote_id: Optional[str] = None  # 平台上的 roleId


@dataclass
class DictOptionChange(BaseChange):
    """字典选项变更"""
    dict_code: str = ""
    remote_id: Optional[str] = None  # 平台上的字典值 ID


@dataclass
class DictChange(BaseChange):
    """字典变更"""
    remote_id: Optional[str] = None  # 平台上的字典 ID
    option_changes: List[DictOptionChange] = field(default_factory=list)


@dataclass
class FieldChange(BaseChange):
    """模型字段变更"""
    model_code: str = ""
    remote_id: Optional[str] = None  # 平台上的字段 ID
    field_type: Optional[str] = None


@dataclass
class ModelChange(BaseChange):
    """模型变更"""
    remote_id: Optional[str] = None  # 平台上的模型 ID
    field_changes: List[FieldChange] = field(default_factory=list)


@dataclass
class FormComponentChange(BaseChange):
    """表单组件变更"""
    form_code: str = ""                      # 所属表单编码
    component_type: Optional[str] = None     # FORM_TEXT_INPUT 等
    model_field: Optional[str] = None        # modelCode.fieldCode（普通组件和子表内组件）
    table_model_code: Optional[str] = None   # 子表组件的 tableModelCode / 子表内组件所属的子表
    is_sub_table: bool = False               # 是否为子表组件
    changed_properties: List[str] = field(default_factory=list)  # 变更的属性列表


@dataclass
class FormChange(BaseChange):
    """表单变更"""
    remote_id: Optional[str] = None  # 平台上的表单 ID
    menu_id: Optional[str] = None  # 菜单 ID
    model_code: Optional[str] = None  # 关联的模型编码
    component_changes: List[FormComponentChange] = field(default_factory=list)  # 组件变更


@dataclass
class ProcessChange(BaseChange):
    """流程变更"""
    remote_id: Optional[str] = None  # 平台上的流程 ID
    form_code: Optional[str] = None  # 关联的表单编码


@dataclass
class ConfigDiff:
    """配置差异报告"""
    has_changes: bool = False

    # 各资源类型的变更
    role_changes: List[RoleChange] = field(default_factory=list)
    dict_changes: List[DictChange] = field(default_factory=list)
    model_changes: List[ModelChange] = field(default_factory=list)
    form_changes: List[FormChange] = field(default_factory=list)
    process_changes: List[ProcessChange] = field(default_factory=list)

    # 警告和不支持的变更
    warnings: List[str] = field(default_factory=list)
    unsupported_changes: List[str] = field(default_factory=list)

    # 统计
    summary: str = ""

    # 经过编码继承修正后的新配置（调用方保存时应使用此版本）
    normalized_new_config: Optional[Dict[str, Any]] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，用于 API 响应"""
        return {
            "has_changes": self.has_changes,
            "summary": self.summary,
            "role_changes": [self._change_to_dict(c) for c in self.role_changes],
            "dict_changes": [self._dict_change_to_dict(c) for c in self.dict_changes],
            "model_changes": [self._model_change_to_dict(c) for c in self.model_changes],
            "form_changes": [self._form_change_to_dict(c) for c in self.form_changes],
            "process_changes": [self._change_to_dict(c) for c in self.process_changes],
            "warnings": self.warnings,
            "unsupported_changes": self.unsupported_changes,
        }

    def _change_to_dict(self, change: BaseChange) -> Dict[str, Any]:
        return {
            "name": change.name,
            "code": change.code,
            "change_type": change.change_type.value,
            "remote_id": getattr(change, "remote_id", None),
            "old_value": change.old_value,
            "new_value": change.new_value,
        }

    def _dict_change_to_dict(self, change: DictChange) -> Dict[str, Any]:
        result = self._change_to_dict(change)
        result["option_changes"] = [
            {
                "name": opt.name,
                "code": opt.code,
                "change_type": opt.change_type.value,
                "dict_code": opt.dict_code,
                "remote_id": opt.remote_id,
                "old_value": opt.old_value,
                "new_value": opt.new_value,
            }
            for opt in change.option_changes
        ]
        return result

    def _model_change_to_dict(self, change: ModelChange) -> Dict[str, Any]:
        result = self._change_to_dict(change)
        result["field_changes"] = [
            {
                "name": f.name,
                "code": f.code,
                "change_type": f.change_type.value,
                "model_code": f.model_code,
                "field_type": f.field_type,
                "remote_id": f.remote_id,
                "old_value": f.old_value,
                "new_value": f.new_value,
            }
            for f in change.field_changes
        ]
        return result

    def _form_change_to_dict(self, change: FormChange) -> Dict[str, Any]:
        result = self._change_to_dict(change)
        result["menu_id"] = change.menu_id
        result["model_code"] = change.model_code
        result["component_changes"] = [
            {
                "name": c.name,
                "code": c.code,
                "change_type": c.change_type.value,
                "form_code": c.form_code,
                "component_type": c.component_type,
                "model_field": c.model_field,
                "table_model_code": c.table_model_code,
                "is_sub_table": c.is_sub_table,
                "changed_properties": c.changed_properties,
                "old_value": c.old_value,
                "new_value": c.new_value,
            }
            for c in change.component_changes
        ]
        return result


def _normalize_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """标准化配置格式"""
    if not config:
        return {"data": {}}

    # 处理可能的嵌套结构
    if "data" in config:
        data = config["data"]
    else:
        data = config

    return {
        "roles": data.get("roles", []),
        "dicts": data.get("dicts", []),
        "models": data.get("models", []),
        "forms": data.get("forms", []),
        "processes": data.get("processes", []),
    }


# ---------------------------------------------------------------------------
# 名称优先匹配 & V1 编码继承
# ---------------------------------------------------------------------------

def _inherit_codes_from_old(
    old_config: Optional[Dict[str, Any]],
    new_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    将 V2（new_config）中与 V1（old_config）**同名**实体的 code 替换为 V1 的 code。

    这样后续按 code 做 diff 时，同名实体不会因为 AI 生成的编码不同而被误判为
    "删除旧 + 新增新"。

    **就地修改** new_config（的副本）并返回修改后的版本。
    """
    import copy
    new_config = copy.deepcopy(new_config)

    old = _normalize_config(old_config)
    new = _normalize_config(new_config)

    # --- 角色 ---
    _inherit_list_codes(
        old_list=old["roles"],
        new_list=new["roles"],
        name_key="roleName",
        name_fallback="name",
        code_key="roleCode",
        code_fallback="code",
    )

    # --- 字典 ---
    old_dict_by_name = _inherit_list_codes(
        old_list=old["dicts"],
        new_list=new["dicts"],
        name_key="dictionaryName",
        name_fallback="name",
        code_key="dictionaryCode",
        code_fallback="code",
    )
    # 字典选项
    for new_d in new["dicts"]:
        d_name = new_d.get("dictionaryName", new_d.get("name", ""))
        old_d = old_dict_by_name.get(d_name)
        if old_d is not None:
            old_opts = old_d.get("values", old_d.get("options", []))
            new_opts = new_d.get("values", new_d.get("options", []))
            _inherit_list_codes(
                old_list=old_opts,
                new_list=new_opts,
                name_key="valueName",
                name_fallback="name",
                code_key="valueCode",
                code_fallback="code",
            )

    # --- 模型 & 字段 ---
    old_model_by_name = _inherit_list_codes(
        old_list=old["models"],
        new_list=new["models"],
        name_key="modelName",
        name_fallback="name",
        code_key="modelCode",
        code_fallback="code",
    )
    for new_m in new["models"]:
        m_name = new_m.get("modelName", new_m.get("name", ""))
        old_m = old_model_by_name.get(m_name)
        if old_m is not None:
            old_fields = old_m.get("fields", old_m.get("dataModelFields", []))
            new_fields = new_m.get("fields", new_m.get("dataModelFields", []))
            _inherit_list_codes(
                old_list=old_fields,
                new_list=new_fields,
                name_key="fieldName",
                name_fallback="name",
                code_key="fieldCode",
                code_fallback="code",
            )

    # --- 表单 ---
    _inherit_list_codes(
        old_list=old["forms"],
        new_list=new["forms"],
        name_key="formName",
        name_fallback="name",
        code_key="formCode",
        code_fallback="code",
    )

    # --- 流程 ---
    _inherit_list_codes(
        old_list=old["processes"],
        new_list=new["processes"],
        name_key="processName",
        name_fallback="name",
        code_key="processCode",
        code_fallback="code",
    )

    # 将修改后的列表写回 new_config
    if "data" in new_config:
        target = new_config["data"]
    else:
        target = new_config
    target["roles"] = new["roles"]
    target["dicts"] = new["dicts"]
    target["models"] = new["models"]
    target["forms"] = new["forms"]
    target["processes"] = new["processes"]

    return new_config


def _inherit_list_codes(
    old_list: List[Dict],
    new_list: List[Dict],
    name_key: str,
    name_fallback: str,
    code_key: str,
    code_fallback: str,
) -> Dict[str, Dict]:
    """
    对 new_list 中的每一项，按 **名称** 在 old_list 中查找同名实体。
    如果找到，将 new 项的 code 替换为 old 项的 code（就地修改 new_list）。

    返回 old_list 的 name -> item 映射，方便调用方做子级继承。
    """
    def _get_name(item: Dict) -> str:
        return item.get(name_key, item.get(name_fallback, ""))

    def _get_code(item: Dict) -> str:
        return item.get(code_key, item.get(code_fallback, ""))

    old_by_name: Dict[str, Dict] = {}
    for item in old_list:
        n = _get_name(item)
        if n:
            old_by_name[n] = item

    for new_item in new_list:
        n = _get_name(new_item)
        if not n:
            continue
        old_item = old_by_name.get(n)
        if old_item is None:
            continue
        old_code = _get_code(old_item)
        if not old_code:
            continue
        # 将 V2 的 code 替换为 V1 的 code
        if code_key in new_item:
            new_item[code_key] = old_code
        elif code_fallback in new_item:
            new_item[code_fallback] = old_code

    return old_by_name


def _compare_roles(
    old_roles: List[Dict],
    new_roles: List[Dict],
    remote_roles: Optional[List[Dict]] = None
) -> List[RoleChange]:
    """对比角色变更 - 使用 roleName 作为唯一标识"""
    changes = []

    # 辅助函数：获取角色名称作为 key
    def get_role_name(r: Dict) -> str:
        return r.get("roleName", r.get("name", ""))

    # 辅助函数：获取角色编码
    def get_role_code(r: Dict) -> str:
        return r.get("roleCode", r.get("code", ""))

    # 建立 roleName -> role 映射（使用角色名称作为唯一标识）
    old_map = {get_role_name(r): r for r in old_roles if get_role_name(r)}
    new_map = {get_role_name(r): r for r in new_roles if get_role_name(r)}
    remote_map = {}
    if remote_roles:
        remote_map = {get_role_name(r): r for r in remote_roles if get_role_name(r)}

    all_names = set(old_map.keys()) | set(new_map.keys())

    for role_name in all_names:
        if not role_name:
            continue

        old_role = old_map.get(role_name)
        new_role = new_map.get(role_name)
        remote_role = remote_map.get(role_name)

        # 获取角色编码（优先使用旧配置的编码，保持一致性）
        role_code = get_role_code(old_role) if old_role else get_role_code(new_role) if new_role else ""

        if role_name not in old_map and role_name in new_map:
            # 新增
            changes.append(RoleChange(
                name=role_name,
                code=role_code,
                change_type=ChangeType.ADDED,
                new_value=new_role,
                remote_id=remote_role.get("id") if remote_role else None
            ))
        elif role_name in old_map and role_name not in new_map:
            # 删除
            changes.append(RoleChange(
                name=role_name,
                code=role_code,
                change_type=ChangeType.DELETED,
                old_value=old_role,
                remote_id=remote_role.get("id") if remote_role else None
            ))
        elif old_role and new_role:
            # 角色同名 → 视为同一实体
            # 编码差异已在 _inherit_codes_from_old 中修正，不再视为修改
            # 角色目前没有其他业务属性需要对比，故同名即"未变更"
            pass

    return changes


def _compare_dict_options(
    old_options: List[Dict],
    new_options: List[Dict],
    dict_code: str,
    remote_options: Optional[List[Dict]] = None
) -> List[DictOptionChange]:
    """
    对比字典选项变更 — 按**名称优先**匹配。

    编码已在 _inherit_codes_from_old 中完成继承，此处用 code 做映射即可。
    同名同 code 的选项视为未变更（不再因 code 差异误报）。
    """
    changes = []

    # 编码继承已完成，按 code 建立映射
    old_map = {o.get("valueCode", o.get("code", "")): o for o in old_options}
    new_map = {o.get("valueCode", o.get("code", "")): o for o in new_options}
    remote_map = {}
    if remote_options:
        remote_map = {o.get("valueCode", ""): o for o in remote_options}

    all_codes = set(old_map.keys()) | set(new_map.keys())

    for code in all_codes:
        if not code:
            continue

        old_opt = old_map.get(code)
        new_opt = new_map.get(code)
        remote_opt = remote_map.get(code)

        name = (new_opt or old_opt or {}).get("valueName",
               (new_opt or old_opt or {}).get("name", code))

        if code not in old_map and code in new_map:
            changes.append(DictOptionChange(
                name=name,
                code=code,
                change_type=ChangeType.ADDED,
                dict_code=dict_code,
                new_value=new_opt,
                remote_id=remote_opt.get("id") if remote_opt else None
            ))
        elif code in old_map and code not in new_map:
            changes.append(DictOptionChange(
                name=name,
                code=code,
                change_type=ChangeType.DELETED,
                dict_code=dict_code,
                old_value=old_opt,
                remote_id=remote_opt.get("id") if remote_opt else None
            ))
        elif old_opt and new_opt:
            # 同 code 选项 — 只比较名称是否真的变了
            old_name = old_opt.get("valueName", old_opt.get("name", ""))
            new_name = new_opt.get("valueName", new_opt.get("name", ""))

            if old_name != new_name:
                changes.append(DictOptionChange(
                    name=new_name,
                    code=code,
                    change_type=ChangeType.MODIFIED,
                    dict_code=dict_code,
                    old_value=old_opt,
                    new_value=new_opt,
                    remote_id=remote_opt.get("id") if remote_opt else None
                ))

    return changes


def _compare_dicts(
    old_dicts: List[Dict],
    new_dicts: List[Dict],
    remote_dicts: Optional[List[Dict]] = None,
    remote_dict_options: Optional[Dict[str, List[Dict]]] = None
) -> List[DictChange]:
    """对比字典变更"""
    changes = []

    old_map = {d.get("dictionaryCode", d.get("code", "")): d for d in old_dicts}
    new_map = {d.get("dictionaryCode", d.get("code", "")): d for d in new_dicts}
    remote_map = {}
    if remote_dicts:
        remote_map = {d.get("dictionaryCode", ""): d for d in remote_dicts}

    all_codes = set(old_map.keys()) | set(new_map.keys())

    for code in all_codes:
        if not code:
            continue

        old_dict = old_map.get(code)
        new_dict = new_map.get(code)
        remote_dict = remote_map.get(code)

        name = (new_dict or old_dict or {}).get("dictionaryName",
               (new_dict or old_dict or {}).get("name", code))

        # 获取选项
        old_options = []
        new_options = []
        remote_options = []

        if old_dict:
            old_options = old_dict.get("values", old_dict.get("options", []))
        if new_dict:
            new_options = new_dict.get("values", new_dict.get("options", []))
        if remote_dict_options and code in remote_dict_options:
            remote_options = remote_dict_options[code]

        option_changes = _compare_dict_options(old_options, new_options, code, remote_options)

        if code not in old_map and code in new_map:
            changes.append(DictChange(
                name=name,
                code=code,
                change_type=ChangeType.ADDED,
                new_value=new_dict,
                remote_id=remote_dict.get("id") if remote_dict else None,
                option_changes=option_changes
            ))
        elif code in old_map and code not in new_map:
            changes.append(DictChange(
                name=name,
                code=code,
                change_type=ChangeType.DELETED,
                old_value=old_dict,
                remote_id=remote_dict.get("id") if remote_dict else None,
                option_changes=option_changes
            ))
        else:
            # 检查字典本身是否有修改
            old_name = (old_dict or {}).get("dictionaryName", (old_dict or {}).get("name", ""))
            new_name = (new_dict or {}).get("dictionaryName", (new_dict or {}).get("name", ""))

            dict_modified = old_name != new_name

            if dict_modified or option_changes:
                changes.append(DictChange(
                    name=new_name or name,
                    code=code,
                    change_type=ChangeType.MODIFIED if dict_modified else ChangeType.MODIFIED,
                    old_value=old_dict,
                    new_value=new_dict,
                    remote_id=remote_dict.get("id") if remote_dict else None,
                    option_changes=option_changes
                ))

    return changes


def _get_field_comment(field: Optional[Dict]) -> str:
    """读取字段备注，兼容 preview 的 description 写法。"""
    if not field:
        return ""
    return field.get("fieldComment", field.get("description", ""))


def _get_remote_model_id(model: Optional[Dict]) -> Optional[str]:
    """读取远端模型 ID，兼容 id / modelId。"""
    if not model:
        return None
    remote_id = model.get("id", model.get("modelId"))
    return str(remote_id) if remote_id is not None else None


def _get_remote_field_id(field: Optional[Dict]) -> Optional[str]:
    """读取远端字段 ID，兼容 id / fieldId。"""
    if not field:
        return None
    remote_id = field.get("id", field.get("fieldId"))
    return str(remote_id) if remote_id is not None else None


def _compare_fields(
    old_fields: List[Dict],
    new_fields: List[Dict],
    model_code: str,
    remote_fields: Optional[List[Dict]] = None
) -> List[FieldChange]:
    """对比模型字段变更"""
    changes = []

    old_map = {f.get("fieldCode", f.get("code", "")): f for f in old_fields}
    new_map = {f.get("fieldCode", f.get("code", "")): f for f in new_fields}
    remote_map = {}
    if remote_fields:
        remote_map = {f.get("fieldCode", ""): f for f in remote_fields}

    all_codes = set(old_map.keys()) | set(new_map.keys())

    for code in all_codes:
        if not code:
            continue

        old_field = old_map.get(code)
        new_field = new_map.get(code)
        remote_field = remote_map.get(code)

        name = (new_field or old_field or {}).get("fieldName",
               (new_field or old_field or {}).get("name", code))
        field_type = (new_field or old_field or {}).get(
            "fieldType",
            (new_field or old_field or {}).get("type", "")
        )

        if code not in old_map and code in new_map:
            changes.append(FieldChange(
                name=name,
                code=code,
                change_type=ChangeType.ADDED,
                model_code=model_code,
                field_type=field_type,
                new_value=new_field,
                remote_id=_get_remote_field_id(remote_field)
            ))
        elif code in old_map and code not in new_map:
            changes.append(FieldChange(
                name=name,
                code=code,
                change_type=ChangeType.DELETED,
                model_code=model_code,
                field_type=field_type,
                old_value=old_field,
                remote_id=_get_remote_field_id(remote_field)
            ))
        elif old_field and new_field:
            # 只比较核心业务属性（type 和 dict/ref）
            # required/comment 等次要属性差异忽略，因为 AI 两次解析可能不一致
            modified = False

            # 字段类型（核心属性）
            old_type = old_field.get("fieldType", old_field.get("type", ""))
            new_type = new_field.get("fieldType", new_field.get("type", ""))
            if old_type and new_type and old_type != new_type:
                modified = True

            # 关联字典（核心属性）
            old_dict_code = old_field.get("dictionaryCode", old_field.get("dict", "")) or ""
            new_dict_code = new_field.get("dictionaryCode", new_field.get("dict", "")) or ""
            if old_dict_code != new_dict_code:
                modified = True

            # 关联引用模型（核心属性）
            old_ref_val = old_field.get("refModelCode", "") or ""
            new_ref_val = new_field.get("refModelCode", "") or ""
            # ref 也可能是 dict 格式 {"model": "xxx"}
            if not old_ref_val and old_field.get("ref"):
                r = old_field["ref"]
                old_ref_val = r.get("model", "") if isinstance(r, dict) else str(r)
            if not new_ref_val and new_field.get("ref"):
                r = new_field["ref"]
                new_ref_val = r.get("model", "") if isinstance(r, dict) else str(r)
            if old_ref_val != new_ref_val:
                modified = True

            if modified:
                changes.append(FieldChange(
                    name=name,
                    code=code,
                    change_type=ChangeType.MODIFIED,
                    model_code=model_code,
                    field_type=field_type,
                    old_value=old_field,
                    new_value=new_field,
                    remote_id=_get_remote_field_id(remote_field)
                ))

    return changes


def _compare_models(
    old_models: List[Dict],
    new_models: List[Dict],
    remote_models: Optional[List[Dict]] = None
) -> List[ModelChange]:
    """对比模型变更"""
    changes = []

    old_map = {m.get("modelCode", m.get("code", "")): m for m in old_models}
    new_map = {m.get("modelCode", m.get("code", "")): m for m in new_models}
    remote_map = {}
    if remote_models:
        remote_map = {m.get("modelCode", ""): m for m in remote_models}

    all_codes = set(old_map.keys()) | set(new_map.keys())

    for code in all_codes:
        if not code:
            continue

        old_model = old_map.get(code)
        new_model = new_map.get(code)
        remote_model = remote_map.get(code)

        name = (new_model or old_model or {}).get("modelName",
               (new_model or old_model or {}).get("name", code))

        # 获取字段
        old_fields = []
        new_fields = []
        remote_fields = []

        if old_model:
            old_fields = old_model.get("fields", old_model.get("dataModelFields", []))
        if new_model:
            new_fields = new_model.get("fields", new_model.get("dataModelFields", []))
        if remote_model:
            remote_fields = remote_model.get("fields", remote_model.get("dataModelFields", []))

        field_changes = _compare_fields(old_fields, new_fields, code, remote_fields)

        if code not in old_map and code in new_map:
            changes.append(ModelChange(
                name=name,
                code=code,
                change_type=ChangeType.ADDED,
                new_value=new_model,
                remote_id=_get_remote_model_id(remote_model),
                field_changes=field_changes
            ))
        elif code in old_map and code not in new_map:
            changes.append(ModelChange(
                name=name,
                code=code,
                change_type=ChangeType.DELETED,
                old_value=old_model,
                remote_id=_get_remote_model_id(remote_model),
                field_changes=field_changes
            ))
        else:
            old_name = (old_model or {}).get("modelName", (old_model or {}).get("name", ""))
            new_name = (new_model or {}).get("modelName", (new_model or {}).get("name", ""))

            model_modified = old_name != new_name

            if model_modified or field_changes:
                changes.append(ModelChange(
                    name=new_name or name,
                    code=code,
                    change_type=ChangeType.MODIFIED if model_modified else ChangeType.MODIFIED,
                    old_value=old_model,
                    new_value=new_model,
                    remote_id=_get_remote_model_id(remote_model),
                    field_changes=field_changes
                ))

    return changes


def _get_component_key(component: Dict) -> str:
    """
    获取组件唯一标识

    规则：
    - 子表组件使用 tableModelCode
    - 普通组件和子表内组件使用 modelField（格式：modelCode.fieldCode）
    """
    comp_type = component.get("componentType", "")

    if comp_type == "FORM_WIDGET_SON_TABLE":
        # 子表组件使用 tableModelCode
        return component.get("tableModelCode", "")

    # 普通组件和子表内组件都使用 modelField
    return component.get("modelField", "")


def _build_component_map(components: List[Dict]) -> Dict[str, Dict]:
    """
    构建组件索引（含递归处理子表内组件）

    返回扁平化的组件映射，key 为组件唯一标识
    """
    result = {}
    for comp in components:
        key = _get_component_key(comp)
        if key:
            result[key] = comp

        # 递归处理子表内的组件
        if comp.get("componentType") == "FORM_WIDGET_SON_TABLE":
            table_model_code = comp.get("tableModelCode", "")
            for col in comp.get("tableColumn", []):
                col_key = _get_component_key(col)
                if col_key:
                    col_copy = col.copy()
                    col_copy["_table_model_code"] = table_model_code  # 记录所属子表
                    result[col_key] = col_copy
    return result


def _compare_component_properties(old: Dict, new: Dict) -> List[str]:
    """
    对比组件属性变更

    返回变更的属性名列表
    """
    key_props = [
        "componentType", "label", "required", "readOnly",
        "hidden", "placeholder", "dictionarySelectConfig",
        "defaultValue", "maxLength", "minLength", "pattern",
        "tips", "showCondition", "tableColumn"
    ]
    return [p for p in key_props if old.get(p) != new.get(p)]


def _compare_form_components(
    old_components: List[Dict],
    new_components: List[Dict],
    form_code: str
) -> List[FormComponentChange]:
    """
    对比表单组件变更

    Args:
        old_components: 旧表单的组件列表
        new_components: 新表单的组件列表
        form_code: 表单编码

    Returns:
        组件变更列表
    """
    changes = []

    old_map = _build_component_map(old_components)
    new_map = _build_component_map(new_components)
    all_keys = set(old_map.keys()) | set(new_map.keys())

    for key in all_keys:
        if not key:
            continue

        old_comp = old_map.get(key)
        new_comp = new_map.get(key)

        if key not in old_map:
            # 新增
            is_sub_table = new_comp.get("componentType") == "FORM_WIDGET_SON_TABLE"
            changes.append(FormComponentChange(
                name=new_comp.get("label", key),
                code=key,
                change_type=ChangeType.ADDED,
                form_code=form_code,
                component_type=new_comp.get("componentType"),
                model_field=new_comp.get("modelField"),
                table_model_code=new_comp.get("tableModelCode") if is_sub_table else new_comp.get("_table_model_code"),
                new_value=new_comp,
                is_sub_table=is_sub_table
            ))
        elif key not in new_map:
            # 删除
            is_sub_table = old_comp.get("componentType") == "FORM_WIDGET_SON_TABLE"
            changes.append(FormComponentChange(
                name=old_comp.get("label", key),
                code=key,
                change_type=ChangeType.DELETED,
                form_code=form_code,
                component_type=old_comp.get("componentType"),
                model_field=old_comp.get("modelField"),
                table_model_code=old_comp.get("tableModelCode") if is_sub_table else old_comp.get("_table_model_code"),
                old_value=old_comp,
                is_sub_table=is_sub_table
            ))
        else:
            # 对比属性
            changed_props = _compare_component_properties(old_comp, new_comp)
            if changed_props:
                is_sub_table = new_comp.get("componentType") == "FORM_WIDGET_SON_TABLE"
                changes.append(FormComponentChange(
                    name=new_comp.get("label", key),
                    code=key,
                    change_type=ChangeType.MODIFIED,
                    form_code=form_code,
                    component_type=new_comp.get("componentType"),
                    model_field=new_comp.get("modelField"),
                    table_model_code=new_comp.get("tableModelCode") if is_sub_table else new_comp.get("_table_model_code"),
                    old_value=old_comp,
                    new_value=new_comp,
                    changed_properties=changed_props,
                    is_sub_table=is_sub_table
                ))

    return changes


def _compare_forms(
    old_forms: List[Dict],
    new_forms: List[Dict],
    remote_forms: Optional[List[Dict]] = None
) -> List[FormChange]:
    """对比表单变更"""
    changes = []

    old_map = {f.get("formCode", f.get("code", "")): f for f in old_forms}
    new_map = {f.get("formCode", f.get("code", "")): f for f in new_forms}
    remote_map = {}
    if remote_forms:
        remote_map = {f.get("formCode", ""): f for f in remote_forms}

    all_codes = set(old_map.keys()) | set(new_map.keys())

    for code in all_codes:
        if not code:
            continue

        old_form = old_map.get(code)
        new_form = new_map.get(code)
        remote_form = remote_map.get(code)

        name = (new_form or old_form or {}).get("formName",
               (new_form or old_form or {}).get("name", code))
        model_code = (new_form or old_form or {}).get("modelCode", "")

        # 获取组件列表
        old_components = []
        new_components = []
        if old_form:
            old_components = old_form.get("components", [])
        if new_form:
            new_components = new_form.get("components", [])

        # 对比组件变更
        component_changes = _compare_form_components(old_components, new_components, code)

        if code not in old_map and code in new_map:
            changes.append(FormChange(
                name=name,
                code=code,
                change_type=ChangeType.ADDED,
                new_value=new_form,
                remote_id=remote_form.get("id") if remote_form else None,
                menu_id=remote_form.get("menuId") if remote_form else None,
                model_code=model_code,
                component_changes=component_changes
            ))
        elif code in old_map and code not in new_map:
            changes.append(FormChange(
                name=name,
                code=code,
                change_type=ChangeType.DELETED,
                old_value=old_form,
                remote_id=remote_form.get("id") if remote_form else None,
                menu_id=remote_form.get("menuId") if remote_form else None,
                model_code=model_code,
                component_changes=component_changes
            ))
        elif old_form and new_form:
            # 比较表单名称
            old_name = old_form.get("formName", old_form.get("name", ""))
            new_name = new_form.get("formName", new_form.get("name", ""))

            form_name_modified = old_name != new_name

            # 如果表单名称修改或有组件变更，则记录表单变更
            if form_name_modified or component_changes:
                changes.append(FormChange(
                    name=new_name,
                    code=code,
                    change_type=ChangeType.MODIFIED,
                    old_value=old_form,
                    new_value=new_form,
                    remote_id=remote_form.get("id") if remote_form else None,
                    menu_id=remote_form.get("menuId") if remote_form else None,
                    model_code=model_code,
                    component_changes=component_changes
                ))

    return changes


def _compare_processes(
    old_processes: List[Dict],
    new_processes: List[Dict],
    remote_processes: Optional[List[Dict]] = None
) -> List[ProcessChange]:
    """对比流程变更"""
    changes = []

    old_map = {p.get("processCode", p.get("code", "")): p for p in old_processes}
    new_map = {p.get("processCode", p.get("code", "")): p for p in new_processes}
    remote_map = {}
    if remote_processes:
        remote_map = {p.get("processCode", ""): p for p in remote_processes}

    all_codes = set(old_map.keys()) | set(new_map.keys())

    for code in all_codes:
        if not code:
            continue

        old_proc = old_map.get(code)
        new_proc = new_map.get(code)
        remote_proc = remote_map.get(code)

        name = (new_proc or old_proc or {}).get("processName",
               (new_proc or old_proc or {}).get("name", code))
        form_code = (new_proc or old_proc or {}).get("formCode", "")

        if code not in old_map and code in new_map:
            changes.append(ProcessChange(
                name=name,
                code=code,
                change_type=ChangeType.ADDED,
                new_value=new_proc,
                remote_id=remote_proc.get("id") if remote_proc else None,
                form_code=form_code
            ))
        elif code in old_map and code not in new_map:
            changes.append(ProcessChange(
                name=name,
                code=code,
                change_type=ChangeType.DELETED,
                old_value=old_proc,
                remote_id=remote_proc.get("id") if remote_proc else None,
                form_code=form_code
            ))
        elif old_proc and new_proc:
            # 简化比较
            if old_proc != new_proc:
                changes.append(ProcessChange(
                    name=name,
                    code=code,
                    change_type=ChangeType.MODIFIED,
                    old_value=old_proc,
                    new_value=new_proc,
                    remote_id=remote_proc.get("id") if remote_proc else None,
                    form_code=form_code
                ))

    return changes


def _generate_summary(diff: ConfigDiff) -> str:
    """生成变更摘要"""
    parts = []

    # 角色
    role_added = sum(1 for c in diff.role_changes if c.change_type == ChangeType.ADDED)
    role_modified = sum(1 for c in diff.role_changes if c.change_type == ChangeType.MODIFIED)
    role_deleted = sum(1 for c in diff.role_changes if c.change_type == ChangeType.DELETED)
    if role_added or role_modified or role_deleted:
        role_parts = []
        if role_added:
            role_parts.append(f"新增 {role_added} 个")
        if role_modified:
            role_parts.append(f"修改 {role_modified} 个")
        if role_deleted:
            role_parts.append(f"删除 {role_deleted} 个")
        parts.append(f"角色: {', '.join(role_parts)}")

    # 字典
    dict_added = sum(1 for c in diff.dict_changes if c.change_type == ChangeType.ADDED)
    dict_modified = sum(1 for c in diff.dict_changes if c.change_type == ChangeType.MODIFIED)
    dict_deleted = sum(1 for c in diff.dict_changes if c.change_type == ChangeType.DELETED)
    if dict_added or dict_modified or dict_deleted:
        dict_parts = []
        if dict_added:
            dict_parts.append(f"新增 {dict_added} 个")
        if dict_modified:
            dict_parts.append(f"修改 {dict_modified} 个")
        if dict_deleted:
            dict_parts.append(f"删除 {dict_deleted} 个")
        parts.append(f"字典: {', '.join(dict_parts)}")

    # 模型
    model_added = sum(1 for c in diff.model_changes if c.change_type == ChangeType.ADDED)
    model_modified = sum(1 for c in diff.model_changes if c.change_type == ChangeType.MODIFIED)
    model_deleted = sum(1 for c in diff.model_changes if c.change_type == ChangeType.DELETED)
    if model_added or model_modified or model_deleted:
        model_parts = []
        if model_added:
            model_parts.append(f"新增 {model_added} 个")
        if model_modified:
            model_parts.append(f"修改 {model_modified} 个")
        if model_deleted:
            model_parts.append(f"删除 {model_deleted} 个")
        parts.append(f"模型: {', '.join(model_parts)}")

    # 表单
    form_added = sum(1 for c in diff.form_changes if c.change_type == ChangeType.ADDED)
    form_modified = sum(1 for c in diff.form_changes if c.change_type == ChangeType.MODIFIED)
    form_deleted = sum(1 for c in diff.form_changes if c.change_type == ChangeType.DELETED)
    # 统计组件变更
    comp_added = sum(
        sum(1 for cc in c.component_changes if cc.change_type == ChangeType.ADDED)
        for c in diff.form_changes
    )
    comp_modified = sum(
        sum(1 for cc in c.component_changes if cc.change_type == ChangeType.MODIFIED)
        for c in diff.form_changes
    )
    comp_deleted = sum(
        sum(1 for cc in c.component_changes if cc.change_type == ChangeType.DELETED)
        for c in diff.form_changes
    )
    if form_added or form_modified or form_deleted:
        form_parts = []
        if form_added:
            form_parts.append(f"新增 {form_added} 个")
        if form_modified:
            form_parts.append(f"修改 {form_modified} 个")
        if form_deleted:
            form_parts.append(f"删除 {form_deleted} 个")
        # 添加组件变更统计
        if comp_added or comp_modified or comp_deleted:
            comp_parts = []
            if comp_added:
                comp_parts.append(f"新增 {comp_added}")
            if comp_modified:
                comp_parts.append(f"修改 {comp_modified}")
            if comp_deleted:
                comp_parts.append(f"删除 {comp_deleted}")
            form_parts.append(f"组件: {', '.join(comp_parts)}")
        parts.append(f"表单: {', '.join(form_parts)}")

    # 流程
    proc_added = sum(1 for c in diff.process_changes if c.change_type == ChangeType.ADDED)
    proc_modified = sum(1 for c in diff.process_changes if c.change_type == ChangeType.MODIFIED)
    proc_deleted = sum(1 for c in diff.process_changes if c.change_type == ChangeType.DELETED)
    if proc_added or proc_modified or proc_deleted:
        proc_parts = []
        if proc_added:
            proc_parts.append(f"新增 {proc_added} 个")
        if proc_modified:
            proc_parts.append(f"修改 {proc_modified} 个")
        if proc_deleted:
            proc_parts.append(f"删除 {proc_deleted} 个")
        parts.append(f"流程: {', '.join(proc_parts)}")

    return "；".join(parts) if parts else "无变更"


def _generate_warnings(diff: ConfigDiff) -> List[str]:
    """生成警告信息"""
    warnings = []

    # 字典删除警告
    for dc in diff.dict_changes:
        if dc.change_type == ChangeType.DELETED:
            warnings.append(f"字典「{dc.name}」删除将调用禁用接口（保留数据完整性）")
        for opt in dc.option_changes:
            if opt.change_type == ChangeType.DELETED:
                warnings.append(f"字典「{dc.name}」选项「{opt.name}」删除将调用禁用接口")

    # 模型删除警告
    for mc in diff.model_changes:
        if mc.change_type == ChangeType.DELETED:
            warnings.append(f"模型「{mc.name}」删除：平台不支持删除模型，将忽略此变更")
        for fc in mc.field_changes:
            if fc.change_type == ChangeType.DELETED:
                warnings.append(f"模型「{mc.name}」字段「{fc.name}」删除将通过更新状态实现")

    # 流程删除警告
    for pc in diff.process_changes:
        if pc.change_type == ChangeType.DELETED:
            warnings.append(f"流程「{pc.name}」删除将调用关闭接口")

    return warnings


def _generate_unsupported(diff: ConfigDiff) -> List[str]:
    """生成不支持的变更列表"""
    unsupported = []

    # 模型删除不支持
    for mc in diff.model_changes:
        if mc.change_type == ChangeType.DELETED:
            unsupported.append(f"模型「{mc.name}」删除：平台不支持")

    return unsupported


def compute_config_diff(
    old_config: Optional[Dict[str, Any]],
    new_config: Dict[str, Any],
    remote_data: Optional[Dict[str, Any]] = None
) -> ConfigDiff:
    """
    对比新旧配置，生成差异报告

    Args:
        old_config: 旧配置（本地保存的上一次配置）
        new_config: 新配置（LLM 生成的最新配置）
        remote_data: 平台远程数据（可选，用于获取 remote_id）
            格式: {
                "roles": [...],
                "dicts": [...],
                "dict_options": {"dict_code": [...options]},
                "models": [...],
                "forms": [...],
                "processes": [...]
            }

    Returns:
        ConfigDiff: 差异报告
    """
    # ★ 关键步骤：按名称匹配，将 V2 的编码继承为 V1 的编码
    # 这样后续按 code 做 diff 时，同名实体不会因 AI 编码差异被误判
    new_config = _inherit_codes_from_old(old_config, new_config)

    old = _normalize_config(old_config)
    new = _normalize_config(new_config)

    remote_roles = remote_data.get("roles", []) if remote_data else None
    remote_dicts = remote_data.get("dicts", []) if remote_data else None
    remote_dict_options = remote_data.get("dict_options", {}) if remote_data else None
    remote_models = remote_data.get("models", []) if remote_data else None
    remote_forms = remote_data.get("forms", []) if remote_data else None
    remote_processes = remote_data.get("processes", []) if remote_data else None

    diff = ConfigDiff()
    diff.normalized_new_config = new_config  # 保存编码继承后的配置

    # 对比各资源
    diff.role_changes = _compare_roles(old["roles"], new["roles"], remote_roles)
    diff.dict_changes = _compare_dicts(old["dicts"], new["dicts"], remote_dicts, remote_dict_options)
    diff.model_changes = _compare_models(old["models"], new["models"], remote_models)
    diff.form_changes = _compare_forms(old["forms"], new["forms"], remote_forms)
    diff.process_changes = _compare_processes(old["processes"], new["processes"], remote_processes)

    # 判断是否有变更
    diff.has_changes = bool(
        diff.role_changes or
        diff.dict_changes or
        diff.model_changes or
        diff.form_changes or
        diff.process_changes
    )

    # 生成摘要和警告
    diff.summary = _generate_summary(diff)
    diff.warnings = _generate_warnings(diff)
    diff.unsupported_changes = _generate_unsupported(diff)

    return diff
