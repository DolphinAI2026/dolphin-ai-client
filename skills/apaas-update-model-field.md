# aPaaS Update Model Field

## 用途
更新单个模型字段

## API 端点
```
POST /xdap-app/modelField/update/fromApp
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
| id | body | string | 是 | 字段 ID |
| modelId | body | string | 是 | 模型 ID |
| fieldCode | body | string | 是 | 字段编码（不可修改） |
| fieldName | body | string | 是 | 字段名称 |
| fieldType | body | string | 是 | 字段类型：STRING / NUM / DATE / BIG_TEXT |
| databaseFieldType | body | string | 是 | 数据库字段类型 |
| fieldStatus | body | string | 是 | 状态：ENABLE / DISABLE |
| fieldComment | body | string | 否 | 字段注释 |

### 请求示例
```json
POST /xdap-app/modelField/update/fromApp

{
  "id": "822878739107938304",
  "modelId": "822876369124851712",
  "fieldCode": "user_name",
  "fieldName": "用户名（已修改）",
  "fieldType": "STRING",
  "databaseFieldType": "varchar",
  "fieldStatus": "ENABLE",
  "fieldComment": "更新后的注释"
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功"
}
```

## Python 调用示例

### 更新字段名称
```python
from app.apaas_client import APaaSClient

async def update_field_name(
    client: APaaSClient,
    app_id: str,
    model_id: str,
    field_id: str,
    new_name: str
):
    """更新字段名称"""
    # 先查询字段信息
    query_result = await client.request(
        "POST",
        "/xdap-app/modelField/query",
        json={
            "dataModelId": model_id,
            "page": 1,
            "pageSize": 100
        },
        app_id=app_id
    )

    field = next((f for f in query_result.get("table", []) if f["id"] == field_id), None)
    if not field:
        print(f"未找到字段 {field_id}")
        return None

    result = await client.request(
        "POST",
        "/xdap-app/modelField/update/fromApp",
        json={
            "id": field_id,
            "modelId": model_id,
            "fieldCode": field["fieldCode"],
            "fieldName": new_name,
            "fieldType": field["fieldType"],
            "databaseFieldType": field["databaseFieldType"],
            "fieldStatus": field["fieldStatus"],
            "fieldComment": field.get("fieldComment", "")
        },
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"字段更新成功，新名称: {new_name}")

    return result
```

### 通用字段更新
```python
async def update_model_field(
    client: APaaSClient,
    app_id: str,
    model_id: str,
    field_id: str,
    updates: dict
):
    """通用字段更新方法"""
    # 先查询字段信息
    query_result = await client.request(
        "POST",
        "/xdap-app/modelField/query",
        json={
            "dataModelId": model_id,
            "page": 1,
            "pageSize": 100
        },
        app_id=app_id
    )

    field = next((f for f in query_result.get("table", []) if f["id"] == field_id), None)
    if not field:
        print(f"未找到字段 {field_id}")
        return None

    payload = {
        "id": field_id,
        "modelId": model_id,
        "fieldCode": field["fieldCode"],  # 不可修改
        "fieldName": updates.get("fieldName", field["fieldName"]),
        "fieldType": updates.get("fieldType", field["fieldType"]),
        "databaseFieldType": updates.get("databaseFieldType", field["databaseFieldType"]),
        "fieldStatus": updates.get("fieldStatus", field["fieldStatus"]),
        "fieldComment": updates.get("fieldComment", field.get("fieldComment", ""))
    }

    result = await client.request(
        "POST",
        "/xdap-app/modelField/update/fromApp",
        json=payload,
        app_id=app_id
    )

    return result
```

## 注意事项

### fieldCode 不可修改
- `fieldCode` 在创建后不可修改
- 编辑时必须传入原始 `fieldCode`

### 类型修改限制
- 修改 `fieldType` 和 `databaseFieldType` 可能影响已有数据
- 建议谨慎修改字段类型

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | id 不存在 | 检查字段 ID |
| 500 | Internal Server Error | fieldCode 与原值不一致 | 使用原始 fieldCode |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills

### 数据模型管理
- `apaas-query-model` — 查询模型及字段详情
- `apaas-page-query-model` — 分页查询模型列表
- `apaas-create-model` — 创建模型
- `apaas-update-model` — 更新模型

### 模型字段管理
- `apaas-page-query-model-field` — 分页查询模型字段（获取字段详情）
- `apaas-create-model-field` — 新增字段
- `apaas-batch-update-model-field` — 批量更新字段
