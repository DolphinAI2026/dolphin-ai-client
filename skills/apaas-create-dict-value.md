# aPaaS Create Dictionary Value

## 用途
新增字典选项值

## API 端点
```
POST /xdap-app/dataDictionary/add/dictionaryValue
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
| dictionaryId | body | string | 是 | 所属字典 ID |
| appId | body | string | 是 | 应用 ID |
| valueCode | body | string | 是 | 值编码（唯一） |
| valueName | body | string | 是 | 值名称（显示名） |
| valueStatus | body | string | 是 | 状态：ENABLE / DISABLE |
| displayOrder | body | integer | 否 | 显示顺序，默认 0 |
| valueDescribe | body | string | 否 | 值描述 |
| valueMulticolor | body | string | 否 | 多色标签颜色（十六进制，如 #027AFF） |
| valueNameI18nAssociated | body | boolean | 否 | 是否关联国际化，默认 false |
| valueNameI18nResourceCode | body | string | 否 | 国际化资源编码 |
| valueNameI18n | body | object | 否 | 国际化配置对象 |

### 请求示例
```json
POST /xdap-app/dataDictionary/add/dictionaryValue

{
  "appId": "822790159832449024",
  "dictionaryId": "822869360979738624",
  "valueCode": "option_1",
  "valueName": "选项一",
  "valueStatus": "ENABLE",
  "displayOrder": 0,
  "valueDescribe": "这是选项一的描述",
  "valueMulticolor": "#027AFF",
  "valueNameI18nAssociated": false,
  "valueNameI18nResourceCode": "",
  "valueNameI18n": {}
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "新增数据字典值成功"
}
```

## Python 调用示例

### 新增单个字典值
```python
from app.apaas_client import APaaSClient

async def create_dict_value(
    client: APaaSClient,
    app_id: str,
    dict_id: str,
    value_code: str,
    value_name: str,
    color: str = "#027AFF",
    order: int = 0,
    description: str = ""
):
    """新增字典选项值"""
    result = await client.request(
        "POST",
        "/xdap-app/dataDictionary/add/dictionaryValue",
        json={
            "appId": app_id,
            "dictionaryId": dict_id,
            "valueCode": value_code,
            "valueName": value_name,
            "valueStatus": "ENABLE",
            "displayOrder": order,
            "valueDescribe": description,
            "valueMulticolor": color,
            "valueNameI18nAssociated": False,
            "valueNameI18nResourceCode": "",
            "valueNameI18n": {}
        },
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"字典值 {value_name} 创建成功")
    else:
        print(f"创建失败: {result.get('message')}")

    return result
```

### 批量新增字典值
```python
async def create_dict_values_batch(
    client: APaaSClient,
    app_id: str,
    dict_id: str,
    values: list[dict]
):
    """批量新增字典值

    Args:
        values: [{"code": "opt1", "name": "选项一", "color": "#027AFF"}, ...]
    """
    results = []
    for i, v in enumerate(values):
        result = await create_dict_value(
            client,
            app_id,
            dict_id,
            value_code=v["code"],
            value_name=v["name"],
            color=v.get("color", "#027AFF"),
            order=i,
            description=v.get("description", "")
        )
        results.append({"valueCode": v["code"], "result": result})
    return results
```

### 常用颜色列表
```python
# 常用多色标签颜色
DICT_VALUE_COLORS = {
    "blue": "#027AFF",
    "green": "#00B578",
    "red": "#FF3B30",
    "orange": "#FF9500",
    "purple": "#AF52DE",
    "gray": "#8E8E93",
    "yellow": "#FFCC00",
    "cyan": "#5AC8FA"
}

async def create_dict_value_with_color(
    client: APaaSClient,
    app_id: str,
    dict_id: str,
    value_code: str,
    value_name: str,
    color_name: str = "blue"
):
    """使用预设颜色创建字典值"""
    color = DICT_VALUE_COLORS.get(color_name, "#027AFF")
    return await create_dict_value(
        client, app_id, dict_id, value_code, value_name, color=color
    )
```

## 注意事项

### valueCode 唯一性
- 同一字典下 `valueCode` 必须唯一
- 建议使用小写字母和下划线命名

### 显示顺序
- `displayOrder` 控制选项在下拉列表中的显示顺序
- 数值越小越靠前

### 多色标签
- 需要字典启用 `dictionaryMulticolorStatus: ENABLE`
- 颜色使用十六进制格式

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | valueCode 已存在 | 使用不同的 valueCode |
| 500 | Internal Server Error | dictionaryId 不存在 | 检查字典 ID |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills

### 字典值管理
- `apaas-query-dict-value` — 查询字典值列表
- `apaas-update-dict-value` — 编辑字典值
- `apaas-enable-dict-value` — 启用字典值
- `apaas-disable-dict-value` — 禁用字典值

### 字典管理
- `apaas-query-dict` — 查询字典列表（获取 dictionaryId）
- `apaas-create-dict` — 批量创建字典
- `apaas-update-dict` — 编辑字典
- `apaas-enable-dict` — 启用字典
- `apaas-disable-dict` — 禁用字典
