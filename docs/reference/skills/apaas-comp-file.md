# aPaaS Component: File Upload (附件上传)

## 组件类型
`FORM_FILE_UPLOAD` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_FILE_UPLOAD",
  "label": "附件",
  "modelField": "service_order_a1b2.attachment"
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "附件", "type": "附件上传"},
    "service_order_a1b2", "attachment"
)
```

## 注意事项
- **不适合**作为列表页查询条件和显示列
- 存储文件引用（STRING 类型）
- 支持多文件上传
