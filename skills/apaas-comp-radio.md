# aPaaS Component: Radio (单选框)

## 组件类型
`FORM_RADIO_INPUT` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_RADIO_INPUT",
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

## 注意事项
- 需要 `dictionarySelectConfig` 绑定字典
- `dictionaryCode` 必须使用带后缀的实际编码（从 `dict_code_map` 获取）
- 可作为列表页查询条件和显示列
- 需要在 skills.components 中增加其组件类型

## 相关组件
- `FORM_SELECT_INPUT_SINGLE` — 下拉单选（只能选一个）
- `FORM_SELECT_INPUT` - 下拉框
- `FORM_CHECKBOX_INPUT` - 复选框

## 相关技能
- `apaas-create-dict` — 创建数据字典
