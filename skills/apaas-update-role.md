# aPaaS Update Role

## 用途
编辑已有角色（修改名称、参数化配置）、管理角色用户（添加/删除/查询）

## API 端点

### 编辑角色
```
POST /xdap-app/roles/edit/role
```

### 删除角色
```
POST /xdap-app/roles/delete/role
```

### 查询角色用户
```
POST /xdap-app/roles/query/roleUsers
```

### 添加角色用户
```
POST /xdap-app/roles/add/roleUsers
```

### 删除角色用户
```
POST /xdap-app/roles/delete/roleUsers
```

### 按 userId 查询用户信息
```
POST /xdap-admin/user/query/userList
```

### 按关键字搜索用户
```
POST /xdap-app/user/select/queryAllUsers
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

## 编辑角色

### 请求格式
```json
{
  "appId": "755484864311984128",
  "useScope": "AI场景演示",
  "internalResource": true,
  "roleCode": "host_rfmz",
  "roleName": "主持人（新名称）",
  "roleNameI18nAssociated": false,
  "roleNameI18nResourceCode": "",
  "roleNameI18n": {},
  "enableGroupParam": "DISABLE",
  "roleId": "758716287122669568",
  "roleParams": []
}
```

### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| appId | string | 是 | 应用 ID |
| roleId | string | 是 | 角色 ID（从查询接口获取的 `id`） |
| roleCode | string | 是 | 角色编码（**不可修改**，原样传回） |
| roleName | string | 是 | 角色名称（可修改） |
| useScope | string | 是 | 使用范围（应用名称） |
| internalResource | boolean | 是 | 应用级角色传 `true` |
| enableGroupParam | string | 是 | 是否启用分组参数：`"ENABLE"` / `"DISABLE"` |
| roleParams | array | 是 | 角色参数列表（不使用时传 `[]`） |
| roleNameI18nAssociated | boolean | 是 | 是否关联国际化，通常传 `false` |
| roleNameI18nResourceCode | string | 否 | 国际化资源编码，通常传 `""` |
| roleNameI18n | object | 否 | 国际化文本，通常传 `{}` |

### 响应格式
```json
{
  "code": "ok",
  "message": "编辑角色成功"
}
```

## 删除角色

### 请求格式
```json
{
  "roleId": "758716287122669568"
}
```

### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| roleId | string | 是 | 角色 ID |

### 响应格式
```json
{
  "code": "ok",
  "message": "删除角色成功"
}
```

## Python 调用示例

### 修改角色名称
```python
from app.apaas_client import APaaSClient

async def update_role_name(client: APaaSClient, app_id: str, role_id: str, new_name: str):
    """修改角色名称"""
    # 1. 先查询角色信息
    result = await client.request(
        "GET",
        f"/xdap-app/user/select/queryRoleList?appId={app_id}",
        app_id=app_id
    )
    role_info = next(r for r in result["table"] if r["id"] == role_id)

    # 2. 编辑角色
    await client.request(
        "POST",
        "/xdap-app/roles/edit/role",
        json={
            "appId": app_id,
            "useScope": role_info.get("useScope", ""),
            "internalResource": role_info.get("internalResource", True),
            "roleCode": role_info["roleCode"],
            "roleName": new_name,
            "roleNameI18nAssociated": False,
            "roleNameI18nResourceCode": "",
            "roleNameI18n": {},
            "enableGroupParam": role_info.get("enableGroupParam", "DISABLE"),
            "roleId": role_id,
            "roleParams": []
        },
        app_id=app_id
    )
    print(f"角色名称已更新为: {new_name}")
```

### 删除角色
```python
async def delete_role(client: APaaSClient, app_id: str, role_id: str):
    """删除角色"""
    await client.request(
        "POST",
        "/xdap-app/roles/delete/role",
        json={"roleId": role_id},
        app_id=app_id
    )
    print(f"角色 {role_id} 已删除")
```

### 完整流程：查询角色 → 修改名称
```python
async def rename_role_by_code(client: APaaSClient, app_id: str, role_code: str, new_name: str):
    """按 roleCode 查找角色并修改名称"""
    # 1. 查询角色
    result = await client.request(
        "GET",
        f"/xdap-app/user/select/queryRoleList?appId={app_id}",
        app_id=app_id
    )

    role_info = None
    for r in result.get("table", []):
        if r["roleCode"] == role_code:
            role_info = r
            break

    if not role_info:
        print(f"角色 {role_code} 不存在")
        return

    # 2. 修改名称
    await update_role_name(client, app_id, role_info["id"], new_name)
```

## 角色用户管理

### 查询角色用户

#### 请求格式
```json
{
  "roleId": "821082718791008256",
  "page": 1,
  "size": 10
}
```

#### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| roleId | string | 是 | 角色 ID |
| page | integer | 是 | 页码（从 1 开始） |
| size | integer | 是 | 每页数量 |

#### 响应格式
```json
{
  "code": "ok",
  "message": "查询角色用户列表成功",
  "total": 1,
  "table": [
    {
      "roleId": "821082718791008256",
      "id": "821089218645196800",
      "userId": "100169876816012509184",
      "userName": "萧轩",
      "phone": "+86-176****0039",
      "workStatus": "WORK",
      "workStatusMeaning": "在职",
      "exitStatus": "ENABLE",
      "account": "17621440039",
      "accountStatus": "ENABLE",
      "roleUserParamGroupDtoList": [
        {
          "groupId": "821089218687139840",
          "groupName": "参数组1",
          "roleUserParams": []
        }
      ]
    }
  ]
}
```

#### 响应字段说明
| 字段 | 说明 |
|------|------|
| id | 角色-用户关系 ID（删除时需要） |
| userId | 用户 ID（添加时使用） |
| userName | 用户姓名 |
| account | 登录账号 |
| workStatus | 在职状态：WORK（在职）等 |

### 添加角色用户

#### 请求格式
```json
{
  "roleId": "821082718791008256",
  "userIdList": ["100169876816012509184"]
}
```

#### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| roleId | string | 是 | 角色 ID |
| userIdList | array | 是 | 用户 ID 数组（支持批量添加） |

#### 响应格式
```json
{
  "code": "ok",
  "message": "添加成功"
}
```

### 删除角色用户

#### 请求格式
```json
{
  "id": "821089218645196800",
  "roleId": "821082718791008256",
  "userId": "100169876816012509184"
}
```

#### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | 是 | 角色-用户关系 ID（从 `roles/query/roleUsers` 获取） |
| roleId | string | 是 | 角色 ID |
| userId | string | 是 | 用户 ID |

#### 响应格式
```json
{
  "code": "ok",
  "message": "删除成功"
}
```

### 按 userId 查询用户信息

#### 请求格式
```json
["100169876816012509184"]
```

> 注意：请求体是 **JSON 数组**（不是对象），元素为 userId 字符串。

#### 响应格式
```json
[
  {
    "id": "100169876816012509184",
    "account": "17621440039",
    "phone": "17621440039",
    "username": "萧轩",
    "status": "ENABLE",
    "accountType": "FORMAL"
  }
]
```

> 注意：此接口在 `xdap-admin` 下，不在 `xdap-app` 下。

### 按关键字搜索用户

#### 请求格式
```json
{
  "page": 1,
  "pageSize": 100,
  "keyWord": "刘鑫"
}
```

#### 参数说明
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | integer | 是 | 页码（从 1 开始） |
| pageSize | integer | 是 | 每页数量 |
| keyWord | string | 是 | 搜索关键字（姓名、账号、手机号） |

#### 响应格式
```json
{
  "code": "ok",
  "message": "操作成功",
  "total": 100000,
  "table": [
    {
      "id": "100295140271014805504",
      "username": "刘鑫",
      "phone": "18616380646",
      "account": "18616380646",
      "commonDepartment": []
    }
  ]
}
```

#### 响应字段说明
| 字段 | 说明 |
|------|------|
| id | 用户 ID（即 userId，添加到角色时使用） |
| username | 用户姓名 |
| account | 登录账号 |
| phone | 手机号 |

## Python 调用示例（角色用户管理）

### 查询角色下的用户
```python
async def query_role_users(client: APaaSClient, app_id: str, role_id: str, page: int = 1, size: int = 100):
    """查询角色下的用户列表"""
    result = await client.request(
        "POST",
        "/xdap-app/roles/query/roleUsers",
        json={"roleId": role_id, "page": page, "size": size},
        app_id=app_id
    )
    users = result.get("table", [])
    print(f"角色共 {result.get('total', 0)} 个用户")
    for u in users:
        print(f"  {u['userName']} (userId={u['userId']}, account={u['account']}, 关系ID={u['id']})")
    return users
```

### 添加用户到角色
```python
async def add_users_to_role(client: APaaSClient, app_id: str, role_id: str, user_ids: list):
    """批量添加用户到角色"""
    await client.request(
        "POST",
        "/xdap-app/roles/add/roleUsers",
        json={"roleId": role_id, "userIdList": user_ids},
        app_id=app_id
    )
    print(f"已添加 {len(user_ids)} 个用户到角色")
```

### 从角色删除用户
```python
async def remove_user_from_role(client: APaaSClient, app_id: str, role_id: str, user_id: str):
    """从角色中删除用户（需先查询获取关系 ID）"""
    # 1. 查询角色用户，获取关系 ID
    users = await query_role_users(client, app_id, role_id)
    target = next((u for u in users if u["userId"] == user_id), None)
    if not target:
        print(f"用户 {user_id} 不在角色中")
        return

    # 2. 删除
    await client.request(
        "POST",
        "/xdap-app/roles/delete/roleUsers",
        json={
            "id": target["id"],
            "roleId": role_id,
            "userId": user_id
        },
        app_id=app_id
    )
    print(f"已从角色中删除用户: {target['userName']}")
```

### 完整流程：按用户名搜索并添加到角色
```python
async def add_user_by_name_to_role(
    client: APaaSClient,
    app_id: str,
    role_code: str,
    user_name: str
):
    """按用户名搜索并添加到角色"""
    # 1. 搜索用户
    result = await client.request(
        "POST",
        "/xdap-app/user/select/queryAllUsers",
        json={"page": 1, "pageSize": 100, "keyWord": user_name},
        app_id=app_id
    )

    users = result.get("table", [])
    target_user = next(
        (u for u in users if u.get("username") == user_name),
        None
    )
    if not target_user:
        print(f"未找到用户: {user_name}")
        return

    user_id = target_user["id"]
    print(f"找到用户: {target_user['username']} (userId={user_id})")

    # 2. 查询目标角色
    result = await client.request(
        "GET",
        f"/xdap-app/user/select/queryRoleList?appId={app_id}",
        app_id=app_id
    )
    target_role = next(
        (r for r in result["table"] if r["roleCode"] == role_code),
        None
    )
    if not target_role:
        print(f"角色 {role_code} 不存在")
        return

    # 3. 添加用户到角色
    await client.request(
        "POST",
        "/xdap-app/roles/add/roleUsers",
        json={"roleId": target_role["id"], "userIdList": [user_id]},
        app_id=app_id
    )
    print(f"已将 {user_name} 添加到角色 {target_role['roleName']}")
```

## 注意事项

### roleCode 不可修改
- 编辑角色时 `roleCode` 必须原样传回
- 只能修改 `roleName`、`enableGroupParam`、`roleParams` 等

### roleId 的来源
- 查询接口 `queryRoleList` 返回的 `id` 字段即为 `roleId`
- 编辑和删除都需要此 ID

### 删除角色的风险
- 删除角色是**硬删除**，不可恢复
- 如果角色下有用户或被流程引用，删除可能失败
- 建议先确认角色的 `userCount` 为 0 再删除

### 编辑需要传完整参数
- 编辑时必须传 roleId、roleCode、roleName、enableGroupParam 等
- 建议先查询角色信息，修改目标字段后整体传回

### 角色用户管理
- **搜索用户**使用 `POST /xdap-app/user/select/queryAllUsers`，支持按姓名、账号、手机号搜索
- **添加用户**需要 `userId`，可通过以下方式获取：
  - 使用 `queryAllUsers` 按关键字搜索
  - 从已有角色的 `roles/query/roleUsers` 结果中查找
  - 通过 `POST /xdap-admin/user/query/userList`（传 userId 数组）查询已知用户
- **删除用户**需要三个 ID：角色-用户关系 `id`、`roleId`、`userId`
  - 关系 `id` 必须通过 `roles/query/roleUsers` 查询获得
- 添加已存在于角色中的用户不会报错（幂等操作）
- 删除用户是硬删除，用户从角色中立即移除

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| - | 角色不存在 | roleId 错误 | 先查询获取正确的 roleId |
| - | 角色编码已存在 | roleCode 冲突 | roleCode 不能改，原样传回 |
| 500 | Internal Server Error | 时间戳格式错误 | 使用正确的毫秒时间戳 |
| 401 | 未授权 | token 过期 | 重新登录 |

| - | 参数为空 | 删除角色用户时缺少 id/roleId/userId | 三个字段都必传 |

## 相关 Skills
- `apaas-query-role` — 查询角色列表（获取 roleId 和 roleCode）
- `apaas-create-role` — 批量创建角色
