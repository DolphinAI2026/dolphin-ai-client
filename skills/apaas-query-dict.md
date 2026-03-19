# aPaaS Query Data Dictionary

## 用途
查询应用下的数据字典及其选项值，用于获取已有字典的 id、dictionaryCode、选项列表等信息

## API 端点

### 查询字典列表
```
POST /xdap-app/dataDictionary/query/dataDictionaryList
```

### 查询字典选项值
```
POST /xdap-app/dataDictionary/query/dictionaryValueList
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

## 查询字典列表

### 请求格式
```json
{
  "keyword": "",
  "appId": "755484864311984128"
}
```

### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| keyword | string | 否 | 关键字搜索（模糊匹配字典名称） |
| appId | string | 是 | 应用 ID，按应用过滤 |

### 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "total": 6,
  "table": [
    {
      "id": "758716287454019584",
      "dictionaryCode": "meeting_type_rfmz",
      "dictionaryName": "会议类型字典",
      "dictionaryStatus": "ENABLE",
      "dictionaryMulticolorStatus": "DISABLE",
      "dictionaryDescribe": "",
      "dictionaryNameI18nAssociated": false,
      "appId": "755484864311984128",
      "internalResource": true,
      "useScope": "AI场景演示",
      "objectVersionNumber": 1,
      "tenantId": "743906758237356033",
      "creationDate": "2025-09-24 15:47:39",
      "lastUpdateDate": "2025-09-24 15:47:39"
    }
  ]
}
```

### 响应字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 字典 ID（查询选项、编辑字典时需要） |
| dictionaryCode | string | 字典编码（带后缀的实际编码） |
| dictionaryName | string | 字典名称 |
| dictionaryStatus | string | 字典状态：ENABLE / DISABLE |
| dictionaryMulticolorStatus | string | 多色状态：ENABLE / DISABLE |
| dictionaryDescribe | string | 字典描述 |
| appId | string | 所属应用 ID |
| internalResource | boolean | 是否为应用内部资源 |
| useScope | string | 使用范围（应用名称） |
| objectVersionNumber | integer | 乐观锁版本号 |

## 查询字典选项值

### 请求格式
```json
{
  "page": 1,
  "pageSize": 50,
  "keyword": "",
  "dictionaryId": "758716287454019584",
  "appId": "755484864311984128"
}
```

### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| dictionaryId | string | 是 | 字典 ID（从查询字典列表获取） |
| appId | string | 否 | 应用 ID |
| keyword | string | 否 | 关键字搜索（模糊匹配选项名称） |
| page | integer | 否 | 页码 |
| pageSize | integer | 否 | 每页条数 |

### 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "total": 5,
  "table": [
    {
      "id": "758716287525322752",
      "dictionaryId": "758716287454019584",
      "valueCode": "regular_meeting_rfmz",
      "valueName": "例会",
      "valueStatus": "ENABLE",
      "displayOrder": 0,
      "valueDescribe": "-",
      "valueMulticolor": "#027AFF",
      "valueNameI18nResourceCode": "i18n_PhvtDdB8",
      "valueNameI18nAssociated": false,
      "objectVersionNumber": 1
    }
  ]
}
```

### 选项字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 选项 ID（编辑、禁用选项时需要） |
| dictionaryId | string | 所属字典 ID |
| valueCode | string | 选项编码 |
| valueName | string | 选项名称（显示值） |
| valueStatus | string | 选项状态：ENABLE / DISABLE |
| displayOrder | integer | 显示顺序，从 0 开始 |
| valueDescribe | string | 选项描述 |
| valueMulticolor | string | 选项颜色值 |
| objectVersionNumber | integer | 乐观锁版本号 |

## Python 调用示例

### 查询应用下所有字典
```python
from app.apaas_client import APaaSClient

async def query_dicts(client: APaaSClient, app_id: str):
    """查询应用下所有字典"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={"keyword": "", "appId": app_id},
        app_id=app_id
    )

    dicts = result.get("table", [])
    print(f"共 {result.get('total', 0)} 个字典")
    for d in dicts:
        print(f"  {d['dictionaryName']} ({d['dictionaryCode']}) id={d['id']}")

    return dicts
```

### 按关键字搜索字典
```python
async def search_dict(client: APaaSClient, app_id: str, keyword: str):
    """按关键字搜索字典"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={"keyword": keyword, "appId": app_id},
        app_id=app_id
    )
    return result.get("table", [])
```

### 查询字典的所有选项
```python
async def query_dict_values(client: APaaSClient, app_id: str, dictionary_id: str):
    """查询指定字典的所有选项"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dictionaryValueList",
        json={
            "dictionaryId": dictionary_id,
            "appId": app_id,
            "keyword": "",
            "page": 1,
            "pageSize": 200
        },
        app_id=app_id
    )

    values = result.get("table", [])
    for v in values:
        print(f"  {v['valueName']} ({v['valueCode']}) status={v['valueStatus']}")

    return values
```

### 构建 dict_code_map（用于表单创建）
```python
async def build_dict_code_map(client: APaaSClient, app_id: str):
    """从已有字典构建 dict_code_map，供 transform_form_config 使用"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={"keyword": "", "appId": app_id},
        app_id=app_id
    )

    dict_code_map = {}
    for d in result.get("table", []):
        dict_code_map[d["dictionaryCode"]] = d["dictionaryCode"]

    return dict_code_map
```

## 注意事项

### appId 过滤
- 必须传 `appId` 过滤，否则会返回全租户所有字典（含全局共享字典，可能数百个）
- 返回结果中 `internalResource: true` 表示应用级字典

### 字典 ID 的获取
- 查询字典列表返回 `id` 字段即为 `dictionaryId`
- 查询选项时需要用此 `dictionaryId`

### 分页
- 字典列表无分页参数，直接返回全部
- 选项值支持分页，建议传 `page: 1, pageSize: 200` 确保获取所有选项

### 返回的编码即实际编码
- 返回的 `dictionaryCode` 和 `valueCode` 是平台中的实际编码（已包含后缀）
- 可以直接用于表单组件的 `dictionarySelectConfig.dictionaryCode`

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | xdaptimestamp 格式错误 | 使用正确的毫秒时间戳（macOS 需用 Python 生成） |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills
- `apaas-create-dict` — 批量创建字典
- `apaas-update-dict` — 编辑字典和选项
- `apaas-comp-select-single` — 下拉单选组件（使用字典）
- `apaas-comp-select-multi` — 下拉多选组件（使用字典）
