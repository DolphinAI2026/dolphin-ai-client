# aPaaS Component: Text Input (单行输入)

## 组件类型
`FORM_TEXT_INPUT`

## 数据模型字段类型
`STRING`

## 用途
普通单行文本输入框，用于姓名、标题、编号等短文本字段

## 组件配置
```json
{
  "componentType": "FORM_TEXT_INPUT",
  "label": "客户名称",
  "modelField": "customer_a1b2.customer_name"
}
```

## 完整配置（可选参数）
```json
{
  "componentType": "FORM_TEXT_INPUT",
  "label": "客户名称",
  "modelField": "customer_a1b2.customer_name",
  "required": true,
  "readOnly": false,
  "hidden": false,
  "placeholder": "请输入客户名称"
}
```

## 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| componentType | string | 是 | 固定值 "FORM_TEXT_INPUT" |
| label | string | 是 | 字段标签（显示名称） |
| modelField | string | 是 | 模型字段，格式 `{modelCode}.{fieldCode}` |
| required | boolean | 否 | 是否必填，默认 false |
| readOnly | boolean | 否 | 是否只读，默认 false |
| hidden | boolean | 否 | 是否隐藏，默认 false |
| placeholder | string | 否 | 占位符文本 |

## 在 formConfig 中的使用
```json
{
  "formName": "客户",
  "formCode": "form_a1b2c3",
  "allModelCodes": ["customer_x9y8"],
  "formComponents": [
    {
      "componentType": "FORM_TEXT_INPUT",
      "label": "客户名称",
      "modelField": "customer_x9y8.customer_name"
    },
    {
      "componentType": "FORM_TEXT_INPUT",
      "label": "联系人",
      "modelField": "customer_x9y8.contact_name"
    }
  ],
  "listPageView": {
    "queryConditions": ["customer_x9y8.customer_name"],
    "queryList": ["customer_x9y8.customer_name", "customer_x9y8.contact_name"]
  }
}
```

## Python 生成示例
```python
def build_text_input_component(model_code: str, field_code: str, label: str, required: bool = False):
    component = {
        "componentType": "FORM_TEXT_INPUT",
        "label": label,
        "modelField": f"{model_code}.{field_code}"
    }
    if required:
        component["required"] = True
    return component

# 使用
component = build_text_input_component("customer_a1b2", "customer_name", "客户名称", required=True)
```

## 注意事项
- 字段类型必须是 `STRING`
- 适合长度 ≤ 200 字符的文本
- 超过 200 字符建议使用 `FORM_TEXTAREA_INPUT`（多行输入）
- 可以在列表页作为查询条件和显示列

## 相关组件
- `FORM_TEXTAREA_INPUT` — 多行输入（长文本）
- `FORM_PHONE_INPUT` — 手机号码（带格式验证）
- `FORM_EMAIL_INPUT` — 电子邮箱（带格式验证）
