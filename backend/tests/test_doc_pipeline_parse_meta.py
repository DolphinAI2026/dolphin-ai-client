from app.doc_pipeline import _split_parse_messages


def test_split_parse_messages_moves_auto_fixes_out_of_errors():
    messages = [
        "模型 '合作方协议表' 字段 '备注'：未知字段类型 '他表字段'，已降级为 '单行输入'",
        "模型 '企业信息' 字段 'id' 编码 'id' 是平台系统字段，已自动移除",
        "表单组件 'industry_form.company_type' 已按模型字段类型 '单行输入' 从 'FORM_DATA_SELECTOR' 自动同步为 'FORM_TEXT_INPUT'",
        "模型 '合作方协议表' 字段 '合作方ID'：类型 '数据单选' 需要关联模型编码",
    ]

    errors, auto_fixes = _split_parse_messages(messages)

    assert errors == [
        "模型 '合作方协议表' 字段 '合作方ID'：类型 '数据单选' 需要关联模型编码",
    ]
    assert auto_fixes == [
        "模型 '合作方协议表' 字段 '备注'：未知字段类型 '他表字段'，已降级为 '单行输入'",
        "模型 '企业信息' 字段 'id' 编码 'id' 是平台系统字段，已自动移除",
        "表单组件 'industry_form.company_type' 已按模型字段类型 '单行输入' 从 'FORM_DATA_SELECTOR' 自动同步为 'FORM_TEXT_INPUT'",
    ]
