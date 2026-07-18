# Builder 快速认证与多沙箱切换缓存设计

**Spec ID**：`2026-07-18-builder-fast-auth-multi-sandbox-cache`
**日期**：2026-07-18
**状态**：已确认，待实施计划
**主仓库**：`apaas-builder-ai`
**协同仓库**：`control-plane`、`agent-runtime`、`platform-integration`

## 1. 背景与现状证据

Builder 当前把页面身份恢复、应用加载、左栏历史聚合、沙箱打开和运行时凭据轮换
放在同一条用户等待链路中。2026-07-18 本地 Chromium 实测：

| 阶段 | 当前耗时 |
| --- | ---: |
| `/auth/me` 与 `/apaas/status` | 约 0.8 秒 |
| 第一次 `/code/applications` | 约 9.3 秒 |
| 第二次重复 `/code/applications` | 约 17.3 秒 |
| 应用行可见 | 约 17.6 秒 |
| `/code/rail/history` | 约 14.6 秒 |
| 热沙箱 `/open` API | 约 3.2 秒 |
| iframe 初步可用 | 约 5.8 秒 |

主要瓶颈不是 JWT 验签，而是：

1. 应用页和全局左栏分别请求相同应用列表，重复穿透 Builder 和 Control Plane。
2. `/code/rail/history` 在请求内逐个访问历史 Runtime 的
   `/api/agent/sessions`，旧沙箱连续返回 401，延迟随历史沙箱数量线性增长。
3. 切租户先调用 `/auth/switch-tenant`，再 `/auth/me`，随后整页 reload；新页面路由
   又调用 `/auth/me`，并重新加载全部租户数据。
4. 已 ready 的 workspace 每次打开仍调用 `workspace/open`。
5. Control Plane 对 ready workspace 执行 launch token rotation。Helm 路径会更新
   Kubernetes Secret，并等待 Runtime 接受新 token；Projected Secret 延迟可能达到
   数十秒。
6. 页面认证、浏览器会话续期和 Kubernetes 基础设施凭据轮换没有解耦。

## 2. 与既有设计的关系

本设计继承
`2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md` 的以下原则：

- entry credential 不进入浏览器状态和数据库明文字段。
- 每个浏览器拥有独立 Runtime session。
- Runtime session 超时后无感续期。
- 同账号多浏览器并发不能互相覆盖凭据。
- 账号失效、租户解绑和明确撤销必须失败关闭。

本设计替代该文档中以下性能关键路径：

- 不再把普通打开或 Runtime Cookie 续期实现为
  `workspace/open -> rotate launch token -> bootstrap`。
- 不再在每次 ready workspace open 时修改 Kubernetes Secret。
- 不再让左栏历史同步探测所有 Runtime。

## 3. 已确认决策

1. 性能优先。
2. 普通打开、沙箱切换和浏览器会话续期不修改 Kubernetes Secret。
3. Kubernetes Secret 保留为沙箱长期服务身份和应急吊销边界。
4. 浏览器使用 Control Plane 短期 Launch Ticket 换取 Runtime Cookie。
5. 支持同时缓存多个沙箱，不限定为“当前和上一个”。
6. 增加 `normal` 和 `performance` 两种缓存模式。
7. 两种模式只改变缓存数量，认证协议、TTL、失败恢复和安全语义保持一致。
8. Control Plane 负责解析平台默认值和租户覆盖值，Builder 不成为配置事实源。

## 4. 目标与非目标

### 4.1 目标

- 页面身份壳 P95 在 500 毫秒内可用。
- 应用首批数据 P95 在 1.5 秒内可用。
- 浏览器热帧切换 P95 在 200 毫秒内完成。
- 服务端热沙箱重新挂载 P95 在 1.5 秒内完成。
- 暂停沙箱恢复 P95 在 8 秒内完成。
- 可恢复认证失效不向用户展示 401、空白 iframe 或重新登录闪烁。
- 延迟不随历史沙箱数量线性增长。
- 切租户后不显示前一租户的应用、会话、iframe 或缓存数据。

### 4.2 非目标

- 不取消登录鉴权和租户隔离。
- 不让浏览器直接持有 Runtime service secret。
- 不通过延长永久 token 规避续期。
- 不在本阶段引入 Service Mesh 或 mTLS 全面改造。
- 不为普通和性能模式维护两套认证实现。
- 不保证暂停或首次创建沙箱像浏览器热帧一样瞬时可用。

## 5. 总体架构

```text
Browser
  ├─ Auth Bootstrap Store
  ├─ Tenant Epoch Cache
  └─ Sandbox Frame Cache (LRU)
         |
         v
Builder BFF
  ├─ Auth bootstrap / tenant switch
  ├─ Shared application query cache
  ├─ DB-only rail history
  ├─ Browser Runtime Session store
  └─ Sandbox open singleflight
         |
         v
Control Plane
  ├─ Tenant/config authority
  ├─ Workspace lifecycle
  ├─ Launch Ticket signer
  └─ Warm sandbox LRU policy
         |
         v
Agent Runtime
  ├─ Stable sandbox service identity
  ├─ Offline Launch Ticket validation
  ├─ Browser Runtime Cookie
  └─ Session/activity endpoints
```

核心分离：

- **Workspace lifecycle**：创建、恢复、暂停和销毁沙箱。
- **Sandbox service identity**：Control Plane 与 Runtime 的长期服务身份。
- **Launch Ticket**：用户或浏览器本次进入沙箱的短期授权。
- **Browser Runtime Session**：浏览器在 Runtime 的滑动会话。
- **Frame cache**：浏览器端已加载工作台的展示缓存。

## 6. Secret 与 Launch Ticket

### 6.1 稳定 Secret

每个沙箱保留现有 Kubernetes Secret，但用途调整为：

- Runtime 内部服务身份。
- Control Plane 内部管理调用。
- 沙箱创建、恢复后的身份初始化。
- 主动吊销、安全事件和后台周期轮换。

以下动作不得修改 Kubernetes Secret：

- 打开已 ready 的沙箱。
- 在多个 ready 沙箱之间切换。
- Browser Runtime Cookie 续期。
- 页面刷新。
- iframe 重建。
- 同账号在另一个浏览器打开同一沙箱。

Secret 后台轮换与用户请求解耦。轮换使用新旧 generation 短时重叠，完成后再撤销旧
generation。轮换失败记录告警，但不得阻塞仍持有有效浏览器会话的用户。

### 6.2 Launch Ticket

Control Plane 增加短期签名 Launch Ticket：

```json
{
  "iss": "orcamatrix-control-plane",
  "aud": "agent-runtime-launch",
  "tenant_id": "tenant-id",
  "user_id": "user-id",
  "application_id": "application-id",
  "workspace_id": "workspace-id",
  "sandbox_instance_id": "sandbox-instance-id",
  "browser_session_id": "random-id",
  "jti": "one-time-id",
  "iat": 0,
  "exp": 0
}
```

约束：

- 默认 TTL 60 秒。
- 必须绑定 tenant、user、workspace、sandbox 和 browser session。
- Control Plane 使用独立签名私钥。
- Agent Runtime 使用公钥或 JWKS 本地验签，不为每次验签回调 Control Plane。
- Runtime 在 Ticket TTL 内记录已消费 `jti`，阻止重复交换。
- 单 Pod Runtime 使用本地 TTL 集合；未来同一沙箱多副本时切换到共享存储。
- Ticket 只在 Builder 服务端调用栈中使用，不进入 iframe URL、localStorage 或日志。

### 6.3 Ticket 交换

Builder 服务端调用 Runtime：

```http
POST /internal/browser-sessions/exchange
Authorization: LaunchTicket <ticket>
```

Runtime 返回新的 HttpOnly Runtime Cookie。Builder 加密保存到既有
`CodeRuntimeBrowserSession`，并通过自己的同源代理注入上游请求。

Ticket 交换不访问 Kubernetes API，也不触发 Pod rollout。

### 6.4 撤销传播与授权租约

快速路径不在每次切换时同步调用 Control Plane，但不能因此延迟明确撤销：

- Builder 为 `(user_id, tenant_id)` 保存最长 60 秒的授权租约，只记录版本和过期时间，
  不保存新的长期凭据。
- Control Plane 在账号禁用、tenant membership 撤销、workspace 撤销和 sandbox
  撤销时发布失效事件。
- Builder 收到事件后立即递增本地授权 generation，清除对应 Browser Runtime
  Session，并使旧 embed token 失效。
- Runtime Cookie 即使尚未自然过期，也必须经过 Builder 同源代理的授权 generation
  检查；旧 generation 不得继续访问。
- Launch Ticket 签发始终执行最新用户、tenant、workspace 和 sandbox 校验。
- 失效事件暂时不可达时，授权租约最多继续 60 秒；租约到期后必须重新校验，不能
  无限离线放行。

因此，普通热切换无需 Control Plane 往返，而明确撤销仍在 60 秒硬上限内生效；事件
链路正常时立即生效。

## 7. 快速打开数据流

### 7.1 浏览器热帧

1. 用户点击已缓存在浏览器的沙箱。
2. Frame Cache 立即把目标 iframe 设为 active，把当前 iframe 设为 hidden。
3. 目标 iframe 恢复交互和事件流。
4. Builder 在后台检查 Browser Runtime Session 剩余 TTL。
5. 需要续期时走 Launch Ticket singleflight，不阻塞已可用界面。

目标：P95 小于 200 毫秒。

### 7.2 服务端热沙箱

1. 目标 iframe 不在浏览器缓存，但 workspace 和 sandbox 为 ready。
2. Builder 查询现有 binding。
3. 若当前浏览器 Runtime Cookie 仍有效，直接返回 embed URL。
4. 若 Cookie 缺失或临近过期，Builder 请求 Launch Ticket 并交换 Cookie。
5. 浏览器加载 iframe；静态资源使用浏览器 HTTP cache。

该路径不调用 workspace provision，不旋转 Secret。

目标：P95 小于 1.5 秒。

### 7.3 暂停或首次创建沙箱

1. Builder 调用 Control Plane workspace lifecycle API。
2. Control Plane 返回 `starting` 或 `resuming` 状态和 task ID。
3. 旧工作台继续显示，目标区域不出现空白页。
4. Builder 通过任务事件等待 ready。
5. ready 后签发 Launch Ticket、交换 Cookie并原子切换 iframe。

目标：暂停恢复 P95 小于 8 秒。首次创建按基础设施实际耗时单独计量。

## 8. Browser Runtime Session 快速路径

Builder 复用现有：

- `CodeRuntimeBinding`
- `CodeRuntimeBrowserSession`
- `browser_session_id`
- `runtime_session_cookie_enc`
- `runtime_session_expires_at`
- `auth_generation`

`/code/sessions/{session}/open` 的决策顺序：

1. 校验 Builder 登录态、tenant 和 shell session。
2. binding ready 且 Browser Runtime Session 剩余 TTL 大于安全窗口：
   - 直接生成 embed token。
   - 不调用 Control Plane。
3. binding ready 但浏览器会话需要续期：
   - 调用 Launch Ticket API。
   - 服务端交换 Runtime Cookie。
   - 更新 Browser Session generation。
4. binding 不存在、sandbox 非 ready 或明确不可达：
   - 进入 workspace lifecycle。

同一 `(binding_id, browser_session_id)` 的续期使用 singleflight。并发请求等待第一
个续期结果，不能重复签票或覆盖 Cookie。

## 9. 认证首屏与租户切换

### 9.1 Auth Bootstrap

新增聚合接口：

```http
GET /api/auth/bootstrap
```

返回：

- 当前用户展示信息。
- Control Plane 权威侧解析的当前 tenant。
- Control Plane 权威侧可切换 tenant 列表；Builder 本地数据只保存映射。
- 解析后的沙箱缓存 profile。
- Builder 功能开关。
- `tenant_epoch`。

路由守卫只等待该接口。`/apaas/status` 改为页面后台加载，不能阻塞进入应用列表。

### 9.2 租户切换

`POST /api/auth/switch-tenant` 返回：

- 新 access token。
- 新 tenant 下的 user snapshot。
- 新 `tenant_epoch`。
- 新 tenant 的沙箱缓存 profile。

前端不再整页 reload：

1. 取消旧 tenant 的在途请求。
2. 原子替换 token、user、tenant 和 profile。
3. 清空或隔离旧 tenant store。
4. 关闭旧 tenant 的浏览器热帧。
5. 跳转到新 tenant 的 `/code/apps`。
6. 并行加载新 tenant 的应用和数据库历史。

所有缓存 key 必须包含 `tenant_id + tenant_epoch`。旧响应即使晚到也不得写入新 tenant
store。

## 10. 应用列表与左栏历史

### 10.1 应用列表单一来源

应用页和 Rail Sidebar 共享一个 tenant-scoped application store：

- 同一 tenant 同一时刻只有一个在途请求。
- 页面列表和左栏 badge 读取同一结果。
- 支持短 TTL stale-while-revalidate。
- Control Plane 支持 ETag 或短 TTL 查询缓存。

禁止页面和左栏分别穿透 Control Plane。

### 10.2 DB-only Rail History

`/code/rail/history` 的首屏响应只读取 Builder 数据库：

- shell session。
- application snapshot。
- 已记录的 runtime session snapshot。
- current runtime session ID。
- 最后活动时间和可恢复状态。

首屏请求不得调用任何 Runtime。

用户展开某个应用或点击某个历史会话时，才懒加载该沙箱的最新会话：

- 单沙箱请求。
- 500 毫秒目标超时。
- 401、404 和不可达结果写入短期 negative cache。
- 失败只影响该应用，不影响其他历史和页面首屏。

Runtime 会话创建、激活、删除和状态事件成功后，Builder 增量更新数据库 snapshot，
避免依赖全量反查。

## 11. 普通模式与性能模式

### 11.1 配置模型

Control Plane 保存平台默认值和 tenant override，Builder 只消费解析结果：

```yaml
codeSandbox:
  cacheProfile: normal
  profiles:
    normal:
      browserHotFrames: 2
      serverWarmSandboxesPerUser: 4
    performance:
      browserHotFrames: 5
      serverWarmSandboxesPerUser: 10
```

默认值：

| 模式 | 浏览器热 iframe，含当前 | 服务端热沙箱/用户 |
| --- | ---: | ---: |
| `normal` | 2 | 4 |
| `performance` | 5 | 10 |

两种模式仅改变以上数量。Ticket TTL、Cookie TTL、Secret 轮换、失败恢复和租户隔离
完全一致。

### 11.2 配置优先级

```text
tenant override
  > platform default
  > built-in normal defaults
```

环境变量只用于部署初始默认值，不能覆盖已存在的 tenant 配置且不产生第三套事实源。

### 11.3 Browser Frame Cache

缓存 key：

```text
tenant_id + browser_session_id + shell_session_id
```

状态：

- `active`：当前可见、可交互。
- `hot_hidden`：DOM 保留，不可见，暂停高成本流。
- `evicted`：iframe 已卸载，服务端沙箱可继续 warm。

规则：

- active iframe 不参与淘汰。
- 其余按最后切换时间 LRU 淘汰。
- `hot_hidden` 暂停 timeline、observability、history 等高成本轮询。
- 再次 active 时恢复事件流，不重建整个应用。
- 从 performance 切到 normal 时立即淘汰超额 hidden iframe。
- 从 normal 切到 performance 时不批量启动沙箱，按后续访问逐步预热。

### 11.4 Server Warm Sandbox Cache

缓存 key：

```text
tenant_id + user_id + workspace_id
```

规则：

- ready 且最近使用的沙箱进入用户 warm LRU。
- 超过 profile 数量后，异步暂停最旧沙箱。
- 暂停动作不阻塞当前目标沙箱切换。
- 暂停不删除 workspace、会话或用户文件。
- tenant 另有总量硬上限；达到硬上限时按租户 LRU 提前暂停。
- 用户有前台活动、运行中 Agent turn、未完成工具调用或文件写入时不得暂停。

## 12. 失败恢复

| 场景 | 行为 |
| --- | --- |
| Browser Cookie 临近过期 | 后台 singleflight 签票续期 |
| Runtime 返回明确 session expired | 签票并重放一次 |
| Launch Ticket 过期 | 重新签发一次 |
| Ticket 重放或签名无效 | 失败关闭，记录安全审计 |
| Control Plane 暂时不可用 | 有效 Browser Session 继续使用；新签票暂缓 |
| Runtime 暂时不可达 | 保留旧 iframe，目标显示切换中并有限重试 |
| 沙箱已暂停 | 进入异步 resume，不旋转普通打开 Secret |
| tenant 已切换 | 旧 tenant iframe 立即失活并移除 |
| 用户、租户或绑定已撤销 | 失效事件递增 generation，清除 Browser Session；事件异常时最迟在 60 秒授权租约到期后失败关闭 |
| Secret 主动轮换 | 新旧 generation 重叠，后台迁移，不阻塞有效会话 |

所有自动恢复最多重试一次业务动作。不得用无限 401 重放掩盖真实撤销。

## 13. 可观测性

增加分阶段指标和 trace：

- `auth.bootstrap.duration`
- `tenant.switch.duration`
- `applications.shared_load.duration`
- `rail.history.db.duration`
- `sandbox.open.fast_path.duration`
- `sandbox.ticket.issue.duration`
- `sandbox.ticket.exchange.duration`
- `sandbox.frame.activate.duration`
- `sandbox.resume.duration`
- `sandbox.secret.rotate.duration`

关键维度只允许：

- profile：`normal | performance`
- path：`browser_hot | server_warm | resume | create`
- result：`success | recoverable | hard_failure`

禁止把 token、ticket、Cookie、workspace URL、user ID 或高基数 session ID 放入指标标签。

仪表盘必须分别展示：

- 页面身份壳。
- 应用数据。
- 左栏历史。
- 热帧切换。
- 服务端热沙箱。
- 暂停恢复。
- Secret 后台轮换。

## 14. 分阶段实施

### Phase 1：去除首屏放大器

- 应用列表共享 store 和请求去重。
- Rail History 改为 DB-only。
- 移除首屏 Runtime fan-out。
- 增加分阶段耗时指标。

该阶段不改凭据模型，风险最低，预期可把应用首屏从十几秒降到 1–2 秒。

### Phase 2：认证 Bootstrap 与无 reload 切租户

- 聚合 `/auth/bootstrap`。
- `/apaas/status` 后台化。
- switch-tenant 返回 user snapshot、profile 和 tenant epoch。
- tenant-scoped cache 原子切换。

### Phase 3：Launch Ticket 快速续期

- Control Plane Ticket signer。
- Agent Runtime 本地验签和一次性消费。
- Builder Browser Session 快速路径。
- ready workspace open 不再旋转 Kubernetes Secret。
- Secret 改为后台生命周期管理。

### Phase 4：多沙箱缓存

- Browser Frame Cache。
- Server Warm Sandbox LRU。
- normal/performance 配置和租户覆盖。
- 运行中任务保护和异步暂停。

### Phase 5：灰度与收口

- normal 小流量灰度。
- performance 指定租户灰度。
- 对比 SLO、内存、Pod 数和失败率。
- 移除旧的 per-open token rotation 调用路径。

## 15. 分级验证

### L0：静态和契约

- 配置解析。
- Ticket claims、签名和过期。
- tenant epoch cache key。
- LRU 淘汰。
- 日志脱敏。

### L1：API

- Auth bootstrap 单请求。
- 应用列表 singleflight。
- DB-only rail history 不调用 Runtime。
- ready binding fast open 不调用 workspace lifecycle。
- Ticket replay 被拒绝。

### L2：真实 Chromium

- normal 模式依次切换超过 2 个沙箱。
- performance 模式依次切换超过 5 个沙箱。
- 热帧、服务端热沙箱和暂停恢复三条路径。
- 切租户后无旧 tenant 数据和 iframe。
- Browser Cookie 超时后用户无可见错误。

### L3：并发与故障

- 同账号 Chromium 与 Firefox 并发。
- 多标签页同时续期 singleflight。
- Control Plane 临时不可用。
- Runtime 重启。
- Secret 后台轮换。
- 性能模式达到用户和 tenant 上限后的 LRU 行为。

验证按 L0 到 L3 逐级执行，失败即停，不等待全部完成后一次性反馈。

## 16. 验收标准

1. 普通打开和切换日志中没有 Kubernetes Secret write 或 rollout。
2. ready Browser Session fast path 不调用 Control Plane workspace lifecycle。
3. 应用页和左栏合计只产生一次应用列表上游请求。
4. Rail History 首屏对 Runtime 的请求数为 0。
5. 切租户不发生整页 reload，不重复 `/auth/me`。
6. normal 和 performance 只在缓存数量上存在行为差异。
7. normal 超过 2 个浏览器 frame、4 个服务端 warm sandbox 后正确 LRU。
8. performance 超过 5 个浏览器 frame、10 个服务端 warm sandbox 后正确 LRU。
9. Browser Cookie 超时、Ticket 超时和 access token 刷新成功时无用户可见认证错误。
10. 用户、租户或绑定撤销在事件正常时立即失败关闭，事件异常时不超过 60 秒。
11. 热帧切换 P95 小于 200 毫秒。
12. 服务端热沙箱重新挂载 P95 小于 1.5 秒。
13. 应用首批数据 P95 小于 1.5 秒。
14. 暂停沙箱恢复 P95 小于 8 秒。

## 17. 实施边界

本设计确认后，实施计划必须分别列出：

- `apaas-builder-ai`：bootstrap、tenant epoch、共享 store、DB-only history、
  Browser Session fast path、Frame Cache。
- `control-plane`：配置权威、Launch Ticket、workspace lifecycle 与 warm LRU、
  移除 per-open rotation。
- `agent-runtime`：Ticket 验签、一次性消费、Browser Cookie exchange、后台 Secret
  generation 兼容。
- `platform-integration`：normal/performance 默认配置、部署模板、灰度开关和可观测性。

不得把 Phase 1 的前端去重伪装成整个方案已完成，也不得在 Phase 3 未完成前宣称
Secret 已从普通切换关键路径移除。
