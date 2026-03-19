# aPaaS Component: Location (地理位置)

## 组件类型
`FORM_WIDGET_LOCATION` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_WIDGET_LOCATION",
  "label": "地理位置",
  "modelField": "site_a1b2.location_info"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "地理位置", "type": "地理位置"},
    "site_a1b2", "location_info"
)
```

## 注意事项
- 自带地图选点 UI
- 存储经纬度信息（STRING 类型）
- 可作为列表页显示列
