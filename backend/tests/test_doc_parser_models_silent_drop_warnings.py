"""数据模型解析「非法即默默 continue」真丢数据点应进 errors 通道（行为不变 + 可见消息）。

覆盖：
1. 聚合格式 A：字段行「模型编码」为空 → 该字段无法归属、被跳过
2. 聚合格式：模型定义行「模型编码」为空 → 该模型被跳过
3. 分块格式 B：#### 块缺少「模型编码：xxx」声明 → 整块字段被跳过
"""
from __future__ import annotations

from app.doc_parsers import models as models_parser


def test_aggregate_field_row_empty_model_code_dropped_with_message():
    section = """## 四、数据模型

### 4.1 模型定义

| 模型编码 | 模型名称 |
|---|---|
| customer | 客户 |

### 4.2 模型字段

| 模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |
|---|---|---|---|---|
| customer | cust_name | 客户名称 | varchar | 64 |
|  | orphan_field | 孤儿字段 | varchar | 64 |
"""
    parsed, errors = models_parser.parse(section)

    # 行为不变：customer 模型在，合法字段在
    customer = next(m for m in parsed if m["code"] == "customer")
    field_codes = {f["code"] for f in customer["fields"]}
    assert "cust_name" in field_codes
    # 孤儿字段（无模型编码）没被挂到任何模型上
    assert "orphan_field" not in field_codes

    # 可见消息
    assert any("孤儿字段" in e and "所属模型编码为空" in e for e in errors), errors


def test_aggregate_model_row_empty_code_dropped_with_message():
    section = """## 四、数据模型

### 4.1 模型定义

| 模型编码 | 模型名称 |
|---|---|
| customer | 客户 |
|  | 无编码模型 |

### 4.2 模型字段

| 模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |
|---|---|---|---|---|
| customer | cust_name | 客户名称 | varchar | 64 |
"""
    parsed, errors = models_parser.parse(section)

    codes = {m["code"] for m in parsed}
    assert "customer" in codes
    # 无编码的模型行被跳过
    assert len(parsed) == 1

    assert any("无编码模型" in e and "模型编码为空" in e for e in errors), errors


def test_block_format_missing_model_code_declaration_dropped_with_message():
    # 格式 B：第二个 #### 块没有「模型编码：xxx」声明 → 整块字段静默丢，应有提示
    section = """## 四、数据模型

### 4.1 模型定义

| 模型编码 | 模型名称 |
|---|---|
| customer | 客户 |
| product | 产品 |

#### 客户字段

> 模型编码：`customer`

| 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |
|---|---|---|---|
| cust_name | 客户名称 | varchar | 64 |

#### 产品字段（漏写模型编码）

| 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |
|---|---|---|---|
| prod_name | 产品名称 | varchar | 64 |
"""
    parsed, errors = models_parser.parse(section)

    customer = next(m for m in parsed if m["code"] == "customer")
    assert {f["code"] for f in customer["fields"]} == {"cust_name"}

    # product 模型在（来自模型定义表），但因块漏声明、它的字段没挂上
    product = next(m for m in parsed if m["code"] == "product")
    assert {f["code"] for f in product["fields"]} == set()

    # 可见消息：哪个块缺声明
    assert any("缺少" in e and "模型编码" in e and "产品字段" in e for e in errors), errors
