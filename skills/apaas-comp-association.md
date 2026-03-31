# aPaaS Component: Association (关联表单)

## 组件类型
`FORM_ASSOCIATION` | 字段类型: 无

## 组件配置
```json
{
  "componentType": "FORM_ASSOCIATION",
  "label": "技能标签",
  "formAssociationConfig": {
    "originFieldCode": "sourceField",
    "targetModelCode": "targetModel",
    "targetFieldCode": "targetField"
  }
}
```

## formAssociationConfig 关联配置参数

| 参数 | 类型 | 是否必填 | 描述 |
| --- | --- | --- | --- |
| originFieldCode | string | 是 | 关联的本表字段编码 |
| targetModelCode | string | 是 | 关联的它表的模型编码 |
| targetFieldCode | string | 是 | 关联的它表模型的字段编码 |

## 注意事项
- 需要 `formAssociationConfig` 绑定关联配置
