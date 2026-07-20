---
asset_id: spec.2026-07-20-builder-tenant-url-public-uuid
asset_kind: spec
knowledge_level: L1
phase_id: 2026-07-20-builder-tenant-url-public-uuid
revision: 1
status: draft
change_type: added
source_section_refs:
  - "Builder 租户 URL 公共 UUID 设计"
relations:
  - type: extends
    target: docs/solutions/l1/arch/builder-tenant-auth-panorama.md
  - type: contributes_to
    target: docs/solutions/l1/roadmap/builder-tenant-auth-optimization-roadmap.md
---

# Builder 租户 URL 公共 UUID 设计

**Spec ID**：`2026-07-20-builder-tenant-url-public-uuid`
**日期**：2026-07-20
**状态**：设计已对齐，待 Spec 审查
**主仓库**：`apaas-builder-ai`

## 1. 背景与问题

Builder 当前通过 Builder JWT 的数字型 `tid` 表达当前租户。浏览器地址只包含业务
资源标识，例如：

```text
/ai-builder/code/<session-public-id>?agent=<runtime-session-id>
```

这产生三个直接问题：

1. 分享、收藏或恢复深链接时，URL 没有说明页面属于哪个租户。
2. 同一账号切换租户后打开旧链接，前端会先按当前 token 的租户请求资源，容易出现
   误导性的 404、空页面或运行时鉴权失败。
3. 数字型数据库主键不适合作为跨环境、可分享的公开路由标识，也会暴露内部数据规模
   和创建顺序。

2026-07-20 的线上诊断还确认，已发布前端在 Code 深链接中先调用旧的
`/code-runtime/.../activate` Cookie 依赖路径，导致首次打开带 `agent` 的链接时返回
`401 Code runtime token required`。仓库 `main` 已包含
`49a4bef4 fix(code): use builder auth for outer runtime sessions`，但线上静态资源尚未包含
该修复。本 Spec 的发布必须携带该既有修复，并补齐显式租户 URL 契约。

## 2. 目标

1. 所有需要登录且存在租户上下文的前端页面都使用查询参数
   `tenantId=<tenant-public-uuid>`。
2. 租户公开标识使用稳定 UUID，数据库数字主键继续作为内部外键和 JWT `tid`。
3. 打开其他已授权租户的深链接时，前端自动切换租户并恢复同一 URL。
4. 旧链接、登录回跳、多租户选择、侧边栏切换和 Code iframe 打开遵循同一状态机。
5. 在任何业务数据请求发出前完成 URL 租户校验，避免旧租户数据短暂显示。
6. UUID 不改变授权边界；服务端仍以已签名身份和租户成员关系作为访问依据。

## 3. 非目标

- 不把数据库中的数字型 `tenants.id` 改为 UUID 主键。
- 不在本切片移除 Builder JWT 的 `tid`。
- 不引入新的租户请求 Header，也不替代路线图 P3 的请求级租户权威治理。
- 不允许仅凭 URL 中的 UUID 获取租户权限。
- 不跨仓库修改 Control Plane、Agent Runtime 或 aPaaS 的租户标识。
- 不把旧业务资源 ID 从 URL 中移除；本切片只增加显式租户上下文。

## 4. 已确认决策

1. 方案覆盖所有需要登录且具有租户上下文的页面，不只覆盖 Code 页面。
2. 查询参数名称固定为 `tenantId`，值固定为租户公开 UUID 的小写规范格式。
3. 租户公开 UUID 创建后不可变；重命名租户不改变现有链接。
4. URL 缺少 `tenantId` 时，前端用当前租户 UUID 原地 `replace` 为规范 URL。
5. URL 指向账号有权访问的其他租户时，URL resolver 调用 user store 的稳定切换接口；
   当前适配器在原子提交 token 和 user snapshot 后整页 `replace` 到原始深链接。
6. URL 指向无权访问、未知或格式非法的 UUID 时，不尝试猜测租户，也不发出目标页面
   的业务请求；回到当前模式首页并显示稳定错误提示。
7. 侧边栏主动切租户时，不保留旧租户的资源路径；进入目标模式首页，避免把旧租户的
   session、project 或 application ID 带入新租户。
8. Code URL 的规范形态为：

   ```text
   /ai-builder/code/<session-public-id>?tenantId=<tenant-public-uuid>&agent=<runtime-session-id>
   ```

   查询参数顺序不作为契约，`tenantId` 和 `agent` 均须保留。
9. 本 phase 只拥有公共 UUID、URL 解析、规范化和导航恢复；不重复实现
   `2026-07-18-builder-fast-auth-multi-sandbox-cache-design.md` 的 Auth Bootstrap、
   `tenant_epoch` 和无 reload 缓存切换。
10. URL resolver 不直接清理 Pinia store、标签页或 iframe；这些副作用只由
    `userStore.switchTenantContext()` 适配器拥有。
11. 平台管理和桌面设置等租户无关页面不得携带 `tenantId`。

## 5. 数据模型

### 5.1 Tenant 公共标识

在 `Tenant` 增加：

```text
public_id: VARCHAR(36), NOT NULL, UNIQUE, INDEXED
```

约束：

- 值必须可由标准 UUID parser 解析。
- API 序列化时输出小写连字符格式。
- 新建租户使用 UUID v4。
- 应用代码不得更新已有非空 `public_id`。
- 内部关联、JWT `tid`、数据库查询和现有外键继续使用数字型 `Tenant.id`。

### 5.2 历史数据回填

当前工程不依赖 Alembic。租户公共 ID 是启动硬依赖，不能进入会吞异常的
`_execute_best_effort()`。新增专用严格 helper
`_ensure_tenant_public_ids(conn)`，由 `init_db()` 在开放请求前调用。

固定 namespace 为：

```text
BUILDER_TENANT_PUBLIC_ID_NAMESPACE =
  UUID("13ad9ef8-0005-5fc9-a95d-ac66f5c431ed")
```

该常量版本属于 `apaas-builder-ai`，不可按部署环境配置或在后续版本重新生成。历史
租户的回填不得为同一行各自生成随机 UUID。迁移分四步：

1. 添加允许为空的 `public_id` 列。
2. 对历史租户使用固定 namespace 的 UUID v5：

   ```text
   uuid5(BUILDER_TENANT_PUBLIC_ID_NAMESPACE, "tenant:<numeric-id>")
   ```

   同一租户在任意实例上得到同一值，重试幂等。
3. 校验所有已有非空值均为规范 UUID 且全局唯一；非法值和冲突值均失败关闭。
4. 在空值为零后创建唯一索引；支持的数据库若不能在线增加 `NOT NULL`，则由启动
   doctor 和模型校验共同保证非空，后续数据库专项迁移再收紧物理约束。

并发和方言规则：

- 支持 SQLite、MySQL 和 PostgreSQL。
- 添加列或索引时，只有“对象已存在”可在重新 inspect 确认结构正确后视为成功。
- 回填使用 `UPDATE ... WHERE id=:id AND public_id IS NULL`，并发实例只能写入相同
  UUID v5。
- helper 在当前启动事务中执行；任何非预期 DDL、回填、校验或唯一索引错误必须向上
  抛出，禁止记录后继续启动。
- 新建租户由模型默认值生成 UUID v4；历史回填只使用上述 UUID v5。

启动迁移必须记录：

- `tenant_public_id_backfill_total`
- `tenant_public_id_backfill_failed`
- 冲突租户的数字 ID，但不得输出用户凭据或 token。

若存在无法回填或唯一索引冲突，应用启动失败关闭，不得在部分租户有 UUID、部分没有
UUID 的状态下继续提供登录和租户切换。

## 6. API 契约

### 6.1 公共 schema

`UserInfo` 增加：

```text
tenant_public_id: string | null
```

有租户上下文时必填规范 UUID；无租户的平台管理员为 `null`。`TenantOption` 增加：

```text
tenant_public_id: string
```

`tenant_id` 继续保留，避免破坏现有客户端和后端内部调用。

新增专用响应：

```json
{
  "access_token": "<token>",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "is_active": true,
    "is_platform_admin": true,
    "created_at": "2026-07-20T00:00:00Z",
    "tenant_id": 3,
    "tenant_public_id": "34af86ef-0af1-44bb-ae06-0b7131bc86c9",
    "tenant_name": "admin 的组织",
    "tenant_role": "platform_admin",
    "org_permissions": {"*": true}
  },
  "tenant_epoch": null,
  "request_id": "9cfc76ab-82cf-43cc-934e-776ae42f961a"
}
```

对应 schema 名为 `TenantSwitchResponse`：

- `access_token: str`，必填。
- `token_type: Literal["bearer"]`，必填。
- `user: UserInfo`，必填，必须是候选 token 对应的目标租户 snapshot。
- `tenant_epoch: int | null = null`，仅为 2026-07-18 Phase 2 预留；本 phase 不消费。
- `request_id: UUID`，必填，同时写入响应 Header `X-Request-ID` 和后端日志。

### 6.2 逐端点契约

| Endpoint | 响应契约 | `tenant_public_id` 规则 |
| --- | --- | --- |
| `POST /auth/login` | 保持现有 `LoginResponse` | 多租户分支的 `tenants[]` 必填；直接登录仍只返回 token，随后由 `/auth/me` 恢复 |
| `POST /auth/select-tenant` | 保持现有 `Token` | 选完后由 `/auth/me` 获取；请求继续使用数字 `tenant_id` |
| `POST /auth/switch-tenant` | 改为 `TenantSwitchResponse` | `user.tenant_public_id` 必须等于目标租户 UUID |
| `GET /auth/me` | `UserInfo` | 租户上下文为 UUID，无租户为 `null` |
| `GET /auth/me/tenants` | `list[TenantOption]` | 每一项必填 UUID，只返回 active 且可切换租户 |

前端 TypeScript 同步增加 `User.tenant_public_id`、`TenantOption.tenant_public_id` 和
`TenantSwitchResponse`，不使用 `any` 绕过。

### 6.3 切租户原子提交

本切片保留 `POST /auth/switch-tenant` 的数字 `tenant_id` 请求。前端只能从
`/auth/me/tenants` 返回的可访问列表中，将 URL UUID 映射到数字 ID。

服务端必须联查成员关系与 `Tenant.status == 1`。`get_auth_context()` 和
`get_auth_context_from_token()` 也必须拒绝携带停用租户的存量 token。

`POST /auth/switch-tenant` 必须是纯授权校验、候选 JWT 签发和 snapshot 投影接口：

- 删除现有 endpoint 中对 `set_current_app()` 的调用；在响应返回前不得修改
  `current_app._STATE`、alias cache、数据库或其他服务端租户状态。
- 服务端先构造并校验完整 `TenantSwitchResponse`，确认 snapshot 的数字租户 ID 和
  公共 UUID 都等于目标租户后才返回。
- `current_app` slot 改由已提交 token 的认证恢复流程同步：前端提交候选 token 并重载
  后，首个 `GET /auth/me` 使用该 token 调用 `set_current_app(user.id, tenant_id, 0, "")`。
  候选响应被拒绝、请求超时或网络中断时不会触发该同步。
- `/auth/me` 的 slot 同步是幂等的；只有已经通过认证的当前 token 可以决定 slot
  租户，不能接受 URL UUID 或请求体中的租户 ID。

`userStore.switchTenantContext()` 按以下顺序处理：

1. 保留源 token、源 user snapshot 和源 URL，不先写 `localStorage`。
2. 调用 switch endpoint，得到候选 token 和目标 user snapshot。
3. 验证 `response.user.tenant_public_id == targetTenantPublicId`。
4. 验证通过后一次性写入 token、user、available tenant context，并调用唯一的
   tenant switch side-effect adapter。
5. 当前 adapter 返回 `reload_required: true`；未来 2026-07-18 Phase 2 可改为
   `false` 并接管 `tenant_epoch`、请求取消和 tenant-scoped store 原子切换。

滚动发布期间旧后端若返回 token-only 响应，前端视为不兼容失败，不保存候选 token，
保留源上下文并提示重试。新前端发布前，发布探针必须确认所有后端实例返回
`X-Tenant-Switch-Contract: v2`；存在旧实例时不得发布新前端。若上线后仍收到 token-only
响应，视为后端 fleet 漂移并触发发布告警，不把“丢弃 token”误认为可回滚旧实例可能
已经写入的进程内 slot。

### 6.4 错误语义

沿用现有 switch endpoint 的 HTTP 状态，前端归一化为以下路由结果：

| 场景 | 路由结果 | 用户提示 |
| --- | --- | --- |
| UUID 格式非法 | 当前模式首页 | `租户链接无效` |
| UUID 不在可访问列表 | 当前模式首页 | `无权访问该租户` |
| 目标租户已停用 | 当前模式首页 | `目标租户不可用` |
| 切换请求返回 401 | 登录页，保留原始 redirect | `登录状态已失效` |
| 切换请求返回 403/404 | 当前模式首页 | `无权访问该租户` |
| 切换请求超时或 5xx | 保持当前租户首页 | `租户切换失败，请重试` |
| 切换响应 UUID 不匹配 | 当前租户首页并记录错误 | `租户切换失败，请重试` |
| 旧后端返回 token-only | 保持源租户和源 URL | `服务正在升级，请稍后重试` |

错误回退 URL 必须携带当前有效租户的 `tenantId`，不得继续保留无效目标 UUID。

## 7. 前端 URL 状态机

### 7.1 路由元数据与覆盖矩阵

主 SPA 的每个受保护路由必须显式声明：

```ts
tenantContext: 'required' | 'none'
```

未知或缺少分类的 `requiresAuth` 路由在测试中失败，在运行时拒绝挂载并回到安全首页。
子路由可继承父路由元数据。覆盖矩阵：

| 分类 | 路由 |
| --- | --- |
| `required` | `/`、`/chat/:id?`、`/ai-chat/:id?`、`/code/**`、`/db-connections`、`/apps`、`/workspace-catalog`、`/workspace/:id?`、`/tenant-logs`、`/hub`、`/skills`、`/skills/:name/workspace`、`/project/:id`、`/project/:id/git`、`/git/callback/:provider`、`/settings`、`/coding`、`/admin/mcp`、`/admin/agent-prompts`、`/work/:appId`、`/datasources`、`/platform-envs`、`/tenant-users`、`/knowledge`、`/generate/:id?` |
| `none` | `/platform-admin/:pathMatch(.*)*`、`/admin/tenants`、`/desktop-setup`、`/desktop-unavailable` |
| public | `/login`、`/tenant-select`、公共错误页 |

独立 `admin-spa` 的全部路由均为平台级 `tenantContext: none`，内部 URL 不增加
`tenantId`。外层 `/platform-admin/**` 进入时若携带旧 `tenantId`，主 SPA 使用
`router.replace` 删除它。

### 7.2 执行顺序

守卫必须按以下顺序执行：

1. 恢复本地 token 并调用 `/auth/me`。
2. 对 `tenantContext: none` 删除 `tenantId` 后继续。
3. 对 `tenantContext: required` 获取当前 `tenant_public_id` 和可访问租户列表。
4. 解析目标 URL 的 `tenantId`。
5. 在允许目标页面组件挂载和业务请求前完成规范化、拒绝或切换。
6. 租户一致后再执行权限守卫和目标页面加载。

租户决议前允许的请求白名单只有：

- `/auth/me`
- `/auth/me/tenants`
- `/auth/switch-tenant`
- `/auth/tenant-url-events`

目标页面组件、Code iframe 和其他 `/api/**` 请求均不得启动。

### 7.3 状态转移

#### A. URL 缺少 `tenantId`

使用 `router.replace` 保留 path、其他 query 和 hash，只增加当前租户 UUID。该操作
不得加入浏览器历史。

#### B. URL UUID 等于当前租户

直接继续导航，不请求 switch endpoint。

#### C. URL UUID 属于其他可访问租户

1. 写入 `sessionStorage` 切换标记：

   ```json
   {
     "targetTenantPublicId": "<uuid>",
     "targetFullPath": "<fullPath>",
     "startedAt": "<unix-ms>",
     "attempt": 1
   }
   ```

2. 调用 `switchTenantContext(mappedNumericTenantId, targetTenantPublicId)`。
3. store 在保存候选 token 前校验目标 user snapshot，并原子提交。
4. 当前 adapter 返回 `reload_required: true` 时，使用
   `window.location.replace(targetFullPath)` 整页恢复，不新增历史记录。
5. 未来 adapter 返回 `reload_required: false` 时，router 使用
   `router.replace(targetFullPath)`；URL 状态机本身不变。

#### D. URL UUID 非法或不可访问

中止目标导航，清除切换标记，使用当前路由模式对应首页替换 URL，并显示一次性错误。

### 7.4 循环保护

- 同一 `targetTenantPublicId + targetFullPath` 最多自动切换一次。
- 切换标记有效期 30 秒，过期后删除。
- 重载后若当前租户已等于目标，删除标记并继续。
- 重载后仍不一致且已有一次尝试，停止自动切换并回到当前租户首页。
- 多个并发导航只允许一个租户切换 promise；后续导航等待同一结果。

该保护只防止前端循环，不能替代服务端权限校验。

## 8. 登录与多租户选择

### 8.1 未登录深链接

访问带 `tenantId` 的受保护页面时，登录跳转继续保存完整 `to.fullPath`，包括 query
和 hash。登录成功后：

- 单租户账号：若租户 UUID 匹配则回跳；不匹配则按无权访问处理。
- 多租户账号：`LoginResponse.tenants[]` 已包含 UUID；若目标 UUID 存在，使用对应数字
  ID 调用 `/auth/select-tenant` 后回跳。
- 目标 UUID 不可访问：进入当前或默认可访问租户首页，并显示无权访问提示。

### 8.2 无 `tenantId` 的旧登录链接

继续使用现有默认租户或用户选择结果。认证完成后，目标受保护 URL 由全局守卫补充
当前租户 UUID。

### 8.3 Open redirect 边界

`redirect` 只允许站内路径。现有 redirect 校验必须覆盖带 query/hash 的 URL，不允许
协议相对路径、绝对 URL 或编码后绕过。

## 9. 主动切租户

侧边栏租户菜单以 `tenant_public_id` 作为选中值和导航目标，但调用后端时映射为数字
`tenant_id`。

主动切换不恢复当前资源路径，目标地址按当前产品模式选择：

| 当前模式 | 目标地址 |
| --- | --- |
| AI Builder | `/ai-builder/?tenantId=<target-uuid>` |
| Code | `/ai-builder/code/apps?tenantId=<target-uuid>` |

目标首页直接复用 `MODE_META.builder.home` 和 `MODE_META.code.home`。平台管理页面是
`tenantContext: none`，不显示租户业务切换入口，也不生成带 `tenantId` 的管理后台
URL。未登记模式回退 Builder 首页。

## 10. Code 深链接与运行时

Code 页面遵循通用租户守卫后才执行 application、session、open、activate 等请求。

必须保证：

1. 目标租户切换完成前不创建 iframe。
2. `tenantId` 始终保留在外层 Builder URL，不拼入 Runtime 上游 URL。
3. `agent` 参数切换或激活时保留 `tenantId`。
4. create/activate/delete Agent Session 使用 Builder Bearer 鉴权的
   `/code/sessions/...` 外层 API，不回退到依赖 Runtime Cookie 的
   `/code-runtime/...` 路径。
5. 首次打开分享链接不要求先访问无 `agent` URL 以建立 Cookie。

## 11. 缓存与存储所有权

URL resolver 不直接清理任何 tenant-scoped store。唯一 owner 是
`userStore.switchTenantContext()` 的 side-effect adapter：

- 当前 adapter 复用既有整页 reload，提交新 token/user 后清除持久化标签页并关闭旧
  iframe，其他内存状态由重载释放。
- 2026-07-18 Phase 2 接管后，由其统一取消旧请求、切换 `tenant_epoch`、隔离查询
  cache 和关闭热帧；本 phase 不再创建第二套 invalidation 列表。
- URL resolver 只接收 `{reload_required, destination}`，不导入具体业务 store。

主题、语言和界面偏好始终不清理。切换标记在目标 UUID 验证成功后删除。

## 12. 并发、失败与恢复

### 12.1 多标签页

多个标签页共享 `localStorage` token，因此本切片明确采用“最后成功切换的租户在所有
标签页收敛”策略，不支持不同标签页长期停留在不同租户。

收到其他标签页的 token storage event 时：

1. 当前标签页不按旧 URL 自动切回，避免两个标签页互相重签 token。
2. 捕获 `event.newValue` 为不可变 `eventToken`，递增
   `storageAlignmentGeneration`，并取消上一轮仍在执行的对齐请求。
3. 使用显式 `Authorization: Bearer <eventToken>` 调用 `/auth/me`，不得让请求拦截器
   在稍后重新读取共享 `localStorage.token`。
4. 响应落地前同时校验 generation 仍为最新，且 `localStorage` 中的当前 token 与
   `eventToken` 完全一致；任一不满足都丢弃响应，不导航、不写 user。
5. 停止挂载新业务内容；当前 adapter 使用
   `window.location.replace(currentModeHome?tenantId=<new-uuid>)` 收敛到新租户首页。
6. 若新 token 无租户，则进入 `/platform-admin/`。
7. 只有用户后续显式打开旧深链接，才允许再次触发一次自动切换。

两个标签页并发发起不同切换时，以最后完成且写入 storage 的响应为准；每个标签页
最多再执行一次 storage 对齐导航，不得自动反向切换。测试必须注入“token B 的
`/auth/me` 慢返回、token A 后写入且快返回”的乱序场景，最终只能落地 A。

### 12.2 网络失败

自动切换不在前端重试 switch POST，避免重复签发和循环。用户可以从错误提示重新
触发导航或主动切换。超时或 5xx 不加载目标页面，也不删除当前有效 token。

### 12.3 部分成功

如果 switch endpoint 已返回但响应 snapshot 验证失败，源 token 从未被覆盖，直接回
源租户首页。如果原子提交已完成但重载失败，切换标记保留至 30 秒。恢复时重新读取
token 和 `/auth/me`：

- 当前 UUID 等于目标：继续原深链接。
- 当前 UUID 不等于目标：按循环保护回当前租户首页。

## 13. 安全边界

- UUID 是不可枚举性更好的公开标识，不是 secret，也不是授权凭据。
- 服务端所有 tenant-scoped 查询继续使用认证上下文中的数字 `tenant_id`。
- 前端不得把 URL UUID 直接发送为可信数据库过滤条件。
- UUID 到数字 ID 的映射只来自当前身份可访问租户列表。
- 日志允许记录租户 UUID、数字 ID、路由结果和 request ID；不得记录密码、JWT、
  Runtime token、Cookie 或完整 Authorization Header。
- 返回 403/404 时不暴露租户是否真实存在，用户提示统一为无权访问。

## 14. 可观测性

新增 `POST /auth/tenant-url-events`，只接受认证用户的非正常或状态变化事件：

```text
tenant_url_resolution
  outcome=canonicalized|switched|rejected|failed|loop_prevented|storage_aligned
  source=initial_load|router_navigation|login_redirect|tenant_menu|storage_event
  current_tenant_public_id
  target_tenant_public_id
  route_name
  request_id
```

匹配成功的普通导航不发送事件。endpoint 校验 enum 和 UUID，每用户每分钟最多 30 次，
返回 204；只写结构化日志和低基数指标，不保存独立业务表。所有事件都必须携带 UUID v4
request ID：

- `switched` 复用 `TenantSwitchResponse.request_id`。
- `canonicalized`、`rejected`、`failed`、`loop_prevented` 和 `storage_aligned` 由前端
  在事件产生时调用 `crypto.randomUUID()`。
- endpoint 在 204 响应 Header `X-Request-ID` 原样返回已校验的 request ID，并在日志
  使用同一值；服务端不得用租户 UUID 或用户 ID 代替 request ID。

后端 switch 日志增加：

```text
tenant_switch
  user_id
  source_tenant_id
  target_tenant_id
  target_tenant_public_id
  outcome
  request_id
```

最低监控指标：

- `tenant_url_resolution_total{outcome}`
- `tenant_switch_total{outcome}`
- `tenant_switch_duration_seconds`
- `tenant_public_id_backfill_failed`
- Code 首次深链接 activate 的 401 数量

实现复用 `backend/app/code_runtime/sandbox_metrics.py` 的 in-process registry/render
模式，新建 auth 专用 registry，禁止把 user ID、租户 ID、UUID 或 route name 作为
指标 label。switch request ID 写入响应 body、`X-Request-ID` Header 和日志；URL event
request ID 按上面的来源规则写入请求、204 Header 和日志。

前端构建必须注入 `VITE_BUILD_SHA`，并在 `index.html` 输出：

```html
<meta name="builder-build-sha" content="%VITE_BUILD_SHA%">
```

线上 smoke 读取该 meta，确认值等于部署 revision，且该 revision 的祖先包含
`49a4bef4`。静态资源 hash 或 `Last-Modified` 不能替代该证明。

## 15. 兼容、发布与回滚

### 15.1 滚动发布顺序

1. 发布数据库列、幂等回填和后端响应字段。
2. 确认所有租户均有唯一 `public_id`，`/auth/me` 和租户列表稳定返回 UUID。
3. 发布探针对每个后端实例验证 `/auth/switch-tenant` 契约版本为
   `X-Tenant-Switch-Contract: v2`，确认旧实例为零。
4. 发布前端 URL 状态机和导航改造。
5. 构建时注入当前 Git SHA，发布包含 `49a4bef4` Code 外层会话鉴权修复的静态资源。
6. 执行线上登录、切租户、分享链接和 Code 首开验证。

后端先发布期间旧前端忽略新增字段。前端发布前不得依赖尚未完成回填的 UUID。

### 15.2 回滚

- 前端可回滚到不解释 `tenantId` 的版本，额外 query 对旧路由无副作用。
- 后端可回滚应用代码，但保留 `public_id` 列和数据，不删除、不重新生成。
- 不回滚历史 UUID 值，确保已分享链接在再次发布后仍然有效。
- 若前端故障而后端正常，优先只回滚前端；不得通过清空租户 UUID 恢复。

## 16. 验证策略

### 16.1 后端测试

- 新租户生成合法、唯一、稳定的 UUID v4。
- 历史回填精确等于固定 namespace 的 UUID v5，重复和并发执行结果一致。
- SQLite 文件数据库执行重入测试；MySQL 和 PostgreSQL 容器执行真实 DDL/并发测试。
- 回填异常、非法现有值、唯一冲突和索引失败均使 `init_db()` 抛错且服务不 ready。
- `/auth/me`、登录多租户列表和 `/auth/me/tenants` 包含正确 UUID/null 语义。
- switch 返回完整 `TenantSwitchResponse`，body/header/log 使用同一 request ID。
- switch 成功、失败、超时模拟和响应序列化异常都不修改 `current_app` slot；只有使用
  已提交 token 的 `/auth/me` 才同步目标 slot。
- 无成员关系、停用租户、未知租户和携带停用租户的存量 token 均被拒绝。
- 旧客户端只发送数字 `tenant_id` 仍可工作。
- tenant URL event 覆盖非法 enum/UUID、缺失 request ID、每用户第 31 次请求返回 429、
  成功返回 204 和同值 `X-Request-ID`、日志敏感字段排除及指标增量断言。

固定命令：

```bash
cd backend
pytest -q tests/test_tenant_public_id.py tests/test_tenant_public_id_migration.py tests/test_tenant_url_auth.py
bash tests/integration/run_tenant_public_id_dialects.sh
```

`run_tenant_public_id_dialects.sh` 是本 phase 必须交付的固定 runner：

- 启动 `mysql:8.4` 和 `postgres:16` 临时容器，等待各自 health check 通过。
- 分别通过 `TEST_DATABASE_URL` 启动全新的 Python 子进程；子进程必须在导入
  `app.database` 前把 `DATABASE_URL=TEST_DATABASE_URL` 写入环境，不能复用会
  `setdefault` 为 SQLite 的 `backend/tests/conftest.py` 进程。
- 每种方言用两个独立 Python 进程同时执行 `_ensure_tenant_public_ids()`，断言退出码均
  为零、历史行 UUID 精确、空值为零、唯一索引存在且重复执行无变化。
- runner 使用 trap 删除容器和临时 volume；任一 ready、DDL、并发、断言或清理前测试
  步骤失败都返回非零。

### 16.2 前端单元测试

- 缺少 UUID 时规范化且保留其他 query/hash。
- 当前 UUID 匹配时不切换。
- 可访问的其他 UUID 只调用一次 switch，并恢复同一 fullPath。
- 非法、未知和无权 UUID 不挂载目标页面。
- 401、403、404、5xx、超时和响应 UUID 不匹配按表格回退。
- 切换标记过期、一次重试和并发导航不会形成循环。
- `router.getRoutes()` 验证所有受保护路由都有 `tenantContext` 分类。
- tenant 决议前只允许 auth 白名单请求，目标组件和 iframe 均未挂载。
- token-only 旧响应和 UUID 不匹配都不覆盖源 token。
- storage event 使其他标签页对齐新租户首页，不自动切回旧 URL。
- storage event 的旧 generation、已 abort 请求和 token 不相等响应均不得落地；乱序
  `/auth/me(B)` 晚于 `/auth/me(A)` 返回时只能导航到 A。
- 登录和多租户选择保留并消费目标 UUID。
- 侧边栏切换进入目标模式首页，不携带旧资源 ID。
- Code 的 `agent` 更新保留 `tenantId`。
- admin-spa 和平台管理路由移除或拒绝 `tenantId`。

固定命令：

```bash
cd frontend
npm test -- src/router/tenantUrlGuard.spec.ts src/stores/user.tenantSwitch.spec.ts \
  src/views/codeFrameLifecycle.spec.ts
npm run build
```

### 16.3 浏览器 E2E

新增 `tests/e2e/builder-tenant-url-public-uuid.spec.mjs`，fixture 创建当前租户、可访问
目标租户、停用租户和无权 UUID。网络断言在 tenant 决议前：

- 只允许 `/auth/me`、`/auth/me/tenants`、`/auth/switch-tenant` 和事件 endpoint。
- 其他业务 API 请求数为零。
- 目标页面组件和 iframe 未挂载。

使用真实浏览器验证：

1. 使用受控测试管理员账号和 `<password>` 登录并进入目标组织。
2. 地址栏显示该租户 UUID。
3. 复制 Code 深链接到无登录会话，登录后自动进入正确租户和原 session。
4. 从另一租户上下文打开该链接，只发生一次 switch。
5. 无权 UUID 不发出目标业务 API 请求。
6. 旧的无 UUID 链接被规范化。
7. 首次直接打开带 `agent` 的 Code 链接，create/activate 请求成功，不出现
   `Code runtime token required`。
8. 切租户后不显示旧租户的应用、会话或 iframe。
9. 两个标签页分别打开不同租户链接后，switch 次数有界并最终收敛到最后成功租户。
10. 首次 Code 激活只调用 `/api/code/sessions/.../activate`，不调用
    `/api/code-runtime/.../activate`，401 数量为零。
11. Chromium 与 Edge channel 至少各执行一次关键深链接流程；若 Edge channel
    不可用，安装失败必须作为发布 blocker，不用 Chromium 冒充。

固定命令：

```bash
npm exec -- playwright install chromium msedge
node tests/e2e/builder-tenant-url-public-uuid.spec.mjs
```

### 16.4 发布版本与线上 telemetry smoke

实现必须交付 `scripts/verify_builder_tenant_url_release.sh`，固定调用方式：

```bash
cd /path/to/apaas-builder-ai
BUILD_SHA="$(git rev-parse HEAD)"
VITE_BUILD_SHA="$BUILD_SHA" npm --prefix frontend run build
BUILDER_ORIGIN="https://<builder-origin>" \
DEPLOYED_REVISION="$BUILD_SHA" \
bash scripts/verify_builder_tenant_url_release.sh
```

脚本必须：

1. `curl -fsS "$BUILDER_ORIGIN/ai-builder/"` 解析唯一
   `meta[name=builder-build-sha]`。
2. 断言 meta 值等于 `DEPLOYED_REVISION`，且为 40 位小写 Git SHA。
3. 执行 `git merge-base --is-ancestor 49a4bef4 "$DEPLOYED_REVISION"`；失败即发布失败。
4. 使用受控 Bearer 凭据向 `/api/auth/tenant-url-events` 发送合法、非法和 31 次限流
   请求，断言 204/422/429、同值 `X-Request-ID`，并从 metrics endpoint 断言对应
   `tenant_url_resolution_total{outcome}` 只按低基数 outcome 增量。
5. 检查响应和采集日志样本不包含 Authorization、JWT、Cookie 或密码。

## 17. 验收标准

- 所有有租户上下文的受保护页面在稳定状态下都包含合法 `tenantId` UUID。
- URL UUID 与 `/auth/me.tenant_public_id` 始终一致后才加载业务页面。
- 已授权跨租户深链接自动切换并恢复原路径、query 和 hash。
- 无权或非法 UUID 失败关闭，且不会泄漏租户存在性。
- 旧链接保持可用并自动规范化。
- 侧边栏切租户不会携带旧租户资源 ID。
- UUID 回填可重入、并发一致，回滚不改变已生成 UUID。
- 停用租户不能切入，携带停用租户的存量 token 不能继续访问。
- 两个标签页不会因不同显式 URL 持续互相切租户。
- switch endpoint 不修改 `current_app`；只有已提交 token 的 `/auth/me` 同步 slot。
- storage event 的乱序响应不能覆盖最后写入的共享 token。
- Code 首次分享链接不再需要无 `agent` 预热，且 activate 不返回
  `Code runtime token required`。
- 后端、前端和浏览器测试均通过；`builder-build-sha` 等于部署 revision，且该 revision
  的祖先包含 `49a4bef4`。

## 18. 实施边界

实施计划应优先复用：

- `frontend/src/router/index.ts` 的全局守卫。
- `frontend/src/stores/user.ts` 的用户恢复流程，并把现有 `switchTenant` 收敛为
  `switchTenantContext` 稳定接口。
- `frontend/src/components/v2/RailSidebar.vue` 的租户菜单。
- `frontend/src/stores/mode.ts` 的 Builder/Code 首页，不新增 admin mode。
- 登录和多租户选择现有 `redirect` 契约。
- `backend/app/database.py` 的 `init_db()`，但租户 UUID 使用独立严格 helper，禁止走
  `_execute_best_effort()`。
- 现有 UUID public ID 模式和 Code 外层 session API。
- `backend/app/code_runtime/sandbox_metrics.py` 的 registry/render 模式。

与 `2026-07-18-builder-fast-auth-multi-sandbox-cache-design.md` 的边界：

- 本 phase 拥有 `tenant_public_id`、路由 metadata、URL resolver、登录 redirect 消费
  和稳定 switch response。
- 7 月 18 日设计拥有 Auth Bootstrap、`tenant_epoch` 的最终语义、无 reload 切换、
  请求取消和 tenant-scoped cache。
- 当前 adapter 的整页 reload 是兼容实现，不在 URL resolver 中复制 cache 清理逻辑；
  后续替换 adapter 时 URL、API UUID 和路由测试不变。

除非代码证据表明现有边界无法承载，不新建第二套路由器、租户状态管理器、token
存储或数据库迁移框架。
