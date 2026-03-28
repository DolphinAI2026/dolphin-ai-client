# aPaaS Component: Select Multi (下拉多选)

## 组件类型
`FORM_SELECT_INPUT` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_SELECT_INPUT",
  "label": "技能标签",
  "modelField": "engineer_a1b2.skill_tag",
  "dictionarySelectConfig": {
    "dictionaryCode": "skill_tag_x9y8",
    "dictionarySelectOptions": [
      {"id": "mechanical_x9y8", "label": "机械"},
      {"id": "electrical_x9y8", "label": "电气"},
      {"id": "software_x9y8", "label": "软件"}
    ]
  }
}
```

## Python 调用
```python
from app.skills.components import build_component

comp = build_component(
    {"name": "技能标签", "type": "下拉多选", "dict": "skill_tag"},
    "engineer_a1b2", "skill_tag",
    dicts=[{"name": "技能标签", "code": "skill_tag", "options": [
        {"name": "机械", "code": "mechanical"},
        {"name": "电气", "code": "electrical"},
    ]}],
    dict_code_map={"skill_tag": "skill_tag_x9y8"},
)
```

## 注意事项
- 与下拉单选（`FORM_SELECT_INPUT_SINGLE`）的区别：可以选择多个选项
- 同样需要 `dictionarySelectConfig` 绑定字典
- `dictionaryCode` 必须使用带后缀的实际编码（从 `dict_code_map` 获取）
- 可作为列表页查询条件和显示列

## 相关组件
- `FORM_SELECT_INPUT_SINGLE` — 下拉单选（只能选一个）
- `apaas-create-dict` — 创建数据字典
