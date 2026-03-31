# aPaaS Query Dictionary Value

## 用途
查询字典下的选项值列表

## API 端点
```
POST /xdap-app/dataDictionary/query/dictionaryValueList
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
| dictionaryId | body | string | 是 | 字典 ID |
| appId | body | string | 是 | 应用 ID |
| keyword | body | string | 否 | 关键字搜索 |
| page | body | integer | 否 | 页码，默认 1 |
| pageSize | body | integer | 否 | 每页数量，默认 10 |

### 请求示例
```json
POST /xdap-app/dataDictionary/query/dictionaryValueList

{
  "page": 1,
  "pageSize": 10,
  "keyword": "",
  "dictionaryId": "822869360979738624",
  "appId": "822790159832449024"
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "total": 1,
  "table": [
    {
      "id": "822872563364397056",
      "dictionaryId": "822869360979738624",
      "valueCode": "ceshi",
      "valueName": "测试名称",
      "valueNameI18nAssociated": false,
      "displayOrder": 0,
      "valueDescribe": "描述信息",
      "valueStatus": "ENABLE",
      "valueMulticolor": "#027AFF",
      "appId": "822790159832449024",
      "tenantId": "566642786573484033",
      "owner": "100169876816012509184",
      "createdBy": "100169876816012509184",
      "lastUpdatedBy": "100169876816012509184",
      "objectVersionNumber": 1,
      "creationDate": "2026-03-20 16:41:47",
      "lastUpdateDate": "2026-03-20 16:41:47"
    }
  ]
}
```

### 响应字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 字典值 ID |
| dictionaryId | string | 所属字典 ID |
| valueCode | string | 值编码 |
| valueName | string | 值名称（显示名） |
| valueStatus | string | 状态：ENABLE / DISABLE |
| valueMulticolor | string | 多色标签颜色（十六进制） |
| displayOrder | integer | 显示顺序 |
| valueDescribe | string | 值描述 |
| total | integer | 总数 |

## Python 调用示例

### 查询字典下所有值
```python
from app.apaas_client import APaaSClient

async def query_dict_values(client: APaaSClient, app_id: str, dict_id: str, keyword: str = ""):
    """查询字典下所有选项值"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dictionaryValueList",
        json={
            "page": 1,
            "pageSize": 100,
            "keyword": keyword,
            "dictionaryId": dict_id,
            "appId": app_id
        },
        app_id=app_id
    )

    values = result.get("table", [])
    print(f"共 {result.get('total', 0)} 个选项值")
    for v in values:
        status = "启用" if v["valueStatus"] == "ENABLE" else "禁用"
        print(f"  [{status}] {v['valueName']} ({v['valueCode']}) id={v['id']}")

    return values
```

### 按 valueCode 查找字典值
```python
async def find_dict_value_by_code(client: APaaSClient, app_id: str, dict_id: str, value_code: str):
    """按 valueCode 查找字典值"""
    result = await client.request(
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

    for v in result.get("table", []):
        if v["valueCode"] == value_code:
            return v
    return None
```

### 分页查询
```python
async def query_dict_values_paged(client: APaaSClient, app_id: str, dict_id: str, page: int = 1, page_size: int = 10):
    """分页查询字典值"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dictionaryValueList",
        json={
            "page": page,
            "pageSize": page_size,
            "keyword": "",
            "dictionaryId": dict_id,
            "appId": app_id
        },
        app_id=app_id
    )

    return {
        "values": result.get("table", []),
        "total": result.get("total", 0),
        "page": page,
        "pageSize": page_size
    }
```

## 注意事项

### 支持分页
- 使用 `page` 和 `pageSize` 进行分页查询
- 响应中 `total` 表示总数

### 字典值 ID 的用途
- `id` 字段用于：
  - 编辑字典值
  - 禁用/启用字典值
  - 删除字典值

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | dictionaryId 不存在 | 检查字典 ID 是否正确 |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills

### 字典值管理
- `apaas-create-dict-value` — 新增字典值
- `apaas-update-dict-value` — 编辑字典值
- `apaas-enable-dict-value` — 启用字典值
- `apaas-disable-dict-value` — 禁用字典值

### 字典管理
- `apaas-query-dict` — 查询字典列表（获取 dictionaryId）
- `apaas-create-dict` — 批量创建字典
- `apaas-update-dict` — 编辑字典
- `apaas-enable-dict` — 启用字典
- `apaas-disable-dict` — 禁用字典
