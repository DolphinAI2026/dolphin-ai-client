# aPaaS Delete Role

## 用途
删除应用下的角色

## API 端点
```
POST /xdap-app/roles/delete/role
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
| roleId | body | string | 是 | 要删除的角色 ID |

### 请求示例
```json
POST /xdap-app/roles/delete/role

{
  "roleId": "822846607358689280"
}
```

## 响应格式
```json
{
  "code": "ok",
  "message": "操作成功"
}
```

## Python 调用示例

### 删除单个角色
```python
from app.apaas_client import APaaSClient

async def delete_role(client: APaaSClient, app_id: str, role_id: str):
    """删除指定角色"""
    result = await client.request(
        "POST",
        "/xdap-app/roles/delete/role",
        json={"roleId": role_id},
        app_id=app_id
    )

    if result.get("code") == "ok":
        print(f"角色 {role_id} 删除成功")
    else:
        print(f"删除失败: {result.get('message')}")

    return result
```

### 批量删除角色
```python
async def delete_roles_batch(client: APaaSClient, app_id: str, role_ids: list[str]):
    """批量删除多个角色"""
    results = []
    for role_id in role_ids:
        result = await delete_role(client, app_id, role_id)
        results.append({"roleId": role_id, "result": result})
    return results
```

### 按 roleCode 删除角色
```python
async def delete_role_by_code(client: APaaSClient, app_id: str, role_code: str):
    """按 roleCode 查找并删除角色"""
    # 先查询角色列表
    query_result = await client.request(
        "POST",
        "/xdap-app/roles/query/rolesList",
        json={
            "keyWord": "",
            "appId": app_id,
            "appQueryFlag": True
        },
        app_id=app_id
    )

    # 查找匹配的角色
    for role in query_result.get("data", []):
        if role["roleCode"] == role_code:
            return await delete_role(client, app_id, role["id"])

    print(f"未找到 roleCode={role_code} 的角色")
    return None
```

## 注意事项

### 删除限制
- 只能删除应用级角色（`internalResource: true`）
- 全局角色无法通过此接口删除
- 删除前建议检查角色下是否有用户（`userCount > 0`）

### 不可恢复
- 角色删除后无法恢复
- 建议删除前先备份角色配置

## 常见错误

| 错误码 | 错误信息 | 原因 | 解决方法 |
|--------|---------|------|---------|
| 500 | Internal Server Error | roleId 不存在 | 检查 roleId 是否正确 |
| 401 | 未授权 | token 过期 | 重新登录 |
| 403 | 无权限 | 无权删除该角色 | 检查用户权限 |

## 相关 Skills

### 角色管理
- `apaas-query-role` — 查询角色列表（获取 roleId）
- `apaas-create-role` — 批量创建角色
- `apaas-update-role` — 编辑角色
