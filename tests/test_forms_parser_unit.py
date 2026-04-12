import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.doc_parsers import forms as forms_parser


def _sample_models():
    return [
        {
            "code": "customer",
            "name": "客户",
            "fields": [
                {"code": "name", "name": "客户名称", "type": "单行输入"},
                {"code": "phone", "name": "联系电话", "type": "手机号码"},
            ],
        }
    ]


def test_forms_parser_accepts_model_code_in_heading():
    section_text = """
### 客户表单（customer）

| 字段编码 | 字段名称 | 是否必填 |
|---------|---------|---------|
| name | 客户名称 | 是 |
| phone | 联系电话 | 否 |
"""

    forms, errors = forms_parser.parse(section_text, _sample_models())

    assert errors == []
    assert len(forms) == 1
    assert forms[0]["modelCode"] == "customer"
    assert {c["code"] for c in forms[0]["components"]} == {"name", "phone"}


def test_forms_parser_accepts_model_name_in_metadata():
    section_text = """
### 客户信息表单

| 表单名称 | 绑定主表模型名称 |
|---------|----------------|
| 客户信息表单 | 客户 |

| 字段编码 | 字段名称 | 是否必填 |
|---------|---------|---------|
| name | 客户名称 | 是 |
"""

    forms, errors = forms_parser.parse(section_text, _sample_models())

    assert errors == []
    assert len(forms) == 1
    assert forms[0]["modelCode"] == "customer"
    assert forms[0]["name"] == "客户信息表单"
