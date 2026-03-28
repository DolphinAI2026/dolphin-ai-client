# aPaaS Query Model with Fields

## 用途
查询应用下的数据模型及其字段详情，用于获取已有模型的 modelCode、modelId、字段列表等信息

## API 端点
```
POST /xdap-app/dataModel/query/modelWithField
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
{
  "appId": "755484864311984128",
  "page": 1,
  "pageSize": 50
}
```

## 参数说明

### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 否 | 应用 ID，按应用过滤 |
| modelName | string | 否 | 模型名称，模糊搜索 |
| modelCode | string | 否 | 模型编码，模糊搜索 |
| accurateQuery | boolean | 否 | 是否按 modelCode 精确匹配 |
| datasourceId | string | 否 | 数据源 ID |
| page | integer | 否 | 页码 |
| pageSize | integer | 否 | 每页条数 |

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "total": 12,
  "table": [
    {
      "modelName": "通知与提醒",
      "modelCode": "notification_reminder_rfmz",
      "modelId": "758716638387240960",
      "modelType": "DATABASE",
      "generateType": "NEWCREATE",
      "interfaceType": "CUSTOM",
      "dataModelFields": [
        {
          "id": "758716638458544128",
          "fieldCode": "notification_id_rfmz",
          "fieldName": "通知编号",
          "fieldType": "STRING",
          "fieldStatus": "ENABLE",
          "modelCode": "notification_reminder_rfmz",
          "modelId": "758716638387240960",
          "maxLength": "500",
          "fieldTypeDisplay": "字符串",
          "databaseFieldType": "varchar"
        }
      ]
    }
  ]
}
```

### 响应字段说明

#### 模型层
| 字段 | 类型 | 说明 |
|------|------|------|
| modelName | string | 模型名称 |
| modelCode | string | 模型编码（带后缀的实际编码） |
| modelId | string | 模型 ID（追加字段时需要） |
| modelType | string | 模型类型，通常为 "DATABASE" |
| dataModelFields | array | 字段列表 |

#### 字段层（dataModelFields 数组元素）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 字段 ID |
| fieldCode | string | 字段编码 |
| fieldName | string | 字段名称 |
| fieldType | string | 字段类型：STRING, NUM, DATE, BIG_TEXT |
| fieldStatus | string | 字段状态：ENABLE / DISABLE |
| modelCode | string | 所属模型编码 |
| modelId | string | 所属模型 ID |
| maxLength | string | 最大长度（STRING 类型） |
| databaseFieldType | string | 数据库字段类型（如 varchar） |

## Python 调用示例

### 使用 APaaSClient
```python
from app.apaas_client import APaaSClient

async def query_models(client: APaaSClient, app_id: str):
    """查询应用下所有模型及其字段"""
    result = await client.request(
        "POST",
        "/xdap-app/dataModel/query/modelWithField",
        json={"appId": app_id, "page": 1, "pageSize": 200},
        app_id=app_id
    )

    models = result.get("table", [])
    print(f"共 {result.get('total', 0)} 个模型")
    for m in models:
        print(f"  {m['modelName']} ({m['modelCode']}) id={m['modelId']}")
        for f in m.get("dataModelFields", []):
            print(f"    - {f['fieldName']} ({f['fieldCode']}) type={f['fieldType']}")

    return models
```

### 按 modelCode 精确查询
```python
async def query_model_by_code(client: APaaSClient, app_id: str, model_code: str):
    """按 modelCode 精确查询单个模型"""
    result = await client.request(
        "POST",
        "/xdap-app/dataModel/query/modelWithField",
        json={
            "appId": app_id,
            "modelCode": model_code,
            "accurateQuery": True,
            "page": 1,
            "pageSize": 1
        },
        app_id=app_id
    )

    models = result.get("table", [])
    return models[0] if models else None
```

### 构建 code_map（用于表单创建）
```python
async def build_code_map_from_existing(client: APaaSClient, app_id: str):
    """从已有模型构建 code_map，供 transform_form_config 使用"""
    result = await client.request(
        "POST",
        "/xdap-app/dataModel/query/modelWithField",
        json={"appId": app_id, "page": 1, "pageSize": 200},
        app_id=app_id
    )

    code_map = {}
    for m in result.get("table", []):
        code_map[m["modelCode"]] = m["modelCode"]  # 已有模型无需映射

    return code_map
```

## 使用场景

### 场景 1: 在已有应用中创建新表单，引用已有模型
```python
# 1. 查询已有模型
models = await query_models(client, app_id)

# 2. 找到要引用的模型
customer_model = next(m for m in models if "customer" in m["modelCode"])
model_code = customer_model["modelCode"]  # 如 customer_a1b2

# 3. 在新表单中使用数据选择器引用已有模型
component = {
    "componentType": "FORM_DATA_SELECTOR_SINGLE",
    "label": "关联客户",
    "modelField": f"{new_model_code}.customer_ref",
    "dataSelectorConfig": {
        "type": "LOV_CHOOSE",
        "otherModelCode": model_code,
        "otherFieldCode": "customer_name"
    }
}
```

### 场景 2: 检查模型是否已存在（避免重复创建）
```python
existing = await query_model_by_code(client, app_id, "customer_a1b2")
if existing:
    print(f"模型已存在: {existing['modelName']}")
else:
    # 创建新模型
    ...
```

## 注意事项

### 返回的编码即实际编码
- 返回的 `modelCode` 和 `fieldCode` 是平台中的**实际编码**（已包含后缀）
- 可以直接用于表单的 `modelField`（如 `customer_a1b2.customer_name`）
- 无需再通过 `code_map` 映射

### modelId 的获取
- 模型层返回 `modelId` 字段
- 字段层也返回 `modelId` 字段（值相同）
- 追加字段（`/modelField/add`）时需要此 ID

### 分页
- 默认不分页，建议传 `page: 1, pageSize: 200` 确保获取所有模型
- 返回的 `total` 表示总数

### 备选 API
- `POST /dataModel/query/list` — 只返回模型列表（不含字段），返回的 `id` 即 modelId
- `GET /dataModel/query/detail?id={modelId}` — 按 ID 查询单个模型详情

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 401 | 未授权 | token 过期 | 重新登录 |
| 500 | 时间戳验证失败 | xdaptimestamp 超出范围 | 使用当前时间戳 |

## 相关 Skills
- `apaas-create-model` — 创建数据模型
- `apaas-add-field` — 给已有模型追加字段
- `apaas-create-form` — 创建表单配置（使用查询到的 modelCode）
