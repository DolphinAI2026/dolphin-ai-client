# aPaaS Component: Switch (开关)

## 组件类型
`FORM_SWITCH_SELECT` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_SWITCH_SELECT",
  "label": "是否启用",
  "modelField": "config_a1b2.is_enabled"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "是否启用", "type": "开关"},
    "config_a1b2", "is_enabled"
)
```

## 注意事项
- 字段类型是 `STRING`（不是 BOOL，平台不支持 BOOL 类型）
- 存储 "true"/"false" 字符串
- 可作为列表页查询条件和显示列
