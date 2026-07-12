# aPaaS 租户环境绑定设计

## 目标

在现有平台管理的“aPaaS 租户”页面提供环境绑定界面，使一个 Builder 本地租户绑定一个默认 aPaaS 环境，并复用已配置的平台管理员账号完成后续认证。

## 范围

- 一个 Builder 租户只维护一个默认 aPaaS 环境。
- 不启用当前占位的完整“平台环境”页面。
- 不增加新的数据库模型。
- 不在前端展示或返回密码、密码密文和 Token。
- 复用现有 `Tenant`、`PlatformEnv` 和 `APaaSPlatformCredential`。

## 页面交互

入口保持为：

```text
平台管理 -> aPaaS 租户
```

租户列表增加：

- “环境绑定”状态：已绑定或未绑定。
- 已绑定的 aPaaS 租户 ID。
- “绑定环境”或“修改绑定”操作。

绑定弹窗包含：

- 平台管理员账号：默认使用页面当前选中的账号，可切换。
- aPaaS 地址：优先使用已有环境地址，其次使用系统配置地址。
- aPaaS 租户 ID：优先使用租户同步结果。

保存成功后关闭弹窗并刷新当前租户列表。

## 后端接口

在现有 `/api/mcp-platform` 下增加单一绑定接口：

```text
PUT /api/mcp-platform/apaas-tenants/{local_tenant_id}/binding
```

请求字段：

```json
{
  "admin_id": "db_platform_credential_1",
  "base_url": "https://apaas.example.com/backend",
  "platform_tenant_id": "tenant-id"
}
```

接口行为：

1. 校验调用者是平台管理员。
2. 校验本地租户和平台管理员账号存在。
3. 创建或更新该本地租户的默认 `PlatformEnv`。
4. 设置 `Tenant.apaas_env_id` 和 `Tenant.apaas_tenant_id_str`。
5. 将选中平台管理员账号的账号和加密密码复制到环境记录。
6. 地址或租户发生变化时清除旧 Token，并将状态设为 `disconnected`。
7. 返回公开绑定信息，不返回任何敏感字段。

## 列表数据

现有本地租户列表响应补充：

- `baseUrl`
- `platformTenantId`
- `platformEnvId`
- `environmentBound`
- `adminAccount`

租户刷新自动创建的环境和人工绑定的环境使用同一套展示数据。

## 错误处理

- 未配置平台管理员账号：禁止保存并提示先新增账号。
- 本地租户不存在：返回 404。
- 管理员账号不存在：返回 400。
- 地址或 aPaaS 租户 ID 为空：返回 400。
- 保存失败时弹窗保持打开，前端显示后端错误信息。

## 验证

- 后端测试覆盖创建绑定、更新绑定、凭据关联、Token 清理和敏感字段不返回。
- 前端回归测试覆盖状态列、绑定按钮、弹窗字段和绑定接口调用。
- 管理端生产构建通过。
- Playwright 验证弹窗可打开、已有数据可回填、保存后状态更新且控制台无错误。
