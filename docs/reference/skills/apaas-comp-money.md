# aPaaS Component: Money (金额)

## 组件类型
`FORM_MONEY_INPUT` | 字段类型: `NUM`

## 组件配置
```json
{
  "componentType": "FORM_MONEY_INPUT",
  "label": "金额",
  "modelField": "settlement_a1b2.total_amount"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "金额", "type": "金额"},
    "settlement_a1b2", "total_amount"
)
```

## 注意事项
- 字段类型必须是 `NUM`
- 自带货币格式化显示
- 可作为列表页查询条件和显示列
