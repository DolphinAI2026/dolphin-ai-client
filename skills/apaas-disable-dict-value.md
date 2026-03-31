# aPaaS Disable Dictionary Value

## 用途
禁用字典选项值

## API 端点
```
GET /xdap-app/dataDictionary/disable/dictionaryValue
```

## 请求头
```json
{
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>",
  "appid": "<app_id>"
}
```

## 请求参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| id | query | string | 是 | 要禁用的字典值 ID |

### 请求示例
```
GET /xdap-app/dataDictionary/disable/dictionaryValue?id=822872563364397056
```

## 响应格式
```json
{
  "code": "ok",
  "message": "禁用数据字典值成功"
}
```

## Python 调用示例

### 禁用单个字典值
```python
from app.apaas_client import APaaSClient

async def disable_dict_value(client: APaaSClient, app_id: str, value_id: str):
    """禁用指定字典值"""
    result = await client.request(
        "GET",
        f"/xdap-app/dataDictionary/disable/dictionaryValue?id={value_id}",
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"字典值 {value_id} 禁用成功")
    else:
        print(f"禁用失败: {result.get('message')}")

    return result
```

### 按 valueCode 禁用字典值
```python
async def disable_dict_value_by_code(
    client: APaaSClient,
    app_id: str,
    dict_id: str,
    value_code: str
):
    """按 valueCode 查找并禁用字典值"""
    # 先查询字典值列表
    query_result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dictionaryValueList",
        json={
            "page": 1,
            "pageSize": 100,
            "keyword": "",
            "dictionaryId": dict_id,
            "appId": app_id
        },
        app_id=app_id
    )

    # 查找匹配的值
    for v in query_result.get("table", []):
        if v["valueCode"] == value_code:
            return await disable_dict_value(client, app_id, v["id"])

    print(f"未找到 valueCode={value_code} 的字典值")
    return None
```

### 批量禁用字典值
```python
async def disable_dict_values_batch(client: APaaSClient, app_id: str, value_ids: list[str]):
    """批量禁用多个字典值"""
    results = []
    for value_id in value_ids:
        result = await disable_dict_value(client, app_id, value_id)
        results.append({"valueId": value_id, "result": result})
    return results
```

## 注意事项

### 禁用后的影响
- 禁用后的字典值在表单下拉中不可选择
- 已使用该值的数据不受影响
- 可以通过启用接口重新启用

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | id 不存在 | 检查字典值 ID |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills

### 字典值管理
- `apaas-query-dict-value` — 查询字典值列表
- `apaas-create-dict-value` — 新增字典值
- `apaas-update-dict-value` — 编辑字典值
- `apaas-enable-dict-value` — 启用字典值

### 字典管理
- `apaas-query-dict` — 查询字典列表（获取 dictionaryId）
- `apaas-create-dict` — 批量创建字典
- `apaas-update-dict` — 编辑字典
- `apaas-enable-dict` — 启用字典
- `apaas-disable-dict` — 禁用字典
