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
**状态**：已完成复审修订，待只读复核
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
   当前适配器先用候选 token 显式调用 `/auth/me` 验证目标 UUID，再提交 token 和 user，
   最后整页 `replace` 到原始深链接。
6. URL 指向无权访问、未知或格式非法的 UUID 时，不尝试猜测租户，也不发出目标页面
   的业务请求；回到当前模式首页并显示稳定错误提示。
7. 侧边栏主动切租户时，不保留旧租户的资源路径；进入目标模式首页，避免把旧租户的
   session、project 或 application ID 带入新租户。
8. Code URL 的规范形态为：

   ```text
   /ai-builder/code/<session-public-id>?tenantId=<tenant-public-uuid>&agent=<runtime-session-id>
   ```

   查询参数顺序不作为契约，`tenantId` 和 `agent` 均须保留。
9. 本 phase 只拥有公共 UUID、URL 解析、规范化、候选 token 验证和导航恢复；不重复实现
   `2026-07-18-builder-fast-auth-multi-sandbox-cache-design.md` 的 Auth Bootstrap、
   `tenant_epoch` 和无 reload 缓存切换。
10. URL resolver 不直接清理 Pinia store、标签页或 iframe；这些副作用只由
    `userStore.switchTenantContext()` 适配器拥有。
11. 平台管理和桌面设置等租户无关页面不得携带 `tenantId`。

## 5. 数据模型

### 5.1 Tenant 公共标识

在 `Tenant` 增加：

```text
public_id: VARCHAR(36), NULLABLE, UNIQUE, INDEXED
```

约束：

- 值必须可由标准 UUID parser 解析。
- API 序列化时输出小写连字符格式。
- 所有当前版本的新建租户写入路径必须显式赋 UUID v4。
- 应用代码不得更新已有非空 `public_id`。
- 内部关联、JWT `tid`、数据库查询和现有外键继续使用数字型 `Tenant.id`。
- 本 phase 不把数据库列收紧为 `NOT NULL`。物理 nullable 是旧二进制滚动共存和回滚
  窗口的兼容边界，不代表新版本 API 允许返回空 UUID。

### 5.2 历史数据回填

当前工程不依赖 Alembic。新增专用严格 helper
`_ensure_tenant_public_ids(conn)`，由 `init_db()` 在开放请求前调用，并提供复用同一
helper 的发布后 reconciliation CLI。它不能进入会吞异常的 `_execute_best_effort()`。

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
4. 在当前快照空值为零后创建唯一索引；列继续允许为空，避免滚动期间旧 writer 和
   回滚二进制因缺少该字段而写入失败。

并发和方言规则：

- 支持 SQLite、MySQL 和 PostgreSQL。
- 添加列或索引时，只有“对象已存在”可在重新 inspect 确认结构正确后视为成功。
- 回填使用 `UPDATE ... WHERE id=:id AND public_id IS NULL`，并发实例只能写入相同
  UUID v5。
- helper 在当前启动事务中执行；任何非预期 DDL、回填、校验或唯一索引错误必须向上
  抛出，禁止记录后继续启动。
- 当前版本所有 `Tenant(...)` writer 都显式或通过统一 ORM helper 生成 UUID v4。
- 滚动期间旧实例或回滚版本新建的空值行，由启动 helper、发布后 reconciliation 和
  后续新版本读取前的严格投影 helper 使用上述 UUID v5 补齐；已有非空 UUID 永不改写。
- 发布脚本在全部 Pod 更新后必须再次运行 reconciliation，断言 `NULL=0` 后才放行。
- 回滚到旧二进制时必须同时回滚前端到不要求 `tenantId` 的版本；允许旧 writer 暂时
  产生 NULL。再次升级时先 reconcile，再启用 UUID URL。

启动迁移必须记录：

- `tenant_public_id_backfill_total`
- `tenant_public_id_backfill_failed`
- 冲突租户的数字 ID，但不得输出用户凭据或 token。

若启动时已有行无法回填或唯一索引冲突，应用启动失败关闭。滚动期间旧 writer 新增的
NULL 行不能由新版本 API 投影为缺失 UUID：投影 helper 必须在当前事务内补齐并校验，
失败时该认证请求失败关闭。

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

`tenant_id` 继续保留，避免破坏现有客户端和后端内部调用。本 phase 不新增 switch
response schema。

### 6.2 逐端点契约

| Endpoint | 响应契约 | `tenant_public_id` 规则 |
| --- | --- | --- |
| `POST /auth/login` | 保持现有 `LoginResponse` | 多租户分支的 `tenants[]` 必填；直接登录仍只返回 token，随后由 `/auth/me` 恢复 |
| `POST /auth/select-tenant` | 保持现有 `Token` | 选完后由 `/auth/me` 获取；请求继续使用数字 `tenant_id` |
| `POST /auth/switch-tenant` | 保持现有 `Token` | 请求继续使用数字 `tenant_id`；候选 token 由显式 `/auth/me` 校验 |
| `GET /auth/me` | `UserInfo` | 租户上下文为 UUID，无租户为 `null` |
| `GET /auth/me/tenants` | `list[TenantOption]` | 每一项必填 UUID，只返回 active 且可切换租户 |

前端 TypeScript 只增加 `User.tenant_public_id` 和 `TenantOption.tenant_public_id`，
继续复用现有 `Token`，不新增平行 switch DTO，也不使用 `any` 绕过。

### 6.3 候选 token 验证与浏览器提交

本切片保留 `POST /auth/switch-tenant` 的数字 `tenant_id` 请求。前端只能从
`/auth/me/tenants` 返回的可访问列表中，将 URL UUID 映射到数字 ID。

服务端必须联查成员关系与 `Tenant.status == 1`。`get_auth_context()` 和
`get_auth_context_from_token()` 也必须拒绝携带停用租户的存量 token。

`current_app._STATE` 是现有进程内 MCP/app hint，不是本 phase 的租户权威，也不能用于
证明多 worker 或多 Pod 的浏览器租户一致性。本 phase 不新增 `/auth/me` slot 同步、
generation 或共享状态，不改变现有 MCP 生命周期。所有 Builder tenant-scoped API 仍
以已验证 JWT 的数字 `tid` 为权威。`current_app` 的 fleet 一致性由
`2026-07-18-builder-fast-auth-multi-sandbox-cache-design.md` 或后续共享状态 phase 处理。

`userStore.switchTenantContext()` 按以下顺序处理：

1. 保留源 token、源 user snapshot 和源 URL，不先写 `localStorage`。
2. 调用现有 switch endpoint，得到候选 `Token`。
3. 使用不读取、不覆盖 `localStorage` 的 `authApi.getMeWithToken(candidateToken)`，
   以显式 `Authorization: Bearer <candidateToken>` 调用 `/auth/me`。
4. 验证候选 `UserInfo.tenant_id == mappedNumericTenantId` 且
   `tenant_public_id == targetTenantPublicId`。
5. 验证通过后一次性写入 token、user、available tenant context，并调用唯一的
   tenant switch side-effect adapter。
6. 当前 adapter 返回 `reload_required: true`；未来 2026-07-18 Phase 2 可改为
   `false` 并接管 `tenant_epoch`、请求取消和 tenant-scoped store 原子切换。

`frontend/src/utils/request.ts` 的拦截器必须保留调用方显式提供的 Authorization，不得
用当前 `localStorage.token` 覆盖候选 token。候选 `/auth/me` 的 401/403/5xx、超时、
UUID/数字 ID 不匹配或序列化缺字段都不提交本地状态。现有 switch endpoint 的
`current_app` side effect 属于已知遗留行为，不纳入本 phase 的原子性承诺，也不得被
前端用于判断切换成功。

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
| 候选 `/auth/me` UUID 或数字 ID 不匹配 | 当前租户首页并记录错误 | `租户切换失败，请重试` |
| 候选 `/auth/me` 缺少 UUID | 保持源租户和源 URL | `服务正在升级，请稍后重试` |

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
3. store 使用候选 token 显式调用 `/auth/me`，在保存前校验目标 user snapshot。
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

### 8.4 表单字段边界

`login-deep-link` 提交字段保持现有 `username`、`password`、`captcha_id` 和
`captcha_code`；`redirect` 与目标 `tenantId` 是客户端保留状态，不新增到
`UserLogin`。验证码由现有登录响应和页面状态决定，失败时保留安全 redirect。

`multi-tenant-selection` 只提交现有 `selection_token + tenant_id`。
`tenant_public_id` 只用于从 `LoginResponse.tenants[]` 映射对应数字 ID，不加入
`TenantSelectRequest`。选择成功后先调用 `/auth/me`，再消费原始 redirect。

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

如果 switch endpoint 已返回但候选 `/auth/me` 验证失败，源 token 从未被覆盖，直接回
源租户首页。如果浏览器提交已完成但重载失败，切换标记保留至 30 秒。恢复时重新读取
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

本 phase 不新增浏览器事件上报 endpoint、不新增第二套 metrics registry，也不新增专用
metrics URL。服务端在现有 switch endpoint 增加结构化日志：

```text
tenant_switch
  user_id
  source_tenant_id
  target_tenant_id
  target_tenant_public_id
  outcome
```

迁移日志固定记录 reconciliation 扫描数、补齐数、失败数和冲突数字租户 ID。浏览器
URL resolver 的正常、拒绝、循环保护和 storage 对齐通过单元测试与 E2E 形成证据，
不把 route name、UUID 或用户 ID 引入指标 label。Code 首次激活 401 继续复用现有
Code runtime 诊断和 `/code/internal/sandbox-auth-metrics`，不得建立平行端点。

前端构建必须注入 `VITE_BUILD_SHA`，并在 `index.html` 输出：

```html
<meta name="builder-build-sha" content="%VITE_BUILD_SHA%">
```

线上 smoke 读取该 meta，确认值等于部署 revision，且该 revision 的祖先包含
`49a4bef4`。静态资源 hash 或 `Last-Modified` 不能替代该证明。

## 15. 兼容、发布与回滚

### 15.1 单镜像滚动发布

现有镜像同时包含后端和 `frontend/dist`，本 phase 不虚构前后端两阶段发布。发布 owner
保持 `.gitlab-ci.yml`、`scripts/deploy_online_latest_kubesphere.sh` 和现有 StatefulSet：

1. CI 用 `CI_COMMIT_SHA` 作为 `VITE_BUILD_SHA` Docker build arg 构建一个镜像，并从
   BuildKit metadata 解析内容 digest；后续部署固定使用
   `<repository>@sha256:<digest>`，不使用可变 tag 作为发布身份。
2. 同一镜像同时更新 backend container 与 `copy-frontend-dist` initContainer。
3. 滚动期间保持 API 向后兼容：旧前端忽略新增 UUID；新前端仍消费旧有 `Token` switch
   响应。若命中旧后端而 `/auth/me` 缺 UUID，新前端失败关闭并提示稍后重试。
4. rollout 完成后，现有发布脚本完成部署 job；依赖该 job 的 browser-smoke job 调用
   共享 smoke helper。逐 Pod 断言 Ready、backend 与 dist initContainer 使用同一预期
   digest，并确认旧 Pod 为零。
5. 在一个新 Pod 内执行租户 UUID reconciliation CLI，断言 `NULL=0`、UUID 合法唯一。
6. 公网读取 `builder-build-sha`，确认等于部署 commit 且祖先包含 `49a4bef4`。
7. 使用受控测试账号执行登录、切租户、分享链接和 Code 首开验证。

### 15.2 回滚

- 前端可回滚到不解释 `tenantId` 的版本，额外 query 对旧路由无副作用。
- 回滚必须使用旧后端和旧前端的同一历史镜像，保留 nullable `public_id` 列和已有值。
- 回滚窗口内旧 writer 可产生 NULL；下一次升级在启用 UUID URL 前重新 reconcile。
- 不回滚历史 UUID 值，确保已分享链接在再次发布后仍然有效。
- 现有单镜像部署不支持“只回滚前端”的承诺；不得通过清空租户 UUID 恢复。

## 16. 验证策略

### 16.1 后端测试

- 新租户生成合法、唯一、稳定的 UUID v4。
- 历史回填精确等于固定 namespace 的 UUID v5，重复和并发执行结果一致。
- SQLite 文件数据库执行重入测试；MySQL 和 PostgreSQL 容器执行真实 DDL/并发测试。
- 回填异常、非法现有值、唯一冲突和索引失败均使 `init_db()` 抛错且服务不 ready。
- 旧 writer 模拟插入 NULL 后，reconciliation 再次补齐；旧二进制面对 nullable schema
  的创建与回滚兼容测试通过。
- `/auth/me`、登录多租户列表和 `/auth/me/tenants` 包含正确 UUID/null 语义。
- switch 继续返回现有 `Token`，不新增 body/header contract。
- 无成员关系、停用租户、未知租户和携带停用租户的存量 token 均被拒绝。
- 旧客户端只发送数字 `tenant_id` 仍可工作。
- switch 和 reconciliation 结构化日志不包含密码、JWT、Cookie 或 Authorization。

固定命令：

```bash
cd backend
python -m pip install -r requirements.txt
test -f tests/test_tenant_public_id.py
test -f tests/test_tenant_public_id_migration.py
test -f tests/test_tenant_url_auth.py
python -m pytest -q \
  tests/test_tenant_public_id.py \
  tests/test_tenant_public_id_migration.py \
  tests/test_tenant_url_auth.py
docker info >/dev/null
bash tests/integration/run_tenant_public_id_dialects.sh
```

`run_tenant_public_id_dialects.sh` 是本 phase 必须交付的固定 runner：

- 启动 `mysql:8.4` 和 `postgres:16` 临时容器，等待各自 health check 通过。
- 分别通过 `TEST_DATABASE_URL` 启动全新的 Python 子进程；子进程必须在导入
  `app.database` 前把 `DATABASE_URL=TEST_DATABASE_URL` 写入环境，不能复用会
  `setdefault` 为 SQLite 的 `backend/tests/conftest.py` 进程。
- 每种方言用两个独立 Python 进程同时执行 `_ensure_tenant_public_ids()`，断言退出码均
  为零、历史行 UUID 精确、空值为零、唯一索引存在且重复执行无变化。
- 每种方言模拟旧 writer 在首次回填后插入 NULL，再运行 reconciliation，断言新行得到
  确定性 UUID v5；旧 writer 对 nullable schema 的 insert 不失败。
- runner 使用 trap 删除容器和临时 volume；任一 ready、DDL、并发、断言或清理前测试
  步骤失败都返回非零。
- `.gitlab-ci.yml` 新增独立 Docker-capable verify job，显式配置 DinD service 并调用
  该 runner；日志逐项输出 `sqlite=passed`、`mysql=passed`、`postgresql=passed`。

### 16.2 前端单元测试

- 缺少 UUID 时规范化且保留其他 query/hash。
- 当前 UUID 匹配时不切换。
- 可访问的其他 UUID 只调用一次 switch，并恢复同一 fullPath。
- 非法、未知和无权 UUID 不挂载目标页面。
- 401、403、404、5xx、超时和响应 UUID 不匹配按表格回退。
- 切换标记过期、一次重试和并发导航不会形成循环。
- `router.getRoutes()` 验证所有受保护路由都有 `tenantContext` 分类。
- tenant 决议前只允许 auth 白名单请求，目标组件和 iframe 均未挂载。
- 候选 `/auth/me` 缺 UUID、数字 ID 不匹配或 UUID 不匹配都不覆盖源 token。
- 显式 Authorization 不被请求拦截器中的 `localStorage.token` 覆盖。
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
npm ci
test -f src/router/tenantUrlGuard.spec.ts
test -f src/stores/user.tenantSwitch.spec.ts
test -f src/utils/request.explicitAuth.spec.ts
test -f src/views/codeFrameLifecycle.spec.ts
npm exec -- vitest run \
  src/router/tenantUrlGuard.spec.ts \
  src/stores/user.tenantSwitch.spec.ts \
  src/utils/request.explicitAuth.spec.ts \
  src/views/codeFrameLifecycle.spec.ts \
  --reporter=verbose
npm run build
```

禁止通过 `npm test -- ...` 的 `--passWithNoTests` 路径验收；任一测试文件缺失、未收集
测试或依赖未安装都必须非零退出。

### 16.3 浏览器 E2E

根 `package.json` 是所有 `tests/e2e/*.mjs` 的唯一 Playwright package owner，版本固定为
`1.61.1`；移除 `frontend/package.json` 中重复的 Playwright dependency。新增
`tests/e2e/builder-tenant-url-public-uuid-fixture.sh` 和
`tests/e2e/builder-tenant-url-public-uuid.spec.mjs`。fixture 必须复用
`builder-sandbox-auth-renewal-fixture.sh` 的自包含模式：

- 创建临时 SQLite 数据库、当前租户、可访问目标租户、停用租户、无权 UUID、管理员
  用户、Code session 和 Agent session。
- 计算 `BUILD_SHA="$(git rev-parse HEAD)"`，强制执行
  `VITE_BUILD_SHA="$BUILD_SHA" npm --prefix frontend run build`，断言
  `frontend/dist/index.html` 存在且唯一 `builder-build-sha` meta 精确等于该 40 位 SHA，
  再在随机空闲端口启动后端与构建后的前端入口并等待 health/content ready。
- 通过环境变量把 Builder base URL、fixture ID 和浏览器 channel 传给 `.mjs`。
- trap 关闭子进程并删除临时数据库、日志和 profile；失败时输出脱敏后的后端、前端和
  Playwright 日志路径。

网络断言在 tenant 决议前：

- 只允许 `/auth/me`、`/auth/me/tenants` 和 `/auth/switch-tenant`。
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
11. Chromium 与 Edge channel 至少各执行一次关键深链接流程；Edge 是用户复现浏览器，
    线上发布验收不得用 Chromium 结果替代。

固定命令：

```bash
npm ci
npm --prefix frontend ci
BUILD_SHA="$(git rev-parse HEAD)"
VITE_BUILD_SHA="$BUILD_SHA" npm --prefix frontend run build
npm exec -- playwright install chromium msedge
test -f frontend/dist/index.html
test -f tests/e2e/builder-tenant-url-public-uuid-fixture.sh
test -f tests/e2e/builder-tenant-url-public-uuid.spec.mjs
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" \
BROWSER_CHANNEL=chromium \
bash tests/e2e/builder-tenant-url-public-uuid-fixture.sh
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}" \
BROWSER_CHANNEL=msedge \
bash tests/e2e/builder-tenant-url-public-uuid-fixture.sh
```

fixture 即使被单独调用，也必须检查根和 frontend 依赖、重新构建 frontend 并校验 dist，
不能依赖调用者恰好先执行了 build。根安装与 frontend 安装分别固定为：

```bash
npm ci
npm --prefix frontend ci
```

若浏览器 executable 缺失，先执行上述 Playwright install；下载仍失败时发布阻塞，并
保留失败命令和日志。fixture 缺依赖、端口、账号、session 或服务启动步骤时不得直接
执行 `.mjs` 冒充自包含验收。

### 16.4 现有发布入口与线上 smoke

实现交付共享 helper `scripts/verify_builder_tenant_url_smoke.sh`，但它不是平行发布入口。
`scripts/deploy_online_latest_kubesphere.sh` 在交互式发布时调用它；GitLab CI 中
`release_and_update_server` 只负责 kubectl rollout，新增
`release_builder_browser_smoke` 以 `needs: [release_and_update_server]` 调用 helper，
只有 browser-smoke 成功才把整条 release pipeline 视为完成。

CI 构建链固定增加：

```text
CI_COMMIT_SHA
  -> buildctl build-arg VITE_BUILD_SHA
  -> deploy/docker/Dockerfile ARG/ENV
  -> frontend/index.html builder-build-sha meta
buildctl --metadata-file
  -> containerimage.digest
  -> BUILDER_IMAGE=<repository>@sha256:<digest>
  -> StatefulSet backend + copy-frontend-dist
```

`release_builder_browser_smoke` 使用包含 Node 20 与 Playwright `1.61.1` 的固定浏览器镜像，
安装或携带固定 `kubectl 1.30.7`，执行根 `npm ci` 和
`npm exec -- playwright install msedge`。kubectl-only 的 release job 不承担浏览器
安装。浏览器 job 缺 Edge、Node、根 Playwright 依赖或 kubectl 时失败关闭。

共享 helper 的固定输入是 `BUILDER_ORIGIN`、`DEPLOYED_REVISION`、`BUILDER_IMAGE`、
`KUBE_NAMESPACE`、`KUBE_LABEL_SELECTOR`、`KUBE_BACKEND_CONTAINER`、
`KUBE_DIST_INIT_CONTAINER`、`KUBE_WEB_CONTAINER`、`BUILDER_SMOKE_USERNAME`、
`BUILDER_SMOKE_PASSWORD`、
`BUILDER_SMOKE_TENANT_NAME`、`BUILDER_SMOKE_CODE_SESSION_ID` 和可选
`BUILDER_SMOKE_AGENT_ID`。密码只进入 stdin/header，不写 stdout、stderr、参数列表或
临时文件。

helper 必须：

1. 解析公网 `/ai-builder/` 唯一 `builder-build-sha` meta，断言等于 40 位小写
   `DEPLOYED_REVISION`，并执行
   `git merge-base --is-ancestor 49a4bef4 "$DEPLOYED_REVISION"`。
2. 枚举 selector 命中的全部 Pod，数量大于零；逐个断言 Ready、StatefulSet rollout
   revision 一致、backend 与 dist initContainer 的 image 等于 digest 形式的
   `BUILDER_IMAGE`。读取
   `status.containerStatuses[backend].imageID` 和
   `status.initContainerStatuses[copy-frontend-dist].imageID`，归一化后必须非空、互相
   相等、等于 BuildKit 输出 digest，且所有 Pod 一致。
3. 在一个 Ready 新 Pod 内执行
   `python -m app.tenant_public_id reconcile --verify-only-after-write`，输出仅含扫描数、
   补齐数、空值数和冲突数字 ID；断言空值和冲突均为零。
4. 使用受控账号调用现有登录接口；若返回多租户选择，从 `tenants[]` 按
   `BUILDER_SMOKE_TENANT_NAME` 映射数字 ID，调用现有 `/auth/select-tenant`。随后
   `/auth/me` 必须返回合法 `tenant_public_id`，`/auth/me/tenants` 每项 UUID 非空。
5. 从另一个可访问租户调用现有 `/auth/switch-tenant`，使用候选 token 显式调用
   `/auth/me`，断言目标 UUID 后再进行浏览器 smoke；不得把候选 token 写入日志。
6. 对每个 Pod 使用
   `kubectl exec -c "$KUBE_WEB_CONTAINER" -- wget -qO- http://127.0.0.1/ai-builder/`
   读取该 Pod web sidecar 实际提供的 HTML；唯一 `builder-build-sha` 必须等于
   `DEPLOYED_REVISION`。公网 Ingress meta 检查只作为补充，不替代逐 Pod 检查。
7. 用 Edge channel 打开
   `/ai-builder/code/<session>?tenantId=<uuid>&agent=<agent>`，断言 URL 保留 tenantId、
   首次 activate 只调用 `/api/code/sessions/.../activate`、不调用
   `/api/code-runtime/.../activate`，且无 `Code runtime token required` 或 401。
8. 采样本次 rollout 后端日志，断言不包含测试密码、Authorization、JWT 或 Cookie。

任何输入缺失、Pod/image/revision 不一致、reconciliation 非零、登录/切换失败、Edge
不可用或 Code 深链接断言失败都返回非零，并使现有发布 job 失败。

## 17. 验收标准

- 所有有租户上下文的受保护页面在稳定状态下都包含合法 `tenantId` UUID。
- URL UUID 与 `/auth/me.tenant_public_id` 始终一致后才加载业务页面。
- 已授权跨租户深链接自动切换并恢复原路径、query 和 hash。
- 无权或非法 UUID 失败关闭，且不会泄漏租户存在性。
- 旧链接保持可用并自动规范化。
- 侧边栏切租户不会携带旧租户资源 ID。
- UUID expand/reconcile 可重入、并发一致；滚动旧 writer 产生的 NULL 在放行前归零，
  回滚不改变已生成 UUID。
- 停用租户不能切入，携带停用租户的存量 token 不能继续访问。
- 两个标签页不会因不同显式 URL 持续互相切租户。
- switch endpoint 保持现有 `Token` 契约；候选 token 的 `/auth/me` 验证通过前不覆盖
  浏览器源 token 或 user。`current_app` 不作为本验收的租户权威。
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
- `frontend/src/api/auth.ts` 增加 `getMeWithToken(candidateToken)`；owner symbol 固定为
  `authApi.getMeWithToken`，只调用现有 `/auth/me`。
- `frontend/src/utils/request.ts` 的 request interceptor 只在调用方未显式提供
  Authorization 时注入 `localStorage.token`。
- `frontend/src/components/v2/RailSidebar.vue` 的租户菜单。
- `frontend/src/stores/mode.ts` 的 Builder/Code 首页，不新增 admin mode。
- `frontend/src/router/index.ts` 新增 route meta 分类和 resolver；测试 owner 为
  `frontend/src/router/tenantUrlGuard.spec.ts`。
- 登录与 `frontend/src/views/TenantSelect.vue` 继续提交现有
  `selection_token + tenant_id`，`tenant_public_id` 只用于客户端映射，不进入 request。
- `backend/app/database.py` 的 `init_db()`，但租户 UUID 使用独立严格 helper，禁止走
  `_execute_best_effort()`。
- `backend/app/models/tenant.py` 的 `Tenant.public_id` 与统一 UUID helper；所有现有
  Tenant writer 通过 ORM default 获得 UUID v4，reconciliation 对 NULL 使用 UUID v5。
- `backend/app/schemas.py`、`backend/app/routes/auth/login.py`、
  `backend/app/routes/auth/tenants_admin.py` 只投影 UUID，不改变 `Token` DTO。
- `backend/app/deps.py` 的 header/query-token 两条认证路径都拒绝停用租户 token。
- 现有 UUID public ID 模式和 Code 外层 session API。
- `deploy/docker/Dockerfile`、`.gitlab-ci.yml` 和
  `scripts/deploy_online_latest_kubesphere.sh` 是构建与发布 owner；共享 smoke helper
  只能由这些入口调用。
- 根 `package.json`/`package-lock.json` 是 E2E Playwright 唯一依赖 owner；frontend
  package 只拥有 Vue/Vitest 构建与单元测试依赖。

与 `2026-07-18-builder-fast-auth-multi-sandbox-cache-design.md` 的边界：

- 本 phase 拥有 `tenant_public_id`、路由 metadata、URL resolver、登录 redirect 消费
  和候选 `Token -> /auth/me -> commit` 适配器。
- 7 月 18 日设计拥有 Auth Bootstrap、`tenant_epoch` 的最终语义、无 reload 切换、
  请求取消、tenant-scoped cache 和 `current_app` fleet 一致性。
- 当前 adapter 的整页 reload 是兼容实现，不在 URL resolver 中复制 cache 清理逻辑；
  后续替换 adapter 时 URL、API UUID 和路由测试不变。

除非代码证据表明现有边界无法承载，不新建第二套路由器、租户状态管理器、token
存储或数据库迁移框架。
