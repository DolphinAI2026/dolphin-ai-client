# aPaaS Component: Textarea (多行输入)

## 组件类型
`FORM_TEXTAREA_INPUT` | 字段类型: `BIG_TEXT`

## 组件配置
```json
{
  "componentType": "FORM_TEXTAREA_INPUT",
  "label": "备注",
  "modelField": "customer_a1b2.remark"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "备注", "type": "多行输入"},
    "customer_a1b2", "remark"
)
```

## 注意事项
- 字段类型必须是 `BIG_TEXT`（不是 STRING）
- 不适合作为列表页查询条件和显示列
- 适合长文本（>200 字符）
