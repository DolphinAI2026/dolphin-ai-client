# aPaaS Component: People Select (人员选择)

## 组件类型
`FORM_PEOPLE_SELECT` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_PEOPLE_SELECT",
  "label": "负责人",
  "modelField": "service_order_a1b2.owner"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "负责人", "type": "人员选择"},
    "service_order_a1b2", "owner"
)
```

## 注意事项
- 从平台用户列表中选择
- 存储用户 ID（STRING 类型）
- 可作为列表页查询条件和显示列
