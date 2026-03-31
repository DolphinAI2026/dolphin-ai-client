# aPaaS Update Dictionary

## 用途
编辑/更新应用下的数据字典信息

## API 端点
```
POST /xdap-app/dataDictionary/edit/dataDictionary/fromApp
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
| id | body | string | 是 | 要编辑的字典 ID |
| appId | body | string | 是 | 应用 ID |
| dictionaryCode | body | string | 是 | 字典编码（不可修改，需与原值一致） |
| dictionaryName | body | string | 是 | 字典名称 |
| dictionaryDescribe | body | string | 否 | 字典描述 |
| dictionaryStatus | body | string | 是 | 字典状态：ENABLE / DISABLE |
| dictionaryMulticolorStatus | body | string | 是 | 多色标签状态：ENABLE / DISABLE |
| internalResource | body | boolean | 是 | 是否为应用内部资源，通常为 `true` |
| dictionaryNameI18nAssociated | body | boolean | 否 | 是否关联国际化，默认 `false` |
| dictionaryNameI18nResourceCode | body | string | 否 | 国际化资源编码 |
| dictionaryNameI18n | body | object | 否 | 国际化配置对象 |

### 请求示例
```json
POST /xdap-app/dataDictionary/edit/dataDictionary/fromApp

{
  "id": "822869360979738624",
  "appId": "822790159832449024",
  "dictionaryCode": "test_1",
  "dictionaryName": "测试字典",
  "dictionaryDescribe": "这是一个测试字典",
  "dictionaryStatus": "ENABLE",
  "dictionaryMulticolorStatus": "ENABLE",
  "internalResource": true,
  "dictionaryNameI18nAssociated": false,
  "dictionaryNameI18nResourceCode": "",
  "dictionaryNameI18n": {}
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "编辑数据字典成功"
}
```

## Python 调用示例

### 更新字典名称
```python
from app.apaas_client import APaaSClient

async def update_dict_name(client: APaaSClient, app_id: str, dict_id: str, new_name: str):
    """更新字典名称"""
    # 先查询字典信息
    query_result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={
            "keyword": "",
            "appId": app_id
        },
        app_id=app_id
    )

    # 找到目标字典
    dict_info = None
    for d in query_result.get("table", []):
        if d["id"] == dict_id:
            dict_info = d
            break

    if not dict_info:
        print(f"未找到字典 {dict_id}")
        return None

    # 更新字典
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/edit/dataDictionary/fromApp",
        json={
            "id": dict_id,
            "appId": app_id,
            "dictionaryCode": dict_info["dictionaryCode"],
            "dictionaryName": new_name,
            "dictionaryDescribe": dict_info.get("dictionaryDescribe", ""),
            "dictionaryStatus": dict_info["dictionaryStatus"],
            "dictionaryMulticolorStatus": dict_info["dictionaryMulticolorStatus"],
            "internalResource": dict_info["internalResource"],
            "dictionaryNameI18nAssociated": dict_info.get("dictionaryNameI18nAssociated", False),
            "dictionaryNameI18nResourceCode": dict_info.get("dictionaryNameI18nResourceCode", ""),
            "dictionaryNameI18n": {}
        },
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"字典 {dict_id} 更新成功，新名称: {new_name}")
    else:
        print(f"更新失败: {result.get('message')}")

    return result
```

### 通用字典更新
```python
async def update_dictionary(client: APaaSClient, app_id: str, dict_id: str, updates: dict):
    """通用字典更新方法"""
    # 先查询字典信息
    query_result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/query/dataDictionaryList",
        json={
            "keyword": "",
            "appId": app_id
        },
        app_id=app_id
    )

    dict_info = next((d for d in query_result.get("table", []) if d["id"] == dict_id), None)
    if not dict_info:
        print(f"未找到字典 {dict_id}")
        return None

    # 构建更新数据，合并原有数据和更新字段
    payload = {
        "id": dict_id,
        "appId": app_id,
        "dictionaryCode": dict_info["dictionaryCode"],  # dictionaryCode 不可修改
        "dictionaryName": updates.get("dictionaryName", dict_info["dictionaryName"]),
        "dictionaryDescribe": updates.get("dictionaryDescribe", dict_info.get("dictionaryDescribe", "")),
        "dictionaryStatus": updates.get("dictionaryStatus", dict_info["dictionaryStatus"]),
        "dictionaryMulticolorStatus": updates.get("dictionaryMulticolorStatus", dict_info["dictionaryMulticolorStatus"]),
        "internalResource": updates.get("internalResource", dict_info["internalResource"]),
        "dictionaryNameI18nAssociated": updates.get("dictionaryNameI18nAssociated", dict_info.get("dictionaryNameI18nAssociated", False)),
        "dictionaryNameI18nResourceCode": updates.get("dictionaryNameI18nResourceCode", dict_info.get("dictionaryNameI18nResourceCode", "")),
        "dictionaryNameI18n": updates.get("dictionaryNameI18n", {})
    }

    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/edit/dataDictionary/fromApp",
        json=payload,
        app_id=app_id
    )

    return result
```

## 注意事项

### dictionaryCode 不可修改
- `dictionaryCode` 字段在创建后不可修改
- 编辑时必须传入原始 `dictionaryCode`，否则可能导致错误

### 需要完整数据
- 编辑接口需要传入完整的字典数据
- 建议先查询字典详情，修改需要的字段后再提交

### 多色标签状态
- `dictionaryMulticolorStatus` 控制字典值是否支持多色显示
- 启用后可以为每个字典值设置不同的颜色

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | id 不存在 | 检查字典 ID 是否正确 |
| 500 | Internal Server Error | dictionaryCode 与原值不一致 | 使用原始 dictionaryCode |
| 401 | 未授权 | token 过期 | 重新登录 |
| 403 | 无权限 | 无权编辑该字典 | 检查用户权限 |

## 相关 Skills

### 字典管理
- `apaas-query-dict` — 查询字典列表（获取字典详情）
- `apaas-create-dict` — 批量创建字典
- `apaas-enable-dict` — 启用字典
- `apaas-disable-dict` — 禁用字典

### 字典值管理
- `apaas-query-dict-value` — 查询字典值列表
- `apaas-create-dict-value` — 新增字典值
- `apaas-update-dict-value` — 编辑字典值
- `apaas-enable-dict-value` — 启用字典值
- `apaas-disable-dict-value` — 禁用字典值
