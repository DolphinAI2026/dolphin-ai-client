# aPaaS Component: Date (日期时间)

## 组件类型
`FORM_DATEPICK_INPUT` | 字段类型: `DATE`

## 组件配置
```json
{
  "componentType": "FORM_DATEPICK_INPUT",
  "label": "安装日期",
  "modelField": "device_a1b2.install_date"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "安装日期", "type": "日期时间"},
    "device_a1b2", "install_date"
)
```

## 注意事项
- 字段类型必须是 `DATE`（不是 STRING）
- 自带日期选择器 UI
- 可作为列表页查询条件和显示列
