# aPaaS Add Model Field

## 用途
给已有数据模型追加新字段

## API 端点
```
POST /xdap-app/modelField/add
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

### STRING 类型
```json
{
  "fieldCode": "customer_name",
  "fieldName": "客户名称",
  "fieldType": "STRING",
  "fieldStatus": "ENABLE",
  "databaseFieldType": "varchar",
  "maxLength": "500",
  "modelCode": "customer_a1b2",
  "modelId": "758716638387240960"
}
```

### NUM 类型
```json
{
  "fieldCode": "total_amount",
  "fieldName": "总金额",
  "fieldType": "NUM",
  "fieldStatus": "ENABLE",
  "modelCode": "customer_a1b2",
  "modelId": "758716638387240960"
}
```

### DATE 类型
```json
{
  "fieldCode": "created_date",
  "fieldName": "创建日期",
  "fieldType": "DATE",
  "fieldStatus": "ENABLE",
  "modelCode": "customer_a1b2",
  "modelId": "758716638387240960"
}
```

### BIG_TEXT 类型
```json
{
  "fieldCode": "remark",
  "fieldName": "备注",
  "fieldType": "BIG_TEXT",
  "fieldStatus": "ENABLE",
  "modelCode": "customer_a1b2",
  "modelId": "758716638387240960"
}
```

## 参数说明

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| fieldCode | string | 是 | 字段编码，只能包含字母、数字、下划线 |
| fieldName | string | 是 | 字段名称（中文） |
| fieldType | string | 是 | 字段类型：STRING, NUM, DATE, BIG_TEXT |
| fieldStatus | string | 是 | 固定值 "ENABLE"，**必须传**，否则报"状态为空" |
| modelCode | string | 是 | 所属模型编码（从 `query/modelWithField` 获取） |
| modelId | string | 是 | 所属模型 ID（从 `query/modelWithField` 或 `query/list` 获取） |
| databaseFieldType | string | STRING 必填 | STRING 类型**必须**传 "varchar"，否则报 null 异常 |
| maxLength | string | 否 | 最大长度，STRING 类型建议传 "500" |
| fieldModify | string | 否 | 是否可修改，默认 "true" |
| generateType | string | 否 | 生成方式 |

## 各字段类型必填参数对照

| 字段类型 | 基础参数 | 额外必填参数 |
|---------|---------|------------|
| STRING | fieldCode + fieldName + fieldType + fieldStatus + modelCode + modelId | `databaseFieldType: "varchar"` |
| NUM | 同上 | 无 |
| DATE | 同上 | 无 |
| BIG_TEXT | 同上 | 无 |

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "data": {
    "id": "821065701367218176",
    "fieldCode": "customer_name",
    "fieldName": "客户名称",
    "fieldType": "STRING",
    "fieldStatus": "ENABLE",
    "modelCode": "customer_a1b2",
    "modelId": "758716638387240960",
    "maxLength": "500",
    "fieldModify": "true",
    "fieldComment": "客户名称",
    "databaseFieldType": "varchar"
  }
}
```

## Python 调用示例

### 追加单个字段
```python
from app.apaas_client import APaaSClient

async def add_field(
    client: APaaSClient,
    app_id: str,
    model_code: str,
    model_id: str,
    field_code: str,
    field_name: str,
    field_type: str
):
    """给已有模型追加一个字段"""
    payload = {
        "fieldCode": field_code,
        "fieldName": field_name,
        "fieldType": field_type,
        "fieldStatus": "ENABLE",
        "modelCode": model_code,
        "modelId": model_id
    }

    # STRING 类型需要额外参数
    if field_type == "STRING":
        payload["databaseFieldType"] = "varchar"
        payload["maxLength"] = "500"

    result = await client.request(
        "POST",
        "/xdap-app/modelField/add",
        json=payload,
        app_id=app_id
    )

    print(f"字段创建成功: {result['fieldName']} ({result['fieldCode']}) id={result['id']}")
    return result
```

### 批量追加字段
```python
async def add_fields_batch(
    client: APaaSClient,
    app_id: str,
    model_code: str,
    model_id: str,
    fields: list
):
    """批量给已有模型追加字段

    fields 格式:
    [
        {"name": "客户名称", "code": "customer_name", "type": "STRING"},
        {"name": "总金额", "code": "total_amount", "type": "NUM"},
        {"name": "创建日期", "code": "created_date", "type": "DATE"},
        {"name": "备注", "code": "remark", "type": "BIG_TEXT"},
    ]
    """
    # 预览类型 → 数据模型字段类型映射
    TYPE_MAP = {
        "单行输入": "STRING", "手机号码": "STRING", "电子邮箱": "STRING",
        "下拉单选": "STRING", "下拉多选": "STRING", "数据单选": "STRING",
        "附件上传": "STRING", "开关": "STRING", "人员选择": "STRING",
        "地理位置": "STRING", "单据号": "STRING",
        "多行输入": "BIG_TEXT",
        "数字": "NUM", "金额": "NUM",
        "日期时间": "DATE",
    }

    results = []
    for f in fields:
        field_type = TYPE_MAP.get(f["type"], f["type"])  # 兼容中文和英文类型
        result = await add_field(
            client, app_id, model_code, model_id,
            f["code"], f["name"], field_type
        )
        results.append(result)

    print(f"共追加 {len(results)} 个字段到模型 {model_code}")
    return results
```

### 完整流程：查询模型 → 追加字段
```python
async def extend_existing_model(client: APaaSClient, app_id: str):
    """在已有模型上追加新字段的完整流程"""

    # 1. 查询已有模型
    result = await client.request(
        "POST",
        "/xdap-app/dataModel/query/modelWithField",
        json={"appId": app_id, "modelCode": "customer", "page": 1, "pageSize": 10},
        app_id=app_id
    )
    model = result["table"][0]
    model_code = model["modelCode"]
    model_id = model["modelId"]

    # 2. 检查已有字段，避免重复
    existing_codes = {f["fieldCode"] for f in model.get("dataModelFields", [])}

    # 3. 追加新字段
    new_fields = [
        {"name": "客户等级", "code": "customer_level", "type": "STRING"},
        {"name": "年营收", "code": "annual_revenue", "type": "NUM"},
    ]

    for f in new_fields:
        if f["code"] in existing_codes:
            print(f"字段 {f['code']} 已存在，跳过")
            continue
        await add_field(client, app_id, model_code, model_id, f["code"], f["name"], f["type"])
```

## 注意事项

### fieldStatus 必须传
- **必须**传 `"ENABLE"`，否则报错 "状态为空"
- 这是 API 的硬性要求

### STRING 类型必须传 databaseFieldType
- STRING 类型**必须**传 `"databaseFieldType": "varchar"`
- 不传会报 `Cannot invoke "String.toLowerCase()" because ... getDatabaseFieldType() is null`
- NUM、DATE、BIG_TEXT 不需要此参数

### fieldCode 编码规则
- 只能包含字母、数字、下划线
- **避免使用数据库保留字**（同 `apaas-create-model` 中的保留字列表）
- 解决方法：添加前缀 `f_`，如 `f_status`, `f_name`

### modelId 获取方式
- 通过 `POST /dataModel/query/modelWithField` 查询，返回 `modelId` 字段
- 通过 `POST /dataModel/query/list` 查询，返回 `id` 字段即为 modelId
- **不能只传 modelCode**，modelId 是必填的

### 无批量添加接口
- API 一次只能添加一个字段
- 批量添加需要循环调用
- 没有删除字段的 API，添加前建议先检查是否已存在

### 字段添加后的后续步骤
- 新字段添加后，可以在表单组件中引用：`modelField: "{modelCode}.{fieldCode}"`
- 如果是下拉选择类型，还需要创建对应的字典并绑定
- 如果是数据选择器类型，需要配置 `dataSelectorConfig`

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| error | 状态为空 | 未传 fieldStatus | 添加 `"fieldStatus": "ENABLE"` |
| sys_error | Cannot invoke "String.toLowerCase()" ... getDatabaseFieldType() is null | STRING 类型未传 databaseFieldType | 添加 `"databaseFieldType": "varchar"` |
| - | 字段编码与数据库关键字重复 | fieldCode 是保留字 | 添加前缀 `f_` |
| - | 字段编码已存在 | 同模型下 fieldCode 重复 | 先查询已有字段，跳过已存在的 |

## 相关 Skills
- `apaas-query-model` — 查询已有模型（获取 modelCode 和 modelId）
- `apaas-create-model` — 创建新模型（批量创建模型和字段）
- `apaas-create-form` — 创建表单配置（使用新追加的字段）
