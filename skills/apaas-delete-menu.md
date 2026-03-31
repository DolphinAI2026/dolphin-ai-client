# aPaaS Delete Menu

## 用途
删除应用下的菜单项，用于移除表单菜单或普通菜单。

在当前项目里，这个接口也用于删除表单：删除时传入的是表单对应的 `menuId`，不是 `formId`。

## API 端点

### 删除菜单
```
POST /xdap-app/menu/delete/menu
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

## 请求格式
```json
{
  "id": "825727201633632256",
  "appId": "825726475842879488",
  "menuName": "服务工单"
}
```

## 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | 是 | 菜单 ID，也就是 `menuId` |
| appId | string | 是 | 应用 ID |
| menuName | string | 是 | 菜单名称 |

## Query 参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| timestamp | integer | 否 | 时间戳，浏览器请求中常带，用于防缓存 |

### 请求示例
```
POST /xdap-app/menu/delete/menu?timestamp=1774680964583
```

## 响应格式
```json
{
  "code": "ok",
  "message": "删除菜单功能成功"
}
```

## 响应字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| code | string | `ok` 表示成功 |
| message | string | 响应消息 |

## cURL 示例

### 最小可用写法
```bash
curl 'https://apaas-dev8.dfy.definesys.cn/backend/xdap-app/menu/delete/menu' \
  -H 'accept: application/json, text/plain, */*' \
  -H 'content-type: application/json' \
  -H 'appid: <APP_ID>' \
  -H 'xdaptenantid: <TENANT_ID>' \
  -H 'xdaptimestamp: <TIMESTAMP>' \
  -H 'xdaptoken: <XDAP_TOKEN>' \
  --data-raw '{
    "id": "<MENU_ID>",
    "appId": "<APP_ID>",
    "menuName": "<MENU_NAME>"
  }'
```

### 带 timestamp 的写法
```bash
curl 'https://apaas-dev8.dfy.definesys.cn/backend/xdap-app/menu/delete/menu?timestamp=<TIMESTAMP>' \
  -H 'accept: application/json, text/plain, */*' \
  -H 'content-type: application/json' \
  -H 'appid: <APP_ID>' \
  -H 'xdaptenantid: <TENANT_ID>' \
  -H 'xdaptimestamp: <TIMESTAMP>' \
  -H 'xdaptoken: <XDAP_TOKEN>' \
  --data-raw '{
    "id": "<MENU_ID>",
    "appId": "<APP_ID>",
    "menuName": "<MENU_NAME>"
  }'
```

## Python 调用示例

### 直接删除菜单
```python
import httpx
from app.apaas_client import APaaSClient

async def delete_menu(client: APaaSClient, app_id: str, menu_id: str, menu_name: str):
    """删除指定菜单"""
    url = f"{client.base_url}/xdap-app/menu/delete/menu"
    payload = {
        "id": menu_id,
        "appId": app_id,
        "menuName": menu_name,
    }

    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        response = await http.post(
            url,
            headers=client._get_headers(app_id),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    if data.get("code") != "ok":
        raise Exception(data.get("message", "删除菜单失败"))

    print(f"删除成功: {menu_name} ({menu_id})")
    return data
```

### 删除表单对应菜单
```python
async def delete_form_menu(client: APaaSClient, app_id: str, menu_id: str, form_name: str):
    """删除表单对应的菜单项"""
    return await delete_menu(client, app_id, menu_id, form_name)
```

### 结合当前项目的增量删除逻辑
```python
async def delete_form_change(client: APaaSClient, app_id: str, change):
    """模拟当前项目 incremental_executor 里的表单删除逻辑"""
    payload = {
        "id": change.menu_id,
        "appId": app_id,
        "menuName": change.name,
    }

    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        response = await http.post(
            f"{client.base_url}/xdap-app/menu/delete/menu",
            headers=client._get_headers(app_id),
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    if data.get("code") != "ok":
        raise Exception(data.get("message", "删除菜单失败"))

    return data
```

## 使用场景

### 场景 1: 删除表单菜单
- 先通过 [apaas-query-form](./apaas-query-form.md) 或 [apaas-query-form-list](./apaas-query-form-list.md) 获取 `menuId`
- 再调用本接口删除

### 场景 2: 增量更新时删除表单
- 当前项目里删除表单时，实际上调用的是删除菜单接口
- 使用的是 `menuId`，不是 `formId`

### 场景 3: 清理误创建的菜单
- 已知菜单名称和 `menuId`
- 需要快速从应用导航中移除

## 注意事项

### 删除时传的是 menuId，不是 formId
- 这是最容易传错的地方
- 表单详情里的 `formId` 不能直接用于这个接口

### appId 必须和菜单所属应用一致
- 请求头中的 `appid`
- 请求体中的 `appId`
- 菜单本身所属应用

这三者需要一致。

### menuName 建议传当前平台上的真实名称
- 接口请求体要求 `menuName`
- 为了避免名称不一致导致异常，建议先查询后再删除

### 浏览器头不是都必需
- `referer`
- `origin`
- `rsa-public-key`
- `sec-ch-*`
- `priority`
- `user-agent`

这些通常是浏览器自动带上的调试头，服务端脚本一般不需要。

### 最关键的头是这几个
- `appid`
- `xdaptenantid`
- `xdaptimestamp`
- `xdaptoken`

### timestamp 参数通常可选
- Query 参数里的 `timestamp` 更像防缓存参数
- 真正鉴权更依赖请求头中的 `xdaptimestamp`

### 当前仓库没有现成的 APaaSClient.delete_menu() 封装
- 当前项目里是增量执行器直接发请求调用这个接口
- 参考位置见 `backend/app/incremental_executor.py`
