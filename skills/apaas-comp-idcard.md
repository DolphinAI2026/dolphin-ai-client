# aPaaS Component: ID Card (身份证号)

## 组件类型
`FORM_IDCARD_INPUT` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_IDCARD_INPUT",
  "label": "身份证号",
  "modelField": "engineer_a1b2.idcard"
}
```

## 注意事项
- 自带身份证号格式验证
- 可作为列表页查询条件和显示列
- 需要在 skills.components 中增加其组件类型
