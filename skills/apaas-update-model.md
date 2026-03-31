# aPaaS Update Model

## 用途
更新数据模型基本信息

## API 端点
```
POST /xdap-app/dataModel/update
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
| id | body | string | 是 | 模型 ID |
| appId | body | string | 是 | 应用 ID |
| modelCode | body | string | 是 | 模型编码（不可修改） |
| modelName | body | string | 是 | 模型名称 |
| modelType | body | string | 是 | 模型类型：DATABASE |
| modelDataSource | body | string | 是 | 数据源 ID |
| useScope | body | string | 是 | 使用范围（应用名称） |
| internalResource | body | boolean | 是 | 是否内部资源 |
| interfaceType | body | string | 否 | 接口类型：CUSTOM |
| createType | body | string | 否 | 创建类型：NEWCREATE |
| apiVersion | body | string | 否 | API 版本：V2 |
| generateType | body | string | 否 | 生成类型：NEWCREATE |

### 请求示例
```json
POST /xdap-app/dataModel/update

{
  "id": "822876369124851712",
  "appId": "822790159832449024",
  "modelCode": "test_011",
  "modelName": "测试模型（已更新）",
  "modelType": "DATABASE",
  "modelDataSource": "566642829992919040",
  "useScope": "劳务管理系统",
  "internalResource": true,
  "interfaceType": "CUSTOM",
  "createType": "NEWCREATE",
  "apiVersion": "V2",
  "generateType": "NEWCREATE"
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "data": {
    "id": "822876369124851712",
    "modelCode": "test_011",
    "modelName": "测试模型（已更新）",
    "modelType": "DATABASE",
    "status": "ENABLE",
    "apiVersion": "V2",
    "internalResource": true,
    "appId": "822790159832449024",
    "useScope": "劳务管理系统"
  }
}
```

## Python 调用示例

### 更新模型名称
```python
from app.apaas_client import APaaSClient

async def update_model_name(client: APaaSClient, app_id: str, model_id: str, new_name: str):
    """更新模型名称"""
    # 先查询模型信息
    query_result = await client.request(
        "POST",
        "/xdap-app/dataModel/query/list",
        json={
            "page": 1,
            "pageSize": 100,
            "keyWord": "",
            "appId": app_id
        },
        app_id=app_id
    )

    model = next((m for m in query_result.get("table", []) if m["id"] == model_id), None)
    if not model:
        print(f"未找到模型 {model_id}")
        return None

    result = await client.request(
        "POST",
        "/xdap-app/dataModel/update",
        json={
            "id": model_id,
            "appId": app_id,
            "modelCode": model["modelCode"],
            "modelName": new_name,
            "modelType": model["modelType"],
            "modelDataSource": model["modelDataSource"],
            "useScope": model["useScope"],
            "internalResource": model.get("internalResource", True),
            "interfaceType": model.get("interfaceType", "CUSTOM"),
            "createType": model.get("createType", "NEWCREATE"),
            "apiVersion": model.get("apiVersion", "V2"),
            "generateType": model.get("generateType", "NEWCREATE")
        },
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"模型更新成功，新名称: {new_name}")

    return result
```

## 注意事项

### modelCode 不可修改
- `modelCode` 在创建后不可修改
- 编辑时必须传入原始 `modelCode`

### 数据源不可修改
- `modelDataSource` 通常不建议修改
- 修改数据源可能导致数据丢失

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | id 不存在 | 检查模型 ID |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills

### 数据模型管理
- `apaas-page-query-model` — 分页查询模型列表（获取详情）
- `apaas-create-model` — 创建模型

### 模型字段管理
- `apaas-page-query-model-field` — 分页查询模型字段
- `apaas-create-model-field` — 新增字段
- `apaas-update-model-field` — 更新字段
- `apaas-batch-update-model-field` — 批量更新字段
