# Builder 双认证源与 aPaaS 账号联邦绑定设计

**Spec ID**: 2026-07-11-builder-control-plane-apaas-federated-auth

状态：设计已确认，模块 Phase / Plan 已下发，待实现

上游设计：

- `2026-07-09-orcamatrix-full-workspace-platform-integration-design.md`
- `2026-07-09-p0-a-control-plane-full-workspace-auth-integration-design.md`
- `2026-07-09-p0-b-web-console-full-workspace-auth-entry-design.md`

目标实现边界：

- `../apaas-builder-ai`
- `../control-plane`
- Maven 坐标 `com.orcamatrix.sdk:admin-sdk-spring-boot-starter` 与 `com.orcamatrix.sdk:sdk-provider-auth` 对应的认证 SDK / Provider 源仓库

## 1. 设计目标

Builder 是面向用户的统一前端工作平台，登录入口需要同时支持：

- Control Plane 平台账号。
- aPaaS 账号。

无论用户从哪个入口登录，最终都必须获得 Control Plane 当前认可的用户级 access token，并以：

```http
Authorization: Bearer <control-plane-compatible-access-token>
X-Tenant-Id: <validated-tenant-id>
X-Auth-Provider: builder-control-plane
```

访问 Control Plane 租户内业务 API。

aPaaS 原始 token 不直接作为 Control Plane 业务 API 凭据。aPaaS 登录成功后，必须通过外部身份绑定和 token exchange，把 aPaaS 身份关联到一个真实 Control Plane 账号，再签发或刷新 Control Plane 可验证的 token。

本设计支持两种可配置绑定方式：

- `verify_control_plane`：首次绑定时要求用户再次完成 Control Plane 账号认证。
- `username_auto`：首次 aPaaS 登录时，由认证权威侧按规范化后的唯一同名 Control Plane 账号自动绑定。

本文所称“Control Plane 账号”，是指认证 SDK / Provider 管理、可通过 Control Plane Builder auth 门面认证并投影为 Control Plane 用户上下文的平台账号，不是 `control-plane` 本地 `om_auth_user` 或其他自建 IAM 账号。后续 implementation plan 必须以认证 Provider 的真实账号模型、稳定 user ID 和 token issuer 为准。

## 2. 与现有 P0-A / P0-B 的关系

现有 P0-A / P0-B 保持有效：

- Web Console 继续作为 Full Workspace 内嵌产品模块，复用 Full Workspace 登录态。
- Web Console 继续使用 `Authorization + X-Tenant-Id` 调用 Control Plane。
- 旧 `/api/auth/login-key`、`/api/auth/authorize`、`/api/auth/login`、`/api/auth/token`、`/api/auth/refresh` 继续对 Web Console 主线返回 deprecated 语义。
- Control Plane 不恢复本地用户、角色、租户主数据，不成为新的自管 IAM。

本设计新增的是 Builder 专用认证通道：

- 使用独立 `/api/builder-auth/**` 命名空间。
- 认证、绑定和 token 签发事实由认证 SDK / Provider 承接。
- Control Plane 只提供 Builder 专用门面、token provider 路由、请求级 tenant 校验和审计。
- Builder 通过用户 token 调用 Control Plane，不再依赖固定账号或全局 service token 代替最终用户。

因此，“废弃 Control Plane 独立登录主线”只约束 Web Console 和旧 `/api/auth/**` 本地登录入口，不禁止 Control Plane 作为认证 Provider 的受控 Builder 集成门面。

## 3. 核心原则

### 3.1 身份事实归认证权威侧

外部身份绑定必须由认证 SDK / Provider 保存和校验。Builder 不得仅凭用户名在本地合并账号，也不得自行签发 Control Plane token。

### 3.2 稳定 ID 优先

首次自动绑定可以使用规范化用户名定位候选账号；绑定成功后必须只使用稳定 ID：

- `provider`
- `issuer`
- `externalUserId`
- `controlPlaneUserId`

后续登录不得因用户名变化重新匹配或迁移绑定。

### 3.3 用户 token 直达业务鉴权

Builder 调用 Control Plane 业务 API 时使用当前用户交换得到的 token。可以由 Builder Backend 作为 BFF 转发，但鉴权主体必须是用户 token，而不是 Builder 全局 service token。

### 3.4 请求级 tenant 校验

Control Plane 不保存当前活跃 tenant session。每个租户内请求都必须基于用户 token 和 `X-Tenant-Id` 独立校验 tenant 成员关系。

### 3.5 失败关闭

用户名无匹配、多匹配、目标账号禁用、目标账号已被冲突身份绑定或上游认证不可达时，不得自动创建账号、选择任意账号或回退到全局管理员身份。

## 4. 总体架构

```text
Builder Login UI
  ├─ Control Plane 账号
  │    -> Control Plane /api/builder-auth/oauth/**
  │    -> Auth SDK / Provider
  │    -> Control Plane access + refresh token
  │
  └─ aPaaS 账号
       -> aPaaS 登录并取得已验证身份/token
       -> Control Plane /api/builder-auth/federation/apaas/exchange
       -> Auth SDK / Provider 校验 aPaaS token
       -> 查找既有 external identity binding
          ├─ 已绑定：签发最新 Control Plane token
          ├─ username_auto：唯一同名匹配、创建绑定、签发 token
          └─ verify_control_plane：返回 binding challenge
                -> 用户完成 Control Plane OAuth 认证
                -> /api/builder-auth/federation/apaas/bind
                -> 创建绑定并签发 token

Builder Backend
  -> 保存 Builder 自身 session
  -> 加密保存或安全引用 Control Plane refresh token
  -> 使用用户 access token + X-Tenant-Id 调 Control Plane

Control Plane business API
  -> 根据 X-Auth-Provider 路由认证 Provider
  -> 校验 token
  -> 校验 X-Tenant-Id 成员关系
  -> 建立 CurrentUserContext / TenantContext
```

## 5. Builder 登录配置

配置模型固定为：

```yaml
builder_auth:
  # 可选值：control_plane、apaas
  # 默认值：control_plane；必须同时存在于 enabled_login_providers。
  default_login_provider: control_plane

  # 可选项：control_plane、apaas；至少启用一个。
  enabled_login_providers:
    - control_plane
    - apaas

  providers:
    control_plane:
      # 可选值：true、false
      enabled: true
      label: "平台账号"

    apaas:
      # 可选值：true、false
      enabled: true
      label: "aPaaS 账号"
      binding:
        # 可选值：
        # - verify_control_plane：首次绑定时再次验证平台账号。
        # - username_auto：首次登录按规范化用户名唯一匹配并自动绑定。
        # 生产默认值：verify_control_plane
        mode: verify_control_plane

        # 可选值：verify_control_plane、disabled
        # 仅在 mode=username_auto 且自动绑定失败时生效。
        # verify_control_plane：转入二次验证绑定。
        # disabled：直接返回绑定失败，不执行兜底绑定。
        fallback: verify_control_plane
```

约束：

- `default_login_provider` 必须存在于 `enabled_login_providers`。
- `binding.mode` 只允许 `verify_control_plane` 或 `username_auto`。
- `binding.fallback` 只允许 `verify_control_plane` 或 `disabled`，且只在 `binding.mode=username_auto` 时生效。
- `username_auto` 默认 `fallback=verify_control_plane`。
- 不提供模糊匹配字段、邮箱前缀匹配或管理员自动兜底配置。
- 生产默认值为 `verify_control_plane`。
- 环境变量可以作为部署级覆盖，但数据库后台配置与环境变量的优先级必须固定且可观测。
- Builder 和部署仓库中的默认配置模板必须保留字段用途、可选值、默认值及生效条件注释，不能只在本文档中说明。

## 6. 外部身份绑定模型

认证权威侧新增逻辑模型 `ExternalIdentityBinding`：

| 字段 | 语义 |
| --- | --- |
| `bindingId` | 稳定绑定 ID |
| `provider` | 固定为 `apaas` |
| `issuer` | 规范化后的 aPaaS base URL / issuer |
| `externalUserId` | aPaaS 稳定用户 ID |
| `externalUsername` | 绑定时用户名快照，仅用于审计 |
| `controlPlaneUserId` | Control Plane 稳定用户 ID |
| `bindingMethod` | `verified` 或 `username_auto` |
| `status` | `active`、`revoked` |
| `createdAt` / `updatedAt` | 生命周期时间 |
| `createdBy` | 用户本人或受控系统动作 |
| `lastExchangeAt` | 最近一次成功 token exchange |

唯一性：

- active `(provider, issuer, externalUserId)` 只能绑定一个 `controlPlaneUserId`。
- 同一外部身份不得同时绑定多个 Control Plane 账号。
- 一个 Control Plane 账号可以绑定多个 aPaaS tenant membership，但是否允许绑定多个不同 aPaaS 用户必须由认证 Provider 的账号策略显式决定，默认禁止同 issuer 下多用户绑定。
- tenant membership 不等于账号绑定；membership 必须在每次请求或受控短 TTL 内重新校验。

Builder 可以保存 `bindingId`、外部身份引用和展示快照，但不得成为绑定事实源。

## 7. 登录与绑定流程

### 7.1 Control Plane 账号登录

1. 用户在 Builder 选择“平台账号”。
2. Builder 调用 `/api/builder-auth/oauth/**` 完成 RSA、OAuth 2.0 Authorization Code 和 PKCE 流程。
3. Control Plane 门面调用认证 Provider；Provider 返回 Control Plane 可验证的 access token、refresh token、稳定用户 ID 和可访问 tenant 信息。
4. Builder 创建自己的本地 session，并把 Control Plane token 标记为 `authSource=control_plane`。
5. Builder 调用 Control Plane 业务 API 时发送用户 token、`X-Tenant-Id` 和 `X-Auth-Provider: builder-control-plane`。

### 7.2 aPaaS 已绑定登录

1. Builder 验证 aPaaS 账号并取得 aPaaS access token、稳定 user ID 和 tenant 信息。
2. Builder 把原始 aPaaS token发送给 `/api/builder-auth/federation/apaas/exchange`。
3. Control Plane 门面把 token 交给认证 Provider 校验。
4. Provider 使用 `(issuer, externalUserId)` 命中 active binding。
5. Provider 签发最新 Control Plane access token 和 refresh token。
6. Builder 创建本地 session，并使用 Control Plane token 访问后续业务 API。

### 7.3 `username_auto` 首次自动绑定

1. aPaaS token 校验成功，且不存在 active binding。
2. 认证 Provider 使用自己的账号规范化规则生成 canonical username。
3. 只查询 active Control Plane 账号。
4. 恰好命中一个账号，且该账号没有冲突绑定时，原子创建 binding。
5. 创建成功后签发 Control Plane token。
6. 零匹配、多匹配、账号禁用或绑定冲突时返回明确错误；如配置允许，Builder 转入 `verify_control_plane` 流程。

禁止行为：

- Builder 在本地按用户名直接合并 `users` 行。
- 根据 display name、邮箱前缀或大小写不确定规则猜测账号。
- 自动创建新的 Control Plane 账号。
- 多匹配时选择第一条。
- aPaaS token 未经权威侧验证就执行绑定。

### 7.4 `verify_control_plane` 首次绑定

1. exchange 返回 `ACCOUNT_BINDING_REQUIRED` 和短期 `bindingChallenge`。
2. 用户在 Builder 完成一次 Control Plane OAuth/PKCE 登录。
3. Builder 把 `bindingChallenge` 和 Control Plane 登录证明提交到 `/api/builder-auth/federation/apaas/bind`。
4. Provider 校验 challenge 未过期、未使用，且 aPaaS 身份与 Control Plane 身份均已验证。
5. Provider 原子创建 binding，并签发或返回当前 Control Plane token。
6. challenge 使用后立即失效。

Builder 和 Control Plane 不保存用户 Control Plane 明文密码。

### 7.5 token 刷新

- Builder 使用 `/api/builder-auth/oauth/refresh` 刷新 Control Plane token。
- refresh token 必须轮换；新 refresh token 持久化成功后才能废弃旧值。
- refresh 失败不得回退到全局 service token。
- binding 已撤销、账号禁用或 tenant membership 失效时，刷新或后续请求必须失败关闭。
- tenant 切换只改变 `X-Tenant-Id`；除非认证 Provider 明确签发 tenant-bound token，否则不为普通 tenant 切换调用 `switch-tenant` 或重新签发 token。

## 8. Control Plane Builder Auth API

Builder 专用 API 固定放在 `/api/builder-auth`：

| operation | 用途 |
| --- | --- |
| `GET /api/builder-auth/oauth/login-key` | 获取登录 RSA key |
| `POST /api/builder-auth/oauth/authorize` | 创建 OAuth authorization request |
| `POST /api/builder-auth/oauth/login` | 验证 Control Plane 账号 |
| `POST /api/builder-auth/oauth/token` | authorization code 换 token |
| `POST /api/builder-auth/oauth/refresh` | refresh token 轮换 |
| `GET /api/builder-auth/me` | 查询 Builder 认证通道当前用户 |
| `POST /api/builder-auth/federation/apaas/exchange` | aPaaS 身份绑定查询、自动绑定与 token exchange |
| `POST /api/builder-auth/federation/apaas/bind` | 二次验证后创建绑定 |
| `POST /api/builder-auth/federation/apaas/revoke` | 当前用户撤销自己的绑定 |

约束：

- `/api/auth/**` 的 P0-A deprecated 行为不改变。
- Builder auth API 只能调用认证 SDK / Provider，不得读写 `om_auth_user` 作为身份事实源。
- exchange / bind / revoke 必须写审计事件。
- API 不返回明文密码、aPaaS 原始 token、token hash 或内部 Provider 异常。
- 对外响应包含 `traceId`。

## 9. Control Plane 多身份源校验

Control Plane 管理端业务 API 继续统一经过 `TokenAuthenticationFilter`，但增加认证 Provider 路由：

| `X-Auth-Provider` | token 来源 | 校验方 |
| --- | --- | --- |
| 缺省或 `full-workspace` | Full Workspace Shell | 现有 Full Workspace auth adapter |
| `builder-control-plane` | Builder Control Plane 登录或 aPaaS exchange | Admin SDK / Auth Provider adapter |

规则：

- `X-Auth-Provider` 只是路由提示，不是身份事实；选中的 Provider 仍必须完整校验 token。
- 不允许因某个 Provider 返回无效 token 而静默尝试另一个 Provider。
- Provider 不可达返回对应 `503`，不得被映射为另一个 Provider 的无效 token。
- 不在 Control Plane 本地解析 JWT 以复制用户、角色、tenant 或 membership 事实。
- 两种 Provider 最终都投影为同一个 `CurrentUserContext`、`TenantContext` 和 permission context。
- `X-Tenant-Id` 必须由选中的 Provider 校验，不能只与 token claim 做字符串比较。

Builder token 成功校验后可以直接访问 Control Plane 租户内业务 API，不需要再次替换为 service token。

## 10. Builder 本地状态与凭据

Builder 保留本地用户投影，用于：

- Builder 自有资源归属。
- Builder session。
- UI 展示和历史数据关联。
- aPaaS / Control Plane 外部身份引用。

Builder 不得把本地投影视为 Control Plane 身份事实源。

现有 `users.coding_access_token`、`users.coding_refresh_token` 不应继续保存明文 token。实施时迁移为独立加密凭据模型，至少包含：

- `userId`
- `provider`
- `credentialType`
- `valueEncrypted`
- `expiresAt`
- `rotationVersion`
- `updatedAt`

access token 优先只保存在短期 session/cache；必须持久化时也要加密。refresh token 必须加密并限制读取边界。

Builder 调用 Control Plane 时的优先级固定为：

1. 当前用户 Control Plane token。
2. runtime/self-validated 专用 token，仅用于其原有专用接口。
3. 全局 service token 只能用于明确的系统任务，不得作为用户业务请求兜底。

固定用户名密码登录和全局 service token 代替用户身份的兼容逻辑在完成迁移后删除。

## 11. 错误契约

| HTTP | code | 语义 |
| --- | --- | --- |
| `401` | `APAAS_TOKEN_INVALID` | aPaaS token 无效或过期 |
| `401` | `CONTROL_PLANE_LOGIN_INVALID` | Control Plane 登录证明无效 |
| `401` | `CONTROL_PLANE_TOKEN_INVALID` | exchange/refresh 后 token 无效 |
| `403` | `ACCOUNT_BINDING_REQUIRED` | 当前策略要求二次验证或自动绑定无法完成 |
| `403` | `ACCOUNT_BINDING_CONFLICT` | 外部身份或目标账号已有冲突绑定 |
| `403` | `CONTROL_PLANE_ACCOUNT_DISABLED` | 目标 Control Plane 账号禁用 |
| `403` | `TENANT_FORBIDDEN` | 当前用户不可访问目标 tenant |
| `409` | `ACCOUNT_BINDING_AMBIGUOUS` | 同名匹配超过一个候选账号 |
| `409` | `ACCOUNT_BINDING_ALREADY_EXISTS` | 并发请求已创建等价绑定 |
| `410` | `BINDING_CHALLENGE_EXPIRED` | challenge 过期或已使用 |
| `503` | `APAAS_AUTH_UNAVAILABLE` | aPaaS 认证服务不可达 |
| `503` | `CONTROL_PLANE_AUTH_UNAVAILABLE` | Admin SDK / Auth Provider 不可达 |

Builder 必须按 error code 分流，不能只按 HTTP status 判断。

## 12. 安全与审计

- 自动绑定只允许在认证 Provider 内执行。
- aPaaS token 必须由 Provider 直接验证，Builder 传入的用户名只可作为诊断 hint。
- binding challenge 必须短期、一次性、绑定 issuer、external user、目标 client 和 trace。
- bind / exchange / revoke 需要审计 `actorUserRef`、`externalUserRef`、`bindingMethod`、`tenantRef`、`clientId`、`traceId` 和结果。
- 日志、指标、审计和错误响应不得记录原始 access token、refresh token、密码或 token hash。
- 自动绑定发生时应向用户展示或发送可追溯通知。
- 撤销绑定不会删除任一侧账号，但立即禁止后续 exchange。
- 账号禁用、密码重置、binding revoke 和 refresh token rotation 必须有明确失效语义。

## 13. 迁移与发布顺序

### 阶段 0：认证 SDK 源仓库 Gate

- 通过 Maven 坐标定位 `admin-sdk-spring-boot-starter` 和 `sdk-provider-auth` 的源仓库、维护分支和部署 Provider。
- 确认现有 SDK 只有 authorization code exchange / refresh，不具备外部身份 federation 时，先扩展 SDK / Provider。
- 源仓库、部署目标或 token issuer 无法确认时，后续 implementation plan 必须阻塞，不得在 Builder 模拟签发。

### 阶段 1：认证 SDK / Provider

- 实现 binding persistence、aPaaS token validation、username auto bind、manual bind challenge 和 token exchange。
- 发布新 SDK 版本及 Provider deployment。

### 阶段 2：Control Plane

- 新增 `/api/builder-auth/**`。
- 增加认证 Provider 路由和 Builder token tenant validation。
- 保持 `/api/auth/**` P0-A 行为不变。
- 提供 contract test 和 live smoke。

### 阶段 3：Builder

- 将 Provider 名称收敛为 `control_plane` / `apaas`。
- 接入两种 binding mode。
- 替换旧 `login_to_coding_control_plane` 路径。
- 用户业务请求改用用户 Control Plane token。
- 迁移明文 token 字段。

### 阶段 4：联调与兼容清理

- 完成 Control Plane 登录、aPaaS 自动绑定、aPaaS 二次验证绑定、refresh、tenant switch 和 revoke E2E。
- 观察期结束后删除固定账号登录和用户请求 service-token fallback。

## 14. 测试与验收

认证 SDK / Provider：

- 有效 aPaaS token + 已绑定身份可以 exchange。
- 首次 `username_auto` 恰好一个 active 同名账号时原子绑定并签发 token。
- 零匹配、多匹配、账号禁用和绑定冲突失败关闭。
- 并发自动绑定只有一个 binding 成功。
- manual challenge 过期、重放和跨用户使用被拒绝。
- revoke 后 exchange 和 refresh 失效。

Control Plane：

- `/api/auth/**` 仍保持 P0-A deprecated/current-user contract。
- `/api/builder-auth/**` 使用认证 SDK，不写本地 auth 主数据。
- Builder token + 合法 tenant 可以访问至少一个真实业务 API。
- Builder token + 非法 tenant 返回 `TENANT_FORBIDDEN`。
- `X-Auth-Provider` 缺失、错误或 Provider 不可达均有稳定结果。
- Full Workspace Web Console token 主线不回归。

Builder：

- 登录页可按配置显示 Control Plane 和 aPaaS 两个入口。
- 两种默认 Provider 均可配置。
- `verify_control_plane` 首次绑定完整通过。
- `username_auto` 首次登录无需 Control Plane 密码即可绑定并取得 token。
- 自动绑定失败按配置进入二次验证。
- 已绑定用户后续登录不再按用户名匹配。
- refresh token 轮换、tenant 切换、binding revoke 和登录失效处理正确。
- 用户业务请求不再使用固定账号或全局 service token。

Live E2E：

- 使用真实 Control Plane 账号与真实 aPaaS 测试账号完成两种绑定方式。
- 交换得到的 token 能携带 `X-Tenant-Id` 调用 Control Plane application/workspace 真实 API。
- 跨 tenant 请求被拒绝。
- token、密码和敏感凭据不出现在日志、trace、截图或测试产物。

## 15. 仓库承接关系

| 角色 | 目标仓库 | 责任 |
| --- | --- | --- |
| 正式设计源 | `product-design` | 本设计、跨仓库契约、状态总账和偏差回写 |
| 认证权威 | 认证 SDK / Provider 源仓库 | binding、aPaaS token validation、token exchange、refresh、revoke |
| 认证门面与资源服务 | `control-plane` | `/api/builder-auth/**`、Provider 路由、tenant 校验、业务 API 鉴权 |
| 用户平台 | `apaas-builder-ai` | 双登录入口、配置、绑定交互、Builder session、用户 token 转发和凭据加密 |

本设计已通过用户审阅并完成 Spec 快照、module phase 和 implementation plan 下发；代码实现仍需按各模块 plan 顺序执行。

## 16. 下发 Phase / Plan 与执行状态记录

### 16.1 OrcaMatrix SDK / Auth Provider

| 项目 | 路径 / 状态 |
| --- | --- |
| spec 快照 | `../orcamatrix-sdk/docs/superpowers/specs/2026-07-11-builder-control-plane-apaas-federated-auth-design.md` |
| chain analysis | `../orcamatrix-sdk/docs/solutions/l3/auth/builder-apaas-federated-auth-chain-analysis.md` |
| module phase | `../orcamatrix-sdk/docs/phases/2026-07-11-builder-apaas-federated-auth-sdk.md` |
| implementation plan | `../orcamatrix-sdk/docs/superpowers/plans/2026-07-11-builder-apaas-federated-auth-sdk.md` |
| 当前状态 | Plan Ready，未开始实现 |
| 验收结果 | 待执行 |
| 偏差 / Gate | SDK 当前 Admin Auth 不含 tenant membership。实施必须先锁定真实 tenant authority；未达到 `Tenant Access Ready` 时只能汇报 `Auth Federation Ready`，不得宣称 Builder token 已可访问 Control Plane 租户业务 API。 |

### 16.2 Control Plane

| 项目 | 路径 / 状态 |
| --- | --- |
| spec 快照 | `../control-plane/docs/superpowers/specs/2026-07-11-builder-control-plane-apaas-federated-auth-design.md` |
| chain analysis | `../control-plane/docs/solutions/l3/auth/builder-federated-auth-chain-analysis.md` |
| module phase | `../control-plane/docs/phases/2026-07-11-builder-federated-auth-control-plane.md` |
| implementation plan | `../control-plane/docs/superpowers/plans/2026-07-11-builder-federated-auth-control-plane.md` |
| 当前状态 | Plan Ready，等待 SDK 前置能力 |
| 验收结果 | 待执行 |
| 偏差 / Gate | 保持 `/api/auth/**` P0-A 行为不变；新增能力仅在 `/api/builder-auth/**`。Control Plane 只依赖 `admin-sdk-spring-boot-starter`。 |

### 16.3 aPaaS Builder AI

| 项目 | 路径 / 状态 |
| --- | --- |
| spec 快照 | `../apaas-builder-ai/docs/superpowers/specs/2026-07-11-builder-control-plane-apaas-federated-auth-design.md` |
| module phase | `../apaas-builder-ai/docs/phases/2026-07-11-builder-control-plane-apaas-federated-auth.md` |
| implementation plan | `../apaas-builder-ai/docs/superpowers/plans/2026-07-11-builder-control-plane-apaas-federated-auth.md` |
| 当前状态 | Plan Ready，当前仓库存在用户未提交认证改动，执行时必须原地兼容 |
| 验收结果 | 待执行 |
| 偏差 / Gate | Provider 名称收敛为 `control_plane` / `apaas`；`platform` / `coding` 只做迁移兼容。Control Plane token 改为独立加密 credential store，用户请求不再用全局 service token 兜底。 |

### 16.4 推荐执行顺序

1. `orcamatrix-sdk`：先完成 federation contract、binding persistence、challenge、exchange、revoke 和 tenant authority Gate。
2. `control-plane`：升级 Admin SDK，新增 `/api/builder-auth/**` 和请求级 Provider router。
3. `apaas-builder-ai`：迁移配置、登录编排、绑定 UI、加密 token store 和用户 token 转发。
4. 三仓联调：完成登录、自动绑定、二次验证绑定、refresh、tenant、revoke E2E 后，再清理旧兼容路径。
