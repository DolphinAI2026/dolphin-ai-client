"""aPaaS 表单权限原子操作(operations 层)。

收口 generator_v2 / step_executor 间漂移的权限相关函数,使两条 0-1 生成路径
(一把梭 run_complete_generation / 分步 execute_*)共享单一实现,杜绝"修一侧
漏另一侧"的漂移(历史上权限 payload 修复只落 step_executor 侧)。

逐个函数收口,canonical 取两侧中行为更正确/更鲁棒的一份(见各函数 docstring)。
"""

from __future__ import annotations

from typing import Dict, List


def _parse_permission_ops(op: object) -> set[str]:
    """把权限规则的 op 字段解析成操作集合。

    canonical = step_executor 版(严格超集):
    - str(常见情形): 按逗号拆分、去空白、丢空 —— 与旧 generator_v2 版逐字等价。
    - list/tuple/set: 逐项取用 —— 旧 generator_v2 版对非 str 一律返回 {"all"},
      会丢掉真实 ops(bug);本版正确保留。
    - 其它类型: 回退 {"all"}。
    """
    if isinstance(op, str):
        raw_ops = op.replace(" ", "").split(",") if "," in op else [op]
    elif isinstance(op, (list, tuple, set)):
        raw_ops = list(op)
    else:
        raw_ops = ["all"]
    return {str(item).strip() for item in raw_ops if str(item).strip()}


def _permission_object_for_form_config(rule: dict, role_code_map: Dict[str, dict]) -> dict:
    """把一条权限规则解析成 permissionObject(type/value/displayName)。

    canonical = generator_v2 版(读 `roleCode|role` 双 key,是 step_executor
    `_resolve_permission_object` 只读 `role` 的超集,更鲁棒)。ALL_USER 时 value
    必须空串(平台要求,写 'ALL_USER' 会被当用户 ID 查)。
    """
    role_code = str(rule.get("roleCode") or rule.get("role") or "").strip()
    if role_code and role_code != "all":
        role_info = role_code_map.get(role_code, {})
        role_id = str(role_info.get("id") or "").strip()
        role_code_value = str(role_info.get("roleCode") or role_code).strip()
        role_name = str(role_info.get("roleName") or rule.get("roleName") or role_code).strip()
        return {
            "permissionObjectType": "ROLE",
            "permissionObjectValue": role_id or role_code_value,
            "permissionObjectDisplayName": role_name,
        }
    return {
        "permissionObjectType": "ALL_USER",
        "permissionObjectValue": "",
        "permissionObjectDisplayName": "全部人员",
    }


def _build_permission_groups_for_form_config(
    rules: List[dict],
    role_code_map: Dict[str, dict],
) -> tuple[List[dict], List[dict], List[dict]]:
    """构建 formConfig 三组权限 payload(permission/advanced/operation groups)。

    canonical(3-6 收口,2026-06-14 平台确认后):
    = generator_v2 的 9 字段 superset(advanced 含 query/update/delete +
      comment/export/print/log/dataShare/queryApprovalInfo —— 平台 honor 全部 9 个)
    + step_executor 的 operation 对象 `permissionRange`(更完整)。

    收口顺带修了 step_executor 旧 bug:它旧实现 advanced 只发 3 个字段,漏发了
    导出/打印/评论/日志等权限(而其 _build_form_permission_payload 的 dataPermissionGroups
    本就声明含这些)。
    """
    from app.operations.form_config import _normalize_permission_range

    permission_groups: List[dict] = []
    advanced_groups: List[dict] = []
    operation_groups: List[dict] = []

    for index, rule in enumerate(rules, start=1):
        perm_obj = _permission_object_for_form_config(rule, role_code_map)
        object_type = perm_obj["permissionObjectType"]
        object_value = perm_obj["permissionObjectValue"]
        object_name = perm_obj["permissionObjectDisplayName"]
        range_type = _normalize_permission_range(rule.get("data", "ALL"))
        ops = _parse_permission_ops(rule.get("op", "all"))
        can_view = "all" in ops or "view" in ops
        can_add = "all" in ops or "add" in ops
        can_edit = "all" in ops or "edit" in ops
        can_delete = "all" in ops or "delete" in ops
        can_import = bool(rule.get("canImport"))
        can_draft = bool(rule.get("canDraft"))
        can_export = bool(rule.get("canExport"))

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
                    "permissionRange": {"rangeType": range_type},
                }],
            })

    return permission_groups, advanced_groups, operation_groups
