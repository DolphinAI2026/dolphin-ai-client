"""aPaaS 表单权限原子操作(operations 层)。

收口 generator_v2 / step_executor 间漂移的权限相关函数,使两条 0-1 生成路径
(一把梭 run_complete_generation / 分步 execute_*)共享单一实现,杜绝"修一侧
漏另一侧"的漂移(历史上权限 payload 修复只落 step_executor 侧)。

逐个函数收口,canonical 取两侧中行为更正确/更鲁棒的一份(见各函数 docstring)。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


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


async def _sync_form_permissions_to_form_config(
    client,
    app_id: str,
    form_id: str,
    *,
    rules: List[dict],
    role_code_map: Dict[str, dict],
    form_name: str = "",
    form_code: str = "",
    all_model_codes: Optional[List[str]] = None,
    fallback_components: Optional[List[dict]] = None,
    menu_id: str = "",
) -> None:
    """把表单权限回写到 formConfig(canonical,3-7 收口)。

    canonical = generator_v2 编排(更优/更全)+ step_executor 的 `if not form_id` 早返守卫:
    - fetch 用 `_query_saveable_form_config`(先试 query_form_context_config 超集,异常回退
      query_detail_page_config)—— 旧 step 直用 raw,本版严格更全。
    - `_apply_latest` 每次重建权限组(retry 用新 dict,避免别名)+ 固化表单标识(传
      all_model_codes 修 allModelCodes,防"我的待办"占位)+ 画布组件补全 + detailPage 镜像。
    - 带冲突重试保存。

    两条 0-1 路径(一把梭/分步)共享本对象,杜绝权限回写漂移。
    """
    from app.operations.form_config import (
        _apply_form_identity_to_form_config,
        _clone_for_form_config_permissions,
        _ensure_canvas_form_components,
        _query_saveable_form_config,
        _save_form_config_with_retry,
    )

    if not form_id:
        return

    def _apply_latest(form_config: dict) -> None:
        permission_groups, advanced_groups, operation_groups = _build_permission_groups_for_form_config(
            rules, role_code_map,
        )
        permission_groups = _clone_for_form_config_permissions(permission_groups)
        advanced_groups = _clone_for_form_config_permissions(advanced_groups)
        operation_groups = _clone_for_form_config_permissions(operation_groups)
        form_config["permissionGroups"] = permission_groups
        form_config["advancedPermissionGroups"] = advanced_groups
        form_config["operationPermissionGroups"] = operation_groups
        detail_page = form_config.setdefault("detailPage", {})
        if isinstance(detail_page, dict):
            detail_page["permissionGroups"] = permission_groups
            detail_page["advancedPermissionGroups"] = advanced_groups
            detail_page["operationPermissionGroups"] = operation_groups
        _apply_form_identity_to_form_config(
            form_config,
            form_name=form_name,
            form_code=form_code,
            all_model_codes=all_model_codes or [],
            app_id=app_id,
            form_id=form_id,
            menu_id=menu_id,
        )
        _ensure_canvas_form_components(form_config, fallback_components)

    form_config = await _query_saveable_form_config(client, app_id, form_id)
    _apply_latest(form_config)
    logger.info(
        "save_form_config reason: 回写表单权限 (formId=%s, formName=%s)",
        form_id,
        form_name or "<unknown>",
    )
    await _save_form_config_with_retry(
        client,
        app_id,
        form_config,
        form_id=form_id,
        apply_latest=_apply_latest,
        reason="回写表单权限",
    )
