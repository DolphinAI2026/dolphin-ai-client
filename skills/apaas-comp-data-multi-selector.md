# aPaaS Component: Data Selector (数据选择)

## 组件类型
`FORM_DATA_SELECTOR`

## 数据模型字段类型
`STRING`

## 用途
数据选择器，关联其他模型的数据，用于外键关系（如订单关联客户、设备关联站点）

## 组件配置
```json
{
  "componentType": "FORM_DATA_SELECTOR",
  "label": "所属客户",
  "modelField": "device_a1b2.customer_ref",
  "dataSelectorConfig": {
    "type": "LOV_CHOOSE",
    "otherModelCode": "customer_x9y8",
    "otherFieldCode": "customer_name"
  }
}
```

## 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| componentType | string | 是 | 固定值 "FORM_DATA_SELECTOR" |
| label | string | 是 | 字段标签 |
| modelField | string | 是 | 模型字段，格式 `{modelCode}.{fieldCode}` |
| dataSelectorConfig | object | 是 | 数据选择器配置 |

### dataSelectorConfig 对象
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | string | 是 | 固定值 "LOV_CHOOSE"（**不是** "DATA_SELECTOR"） |
| otherModelCode | string | 是 | 关联的模型编码（**必须是带后缀的实际编码**） |
| otherFieldCode | string | 是 | 关联模型的显示字段编码 |

## 在 formConfig 中的使用
```json
{
  "formName": "设备",
  "formCode": "form_a1b2c3",
  "allModelCodes": ["device_x9y8"],
  "formComponents": [
    {
      "componentType": "FORM_TEXT_INPUT",
      "label": "设备名称",
      "modelField": "device_x9y8.device_name"
    },
    {
      "componentType": "FORM_DATA_SELECTOR",
      "label": "所属客户",
      "modelField": "device_x9y8.customer_ref",
      "dataSelectorConfig": {
        "type": "LOV_CHOOSE",
        "otherModelCode": "customer_a1b2",
        "otherFieldCode": "customer_name"
      }
    },
    {
      "componentType": "FORM_DATA_SELECTOR",
      "label": "所属站点",
      "modelField": "device_x9y8.site_ref",
      "dataSelectorConfig": {
        "type": "LOV_CHOOSE",
        "otherModelCode": "site_a1b2",
        "otherFieldCode": "site_name"
      }
    }
  ],
  "listPageView": {
    "queryConditions": ["device_x9y8.device_name", "device_x9y8.customer_ref"],
    "queryList": ["device_x9y8.device_name", "device_x9y8.customer_ref", "device_x9y8.site_ref"]
  }
}
```


## 注意事项

### type 必须是 LOV_CHOOSE
- **错误**: `"type": "DATA_SELECTOR"`
- **正确**: `"type": "LOV_CHOOSE"`
- 使用错误的 type 会导致数据选择器无法正常工作

### 模型编码映射（重要！）
- `otherModelCode` 必须使用**带后缀的实际模型编码**
- 从 `code_map` 获取映射：

### otherFieldCode 说明
- 指定关联模型的哪个字段作为显示值
- 通常选择名称字段（如 `customer_name`, `site_name`）
- 该字段必须在关联模型中存在

### 字段类型
- 数据模型字段类型必须是 `STRING`
- 存储的是关联记录的 ID集合

### 列表页支持
- 可以作为查询条件（queryConditions）
- 可以作为显示列（queryList）
- 列表页会显示关联记录的 otherFieldCode 值


## 常见错误

| 错误 | 原因 | 解决方法 |
|------|------|---------|
| 数据选择器不工作 | type 使用了 "DATA_SELECTOR" | 改为 "LOV_CHOOSE" |
| 关联模型不存在 | otherModelCode 不正确 | 使用 code_map 获取正确的编码 |
| 显示字段不存在 | otherFieldCode 在关联模型中不存在 | 确保字段已在关联模型中创建 |
| 无法选择数据 | 关联模型没有数据 | 先在关联模型中创建数据 |

## 使用场景示例

### 场景 1: 订单关联客户
```json
{
  "componentType": "FORM_DATA_SELECTOR",
  "label": "客户",
  "modelField": "service_order_a1b2.customer_ref",
  "dataSelectorConfig": {
    "type": "LOV_CHOOSE",
    "otherModelCode": "customer_x9y8",
    "otherFieldCode": "customer_name"
  }
}
```

### 场景 2: 设备关联站点
```json
{
  "componentType": "FORM_DATA_SELECTOR",
  "label": "安装站点",
  "modelField": "device_a1b2.site_ref",
  "dataSelectorConfig": {
    "type": "LOV_CHOOSE",
    "otherModelCode": "site_x9y8",
    "otherFieldCode": "site_name"
  }
}
```

### 场景 3: 工单关联工程师
```json
{
  "componentType": "FORM_DATA_SELECTOR",
  "label": "负责工程师",
  "modelField": "service_order_a1b2.engineer_ref",
  "dataSelectorConfig": {
    "type": "LOV_CHOOSE",
    "otherModelCode": "engineer_x9y8",
    "otherFieldCode": "eng_name"
  }
}
```

## 相关组件
- `apaas-create-model` — 创建数据模型
