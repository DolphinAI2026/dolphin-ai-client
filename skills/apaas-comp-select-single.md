# aPaaS Component: Select Single (下拉单选)

## 组件类型
`FORM_SELECT_INPUT_SINGLE`

## 数据模型字段类型
`STRING`

## 用途
下拉单选框，绑定数据字典，用于状态、类型、等级等枚举字段

## 组件配置
```json
{
  "componentType": "FORM_SELECT_INPUT_SINGLE",
  "label": "客户等级",
  "modelField": "customer_a1b2.customer_level",
  "dictionarySelectConfig": {
    "dictionaryCode": "customer_level_x9y8",
    "dictionarySelectOptions": [
      {"id": "vip_x9y8", "label": "VIP"},
      {"id": "normal_x9y8", "label": "普通"},
      {"id": "strategic_x9y8", "label": "战略客户"}
    ]
  }
}
```

## 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| componentType | string | 是 | 固定值 "FORM_SELECT_INPUT_SINGLE" |
| label | string | 是 | 字段标签 |
| modelField | string | 是 | 模型字段，格式 `{modelCode}.{fieldCode}` |
| dictionarySelectConfig | object | 是 | 字典绑定配置 |

### dictionarySelectConfig 对象
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dictionaryCode | string | 是 | 字典编码（**必须是带后缀的实际编码**） |
| dictionarySelectOptions | array | 是 | 字典选项数组 |

### dictionarySelectOptions 数组元素
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | 是 | 选项编码（**必须是带后缀的实际编码**） |
| label | string | 是 | 选项显示名称 |

## 在 formConfig 中的使用
```json
{
  "formName": "客户",
  "formCode": "form_a1b2c3",
  "allModelCodes": ["customer_x9y8"],
  "formComponents": [
    {
      "componentType": "FORM_TEXT_INPUT",
      "label": "客户名称",
      "modelField": "customer_x9y8.customer_name"
    },
    {
      "componentType": "FORM_SELECT_INPUT_SINGLE",
      "label": "客户等级",
      "modelField": "customer_x9y8.customer_level",
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
    "queryConditions": ["customer_x9y8.customer_name", "customer_x9y8.customer_level"],
    "queryList": ["customer_x9y8.customer_name", "customer_x9y8.customer_level"]
  }
}
```

## Python 生成示例

### 使用 config_transformer
```python
from app.config_transformer import _build_component

def build_select_single_component(
    field: dict,
    model_code: str,
    field_code: str,
    dicts: list,
    dict_code_map: dict
):
    """从预览字段定义生成下拉单选组件"""
    component = {
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": field["name"],
        "modelField": f"{model_code}.{field_code}"
    }

    # 字典绑定
    if field.get("dict"):
        raw_dict_code = field["dict"]
        # 使用映射后的字典 code（带后缀）
        actual_dict_code = dict_code_map.get(raw_dict_code, raw_dict_code)

        # 从 dicts 列表中查找匹配的字典定义
        dict_def = next((d for d in dicts if d.get("code") == raw_dict_code), None)
        options_list = []
        if dict_def:
            for i, opt in enumerate(dict_def.get("options", [])):
                if isinstance(opt, str):
                    options_list.append({"id": f"{raw_dict_code}_{i+1}", "label": opt})
                elif isinstance(opt, dict):
                    options_list.append({
                        "id": opt.get("code", opt.get("id", f"{raw_dict_code}_{i+1}")),
                        "label": opt.get("name", opt.get("label", str(opt)))
                    })

        component["dictionarySelectConfig"] = {
            "dictionaryCode": actual_dict_code,
            "dictionarySelectOptions": options_list
        }

    return component
```

### 直接构建示例
```python
def create_select_single_direct(model_code, field_code, label, dict_code, options):
    return {
        "componentType": "FORM_SELECT_INPUT_SINGLE",
        "label": label,
        "modelField": f"{model_code}.{field_code}",
        "dictionarySelectConfig": {
            "dictionaryCode": dict_code,
            "dictionarySelectOptions": [
                {"id": opt["code"], "label": opt["name"]}
                for opt in options
            ]
        }
    }

# 使用
component = create_select_single_direct(
    "customer_a1b2",
    "customer_level",
    "客户等级",
    "customer_level_a1b2",
    [
        {"code": "vip_a1b2", "name": "VIP"},
        {"code": "normal_a1b2", "name": "普通"}
    ]
)
```

## 注意事项

### 字典编码映射（重要！）
- `dictionaryCode` 必须使用**带后缀的实际字典编码**
- 从 `dict_code_map` 获取映射：
  ```python
  # 字段定义中引用原始 code
  field = {"type": "下拉单选", "dict": "customer_level"}

  # 组件中使用映射后的 code
  actual_dict_code = dict_code_map.get("customer_level")  # customer_level_a1b2
  ```

### 选项编码映射
- `dictionarySelectOptions` 中的 `id` 也必须是**带后缀的选项编码**
- 必须与 `transform_dicts` 生成的选项编码一致

### 选项列表必填
- `dictionarySelectOptions` 不能为空数组
- 必须包含所有字典选项
- 如果字典未定义，组件会无法正常工作

### 字段类型
- 数据模型字段类型必须是 `STRING`
- 存储的是选项的 `id`（optionCode）

### 列表页支持
- 可以作为查询条件（queryConditions）
- 可以作为显示列（queryList）
- 列表页会显示选项的 label，不是 id

## 常见错误

| 错误 | 原因 | 解决方法 |
|------|------|---------|
| 字典选项不显示 | dictionaryCode 不匹配 | 使用 dict_code_map 获取正确的编码 |
| 选项 ID 不匹配 | dictionarySelectOptions 的 id 不正确 | 确保与 transform_dicts 生成的 optionCode 一致 |
| JSON parse error | dictionarySelectOptions 格式错误 | 必须是数组 `[]`，不能是对象 `{}` |

## 相关组件
- `FORM_SELECT_INPUT` — 下拉多选（可选多个选项）
- `apaas-create-dict` — 创建数据字典
