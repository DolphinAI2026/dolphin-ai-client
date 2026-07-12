# aPaaS 平台管理员绑定与租户同步设计

**Spec ID**: `2026-07-12-apaas-platform-admin-binding`

状态：用户已确认设计，待实施

## 1. 目标

在 Builder 平台管理中提供可操作的 aPaaS 平台管理员绑定入口，使平台管理员能够：

- 配置一套或多套 aPaaS 平台管理员账号。
- 使用账号密码登录 aPaaS 并由后端换取、保存最新 Token。
- 选择默认管理员账号。
- 从 aPaaS 刷新租户，并同步为 Builder 的 `Tenant` 与 `PlatformEnv`。

本功能只处理 Builder 到 aPaaS 的平台凭据和租户同步，不修改 Control Plane 认证接口或认证模式。

## 2. 环境配置

本地开发环境使用：

```env
APAAS_BASE_URL=https://apaas-trial.definesys.cn/backend
```

约束：

- `APAAS_BASE_URL` 是可选部署项；未配置时，平台管理员绑定操作必须显示明确错误。
- 账号和密码不得写入仓库配置文件。
- 密码只通过管理页面提交，由后端使用现有加密逻辑存入数据库。
- aPaaS Token 不返回给管理页面，也不写入浏览器存储。

## 3. 管理端界面

修改 `admin-spa/src/views/PlatformTenants.vue`，在租户列表上方增加“平台管理员账号”区域。

账号列表展示：

- 名称。
- 登录账号。
- 默认账号标识。
- 连接状态。
- 最近登录时间。

支持操作：

- 新增账号。
- 编辑名称、账号和密码。
- 设为默认账号。
- 重新登录。
- 删除账号。

新增与编辑使用同一个对话框：

| 字段 | 规则 |
| --- | --- |
| 名称 | 必填，用于管理端展示 |
| 账号 | 必填，填写 aPaaS 平台管理员账号 |
| 密码 | 新增时必填；编辑时留空表示不修改 |
| 默认账号 | 可选；首个账号自动成为默认账号 |

页面不展示 Token、密码密文或 Token 指纹。

## 4. 数据流

### 4.1 新增账号

1. 页面调用 `POST /api/mcp-platform/apaas-admins`。
2. 后端使用 `APAAS_BASE_URL` 和现有加密组件保存账号密码。
3. 页面立即调用 `POST /api/mcp-platform/apaas-admins/{admin_id}/login`。
4. 登录成功后刷新管理员账号列表。
5. 登录失败时保留账号记录并显示后端错误，允许用户修改密码后重试。

### 4.2 刷新租户

1. 用户选择一个已配置的管理员账号。
2. 页面调用 `GET /api/mcp-platform/apaas-tenants?admin_id=...`。
3. 后端使用已有 Token；Token 不存在或失效时自动使用保存的账号密码重新登录。
4. 后端从 aPaaS 获取租户列表。
5. 后端现有同步逻辑创建或更新 Builder `Tenant`。
6. 每个 aPaaS 租户创建或更新对应的默认 `PlatformEnv`，继承平台地址和管理员凭据。
7. 页面展示同步结果和租户列表。

## 5. 后端边界

复用现有接口：

- `GET /api/mcp-platform/apaas-admins`
- `POST /api/mcp-platform/apaas-admins`
- `PUT /api/mcp-platform/apaas-admins/{admin_id}`
- `DELETE /api/mcp-platform/apaas-admins/{admin_id}`
- `POST /api/mcp-platform/apaas-admins/{admin_id}/login`
- `GET /api/mcp-platform/apaas-tenants`

本次不新增凭据模型，不修改 Token 签发逻辑，不修改 Control Plane。

仅在现有接口无法向页面返回必要的非敏感状态时，允许增加最小响应字段；不得返回密码、密文或完整 Token。

## 6. 错误处理

- 未配置 `APAAS_BASE_URL`：阻止新增或登录，提示配置平台地址。
- aPaaS 账号密码错误：展示后端返回的登录错误，不自动删除记录。
- aPaaS 不可达：展示网络错误，保留当前绑定。
- Token 过期：后端自动重新登录一次；仍失败则返回错误。
- 删除默认账号：后端沿用现有逻辑，把剩余首个账号设为默认。
- 无管理员账号：租户刷新按钮禁用，并提示先新增平台管理员账号。

## 7. 验证

必须完成：

- 管理端生产构建通过。
- 管理员账号新增、编辑、设默认、重新登录、删除操作可用。
- 密码不出现在列表、响应展示和浏览器存储中。
- 真实浏览器中可新增账号并触发登录。
- 登录成功后可刷新租户。
- 租户同步后 Builder 数据库存在对应 `Tenant` 和默认 `PlatformEnv`。
- 现有平台管理 iframe 不再出现永久加载遮罩。

## 8. 非目标

- 不在管理页面配置 Control Plane 账号。
- 不修改 Builder 登录模式。
- 不把 aPaaS Token 作为 Control Plane Token 使用。
- 不支持在前端直接粘贴或查看完整 aPaaS Token。
- 不把账号密码写入 Git、日志或前端本地存储。
