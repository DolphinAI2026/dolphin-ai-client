"""表单解析「非法即默默 continue」真丢数据点应进 errors 通道（行为不变 + 用户可见消息）。

覆盖三类静默丢点：
1. 聚合格式主表字段编码为空 → 该字段跳过
2. 聚合格式子表绑定模型为空 → 该子表跳过
3. 聚合格式子表字段编码对不上模型 → 该字段跳过

断言两件事：解析结果（行为）不变 + 丢失点在 errors 里有人话提示。
"""
from __future__ import annotations

from app.doc_parsers import forms as forms_parser


_MODELS = [
    {
        "code": "order",
        "name": "订单",
        "fields": [
            {"code": "order_no", "name": "订单号", "type": "单行输入"},
            {"code": "amount", "name": "金额", "type": "数字"},
        ],
    },
    {
        "code": "order_item",
        "name": "订单明细",
        "fields": [
            {"code": "item_name", "name": "明细名称", "type": "单行输入"},
        ],
    },
]


def test_aggregate_main_field_empty_code_dropped_with_message():
    # 主表字段表里有一行字段编码为空 —— 该字段会被跳过，但要有可见提示
    section = """## 五、表单配置

### 表单清单

| 表单名称 | 表单编码 | 绑定主表模型 |
|---|---|---|
| 订单表单 | order_form | order |

### 主表字段定义

| 表单名称 | 字段编码 | 字段名称 |
|---|---|---|
| 订单表单 | order_no | 订单号 |
| 订单表单 |  | 金额 |
"""
    forms, errors = forms_parser.parse(section, _MODELS)

    # 行为不变：表单仍解析出来，order_no 组件在
    assert len(forms) == 1
    codes = {c["code"] for c in forms[0]["components"]}
    assert "order_no" in codes

    # 编码为空的「金额」行没有产生以空编码命名的组件
    assert "" not in codes

    # 可见消息：说明丢了哪个字段
    assert any("金额" in e and "字段编码为空" in e for e in errors), errors


def test_aggregate_subtable_empty_model_dropped_with_message():
    section = """## 五、表单配置

### 表单清单

| 表单名称 | 表单编码 | 绑定主表模型 |
|---|---|---|
| 订单表单 | order_form | order |

### 子表区域定义

| 表单名称 | 子表区域名称 | 绑定模型 |
|---|---|---|
| 订单表单 | 明细区 |  |
"""
    forms, errors = forms_parser.parse(section, _MODELS)

    assert len(forms) == 1
    assert any("明细区" in e and "绑定模型为空" in e for e in errors), errors


def test_aggregate_subtable_field_not_in_model_dropped_with_message():
    section = """## 五、表单配置

### 表单清单

| 表单名称 | 表单编码 | 绑定主表模型 |
|---|---|---|
| 订单表单 | order_form | order |

### 子表区域定义

| 表单名称 | 子表区域名称 | 绑定模型 |
|---|---|---|
| 订单表单 | 明细区 | order_item |

### 子表字段定义

| 表单名称 | 子表区域名称 | 字段编码 | 字段名称 |
|---|---|---|---|
| 订单表单 | 明细区 | item_name | 明细名称 |
| 订单表单 | 明细区 | ghost_field | 幽灵字段 |
"""
    forms, errors = forms_parser.parse(section, _MODELS)

    assert len(forms) == 1
    codes = {c["code"] for c in forms[0]["components"]}
    # 行为不变：合法子表字段在，幽灵字段不在
    assert "item_name" in codes
    assert "ghost_field" not in codes

    # 可见消息：说明对不上模型的字段被丢了
    assert any("ghost_field" in e and "找不到对应字段" in e for e in errors), errors
