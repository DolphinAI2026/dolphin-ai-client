# aPaaS Component: Department Select (部门选择)

## 组件类型
`FORM_DEPARTMENT_SELECT` | 字段类型: `STRING`

## 组件配置
```json
{
  "componentType": "FORM_DEPARTMENT_SELECT",
  "label": "部门",
  "modelField": "service_order_a1b2.department"
}
```

## 注意事项
- 从平台部门列表中选择部门
- 存储部门 ID（STRING 类型）
- 可作为列表页查询条件和显示列
- 需要在 skills.components 中增加其组件类型
