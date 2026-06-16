# 睿鲸 AI Builder 桌面交付驾驶舱 — 程序级设计文档

- 日期：2026-06-16
- 状态：已通过 brainstorming 评审，待落实现计划
- 作者：大明哥 + Claude
- 范围：这是一份**程序级（program-level）**设计文档，定愿景、架构、拆分与分期。每个子项目（Phase）后续各自走独立的 spec → plan → 实现循环。

---

## 1. 背景与动机

ai-builder（睿鲸 AI）当前是**在线版**的低代码平台，核心能力是「智能配置」+「智能开发（二次开发）」，本质是一个面向远端 aPaaS 平台 + LLM 网关的厚客户端。

我们要做一个 **desktop 版本**，目的有两层：

1. **统一交付工具**：在把 ai-builder 卖给客户之前，先让交付团队所有交付都用这个工具。现状是大家各自用 codex / cc 做交付提效，**动作不一、标准不一**。
2. **沉淀交付标准**：把项目交付过程必须的交付物做成模板放进工具，统一交付动作。

桌面化要解决的痛点（4 个动机全部成立，无单一优先）：

- **分发统一 / 开箱即用**：团队像装 codex/cc 一样装一个原生应用，不用各自配 Python/Node/数据库环境，版本统一好升级。
- **本地代码 + 命令能力**：二次开发要直接读写本机工作区、跑构建/git/命令，桌面比浏览器顺。
- **数据与环境隔离**：每个客户交付彼此独立，客户数据/代码不经过中心服务器，满足安全合规、方便驻场。
- **离线 / 弱网现场可用**：除 aPaaS / LLM 这种必须联网的部分外，工具本身与交付物模板能本地跑。

> 架构事实（已和决策人确认）：desktop 不能让 ai-builder 变成纯离线工具——低代码配置和二次开发最终都在改远端 aPaaS 租户上的东西。aPaaS 与 LLM 是**必须联网**的外部依赖，其余一律本地化。

## 2. 目标与非目标

### 目标

- 现有 ai-builder 的低代码配置 + 二次开发能力，在 macOS 上以原生应用形态运行，连客户自己的 aPaaS + LLM。
- 在其上叠一层**交付标准化模块**：交付项目模型 + 阶段闸口 + 交付物模板引擎 + AI 动作技能库 + 知识/最佳实践库。
- 内部先 dogfood（团队全员切过来用），再产品化对外卖给客户的实施团队。

### 非目标（本程序明确不做 / 暂不做）

- **不重写低代码引擎**。配置 + 二次开发 + agent 循环是皇冠宝石，桌面化是「在外面套壳 + 在上面叠层」，引擎零改写。
- **Windows 暂不做**。先只做 macOS 版（见决策 D2）。
- 不在交付层一期就上向量库 / 复杂 RAG（知识库先做简单检索/引用）。
- 不替换或重新设计 aPaaS 平台本身。

## 3. 关键决策（含理由）

| 编号 | 决策 | 理由 |
|---|---|---|
| D1 | **打包技术 = Tauri（Rust 壳，系统 WebView）+ Python sidecar** | 为对外卖的精致度与安装包体积。Python 后端作为本地 sidecar 这块两条路都一样，区别只在壳。 |
| D2 | **先只做 macOS 版**，Windows 后置 | 砍掉跨平台打包这根最大长板的一半：只面对 WKWebView、只用 PyInstaller 打 macOS、只做 Apple 公证/Developer ID 签名、Tauri 只出 `.app`/`.dmg`。 |
| D3 | **复用现有 codebase**，交付层作为同仓新模块；桌面是一个新的打包目标 | 不 fork、不另起仓库，避免维护翻倍与漂移。引擎零改写。 |
| D4 | **桌面版本身也是可卖产品** | 除自用外，未来作为「交付/实施工具」卖给客户的实施团队。因此授权、自动更新、品牌化、客户隔离要纳入设计（产品化阶段 Phase 5）。 |
| D5 | **本机工作区 + 原生执行**，替掉在线版的 pod-per-workspace / code-server | 桌面上工作区落用户本机，sidecar 直接做文件/命令操作，用已有的原生文件树/viewer/diff UI。兑现「本地代码+命令能力」。 |
| D6 | **标准交付阶段 = 7 个**：调研 → 设计 → 配置 → 开发 → 测试 → 验收 → 上线 | 作为内置「睿鲸标准交付」，可裁剪。 |
| D7 | **阶段闸口默认软门**，关键检查项可在模板里标成硬门 | 硬门一刀切会逼工程师绕开工具，毁掉「全员用它」的目标；标准化价值先靠可见性拿，关键节点再上硬门。 |
| D8 | **bring-your-own aPaaS + LLM，全部在应用内 UI 配置(存本地 DB，不写 env 文件)** | 复用在线版已有的 `platform_envs`(`PlatformEnv` 表，含加密 `password_enc`/`token`)与 `llm_configs`(`LLMConfig` 表，含加密 `api_key_enc`)。已核实低代码流程运行时 100% 从 DB 取连接(`apaas_session._get_apaas_client` / `agent._resolve_llm_config`)，不读 env。桌面 boot 不带任何 aPaaS/LLM env → local-only 登录 → 应用内配 aPaaS 环境(账密换 token) + LLM。卖出去的副本天然连客户自己的 aPaaS/LLM；数据/环境隔离。 |
| D9 | **桌面应用品牌 = 「睿鲸 Builder」** | 与在线版同源、便于品牌延续。 |
| D10 | **Phase 0 验证环境 = trial 环境 + mars 租户** | 用户指定；连通性/登录/一次低代码配置都在此验证（连接细节 Phase 0 落地时确认）。 |

## 4. 架构

### 4.1 地基层（桌面底座）

```
┌─────────────────────────────────────────────────────────┐
│  Tauri 壳 (Rust, macOS, WKWebView)                        │
│  - 启动时拉起 Python sidecar，传 端口 / 数据目录 / 工作区根   │
│  - WebView 加载内置 Vue 构建产物                            │
│  - 自动更新 (Tauri updater, 签名发布)                       │
│                                                           │
│   ┌──────────────────┐      ┌──────────────────────────┐ │
│   │ WebView           │ HTTP │ Python sidecar            │ │
│   │ (Vue3 + Element)  │─────▶│ (PyInstaller 打包的        │ │
│   │ http://127.0.0.1: │ /api │  FastAPI app, uvicorn)    │ │
│   │   <port>/api      │      │  - 本地 SQLite (aiosqlite) │ │
│   └──────────────────┘      │  - 本机文件/命令操作         │ │
│                             │  - in-process MCP servers  │ │
│                             └─────────┬────────────────┘ │
└───────────────────────────────────────┼──────────────────┘
                                         │ 必须联网
                          ┌──────────────┴───────────────┐
                          ▼                              ▼
                  远端客户 aPaaS 平台              LLM provider/网关
                  (per-profile 配置)              (bring-your-own)
```

要点：

- **进程模型**：Tauri 启动时 spawn 打包好的 Python sidecar（PyInstaller 把 FastAPI app 打成单体），sidecar 在本地随机端口跑 uvicorn；端口 / 本地数据目录 / 工作区根目录通过参数/环境变量传入。前端照旧打 `http://127.0.0.1:<port>/api`，前后端通信几乎不改。
- **本地数据**：SQLite（已支持 aiosqlite），放 macOS 应用数据目录（如 `~/Library/Application Support/RuijingBuilder/`）。不带 MySQL。
- **本机工作区**：二次开发工作区落用户本机（如 `~/睿鲸交付/<项目>/workspace`），sidecar 直接做文件/命令操作。用已有原生文件树/viewer/diff，替掉在线版 pod/code-server。
- **联网依赖**：按「交付 profile」配置（aPaaS 地址+凭据、LLM provider/base/key），本地加密存。
- **裁依赖**：playwright 改可选/惰性（当前仅 `backend/app/coding/browser_service.py` 一个文件用到）、删 kubernetes_asyncio（app 内零引用，vibe_coding 删后已死）、去 code-server 依赖。sidecar 更轻。
- **认证简化**：在线版的 JWT/租户/aPaaS token 交换体系，桌面是单机单用户，简化为本地会话 + 仍需保留的 aPaaS token 交换（调 aPaaS 必须）。
- **自动更新**：Tauri updater，签名发布。

### 4.2 交付层

脊柱是骨架，模板产出挂在阶段下，技能是阶段里可执行的标准动作，知识库给模板和技能喂上下文与可复用资产。全部 agent 动作经 `run_agent` + 已有 observability（agent_run / agent_step）落账，使「统一交付动作」可审计、可复盘。

**(a) 交付项目 + 阶段闸口（脊柱）**

- 「交付项目」= 工程师每个客户项目建的顶层容器，挂：客户/行业/周期、一个 aPaaS 环境 profile、一个本机工作区、标准交付阶段实例、各阶段产出物、全部 agent 动作 trace。
- 与现有 `projects` / `applications` 实体的关系在脊柱子项目 spec 阶段对齐（交付项目可能 wrap/extend 现有 project 概念，不在本程序文档过度设计）。
- 标准阶段（D6）：调研 → 设计 → 配置 → 开发 → 测试 → 验收 → 上线。每阶段一组检查项，部分检查项绑定**必需产出物**。闸口默认软门，关键项可标硬门（D7）。阶段模板内置「睿鲸标准交付」一套，团队/客户可裁剪。

**(b) 交付物模板引擎**

- 模板 = 结构化文档定义（章节 + 每章的生成指令/数据来源）。
- 能力：从模板库挂模板到阶段 → 一键基于项目上下文（aPaaS 应用配置/数据模型/需求记录/工作区代码）调**已有的文档生成 agent** 生成初稿 → 人工编辑（复用现有 edit_artifact / read_artifact）→ 导出 docx/pdf/md（python-docx / python-pptx 依赖已在）。
- 模板可被团队定制后沉淀回库。

**(c) AI 动作标准化（技能库）**

- 把交付常见动作固化成「交付技能」：每个技能 = 一个命名的标准 agent 指令 + 可用工具集 + 期望产出。例：「根据需求建数据模型」「生成测试用例」「生成验收报告」「配置合规检查」。
- 按阶段挂载，人人点同一个按钮跑同一套，取代各自手敲 codex/cc prompt。复用 `run_agent` + skills/MCP 基建。技能可版本化、团队共享。
- 这是直接对治「动作不一」。

**(d) 知识 / 最佳实践库**

- 可复用配置片段、行业方案骨架、踩坑/规范条目。
- 模板生成与技能执行时可检索知识库作上下文（先做简单检索/引用，不上向量库）。

## 5. 拆分（6 个子项目）

| 子项目 | 内容 | 对应 Phase |
|---|---|---|
| SP1 桌面底座/打包 | Tauri(macOS) 壳 + Python sidecar + 本地 SQLite + 本机工作区 + profile 配置 + sidecar 生命周期 + 裁依赖 + 打包/签名 + 自动更新骨架 | Phase 0（spike）+ Phase 1 |
| SP2 交付项目模型 + 阶段闸口 | 脊柱实体 + 标准阶段 + 检查项 + 软/硬门 + trace 接入 | Phase 2 |
| SP3 交付物模板引擎 | 模板库 + 一键基于项目上下文生成 + 编辑 + 导出 | Phase 2（最小集）→ 持续 |
| SP4 AI 动作标准化（技能库） | 把 codex/cc 动作收敛成内置交付技能，按阶段挂 | Phase 3 |
| SP5 知识/最佳实践库 | 可复用片段/方案骨架/踩坑，检索喂上下文 | Phase 4 |
| SP6 产品化对外卖 | 授权、自动更新加固、品牌化、客户隔离、onboarding、定价打包 | Phase 5 |

## 6. 分期（dogfood 优先，再产品化）

- **Phase 0 ｜打包 spike**（先打最大风险那根桩）：最小验证 Tauri(macOS) + PyInstaller 打 FastAPI sidecar + WKWebView 加载 Vue，连真实 aPaaS/LLM（**trial 环境 + mars 租户**）跑通登录 + 一次低代码配置。不碰交付层。**本地自签即可，无需 Apple 开发者账号。产出：一个能双击跑的 `.app`，证明地基成立。**
- **Phase 1 ｜桌面底座成型**（= 在线版的桌面化，团队可内部用）：补本地 SQLite、本机工作区、profile 配置、sidecar 生命周期、裁依赖、基础打包/签名。**产出：团队能用桌面版做现有低代码配置 + 二次开发。**
- **Phase 2 ｜脊柱 + 最小交付闭环**（交付层首次落地）：交付项目 + 阶段 + 检查项（软门）+ 2–3 个最高价值交付物模板（接已有 doc-gen）。**产出：真实客户项目能建项目、走阶段、一键生成需求规格/验收报告。**
- **Phase 3 ｜技能库**：把最常用的 5–8 个 codex/cc 动作收敛成内置交付技能，按阶段挂。
- **Phase 4 ｜知识/最佳实践库** + 模板/技能的团队共享与版本化。
- **Phase 5 ｜产品化对外卖**：授权、自动更新加固、品牌化、客户隔离、onboarding、定价打包。

**MVP（先让团队全员切过来）= Phase 0 + 1 + 2 的最小集**，其中 Phase 0 是必须先打的桩。

## 7. 风险与验证

| 风险 | 说明 | 缓解 |
|---|---|---|
| **PyInstaller 打包长板** | 把 FastAPI 全家桶（含 cryptography / aiosqlite / python-docx/pptx 原生扩展）打成 macOS sidecar 是整个地基最大工程长板 | Phase 0 spike 第一刀就验证；先裁依赖（playwright 可选、删 k8s、去 code-server） |
| **WebView 兼容** | Element Plus / X6 / shiki / marked 在 WKWebView 下的表现 | Phase 0 早冒烟测；macOS-only 已大幅收窄变量 |
| **签名/公证** | macOS Gatekeeper 要求联网下载的 app 经 **Developer ID 签名 + 公证** 才能顺滑双击打开（与 App Store 上架是两条线，不上架也需 **Apple Developer Program 99 美元/年** 会员）；否则撞「已损坏/身份不明的开发者」告警 | **可延后，不挡 Phase 0**：Phase 0 本地自签/ad-hoc，无需 Apple 账号；Phase 1 内部 dogfood 可右键→打开或 `xattr -dr com.apple.quarantine` 绕过；**Phase 5 对外卖前再办付费会员做签名+公证**（对要卖的产品是硬伤，必须做） |
| **sidecar 生命周期** | 启停随应用、端口冲突、崩溃恢复 | Phase 1 设计；随机端口 + 健康检查 + 看门狗 |
| **硬门误伤** | 闸口过严逼用户绕开工具 | D7：默认软门，关键项才硬门 |

## 8. 留待子项目 spec 解决的开放问题

- 交付项目实体与现有 `projects` / `applications` 模型如何对齐（SP2）。
- aPaaS/LLM 配置复用现有 `PlatformEnv`/`LLMConfig`(已加密、已有 UI)；待补的是桌面「交付 profile」多环境切换 UX 与首屏引导（SP1/Phase 1）。
- 交付物模板的结构化定义格式（章节 + 生成指令 + 数据来源 schema）（SP3）。
- 交付技能的定义/版本化/共享格式，与现有 skills/MCP 的复用边界（SP4）。
- 产品化阶段的授权模型（licensing）与客户隔离粒度（SP6）。

---

## 下一步

把 **Phase 0（打包 spike）** 拎出来走详细实现计划（writing-plans）。它是验证整个方向能不能成的第一步：在不碰交付层的前提下，证明「Tauri(macOS) + PyInstaller sidecar + WKWebView 加载现有前端 + 连真实 aPaaS/LLM」这条地基跑得通。
