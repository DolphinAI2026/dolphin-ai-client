# 桌面产品登录模块 MVP（SP-A+B+C）— 验收记录

- 日期：2026-06-16
- 分支：`feat/desktop-login-mvp`（从 `feat/desktop-phase0-spike` 切，含 Phase 0 产物；均未并 dev）
- 设计：`docs/superpowers/specs/2026-06-16-desktop-login-hybrid-design.md`
- 计划：`docs/superpowers/plans/2026-06-16-desktop-login-mvp.md`

## 结论

**MVP 跑通。** 「两层身份分离 + 混合架构（公网管账号 / 本地管开发）+ 单独的桌面产品登录模块」最小闭环已实现并经两实例联邦端到端验证。Task 1–6 全部实现，每个过 spec 合规 + 代码质量审查（部分合并为单次先 spec 后质量）。Task 7 两实例联邦验证全绿。

## 两实例联邦端到端验证（本机，不依赖真 agent.dfy）

起两个本地实例：authority(:9100, 无 `public_account_base_url`=authority 模式) + sidecar(:9200, `DESKTOP_MODE=1` + `PUBLIC_ACCOUNT_BASE_URL=http://127.0.0.1:9100`=federation 模式)。结果：

- authority 直连 `/api/desktop-auth/login`(mars/pw123456) → 200 + token ✅
- sidecar federation 登录 → 转发到 authority 认证 → 返回 **sidecar 本地签发的** token ✅
- federation 错误密码 → 401 ✅
- 用 federation token 调 `/api/platform-envs` → **200**（证明本地镜像出的 user 带 tenant_admin 上下文，`require_tenant_admin` 通过；登录后配 aPaaS 环境这层可用）✅
- sidecar 本地库镜像出 mars（1 行；二次登录幂等不重复建）✅

## 实现的东西

| 子项 | 内容 | 关键文件 |
|---|---|---|
| 账号模型 | `User.account_source`('apaas'/'desktop') 隔离两类账号；建号(独立租户+tenant_admin)/校验业务函数 | `backend/app/desktop_accounts.py`、`models/__init__.py`、`database.py`(幂等 ALTER) |
| authority 登录 | `POST /api/desktop-auth/login` 校验桌面账号、签 ai-builder JWT，**绕开 aPaaS 登录链** | `backend/app/routes/desktop_auth.py` |
| 管理员开号 | `POST /api/desktop-auth/admin/accounts`(平台管理员 only，`ctx.user.is_platform_admin` 门控) | 同上 |
| federation | `public_account_base_url` 配置 + sidecar 注入 `PUBLIC_ACCOUNT_BASE_URL`；sidecar 转发公网认证→本地镜像 user/tenant→签本地 JWT(token 不跨端复用，本地用自己的 jwt_secret_key 重签) | `config.py`、`desktop_sidecar.py`、`desktop_auth.py` |
| 前端 | 编译期 `__DESKTOP__` flag；桌面构建 `/login` 渲染新 `DesktopLogin.vue`(账号+密码)，aPaaS `Login.vue` tree-shake 出桌面包、在线版不动 | `vite.config.ts`、`package.json`、`src/vite-env.d.ts`、`src/views/DesktopLogin.vue`、`src/api/desktopAuth.ts`、`src/router/index.ts`、`src/stores/user.ts` |

测试：desktop_accounts(4) + desktop_auth_routes(9) + desktop_auth_federation(3)，全绿；与 aPaaS 登录链零纠缠（独立路由 + account_source 过滤 + 同名 aPaaS 账号不被当桌面账号验，有显式测试）。

## 提交（feat/desktop-login-mvp）

1. `User.account_source` + 建号/校验业务函数
2. `/api/desktop-auth/login` authority 模式
3. 平台管理员开号端点
4. federation 模式(转发+镜像+本地JWT)
5. 前端 `__DESKTOP__` flag
6. `DesktopLogin.vue` + 路由分支 + d.ts 重定位

## 待你/后续做的

- **部署到 agent.dfy**：把这套后端部署到公网 dev 环境，在那以 authority 模式跑；用管理员账号调 `POST /api/desktop-auth/admin/accounts` 给交付同事开号。（部署=crane/k8s 人工步骤，见 [[deploy_crane_workaround_2026_06_08]]。）
- **整壳连真公网**：`scripts/build-desktop.sh` 出 .app，`PUBLIC_ACCOUNT_BASE_URL` 指向真 agent.dfy；打开 .app 看到新产品登录页 → 登录 → 进应用 → platform_envs 配 aPaaS。
- **管理员开号 UI**：目前开号是 API（`/admin/accounts`）；公网后台加个最小开号页面更顺手（admin-spa）。
- **SP-D**：aPaaS 环境配置的公网存储 + 本地同步（MVP 期 platform_envs 仍按现状本地存）。
- **SP-E / Phase-1 债**：离线会话 TTL；SSO provider（钉钉/企微，非必须）；密码哈希 sha256→bcrypt/argon2（现沿用 sha256，弱）；`PUBLIC_ACCOUNT_BASE_URL` 默认硬编码生产地址（dev 本地跑要显式覆盖）；federation 转发明文密码须走 https(生产 agent.dfy)。

### 终审发现的隔离加固项（终审判定非阻塞/潜在，未在本轮改，按优先级记账）

1. **(最值得先做) sidecar 上 aPaaS `/api/auth/login` 旧本地回落未按 account_source 过滤**（`backend/app/routes/auth/login.py:899` 的 `select(User).where(username==...)`）。今天不可利用——federation 镜像密码随机不可用、authority 实例配了 aPaaS 会在认证失败时抛 401 而非回落；但两层隔离目前靠「密码不可用」而非结构。加固=给该回落 `.where(account_source=='apaas')`（种子管理员/aPaaS 用户都是 'apaas' 不受影响），或 `DESKTOP_MODE=1` 时不挂 `auth.router`。**改的是共享 aPaaS 路径，需单独谨慎改 + 加测**，故未在收尾时段动。
2. **federation 复用镜像查询未加 `account_source=='desktop'` 过滤**（`backend/app/routes/desktop_auth.py:61`）。fresh sidecar 上无 apaas 行=今天安全；加 `.where(account_source=='desktop')` 收紧（注意与 provision 的无过滤 dup-check 的交互：apaas 同名碰撞时会 AccountExistsError 大声失败，是更好的行为）。
3. **(Minor) 串入的 dev-proxy**：Task 5 改 `frontend/vite.config.ts` 时把并发 admin-spa 工作的 `/ai-builder/admin` dev-proxy 一起带进了提交（dev-server only、无害）。merge 时与并发分支对齐处理；本轮未动以免干扰并发会话工作树。

## 注意

- 分支链：`dev` →(Phase0)`feat/desktop-phase0-spike` →(本MVP)`feat/desktop-login-mvp`。两者都未并 dev。并入时建议先并 phase0 再并本分支，或一起 review。
- 工作树仍有并发的、与本工作无关的 admin-spa/PlatformAdminEmbed 未提交改动，全程未纳入本分支。
- 预存 `@/views/*.vue` "cannot find module" LSP 诊断是项目级 vue-shim 缺口(build:nocheck + 单独 vue-tsc)，非本次引入，未处理。
