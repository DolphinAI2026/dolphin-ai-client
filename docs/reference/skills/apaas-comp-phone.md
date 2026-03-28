# aPaaS Component: Phone (手机号码)

## 组件类型
`FORM_PHONE_INPUT` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_PHONE_INPUT",
  "label": "联系电话",
  "modelField": "customer_a1b2.contact_phone"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "联系电话", "type": "手机号码"},
    "customer_a1b2", "contact_phone"
)
```

## 注意事项
- 自带手机号格式验证
- 可作为列表页查询条件和显示列
