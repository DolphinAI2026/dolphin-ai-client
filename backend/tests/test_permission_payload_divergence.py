"""3-6/3-7 权限 payload 收口安全网(表征测试)。

generator_v2 与 step_executor 的 `_build_permission_groups_for_form_config` 仍未收口,
因为两侧 advanced_groups 字段集差异取决于 apaas 平台是否 honor 那 6 个额外字段——代码层
无法验证,需平台/xhh 确认(见主计划 Phase 3 §3-6/3-7)。

本测试把当前差异锁成可执行 spec:
  ① 共享不变量(收口到任何一侧都【必须】保住)——见 test_shared_invariants_*
  ② 已知差异(平台确认前的现状,收口时这些断言据结论改)——见 test_known_divergence_*

收口流程:平台确认后,删掉两份实现之一、改 ② 的断言为单一 canonical 输出,① 的断言原样保留
做回归护栏。

⚠️ 已澄清(防再被误导):分析 agent 曾称"gen_v2 ALL_USER payload 写成 'ALL_USER' 是 bug"
   = 误报。两侧 ALL_USER 都返回 permissionObjectValue=""(见 test_shared_invariants_all_user)。
"""
from __future__ import annotations

from app.generator_v2 import _build_permission_groups_for_form_config as build_g2
from app.step_executor import _build_permission_groups_for_form_config as build_step


# 代表性输入:一个 ROLE 规则(含 view/edit/del/add → 触发 operation_groups)+ 一个 ALL_USER 规则。
# 用规范 key "role"(见 config_assembler.py:144 的规则格式),真实规则即此形态。
# (旁注:用非规范 "roleCode" 时两侧会分叉——gen_v2 读 roleCode|role、step 的
#  _resolve_permission_object 只读 role 当 ALL_USER;但真实规则用 role,故非生产差异。)
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

    收口到任一侧都必须保此行为(平台对 ALL_USER 要求空值,写 'ALL_USER' 会被当用户 ID 查)。
    （advanced_groups[*].permissionObjects 是带 permissionObjectType/Value 的结构。）
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


# ─────────────────── ② 已知差异(平台确认前的现状)───────────────────

def test_known_divergence_advanced_operation_type_field_count():
    """advanced_groups 的 permissionOperationType 字段集:gen_v2 多 6 个、step_exec 只 3 个。

    ⚠️待平台确认:平台是否 honor commentPermission/exportPermission/printPermission/
    logPermission/dataSharePermission/queryApprovalInfoPermission。
    - 平台只保留 query/update/delete → 收口成 step_exec(3 字段)。
    - 平台 honor 这 6 个 → 收口成 gen_v2(9 字段)以保导出/打印等权限控制。
    """
    g2, step = _run_both()
    g2_keys = set(g2[1][0]["permissionOperationType"].keys())
    step_keys = set(step[1][0]["permissionOperationType"].keys())
    base = {"queryPermission", "updatePermission", "deletePermission"}
    extra = {
        "commentPermission", "dataSharePermission", "exportPermission",
        "logPermission", "printPermission", "queryApprovalInfoPermission",
    }
    assert base <= g2_keys and base <= step_keys, "两侧都含基础 3 字段"
    assert extra <= g2_keys, "gen_v2 含额外 6 字段"
    assert not (extra & step_keys), "step_exec 不含额外 6 字段"


def test_known_divergence_operation_object_permission_range():
    """operation_groups 的 permissionObjects:step_exec 带 permissionRange, gen_v2 不带。

    收口时应保留 step_exec 的 permissionRange(更完整)。
    """
    g2, step = _run_both()
    g2_obj = g2[2][0]["permissionObjects"][0]
    step_obj = step[2][0]["permissionObjects"][0]
    assert "permissionRange" not in g2_obj, "gen_v2 operation 对象无 permissionRange"
    assert "permissionRange" in step_obj, "step_exec operation 对象带 permissionRange"
