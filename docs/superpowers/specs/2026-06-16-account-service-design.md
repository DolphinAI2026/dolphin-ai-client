# account-service 设计(桌面账号权威)

- 日期：2026-06-16
- 分支基线：`feat/desktop-login-mvp`
- 关联：[[desktop_delivery_cockpit_2026_06_16]]、桌面登录 MVP（`docs/superpowers/specs/2026-06-16-desktop-login-hybrid-design.md`）
- 现状分析依据：本会话 workflow《account-service 抽取分析》+ 一轮 adversarial 设计评审（已据评审修订，见 §15）

## 1. 背景与目标

桌面登录 MVP 目前把桌面账号认证（`desktop_auth.py`）挂在 ai-builder 主后端上。本地 authority 模式下账号存在每台机器各自的 SQLite，导致**换一台机器就没有账号、得手动复制 app.db**。

目标：把桌面账号认证 + 管理抽成一个**独立的公网服务 account-service**，作为桌面账号的唯一权威。桌面端走 federation 连它，任何机器用同一个公网账号即可登录，不再需要复制 app.db。

非目标：
- 不碰 ai-builder web 在线版的 aPaaS 账号登录（`login.py` 那套留在 ai-builder）。
- 不托管 aPaaS 平台凭据 / 双 ID（留 ai-builder，属业务）。
- 不做 SSO（后置）。
- 不签对外业务 token（见 §4）。
- **federation 永不授予 is_platform_admin**（见 §4、§5）。

## 2. 范围

account-service 只管 `account_source='desktop'` 的账号。aPaaS 账号及其 142 处 apaas_* 业务引用全部留 ai-builder。

第一版完成度（已确认）：认证 API + 开号/改密/停用/列账号/管租户 API + 一个 Web 管理后台 + revocation 机制。SSO 不做。

> ⚠️ 边界不是"零接触"：desktop 与 aPaaS 账号**共用一张 `users` 表、共用全局唯一的 `username` 索引**（`models/__init__.py:41`，`account_source` 只是读侧过滤、不是唯一性边界）。撞名问题见 §7，必须正面处理，不能假设两个账号集天然不相交。

## 3. 架构

account-service 是公网部署的独立服务，**同仓独立 package**（共享 `app.models` 的 User/Tenant 定义，避免模型漂移；便于桌面 sidecar 一起打包）。

它内部 = **现在 `desktop_auth.py` 的 authority 分支 + 开号端点 + 新建的管账号 API + 一个管理后台**，独立部署到公网。现有"authority / federation"两分支拆到两个部署单元：

- **account-service** = authority（持账号库、本地校验账密、开号、管账号）。
- **桌面 sidecar** = federation（转发认证、本地镜像、本地签票）。

### 组件

| 组件 | 职责 | 来源 / 工作量 |
|---|---|---|
| 账号库 | desktop User / 私有 Tenant / UserTenant / Role | 共享 `app.models` + `seed_default_roles`（`seed_data.py:13-76`，注意是 aPaaS 路径**共享依赖**，见 §7） |
| 认证 API | `POST /login` 校验账密，**返回 `{username}`（+ 可选非特权 role hint）**；登录侧的租户/角色由下游本地派生（见 §5） | 抽 `desktop_auth.py:_authority_login` + `verify_desktop_account` |
| 建号 API | 开号（管理员门） | 抽 `admin_create_account` + `provision_desktop_account`（已有） |
| **管账号 API（净新建）** | 列账号 / 改密 / 停用 / 管租户 | **现状不存在**，net-new：~4 端点 + service 函数 + 测试 |
| revocation | 停用/改密向下游传播 + token TTL（见 §8） | net-new |
| 管理后台 UI | 上述操作的 Web 界面 | 复用 admin-spa **页面骨架**；**data 层是重写**（见 §9） |

> 修正：原 spec 把"管账号 + 管理后台"当成抽取，实际上现状只有 `/login` 和 `/admin/accounts` 两个端点（`desktop_auth.py:84,102`），其余全是 net-new。第一版工作量 = 抽取（认证/开号）+ **净新建**（管账号 API、revocation、管理后台 data 层）。

## 4. 信任模型

桌面 federation = **"转发认证 + 下游本地签票"**：sidecar 把账密转给 account-service，account-service 只回答"账密对不对、username 是谁"（`_remote_authenticate` 返回 `{username}`，`desktop_auth.py:53`），**业务 JWT 由 sidecar 用自己的 `jwt_secret` 本地签**（`desktop_sidecar.py:13-25` 每实例独立密钥）。

因此 account-service **不签对外业务 token**，**不需要跨服务共享密钥 / JWKS**。

### 4.1 本地签票的信任边界（必须明确）

- **本地签的票只被该本地实例信任**，account-service 和任何共享后端都**不得**接受 sidecar 签的票。account-service 校验账密、签发自己管理后台会话用的内部 JWT，二者密钥**必须不同**（否则 §4 的"无共享密钥"被后门破坏）。
- **federation 镜像出的用户权限（role / is_platform_admin / 所属租户）是本地派生、本地未验证的**。谁控制 sidecar 进程，谁能在本机把镜像 provision 成任意权限并签票（`desktop_accounts.py:45-62` 本地写、`deps.py:181-189` 本地信任）。这在"单机自洽、本地实例无共享资源访问权"前提下可接受——blast radius 仅限本机私有租户。
- **危险前提**：一旦本地签的票被呈给任何共享后端（同一 JWT 到达 agent.dfy / 任何信任 ai-builder JWT 的多租户服务），自提升的 `is_platform_admin` 就成真跨租户提权。**因此铁律：本地签票绝不跨实例信任。若将来有下游和 sidecar 共享 JWT 信任域，"无 JWKS"简化立即失效，必须上 §8 Step 4（JWKS + 服务端签票）。**
- **is_platform_admin 是 local-authority-only 概念**：federation 路径永不把 remote is_platform_admin 写进本地镜像（`provision_desktop_account` 的 `is_platform_admin` 默认 False，federation 不传，`desktop_accounts.py:33-36` 注释已是此约束）。account-service 即便在自己库里给某账号标了管理员，那也只是它管理后台的权限，不经 federation 流到桌面端。

## 5. 数据流

**桌面登录**：
```
sidecar POST /api/desktop-auth/login (federation)
  → 转发 account-service POST /login (账密)
  → account-service authority 校验(verify_desktop_account)
  → 返回 {username}  (不含权限字段)
  → sidecar 本地镜像 user(provision if absent, is_platform_admin=False)
     + 本地私有租户 + 本地 tenant_admin 角色
  → 本地签 JWT(tenant/role 全来自本地镜像)
  → 登录成功
```
身份（tenant_id / role）**不跨 federation 传输**，由下游本地镜像派生。account-service 是"账密是否有效"的权威，不是"这台桌面上该用户有什么权限"的权威。

**开号**：管理员经管理后台 / API → account-service `provision_desktop_account`（建号 + 私有租户 + tenant_admin）。

**新机器**：federation 首次登录自动本地镜像，无需复制 app.db——**前提是该 username 在本地 `users` 表不与已有 aPaaS 账号撞名**（见 §7）。

## 6. 数据库

account-service 持桌面账号库（desktop User/Tenant/UserTenant/Role）为权威，**独立库实例**。

桌面 sidecar / ai-builder 侧本地镜像 user/tenant（现状 federation 已做）。镜像只为本地签票 + 本地业务上下文。

account-service 写入**必须强制 `account_source='desktop'`**（列 server_default 是 `'apaas'`，`models/__init__.py:50`，不显式设会默默变 apaas、被 `verify_desktop_account` 过滤掉而无法登录）。

## 7. 账号命名空间（撞名处理）

`users.username` 全局唯一。desktop 与 aPaaS 两个写入方在同一唯一索引上冲突：
- account-service provision desktop `zhangsan` 后，ai-builder aPaaS 登录 `zhangsan` 会按 username 命中并**覆盖** hashed_password / is_platform_admin / apaas 字段（`login.py:589,601-609`）。
- 反向，已有 aPaaS `zhangsan` 会让 `provision_desktop_account` 抛 `AccountExistsError`（对任意 source 同名即拒，`desktop_accounts.py:37-39`）。
- 物理分库后：account-service 与 ai-builder 各自 `users` 表 = 两个独立 username 唯一域。federation 镜像 desktop `zhangsan` 到 ai-builder 表时，若 aPaaS `zhangsan` 已占索引 → **IntegrityError，登录失败**。"新机器自动镜像"承诺对撞名 username 破。

**方案（推荐，待确认）**：ai-builder 端把 `users` 的唯一约束从 `username` 改为复合 `(username, account_source)`（一次迁移）。这样 federation 镜像 desktop 用户进本地表时，和同名 aPaaS 行不撞索引；`verify_desktop_account` / aPaaS 登录本就各按 account_source 过滤，语义不变。account-service 自己库内 desktop username 唯一即可。
- 备选：desktop username 加命名空间前缀；或行政上声明两个 username 空间必须不相交并文档化失败模式。复合唯一最干净，改动局限在约束 + 镜像 upsert 的 where。

**共享依赖 `seed_default_roles`**：被 desktop（`desktop_accounts.py:44`）和 aPaaS（`login.py:521`）双路径调用，且 import LLMConfig / PERMISSION_CODES（`seed_data.py:8-10`）。抽进 account-service 要么复制（drift），要么共享 models 包里保留它（account-service 因此拖入 LLMConfig 等模块定义）。决策：放共享 `app.models`/seed 包，两边引用同一份。

## 8. 信任 / 吊销 / 会话生命周期（净新建，重点）

现状缺口（评审实证）：token TTL = 1440min / **24h**（`config.py:53`）；federation 镜像后，`get_auth_context` 只校验**本地**镜像 `is_active`（`deps.py:160`、`auth.py:194`），**从不回调 account-service**。后果：account-service 停用账号 / 改密，对下游已登录机器**24h 内无效**；本地镜像 `is_active` 没有任何路径会因远端停用而翻转；改密更无效（本地密码是随机 throwaway，`desktop_auth.py:63`）。**离职员工锁不掉已用过的机器。**

第一版必须包含 revocation：
- **缩短 federation access token TTL**（如 30 分钟），到期强制重新 federation 认证。
- **每次 app 启动 + 周期心跳**向 account-service 校验账号 `is_active`，远端停用 → 翻转本地镜像 `is_active` → 本地校验即失效。
- **容忍的吊销延迟 SLA = 停用后 ≤30 分钟全机失效**（已定）。据此：federation access token TTL ≤30min + 启动时强制重校验 + 心跳同步频率 ≤30min。
- 停用语义：停用必须能传播到本地镜像 `is_active`（今天没有这条路径，net-new）。
- 改密语义：改密使后续 federation 重认证失败即可（本地 session 在 TTL 内仍有效，靠短 TTL 收敛）。

## 9. 管理后台

复用 admin-spa 的 `PlatformUsers.vue` / `PlatformTenants.vue` **页面骨架**。但 data 层是重写不是改适配：
- `PlatformUsers.vue:127` 调 `/auth/tenant-users`（ai-builder aPaaS 向端点）；`PlatformTenants.vue:154,163` 调 `/mcp-platform/apaas-admins|apaas-tenants`（**aPaaS 专属，account-service 根本没有**）；`admin-spa/src/api/client.ts:2-14` baseURL 硬连 ai-builder 后端。
- 复用 = 拿视觉骨架 + 重写所有 API 调用指向 account-service 的 net-new 管账号端点 + 重定 baseURL。spec 按"重写 data 层"计工作量，不按"改适配"。

account-service 管理后台是**独立的公网 Web**（给管理员用），**不进桌面 app 包**。

## 10. ai-builder / 桌面 sidecar 侧改动

federation 转发认证、本地签票、本地镜像现成。落地：
- sidecar `PUBLIC_ACCOUNT_BASE_URL`（`desktop_sidecar.py:45`）从空改成指向 account-service 公网地址 → 切 federation。env 开关，不改码。
- 本地 authority 默认（空）保留作离线兜底。
- ai-builder `users` 唯一约束迁移到复合（§7）。
- 缩短 token TTL + 加 is_active 心跳同步（§8）。

## 11. 迁移路径（不停机）

- **Pre-req（独立 commit，与抽取正交）**：收敛第二签发器 `mcp_server.py:95-103` `_sign_service_token` 回 `auth.py` 单一工厂。这是 ai-builder MCP 基建的 cleanup，**不该捆进抽取 Step 0**（评审：捆绑两个无关 refactor 抬高"零行为变化"步骤风险）。
- **Step 0 — 圈地（零行为变化）**：把桌面账号代码（`desktop_auth.py` authority+开号分支、`desktop_accounts.py`、`auth.py` 账号所需部分）收进内聚 package。**明确 `deps.py` 的处理**：`resolve_default_tenant_id_for_user`（`deps.py:34-45`）嵌在共享 auth-context 核心里，抽取要决定 fork（account-service 复制一份）还是 share（account-service import ai-builder deps + 其 FastAPI/JWT 机制）——**推荐 fork 小函数**，避免 account-service 拖入整个 deps 模块。
- **Step 1 — 抽 account-service 进程**：新建 `backend/services/account_service/`，挂认证 + 开号 + 管账号 API + 管理后台，独立库，独立 JWT secret，部署公网。**明确 `desktop_auth.py` 双分支怎么拆**：account-service 取 authority 分支、sidecar 取 federation 分支——不是同一文件部署两次靠 env gate（drift），而是各持自己需要的那半。`config.py` 给 account-service 一个 Settings 子集（自己的 jwt_secret、db url）。
- **Step 2 — 桌面切 federation + 收敛耦合**：sidecar 指向 account-service；ai-builder `users` 复合唯一迁移；加 revocation 心跳。
- **Step 3（后置，仅多下游公网 SaaS）**：分库已在 Step 1 做；若出现共享 JWT 信任域，上 JWKS + 服务端签票（§4.1 铁律触发）。

## 12. 错误处理

| 情形 | 行为 | 依据 |
|---|---|---|
| account-service 不可达 | federation 503「公网账号服务不可达」 | `desktop_auth.py:43-44` 已有 |
| 账密错 | 401 | 已有 |
| 公网非 401 异常 | 502 | `desktop_auth.py:50-52` 已有 |
| 开号权限不足 | 403 | `desktop_auth.py:109` 已有 |
| 镜像撞名 | IntegrityError → 复合唯一迁移后消除（§7） | net-new |
| 离线/无网 | 本地 authority 兜底 | 保留 |

## 13. 测试

- account-service 单测：开号 / 校验 / login（迁移 `test_desktop_accounts.py` + `test_desktop_auth_routes.py`）。
- **管账号 net-new 测试**：列/改密/停用/管租户 + revocation 传播（停用后本地镜像 is_active 在 SLA 内翻转）。
- federation 端到端：两实例（迁移 `test_desktop_auth_federation.py`）+ 撞名场景（aPaaS 同名存在时 desktop 登录仍成功）。
- 命名空间迁移测试：复合唯一下 desktop+aPaaS 同名共存。

## 14. 已定决策 + 待拍板

| 决策 | 状态 |
|---|---|
| 范围只桌面账号 | ✅ 定 |
| 第一版 认证 + 管理后台 + revocation，无 SSO | ✅ 定 |
| 同仓独立 package，共享 models | ✅ 定 |
| 管理后台复用 admin-spa 骨架（data 层重写） | ✅ 定 |
| federation 本地签票、无 JWKS、is_platform_admin 不跨 federation | ✅ 定（§4） |
| account-service 独立库 | ✅ 定 |
| **撞名方案**：ai-builder `users` 改复合唯一 `(username, account_source)` | ✅ 定（§7） |
| **吊销延迟 SLA**：停用后 ≤30 分钟全机失效（TTL≤30min + 启动重校验 + 心跳） | ✅ 定（§8） |
| 密码哈希 sha256 → bcrypt/argon2 | ✅ 纳入第一版 |

## 15. 评审修订记录

本 spec 经一轮 adversarial 设计评审修订，纳入 6 项：①federation 契约改正（只返 username、身份本地派生、is_platform_admin 不跨 federation）②本地签票信任边界（§4.1）③撞名/共享 users 表（§7）④迁移耦合点 deps/module-split/config/signer（§11）⑤管理 API net-new + admin-spa data 层重写（§3、§9）⑥revocation 净新建（§8）+ 密码哈希升级优先级。

## 16. 关键文件索引

- 桌面认证/开号：`backend/app/routes/desktop_auth.py:1-123`（authority 分支抽走、federation 分支留 sidecar）
- 建号：`backend/app/desktop_accounts.py:1-76`
- JWT 工厂：`backend/app/auth.py:62-168`；待收敛第二签发器 `backend/app/mcp_server.py:95-103`
- 共享 seed：`backend/app/seed_data.py:13-76`（aPaaS+desktop 双路径）
- 默认租户解析（待 fork）：`backend/app/deps.py:34-45`
- aPaaS 撞名覆盖点：`backend/app/routes/auth/login.py:589,601-609`
- 唯一约束：`backend/app/models/__init__.py:41,48-50`
- sidecar / federation 开关 / TTL：`backend/desktop_sidecar.py:28-49`、`backend/app/config.py:53`
- 吊销缺口：`backend/app/deps.py:160`、`backend/app/auth.py:194`
- 管理后台来源：`admin-spa/src/views/PlatformUsers.vue:127`、`admin-spa/src/views/PlatformTenants.vue:154-179`、`admin-spa/src/api/client.ts:2-14`
