# 桌面产品登录模块 + 混合架构（公网账号 + 本地开发）— 设计文档

- 日期：2026-06-16
- 状态：brainstorming 已对齐，待写实现计划
- 关系：本文修订 `2026-06-16-desktop-delivery-cockpit-design.md` 里「桌面单机单用户、本地会话」那段旧假设（决策 D5/认证简化那条），是 Phase 1「桌面底座成型」下的一个子项目。Phase 0 打包 spike（Tauri 壳 + 本地 sidecar）成果保留、角色收窄。

## 1. 背景与要解决的问题

Phase 0 把 ai-builder 打成了能双击运行的 macOS 桌面应用，但它沿用了在线版的登录页——「请输入 aPaaS 账号/密码」。这是**错的**：那是低代码平台(aPaaS)的账号，不该用来登录这个桌面产品。

用户要的是**两个互不相干的身份层**：

- **第一层｜桌面产品登录**：「你是否有权打开这个 ai-builder desktop」。是产品自己的账号体系，跟 aPaaS 毫无关系。**这是本设计要新建的「单独登录模块」。**
- **第二层｜连 aPaaS 环境**：登录之后，每人配「这个项目要连哪个客户的 aPaaS、用什么 aPaaS 凭据」——即现有的 `platform_envs`（PlatformEnv）。aPaaS 账号只在这一层、是「连接信息」，不是「登录」。

类比腾讯 WorkBuddy：桌面客户端 + 云端服务。要有产品账号体系就得有个公网中心服务托管身份——复用现成的 **agent.dfy.definesys.cn**（dev 环境的 ai-builder 部署）作为这个公网账号权威。

## 2. 关键决策

| 编号 | 决策 | 理由 |
|---|---|---|
| L1 | **两层身份彻底分离**：产品登录 ≠ aPaaS 登录 | aPaaS 账号降级为「连接信息」，在 platform_envs 配；产品登录是独立的门。 |
| L2 | **混合架构**：公网 agent.dfy 管账号/身份，本地 sidecar 管二次开发 | 用户决策。Phase 0 sidecar 保留、角色收窄为本地开发。 |
| L3 | **接线 = 方案一**：本地 sidecar 当 WebView 同源前门，登录请求由 sidecar 服务端转发到公网认证 | 避开浏览器「https 公网页面直连 http://127.0.0.1」的混合内容拦截；保住 Phase 0 同源；UX 连贯。 |
| L4 | **公网账号权威 = agent.dfy** | 用户指定复用 dev 部署。⚠️dev 环境当(内部)产品账号权威先用，正式对外再换正式公网环境。 |
| L5 | **登录凭据 = 账号/邮箱 + 密码，provider 可插拔** | 先做最简单、不依赖第三方；以后加钉钉/企微 SSO 只是多一个 provider，不返工。钉钉登录**非必须**。 |
| L6 | **账号来源 = 管理员在公网后台开账号发给交付同事** | 控制严、适合内部。无自助注册。 |
| L7 | **智能配置在本地 sidecar 跑**（用公网同步来的 aPaaS 环境配置直连客户 aPaaS）；公网只存账号 + 加密的 aPaaS 环境配置 + 协同元数据 | 兑现「数据隔离」——客户 aPaaS 数据不流经中心公网服务器。 |

## 3. 架构

```
┌──────────────────── macOS 桌面 (Tauri 壳, Phase 0) ──────────────────┐
│  WebView ── 同源 ──▶ 本地 sidecar (FastAPI, 127.0.0.1:<port>)          │
│  (Vue 前端)          │                                                 │
│                      ├─ 本地: 二次开发工作区 / 文件 / 命令 / 智能配置    │
│                      │   (智能配置直连客户 aPaaS, 用同步来的 env 配置)   │
│                      │                                                 │
│                      └─ 联邦层(新增): server-to-server 调公网            │
│                          ├─ 登录认证 (转发凭据/换 token)                 │
│                          ├─ 拉取本用户的 aPaaS 环境配置(platform_envs)   │
│                          └─ 协同/账号元数据                              │
└───────────────────────────────────┬──────────────────────────────────┘
                                     │ https (server-to-server, 无 CORS/混合内容)
                                     ▼
                  公网 agent.dfy.definesys.cn (ai-builder 部署)
                  ├─ 桌面产品账号体系(新): user/credential, 管理员开号
                  ├─ 登录/token API (provider 可插拔: 密码 / 未来 SSO)
                  ├─ 每用户 aPaaS 环境配置存储(platform_envs, 加密)
                  └─ (后续) 协同 / 模板 / 知识 共享层
                                     │
                                     ▼ (智能配置时, 由本地 sidecar 直连)
                           客户的 aPaaS 环境(per platform_env)
```

要点：
- **WebView 永远只跟 localhost 同源说话**（Phase 0 不变）→ 零 CORS/混合内容。
- **sidecar 新增「联邦层」**：服务端转发到公网做认证、拉配置。客户端永远拿不到公网密钥/直连公网。
- **二次开发 + 智能配置在本地跑**；公网是账号权威 + 配置存储 + (后续)协同。

## 4. 单独登录模块（核心交付物）

### 4.1 公网侧：桌面产品账号体系
- 在 agent.dfy 的 ai-builder 后端新增/启用一套**桌面产品账号**：独立 user 表/标识（或复用现有 `User` + 一个 `account_type=desktop` 区分，避免与 aPaaS-derived user 混淆——实现时定）。**与 aPaaS 登录链路（`_try_apaas_login_flow`）完全分开**。
- **登录 API**（provider 可插拔）：`POST /api/desktop-auth/login`（账号+密码）→ 校验 → 签发**桌面产品 token**（JWT，载 user_id + 标识这是 desktop 产品身份）。Provider 接口预留，未来加 `desktop-auth/sso/dingtalk` 等只是新增实现。
- **管理员开号**（L6）：公网后台一个最小管理界面/接口，管理员创建桌面账号（账号/邮箱 + 初始密码）、停用、改密。无自助注册。
- 不碰、不复用 aPaaS 的 `/login` 流程。

### 4.2 本地侧：登录界面 + 联邦
- 桌面前端**新增独立登录页**（替掉现在的 aPaaS 账密登录页）：账号 + 密码 + 登录。
- 登录时：前端 → 本地 sidecar `POST /api/desktop-auth/login` → sidecar **服务端转发**到 agent.dfy 的 `/api/desktop-auth/login` → 拿到公网签发的桌面 token → sidecar 落本地会话（与本地 sidecar 自己的 JWT 体系桥接，用于后续本地 API 鉴权）→ 前端进入应用。
- 登录后：sidecar 用桌面 token 向公网拉该用户的 aPaaS 环境配置，落本地供智能配置/二次开发用。

### 4.3 会话与离线
- sidecar 持有公网签发的桌面 token + 派生的本地会话。
- **离线考虑**（原驱动之一「弱网现场可用」）：登录必须联公网；但登录成功后缓存会话，**在 TTL 内允许离线做本地二次开发**（不需要每次联公网）。智能配置/拉新 aPaaS 配置仍需联网（本就要连客户 aPaaS）。TTL/刷新策略实现时定。

## 5. 登录后：连 aPaaS 环境（第二层，已存在）
- 进应用后，用户用现有 **platform_envs UI** 配「要连的客户 aPaaS 环境」（base_url / platform_tenant_id / aPaaS 账密，加密存）。
- 这些配置**存在公网**（与账号绑定，换机可同步），由 sidecar 拉到本地，智能配置/二次开发时本地直连客户 aPaaS（L7，数据不过公网）。

## 6. 改动面 / 不动面
- **替掉**：桌面前端的 aPaaS 账密登录页 → 新的产品登录页。
- **新增**：公网桌面账号体系 + 登录/管理员开号 API；本地 sidecar 联邦层 + desktop-auth 路由 + 登录页；aPaaS 环境配置的公网存储+本地同步。
- **不动**：在线版（agent.dfy 的 web 入口）保留原有 aPaaS 登录链路（在线版用户照旧）；platform_envs 的配置 UI 复用；Phase 0 的 Tauri 壳 + sidecar 打包不变。

## 7. 拆分与分期（建议）
- **SP-A（MVP 必需）**：公网桌面账号体系 + 管理员开号 + `/desktop-auth/login` 签 token。
- **SP-B（MVP 必需）**：本地 sidecar 联邦层 + desktop-auth 路由（转发认证、桥接本地会话）。
- **SP-C（MVP 必需）**：桌面前端新登录页，替掉 aPaaS 登录页。
- **SP-D（次步）**：aPaaS 环境配置的公网存储 + 本地同步（MVP 可先让 platform_envs 仍本地存，登录打通后再做同步）。
- **SP-E（后续）**：离线会话 TTL/刷新；SSO provider（钉钉/企微）；协同/模板/知识共享层。
- **MVP = SP-A + SP-B + SP-C**：管理员开个号 → 桌面用新登录页登录(经 sidecar 联邦到 agent.dfy 认证)成功 → 进入应用 → 现有 platform_envs 配 aPaaS 能用。

## 8. 开放问题 / 风险（留待实现计划 / 后续拍板）
- **公网账号模型实现**：新建独立表，还是复用 `User` 加类型字段区分 desktop vs aPaaS-derived？(实现时定；务必不与 aPaaS 登录链路纠缠)
- **token 桥接**：公网桌面 token 与本地 sidecar JWT 如何桥接（sidecar 校验公网 token 后另签本地短 token，还是直接信任公网 token）——安全 + 简单的折中。
- **agent.dfy 是 dev 环境**：当(内部)产品账号权威先用；正式对外前需切正式公网环境 + HTTPS 证书 + 账号数据迁移策略。
- **公网账号体系与现有 tenant 模型的关系**：每个桌面用户对应一个独立 tenant（前述决策「每人独立工作空间」），账号创建时同步建 tenant。
- **离线 TTL**：多长、如何刷新、过期后体验。
- **管理员开号界面**：公网后台现有 admin-spa 能否承载，还是新加最小页面。

## 下一步
SP-A + SP-B + SP-C（MVP）走 writing-plans 出实现计划：先让「管理员开号 → 桌面新登录页 → 经 sidecar 联邦到 agent.dfy 认证 → 进应用」这条最小链路跑通。
