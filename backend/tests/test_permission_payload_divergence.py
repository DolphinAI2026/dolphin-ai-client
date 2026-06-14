"""3-6 权限 payload 收口护栏(收口后:从"锁差异"转为"锁收敛")。

generator_v2 与 step_executor 的 `_build_permission_groups_for_form_config` 已收口到
`app.operations.permissions` 的单一 canonical(两条 0-1 生成路径共享同一对象)。

平台确认(2026-06-14, 大明哥经 xhh):apaas 表单 advanced 权限 **honor 全部 9 个操作字段**
(query/update/delete + comment/export/print/log/dataShare/queryApprovalInfo)。故 canonical
= gen_v2 的 9 字段 superset + step_executor 的 operation 对象 permissionRange。

收口顺带修了 step_executor 旧 bug:它旧 `_build` 只发 3 个 advanced 字段,而
`_build_form_permission_payload` 的 dataPermissionGroups 注释本就声明含"导出/评论/日志/打印"
—— 即旧 step_exec 漏发了这些权限。收口后正确发出。

  ① 共享不变量(收口必须保住)—— test_shared_invariants_*
  ② 收敛断言(两侧同一 canonical)—— test_canonical_*
"""
from __future__ import annotations

from app.generator_v2 import _build_permission_groups_for_form_config as build_g2
from app.step_executor import _build_permission_groups_for_form_config as build_step


# 代表性输入:一个 ROLE 规则(含 view/edit/del/add → 触发 operation_groups)+ 一个 ALL_USER 规则。
# 用规范 key "role"(见 config_assembler.py:144 的规则格式),真实规则即此形态。
_ROLE_MAP = {"manager": {"id": "role-1", "roleCode": "manager", "roleName": "经理"}}
_RULES = [
    {"role": "manager", "op": "view,edit,del,add", "data": "ALL", "canExport": True},
    {"role": "all", "op": "view", "data": "ALL"},
]


def _run_both():
    g2 = build_g2(_RULES, _ROLE_MAP)
    step = build_step(_RULES, _ROLE_MAP)
    return g2, step


# ─────────────────── ① 共享不变量(收口必须保住)───────────────────

def _objs_by_type(advanced_groups, obj_type):
    """从 advanced_groups[*].permissionObjects 取指定类型的权限对象。"""
    return [
        obj
        for g in advanced_groups
        for obj in g.get("permissionObjects", [])
        if obj.get("permissionObjectType") == obj_type
    ]


def test_shared_invariants_all_user_value_empty():
    """两侧 ALL_USER 的 permissionObjectValue 都是空串(不是 'ALL_USER')。

    平台对 ALL_USER 要求空值,写 'ALL_USER' 会被当用户 ID 查。
    """
    for _pg, advanced_groups, _ops in _run_both():
        all_user = _objs_by_type(advanced_groups, "ALL_USER")
        assert all_user, "应有 ALL_USER 权限对象"
        for obj in all_user:
            assert obj["permissionObjectValue"] == "", f"ALL_USER value 必须空串, 实际 {obj!r}"


def test_shared_invariants_role_resolved_to_id():
    """两侧 ROLE 的 permissionObjectValue 都解析成 role id(role-1)。"""
    for _pg, advanced_groups, _ops in _run_both():
        role_objs = _objs_by_type(advanced_groups, "ROLE")
        assert role_objs, "应有 ROLE 权限对象"
        for obj in role_objs:
            assert obj["permissionObjectValue"] == "role-1", f"ROLE value 应为 role id, 实际 {obj!r}"


def test_shared_invariants_three_groups_returned():
    """两侧都返回 (permission_groups, advanced_groups, operation_groups) 三元组, 各非空。"""
    for permission_groups, advanced_groups, operation_groups in _run_both():
        assert len(permission_groups) == 2  # ROLE + ALL_USER
        assert len(advanced_groups) == 2
        # operation_groups 仅 ROLE 规则含 add → 1 条
        assert len(operation_groups) == 1


# ─────────────────── ② 收敛断言(两侧同一 canonical)───────────────────

def test_canonical_is_single_shared_object():
    """两侧 import 的 `_build_permission_groups_for_form_config` 是同一个对象(已收口)。"""
    assert build_g2 is build_step


def test_canonical_output_deep_equal():
    """同一输入两侧产出深度相等(收口铁证)。"""
    g2, step = _run_both()
    assert g2 == step


def test_canonical_advanced_has_nine_fields():
    """advanced_groups 的 permissionOperationType 含全部 9 个字段(平台 honor)。"""
    expected = {
        "queryPermission", "updatePermission", "deletePermission",
        "commentPermission", "dataSharePermission", "exportPermission",
        "logPermission", "printPermission", "queryApprovalInfoPermission",
    }
    for _pg, advanced_groups, _ops in _run_both():
        keys = set(advanced_groups[0]["permissionOperationType"].keys())
        assert keys == expected, f"advanced 应含 9 字段, 实际 {keys}"


def test_canonical_advanced_export_honors_can_export():
    """canExport=True 的规则 → exportPermission True(确保 9 字段不是摆设)。"""
    for _pg, advanced_groups, _ops in _run_both():
        # 第一条规则 canExport=True
        assert advanced_groups[0]["permissionOperationType"]["exportPermission"] is True


def test_canonical_operation_object_has_permission_range():
    """operation_groups 的 permissionObjects 带 permissionRange(取自 step_exec, 更完整)。"""
    for _pg, _adv, operation_groups in _run_both():
        op_obj = operation_groups[0]["permissionObjects"][0]
        assert "permissionRange" in op_obj, "operation 对象应带 permissionRange"
        assert op_obj["permissionRange"] == {"rangeType": "ALL"}
