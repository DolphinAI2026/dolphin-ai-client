# aPaaS Update Data Dictionary

## 用途
编辑已有数据字典（修改名称、描述等）及其选项（追加、编辑、启用/禁用）

## API 端点

### 编辑字典
```
POST /xdap-app/dataDictionary/edit/dataDictionary
```

### 追加选项
```
POST /xdap-app/dataDictionary/add/dictionaryValue
```

### 编辑选项
```
POST /xdap-app/dataDictionary/edit/dictionaryValue
```

### 禁用/启用选项
```
GET /xdap-app/dataDictionary/disable/dictionaryValue?id={valueId}
GET /xdap-app/dataDictionary/enable/dictionaryValue?id={valueId}
```

### 禁用/启用字典
```
GET /xdap-app/dataDictionary/disable/dataDictionary?id={dictionaryId}
GET /xdap-app/dataDictionary/enable/dataDictionary?id={dictionaryId}
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

## 编辑字典

### 请求格式
```json
{
  "appId": "755484864311984128",
  "internalResource": true,
  "id": "758716287454019584",
  "dictionaryCode": "meeting_type_rfmz",
  "dictionaryName": "会议类型字典（新名称）",
  "dictionaryNameI18nAssociated": false,
  "dictionaryNameI18nResourceCode": "",
  "dictionaryNameI18n": {},
  "dictionaryDescribe": "字典描述",
  "dictionaryMulticolorStatus": "DISABLE",
  "dictionaryStatus": "ENABLE"
}
```

### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 是 | 应用 ID |
| internalResource | boolean | 是 | 应用级字典传 `true` |
| id | string | 是 | 字典 ID（从查询接口获取） |
| dictionaryCode | string | 是 | 字典编码（**不可修改**，原样传回） |
| dictionaryName | string | 是 | 字典名称（可修改） |
| dictionaryDescribe | string | 否 | 字典描述（可修改） |
| dictionaryStatus | string | 是 | 字典状态：`"ENABLE"` / `"DISABLE"` |
| dictionaryMulticolorStatus | string | 是 | 多色状态：`"ENABLE"` / `"DISABLE"` |
| dictionaryNameI18nAssociated | boolean | 是 | 是否关联国际化，通常传 `false` |
| dictionaryNameI18nResourceCode | string | 否 | 国际化资源编码，通常传 `""` |
| dictionaryNameI18n | object | 否 | 国际化文本，通常传 `{}` |

### 响应格式
```json
{
  "code": "ok",
  "message": "编辑数据字典成功"
}
```

## 追加选项

### 请求格式
```json
{
  "appId": "755484864311984128",
  "dictionaryId": "758716287454019584",
  "valueCode": "new_option_code",
  "valueName": "新选项",
  "valueNameI18nAssociated": false,
  "valueNameI18nResourceCode": "",
  "valueNameI18n": {},
  "displayOrder": 5,
  "valueDescribe": "",
  "valueStatus": "ENABLE",
  "valueMulticolor": "#027AFF"
}
```

### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 是 | 应用 ID |
| dictionaryId | string | 是 | 字典 ID（从查询接口获取） |
| valueCode | string | 是 | 选项编码，**全局唯一**（跨所有字典），建议带后缀 |
| valueName | string | 是 | 选项名称（显示值） |
| displayOrder | integer | 是 | 显示顺序（查询已有选项后接着排） |
| valueDescribe | string | 否 | 选项描述 |
| valueStatus | string | 是 | 固定传 `"ENABLE"` |
| valueMulticolor | string | 否 | 选项颜色值，默认 `"#027AFF"` |
| valueNameI18nAssociated | boolean | 是 | 通常传 `false` |
| valueNameI18nResourceCode | string | 否 | 通常传 `""` |
| valueNameI18n | object | 否 | 通常传 `{}` |

### 响应格式
```json
{
  "code": "ok",
  "message": "新增数据字典值成功"
}
```

## 编辑选项

### 请求格式
```json
{
  "appId": "755484864311984128",
  "dictionaryId": "758716287454019584",
  "id": "758716287525322752",
  "valueCode": "regular_meeting_rfmz",
  "valueName": "例会（修改后）",
  "valueNameI18nAssociated": false,
  "valueNameI18nResourceCode": "",
  "valueNameI18n": {},
  "displayOrder": 0,
  "valueDescribe": "修改描述",
  "valueStatus": "ENABLE",
  "valueMulticolor": "#027AFF"
}
```

### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 是 | 应用 ID |
| dictionaryId | string | 是 | 字典 ID |
| id | string | 是 | 选项 ID（从查询选项接口获取） |
| valueCode | string | 是 | 选项编码（**不可修改**，原样传回） |
| valueName | string | 是 | 选项名称（可修改） |
| displayOrder | integer | 是 | 显示顺序（可修改） |
| valueDescribe | string | 否 | 选项描述（可修改） |
| valueStatus | string | 是 | 状态（可修改）：`"ENABLE"` / `"DISABLE"` |
| valueMulticolor | string | 否 | 颜色值（可修改） |

### 响应格式
```json
{
  "code": "ok",
  "message": "编辑数据字典值成功"
}
```

## 禁用/启用选项

### 请求格式
```
GET /xdap-app/dataDictionary/disable/dictionaryValue?id={valueId}&timestamp={ms_timestamp}
GET /xdap-app/dataDictionary/enable/dictionaryValue?id={valueId}&timestamp={ms_timestamp}
```

### 响应格式
```json
{
  "code": "ok",
  "message": "禁用数据字典值成功"
}
```

## Python 调用示例

### 编辑字典名称
```python
from app.apaas_client import APaaSClient

async def update_dict_name(client: APaaSClient, app_id: str, dictionary_id: str, new_name: str):
    """修改字典名称"""
    # 1. 先查询字典列表，获取当前字典信息
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={"keyword": "", "appId": app_id},
        app_id=app_id
    )
    dict_info = next(d for d in result["table"] if d["id"] == dictionary_id)

    # 2. 编辑字典
    await client.request(
        "POST",
        "/xdap-app/dataDictionary/edit/dataDictionary",
        json={
            "appId": app_id,
            "internalResource": True,
            "id": dict_info["id"],
            "dictionaryCode": dict_info["dictionaryCode"],
            "dictionaryName": new_name,
            "dictionaryNameI18nAssociated": False,
            "dictionaryNameI18nResourceCode": "",
            "dictionaryNameI18n": {},
            "dictionaryDescribe": dict_info.get("dictionaryDescribe", ""),
            "dictionaryMulticolorStatus": dict_info.get("dictionaryMulticolorStatus", "DISABLE"),
            "dictionaryStatus": dict_info.get("dictionaryStatus", "ENABLE")
        },
        app_id=app_id
    )
    print(f"字典名称已更新为: {new_name}")
```

### 给字典追加选项
```python
async def add_dict_option(
    client: APaaSClient,
    app_id: str,
    dictionary_id: str,
    option_code: str,
    option_name: str,
    display_order: int
):
    """给已有字典追加一个选项"""
    await client.request(
        "POST",
        "/xdap-app/dataDictionary/add/dictionaryValue",
        json={
            "appId": app_id,
            "dictionaryId": dictionary_id,
            "valueCode": option_code,
            "valueName": option_name,
            "valueNameI18nAssociated": False,
            "valueNameI18nResourceCode": "",
            "valueNameI18n": {},
            "displayOrder": display_order,
            "valueDescribe": "",
            "valueStatus": "ENABLE",
            "valueMulticolor": "#027AFF"
        },
        app_id=app_id
    )
    print(f"选项 {option_name} ({option_code}) 已追加")
```

### 批量追加选项
```python
async def add_dict_options_batch(
    client: APaaSClient,
    app_id: str,
    dictionary_id: str,
    options: list
):
    """批量追加选项

    options 格式:
    [
        {"name": "新选项1", "code": "opt1"},
        {"name": "新选项2", "code": "opt2"},
    ]
    """
    # 1. 查询已有选项，确定起始 displayOrder
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
    existing = result.get("table", [])
    existing_codes = {v["valueCode"] for v in existing}
    max_order = max((v["displayOrder"] for v in existing), default=-1)

    # 2. 逐个追加
    added = 0
    for opt in options:
        if opt["code"] in existing_codes:
            print(f"选项 {opt['code']} 已存在，跳过")
            continue
        max_order += 1
        await add_dict_option(
            client, app_id, dictionary_id,
            opt["code"], opt["name"], max_order
        )
        added += 1

    print(f"共追加 {added} 个选项")
```

### 完整流程：查询字典 → 追加选项
```python
async def extend_existing_dict(client: APaaSClient, app_id: str):
    """在已有字典上追加新选项的完整流程"""
    import random, string
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))

    # 1. 查询字典列表
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={"keyword": "会议类型", "appId": app_id},
        app_id=app_id
    )
    dict_info = result["table"][0]
    dictionary_id = dict_info["id"]

    # 2. 追加选项（编码需全局唯一，加后缀）
    new_options = [
        {"name": "视频会议", "code": f"video_meeting_{suffix}"},
        {"name": "电话会议", "code": f"phone_meeting_{suffix}"},
    ]

    await add_dict_options_batch(client, app_id, dictionary_id, new_options)
```

## 注意事项

### dictionaryCode 不可修改
- 编辑字典时 `dictionaryCode` 必须原样传回
- 只能修改 `dictionaryName`、`dictionaryDescribe`、`dictionaryMulticolorStatus` 等

### valueCode 全局唯一
- 追加选项时 `valueCode` 在所有字典中全局唯一
- **必须添加随机后缀**避免冲突
- 编辑选项时 `valueCode` 不可修改，原样传回

### 没有硬删除 API
- 不能删除字典或选项，只能禁用
- 禁用后选项不会在下拉框中显示
- 可以通过 `enable` 接口重新启用

### 无批量操作接口
- 追加选项一次只能添加一个
- 批量追加需要循环调用

### displayOrder 排序
- 追加选项时需查询已有选项的最大 `displayOrder`，然后接着排
- 从 0 开始

### 编辑字典需要完整参数
- 编辑字典时需传完整参数（id、dictionaryCode、dictionaryName 等）
- 建议先查询字典信息，修改目标字段后整体传回

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| - | 数据字典值编码重复 | valueCode 全局重复 | 添加随机后缀 |
| 500 | Internal Server Error | 时间戳格式错误 | 使用正确的毫秒时间戳 |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills
- `apaas-query-dict` — 查询字典及选项（获取 id 和 dictionaryCode）
- `apaas-create-dict` — 批量创建字典
- `apaas-comp-select-single` — 下拉单选组件（使用字典）
- `apaas-comp-select-multi` — 下拉多选组件（使用字典）
