# aPaaS Enable Dictionary

## 用途
启用应用下的数据字典

## API 端点
```
GET /xdap-app/dataDictionary/enable/dataDictionary
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
| id | query | string | 是 | 要启用的字典 ID |

### 请求示例
```
GET /xdap-app/dataDictionary/enable/dataDictionary?id=822869360979738624
```

## 响应格式
```json
{
  "code": "ok",
  "message": "启用数据字典成功"
}
```

## Python 调用示例

### 启用单个字典
```python
from app.apaas_client import APaaSClient

async def enable_dictionary(client: APaaSClient, app_id: str, dict_id: str):
    """启用指定字典"""
    result = await client.request(
        "GET",
        f"/xdap-app/dataDictionary/enable/dataDictionary?id={dict_id}",
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"字典 {dict_id} 启用成功")
    else:
        print(f"启用失败: {result.get('message')}")

    return result
```

### 按 dictionaryCode 启用字典
```python
async def enable_dict_by_code(client: APaaSClient, app_id: str, dict_code: str):
    """按 dictionaryCode 查找并启用字典"""
    # 先查询字典列表
    query_result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={
            "keyword": "",
            "appId": app_id
        },
        app_id=app_id
    )

    # 查找匹配的字典
    for d in query_result.get("table", []):
        if d["dictionaryCode"] == dict_code:
            return await enable_dictionary(client, app_id, d["id"])

    print(f"未找到 dictionaryCode={dict_code} 的字典")
    return None
```

### 批量启用字典
```python
async def enable_dicts_batch(client: APaaSClient, app_id: str, dict_ids: list[str]):
    """批量启用多个字典"""
    results = []
    for dict_id in dict_ids:
        result = await enable_dictionary(client, app_id, dict_id)
        results.append({"dictId": dict_id, "result": result})
    return results
```

## 注意事项

### 启用后的影响
- 启用后的字典可在表单中选择使用
- 字典项（字典值）也会一并可用

### 只能启用禁用状态的字典
- 如果字典已经是启用状态，再次调用不会报错

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | id 不存在 | 检查字典 ID 是否正确 |
| 401 | 未授权 | token 过期 | 重新登录 |
| 403 | 无权限 | 无权操作该字典 | 检查用户权限 |

## 相关 Skills

### 字典管理
- `apaas-query-dict` — 查询字典列表（获取字典 ID）
- `apaas-create-dict` — 批量创建字典
- `apaas-update-dict` — 编辑字典
- `apaas-disable-dict` — 禁用字典

### 字典值管理
- `apaas-query-dict-value` — 查询字典值列表
- `apaas-create-dict-value` — 新增字典值
- `apaas-update-dict-value` — 编辑字典值
- `apaas-enable-dict-value` — 启用字典值
- `apaas-disable-dict-value` — 禁用字典值
