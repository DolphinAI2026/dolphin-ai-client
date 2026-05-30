# 安全漏洞扫描报告 — apaas-builder-ai

> 日期：2026-05-30 ｜ 评审类型：给客户部署前的安全就绪评审（read-only，未改任何源码）
> 方法：两路独立安全审计并行（① 认证/授权/SSRF/注入 ② 密钥泄漏/依赖/部署配置），每条结论**逐条读真实代码 file:line 验证**，并经本机实跑佐证。
> 本文已对两路发现**去重合并**（verify=False、SHA256 口令、Fernet 默认 key、list_users 越权、JWT 等重叠项只列一次）。

---

## 0. 一句话结论

**功能成熟，但安全默认值与若干代码缺陷使「直接交付客户」存在红线风险。** 最严重的不是旧体检报告里的那条，而是**本次新发现**的两个 Critical：①平台反向代理全链路无鉴权 + 进程级全局共享管理员 token；②落库口令加密用硬编码默认密钥（**本机 `.env` 实测确实没设 `ENCRYPTION_KEY`，默认 key 正在生效**）。外加 README/git 历史明文泄漏 JWT 签名密钥（可伪造任意用户）与已提交的 RSA 私钥。

> **对旧体检（`docs/audit-2026-05-29-codebase-health.md`）的关键修正**：该报告的 P0「`exchange_apaas_token` SSRF」已被中和——既加了 `apaas_base_url` 白名单（`auth.py:159`），且该端点依赖的 `app.services.apaas_token_validator` 模块**根本没提交**，运行时 import 即 500，SSRF 链路走不到。**但真正高危的 SSRF/越权在别处（平台代理），旧体检未覆盖。** 别再把旧体检当未办清单照抄。

---

## 1. 风险矩阵（合并去重，按严重级排序）

| ID | 标题 | 级别 | 位置 | 置信度 |
|----|------|:----:|------|:----:|
| **C-1** | 平台反向代理全链路无鉴权 + 全局共享管理员 token（未授权+越权+SSRF 三合一） | 🔴 Critical | `routes/platform_proxy.py` + `main.py:201` | 高 |
| **C-2** | 落库口令加密用硬编码默认 Fernet key（拖库即明文还原） | 🔴 Critical | `config.py:53` + `crypto.py:7` | 高（**本机实测命中**） |
| **C-3** | README + git 全历史明文泄漏 `JWT_SECRET_KEY` ⇒ 可伪造任意用户/租户 token | 🔴 Critical | `README.md:113` 等 + `auth.py:62-78` | 高（已实证可伪造） |
| **C-4** | 已提交 4 份真实 RSA 私钥进 git | 🔴 Critical | `backend/templates/cli-generated/*/https/server.key` | 高 |
| **H-1** | 本地账号口令用无盐 SHA-256（非 bcrypt/argon2） | 🟠 High | `auth.py:49-54` | 高 |
| **H-2** | `quick_db` 已登录用户可连任意主机 MySQL（认证后 SSRF + 端口探测） | 🟠 High | `routes/quick_db.py:127-188`、`db_connections.py:271` | 高 |
| **H-3** | 出站 HTTPS 全程 `verify=False`（96 处，含登录口令上行）⇒ MITM | 🟠 High | `apaas_client.py`(56)、`auth.py:399/430/451/480` 等 | 高 |
| **H-4** | 容器以 root 运行 + 挂 `docker.sock` ⇒ 逃逸即宿主 root | 🟠 High | `deploy/docker/Dockerfile`、`docker-compose.yml:58` | 高 |
| **H-5** | code-server `--auth none` 经 nginx `/ide/` 公网暴露 = RCE 即服务 | 🟠 High | `supervisord.conf:54`、`nginx.conf.example:55` | 高 |
| **H-6** | `python-jose==3.3.0` 已知 CVE（算法混淆 + JWT 炸弹 DoS） | 🟠 High | `requirements.txt:10` | 高 |
| **H-7** | `exchange_apaas_token` 依赖模块缺失 → 无鉴权端点崩 500（SSO 实际坏） | 🟠 High | `routes/auth.py:1061`、`mcp_platform.py:631` | 高 |
| **H-8** | `git/connection.py` Fernet 有硬编码 dev fallback（漏配即可解密 git token） | 🟠 High | `git/connection.py:18-22` | 高 |
| **H-9** | headless 浏览器 `/navigate` 可达任意 URL（认证后 SSRF，凭 IDE token） | 🟠 High | `routes/browser.py:123-137` | 高 |
| M-1 | `_resolve_safe` 用 `startswith` 围栏 ⇒ 兄弟工作区前缀绕过（越界读写） | 🟡 Med | `coding/tools.py:201-210` | 高 |
| M-2 | MCP 平台换 token 时校验被 `try/except` 静默吞掉（失败放行） | 🟡 Med | `mcp_platform.py:629-638` | 中 |
| M-3 | `list_users` 对 platform_admin 无租户隔离，返回全平台用户 | 🟡 Med | `routes/auth.py:2182-2197` | 高 |
| M-4 | 平台代理把拦截到的请求体写死到开发者本机路径（敏感落盘+调试残留） | 🟡 Med | `platform_proxy.py:691-731` | 高 |
| M-5 | nginx（docker+k8s）零安全响应头（无 HSTS/X-Frame-Options/CSP/nosniff） | 🟡 Med | `nginx.conf.example`、`15-configmap-nginx.yaml` | 高 |
| M-6 | 文档明文 aPaaS 生产 DB 口令 + redis 口令 + 个人 root DB 口令 | 🟡 Med | `docs/reference/coding-skills/aPaaS-后端开发指南.md:431/444` 等 | 高 |
| M-7 | DB 弱口令 `apaas:apaas2024` 作默认值散落多处部署文档/脚本 | 🟡 Med | `start.sh:23`、`config.py:41`、多份 README | 高 |
| M-8 | k8s 镜像钉死旧 tag `20260428-ruijing` + `IfNotPresent`（补丁滞后） | 🟡 Med | `deploy/k8s/30-statefulset.yaml:31/48` | 高 |
| L-1 | JWT 用 HS256 对称密钥 + 解码不验 aud/type（弱化，无 alg-confusion） | ⚪ Low | `auth.py:62-78` | 高 |
| L-2 | 路由广泛把 `str(e)` 回传客户端（信息泄露内部路径/SQL） | ⚪ Low | `coding.py`(13)、`chat.py`(7) 等 | 高 |
| L-3 | 模板 `.mdc` 内嵌已过期 aPaaS xdaptoken + 泄漏 user_id | ⚪ Low | `coding/default_rules/前端SDK-v2介绍.mdc:1185` | 高 |
| L-4 | MCP API key 校验用非常量时间 `in` 比较（时序侧信道） | ⚪ Low | `mcp_server.py:65-71` | 高 |
| L-5 | admin-spa `vite@^5.2.0` 浮动（存量 esbuild dev-server CVE，仅开发期） | ⚪ Low | `admin-spa/package.json:23` | 高 |
| L-6 | CORS `allow_credentials=True` + 固定 origin 列表（当前安全，扩展需谨慎） | ⚪ Low | `main.py:130-150` | 高 |

合计：**4 Critical · 9 High · 8 Medium · 6 Low**。

---

## 2. Critical 详情（上线阻断项）

### C-1 平台反向代理全链路无鉴权 + 全局共享管理员 token
- **位置**：`routes/platform_proxy.py:395-405`(`proxy_init`)、`651-816`(catch-all `/platform/* /backend/* /xdap-* /apaas/* ...`)、`34-40`(进程级全局 `_proxy_state`)、`619-648`(`_ensure_proxy_state` 自动回填)；`main.py:201` 无 prefix 无依赖挂载。
- **问题**：①这些路由**无任何认证依赖**，未认证者 `POST /api/platform-proxy/init {host,token,tenant_id,password}` 即可把任意目标+凭证写进进程级全局单例；②随后 `/backend/<任意 apaas 路径>` 被代理且自动注入 `xdaptoken`，借后端身份调 apaas 管理 API；③`_proxy_state` 是**跨所有用户/请求的单例**——任一租户用户开过一次 iframe（`proxy_entry` 把其绑定环境的**管理员 token + 明文密码**写入全局），随后任何人用**该管理员 token** 调 `/backend/*` 增删改其他租户数据。
- **本机实证**：E2E 启动日志出现 `Proxy state auto-recovered: host=https://apaas-trial.definesys.cn` —— 即 `_ensure_proxy_state` 在无人调用时自动捞了一个 connected 环境的凭证回填，**全局共享行为已确证**。
- **客户暴露**：高。生产 nginx 反代 `/ai-builder/api/*` 公网可达，多租户共用单后端进程 → 单例必串号。
- **修复**：给所有 proxy 路由加 `Depends(get_auth_context)`，从 JWT 取 user→tenant；删 `proxy_init` 或只接受 app_id 由服务端查环境；**废弃全局 `_proxy_state` 单例**改 per-(user,tenant)；代理目标走 PlatformEnv 白名单。

### C-2 落库口令加密用硬编码默认 Fernet key
- **位置**：`config.py:53`（`encryption_key: str = "default-key-change-in-production-32b"`，非必填、有可用默认值）+ `crypto.py:7-12`（`sha256(encryption_key)` 派生 Fernet）。用处：aPaaS 平台/后端账号口令、客户业务库连接口令、LLM api_key、git secret 全用它加密落库。
- **本机实证**：`backend/.env` 中**没有 `ENCRYPTION_KEY` 这一行**（实测 grep 确认）→ 运行时落在硬编码默认值上。
- **影响**：拿到源码（公开仓库）+ 数据库（备份/拖库）即可一行代码解出所有 `*_enc` 明文：aPaaS 管理员密码、客户生产 DB 密码、LLM key。加密形同虚设。
- **修复**：移除默认值改 required，缺失 fail-fast；部署生成随机 32B key；对存量 `*_enc` 用新 key 重加密迁移；**视所有现存被加密口令为已泄漏，连带轮换**。

### C-3 README + git 历史泄漏 JWT 签名密钥 ⇒ 可伪造任意用户
- **位置**：`README.md:106/113`、`docs/internal/PROJECT_STATUS.md`、`PROJECT_SUMMARY.md` 明文 `LLM_API_KEY=sk_PR…` 与 `JWT_SECRET_KEY=STJN…`，且在 git 全历史可 checkout（曾在 `.env.example`）。
- **影响**：HS256 对称密钥泄漏 ⇒ 任意人用该密钥本地构造合法签名的 access token（`{"sub":"1"}` 即冒充首个管理员）。`decode_token` 不验 aud/type、`get_current_user` 只按 sub 查库（`auth.py:167-191`）⇒ 无需任何前置即全站账号接管。审计已**实证伪造**一张通过校验的管理员 token。LLM key 还会被盗刷计费。
- **修复**：立即轮换两枚密钥；从 README/文档删明文改占位；`git filter-repo`/BFG 清历史；接 gitleaks/trufflehog pre-commit+CI。

### C-4 已提交真实 RSA 私钥进 git
- **位置**：`backend/templates/cli-generated/{form-layout-web,form-page-web,form-view-web,frontend-plugin-web}/https/server.key`（+ `.crt`，4 份 MD5 相同，`openssl rsa -check`=ok，证书 2026-02-26 已过期）。
- **影响**：完整可用 2048-bit RSA 私钥进仓库；由该模板生成的应用若沿用此 key，则其 TLS 私钥对全世界公开。即便仅 dev 也是硬性违规 + 坏示范。
- **修复**：从仓库与历史移除全部 `server.key/.crt`；`.gitignore` 加 `*.key/*.pem/https/`；模板改为构建/首启现场生成自签证书。

---

## 3. High 详情

- **H-1 无盐 SHA-256 口令**（`auth.py:49-54`）：单轮无盐快哈希，GPU 可秒级离线爆破，相同口令同哈希。依赖已含 `passlib[bcrypt]` 却没用。→ 迁 bcrypt/argon2，登录时透明 rehash 升级旧记录。
- **H-2 quick-db 认证后 SSRF**（`quick_db.py:127-188` / `db_connections.py:271`）：任意登录成员可让后端连任意 `host:port` 的 MySQL，错误原文回显 ⇒ 探活内网、识别服务、配弱口令拖库。SQL 本身用 `%s` 参数化（无注入），但**目标地址完全可控**。→ host 加私网/出网拒绝白名单（屏蔽 RFC1918/169.254/localhost/元数据 IP），错误脱敏。
- **H-3 verify=False（96 处）**（`apaas_client.py` 56 处 + `auth.py:399/430/451/480` 登录口令上行）：对 apaas 平台所有 HTTPS（含传输明文口令、xdaptoken）一律不验证书 ⇒ 链路 MITM 截获管理员凭证。→ 生产 `verify=<内部 CA bundle>`，集中 httpx 工厂，lint 禁散落 `verify=False`。
- **H-4 容器 root + docker.sock**（`Dockerfile` 无 `USER`；`docker-compose.yml:58` 挂 sock + `:41` host 网络）：容器内经 docker socket 可起特权容器读写宿主 = 宿主 root；叠加本应用「执行 AI 生成代码」属性，逃逸近乎无门槛。→ 加非 root `USER`、`cap_drop:[ALL]`/`no-new-privileges`/`read_only`、去 host 网络；生产改 K8s 受限 RBAC runtime 而非裸挂 sock。
- **H-5 code-server `--auth none` 公网暴露**（`supervisord.conf:54` + `nginx.conf.example:55`/`15-configmap-nginx.yaml`）：浏览器内 VS Code 自带终端+任意文件读写，nginx `/ide/` 反代前**无鉴权 gate** ⇒ 可达即 RCE，叠加 H-4 直达宿主 root。→ `/ide/` 前置 `auth_request` 校验 `ide_access` JWT（`auth.py:139` 已具签发能力）或 Basic/mTLS/IP allowlist；生产默认 `CODE_SERVER_BASE_URL` 留空禁用 Web IDE。
- **H-6 python-jose 3.3.0 CVE**（`requirements.txt:10`）：CVE-2024-33663（算法混淆）+ CVE-2024-33664（JWT 炸弹 DoS），用于全部 JWT 编解码。→ 升 3.4.0+ 或迁 `pyjwt`；同时 `passlib 1.7.4` 已停维护、`cryptography` 在 `:8/:15` 重复声明应去重。
- **H-7 exchange_apaas_token 依赖模块缺失**（`auth.py:1061` import 不存在的 `app.services.apaas_token_validator`）：无鉴权 SSO 换票端点运行时必 500 —— ①中和了旧体检的 SSRF（链路崩了走不到）；②但凡客户靠「apaas token 换 ai-builder JWT」做 SSO 接入则**功能是坏的**；③`mcp_platform.py:631` 那处被 try/except 吞掉 → token 归属校验被静默跳过（见 M-2）。→ 补回该模块（连同已写好的白名单+成员校验）或删端点，别让「无鉴权且崩溃」入口挂公网。
- **H-8 git Fernet dev fallback**（`git/connection.py:18-22`）：`BUILDER_FERNET_KEY` 缺失则回退硬编码常量，加密 git token/webhook secret ⇒ 漏配即可解密。与 C-2 同类（**第二把独立 Fernet key**）。→ 移除 fallback，缺失 fail-fast。
- **H-9 headless 浏览器 SSRF**（`browser.py:123-137`）：持 `ide_access` JWT 可让服务端 Chromium 访问任意 URL（含内网/元数据），经截图/DOM 回读。原 user/tenant 交叉校验已变死代码。→ 目标 URL 出网白名单；恢复 token↔workspace 归属校验。

---

## 4. Medium / Low（摘要）

**Medium**
- **M-1** `coding/tools.py:201-210` `_resolve_safe` 用 `startswith` 而非 `Path.relative_to`，`../oc_abc_x/secret` 可越界到同前缀兄弟工作区读写（其余路径校验都正确用了 `relative_to`）。→ 改 `relative_to`。
- **M-2** `mcp_platform.py:629-638` `validate_apaas_token` 异常被 `except: token_info=None` 吞掉，「校验 token 归属租户」被静默跳过。虽有 `_require_platform_admin` 前置，仍属「安全校验失败默默放行」危险模式。
- **M-3** `auth.py:2182-2197` `/auth/users` 在 `ctx.tenant_id` 缺失（platform_admin 无 tid）时全表返回所有 active 用户 → 用户枚举。
- **M-4** `platform_proxy.py:691-731` 残留把代理写请求 body 落盘到 `/Users/mars/...docs/captures` 的调试代码（敏感数据 + 硬编码作者路径）。→ 删除。
- **M-5** nginx 两份均零安全头（无 HSTS/X-Frame-Options/CSP/nosniff/Referrer-Policy），而本应用大量 iframe 内嵌。→ 统一 `add_header`。
- **M-6** `docs/reference/coding-skills/aPaaS-后端开发指南.md:431/444` 明文 aPaaS 生产库口令 `…applJ7XHi***` + redis `xdapredis` + 内网 IP；`docs/superpowers/plans/...:175` 个人 root 口令 `Marscaden***`。→ 清文档+轮换。
- **M-7** `apaas:apaas2024` / `root:password` 作默认 DB 口令散落 `start.sh:23`、`config.py:41`、多份部署文档，客户易照抄上生产。→ 改 `<CHANGE_ME>` + 缺 `DATABASE_URL` fail-fast。
- **M-8** `deploy/k8s/30-statefulset.yaml` 钉死旧 tag + `IfNotPresent`，安全补丁不随重启生效。→ 不可变 digest tag + 补丁流程。

**Low**：L-1 JWT HS256 不验 aud/type（但密钥 required、algorithms 单值无 alg-confusion，风险有限）；L-2 `str(e)` 广泛回传客户端；L-3 模板内嵌已过期 xdaptoken + 真实 user_id；L-4 MCP key 非常量时间比较（→`hmac.compare_digest`）；L-5 admin-spa vite5 dev-server CVE（仅开发期）；L-6 CORS 当前安全（固定白名单，未反射 Origin），仅提示扩展需谨慎。

---

## 5. 已核验为「安全 / 非问题」（避免重复排查）
- **无 SQL 注入**：全仓 `text(f"...")` 只插值硬编码表/列名，值用 `:param`/`%s` 参数化；`quick_db`/`db_connections` 直连客户库也全 `%s`。
- **zip-slip 已防**：`mcp_server.py:2824` / `coding.py` 解压有 `..` 检查 + `relative_to`。
- **命令执行非未授权 RCE**：`coding/tools.py:557` `create_subprocess_shell` 是 vibe coding 设计功能，入口受 `/api/mcp` 的 `_McpAuthMiddleware` 保护，`MCP_API_KEYS` 空时 fail-closed 拒绝。⚠️ 但生产需确认 `vibe_coding_runtime="docker"`，否则持 key 者 = 后端宿主任意命令执行。
- **git webhook**：`git/webhook.py:31-40` 用 `hmac.compare_digest` 常量时间验签。
- **路径穿越（IDE/workspace 主路径）**：`_resolve_ide_edit_path` / `_resolve_workspace_path` 用 `..`-parts + `relative_to` + 归属校验（唯一例外 M-1）。
- **大部分管理端点**：均有 `Depends(get_auth_context)` + tenant 过滤，`_require_platform_admin` 覆盖到位。

---

## 6. 交付客户前「安全加固」必办清单

**A. 立即轮换（视为已泄漏）**
1. [ ] 重置 `LLM_API_KEY` 与 `JWT_SECRET_KEY`（C-3，新 JWT 密钥强随机 ≥32B，旧 token 全失效）。
2. [ ] 生成新 `ENCRYPTION_KEY`（C-2）+ `BUILDER_FERNET_KEY`（H-8），对存量 `*_enc` 重加密；连带轮换被加密的 aPaaS 账号口令 / 外部 DB 口令。
3. [ ] 移除并重签模板 RSA 私钥（C-4）。
4. [ ] 轮换文档泄漏的 aPaaS DB 口令 `…applJ7XHi***`、redis `xdapredis`、个人 `Marscaden***`（M-6）；改默认 `apaas2024`/`root:password`（M-7）。
5. [ ] 轮换本机 `.env` 的 GitHub PAT 与 Dolphin key（纵深防御，已写入本机磁盘）。

**B. 清源 + 历史擦除**
6. [ ] 从 README / `PROJECT_STATUS.md` / `PROJECT_SUMMARY.md` / aPaaS 指南 / `.mdc` 删明文凭据改占位。
7. [ ] `git filter-repo`/BFG 清全历史密钥与私钥；强推后通知所有克隆方；`.gitignore`/`.dockerignore` 加 `*.key *.pem https/`。
8. [ ] 接 gitleaks/trufflehog pre-commit + CI 阻断。

**C. 代码加固（这些是脚本改不了、须改代码的「真·上线前必办」）**
9. [ ] **C-1**：所有 `platform_proxy` 路由加鉴权、删 `proxy_init`、废弃全局 `_proxy_state` 单例（**最高优先**）。
10. [ ] **C-2/H-8**：移除 `config.py:53`、`git/connection.py:21` 硬编码密钥默认值，缺失 fail-fast；同样处理 `DATABASE_URL` 默认口令。
11. [ ] **H-1/M-4** 口令迁 bcrypt/argon2 + 盐；删 `platform_proxy` 抓包落盘代码。
12. [ ] **H-2/H-9** quick-db / browser navigate 加私网/出网拒绝白名单 + 错误脱敏。
13. [ ] **H-3** 取消全局 `verify=False`，改内网 CA bundle。
14. [ ] **H-6/L-5** 升 `python-jose`→3.4+（或迁 pyjwt）、`vite@5`→修订版、去 `cryptography` 重复 pin，跑 `pip-audit`+`npm audit` 入 CI。
15. [ ] **L-1** `decode_token` 校验 `iss/aud/type`；`get_current_user` 拒非 access 票。
16. [ ] **H-7** 补回或删除 `exchange_apaas_token` 端点。

**D. 部署面加固（已并入部署脚本/前置要求，见 [部署前置要求](部署前置要求.md)）**
17. [ ] Dockerfile 非 root `USER` + compose `cap_drop`/`no-new-privileges`/去 host 网络（H-4）。
18. [ ] 生产默认禁用 Web IDE；启用则 `/ide/` 前置鉴权 + code-server `--auth password`（H-5）。
19. [ ] nginx 补 HSTS/X-Frame-Options/nosniff/CSP/Referrer-Policy（M-5）。
20. [ ] k8s 镜像钉不可变 digest + 补丁流程（M-8）；确认不用 Vibe 时 `VIBE_CODING_RUNTIME=host` 去 docker.sock。

---

## 7. 需你确认的 3 个部署事实（决定真实暴露评级）
1. **`ENCRYPTION_KEY`/`JWT_SECRET_KEY` 是否生产设了非默认高熵值** —— 本机 `.env` 实测 `ENCRYPTION_KEY` **未设**（C-2 命中）；`JWT_SECRET_KEY` 已设但需确认不是 README 那枚泄漏值。
2. **`vibe_coding_runtime` 是否 `"docker"`** —— 否则持 MCP_API_KEY 者 = 宿主 RCE（本机 `.env` 未显式设，默认 `auto`）。
3. **生产 nginx 是否在边缘对 `/platform`、`/backend`、`/api/platform-proxy/*` 额外鉴权** —— 若有可降 C-1 暴露评级，但 `/api/platform-proxy/init` 必经 `/api` 前缀仍可达。

> **审计边界**：未运行 `pip-audit`/`npm audit`（不改环境），依赖 CVE 结论基于版本号 + 公开 CVE 知识（截至 2026-01），交付前请以实际审计输出为准。
