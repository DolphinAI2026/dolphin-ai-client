# aPaaS Query Dictionary

## 用途
查询应用下的数据字典列表，用于获取已有字典的 id、dictionaryCode、dictionaryName 等信息

## API 端点
```
POST /xdap-app/dataDictionary/query/dataDictionaryList
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
| keyword | body | string | 否 | 关键字搜索（字典名称/编码） |
| appId | body | string | 是 | 应用 ID |

### 请求示例
```json
POST /xdap-app/dataDictionary/query/dataDictionaryList

{
  "keyword": "",
  "appId": "822790159832449024"
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "total": 33,
  "table": [
    {
      "id": "822790226001788928",
      "dictionaryCode": "pay_deadline_jbft",
      "dictionaryName": "支付期限",
      "dictionaryNameI18nAssociated": false,
      "dictionaryStatus": "ENABLE",
      "dictionaryMulticolorStatus": "ENABLE",
      "appId": "822790159832449024",
      "tenantId": "566642786573484033",
      "internalResource": true,
      "useScope": "劳务管理系统",
      "owner": "100169876816012509184",
      "createdBy": "100169876816012509184",
      "lastUpdatedBy": "100169876816012509184",
      "objectVersionNumber": 1,
      "creationDate": "2026-03-20 11:14:37",
      "lastUpdateDate": "2026-03-20 11:14:37"
    }
  ]
}
```

### 响应字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 字典 ID（编辑/删除字典时使用） |
| dictionaryCode | string | 字典编码 |
| dictionaryName | string | 字典名称 |
| dictionaryStatus | string | 字典状态：ENABLE / DISABLE |
| dictionaryMulticolorStatus | string | 多色标签状态：ENABLE / DISABLE |
| dictionaryNameI18nAssociated | boolean | 是否关联国际化 |
| appId | string | 所属应用 ID |
| tenantId | string | 所属租户 ID |
| internalResource | boolean | 是否为应用内部资源（`true` = 应用级字典） |
| useScope | string | 使用范围（应用名称或 "全部应用"） |
| owner | string | 所有者用户 ID |
| createdBy | string | 创建者用户 ID |
| lastUpdatedBy | string | 最后更新者用户 ID |
| objectVersionNumber | integer | 乐观锁版本号 |
| total | integer | 字典总数 |

## Python 调用示例

### 查询应用下所有字典
```python
from app.apaas_client import APaaSClient

async def query_dictionaries(client: APaaSClient, app_id: str, keyword: str = ""):
    """查询应用下所有数据字典"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={
            "keyword": keyword,
            "appId": app_id
        },
        app_id=app_id
    )

    dicts = result.get("table", [])
    print(f"共 {result.get('total', 0)} 个字典")
    for d in dicts:
        status = "启用" if d["dictionaryStatus"] == "ENABLE" else "禁用"
        print(f"  [{status}] {d['dictionaryName']} ({d['dictionaryCode']}) id={d['id']}")

    return dicts
```

### 只获取应用级字典
```python
async def query_app_dictionaries(client: APaaSClient, app_id: str):
    """只获取应用级字典（排除全局字典）"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={
            "keyword": "",
            "appId": app_id
        },
        app_id=app_id
    )

    app_dicts = [d for d in result.get("table", []) if d.get("internalResource")]
    return app_dicts
```

### 按 dictionaryCode 查找字典
```python
async def find_dict_by_code(client: APaaSClient, app_id: str, dict_code: str):
    """按 dictionaryCode 查找字典"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={
            "keyword": "",
            "appId": app_id
        },
        app_id=app_id
    )

    for d in result.get("table", []):
        if d["dictionaryCode"] == dict_code:
            return d
    return None
```

### 按关键字搜索字典
```python
async def search_dictionaries(client: APaaSClient, app_id: str, keyword: str):
    """按关键字搜索字典"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={
            "keyword": keyword,
            "appId": app_id
        },
        app_id=app_id
    )

    return result.get("table", [])
```

### 获取启用状态的字典
```python
async def query_enabled_dictionaries(client: APaaSClient, app_id: str):
    """只获取启用状态的字典"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={
            "keyword": "",
            "appId": app_id
        },
        app_id=app_id
    )

    enabled_dicts = [d for d in result.get("table", []) if d["dictionaryStatus"] == "ENABLE"]
    return enabled_dicts
```

## 注意事项

### 返回结果包含全局字典
- 返回结果可能包含应用级字典和全局字典
- 通过 `internalResource: true` 过滤应用级字典
- 通过 `useScope` 可以看到字典的使用范围

### 字典 ID 的用途
- `id` 字段用于：
  - 查询字典项（`/dataDictionary/query/dataDictionaryValueList`）
  - 编辑字典（`/dataDictionary/edit/dataDictionary`）
  - 删除字典（`/dataDictionary/delete/dataDictionary`）

### 有分页信息
- 响应中包含 `total` 字段表示总数
- `table` 数组返回所有字典数据

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | appId 格式错误 | 检查 appId 是否正确 |
| 401 | 未授权 | token 过期 | 重新登录 |
| 403 | 无权限 | 无权访问该应用 | 检查用户权限 |

## 相关 Skills

### 字典管理
- `apaas-create-dict` — 批量创建字典
- `apaas-update-dict` — 编辑字典
- `apaas-enable-dict` — 启用字典
- `apaas-disable-dict` — 禁用字典

### 字典值管理
- `apaas-query-dict-value` — 查询字典值列表
- `apaas-create-dict-value` — 新增字典值
- `apaas-update-dict-value` — 编辑字典值
- `apaas-enable-dict-value` — 启用字典值
- `apaas-disable-dict-value` — 禁用字典值

