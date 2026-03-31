# aPaaS Create Form Configuration

## 用途
在应用下批量创建表单配置（包含表单组件、列表页配置、模型绑定）

## API 端点
```
POST /xdap-app/common/resource/formConfig
```

## 请求头
```json
{
  "Content-Type": "application/json",
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>",
  "appid": "<app_id>"
}
```

## 请求格式
```json
[
  {
    "formName": "客户",
    "formCode": "form_a1b2c3",
    "allModelCodes": ["customer_x9y8"],
    "formComponents": [
      {
        "componentType": "FORM_TEXT_INPUT",
        "label": "客户名称",
        "modelField": "customer_x9y8.customer_name"
      }
    ],
    "listPageView": {
      "queryConditions": ["customer_x9y8.customer_name"],
      "queryList": ["customer_x9y8.customer_name", "customer_x9y8.contact_phone"]
    }
  }
]
```

## 参数说明

### 表单对象
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| formName | string | 是 | 表单名称（中文） |
| formCode | string | 是 | 表单编码，建议格式 `form_{随机后缀}` |
| allModelCodes | array | 是 | 关联的所有模型编码（主表 + 子表） |
| formComponents | array | 是 | 表单组件数组 |
| listPageView | object | 是 | 列表页配置 |

### formComponents 数组元素（基础字段）
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| componentType | string | 是 | 组件类型（见组件类型表） |
| label | string | 是 | 字段标签（显示名称） |
| modelField | string | 是 | 模型字段，格式 `{modelCode}.{fieldCode}` |

### listPageView 对象
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| queryConditions | array | 是 | 查询条件字段（最多 4 个） |
| queryList | array | 是 | 列表显示字段（最多 6 个） |

## 组件类型表

| 组件类型 | 说明 | 对应 Skill |
|---------|------|-----------|
| FORM_DOCUMENT_NUMBER | 单据号 | apaas-comp-doc-number |
| FORM_TEXT_INPUT | 单行输入 | apaas-comp-text |
| FORM_TEXTAREA_INPUT | 多行输入 | apaas-comp-textarea |
| FORM_NUMBER_INPUT | 数字输入 | apaas-comp-number |
| FORM_MONEY_INPUT | 金额 | apaas-comp-money |
| FORM_PHONE_INPUT | 手机号码 | apaas-comp-phone |
| FORM_EMAIL_INPUT | 电子邮箱 | apaas-comp-email |
| FORM_DATEPICK_INPUT | 日期时间 | apaas-comp-date |
| FORM_SELECT_INPUT_SINGLE | 下拉单选 | apaas-comp-select-single |
| FORM_SELECT_INPUT | 下拉多选 | apaas-comp-select-multi |
| FORM_DATA_SELECTOR_SINGLE | 数据单选 | apaas-comp-data-selector |
| FORM_FILE_UPLOAD | 附件上传 | apaas-comp-file |
| FORM_SWITCH_SELECT | 开关 | apaas-comp-switch |
| FORM_PEOPLE_SELECT | 人员选择 | apaas-comp-people |
| FORM_WIDGET_LOCATION | 地理位置 | apaas-comp-location |
| FORM_WIDGET_SON_TABLE | 子表 | apaas-comp-son-table |
| FORM_DEPARTMENT_SELECT | 部门选择 | apaas-comp-department |
| FORM_IDCARD_INPUT | 身份证号 | apaas-comp-idcard |
| FORM_RADIO_INPUT | 单选框 | apaas-comp-radio |
| FORM_CHECKBOX_INPUT | 复选框 | apaas-comp-checkbox |
| FORM_RICH_TEXT | 富文本框 | apaas-comp-rich |
| FORM_WIDGET_AREA | 区域选择 | apaas-comp-area |
| FORM_HYPERLINK_INPUT | 超链接 | apaas-comp-hyperlink |
| FORM_DATA_SELECTOR | 数据选择 | apaas-comp-data-multi-selector |
| FORM_ASSOCIATION | 关联表单 | apaas-comp-association |

## 响应格式
```json
{
  "code": "ok",
  "data": [
    {
      "id": "form_id_1",
      "formCode": "form_a1b2c3",
      "formName": "客户",
      ...
    }
  ]
}
```

## Python 调用示例

### 使用 config_transformer
```python
from app.config_transformer import transform_form_config
from app.apaas_client import APaaSClient

async def create_forms_example(
    client: APaaSClient,
    app_id: str,
    models: list,
    dicts: list,
    model_results: list,
    model_payload: dict,
    code_map: dict,
    dict_code_map: dict
):
    # 转换为 API 格式
    form_payload = transform_form_config(
        models,
        dicts,
        model_results,
        model_payload,
        code_map,
        dict_code_map
    )

    # 调用 API
    result = await client.create_form_config(app_id, form_payload)

    print(f"创建了 {len(result)} 个表单")
    return result
```

### 完整示例（含字典绑定和数据选择器）
```python
async def create_form_with_dict_and_ref(client, app_id):
    # 假设已创建模型和字典
    code_map = {"customer": "customer_a1b2"}
    dict_code_map = {"customer_level": "customer_level_a1b2"}

    form_payload = [
        {
            "formName": "客户",
            "formCode": "form_x9y8z7",
            "allModelCodes": ["customer_a1b2"],
            "formComponents": [
                {
                    "componentType": "FORM_TEXT_INPUT",
                    "label": "客户名称",
                    "modelField": "customer_a1b2.customer_name"
                },
                {
                    "componentType": "FORM_PHONE_INPUT",
                    "label": "联系电话",
                    "modelField": "customer_a1b2.contact_phone"
                },
                {
                    "componentType": "FORM_SELECT_INPUT_SINGLE",
                    "label": "客户等级",
                    "modelField": "customer_a1b2.customer_level",
                    "dictionarySelectConfig": {
                        "dictionaryCode": "customer_level_a1b2",
                        "dictionarySelectOptions": [
                            {"id": "vip_a1b2", "label": "VIP"},
                            {"id": "normal_a1b2", "label": "普通"}
                        ]
                    }
                }
            ],
            "listPageView": {
                "queryConditions": [
                    "customer_a1b2.customer_name",
                    "customer_a1b2.customer_level"
                ],
                "queryList": [
                    "customer_a1b2.customer_name",
                    "customer_a1b2.contact_phone",
                    "customer_a1b2.customer_level"
                ]
            }
        }
    ]

    await client.create_form_config(app_id, form_payload)
```

### 子表表单示例
```python
async def create_form_with_subtable(client, app_id):
    code_map = {
        "service_order": "service_order_a1b2",
        "order_fee": "order_fee_a1b2"  # 子表模型
    }

    form_payload = [
        {
            "formName": "工单",
            "formCode": "form_x9y8z7",
            "allModelCodes": ["service_order_a1b2", "order_fee_a1b2"],  # 包含子表
            "formComponents": [
                {
                    "componentType": "FORM_DOCUMENT_NUMBER",
                    "label": "工单号",
                    "modelField": "service_order_a1b2.order_no"
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
                                "dictionaryCode": "fee_type_a1b2",
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
            ],
            "listPageView": {
                "queryConditions": ["service_order_a1b2.order_no"],
                "queryList": ["service_order_a1b2.order_no"]
            }
        }
    ]

    await client.create_form_config(app_id, form_payload)
```

## 注意事项

### formCode 编码规则
- 建议格式：`form_{6位随机字符}`
- 示例：`form_a1b2c3`
- 生成方式：
  ```python
  import random, string
  form_code = f"form_{''.join(random.choices(string.ascii_lowercase + string.digits, k=6))}"
  ```

### modelField 格式
- 必须是 `{modelCode}.{fieldCode}` 格式
- modelCode 必须是**带后缀的实际模型编码**（从 model_results 或 code_map 获取）
- 错误示例：`customer.name`（应该是 `customer_a1b2.name`）

### allModelCodes 数组
- 必须包含表单中所有用到的模型编码
- 主表 + 所有子表模型
- 示例：`["customer_a1b2", "customer_contact_a1b2"]`

### listPageView 字段选择
- **queryConditions**: 列表页的查询条件（搜索框），最多 4 个
- **queryList**: 列表页的显示列，最多 6 个
- 排除以下字段类型：
  - 附件上传（FORM_FILE_UPLOAD）
  - 多行输入（FORM_TEXTAREA_INPUT）
  - 子表（FORM_WIDGET_SON_TABLE）
- 自动选择策略：
  ```python
  listable_count = 0
  for field in fields:
      if field_type not in ('附件上传', '多行输入', '子表'):
          if listable_count < 4:
              query_conditions.append(model_field)
          if listable_count < 6:
              query_list.append(model_field)
          listable_count += 1
  ```

### 字典绑定注意事项
- 必须使用**带后缀的字典编码**（从 dict_code_map 获取）
- `dictionarySelectOptions` 必须包含所有选项（id + label）
- 选项的 id 也必须是**带后缀的选项编码**

### 数据选择器注意事项
- `dataSelectorConfig.type` 必须是 `"LOV_CHOOSE"`（不是 `"DATA_SELECTOR"`）
- `otherModelCode` 必须是**带后缀的模型编码**
- `otherFieldCode` 是关联模型的显示字段编码

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 12022 | 此表单没有数据模型字段 | modelField 格式错误或 allModelCodes 缺失 | 检查 modelField 格式和 allModelCodes |
| 4168 | 表单已存在 | formCode 重复 | 使用随机 formCode |
| - | 字段不存在 | modelField 中的 fieldCode 不存在 | 确保字段已在模型中创建 |
| - | 模型不存在 | modelField 中的 modelCode 不存在 | 确保模型已创建且使用正确的 code |

## 相关 Skills
- `apaas-create-app` — 创建应用（获取 appId）
- `apaas-create-model` — 创建数据模型（获取 modelCode）
- `apaas-create-dict` — 创建数据字典（获取 dictionaryCode）
- `apaas-comp-*` — 各种表单组件的详细配置
