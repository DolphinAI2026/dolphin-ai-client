"""config_diff 空 key 实体「从增量对比中静默消失」应进 diff.warnings 通道。

空 code/name 的实体会塌进同一个空 key、被 `if not code: continue` 跳过，
等于增量更新无声漏改。补 warning 让用户在预览里看得见，且：
- 行为不变（changes 不受影响）
- warning 经 to_dict() 透出（→ DiffResponse.warnings → 前端）
- 既有删除类 warning（_generate_warnings）不被覆盖
"""
from __future__ import annotations

from app.config_diff import compute_config_diff


def test_empty_code_model_warned_and_excluded_from_diff():
    old_config = {"data": {"models": []}}
    new_config = {
        "data": {
            "models": [
                {"code": "customer", "name": "客户", "fields": []},
                {"code": "", "name": "无编码模型", "fields": []},  # 空编码 → 被丢
            ]
        }
    }

    diff = compute_config_diff(old_config, new_config)

    # 行为不变：只有合法的 customer 进了 diff（新增）
    model_codes = {c.code for c in diff.model_changes}
    assert "customer" in model_codes
    assert "" not in model_codes

    # 空编码模型在 warnings 里有人话提示
    assert any("无编码模型" in w and "编码为空" in w for w in diff.warnings), diff.warnings

    # 经 to_dict 透出（API 边界）
    payload = diff.to_dict()
    assert any("无编码模型" in w for w in payload["warnings"]), payload["warnings"]


def test_empty_field_code_warned_and_excluded():
    old_config = {"data": {"models": [
        {"code": "customer", "name": "客户", "fields": [
            {"code": "cust_name", "name": "客户名称", "type": "单行输入"},
        ]},
    ]}}
    new_config = {"data": {"models": [
        {"code": "customer", "name": "客户", "fields": [
            {"code": "cust_name", "name": "客户名称", "type": "单行输入"},
            {"code": "", "name": "孤儿字段", "type": "单行输入"},  # 空编码字段
        ]},
    ]}}

    diff = compute_config_diff(old_config, new_config)

    # 唯一合法字段没变更（cust_name 两边一致），空编码字段被忽略
    customer_change = next((c for c in diff.model_changes if c.code == "customer"), None)
    if customer_change is not None:
        field_codes = {fc.code for fc in customer_change.field_changes}
        assert "" not in field_codes

    assert any("孤儿字段" in w and "编码为空" in w for w in diff.warnings), diff.warnings


def test_data_loss_warning_does_not_clobber_delete_warning():
    # 同时存在：①既有删除类 warning（_generate_warnings 产出）②空 key 丢失 warning
    # 验证两类都在 diff.warnings 里（合并而非互相覆盖）
    old_config = {"data": {"dicts": [
        {"code": "status", "name": "状态", "values": [
            {"code": "active", "name": "启用"},
        ]},
    ]}}
    new_config = {"data": {"dicts": [
        {"code": "", "name": "无编码字典", "values": []},  # 空编码字典 → 丢失 warning
    ]}}

    diff = compute_config_diff(old_config, new_config)

    # ① 删除类 warning：status 字典在 new 里没了（按 code 删除）
    assert any("状态" in w and "删除" in w for w in diff.warnings), diff.warnings
    # ② 空 key 丢失 warning
    assert any("无编码字典" in w and "编码为空" in w for w in diff.warnings), diff.warnings


def test_no_warnings_when_all_keys_present():
    # 全部实体编码齐全 → 不冒出任何空 key 告警（不误报）
    old_config = {"data": {"models": [
        {"code": "customer", "name": "客户", "fields": [
            {"code": "cust_name", "name": "客户名称", "type": "单行输入"},
        ]},
    ]}}
    new_config = {"data": {"models": [
        {"code": "customer", "name": "客户", "fields": [
            {"code": "cust_name", "name": "客户名称", "type": "单行输入"},
            {"code": "phone", "name": "电话", "type": "单行输入"},
        ]},
    ]}}

    diff = compute_config_diff(old_config, new_config)

    assert not any("编码为空" in w for w in diff.warnings), diff.warnings
