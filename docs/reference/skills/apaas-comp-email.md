# aPaaS Component: Email (电子邮箱)

## 组件类型
`FORM_EMAIL_INPUT` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_EMAIL_INPUT",
  "label": "邮箱",
  "modelField": "engineer_a1b2.email_addr"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "邮箱", "type": "电子邮箱"},
    "engineer_a1b2", "email_addr"
)
```

## 注意事项
- 自带邮箱格式验证
- 可作为列表页查询条件和显示列
