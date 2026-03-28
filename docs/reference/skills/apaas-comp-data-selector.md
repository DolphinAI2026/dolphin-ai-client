# aPaaS Component: Data Selector Single (数据单选)

## 组件类型
`FORM_DATA_SELECTOR_SINGLE`

## 数据模型字段类型
`STRING`

## 用途
数据选择器，关联其他模型的数据，用于外键关系（如订单关联客户、设备关联站点）

## 组件配置
```json
{
  "componentType": "FORM_DATA_SELECTOR_SINGLE",
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
| componentType | string | 是 | 固定值 "FORM_DATA_SELECTOR_SINGLE" |
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
      "componentType": "FORM_DATA_SELECTOR_SINGLE",
      "label": "所属客户",
      "modelField": "device_x9y8.customer_ref",
      "dataSelectorConfig": {
        "type": "LOV_CHOOSE",
        "otherModelCode": "customer_a1b2",
        "otherFieldCode": "customer_name"
      }
    },
    {
      "componentType": "FORM_DATA_SELECTOR_SINGLE",
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

## Python 生成示例

### 使用 config_transformer
```python
def build_data_selector_component(
    field: dict,
    model_code: str,
    field_code: str,
    code_map: dict
):
    """从预览字段定义生成数据选择器组件"""
    component = {
        "componentType": "FORM_DATA_SELECTOR_SINGLE",
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}"
    }

    # 数据选择器配置
    if field.get("ref"):
        ref = field["ref"]
        if isinstance(ref, dict):
            ref_model = ref.get("model", "")
            ref_field = ref.get("field", "")
        else:
            # 兼容旧格式：ref 为字符串（模型名）
            ref_model = str(ref)
            ref_field = ""

        # 如果 code_map 中有带后缀的版本，使用它
        resolved_model = code_map.get(ref_model, ref_model)

        component["dataSelectorConfig"] = {
            "type": "LOV_CHOOSE",
            "otherModelCode": resolved_model,
            "otherFieldCode": ref_field
        }

    return component
```

### 直接构建示例
```python
def create_data_selector_direct(model_code, field_code, label, ref_model_code, ref_field_code):
    return {
        "componentType": "FORM_DATA_SELECTOR_SINGLE",
        "label": label,
        "modelField": f"{model_code}.{field_code}",
        "dataSelectorConfig": {
            "type": "LOV_CHOOSE",
            "otherModelCode": ref_model_code,
            "otherFieldCode": ref_field_code
        }
    }

# 使用
component = create_data_selector_direct(
    "device_a1b2",
    "customer_ref",
    "所属客户",
    "customer_x9y8",  # 关联的客户模型（带后缀）
    "customer_name"   # 显示客户名称字段
)
```

## 注意事项

### type 必须是 LOV_CHOOSE
- **错误**: `"type": "DATA_SELECTOR"`
- **正确**: `"type": "LOV_CHOOSE"`
- 使用错误的 type 会导致数据选择器无法正常工作

### 模型编码映射（重要！）
- `otherModelCode` 必须使用**带后缀的实际模型编码**
- 从 `code_map` 获取映射：
  ```python
  # 字段定义中引用原始 code
  field = {"type": "数据单选", "ref": {"model": "customer", "field": "customer_name"}}

  # 组件中使用映射后的 code
  resolved_model = code_map.get("customer")  # customer_a1b2
  ```

### otherFieldCode 说明
- 指定关联模型的哪个字段作为显示值
- 通常选择名称字段（如 `customer_name`, `site_name`）
- 该字段必须在关联模型中存在

### 字段类型
- 数据模型字段类型必须是 `STRING`
- 存储的是关联记录的 ID

### 列表页支持
- 可以作为查询条件（queryConditions）
- 可以作为显示列（queryList）
- 列表页会显示关联记录的 otherFieldCode 值

### ref 字段格式
预览格式中的 ref 字段支持两种格式：

**格式 1: 对象（推荐）**
```json
{
  "type": "数据单选",
  "ref": {
    "model": "customer",
    "field": "customer_name"
  }
}
```

**格式 2: 字符串（兼容）**
```json
{
  "type": "数据单选",
  "ref": "customer"
}
```

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
  "componentType": "FORM_DATA_SELECTOR_SINGLE",
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
  "componentType": "FORM_DATA_SELECTOR_SINGLE",
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
  "componentType": "FORM_DATA_SELECTOR_SINGLE",
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
- `FORM_SELECT_INPUT_SINGLE` — 下拉单选（绑定字典，不是关联模型）
- `apaas-create-model` — 创建数据模型
