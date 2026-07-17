# Builder 沙箱 Token-Free 与无感续期设计

**Spec ID**: 2026-07-17-builder-sandbox-token-free-transparent-renewal

**Spec ID**：`2026-07-17-builder-sandbox-token-free-transparent-renewal`
**日期**：2026-07-17
**状态**：已确认，待实施计划
**主仓库**：`apaas-builder-ai`
**协同仓库**：`control-plane`、`agent-runtime`

## 1. 背景

当前 Builder Code 沙箱入口同时存在：

- Control Plane 返回的 Runtime entry token。
- iframe URL 中的 `token`。
- Builder 短期 `dolphin_token`。
- Builder 代理 Cookie `dolphin_code_runtime_*`。
- Agent Runtime Cookie `apaas_sandbox_token`。

现有 `CodeRuntimeBinding.builder_url` 会保存 Control Plane 返回的完整 URL，因此 entry token 会进入数据库。浏览器首次打开 iframe 后，再通过 URL token 换取 Runtime Cookie。服务端会话列表、新建会话、激活会话等请求也会从 `builder_url` 重新提取 entry token。

现有代码只对部分服务端 JSON 请求执行一次 401 reopen。iframe、静态资源和 SSE 代理会直接把 Runtime 401 返回浏览器，无法保证超时后无感续期。

## 2. 已确认目标

本阶段采用 Builder 网关透明续期方案：

1. entry token 不进入数据库。
2. entry token 不进入浏览器 URL、localStorage、sessionStorage、Cookie、控制台和前端状态。
3. Control Plane 只负责 workspace、租户权限和 token broker，不代理业务数据。
4. 每个浏览器拥有独立的 Runtime session，不能因同一统一账号而共享浏览器凭据。
5. Runtime session、launch token 和 Control Plane 短期 token 超时后自动续期。
6. 用户不看到可恢复的 401、iframe 错误、SSE 断线或重新登录提示。
7. 统一账号 refresh 失效、账号禁用、权限撤销或租户解绑时失败关闭，允许要求重新登录或展示无权限状态。
8. 暂时保留 `dolphin_code_runtime_*` 与 `apaas_sandbox_token` 两层 HttpOnly Cookie；单 Cookie 收敛属于后续阶段。
9. 使用真实 Chromium 和 Firefox 验证同一账号跨浏览器并发及超时恢复。
10. 验证必须分级、失败即停、逐级反馈，不能等待全部测试完成后一次性报告。

## 3. 非目标

- 本阶段不把两个沙箱 Cookie 收敛为单个 `sandbox_session`。
- 不让 Control Plane 成为 Runtime 业务 API 数据代理。
- 不通过保存用户密码实现统一账号硬过期后的静默登录。
- 不修改旧 Coding Terminal 的 WebSocket + query token 链路；该链路单独治理。
- 不用延长到近似永久有效的 Runtime session 代替续期机制。
- 不在鉴权来源不明确时重放业务请求。
- 不在本切片解决“一次性 refresh 已在远端轮换、Builder 保存新 token 时数据库
  故障”的跨系统提交问题；该问题进入路线图 `P5-A`。

## 4. 身份和租户边界

统一账号和租户事实继续遵循既有联邦认证设计：

- 有平台模式以 Control Plane 用户和平台租户为权威。
- 平台租户可以绑定一个 aPaaS 租户。
- Builder 只保存必要的本地资源映射，不成为平台租户事实源。
- workspace renew 时，Control Plane 必须重新校验用户状态、平台租户成员关系、aPaaS 租户绑定、应用和 workspace 归属。

沙箱续期不能只凭 Builder 数据库里的 `user_id` 或 `tenant_id` 成功。Control Plane 是续期授权决策点。

## 5. 复用优先的凭据模型

### 5.1 Builder 浏览器代理会话

`dolphin_code_runtime_*` 继续作为 Builder 代理入口 Cookie，并增加随机
`browser_session_id`：

- 每次 `/open` 生成新的随机 ID。
- ID 进入签名后的 embed token 和代理 Cookie 声明。
- ID 不是认证 secret，只用于数据库关联和 singleflight key。
- Chromium、Firefox 和其他独立浏览器必须获得不同 ID。
- Cookie 保持 HttpOnly，并按 `/api/code-runtime/{session}` 路径隔离。

### 5.2 Runtime 浏览器会话

`apaas_sandbox_token` 继续由 Agent Runtime 生成：

- 每个浏览器独立生成。
- Cookie 值不进入 API JSON。
- Builder 只在服务端加密保存，用于该浏览器的代理恢复。
- 不同浏览器不得因为同一 binding 或同一统一账号而复用 Runtime Cookie。
- 浏览器传入的 `apaas_sandbox_token` 不是 Builder 的权威凭据。代理必须先剥离
  该 Cookie，再按签名 `browser_session_id` 对应的服务端会话行解密并注入上游。

### 5.3 Control Plane 用户凭据

本阶段不新增 `renewal_grant`、renew endpoint 或新的 Control Plane 凭据类型。
Builder 复用现有能力：

- `User.coding_access_token` 和 `User.coding_refresh_token` 已加密保存。
- `_control_plane_request_auth` 已在用户行锁下检查和刷新 access token。
- workspace 超时恢复继续调用现有 authenticated `workspace/open`。
- Control Plane 在 ready workspace reopen 时重新校验用户、租户、应用和
  workspace，并用 `preserveSessions=true` 轮换 launch token。

这使统一账号 refresh 成为静默续期的硬上限。refresh 缺失、失效或被撤销时，
Builder 不得使用 service token、平台管理员 token 或其他旁路继续续期。

### 5.4 Runtime entry token

entry token 保持一次性 launch token：

- Control Plane `workspace/open` 生成。
- Builder 只在当前服务端调用栈内使用。
- Builder 通过 `GET /api/status?token=<entry-token>` 服务端请求完成 bootstrap。
- Runtime 消费 query token 并通过 `Set-Cookie` 返回新的
  `apaas_sandbox_token`。
- bootstrap 完成后立即丢弃 entry token。
- entry token 不进入 Builder 数据库、浏览器、异常、指标标签或测试快照。

服务间 query URL 仍属于敏感数据，必须在 Builder HTTP 客户端、Runtime access
log 和 tracing 中按 `token` 参数强制脱敏。

## 6. 仓库职责和数据模型

### 6.1 仓库职责

| 仓库 | 本阶段职责 |
| --- | --- |
| `agent-runtime` | Runtime session TTL、Cookie Max-Age、稳定鉴权错误契约 |
| `apaas-builder-ai` | 干净 URL、服务端 bootstrap、浏览器会话、singleflight、重放、SSE、迁移 |
| `control-plane` | 不新增生产接口；只补现有 `workspace/open`、并发 launch token、`preserveSessions` 回归测试 |

Control Plane 的 ready reopen 和 Agent Runtime 的并发 launch token 支持是本方案
的前置能力，不作为新系统重建。

### 6.2 `CodeRuntimeBinding`

现有 binding 增加：

| 字段 | 类型与约束 | 用途 |
| --- | --- | --- |
| `builder_url` | 现有字段 | 只保存移除 `token` 后的干净 URL |
| `runtime_service_session_enc` | `Text nullable` | 最新可用 Runtime session，加密后供外层服务端 Runtime 调用 |
| `auth_generation` | `Integer not null default 1` | 成功 open/renew 后递增 |

外层会话列表、新建、激活和删除等服务端 JSON 请求必须使用
`runtime_service_session_enc` 组装 Cookie，不再从 `builder_url` 提取 entry token。

### 6.3 `CodeRuntimeBrowserSession`

新增浏览器会话表：

| 字段 | 类型与约束 |
| --- | --- |
| `id` | `Integer primary key` |
| `binding_id` | `ForeignKey(code_runtime_bindings.id, ondelete=CASCADE), indexed` |
| `browser_session_id` | `String(64), not null` |
| `runtime_session_cookie_enc` | `Text, not null` |
| `runtime_session_hash` | `String(64), not null` |
| `runtime_session_expires_at` | `DateTime, nullable` |
| `generation` | `Integer, not null, default 1` |
| `created_at` / `updated_at` | `DateTime, not null` |

唯一约束为 `(binding_id, browser_session_id)`。不增加持久化 `renewing` 状态或
lease 字段；数据库行锁释放即代表续期临界区结束，避免 worker 崩溃后留下永久
卡死状态。

明文 Runtime Cookie 和 entry token 均不得落表。`runtime_session_hash` 只用于
测试、比较和诊断，不得作为认证材料。

## 7. 首次打开和 bootstrap

1. `/code/sessions/{session}/open` 使用现有 `_control_plane_request_auth` 获取有效
   用户 Bearer。
2. Builder 调用现有 Control Plane `workspace/open`。
3. Control Plane 校验用户、平台租户、绑定的 aPaaS 租户、应用和 workspace。
4. Control Plane 返回带一次性 entry token 的 Runtime URL。
5. Builder 在内存中拆出 token，并生成不含 `token` 的 `builder_url`。
6. Builder 生成新的 `browser_session_id`。
7. Builder 服务端调用 Runtime
   `GET /api/status?token=<entry-token>`，捕获 `Set-Cookie`。
8. Builder 加密保存浏览器 Runtime Cookie，同时更新
   `runtime_service_session_enc` 和 `auth_generation`。
9. Builder 返回只包含 `dolphin_token` 的 iframe URL；该签名 token 包含
   `browser_session_id`，不包含 Runtime 凭据。
10. iframe 首次进入代理时，Builder 校验 `dolphin_token`，设置
    `dolphin_code_runtime_*`，并从对应浏览器会话行恢复、重写和设置
    `apaas_sandbox_token`。

首次打开不能复用其他浏览器的 Runtime Cookie。若 Runtime bootstrap 成功但
Builder 数据库提交失败，新 Runtime session 作为短 TTL orphan 自然过期；当前
请求失败，下一次 `/open` 可重复调用 Control Plane 并重新 bootstrap，不存在
不可恢复的中间状态。

## 8. Runtime session 契约

### 8.1 TTL

Agent Runtime 将 `sessions map[string]int64` 改为包含 generation、创建时间、
最近访问时间和过期时间的记录：

- 配置键：`APAAS_SANDBOX_SESSION_IDLE_TTL`。
- 默认值：`30m`。
- 最小值：`1m`。
- 最大值：`12h`。
- 测试通过注入 fake clock 推进时间，不使用真实 sleep 等待 TTL。
- 成功 Cookie 认证时滑动延长过期时间。
- 仅当剩余 TTL 小于等于总 TTL 的一半时重写 Cookie，减少 `Set-Cookie` 抖动。
- Cookie `Max-Age` 与服务端当前 session TTL 对齐。
- `preserveSessions=true` 只保留未过期 session。
- 默认 rotate、明确撤销和 sandbox 销毁继续清空全部 session。

`EntryTokenAuthResult` 增加 `RefreshCookie` 和 `CookieMaxAgeSeconds`，HTTP
middleware 只在新建 session 或滑动刷新门槛到达时写 `Set-Cookie`。过期分类在
删除记录前完成：已存在但过期返回 `sandbox_session_expired`，未知/撤销 Cookie
返回 `sandbox_session_invalid`；launch token 同理区分 expired 与 invalid。

### 8.2 稳定鉴权错误

Runtime 鉴权中间件在进入业务 Handler 前返回：

```http
HTTP/1.1 401 Unauthorized
X-APAAS-Sandbox-Auth-Error: sandbox_session_expired
```

错误码：

| 错误码 | 语义 | Builder 行为 |
| --- | --- | --- |
| `sandbox_session_expired` | Cookie session 超时 | 可续期 |
| `sandbox_session_invalid` | Cookie 被撤销或不匹配 | 可续期一次 |
| `sandbox_credential_missing` | 未携带 Runtime 凭据 | 不自动重放 |
| `sandbox_launch_token_expired` | bootstrap token 超时 | 重新 open 一次 |
| `sandbox_launch_token_invalid` | token 无效或已消费 | 不自动循环 |

Builder 只能根据该响应头和已知错误码判定可续期。普通 401、响应正文文本、
连接失败或未知 header 均不得触发重放。

## 9. 无感续期与并发

### 9.1 同账号 Control Plane token 刷新

Control Plane access token 的解析和刷新使用独立数据库 session：

1. 先读取当前 access token。
2. 接近过期时锁定 `User` 行。
3. 锁内二次检查，只有第一个请求执行 refresh。
4. 更新加密 access/refresh token 并提交。
5. 其他浏览器复用已更新的 token。

若 `workspace/open` 返回明确 access-token 过期，Builder 允许强制 refresh 后
重试一次。refresh 无效、账号禁用或租户权限失败立即进入硬失败。

本切片的无感保证覆盖正常 refresh 成功并完成本地凭据持久化。若远端一次性
refresh 已轮换、但 Builder 保存新凭据时数据库提交失败，当前请求归一化为
`workspace_temporarily_unavailable`，不清 Cookie、不循环刷新；该跨系统恢复
由 `P5-A` 单独设计，不能在本阶段误报为已解决。

Control Plane 结果按以下稳定外部语义归一化：

| 结果 | Builder 外部状态 | 是否清 Cookie |
| --- | --- | --- |
| refresh 失败或重试后仍为 401 | `login_required` | 是 |
| 403 | `workspace_forbidden` | 是 |
| 404/410 | `sandbox_unavailable` | 是 |
| timeout/5xx | `workspace_temporarily_unavailable` | 否 |

timeout/5xx 不得被误报为登录失效，也不得无界重试；当前请求完成一次续期预算后
返回暂时不可用状态。

### 9.2 单浏览器 singleflight

代理向 Runtime 发请求前记录当前浏览器会话 `observed_generation`。收到可续期
鉴权错误后：

1. 不向浏览器发送上游响应。
2. 校验代理 Cookie 中的 `browser_session_id` 与 binding 的用户、租户归属。
3. 在独立数据库 session 中取得有效 Control Plane 用户 Bearer。
4. 对 `(binding_id, browser_session_id)` 执行 `SELECT ... FOR UPDATE`。
5. 若行内 generation 已大于 `observed_generation`，复用新 Runtime Cookie。
6. 否则在行锁内调用现有 `workspace/open`，超时上限为 60 秒。
7. 用新 entry token 调 Runtime `/api/status?token=...`，超时上限为 10 秒。
8. 原子更新浏览器 Cookie、binding 服务端 Cookie 和 generation 后提交。
9. 把新 Runtime Cookie 写回当前浏览器。
10. 原请求只重放一次。

同一浏览器的并发 HTML、静态资源、API 和 SSE 请求只有一个请求实际 open；
等待者取得行锁后看到新 generation，直接 join。worker 崩溃时数据库自动释放
行锁，不保留 `renewing` 状态。

每次正常代理请求同样按 `browser_session_id` 读取对应行，剥离浏览器请求中的
Runtime Cookie 后注入服务端保存值。浏览器 Cookie 仅用于保持现阶段兼容和
Runtime 原生语义，不能改变服务端选择的浏览器会话。

请求进入代理时计算浏览器传入 Runtime Cookie 的 hash，并与服务端行的
`runtime_session_hash` 比较。缺失或不一致时：

- 上游仍直接使用数据库中已提交的加密 Cookie。
- 当前响应重新下发服务端 Cookie。
- 不调用 `workspace/open`，不增加 generation。

因此“数据库提交成功、`Set-Cookie` 响应中断”的下一请求会零次 reopen 地恢复。

### 9.3 多浏览器隔离

Chromium 和 Firefox 使用不同浏览器会话行，因此可以并行续期：

- 两端各自取得独立 launch token 和 Runtime Cookie。
- 浏览器 A 的续期不能修改浏览器 B 的行、generation 或 Cookie。
- binding 的 `runtime_service_session_enc` 允许最后成功者写入，不能覆盖浏览器
  专属行。
- 同一用户 access token refresh 仍由 `User` 行锁串行化。

Control Plane 已支持 `preserveSessions=true` 下多个并发 launch token；L2 必须
用 barrier 证明两个 token 可分别消费，不能只做顺序测试。

### 9.4 部分成功恢复

| 失败点 | 恢复策略 |
| --- | --- |
| Control Plane open 失败 | 不改浏览器行，按可恢复/硬失败分类 |
| open 成功、Runtime bootstrap 失败 | 丢弃 token，最多重新 open 并 bootstrap 一次 |
| bootstrap 成功、数据库提交失败 | 新 session 作为 orphan 等待 TTL；下次请求重新 open |
| 数据库提交成功、浏览器响应中断 | Cookie hash 不一致时直接恢复数据库 Cookie，零次 reopen |
| refresh 远端轮换成功、Builder 提交失败 | 返回暂时不可用且不清 Cookie；后续恢复属于 P5-A |

每个外部调用都设置超时。一个代理请求最多执行两次 `workspace/open`、两次
bootstrap 和一次业务请求重放，不允许无界循环。

## 10. 请求重放规则

GET、HEAD、iframe HTML、静态资源和 SSE 建连可在明确 Runtime auth header 下
重放一次。

POST、PUT、PATCH 和 DELETE 只有同时满足以下条件才允许重放：

- Runtime 返回已登记的 `X-APAAS-Sandbox-Auth-Error`。
- Runtime 测试证明鉴权中间件在业务 Handler 前产生该响应。
- Builder 已按字节缓冲原请求体。
- 当前请求尚未执行续期重放。

L2 测试必须让首个请求在 auth middleware 被拒绝，断言 Handler 调用次数为
`0`；续期后重放字节与原请求完全一致，最终 Handler 调用次数为 `1`。普通
401、缺失/未知 header 或第二次 401 均不得再次重放。

## 11. SSE 处理

Builder 必须取得上游 status 和 headers 后，再创建下游 `StreamingResponse`：

- 上游 2xx：正常转发。
- 明确 sandbox auth 401：关闭上游，续期并重新建立一次 SSE。
- 其他 4xx/5xx：原样返回。

ASGI 契约测试必须记录 `http.response.start` 和 `http.response.body` 事件，证明
可恢复 401 场景在续期完成前没有任何下游响应事件。已建立的 SSE 不因 TTL
主动断开；浏览器重连时再走正常鉴权与透明续期。

## 12. 硬失败边界

以下情况禁止继续静默续期：

- 统一账号 refresh 缺失、失效或撤销。
- 用户被禁用或删除。
- 平台租户成员关系失效。
- 平台租户与 aPaaS 租户解绑。
- 应用或 workspace 权限被撤销。
- sandbox 已销毁。

Builder 清除当前浏览器的两层沙箱 Cookie，停止重试，并根据稳定错误映射进入
重新登录或无权限状态。不得回退到全局管理员 token、service token 或宽权限
delegation。

## 13. 滚动迁移和回滚

迁移使用 expand/contract：

1. **Expand release**：新增字段和浏览器会话表；新代码只写干净 URL，但允许
   临时读取历史 tokenized URL 以完成 reopen，不执行批量删除。
2. **版本门禁**：通过实例版本指标和写入扫描确认所有旧 worker 已退出，不再
   有代码写回 tokenized URL。
3. **Contract cleanup**：按主键 checkpoint 分批移除 `builder_url` 中名为
   `token` 的 query 参数，保留其他参数；不把旧 token 搬到其他字段。
4. **持续扫描**：记录 `rows_scanned`、`rows_cleaned`、`rows_recontaminated`，
   任一重新污染阻断发布。

cleanup 之后只允许回滚到兼容新 schema 且不会写 tokenized URL 的 expand
版本，不允许回滚到旧 writer。历史 binding 缺少 Runtime session 时通过已认证
`workspace/open` 自愈。

## 14. 安全和可观测性

### 14.1 Canary 泄漏扫描

测试为 entry token、Runtime Cookie 和 Control Plane token 注入唯一 canary，
并扫描：

- Builder 数据库和 API JSON。
- 浏览器 URL、Cookie 名单、localStorage、sessionStorage。
- 上下游 request/response headers 和 bodies。
- Builder、Control Plane、Runtime 日志与异常。
- metrics 和 trace 属性。
- Playwright trace、HAR、console、`pageerror`、`requestfailed`。

Runtime Cookie 值允许存在于 HttpOnly Cookie jar 和必要的服务间 Cookie header，
但不得进入 JavaScript 可读状态、URL、日志和 artifact。entry token 不允许进入
浏览器侧任何网络 URL；服务间 query URL 必须脱敏后才能进入日志或 trace。

### 14.2 指标

- `sandbox_auth_renew_total{result,reason}`
- `sandbox_auth_renew_duration`
- `sandbox_auth_singleflight_join_total`
- `sandbox_auth_replay_total{method,result}`
- `sandbox_auth_orphan_session_total{stage}`
- `sandbox_auth_hard_failure_total{reason}`
- `sandbox_builder_url_cleanup_total{result}`

标签不得包含用户、租户、workspace、URL 或任何凭据。

允许的低基数枚举固定为：

| 标签 | 允许值 |
| --- | --- |
| `renew.result` | `success`、`transient_failure`、`hard_failure` |
| `renew.reason` | `session_expired`、`session_invalid`、`launch_expired`、`cp_access_expired`、`cp_forbidden`、`sandbox_missing` |
| `replay.method` | `GET`、`HEAD`、`POST`、`PUT`、`PATCH`、`DELETE`、`SSE` |
| `replay.result` | `success`、`rejected`、`failed` |
| `hard_failure.reason` | `login_required`、`workspace_forbidden`、`sandbox_unavailable` |
| `cleanup.result` | `scanned`、`cleaned`、`recontaminated` |

测试使用隔离 metrics registry，记录场景前后快照，断言 renew、singleflight
join、replay 和 hard failure 的目标 series 精确增加 `1`，未触发 series 增量为
`0`；同时断言 exposition 中只有白名单 label，并且不存在任一 canary。

## 15. 分等级验证

验证按 L1 到 L4 逐级执行。任一级失败立即停止升级，修复并重跑当前级。每级
完成立即汇报，不等待全量测试。

### L1：快速单元验证，目标 3 分钟内

Agent Runtime：

```bash
go test ./internal/application ./internal/http \
  -run 'TestEntryTokenManager|TestSandboxAuth' -count=1
```

Builder：

```bash
cd backend
python -m pytest \
  tests/test_code_runtime_service.py \
  tests/test_code_runtime_routes.py \
  -q
```

只运行新增或直接受影响的测试方法时，使用 `-k` 再缩小范围。覆盖 fake clock
TTL、稳定错误 header、URL 清理、加密字段、代理 Cookie 声明、最多一次重放，
以及隔离 metrics registry 的精确 delta 和标签白名单。

### L2：组件契约与确定性并发，目标 8 分钟内

Control Plane：

```bash
scripts/mvn-fast \
  -Dtest=WorkspaceOpenServiceTest,WorkspaceRuntimeProvisionerTest,AgentRuntimeInternalClientTest,HelmSandboxClientTest \
  test
```

Agent Runtime：

```bash
go test ./internal/application ./internal/http \
  -run 'TestEntryTokenManager|TestRotateEntryToken' -count=1
```

Builder：

```bash
cd backend
python -m pytest \
  tests/test_code_runtime_service.py \
  tests/test_code_runtime_routes.py \
  -q -k 'browser_session or concurrent or renew or replay or sse or bootstrap'
```

并发测试使用 `asyncio.Event`/thread barrier 阻塞在首次上游 401 后，同时释放
请求；每个 barrier 等待上限 5 秒，整体测试上限 30 秒。必须断言：

- 同浏览器 N 个请求只有一次 `workspace/open` 和一次 bootstrap。
- 两个浏览器各一次 open，Cookie、行 ID 和 generation 独立。
- Control Plane 两个并发 launch token 均可分别消费。
- POST 首次 Handler 调用为 0，重放后为 1，body 字节一致。
- SSE 续期前没有下游 ASGI response event。
- open/bootstrap 失败没有半提交浏览器行。
- 续期提交后模拟响应中断，下一请求携带旧 Cookie 时 `workspace/open` 调用为
  0，数据库 Cookie 被用于上游并重新下发浏览器。
- refresh 凭据本地提交失败时返回暂时不可用、不清 Cookie、不重试循环，也不
  把该场景计为正常无感续期通过。

### L3：真实 Chromium + Firefox，目标 12 分钟内

新增单一关键路径 runner：

- Builder：
  `tests/e2e/builder-sandbox-auth-renewal-fixture.sh` 负责启动临时数据库、fake
  Control Plane、Builder backend 和 Runtime 测试 fixture，完成后统一清理。
- Agent Runtime：
  `tests/e2e/authrenewalfixture` 是测试专用 Go binary，复用生产
  `EntryTokenManager` 和 HTTP server，但注入 controllable fake clock。
- Runtime fixture 的业务 listener 与 clock-control listener 分离。control
  listener 只绑定随机 `127.0.0.1` 端口，并要求 runner 生成的随机 nonce；该
  endpoint 不进入 `cmd/sandbox-runtime`、镜像或 Helm。
- `POST /advance` 接收 `{"duration":"31m"}`，推进 fake clock 后返回当前
  `clock_generation`。runner 只有收到 generation ack 才释放浏览器 barrier。
- fake Control Plane 提供调用计数、可切换账号禁用/refresh 失效/租户解绑状态
  和两个并发 open barrier；每个 barrier 5 秒超时，整个 runner 720 秒硬超时。

执行命令：

```bash
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.agentic-coding/playwright"
npm exec -- playwright install chromium firefox

timeout 12m env \
  PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
  bash tests/e2e/builder-sandbox-auth-renewal-fixture.sh
```

脚本必须启动两个真实 browser process，而不是同一 Chromium 的两个 page：

- `chromium.launch()` 和 `firefox.launch()`。
- 每个 browser 使用独立 context，同一统一账号、租户和 workspace。
- 两个 browser 到达 `ready-to-expire` barrier 后，runner 调 control listener
  推进 `31m`；收到 clock generation ack 后才同时释放 API、iframe、静态资源
  和 SSE 请求，不使用 TTL sleep。
- A、B 初始 Cookie、`browser_session_id` 和数据库行不同。
- A 续期时 B 的 Cookie、行和 generation 保持不变。
- A、B 同时过期时各自透明恢复 API、iframe、静态资源和 SSE。
- 页面无可恢复 401、登录弹窗、断线提示或错误页。
- trace/HAR/console/pageerror/requestfailed 和数据库均通过 canary 扫描。
- 账号禁用、refresh 失效、租户解绑分别验证硬失败且无重试循环。

若浏览器缺失，先执行 Playwright install；只有安装仍失败才停止 L3，并报告
失败命令和错误摘要。

### L4：回归，L1-L3 通过后执行

三仓命令从 `/mnt/d/workspaces/d-ai-code` 启动，可并行执行以把 wall time 控制
在约 12 分钟；每个子命令独立绑定仓库 cwd、使用 12 分钟硬超时，任一失败或
超时均表示 L4 未通过：

```bash
timeout 12m bash -lc '
  cd /mnt/d/workspaces/d-ai-code/apaas-builder-ai/backend &&
  python -m pytest -q &&
  cd ../frontend &&
  npm run test &&
  npm run build
' &
builder_pid=$!

timeout 12m bash -lc '
  cd /mnt/d/workspaces/d-ai-code/control-plane &&
  mvn verify
' &
control_plane_pid=$!

timeout 12m bash -lc '
  cd /mnt/d/workspaces/d-ai-code/agent-runtime &&
  go test ./... -count=1
' &
runtime_pid=$!

status=0
wait "$builder_pid" || status=1
wait "$control_plane_pid" || status=1
wait "$runtime_pid" || status=1
exit "$status"
```

L4 启动前先汇报 L1-L3。L4 超时不得降级为通过；应列出超时仓库并单独排查。
不得用 L4 替代跨浏览器 L3。

## 16. 验收标准

1. 新写入和迁移后的 `builder_url` 均不含 entry token。
2. entry token 不出现在浏览器 URL、存储、日志和测试 artifact。
3. Chromium 和 Firefox并发打开同一 workspace 时获得不同 Runtime session。
4. 任一浏览器 session 超时后，其 API、静态资源和 SSE 自动恢复。
5. 同浏览器并发请求只触发一次 workspace reopen。
6. 两个浏览器同时超时时互不覆盖、互不踢出。
7. 可恢复的 Runtime 401 不返回浏览器。
8. 统一账号 refresh、账号、租户和权限硬失败不会循环续期。
9. POST 等写请求不会因续期重复执行业务 Handler。
10. L1、L2、L3 通过后才进入 L4。

## 17. 路线图位置和实施拆分

本 Spec 是 P6 下的受控安全切片 `P6-A`，只处理“沙箱凭据不落浏览器 URL/数据库
和可恢复超时无感续期”。它复用已确认的平台身份与租户权威结论，但不代表 P1
全量完成，也不解锁 P2-P5、P6 其他 delegation 或 P7-P8。

后续实施计划按仓库职责拆分：

1. Agent Runtime session TTL 和稳定鉴权错误。
2. Builder 干净 binding、浏览器会话表和服务端 bootstrap。
3. Builder singleflight、Cookie hash 恢复、请求 replay 和 SSE 恢复。
4. expand/contract 迁移和 canary 泄漏扫描。
5. Control Plane 现有 reopen/并发 launch token 回归测试。
6. Chromium + Firefox 关键路径。
7. L4 回归。

每项测试先行，并按 L1 到 L4 的门禁逐级验证；不等待大批量测试后才反馈。
