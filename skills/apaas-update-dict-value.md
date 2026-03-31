# aPaaS Update Dictionary Value

## 用途
编辑/更新字典选项值

## API 端点
```
POST /xdap-app/dataDictionary/edit/dictionaryValue/fromApp
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
| id | body | string | 是 | 要编辑的字典值 ID |
| dictionaryId | body | string | 是 | 所属字典 ID |
| appId | body | string | 是 | 应用 ID |
| valueCode | body | string | 是 | 值编码（不可修改） |
| valueName | body | string | 是 | 值名称（显示名） |
| valueStatus | body | string | 是 | 状态：ENABLE / DISABLE |
| displayOrder | body | integer | 否 | 显示顺序 |
| valueDescribe | body | string | 否 | 值描述 |
| valueMulticolor | body | string | 否 | 多色标签颜色 |
| valueNameI18nAssociated | body | boolean | 否 | 是否关联国际化 |
| valueNameI18n | body | object | 否 | 国际化配置对象 |

### 请求示例
```json
POST /xdap-app/dataDictionary/edit/dictionaryValue/fromApp

{
  "id": "822872563364397056",
  "appId": "822790159832449024",
  "dictionaryId": "822869360979738624",
  "valueCode": "ceshi",
  "valueName": "测试名称（已修改）",
  "valueStatus": "ENABLE",
  "displayOrder": 0,
  "valueDescribe": "更新后的描述",
  "valueMulticolor": "#027AFF",
  "valueNameI18nAssociated": false,
  "valueNameI18n": {}
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "编辑数据字典值成功"
}
```

## Python 调用示例

### 更新字典值名称
```python
from app.apaas_client import APaaSClient

async def update_dict_value_name(
    client: APaaSClient,
    app_id: str,
    dict_id: str,
    value_id: str,
    new_name: str
):
    """更新字典值名称"""
    # 先查询字典值信息
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

    # 找到目标值
    value_info = None
    for v in query_result.get("table", []):
        if v["id"] == value_id:
            value_info = v
            break

    if not value_info:
        print(f"未找到字典值 {value_id}")
        return None

    # 更新
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/edit/dictionaryValue/fromApp",
        json={
            "id": value_id,
            "appId": app_id,
            "dictionaryId": dict_id,
            "valueCode": value_info["valueCode"],
            "valueName": new_name,
            "valueStatus": value_info["valueStatus"],
            "displayOrder": value_info.get("displayOrder", 0),
            "valueDescribe": value_info.get("valueDescribe", ""),
            "valueMulticolor": value_info.get("valueMulticolor", "#027AFF"),
            "valueNameI18nAssociated": value_info.get("valueNameI18nAssociated", False),
            "valueNameI18n": {}
        },
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"字典值更新成功，新名称: {new_name}")

    return result
```

### 通用字典值更新
```python
async def update_dict_value(
    client: APaaSClient,
    app_id: str,
    dict_id: str,
    value_id: str,
    updates: dict
):
    """通用字典值更新方法"""
    # 先查询字典值信息
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

    value_info = next((v for v in query_result.get("table", []) if v["id"] == value_id), None)
    if not value_info:
        print(f"未找到字典值 {value_id}")
        return None

    # 合并更新
    payload = {
        "id": value_id,
        "appId": app_id,
        "dictionaryId": dict_id,
        "valueCode": value_info["valueCode"],  # 不可修改
        "valueName": updates.get("valueName", value_info["valueName"]),
        "valueStatus": updates.get("valueStatus", value_info["valueStatus"]),
        "displayOrder": updates.get("displayOrder", value_info.get("displayOrder", 0)),
        "valueDescribe": updates.get("valueDescribe", value_info.get("valueDescribe", "")),
        "valueMulticolor": updates.get("valueMulticolor", value_info.get("valueMulticolor", "#027AFF")),
        "valueNameI18nAssociated": updates.get("valueNameI18nAssociated", value_info.get("valueNameI18nAssociated", False)),
        "valueNameI18n": updates.get("valueNameI18n", {})
    }

    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/edit/dictionaryValue/fromApp",
        json=payload,
        app_id=app_id
    )

    return result
```

## 注意事项

### valueCode 不可修改
- `valueCode` 字段在创建后不可修改
- 编辑时必须传入原始 `valueCode`

### 需要完整数据
- 编辑接口需要传入完整的字典值数据
- 建议先查询字典值详情，修改需要的字段后再提交

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | id 不存在 | 检查字典值 ID |
| 500 | Internal Server Error | valueCode 与原值不一致 | 使用原始 valueCode |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills

### 字典值管理
- `apaas-query-dict-value` — 查询字典值列表（获取详情）
- `apaas-create-dict-value` — 新增字典值
- `apaas-enable-dict-value` — 启用字典值
- `apaas-disable-dict-value` — 禁用字典值

### 字典管理
- `apaas-query-dict` — 查询字典列表（获取 dictionaryId）
- `apaas-create-dict` — 批量创建字典
- `apaas-update-dict` — 编辑字典
- `apaas-enable-dict` — 启用字典
- `apaas-disable-dict` — 禁用字典
