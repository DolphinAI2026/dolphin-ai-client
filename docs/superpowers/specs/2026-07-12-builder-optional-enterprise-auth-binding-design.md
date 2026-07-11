# Builder 可选企业认证账号绑定设计

**Spec ID**: `2026-07-12-builder-optional-enterprise-auth-binding`

状态：设计已确认，待实施计划

## 1. 目标

Builder 保持单一默认登录入口，并可由平台管理员选择是否启用企业级认证账号绑定。

默认登录入口支持：

- `control_plane`：使用现有 Control Plane 登录适配器。
- `apaas`：使用现有 aPaaS 登录适配器。

企业绑定启用后，Builder 在默认认证源登录成功后，根据平台管理中预先配置的租户和管理员账号绑定，尝试取得另一认证源的凭据。Control Plane Token 只用于 Control Plane，aPaaS Token 只用于 aPaaS。

本设计不修改 Control Plane 或 OrcaMatrix SDK 的认证协议、Token 签发、Token 校验和租户鉴权。

## 2. 范围

### 2.1 本次修改

- `apaas-builder-ai` 配置、数据模型、登录编排、平台管理 API 和管理界面。
- 企业认证账号的加密凭据存储。
- Control Plane 与 aPaaS 账号的多对多绑定。
- 登录后绑定解析、另一侧凭据获取和未绑定降级。
- Control Plane/aPaaS 请求按目标系统使用对应 Token。

### 2.2 明确不修改

- 不修改 `control-plane` 代码。
- 不修改 `orcamatrix-sdk` 代码。
- 不恢复 Control Plane 已废弃的旧认证入口。
- 不新增 SDK federation、external identity、binding challenge 或 tenant authority。
- 不允许 aPaaS Token 访问 Control Plane。
- 不允许 Control Plane Token 访问 aPaaS。
- 不把 Builder 本地 JWT 当作 Control Plane 或 aPaaS 的上游 Token。

## 3. 配置

配置项均为可选项：

```env
# 可选项。Builder 默认登录方式。
# 可选值：control_plane、apaas。
# 示例值：control_plane。未配置时保留现有兼容登录行为。
AUTH_PROVIDER=control_plane

# 可选项。是否启用 Control Plane 与 aPaaS 企业认证账号绑定。
# 默认值：false。
# false 时只执行 AUTH_PROVIDER 指定的登录，不查询绑定、不登录另一侧。
# true 时登录成功后尝试解析企业绑定；无绑定不阻止登录。
AUTH_ACCOUNT_BINDING_ENABLED=false
```

兼容期内，现有 `coding` 配置值可作为 `control_plane` 的别名，配置模板和新代码统一使用 `control_plane`。

## 4. 核心模型

### 4.1 企业认证账号

新增 `enterprise_auth_accounts`：

| 字段 | 说明 |
| --- | --- |
| `id` | Builder 内部主键 |
| `provider` | `control_plane` 或 `apaas` |
| `base_url` | 认证系统地址，保存规范化结果 |
| `tenant_ref` | 对应系统的稳定租户标识 |
| `tenant_name` | 管理界面展示名称，不作为匹配事实 |
| `account` | 管理员账号 |
| `password_enc` | 加密密码，仅在后端认证边界内解密，不返回前端 |
| `access_token_enc` | 可选的加密短期 Token |
| `refresh_token_enc` | 可选的加密刷新 Token |
| `token_expires_at` | Token 过期时间 |
| `status` | `unverified`、`connected`、`error`、`disabled` |
| `last_verified_at` | 最近成功验证时间 |
| `last_error` | 脱敏并截断后的最近错误 |
| `created_by` | Builder 平台管理员 ID |
| `created_at` / `updated_at` | 审计时间 |

唯一性按 `provider + normalized_base_url + tenant_ref + account` 约束。

密码和 Token 不返回给前端，不写入普通日志、错误响应和审计详情。更新账号时，空密码表示保留原密码，显式新密码才覆盖密文。

### 4.2 企业认证绑定

新增 `enterprise_auth_bindings`：

| 字段 | 说明 |
| --- | --- |
| `id` | Builder 内部主键 |
| `left_account_id` | 一侧企业认证账号 |
| `right_account_id` | 另一侧企业认证账号 |
| `priority` | 绑定选择优先级，数值越小优先级越高 |
| `enabled` | 是否启用 |
| `created_by` | Builder 平台管理员 ID |
| `created_at` / `updated_at` | 审计时间 |

约束：

- 一条绑定的两侧 Provider 必须不同。
- 相同账号对只能存在一条有效关系。
- 关系可双向解析，不分别保存 `control_plane -> apaas` 和 `apaas -> control_plane`。
- 一个账号可以关联多个另一侧账号，允许多对多。

## 5. 登录编排

### 5.1 绑定关闭

当 `AUTH_ACCOUNT_BINDING_ENABLED=false`：

1. 只调用 `AUTH_PROVIDER` 指定的现有登录适配器。
2. 登录成功后创建 Builder 本地会话。
3. 不查询企业认证账号和绑定表。
4. 不尝试登录另一认证源。
5. 保持当前单认证源行为。

### 5.2 Control Plane 为默认登录源

当 `AUTH_PROVIDER=control_plane` 且绑定开启：

1. 使用现有 Control Plane 登录适配器验证用户。
2. 创建或恢复 Builder 本地用户和会话。
3. 根据已验证的 Control Plane `base_url + tenant_ref + account` 查找启用的企业账号。
4. 查找该账号关联的启用 aPaaS 账号。
5. 唯一选择成功时，使用后台保存的 aPaaS 管理员凭据取得或刷新 aPaaS Token。
6. 把两侧凭据状态关联到当前 Builder 会话。
7. 找不到绑定或另一侧登录失败时，Builder 登录仍然成功，并标记 aPaaS 能力不可用。

### 5.3 aPaaS 为默认登录源

当 `AUTH_PROVIDER=apaas` 且绑定开启：

1. 使用现有 aPaaS 登录适配器验证用户。
2. 创建或恢复 Builder 本地用户和会话。
3. 根据已验证的 aPaaS `base_url + tenant_ref + account` 查找启用的企业账号。
4. 查找该账号关联的启用 Control Plane 账号。
5. 唯一选择成功时，使用后台保存的 Control Plane 管理员凭据取得或刷新 Control Plane Token。
6. 把两侧凭据状态关联到当前 Builder 会话。
7. 找不到绑定或另一侧登录失败时，Builder 登录仍然成功，并标记 Control Plane 能力不可用。

### 5.4 多绑定选择

同一登录账号命中多个绑定时：

1. 过滤禁用账号和禁用绑定。
2. 按 `priority` 升序选择。
3. 只有一个最高优先级候选时使用该候选。
4. 多个候选具有相同最高优先级时视为配置歧义，不随机选择。
5. 配置歧义不阻止 Builder 登录，只禁用另一侧能力并记录脱敏诊断。

## 6. 会话与 Token 使用

Builder 本地 JWT 只代表 Builder 会话，不替代上游系统 Token。

请求路由规则：

| 目标系统 | 使用凭据 |
| --- | --- |
| Builder API | Builder 本地 JWT |
| Control Plane API | 当前绑定解析出的 Control Plane Token |
| aPaaS API | 当前绑定解析出的 aPaaS Token |

用户业务请求不得被全局 `DOLPHIN_CODE_CONTROL_PLANE_TOKEN` 静默覆盖。全局 service token 只能保留给明确标记的系统任务。

短期 access token 优先放入会话缓存；确需数据库持久化时必须加密。refresh token 和密码必须加密持久化，并限制解密边界。

## 7. 未绑定与降级

绑定开启但当前账号没有有效绑定时：

- Builder 登录成功。
- 当前登录源相关功能正常可用。
- 依赖另一认证源的功能禁用。
- 后端返回稳定错误码 `ENTERPRISE_AUTH_BINDING_UNAVAILABLE`。
- 前端提示“当前租户尚未配置对应平台账号绑定，请联系平台管理员”。
- 不要求普通用户输入另一侧账号密码。
- 不回退到随机账号、全局管理员或全局 service token。

绑定存在但另一侧认证失败时，返回 `ENTERPRISE_AUTH_BINDING_UNAVAILABLE`，并在平台管理中展示脱敏后的最近验证错误。

## 8. 平台管理

在 Builder 平台管理增加“认证绑定”功能：

### 8.1 认证账号

- 查看 Control Plane 和 aPaaS 企业账号。
- 新增、编辑、启用、禁用和删除账号。
- 配置地址、租户、管理员账号和密码。
- 执行“测试连接”。
- 展示状态、最近验证时间和脱敏错误。

### 8.2 绑定关系

- 从两个不同 Provider 的企业账号中创建绑定。
- 允许多对多。
- 设置优先级。
- 启用、禁用和删除绑定。
- 在删除账号前检查现存绑定，禁止产生悬空关系。

管理 API 必须复用现有平台管理员权限边界，普通租户用户不可查看或修改企业凭据。

## 9. Builder 代码边界

建议改动集中在：

- `backend/app/config.py`：新增可选绑定开关，规范化 `control_plane` Provider 名称。
- `backend/app/models/`：新增企业认证账号和绑定模型。
- `backend/app/services/enterprise_auth_binding.py`：绑定解析、另一侧登录、Token 刷新和降级决策。
- `backend/app/routes/auth/login.py`：现有登录成功后调用绑定服务，不重写两侧登录实现。
- `backend/app/code_runtime/service.py`：用户请求使用绑定解析出的 Control Plane Token。
- aPaaS client 统一入口：使用绑定解析出的 aPaaS Token。
- `backend/app/routes/`：新增平台管理 CRUD、测试连接和绑定管理 API。
- `frontend/src/views/PlatformTenants.vue` 或平台管理对应模块：新增认证账号与绑定管理视图。

现有 `User.apaas_token`、`User.coding_access_token` 和 `User.coding_refresh_token` 不再作为企业绑定事实源。实施阶段先保持兼容读取，新增流程只写入新的加密凭据边界，后续再独立迁移旧字段。

## 10. 错误契约

| HTTP | code | 说明 |
| --- | --- | --- |
| `400` | `ENTERPRISE_AUTH_ACCOUNT_INVALID` | 企业账号配置缺失或字段非法 |
| `403` | `ENTERPRISE_AUTH_ADMIN_REQUIRED` | 非平台管理员访问管理接口 |
| `404` | `ENTERPRISE_AUTH_ACCOUNT_NOT_FOUND` | 企业账号不存在 |
| `404` | `ENTERPRISE_AUTH_BINDING_NOT_FOUND` | 绑定不存在 |
| `409` | `ENTERPRISE_AUTH_ACCOUNT_DUPLICATE` | 企业账号唯一键冲突 |
| `409` | `ENTERPRISE_AUTH_BINDING_DUPLICATE` | 相同账号对重复绑定 |
| `409` | `ENTERPRISE_AUTH_BINDING_AMBIGUOUS` | 多条最高优先级绑定无法唯一选择 |
| `409` | `ENTERPRISE_AUTH_BINDING_REQUIRED` | 当前功能需要另一认证源，但没有有效绑定 |
| `503` | `ENTERPRISE_AUTH_BINDING_UNAVAILABLE` | 绑定存在，但另一认证源不可用或凭据失效 |

登录接口不会因 `BINDING_REQUIRED` 或 `BINDING_UNAVAILABLE` 失败；这些状态通过登录响应的能力状态和后续目标功能错误表达。

## 11. 测试与验收

必须覆盖：

- 绑定开关默认关闭，完全不查询绑定。
- `control_plane` 和 `apaas` 两种默认登录源。
- 开关开启且唯一绑定成功，取得另一侧凭据。
- 无绑定时登录成功，另一侧能力返回 `ENTERPRISE_AUTH_BINDING_REQUIRED`。
- 另一侧认证失败时登录成功，能力返回 `ENTERPRISE_AUTH_BINDING_UNAVAILABLE`。
- 多对多绑定按唯一最高优先级选择。
- 相同最高优先级候选返回歧义，不随机选择。
- 禁用账号和禁用绑定不参与解析。
- Control Plane 请求不使用 aPaaS Token。
- aPaaS 请求不使用 Control Plane Token。
- 用户请求不被全局 Control Plane service token 覆盖。
- 平台管理员可管理账号和绑定，普通用户被拒绝。
- API、日志和数据库明文查询结果不泄露密码或 Token。
- 关闭绑定后现有登录和单认证源功能无回归。

## 12. 发布顺序

1. 新增配置和数据表，保持开关默认关闭。
2. 上线平台管理账号与绑定配置。
3. 管理员配置并测试企业账号、租户和绑定。
4. 在测试环境开启绑定，验证两种默认登录源和未绑定降级。
5. 确认无回归后按环境逐步开启。
