# aPaaS Component: Son Table (子表)

## 组件类型
`FORM_WIDGET_SON_TABLE`

## 数据模型字段类型
不生成字段（子表是独立的数据模型）

## 用途
子表组件，用于一对多关系（如订单明细、费用明细、联系人列表）

## 组件配置
```json
{
  "componentType": "FORM_WIDGET_SON_TABLE",
  "label": "费用明细",
  "tableColumn": [
    {
      "componentType": "FORM_SELECT_INPUT_SINGLE",
      "label": "费用类型",
      "modelField": "order_fee_a1b2.fee_type",
      "dictionarySelectConfig": {
        "dictionaryCode": "fee_type_x9y8",
        "dictionarySelectOptions": [...]
      }
    },
    {
      "componentType": "FORM_MONEY_INPUT",
      "label": "金额",
      "modelField": "order_fee_a1b2.amount"
    }
  ]
}
```

## 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| componentType | string | 是 | 固定值 "FORM_WIDGET_SON_TABLE" |
| label | string | 是 | 子表标签 |
| tableColumn | array | 是 | 子表列配置数组 |

### tableColumn 数组元素
子表列是普通的表单组件，支持所有组件类型（除了子表本身）。每个列的 `modelField` 必须使用**子表模型的编码**。

## 在 formConfig 中的使用
```json
{
  "formName": "工单",
  "formCode": "form_a1b2c3",
  "allModelCodes": ["service_order_x9y8", "order_fee_a1b2"],  // 包含子表模型
  "formComponents": [
    {
      "componentType": "FORM_DOCUMENT_NUMBER",
      "label": "工单号",
      "modelField": "service_order_x9y8.order_no"
    },
    {
      "componentType": "FORM_DATA_SELECTOR_SINGLE",
      "label": "客户",
      "modelField": "service_order_x9y8.customer_ref",
      "dataSelectorConfig": {
        "type": "LOV_CHOOSE",
        "otherModelCode": "customer_m5n7",
        "otherFieldCode": "customer_name"
      }
    },
    {
      "componentType": "FORM_WIDGET_SON_TABLE",
      "label": "费用明细",
      "tableColumn": [
        {
          "componentType": "FORM_SELECT_INPUT_SINGLE",
          "label": "费用类型",
          "modelField": "order_fee_a1b2.fee_type",
          "dictionarySelectConfig": {
            "dictionaryCode": "fee_type_x9y8",
            "dictionarySelectOptions": [
              {"id": "labor_x9y8", "label": "人工费"},
              {"id": "parts_x9y8", "label": "配件费"}
            ]
          }
        },
        {
          "componentType": "FORM_MONEY_INPUT",
          "label": "金额",
          "modelField": "order_fee_a1b2.amount"
        },
        {
          "componentType": "FORM_TEXTAREA_INPUT",
          "label": "备注",
          "modelField": "order_fee_a1b2.remark"
        }
      ]
    }
  ],
  "listPageView": {
    "queryConditions": ["service_order_x9y8.order_no"],
    "queryList": ["service_order_x9y8.order_no", "service_order_x9y8.customer_ref"]
    // 注意：子表字段不加入 queryConditions 和 queryList
  }
}
```

## Python 生成示例

### 使用 config_transformer
```python
def build_son_table_component(
    field: dict,
    code_map: dict,
    dicts: list,
    dict_code_map: dict
):
    """从预览字段定义生成子表组件"""
    sub_code = field.get("sub_code") or "sub_table"
    sub_model_code = code_map.get(sub_code, sub_code)

    sub_cols = []
    for sf in field.get("sub_fields", []):
        # 为每个子表字段生成组件
        sf_code = sf.get("code", "field")
        sub_comp = _build_component(sf, sub_model_code, sf_code, dicts, code_map, dict_code_map)
        sub_cols.append(sub_comp)

    return {
        "componentType": "FORM_WIDGET_SON_TABLE",
        "label": field["name"],
        "tableColumn": sub_cols
    }
```

### 完整示例（含数据模型创建）
```python
from app.config_transformer import transform_models, transform_form_config
from app.apaas_client import APaaSClient

async def create_form_with_subtable(client: APaaSClient, app_id: str):
    # 1. 定义模型（包含子表）
    models = [
        {
            "name": "工单",
            "code": "service_order",
            "fields": [
                {"name": "工单号", "code": "order_no", "type": "单据号"},
                {"name": "客户", "code": "customer_ref", "type": "数据单选",
                 "ref": {"model": "customer", "field": "customer_name"}},
                # 子表字段
                {
                    "name": "费用明细",
                    "type": "子表",
                    "sub_code": "order_fee",
                    "sub_fields": [
                        {"name": "费用类型", "code": "fee_type", "type": "下拉单选", "dict": "fee_type"},
                        {"name": "金额", "code": "amount", "type": "金额"},
                        {"name": "备注", "code": "remark", "type": "多行输入"}
                    ]
                }
            ]
        }
    ]

    # 2. 创建数据模型（会自动创建主表和子表两个模型）
    model_payload, code_map = transform_models(app_id, models)
    model_results = await client.create_models(app_id, model_payload)
    # code_map: {"service_order": "service_order_a1b2", "order_fee": "order_fee_a1b2"}

    # 3. 创建字典
    dicts = [
        {
            "name": "费用类型",
            "code": "fee_type",
            "options": [
                {"name": "人工费", "code": "labor"},
                {"name": "配件费", "code": "parts"}
            ]
        }
    ]
    dict_payload, dict_code_map = transform_dicts(app_id, dicts)
    await client.create_dicts(app_id, dict_payload)

    # 4. 创建表单配置
    form_payload = transform_form_config(
        models, dicts, model_results, model_payload, code_map, dict_code_map
    )
    await client.create_form_config(app_id, form_payload)
```

## 注意事项

### 子表模型创建
- 子表需要**单独创建一个数据模型**
- 子表模型的 `modelCode` 通常为 `{主表code}_sub` 或自定义的 `sub_code`
- `transform_models` 会自动处理子表模型的创建

### allModelCodes 必须包含子表
```json
{
  "allModelCodes": ["service_order_a1b2", "order_fee_a1b2"]
  // 必须包含主表和所有子表模型
}
```

### tableColumn 中的 modelField
- 所有子表列的 `modelField` 必须使用**子表模型的编码**
- 错误示例：`"modelField": "service_order_a1b2.fee_type"`（使用了主表编码）
- 正确示例：`"modelField": "order_fee_a1b2.fee_type"`（使用子表编码）

### 子表字段不加入列表页
- 子表字段**不能**加入 `queryConditions`
- 子表字段**不能**加入 `queryList`
- 只有主表字段可以在列表页显示

### 外键自动创建
- 系统会自动在子表中创建 `tab_doc_id` 字段
- `tab_doc_id` 是外键，关联主表记录
- 不需要手动创建此字段

### 子表组件支持的列类型
子表列可以使用以下组件类型：
- ✅ FORM_TEXT_INPUT
- ✅ FORM_TEXTAREA_INPUT
- ✅ FORM_NUMBER_INPUT
- ✅ FORM_MONEY_INPUT
- ✅ FORM_PHONE_INPUT
- ✅ FORM_EMAIL_INPUT
- ✅ FORM_DATEPICK_INPUT
- ✅ FORM_SELECT_INPUT_SINGLE
- ✅ FORM_SELECT_INPUT
- ✅ FORM_DATA_SELECTOR_SINGLE
- ✅ FORM_FILE_UPLOAD
- ✅ FORM_SWITCH_SELECT
- ❌ FORM_WIDGET_SON_TABLE（子表不能嵌套）

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 12022 | MAINMODEL_NOTIN_SONTABLE | 子表列使用了主表字段 | 确保 tableColumn 中的 modelField 使用子表模型编码 |
| - | 模型不存在 | allModelCodes 缺少子表模型 | 在 allModelCodes 中添加子表模型编码 |
| - | 字段不存在 | 子表字段未在子表模型中创建 | 确保子表字段已在子表模型中创建 |

## 使用场景示例

### 场景 1: 订单明细
```json
{
  "componentType": "FORM_WIDGET_SON_TABLE",
  "label": "订单明细",
  "tableColumn": [
    {
      "componentType": "FORM_DATA_SELECTOR_SINGLE",
      "label": "产品",
      "modelField": "order_item_a1b2.product_ref",
      "dataSelectorConfig": {
        "type": "LOV_CHOOSE",
        "otherModelCode": "product_x9y8",
        "otherFieldCode": "product_name"
      }
    },
    {
      "componentType": "FORM_NUMBER_INPUT",
      "label": "数量",
      "modelField": "order_item_a1b2.quantity"
    },
    {
      "componentType": "FORM_MONEY_INPUT",
      "label": "单价",
      "modelField": "order_item_a1b2.unit_price"
    }
  ]
}
```

### 场景 2: 联系人列表
```json
{
  "componentType": "FORM_WIDGET_SON_TABLE",
  "label": "联系人",
  "tableColumn": [
    {
      "componentType": "FORM_TEXT_INPUT",
      "label": "姓名",
      "modelField": "customer_contact_a1b2.contact_name"
    },
    {
      "componentType": "FORM_PHONE_INPUT",
      "label": "电话",
      "modelField": "customer_contact_a1b2.phone"
    },
    {
      "componentType": "FORM_EMAIL_INPUT",
      "label": "邮箱",
      "modelField": "customer_contact_a1b2.email"
    }
  ]
}
```

## 相关 Skills
- `apaas-create-model` — 创建数据模型（含子表模型）
- `apaas-create-form` — 创建表单配置
- 所有 `apaas-comp-*` — 子表列可以使用的组件类型
