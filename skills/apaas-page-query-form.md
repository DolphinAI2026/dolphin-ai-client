# aPaaS Query Form List

## 用途
分页查询租户下的表单配置列表，用于获取表单 ID、表单编码、表单名称、所属应用、menuId 等信息。

这个接口更偏向“表单后台列表查询”，和 `apaas-query-form` 中“按应用查询菜单 + 表单详情”是两类能力。

## API 端点

### 查询表单列表
```
GET /xdap-app/formConfig/query/allFormConfigList
```

## 请求头
```json
{
  "Content-Type": "application/json",
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>"
}
```

## 请求参数

### Query 参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | integer | 是 | 页码，从 1 开始 |
| pageSize | integer | 是 | 每页条数 |
| timestamp | integer | 否 | 时间戳，浏览器请求中常带，用于防缓存 |

### 请求示例
```
GET /xdap-app/formConfig/query/allFormConfigList?timestamp=1774676234394&page=1&pageSize=10
```

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "total": 26,
  "table": [
    {
      "id": "69c535bdcfa50072690bca01",
      "formCode": "form_contract",
      "formName": "合同",
      "formType": "MODEL",
      "createName": "萧轩",
      "creationData": "2026-03-26 21:33:49",
      "appId": "825120213669249024",
      "appName": "CRM客户管理系统",
      "menuId": "825120382561288192",
      "scopeOfAuthorization": "CURRENT_APP",
      "useScope": "CRM客户管理系统",
      "internalResource": true,
      "account": "17621440039"
    }
  ]
}
```

## 响应字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 表单 ID |
| formCode | string | 表单编码 |
| formName | string | 表单名称 |
| formType | string | 表单类型，常见为 `MODEL` |
| createName | string | 创建人姓名 |
| creationData | string | 创建时间 |
| appId | string | 所属应用 ID |
| appName | string | 所属应用名称 |
| menuId | string | 关联菜单 ID |
| scopeOfAuthorization | string | 授权范围 |
| useScope | string | 使用范围，通常是应用名称 |
| internalResource | boolean | 是否为应用内部资源 |
| account | string | 创建账号 |

## cURL 示例

### 最小可用写法
```bash
curl 'https://apaas-dev8.dfy.definesys.cn/backend/xdap-app/formConfig/query/allFormConfigList?page=1&pageSize=10' \
  -H 'accept: application/json, text/plain, */*' \
  -H 'xdaptenantid: <TENANT_ID>' \
  -H 'xdaptimestamp: <TIMESTAMP>' \
  -H 'xdaptoken: <XDAP_TOKEN>'
```

### 带 timestamp 的写法
```bash
curl 'https://apaas-dev8.dfy.definesys.cn/backend/xdap-app/formConfig/query/allFormConfigList?timestamp=<TIMESTAMP>&page=1&pageSize=10' \
  -H 'accept: application/json, text/plain, */*' \
  -H 'xdaptenantid: <TENANT_ID>' \
  -H 'xdaptimestamp: <TIMESTAMP>' \
  -H 'xdaptoken: <XDAP_TOKEN>'
```

## Python 调用示例

### 直接分页查询表单列表
```python
import httpx
from app.apaas_client import APaaSClient

async def query_form_list(client: APaaSClient, page: int = 1, page_size: int = 10):
    """分页查询租户下表单列表"""
    params = {
        "page": page,
        "pageSize": page_size,
    }
    url = f"{client.base_url}/xdap-app/formConfig/query/allFormConfigList"

    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        response = await http.get(
            url,
            headers=client._get_headers(),
            params=params,
        )
        response.raise_for_status()
        data = response.json()

    if data.get("code") != "ok":
        raise Exception(data.get("message", "查询表单列表失败"))

    table = data.get("table", [])
    print(f"共 {data.get('total', 0)} 个表单，当前返回 {len(table)} 条")
    for item in table:
        print(f"  {item['formName']} ({item['formCode']}) id={item['id']} app={item['appName']}")

    return table
```

### 按应用过滤表单列表
```python
async def filter_form_list_by_app(client: APaaSClient, target_app_id: str, page: int = 1, page_size: int = 100):
    """先查询列表，再按 appId 过滤"""
    forms = await query_form_list(client, page=page, page_size=page_size)
    return [item for item in forms if item.get("appId") == target_app_id]
```

### 构建 formCode -> formId 映射
```python
async def build_form_id_map(client: APaaSClient, page: int = 1, page_size: int = 200):
    """构建表单编码到表单 ID 的映射"""
    forms = await query_form_list(client, page=page, page_size=page_size)
    return {item["formCode"]: item["id"] for item in forms if item.get("formCode") and item.get("id")}
```

## 使用场景

### 场景 1: 通过 formCode 找 formId
- 适用于后续调用表单详情查询、表单权限配置、表单更新接口

### 场景 2: 统计某个应用下已创建的表单
- 先查全量列表
- 再按 `appId` 或 `appName` 过滤

### 场景 3: 排查表单名称异常
- 该接口会直接返回表单后台列表中的 `formName`
- 可用于定位类似 `formCode=form_customer` 但 `formName=我的待办` 的异常情况

## 注意事项

### 这是租户级列表接口，不是应用级接口
- 当前 curl 中没有 `appid` 请求头
- 返回结果会混合多个应用下的表单
- 如果只看某个应用，需要自行按 `appId` 过滤

### 浏览器头不是都必需
- `referer`
- `rsa-public-key`
- `sec-ch-*`
- `priority`
- `user-agent`

这些是浏览器自动带上的调试头，服务端脚本通常不需要。

### 最关键的头是这几个
- `xdaptenantid`
- `xdaptimestamp`
- `xdaptoken`

### timestamp 参数通常可选
- Query 参数里的 `timestamp` 更像防缓存参数
- 真正鉴权更依赖请求头中的 `xdaptimestamp`

### formName 可能和业务预期不一致
- 返回中的 `formName` 是平台当前记录的表单名称
- 如果平台菜单或表单元数据被默认值污染，可能出现 `formCode` 正常但 `formName` 为“我的待办”的情况

### 当前仓库没有现成的 APaaSClient 封装方法
- 这个接口目前没有像 `query_dicts()`、`query_models()` 那样封装成专用方法
- 使用时建议直接 `httpx.get(...)` 调用
