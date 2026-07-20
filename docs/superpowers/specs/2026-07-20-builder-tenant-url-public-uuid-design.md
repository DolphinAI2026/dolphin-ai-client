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
5. URL 指向账号有权访问的其他租户时，自动切换 token 和当前用户上下文，再整页
   `replace` 到原始深链接。
6. URL 指向无权访问、未知或格式非法的 UUID 时，不尝试猜测租户，也不发出目标页面
   的业务请求；回到当前模式首页并显示稳定错误提示。
7. 侧边栏主动切租户时，不保留旧租户的资源路径；进入目标模式首页，避免把旧租户的
   session、project 或 application ID 带入新租户。
8. Code URL 的规范形态为：

   ```text
   /ai-builder/code/<session-public-id>?tenantId=<tenant-public-uuid>&agent=<runtime-session-id>
   ```

   查询参数顺序不作为契约，`tenantId` 和 `agent` 均须保留。

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

当前工程采用启动时 best-effort DDL，不依赖 Alembic。为了支持多实例并发启动，历史
租户的回填不得为同一行各自生成随机 UUID。迁移分三步：

1. 添加允许为空的 `public_id` 列。
2. 对历史租户使用固定 namespace 的 UUID v5：

   ```text
   uuid5(BUILDER_TENANT_PUBLIC_ID_NAMESPACE, "tenant:<numeric-id>")
   ```

   同一租户在任意实例上得到同一值，重试幂等。
3. 在空值为零后创建唯一索引；支持的数据库若不能在线增加 `NOT NULL`，则由启动
   doctor 和模型校验共同保证非空，后续数据库专项迁移再收紧物理约束。

启动迁移必须记录：

- `tenant_public_id_backfill_total`
- `tenant_public_id_backfill_failed`
- 冲突租户的数字 ID，但不得输出用户凭据或 token。

若存在无法回填或唯一索引冲突，应用启动失败关闭，不得在部分租户有 UUID、部分没有
UUID 的状态下继续提供登录和租户切换。

## 6. API 契约

### 6.1 响应字段

以下响应增加必填字符串字段 `tenant_public_id`：

- 登录成功响应中的当前租户信息。
- `UserInfo` / `/auth/me`。
- `TenantOption` / `/auth/me/tenants`。
- 多租户登录选择列表。

字段格式：

```json
{
  "tenant_id": 3,
  "tenant_public_id": "34af86ef-0af1-44bb-ae06-0b7131bc86c9",
  "tenant_name": "admin 的组织"
}
```

`tenant_id` 暂时保留，避免破坏现有客户端和后端内部调用。

### 6.2 切租户请求

本切片保留现有 `POST /auth/switch-tenant` 数字 `tenant_id` 请求契约。前端只能从
`/auth/me/tenants` 返回的可访问列表中，将 URL UUID 映射到数字 ID 后发起切换。

服务端继续执行成员关系和租户状态校验。平台管理员也必须通过现有服务端规则获得目标
租户上下文，前端不得构造未出现在可访问列表中的数字 ID。

切换成功响应必须包含新 token 和新的 `UserInfo.tenant_public_id`。前端在
`tenant_public_id` 与目标 UUID 不一致时视为契约错误，不继续加载目标页面。

### 6.3 错误语义

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

错误回退 URL 必须携带当前有效租户的 `tenantId`，不得继续保留无效目标 UUID。

## 7. 前端 URL 状态机

### 7.1 适用范围

状态机运行于全局路由守卫，覆盖 `meta.requiresAuth` 且当前用户有
`tenant_public_id` 的路由。

不适用：

- 登录页。
- 多租户选择页。
- 无租户上下文的平台管理页面。
- 404 等公共错误页。

### 7.2 执行顺序

守卫必须按以下顺序执行：

1. 恢复本地 token 并调用 `/auth/me`。
2. 获取当前 `tenant_public_id` 和可访问租户列表。
3. 解析目标 URL 的 `tenantId`。
4. 在允许目标页面组件挂载和业务请求前完成规范化、拒绝或切换。
5. 租户一致后再执行权限守卫和目标页面加载。

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

2. 调用 `switchTenant(mappedNumericTenantId)`。
3. 更新 token 和用户上下文，清理租户级缓存、标签页、Code iframe 和运行时状态。
4. 校验响应 UUID 与目标 UUID 一致。
5. 使用 `window.location.replace(targetFullPath)` 整页恢复，不新增历史记录。

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
- 多租户账号：若目标 UUID 存在于登录响应的租户列表，自动选择该租户后回跳。
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
| 管理后台 | `/admin/?tenantId=<target-uuid>` |
| 其他租户业务模式 | 该模式已登记的首页 |

未登记模式回退 `/ai-builder/`。目标模式首页必须在路由配置中集中定义，不能在多个
组件中复制字符串规则。

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

## 11. 缓存与存储清理

租户切换成功后必须清理所有 tenant-scoped 前端状态：

- Pinia 中的应用、项目、会话、权限和租户资源缓存。
- 已打开标签页及其持久化状态。
- Code iframe、runtime session 选择和最近历史。
- 以旧租户为 key 的查询缓存。

不得清理：

- 新签发的登录 token。
- 与租户无关的主题、语言和界面偏好。
- 用于恢复目标 URL 的当前切换标记；它在重载校验完成后删除。

## 12. 并发、失败与恢复

### 12.1 多标签页

每个标签页独立解析 URL。token 更新通过现有共享 storage 可见，但每个标签页仍须
在下一次导航或收到 storage 事件时重新 `/auth/me`，不得假设其他标签页的页面租户
仍有效。

当两个标签页同时请求不同租户时，以最后成功写入的 token 为账号当前共享登录态。
较早标签页在下一次 API 401/403、storage 事件或导航时重新执行 URL 状态机并恢复其
显式目标租户。此切片不承诺两个标签页同时长期停留在不同租户。

### 12.2 网络失败

自动切换不在前端重试 switch POST，避免重复签发和循环。用户可以从错误提示重新
触发导航或主动切换。超时或 5xx 不加载目标页面，也不删除当前有效 token。

### 12.3 部分成功

如果 switch endpoint 已成功但 `/auth/me` 或重载失败，切换标记保留至 30 秒。
恢复时重新读取 token 和 `/auth/me`：

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

前端为每次租户 URL 决策记录结构化事件：

```text
tenant_url_resolution
  outcome=matched|canonicalized|switched|rejected|failed|loop_prevented
  source=initial_load|router_navigation|login_redirect|tenant_menu|storage_event
  current_tenant_public_id
  target_tenant_public_id
  route_name
  request_id
```

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
- `tenant_switch_duration_ms`
- `tenant_public_id_backfill_failed`
- Code 首次深链接 activate 的 401 数量

## 15. 兼容、发布与回滚

### 15.1 滚动发布顺序

1. 发布数据库列、幂等回填和后端响应字段。
2. 确认所有租户均有唯一 `public_id`，`/auth/me` 和租户列表稳定返回 UUID。
3. 发布前端 URL 状态机和导航改造。
4. 发布包含 `49a4bef4` Code 外层会话鉴权修复的静态资源。
5. 执行线上登录、切租户、分享链接和 Code 首开验证。

后端先发布期间旧前端忽略新增字段。前端发布前不得依赖尚未完成回填的 UUID。

### 15.2 回滚

- 前端可回滚到不解释 `tenantId` 的版本，额外 query 对旧路由无副作用。
- 后端可回滚应用代码，但保留 `public_id` 列和数据，不删除、不重新生成。
- 不回滚历史 UUID 值，确保已分享链接在再次发布后仍然有效。
- 若前端故障而后端正常，优先只回滚前端；不得通过清空租户 UUID 恢复。

## 16. 验证策略

### 16.1 后端测试

- 新租户生成合法、唯一、稳定的 UUID v4。
- 历史回填对同一数字 ID 幂等，多个并发执行结果一致。
- 回填失败或唯一冲突导致启动失败关闭。
- `/auth/me`、登录响应和租户列表包含 `tenant_public_id`。
- switch 成功响应 UUID 与目标租户一致。
- 无成员关系、停用租户和未知租户仍被拒绝。
- 旧客户端只发送数字 `tenant_id` 仍可工作。

### 16.2 前端单元测试

- 缺少 UUID 时规范化且保留其他 query/hash。
- 当前 UUID 匹配时不切换。
- 可访问的其他 UUID 只调用一次 switch，并恢复同一 fullPath。
- 非法、未知和无权 UUID 不挂载目标页面。
- 401、403、404、5xx、超时和响应 UUID 不匹配按表格回退。
- 切换标记过期、一次重试和并发导航不会形成循环。
- 登录和多租户选择保留并消费目标 UUID。
- 侧边栏切换进入目标模式首页，不携带旧资源 ID。
- Code 的 `agent` 更新保留 `tenantId`。

### 16.3 浏览器 E2E

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
9. Chromium 与 Edge 至少各执行一次关键深链接流程。

## 17. 验收标准

- 所有有租户上下文的受保护页面在稳定状态下都包含合法 `tenantId` UUID。
- URL UUID 与 `/auth/me.tenant_public_id` 始终一致后才加载业务页面。
- 已授权跨租户深链接自动切换并恢复原路径、query 和 hash。
- 无权或非法 UUID 失败关闭，且不会泄漏租户存在性。
- 旧链接保持可用并自动规范化。
- 侧边栏切租户不会携带旧租户资源 ID。
- UUID 回填可重入、并发一致，回滚不改变已生成 UUID。
- Code 首次分享链接不再需要无 `agent` 预热，且 activate 不返回
  `Code runtime token required`。
- 后端、前端和浏览器测试均通过，线上静态资源可证明包含 `49a4bef4` 对应修复。

## 18. 实施边界

实施计划应优先复用：

- `frontend/src/router/index.ts` 的全局守卫。
- `frontend/src/stores/user.ts` 的 `switchTenant` 和用户恢复流程。
- `frontend/src/components/v2/RailSidebar.vue` 的租户菜单。
- 登录和多租户选择现有 `redirect` 契约。
- `backend/app/database.py` 的启动 DDL 机制。
- 现有 UUID public ID 模式和 Code 外层 session API。

除非代码证据表明现有边界无法承载，不新建第二套路由器、租户状态管理器、token
存储或数据库迁移框架。
