# Builder Sandbox Token-Free Transparent Renewal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Source Spec:** `docs/superpowers/specs/2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md`

**Goal:** 让 Builder 沙箱 entry token 不落数据库和浏览器，并在 Runtime session、Control Plane access token 超时后自动续期；同一账号的 Chromium、Firefox 保持独立 Runtime 会话，用户不看到可恢复的 401、iframe 错误或 SSE 断线。

**Architecture:** Agent Runtime 提供带空闲 TTL 的 HttpOnly session 和稳定鉴权错误码；Builder 以签名 `browser_session_id` 选择服务端加密保存的 Runtime Cookie，通过现有 authenticated `workspace/open` 和 `/api/status?token=...` 完成首次 bootstrap 与单浏览器 singleflight 续期；Control Plane 不增加生产接口，只回归验证 ready reopen、`preserveSessions=true` 和并发 launch token。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, httpx, Fernet, pytest/pytest-asyncio, Go 1.24, `net/http`, Java 17, Spring Boot, JUnit 5, Mockito, Maven, Node.js, Playwright Chromium/Firefox.

---

## 执行约束

- 三个主工作区始终留在默认分支，不在主工作区 `git switch` 或 `git checkout`。
- 实施开始时分别创建：
  - `/home/shitou/worktrees/d-ai-code/agent-runtime/builder-sandbox-auth-renewal`
  - `/home/shitou/worktrees/d-ai-code/control-plane/builder-sandbox-auth-renewal`
  - `/home/shitou/worktrees/d-ai-code/apaas-builder-ai/builder-sandbox-auth-renewal`
- 每个任务先写失败测试，再写最小实现，再运行任务级命令并提交。
- L1、L2、L3、L4 严格逐级；任一级失败立即停止升级，修复并重跑当前级。
- entry token、Runtime Cookie、Control Plane token 的测试 canary 禁止出现在日志、异常、API JSON、浏览器 URL、trace/HAR 和 metrics 标签。
- 不新增 Control Plane renew endpoint、`renewal_grant`、service-token 回退或持久化 `renewing` lease。
- 远端一次性 refresh 已轮换但 Builder 本地凭据提交失败的跨系统恢复仍属于路线图
  `P5-A`；本计划只保证返回暂时不可用、不清 Cookie、不循环和不误报成功。
- 不修改旧 Coding Terminal WebSocket/query-token 链路，不在本切片收敛两层 HttpOnly Cookie。
- Builder 对一次代理请求最多执行两次 `workspace/open`、两次 bootstrap、一次业务重放。
- PostgreSQL/MySQL 依靠 `SELECT ... FOR UPDATE` 保证跨 worker singleflight；进程内 keyed lock 只作为同 worker 快速合并和 SQLite 测试适配，不能替代数据库行锁。

## Task 1: 建立三仓实施分支和共享设计输入

**Files:**
- Source: `apaas-builder-ai/docs/superpowers/specs/2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md`
- Create: `agent-runtime/docs/superpowers/specs/2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md`
- Create: `control-plane/docs/superpowers/specs/2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md`

- [ ] 从每个主仓默认分支创建 `plan/builder-sandbox-auth-renewal` worktree，不移动主工作区分支。
- [ ] 把已确认 Spec 原样复制到 `agent-runtime` 和 `control-plane` worktree，并用 checksum 证明三份内容一致：

```bash
sha256sum \
  /mnt/d/workspaces/d-ai-code/apaas-builder-ai/docs/superpowers/specs/2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md \
  /home/shitou/worktrees/d-ai-code/agent-runtime/builder-sandbox-auth-renewal/docs/superpowers/specs/2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md \
  /home/shitou/worktrees/d-ai-code/control-plane/builder-sandbox-auth-renewal/docs/superpowers/specs/2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md
```

Expected: 三行 hash 完全相同。

- [ ] 在两个协同仓分别提交：

```bash
git add docs/superpowers/specs/2026-07-17-builder-sandbox-token-free-transparent-renewal-design.md
git commit -m "docs(auth): add sandbox renewal design input"
```

## Task 2: Agent Runtime 增加 session TTL、滑动续期和稳定错误码

**Files:**
- Modify: `agent-runtime/internal/application/runtime_auth.go`
- Modify: `agent-runtime/internal/application/runtime_auth_test.go`
- Modify: `agent-runtime/internal/http/auth.go`
- Modify: `agent-runtime/internal/http/auth_test.go`
- Modify: `agent-runtime/cmd/sandbox-runtime/main.go`
- Create: `agent-runtime/cmd/sandbox-runtime/session_ttl.go`
- Create: `agent-runtime/cmd/sandbox-runtime/session_ttl_test.go`

- [ ] 先在 `runtime_auth_test.go` 增加 fake-clock 失败测试，覆盖：
  - 默认 `30m` 空闲 TTL。
  - Cookie 首次创建时 `RefreshCookie=true`、`CookieMaxAgeSeconds=1800`。
  - 剩余 TTL 大于一半时不重写 Cookie。
  - 剩余 TTL 小于等于一半时滑动续期并重写 Cookie。
  - 过期 Cookie 返回 `sandbox_session_expired`，未知或撤销 Cookie 返回 `sandbox_session_invalid`。
  - launch token 过期返回 `sandbox_launch_token_expired`；无效或已消费返回 `sandbox_launch_token_invalid`。
  - `preserveSessions=true` 只保留未过期 session；默认 rotate 清空全部 session。

- [ ] 把 session 记录改为显式结构，并保留兼容构造器：

```go
const (
    SandboxSessionExpired      = "sandbox_session_expired"
    SandboxSessionInvalid      = "sandbox_session_invalid"
    SandboxCredentialMissing   = "sandbox_credential_missing"
    SandboxLaunchTokenExpired  = "sandbox_launch_token_expired"
    SandboxLaunchTokenInvalid  = "sandbox_launch_token_invalid"
)

type EntryTokenManagerConfig struct {
    SessionIdleTTL time.Duration
    Clock          func() time.Time
}

type entrySession struct {
    generation int64
    createdAt  time.Time
    lastSeenAt time.Time
    expiresAt  time.Time
}

type EntryTokenAuthResult struct {
    Accepted            bool
    SessionCookie       string
    Generation          int64
    RefreshCookie       bool
    CookieMaxAgeSeconds int
}

type EntryTokenAuthError struct {
    Code string
}

func (e *EntryTokenAuthError) Error() string { return e.Code }
```

- [ ] `NewEntryTokenManager(source)` 使用 `30m` 默认值；新增 `NewEntryTokenManagerWithConfig` 供测试 fixture 注入时钟。
- [ ] 在删除过期记录前完成 expired/invalid 分类，禁止把原始 token 或 Cookie 写入错误文本。
- [ ] 在 `auth.go` 先写中间件失败测试，证明鉴权失败发生在业务 Handler 前，稳定响应头为：

```http
HTTP/1.1 401 Unauthorized
X-APAAS-Sandbox-Auth-Error: sandbox_session_expired
```

- [ ] `setSandboxAuthCookie` 接收 `maxAgeSeconds`，新 session 或滑动刷新时设置 `Max-Age`；普通有效 Cookie 请求不产生 `Set-Cookie`。
- [ ] `sandbox_credential_missing` 只用于未携带任何 Runtime 凭据的请求；配置 fallback token 的兼容分支保持现有行为，但也使用稳定错误头。
- [ ] 在 `session_ttl.go` 实现配置解析：

```go
func sandboxSessionIdleTTL(raw string) (time.Duration, error) {
    // empty -> 30m; reject values below 1m or above 12h
}
```

- [ ] `main.go` 增加 `APAAS_SANDBOX_SESSION_IDLE_TTL`，启动时解析失败直接报错，不静默回退。
- [ ] 运行 Runtime L1：

```bash
go test ./internal/application ./internal/http ./cmd/sandbox-runtime \
  -run 'TestEntryTokenManager|TestSandboxAuth|TestSandboxSessionIdleTTL' -count=1
```

Expected: 新增测试从失败变为通过，业务 Handler 在所有 auth 401 场景中调用次数为 `0`。

- [ ] 提交：

```bash
git add internal/application/runtime_auth.go internal/application/runtime_auth_test.go \
  internal/http/auth.go internal/http/auth_test.go \
  cmd/sandbox-runtime/main.go cmd/sandbox-runtime/session_ttl.go \
  cmd/sandbox-runtime/session_ttl_test.go
git commit -m "feat(auth): add expiring sandbox sessions"
```

## Task 3: Control Plane 锁定 ready reopen 和并发 launch token 回归

**Files:**
- Modify: `control-plane/src/test/java/com/orcamatrix/controlplane/workspace/application/WorkspaceRuntimeProvisionerTest.java`
- Modify: `control-plane/src/test/java/com/orcamatrix/controlplane/workspace/application/WorkspaceOpenServiceTest.java`
- Modify: `control-plane/src/test/java/com/orcamatrix/controlplane/workspace/infrastructure/adapter/AgentRuntimeInternalClientTest.java`
- Modify: `control-plane/src/test/java/com/orcamatrix/controlplane/workspace/infrastructure/adapter/HelmSandboxClientTest.java`

- [ ] 在 `WorkspaceRuntimeProvisionerTest` 增加 `CountDownLatch` barrier 测试，同时调用两次 ready workspace `provisionExisting`：
  - 两个调用均进入 `sandboxClient.rotateLaunchToken` 后才统一释放。
  - mock 分别返回 `launch-token-a`、`launch-token-b`。
  - 两个结果 URL 分别只含自己的 token，且 token 不相同。
  - 两个调用都保持原 workspace/sandbox/conversation identity。

- [ ] 在 `WorkspaceOpenServiceTest` 增加 ready reopen 测试，证明每次 authenticated `open` 都重新经过既有用户、租户、应用和 workspace 校验，并调用 `provisionExisting`，不复用旧响应 URL。
- [ ] 在 `AgentRuntimeInternalClientTest` 固定 rotate body 中：

```json
{
  "expiresInSeconds": 300,
  "preserveSessions": true
}
```

并断言 entry token 只在 POST body 中，不进入 URI、异常或日志断言快照。

- [ ] 在 `HelmSandboxClientTest` 增加连续两次 rotate 测试，断言：
  - 每次生成不同 launch token。
  - 两次 Runtime rotate 都携带 `preserveSessions=true`。
  - projected Secret 最终为第二个 token。
  - 第一个 token 不因第二次 rotate 被错误撤销；可消费性由 Task 2 Runtime 并发测试证明。

- [ ] 运行 Control Plane L2 定向测试：

```bash
scripts/mvn-fast \
  -Dtest=WorkspaceOpenServiceTest,WorkspaceRuntimeProvisionerTest,AgentRuntimeInternalClientTest,HelmSandboxClientTest \
  test
```

Expected: barrier 在 5 秒内汇合，两次 reopen 返回不同 launch token，生产代码无需修改。

- [ ] 提交：

```bash
git add src/test/java/com/orcamatrix/controlplane/workspace
git commit -m "test(auth): lock sandbox reopen token guarantees"
```

## Task 4: Builder 增加浏览器会话模型和 expand schema

**Files:**
- Modify: `apaas-builder-ai/backend/app/models/ai_chat.py`
- Modify: `apaas-builder-ai/backend/app/models/__init__.py`
- Modify: `apaas-builder-ai/backend/app/database.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_service.py`

- [ ] 先扩展模型注册测试，要求 `CodeRuntimeBinding` 包含：

```python
{"runtime_service_session_enc", "auth_generation"}
```

并要求新表具有唯一约束 `(binding_id, browser_session_id)`。

- [ ] 新增模型：

```python
class CodeRuntimeBrowserSession(Base):
    __tablename__ = "code_runtime_browser_sessions"
    __table_args__ = (
        UniqueConstraint(
            "binding_id",
            "browser_session_id",
            name="uq_code_runtime_browser_sessions_binding_browser",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    binding_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("code_runtime_bindings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    browser_session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_session_cookie_enc: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_session_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
```

- [ ] `CodeRuntimeBinding` 增加 nullable `runtime_service_session_enc` 和非空默认 `auth_generation=1`。
- [ ] `init_db` expand migration：
  - `create_all` 创建浏览器会话表。
  - 旧 binding 表增加两个字段。
  - 创建 binding/browser 索引和唯一索引。
  - SQLite rebuild helper 的 `common_columns` 自动保留新字段，不删除历史 archive。
- [ ] 增加 SQLite 旧 schema 迁移测试：先手工建旧表并插入 tokenized `builder_url`，运行迁移后旧行仍在、新列存在、URL 暂不清理。
- [ ] 运行：

```bash
cd backend
python -m pytest tests/test_code_runtime_service.py -q \
  -k 'model or browser_session or migration'
```

- [ ] 提交：

```bash
git add backend/app/models/ai_chat.py backend/app/models/__init__.py \
  backend/app/database.py backend/tests/test_code_runtime_service.py
git commit -m "feat(auth): store isolated runtime browser sessions"
```

## Task 5: Builder 实现干净 URL、签名 browser session 和服务端 bootstrap

**Files:**
- Modify: `apaas-builder-ai/backend/app/code_runtime/service.py`
- Create: `apaas-builder-ai/backend/app/code_runtime/sandbox_auth.py`
- Modify: `apaas-builder-ai/backend/app/routes/code_runtime.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_service.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_routes.py`

- [ ] 先写 URL 和 token 声明失败测试：
  - `token` query 参数被移除，`handoffId`、`tab`、fragment 等保留。
  - `build_embed_url` 不再输出 Runtime `token`。
  - `create_embed_token`、`create_proxy_cookie_token` 和对应 validate 函数必须携带并返回 `browser_session_id`。
  - 两次 `/open` 为同一账号和 binding 生成不同 256-bit 随机 browser ID。

- [ ] 在 `sandbox_auth.py` 集中实现敏感值处理：

```python
RUNTIME_COOKIE_NAME = "apaas_sandbox_token"

@dataclass(frozen=True)
class RuntimeBootstrap:
    clean_builder_url: str
    runtime_base_url: str
    runtime_cookie: str
    runtime_cookie_hash: str
    expires_at: datetime | None

def split_entry_token(builder_url: str) -> tuple[str, str]:
    """Return (clean_url, entry_token); never include the token in errors."""

def encrypt_runtime_cookie(value: str) -> str:
    return "enc:v1:" + encrypt_password(value)

def decrypt_runtime_cookie(value: str) -> str:
    ...
```

- [ ] 实现 `bootstrap_runtime_session`：
  - 只在当前调用栈中持有 entry token。
  - `GET {runtime_base_url}/api/status?token=ENTRY_TOKEN_CANARY` 代表实际服务间
    query 调用，10 秒超时；测试和日志必须对真实值脱敏。
  - 从 `response.cookies`/`Set-Cookie` 读取 `apaas_sandbox_token`。
  - 401 `sandbox_launch_token_expired` 返回可重新 open 分类；invalid 不循环。
  - 异常文本、日志和返回对象不得包含完整请求 URL。

- [ ] 修改 `open_code_session`：
  - 调用 Control Plane 后立即 `split_entry_token`。
  - bootstrap 成功后才新增/更新浏览器会话行。
  - `builder_url` 只保存 clean URL。
  - 浏览器行和 `binding.runtime_service_session_enc` 使用同一新 Cookie 密文。
  - `binding.auth_generation += 1`。
  - embed/proxy token 包含 browser ID。
  - 返回 JSON 不包含 entry token 或 Runtime Cookie。

- [ ] 首次 bootstrap 成功但 DB commit 失败测试：
  - 当前 `/open` 失败。
  - API JSON 和异常无 canary。
  - 下一次 `/open` 可重新执行，没有不可恢复状态。

- [ ] 替换 `_runtime_json_request` 的 entry-token Bearer：

```python
headers["cookie"] = (
    f"{RUNTIME_COOKIE_NAME}="
    f"{decrypt_runtime_cookie(binding.runtime_service_session_enc)}"
)
```

外层会话列表、新建、激活、删除只使用服务端 session；明确 Runtime auth 401 时通过现有 authenticated `workspace/open` 续期一次。

- [ ] 运行：

```bash
cd backend
python -m pytest \
  tests/test_code_runtime_service.py \
  tests/test_code_runtime_routes.py \
  -q -k 'clean or token or bootstrap or runtime_service or browser_session'
```

- [ ] 提交：

```bash
git add backend/app/code_runtime/service.py backend/app/code_runtime/sandbox_auth.py \
  backend/app/routes/code_runtime.py backend/tests/test_code_runtime_service.py \
  backend/tests/test_code_runtime_routes.py
git commit -m "feat(auth): bootstrap token-free runtime sessions"
```

## Task 6: Builder 以服务端浏览器会话作为代理 Cookie 权威

**Files:**
- Modify: `apaas-builder-ai/backend/app/routes/code_runtime.py`
- Modify: `apaas-builder-ai/backend/app/code_runtime/sandbox_auth.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_routes.py`

- [ ] 先写失败测试证明浏览器传入的 `apaas_sandbox_token` 永远不直接透传：
  - 正确 Cookie、错误 Cookie、缺失 Cookie三种情况，上游都收到数据库 Cookie。
  - 错误/缺失时响应重新下发数据库 Cookie。
  - 该恢复不调用 `workspace/open`，generation 不增加。
  - 浏览器 A 的代理 token 不能选择浏览器 B 的行。

- [ ] 让 `validate_proxy_cookie_token` 返回已签名 `browser_session_id`，并在 `_authorize_proxy_request` 后把认证声明传给代理，而不是只返回 `Response | None`。推荐返回：

```python
@dataclass(frozen=True)
class ProxyAuthorization:
    browser_session_id: str
    response: Response | None = None
```

- [ ] 初次 `dolphin_token` redirect 在返回前读取对应浏览器会话行，并在同一个
  307 响应中同时设置 `dolphin_code_runtime_*` 和数据库中的
  `apaas_sandbox_token`；浏览器不能再携带 Runtime entry token 完成 bootstrap。
- [ ] `/shell/agent-sessions` 等 Builder-authenticated 路由仍必须从签名代理 Cookie
  取得 browser ID。代理 Cookie仅过期时，允许在 Builder bearer 已通过后校验其
  签名和归属、忽略 `exp` 读取 browser ID 并立即重签；缺失、伪造或归属不符的
  Cookie 不能选择任一浏览器会话行。
- [ ] 将 Cookie 复制拆成显式流程：

```python
def strip_proxy_and_runtime_cookies(cookie_header: str, session_id: CodeSessionRef) -> str:
    ...

def inject_runtime_cookie(headers: dict[str, str], runtime_cookie: str) -> None:
    ...
```

禁止通过浏览器 Cookie 值决定服务端浏览器会话行。

- [ ] 每个代理请求按 `(binding_id, browser_session_id)` 查询行，并同时校验 binding 的 `tenant_id`、`user_id` 和 shell session 归属。
- [ ] 进入代理时记录：

```python
observed_generation = browser_session.generation
incoming_cookie_hash = sha256(incoming_runtime_cookie)
cookie_reissue_required = incoming_cookie_hash != browser_session.runtime_session_hash
```

- [ ] 所有 buffered 和 streaming 响应统一通过一个 response decorator 重写 Runtime `Set-Cookie` path，并在 `cookie_reissue_required` 时追加 DB Cookie。
- [ ] 运行：

```bash
cd backend
python -m pytest tests/test_code_runtime_routes.py -q \
  -k 'cookie or browser_session or proxy_authorization'
```

- [ ] 提交：

```bash
git add backend/app/routes/code_runtime.py backend/app/code_runtime/sandbox_auth.py \
  backend/tests/test_code_runtime_routes.py
git commit -m "feat(auth): enforce server-owned browser runtime cookies"
```

## Task 7: Builder 实现 singleflight、稳定失败映射和低基数指标

**Files:**
- Modify: `apaas-builder-ai/backend/app/code_runtime/sandbox_auth.py`
- Create: `apaas-builder-ai/backend/app/code_runtime/sandbox_metrics.py`
- Modify: `apaas-builder-ai/backend/app/routes/code_runtime.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_routes.py`

- [ ] 先写同浏览器并发失败测试：
  - `asyncio.Event` 让 N 个请求同时收到首个 auth 401。
  - barrier 等待最多 5 秒，测试整体最多 30 秒。
  - 只有一次 `workspace/open` 和一次 bootstrap。
  - 等待者看到 generation 已增加后 join，不再 open。

- [ ] 增加进程内 keyed lock registry，key 为 `(binding_id, browser_session_id)`；进入 lock 后仍必须在独立 SQLAlchemy session 中执行：

```python
select(CodeRuntimeBrowserSession).where(
    CodeRuntimeBrowserSession.binding_id == binding_id,
    CodeRuntimeBrowserSession.browser_session_id == browser_session_id,
).with_for_update()
```

- [ ] 实现 `renew_browser_runtime_session`：
  - 锁内二次比较 `generation > observed_generation`。
  - 未更新时通过 `_control_plane_request_auth` 和现有 `open_code_session`/`workspace/open` 获取新 launch token。
  - Control Plane timeout 60 秒，Runtime bootstrap timeout 10 秒。
  - 同一事务更新浏览器 Cookie、hash、expiry、generation、binding service Cookie 和 auth generation。
  - commit 后才允许重放。

- [ ] Control Plane 用户凭据读取必须使用独立数据库 session；access token 接近
  过期时锁定 `User` 行并在锁内二次检查，只有首个浏览器执行 refresh。若
  `workspace/open` 明确返回 access-token 401，允许强制 refresh 后重试一次；
  同账号双浏览器并发测试必须断言 refresh 调用总数为 `1`。
- [ ] 稳定失败映射：

```python
login_required                  # refresh failure or retried CP 401
workspace_forbidden             # CP 403
sandbox_unavailable             # CP 404/410
workspace_temporarily_unavailable  # timeout/5xx or refresh DB commit failure
```

前三种清当前浏览器两层 Cookie；暂时不可用不清 Cookie。禁止 service token fallback。

- [ ] 首次 open 成功但 bootstrap 失败时，最多重新 open/bootstrap 一次；第二次失败结束，不循环。
- [ ] 增加隔离指标 registry，不引入用户、租户或 URL 标签。固定 series：
  - `sandbox_auth_renew_total{result,reason}`
  - `sandbox_auth_renew_duration`
  - `sandbox_auth_singleflight_join_total`
  - `sandbox_auth_replay_total{method,result}`
  - `sandbox_auth_orphan_session_total{stage}`
  - `sandbox_auth_hard_failure_total{reason}`
  - `sandbox_builder_url_cleanup_total{result}`

- [ ] `SandboxAuthMetricsRegistry` 提供 `snapshot()` 和 Prometheus text `render()`；测试为每个场景注入独立 registry，精确断言目标 series `+1`、其他 series `+0`，并扫描 label 白名单和 canary。
- [ ] 在 `code_runtime.router` 增加不进入 OpenAPI 的
  `GET /api/code/internal/sandbox-auth-metrics`，返回 registry 的 Prometheus text；
  端点只暴露固定低基数 series，不输出实例 URL、binding、用户或租户信息。
- [ ] 增加 refresh 远端轮换成功但 Builder DB commit 失败测试：返回 `workspace_temporarily_unavailable`、不清 Cookie、不循环、不得计为 renew success。
- [ ] 运行：

```bash
cd backend
python -m pytest tests/test_code_runtime_routes.py -q \
  -k 'concurrent or renew or singleflight or hard_failure or metrics'
```

- [ ] 提交：

```bash
git add backend/app/code_runtime/sandbox_auth.py \
  backend/app/code_runtime/sandbox_metrics.py backend/app/routes/code_runtime.py \
  backend/tests/test_code_runtime_routes.py
git commit -m "feat(auth): singleflight sandbox session renewal"
```

## Task 8: Builder 统一请求重放并在 SSE 下游启动前完成续期

**Files:**
- Modify: `apaas-builder-ai/backend/app/routes/code_runtime.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_routes.py`

- [ ] 先把上游发送收敛为单一 helper，测试以下返回值：

```python
@dataclass
class UpstreamAttempt:
    response: httpx.Response
    client: httpx.AsyncClient
    recoverable_auth_error: str | None
```

只有 `status_code == 401` 且 `X-APAAS-Sandbox-Auth-Error` 属于
`sandbox_session_expired|sandbox_session_invalid` 才可续期。

- [ ] 普通 401、缺失 header、未知 header、`sandbox_credential_missing`、第二次 401 均不得重放。
- [ ] GET/HEAD/HTML/静态资源/SSE 建连允许一次重放；POST/PUT/PATCH/DELETE 必须使用首次读取的原始 `body: bytes`。
- [ ] Runtime 中间件契约测试和 Builder POST 测试共同证明：
  - 首个 auth 401 时业务 Handler 调用次数 `0`。
  - 重放 body 与原 body 字节完全一致。
  - 最终 Handler 调用次数 `1`。

- [ ] 调整 streaming 分支顺序：

```python
upstream = await client.send(upstream_request, stream=True)
if is_recoverable_runtime_auth(upstream):
    await upstream.aclose()
    await client.aclose()
    await renew_once(...)
    upstream, client = await send_once(...)

# Only now construct StreamingResponse.
return StreamingResponse(...)
```

- [ ] 增加直接调用 ASGI app 的测试 recorder，记录 `http.response.start` 和 `http.response.body`；可恢复 SSE 401 在续期完成前事件列表必须为空。
- [ ] 增加第二次 SSE 401 测试，证明它原样结束且不触发第三次连接。
- [ ] 运行：

```bash
cd backend
python -m pytest tests/test_code_runtime_routes.py -q \
  -k 'replay or post or sse or streaming'
```

- [ ] 提交：

```bash
git add backend/app/routes/code_runtime.py backend/tests/test_code_runtime_routes.py
git commit -m "feat(auth): replay sandbox requests before response start"
```

## Task 9: Builder 完成 contract cleanup、泄漏扫描和 L1/L2 门禁

**Files:**
- Create: `apaas-builder-ai/backend/scripts/cleanup_code_runtime_builder_urls.py`
- Modify: `apaas-builder-ai/backend/app/code_runtime/sandbox_auth.py`
- Modify: `apaas-builder-ai/backend/app/routes/code_runtime.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_service.py`
- Modify: `apaas-builder-ai/backend/tests/test_code_runtime_routes.py`

- [ ] 先写 cleanup 失败测试：
  - 按主键 checkpoint 和固定 batch size 扫描。
  - 只删除 query key 精确等于 `token` 的参数，保留其他 query、空参数和 fragment。
  - 重跑幂等。
  - 输出 `rows_scanned`、`rows_cleaned`、`rows_recontaminated`。
  - 任一 recontaminated row 返回非零退出码并阻断 contract release。

- [ ] cleanup 脚本默认 dry-run，只有 `--apply` 才提交；日志只输出行 ID 和计数，不输出 URL。
- [ ] 增加 `GET /api/code/internal/sandbox-auth-state`，固定返回
  `{"writer_contract":"clean_builder_url_v1","app_version":APP_VERSION}`。contract
  cleanup 前由发布脚本轮询每个 Builder 实例，只有全部实例都返回
  `clean_builder_url_v1` 才允许执行 `--apply`；缺失、旧值或请求失败均阻断 cleanup。
- [ ] 增加 expand writer 扫描测试：所有 `open_code_session` 新写入必须为 clean URL；历史 tokenized URL 只允许临时读取，不允许重新写回。
- [ ] 为 entry token、Runtime Cookie、Control Plane token 注入三种唯一 canary，扫描：
  - SQLAlchemy 行和 API JSON。
  - 请求/响应 headers 与 bodies 的测试 recorder。
  - captured logs 和异常字符串。
  - metrics exposition。
  - embed URL 和代理 redirect。
- [ ] 运行完整 L1；任一失败立即停止：

```bash
cd /home/shitou/worktrees/d-ai-code/agent-runtime/builder-sandbox-auth-renewal
go test ./internal/application ./internal/http \
  -run 'TestEntryTokenManager|TestSandboxAuth' -count=1

cd /home/shitou/worktrees/d-ai-code/apaas-builder-ai/builder-sandbox-auth-renewal/backend
python -m pytest \
  tests/test_code_runtime_service.py \
  tests/test_code_runtime_routes.py \
  -q
```

- [ ] L1 通过后立即汇报，再运行完整 L2：

```bash
cd /home/shitou/worktrees/d-ai-code/control-plane/builder-sandbox-auth-renewal
scripts/mvn-fast \
  -Dtest=WorkspaceOpenServiceTest,WorkspaceRuntimeProvisionerTest,AgentRuntimeInternalClientTest,HelmSandboxClientTest \
  test

cd /home/shitou/worktrees/d-ai-code/agent-runtime/builder-sandbox-auth-renewal
go test ./internal/application ./internal/http \
  -run 'TestEntryTokenManager|TestRotateEntryToken' -count=1

cd /home/shitou/worktrees/d-ai-code/apaas-builder-ai/builder-sandbox-auth-renewal/backend
python -m pytest \
  tests/test_code_runtime_service.py \
  tests/test_code_runtime_routes.py \
  -q -k 'browser_session or concurrent or renew or replay or sse or bootstrap'
```

- [ ] 提交：

```bash
git add backend/scripts/cleanup_code_runtime_builder_urls.py \
  backend/app/code_runtime/sandbox_auth.py \
  backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py
git commit -m "feat(auth): clean legacy sandbox entry tokens"
```

## Task 10: 增加可控时钟 Runtime fixture 和双浏览器 L3

**Files:**
- Create: `agent-runtime/tests/e2e/authrenewalfixture/main.go`
- Create: `agent-runtime/tests/e2e/authrenewalfixture/main_test.go`
- Create: `apaas-builder-ai/tests/e2e/fixtures/fake_control_plane.py`
- Create: `apaas-builder-ai/tests/e2e/builder-sandbox-auth-renewal.spec.mjs`
- Create: `apaas-builder-ai/tests/e2e/builder-sandbox-auth-renewal-fixture.sh`

- [ ] Runtime fixture 复用生产 `EntryTokenManager` 和 `internal/http.NewServer`：
  - 业务 listener 随机端口。
  - clock-control listener 独立绑定随机 `127.0.0.1` 端口。
  - runner 生成 256-bit nonce；`POST /advance` 必须携带 nonce。
  - body `{"duration":"31m"}`，响应包含单调递增 `clock_generation`。
  - fixture 只在 `tests/e2e` 编译，不进入 `cmd/sandbox-runtime`、镜像或 Helm。

- [ ] fake Control Plane 提供：
  - authenticated workspace/open。
  - 每个 open 生成不同 launch token 并调用 Runtime internal rotate。
  - open、refresh 调用计数。
  - 可切换 `account_disabled`、`refresh_invalid`、`tenant_unbound`。
  - 两浏览器并发 open barrier，每个等待最多 5 秒。
  - 日志对 Authorization、refresh token、launch token 统一输出 `[REDACTED]`。

- [ ] shell runner：
  - 建临时目录和 SQLite DB，不在核心仓根目录落产物。
  - 启动 Runtime fixture、fake CP、Builder backend。
  - 解析各服务 readiness 和随机端口。
  - `trap` 统一终止进程并删除临时目录。
  - 整体由外层 `timeout 12m` 控制。

- [ ] Playwright runner 必须分别调用：

```javascript
const chromiumBrowser = await chromium.launch();
const firefoxBrowser = await firefox.launch();
```

不得用同一 Chromium 的两个 page 替代。

- [ ] 两个独立 context 使用同一统一账号、租户和 workspace，断言初始：
  - `browser_session_id` 不同。
  - Runtime Cookie 不同。
  - 数据库浏览器会话行不同。

- [ ] 两端到达 `ready-to-expire` barrier 后，调用 `/advance` 推进 `31m`；收到 generation ack 后同时释放 API、iframe、静态资源和 SSE 请求，不 sleep TTL。
- [ ] 验证：
  - 浏览器 A 单独续期时 B 的行、generation、Cookie 不变。
  - A/B 同时过期时各自一次 open/bootstrap，互不覆盖。
  - 可恢复 401 不出现在页面、console、pageerror、requestfailed。
  - POST handler 不重复。
  - SSE 自动建立且页面无断线提示。
  - 账号禁用、refresh 失效、租户解绑分别硬失败且不循环。
  - trace/HAR、浏览器 URL、storage、Cookie 名单、数据库和日志通过 canary 扫描。

- [ ] 安装浏览器并运行 L3：

```bash
cd /home/shitou/worktrees/d-ai-code/apaas-builder-ai/builder-sandbox-auth-renewal
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.agentic-coding/playwright"
npm exec -- playwright install chromium firefox

timeout 12m env \
  PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" \
  AGENT_RUNTIME_REPO=/home/shitou/worktrees/d-ai-code/agent-runtime/builder-sandbox-auth-renewal \
  bash tests/e2e/builder-sandbox-auth-renewal-fixture.sh
```

Expected: runner 720 秒内退出 0；缺浏览器时先安装，安装仍失败才停止 L3 并记录失败命令。

- [ ] 分别提交 fixture 和 E2E：

```bash
# agent-runtime
git add tests/e2e/authrenewalfixture
git commit -m "test(auth): add controllable sandbox renewal fixture"

# apaas-builder-ai
git add tests/e2e
git commit -m "test(auth): verify transparent renewal across browsers"
```

## Task 11: 执行 L4、做安全复核并完成三仓收口

**Files:**
- Verify only; modify only files required by discovered regressions.

- [ ] L3 通过后立即汇报，再从 worktree 路径并行执行 L4；每个仓独立 12 分钟硬超时：

```bash
timeout 12m bash -lc '
  cd /home/shitou/worktrees/d-ai-code/apaas-builder-ai/builder-sandbox-auth-renewal/backend &&
  python -m pytest -q &&
  cd ../frontend &&
  npm run test &&
  npm run build
' &
builder_pid=$!

timeout 12m bash -lc '
  cd /home/shitou/worktrees/d-ai-code/control-plane/builder-sandbox-auth-renewal &&
  mvn verify
' &
control_plane_pid=$!

timeout 12m bash -lc '
  cd /home/shitou/worktrees/d-ai-code/agent-runtime/builder-sandbox-auth-renewal &&
  go test ./... -count=1
' &
runtime_pid=$!

status=0
wait "$builder_pid" || status=1
wait "$control_plane_pid" || status=1
wait "$runtime_pid" || status=1
exit "$status"
```

- [ ] 对三个 worktree 执行凭据模式扫描，排除测试 fixture 中明确的 canary 定义行：

```bash
rg -n \
  'builder_url.*token=|Authorization: Bearer [^[]|apaas_sandbox_token=[A-Za-z0-9_-]{20,}' \
  /home/shitou/worktrees/d-ai-code/apaas-builder-ai/builder-sandbox-auth-renewal \
  /home/shitou/worktrees/d-ai-code/control-plane/builder-sandbox-auth-renewal \
  /home/shitou/worktrees/d-ai-code/agent-runtime/builder-sandbox-auth-renewal
```

Expected: 无生产源码或生成 artifact 泄漏；命中只允许测试输入常量并逐条人工确认。

- [ ] 检查：
  - 三仓 `git status --short` 只含已知实施文件或为空。
  - 无未决占位符、跳过测试和无限重试。
  - Builder URL cleanup dry-run 的 `rows_recontaminated=0`。
  - metrics exposition 只含 Spec 白名单标签。
  - L4 的 CP 命令必须是标准 `mvn verify`，不能用 `scripts/mvn-fast` 代替。

- [ ] 使用 `agentic-coding-review`/`superpowers:requesting-code-review` 做跨仓实现复核，重点检查：
  - Runtime 401 是否始终在业务 Handler 前。
  - Builder 是否只按稳定 header 续期。
  - SSE 是否在续期前无下游 ASGI event。
  - 浏览器 Cookie 是否无法覆盖服务端 Cookie 选择。
  - singleflight 是否同时具备进程内 lock 和数据库行锁。
  - hard failure 是否没有 service-token 回退。

- [ ] 修复复核发现后，重跑受影响级别以及 L4。
- [ ] 使用 `agentic-git-sync` 按仓库分别完成默认分支集成和 upstream 同步；禁止 force push、reset、clean 或 rebase。

## 完成定义

- 新写入及 cleanup 后的 `builder_url` 不含 entry token。
- entry token 不进入浏览器 URL、API JSON、数据库、日志、metrics 或测试 artifact。
- Chromium 与 Firefox 的同账号会话具有不同 browser ID、数据库行和 Runtime Cookie。
- Runtime session 过期后 API、iframe、静态资源和 SSE 透明恢复。
- 同浏览器并发请求只触发一次 workspace reopen；两个浏览器续期互不覆盖。
- POST 等写请求的业务 Handler 总调用次数为一次。
- 普通/未知 401 不触发重放；硬失败不循环且不回退宽权限 token。
- L1、L2、L3、L4 均有独立通过记录，且任一级没有被后一级替代。
