# 桌面版近场硬伤加固设计（撤加密旁路 + 引导式 onboarding + 本地签票信任边界）

- 日期: 2026-06-17
- 分支: `feat/desktop-login-mvp`（含未并 dev 的桌面登录/account-service/自动更新工作）
- 关联背景: [[desktop_delivery_cockpit_2026_06_16]]、[[desktop_auto_update_2026_06_16]]
- 来源: 2026-06-17「睿鲸 Builder 桌面版 vs Claude Code desktop vs 腾讯 WorkBuddy」竞品对比的结论——桌面壳工程成熟，但压着几个会让用户「装上就卡死/不安全」的近场硬伤，须先于护城河（交付驾驶舱）清理。

## 背景与动机

桌面版当前是把在线 ai-builder（智能配置 + 二次开发）整壳进 Tauri + Python sidecar。登录、自动更新、account-service 都已成型，但三件近场硬伤未清：

1. **加密旁路**: `backend/desktop_sidecar.py:40` 主动注入 `ALLOW_DEFAULT_ENCRYPTION_KEY=1`，把 `backend/app/main.py:59` 的「默认加密 key 拒绝启动」安全门旁路掉。结果：当前所有 aPaaS/LLM 凭据用仓库默认 Fernet key（`config.py:63`）加密 = 等同明文，不安全。注释自承「Phase 0 spike，Phase 1 改」。
2. **空库 onboarding 缺失**: 用户装完 .app 首次打开是空本地 SQLite——无 aPaaS 环境、无 LLM 模型、无应用。没有任何引导把用户带过「连 aPaaS → 配模型 → 验证」这条路。这是最先发生、最致命的采用杀手。（更正既往判断：LLM/aPaaS 配置写权限已下放到 `require_tenant_admin`，见 `llm_configs.py:195`、`platform_envs.py:52`；federation 桌面号本就是自己租户的 tenant_admin，`desktop_accounts.py:50`。所以这不是权限墙，是纯 UX 缺口。）
3. **本地签票信任边界靠约定**: federation 镜像账号权限本地派生、本地未验证；谁控制 sidecar 进程谁能本机自提权并签票。当前 authority/federation 的 `is_platform_admin` 差异靠手动约定（`desktop_accounts.py:33` 注释），且 authority 票与本地 federation 票共用同一 issuer `"ai-builder"`（`auth.py:131`），共享后端分不出本地票。破防即跨租户提权，是会毁掉整个安全叙事的单点。

## 范围

三个工作块（互相独立，可分别实现/测试）：

- Part 1 — 撤加密旁路 + 每实例持久化加密密钥
- Part 2 — 引导式 onboarding 向导 + 桌面功能边界系统梳理
- Part 3 — 本地签票信任边界：票据 issuer 标记 + 共享后端拒收 + 开号权限启动断言

### 非目标（本轮明确不做）

- 交付驾驶舱差异化层（脊柱/模板/技能/知识库）——下一轮护城河工作。
- Apple 代码签名 + 公证、revocation 短 TTL/心跳——同属 P0/P1 但独立成轮（卡在买证 / 改动面不同）。
- 企业纳管（SSO/SCIM/组织层级/MDM 批量分发）、沙箱、Windows——远期。
- 重写 admin-ui（916 行内嵌 HTML）——不在本轮。

---

## Part 1 — 撤加密旁路 + 持久化加密密钥

### 设计

在 `backend/desktop_sidecar.py` 新增 `ensure_encryption_key(data_dir) -> str`，完全照搬同文件 `ensure_jwt_secret` 的范式：

- 首次启动用 `cryptography.fernet.Fernet.generate_key().decode()` 生成一个合法 Fernet key（44 字符 urlsafe base64），写入 `data_dir/encryption_key`，`chmod(0o600)`。
- 之后启动复用该文件。

`build_env` 改动：

- 新增 `"ENCRYPTION_KEY": ensure_encryption_key(data_dir)`。
- **删除** `"ALLOW_DEFAULT_ENCRYPTION_KEY": "1"` 这一行。

效果：`main.py:59` 的安全门此后是「检测到真实 key、合法放行」，而非被旁路。凭据用每实例独立持久化 key 加密。

### 迁移

- 全新安装：无历史数据，无影响。
- 既有 dogfood 实例（mars 那台）: 旧凭据用默认 key 加密，换 key 后 Fernet 解密失败。处理方式 = 用户在 onboarding 向导/配置页重新填一次 aPaaS/LLM 凭据（既有共识：当前凭据均为 throwaway）。不做自动迁移。需在实现里确认：解密失败时是否优雅降级为「凭据需重配」而非 500——若现状会 500，补一个 try/except 把解密失败转成可读的「请重新配置」状态。

### 测试

- `ensure_encryption_key`: 首次生成合法 Fernet key + 持久化 + 0o600；二次启动复用同值。
- `build_env`: 不再含 `ALLOW_DEFAULT_ENCRYPTION_KEY`；含合法 `ENCRYPTION_KEY`。
- 集成: 用 `build_env` 注入的 env 起 app，能越过 `main.py:59` 加密门启动（用真实 key，非默认）。

---

## Part 2 — 引导式 onboarding 向导 + 桌面功能边界梳理

### 2a 首次启动向导

**触发**: 桌面登录后（`DesktopLogin.vue` 现 redirect 到 `/`），加一道 first-run 检查：当前租户「无任何已连 aPaaS 环境」或「无任何可用 LLM 配置」→ 进向导。

**first-run 状态检测**: 优先复用现成 list 接口（`GET /api/platform-envs` + `GET /api/llm-configs`，两者为空即首启），不新增后端端点。若复用接口的返回粒度不足以判断「是否首启」，再评估加一个极小的只读 `GET /api/desktop/onboarding-state`（仅返两个布尔），但默认走复用。

**向导**: 新增桌面专属 `frontend/src/views/DesktopSetupWizard.vue`（`__DESKTOP__` 门控，在线 build tree-shake），三步，全部复用现成 `platform_envs` / `llm_configs` 接口、不重建后端表单逻辑：

1. 连 aPaaS 环境：填环境名/地址/账密 → 调创建 → 实测连通反馈成功/失败。
2. 配 LLM 令牌：provider 选 Dolphin（自动预填地址 + gpt-5.5）→ 填 omnigate 令牌 → 实测。
3. 完成 → 进主界面。

**跳过路径**: 允许「稍后配置」，但落到一个明确的引导空状态（见 2b 的降级页风格），而非把用户丢进白屏主界面。

**实现要点**: 用路由守卫（router beforeEach，仅 `__DESKTOP__`）做 first-run 分流，避免在每个业务页里塞判断。向导是「半强制」——不配齐 aPaaS+LLM 之前，两条主业务线（智能配置/二次开发）入口给禁用态 + 指回向导。

### 2b 桌面功能边界系统梳理

**问题**: 桌面壳复用在线版 Vue 产物，但在线版有一批功能依赖「没打包的 admin-spa」或「在线 pod」，在桌面是死链/白屏（如 `/platform-admin` 内嵌 admin-spa iframe，现靠 `RailSidebar.vue:35` 改指 `/platform-envs` 绕过）。这类绕过是零散贴膏药，缺一个明确的「桌面功能子集」定义。

**设计**:

1. **枚举与分类**（放进实施计划做）: 遍历 `frontend/src/router` 全部路由 + `RailSidebar`/导航项，逐条分类——`desktop-ok` / `needs-admin-spa`（未打包） / `needs-online-pod`（在线运行时）。产出一张清单。
2. **单一来源收敛**: 用路由 `meta`（如 `meta.desktop: 'ok' | 'hidden' | 'degraded'`）作为桌面可用性的唯一声明，取代散落的 `__DESKTOP__` 判断。导航项可见性、路由守卫都读这个 meta。
3. **守卫与降级**: 桌面 build 下，`hidden` 的导航项不渲染；任何漏网深链到 `hidden`/`degraded` 路由 → 落统一的「此功能在桌面版不可用」降级页（说明原因 + 回主界面），杜绝白屏。
4. 复核既有的 `RailSidebar.vue:35` 等绕过点，归一到 meta 机制。

### 测试

- first-run 守卫: 空租户（无 env / 无 llm）登录 → 路由进向导；已配齐 → 直进主界面。
- 向导三步: 各步调用对应现成接口、实测反馈分支（成功/失败）。
- 功能边界: `meta.desktop='hidden'` 的路由在桌面 build 下导航不可见 + 深链落降级页；在线 build 下不受影响（meta 仅桌面读取）。

---

## Part 3 — 本地签票信任边界

### 设计

**票据 issuer 标记**: 当前 `auth.py` 所有票 `iss=_ISSUER="ai-builder"`（`auth.py:131` 等）。改造 federation 本地签发路径（`desktop_auth.py` 的 `_federation_login` → 本地 `create_access_token`），使本地签的票带独立 issuer，如 `iss="desktop-sidecar"`。

实现方式：给 `create_access_token`（或本地签发封装）加一个可选 `issuer` 参数，federation 本地签发传 `"desktop-sidecar"`；authority 签发与在线主后端仍用 `"ai-builder"`。

**共享后端拒收**: 在线主后端 + account-service 的 `decode_token`（`auth.py:81`）加 issuer 校验——只接受自身签发的 issuer（`"ai-builder"`），显式拒掉 `"desktop-sidecar"` 的票。桌面 sidecar 进程则接受 `"desktop-sidecar"`（它自己签的本地票）。

- 这是在「密钥本就分离」（sidecar 用每实例 `JWT_SECRET_KEY`，account-service 用 `ACCOUNT_SERVICE_JWT_SECRET`）之上的第二道防线：即使哪天密钥被误配成共享，issuer 也兜得住。
- 接受/拒收哪些 issuer 由部署侧配置驱动（如 `accepted_token_issuers`），桌面 sidecar 与在线/account-service 取不同值，避免硬编码漂移。

**开号权限启动断言**:

1. `provision_desktop_account` 已默认 `is_platform_admin=False`（`desktop_accounts.py:27`）。改造使 federation 镜像开号（`desktop_auth.py:63`）和公网 `admin/accounts` 路径**结构上不可能**传入 `True`——用专用变体函数（如 `provision_federation_mirror_account` 内部硬编码 False）或入口处断言，而非依赖调用方记得不传。
2. sidecar 启动断言: federation 模式下，启动时校验「本地票 issuer 配置 + 共享后端拒收配置」就位（如本地 issuer 非 `"ai-builder"`、accepted_issuers 配置自洽），配错 fail fast，而非静默带病运行。

### 信任边界铁律（写入代码注释/契约）

> 本地 sidecar 签发的票（`iss="desktop-sidecar"`）绝不可被任何共享后端（在线主后端 / account-service）接受。federation 镜像账号权限本地派生、本地未验证，`is_platform_admin` 绝不跨 federation 传递。

### 测试

- federation 本地签发的票 `iss="desktop-sidecar"`；authority 签发的票 `iss="ai-builder"`。
- 在线主后端 / account-service `decode_token` 拒收 `iss="desktop-sidecar"` 的票（即使签名/密钥碰巧能过也拒）。
- 桌面 sidecar 接受 `iss="desktop-sidecar"` 的本地票。
- federation 镜像开号 + 公网 admin/accounts 无法产出 `is_platform_admin=True` 账号（结构性，不靠默认）。
- sidecar 启动断言: issuer/accepted 配置错配时 fail fast。

---

## 排期与依赖

- 建议顺序: **Part 1 + Part 3 先做**（后端/安全、改动小，Part 1 解锁正式凭据可用、Part 3 守安全单点），**Part 2 前端为主可并行**。
- Part 1 与 Part 2 的迁移衔接: Part 1 换 key 后旧凭据失效 → 正好由 Part 2 的向导/配置页重新填，二者协同。
- 分支: 全部落在 `feat/desktop-login-mvp`。该分支有未提交/未并 dev 的桌面工作；实施时只动本设计相关文件，不扫入无关未提交改动。
- 验证手段（可复用）: WKWebView 连不上调试器，但用 chrome-devtools/playwright MCP 连 `http://127.0.0.1:<sidecar端口>/` 可真实渲染验证桌面前端（`__DESKTOP__` 已编译进 JS）。重打包 `scripts/build-desktop.sh`（~85s），重打包前先 `pkill -f "Builder.app/Contents/MacOS"` 释放 app.db。

## 风险

- 改 `decode_token` 加 issuer 校验：须确认不误伤现有在线/aPaaS 登录链路的票（它们都是 `"ai-builder"`，应不受影响，但要全量测试过一遍 auth 相关用例）。
- 路由 `meta.desktop` 机制改造面较广（触多个路由/导航点）：按 grep 验证完整性，避免漏标导致桌面误隐藏可用功能或误暴露死链。
- `ensure_encryption_key` 之后旧 dogfood 库凭据解密失败：须确认降级为「请重配」而非 500（见 Part 1 迁移）。
