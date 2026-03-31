# aPaaS Query Role

## 用途
查询应用下的角色列表，用于获取已有角色的 id、roleCode、roleName 等信息

## API 端点
```
POST /xdap-app/roles/query/rolesList
```

## 请求头
```json
{
  "Content-Type": "application/json;charset=UTF-8",
  "xdaptenantid": "<tenant_id>",
  "xdaptimestamp": "<millisecond_timestamp>",
  "xdaptoken": "<auth_token>"
}
```

## 请求参数
| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| keyWord | body | string | 否 | 关键字搜索（角色名称） |
| appId | body | string | 是 | 应用 ID |
| appQueryFlag | body | boolean | 是 | 是否按应用查询，通常为 `true` |

### 请求示例
```json
POST /xdap-app/roles/query/rolesList

{
  "keyWord": "",
  "appId": "822790159832449024",
  "appQueryFlag": true
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "查询角色列表成功",
  "data": [
    {
      "id": "822790180179017728",
      "roleCode": "R_cooperator_jbft",
      "roleName": "合作方",
      "roleNameI18nResourceCode": "i18n_pXZFXGXN",
      "roleNameI18nAssociated": false,
      "roleType": "APP",
      "status": "ENABLE",
      "appId": "822790159832449024",
      "enableGroupParam": "DISABLE",
      "roleTypeMeaning": "应用",
      "roleParams": [],
      "internalResource": true,
      "useScope": "劳务管理系统",
      "checked": false,
      "userCount": 0,
      "owner": "100169876816012509184",
      "createdBy": "100169876816012509184",
      "lastUpdatedBy": "100169876816012509184",
      "objectVersionNumber": 1,
      "creationDate": "2026-03-20 11:14:26",
      "lastUpdateDate": "2026-03-20 11:14:26"
    }
  ]
}
```

### 响应字段说明
| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 角色 ID（编辑/删除角色时作为 roleId 使用） |
| roleCode | string | 角色编码 |
| roleName | string | 角色名称 |
| status | string | 角色状态：ENABLE / DISABLE |
| appId | string | 所属应用 ID |
| enableGroupParam | string | 是否启用分组参数：ENABLE / DISABLE |
| roleType | string | 角色类型：APP（应用级）/ TENANT（租户级） |
| roleTypeMeaning | string | 角色类型含义，如 "应用" |
| roleParams | array | 角色参数列表 |
| internalResource | boolean | 是否为应用内部资源（`true` = 应用级角色） |
| useScope | string | 使用范围（应用名称或 "全部应用"） |
| userCount | integer | 角色下的用户数量 |
| checked | boolean | 是否选中（前端用） |
| owner | string | 所有者用户 ID |
| createdBy | string | 创建者用户 ID |
| lastUpdatedBy | string | 最后更新者用户 ID |
| objectVersionNumber | integer | 乐观锁版本号 |

## Python 调用示例

### 查询应用下所有角色
```python
from app.apaas_client import APaaSClient

async def query_roles(client: APaaSClient, app_id: str, keyword: str = ""):
    """查询应用下所有角色"""
    result = await client.request(
        "POST",
        "/xdap-app/roles/query/rolesList",
        json={
            "keyWord": keyword,
            "appId": app_id,
            "appQueryFlag": True
        },
        app_id=app_id
    )

    roles = result.get("data", [])
    print(f"共 {len(roles)} 个角色")
    for r in roles:
        internal = "应用级" if r.get("internalResource") else "全局"
        print(f"  [{internal}] {r['roleName']} ({r['roleCode']}) id={r['id']} users={r.get('userCount', 0)}")

    return roles
```

### 只获取应用级角色
```python
async def query_app_roles(client: APaaSClient, app_id: str):
    """只获取应用级角色（排除全局角色）"""
    result = await client.request(
        "POST",
        "/xdap-app/roles/query/rolesList",
        json={
            "keyWord": "",
            "appId": app_id,
            "appQueryFlag": True
        },
        app_id=app_id
    )

    app_roles = [r for r in result.get("data", []) if r.get("internalResource")]
    return app_roles
```

### 按 roleCode 查找角色
```python
async def find_role_by_code(client: APaaSClient, app_id: str, role_code: str):
    """按 roleCode 查找角色"""
    result = await client.request(
        "POST",
        "/xdap-app/roles/query/rolesList",
        json={
            "keyWord": "",
            "appId": app_id,
            "appQueryFlag": True
        },
        app_id=app_id
    )

    for r in result.get("data", []):
        if r["roleCode"] == role_code:
            return r
    return None
```

### 按关键字搜索角色
```python
async def search_roles(client: APaaSClient, app_id: str, keyword: str):
    """按关键字搜索角色"""
    result = await client.request(
        "POST",
        "/xdap-app/roles/query/rolesList",
        json={
            "keyWord": keyword,
            "appId": app_id,
            "appQueryFlag": True
        },
        app_id=app_id
    )

    return result.get("data", [])
```

## 注意事项

### 返回结果包含全局角色
- 返回结果包含应用级角色和全局角色
- 通过 `internalResource: true` 过滤应用级角色
- 通过 `useScope` 可以看到角色的使用范围

### 角色 ID 的用途
- `id` 字段即为 `roleId`，用于：
  - 编辑角色（`/roles/edit/role`）
  - 删除角色（`/roles/delete/role`）
  - 添加角色用户（`/roles/add/roleUsers`）

### 无分页
- 该接口直接返回所有角色（`data` 数组），无需分页参数

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | xdaptimestamp 格式错误 | 使用正确的毫秒时间戳 |
| 401 | 未授权 | token 过期 | 重新登录 |

## 相关 Skills

### 角色管理
- `apaas-create-role` — 批量创建角色
- `apaas-update-role` — 编辑角色
- `apaas-delete-role` — 删除角色
