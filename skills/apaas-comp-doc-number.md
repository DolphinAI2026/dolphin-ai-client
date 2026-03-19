# aPaaS Component: Document Number (单据号)

## 组件类型
`FORM_DOCUMENT_NUMBER` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_DOCUMENT_NUMBER",
  "label": "工单号",
  "modelField": "service_order_a1b2.order_no"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "工单号", "type": "单据号"},
    "service_order_a1b2", "order_no"
)
```

## 注意事项
- 系统自动生成编号，用户不可编辑
- 通常作为表单的第一个字段
- 可作为列表页查询条件和显示列
