# aPaaS Component: Number (数字输入)

## 组件类型
`FORM_NUMBER_INPUT` | 字段类型: `NUM`

## 组件配置
```json
{
  "componentType": "FORM_NUMBER_INPUT",
  "label": "数量",
  "modelField": "order_item_a1b2.quantity"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "数量", "type": "数字"},
    "order_item_a1b2", "quantity"
)
```

## 注意事项
- 字段类型必须是 `NUM`
- 存储整数或小数
- 可作为列表页查询条件和显示列
