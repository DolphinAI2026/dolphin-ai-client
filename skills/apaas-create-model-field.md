# aPaaS Create Model Field

## 用途
给已有数据模型追加新字段

## API 端点
```
POST /xdap-app/modelField/add
```

## 请求头
```json
{
  "Content-Type": "application/json;charset=UTF-8",
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>",
  "appid": "<app_id>"
}
```

## 请求参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| dataModelId | body | string | 是 | 数据模型 ID |
| modelId | body | string | 是 | 模型 ID（同 dataModelId） |
| modelCode | body | string | 是 | 模型编码 |
| fieldCode | body | string | 是 | 字段编码（唯一） |
| fieldName | body | string | 是 | 字段名称 |
| fieldType | body | string | 是 | 字段类型：STRING / NUM / DATE / BIG_TEXT |
| databaseFieldType | body | string | 是 | 数据库字段类型 |
| fieldStatus | body | string | 是 | 状态：ENABLE / DISABLE |
| maxLength | body | integer | 否 | 最大长度（STRING 类型需要） |
| fieldComment | body | string | 否 | 字段注释 |
| databaseFieldPrecision | body | integer | 否 | 精度（decimal 类型） |
| databaseFieldScale | body | integer | 否 | 小数位数（decimal 类型） |

### 字段类型与数据库类型对照表

| fieldType | databaseFieldType | 说明 |
|-----------|-------------------|------|
| STRING | varchar | 可变长字符串，需指定 maxLength |
| STRING | char | 定长字符串 |
| NUM | int / integer | 整数 |
| NUM | bigint | 长整数 |
| NUM | decimal | 精确小数，需指定 precision 和 scale |
| NUM | float / double | 浮点数 |
| DATE | datetime | 日期时间 |
| DATE | date | 仅日期 |
| DATE | time | 仅时间 |
| DATE | timestamp | 时间戳 |
| BIG_TEXT | text | 文本 |
| BIG_TEXT | longtext | 长文本 |

### 请求示例
```json
POST /xdap-app/modelField/add

{
  "dataModelId": "822876369124851712",
  "modelId": "822876369124851712",
  "modelCode": "test_011",
  "fieldCode": "user_name",
  "fieldName": "用户名",
  "fieldType": "STRING",
  "databaseFieldType": "varchar",
  "maxLength": 100,
  "fieldComment": "用户登录名",
  "fieldStatus": "ENABLE"
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "data": {
    "id": "822879314046353408",
    "fieldCode": "user_name",
    "fieldName": "用户名",
    "fieldType": "STRING",
    "fieldStatus": "ENABLE",
    "modelCode": "test_011",
    "modelId": "822876369124851712",
    "maxLength": "100",
    "databaseFieldType": "varchar"
  }
}
```

## Python 调用示例

### 新增单个字段
```python
from app.apaas_client import APaaSClient

async def create_model_field(
    client: APaaSClient,
    app_id: str,
    model_id: str,
    model_code: str,
    field_code: str,
    field_name: str,
    field_type: str = "STRING",
    db_field_type: str = "varchar",
    max_length: int = 500,
    comment: str = ""
):
    """新增模型字段"""
    payload = {
        "dataModelId": model_id,
        "modelId": model_id,
        "modelCode": model_code,
        "fieldCode": field_code,
        "fieldName": field_name,
        "fieldType": field_type,
        "databaseFieldType": db_field_type,
        "fieldStatus": "ENABLE",
        "fieldComment": comment
    }

    if field_type == "STRING":
        payload["maxLength"] = max_length

    result = await client.request(
        "POST",
        "/xdap-app/modelField/add",
        json=payload,
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"字段 {field_name} 创建成功，ID: {result['data']['id']}")

    return result
```

### 批量新增字段
```python
async def create_model_fields_batch(
    client: APaaSClient,
    app_id: str,
    model_id: str,
    model_code: str,
    fields: list[dict]
):
    """批量新增模型字段

    Args:
        fields: [{"code": "name", "name": "姓名", "type": "STRING", ...}, ...]
    """
    results = []
    for f in fields:
        result = await create_model_field(
            client,
            app_id,
            model_id,
            model_code,
            field_code=f["code"],
            field_name=f["name"],
            field_type=f.get("type", "STRING"),
            db_field_type=f.get("dbType", "varchar"),
            max_length=f.get("maxLength", 500),
            comment=f.get("comment", "")
        )
        results.append({"fieldCode": f["code"], "result": result})
    return results
```

### 常用字段快捷方法
```python
async def add_varchar_field(client, app_id, model_id, model_code, code, name, length=500):
    """添加 varchar 字段"""
    return await create_model_field(
        client, app_id, model_id, model_code, code, name,
        field_type="STRING", db_field_type="varchar", max_length=length
    )

async def add_int_field(client, app_id, model_id, model_code, code, name):
    """添加 int 字段"""
    return await create_model_field(
        client, app_id, model_id, model_code, code, name,
        field_type="NUM", db_field_type="int"
    )

async def add_datetime_field(client, app_id, model_id, model_code, code, name):
    """添加 datetime 字段"""
    return await create_model_field(
        client, app_id, model_id, model_code, code, name,
        field_type="DATE", db_field_type="datetime"
    )
```

## 注意事项

### fieldCode 唯一性
- 同一模型下 `fieldCode` 必须唯一
- 建议使用小写字母和下划线命名
- 避免数据库保留字（name, status, type, order 等）

### 字段类型选择
- 金额字段使用 `decimal(10,2)`
- ID 字段使用 `bigint`
- 普通文本使用 `varchar(500)`
- 长文本使用 `text` 或 `longtext`

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | fieldCode 已存在 | 使用不同的 fieldCode |
| 500 | Internal Server Error | modelId 不存在 | 检查模型 ID |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills

### 数据模型管理
- `apaas-query-model` — 查询模型及字段详情
- `apaas-page-query-model` — 分页查询模型列表（获取 modelId）
- `apaas-create-model` — 创建模型
- `apaas-update-model` — 更新模型

### 模型字段管理
- `apaas-page-query-model-field` — 分页查询模型字段
- `apaas-update-model-field` — 更新字段
- `apaas-batch-update-model-field` — 批量更新字段
