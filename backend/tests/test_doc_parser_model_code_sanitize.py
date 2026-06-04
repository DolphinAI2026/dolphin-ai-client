"""模型编码带中文时，parser 不能静默丢模型 —— 应自动规范化编码并保留模型(含字段)。

复现 bug：设计文档里某模型编码写成 `test委托`(英文+中文混)，旧逻辑正则一拦直接
continue 把整张模型连字段一起丢掉，文档还报 96 分"通过"。修复后应 sanitize 成 `test`
并保留模型与其字段。
"""
from __future__ import annotations

from app.doc_parsers import models as models_parser


# ── 聚合格式(4.1 模型表 + 4.2 字段平铺大表)——截图里就是这个格式 ──
AGG_SECTION = """## 四、数据模型

### 4.1 模型定义

| 模型编码 | 模型名称 |
|---|---|
| seal_info | 印章台账 |
| test委托 | 检测委托 |

### 4.2 模型字段

| 模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |
|---|---|---|---|---|
| seal_info | seal_code | 印章编码 | varchar | 64 |
| test委托 | apply_no | 申请单号 | varchar | 64 |
"""


def test_aggregate_chinese_model_code_is_sanitized_not_dropped():
    parsed, errors = models_parser.parse(AGG_SECTION)
    codes = [m["code"] for m in parsed]

    # 两张模型都在 —— 带中文的那张没有被静默丢掉
    assert "seal_info" in codes
    assert "test" in codes, f"中文编码模型被丢了，只剩 {codes}"
    assert "test委托" not in codes  # 中文编码已被规范化，不会原样留下

    # 规范化后的编码是合法 ascii snake_case
    for c in codes:
        assert c.isascii() and c.replace("_", "").isalnum()

    # 关键：被规范化的模型，它的字段没有被孤立丢掉
    test_model = next(m for m in parsed if m["code"] == "test")
    field_codes = [f.get("code") for f in test_model["fields"]]
    assert "apply_no" in field_codes, f"模型被规范化后字段丢了：{field_codes}"


def test_aggregate_pure_chinese_model_code_falls_back_to_generated():
    section = """## 四、数据模型

### 4.1 模型定义

| 模型编码 | 模型名称 |
|---|---|
| 委托 | 检测委托 |

### 4.2 模型字段

| 模型编码 | 字段编码 | 字段名称 | 数据库字段类型 | 长度/精度 |
|---|---|---|---|---|
| 委托 | apply_no | 申请单号 | varchar | 64 |
"""
    parsed, errors = models_parser.parse(section)
    assert len(parsed) == 1
    code = parsed[0]["code"]
    # 纯中文编码无 ascii 可留 → 生成一个合法 ascii 编码(c_<hash> 之类)，模型仍保留
    assert code.isascii() and code and code[0].isalpha()
    assert "委托" not in code
