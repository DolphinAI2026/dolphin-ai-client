# 部署前就绪评审 03 — 架构与代码质量评估

> 评审日期: 2026-05-30 · 评审视角: 准备交付客户 / 他人接手 · 性质: **只读评审**(未修改任何源码)
> 仓库: `apaas-builder-ai`(得帆云低代码平台 AI 搭建助手)· 规模: 后端约 11.5 万行 Python / 前端约 8.8 万行 Vue+TS
> 关联文档: `docs/audit-2026-05-29-codebase-health.md`(前一日的全仓体检,本报告对其姿态做了**复核与更新**)

---

## 0. 总体结论(TL;DR)

代码**功能性已相当成熟**(端到端"对话→生成→上线 apaas"主链路打通,149 个后端测试文件,完整设计系统),但从"**交付客户/他人接手**"的成熟度看,存在三类系统性短板:

1. **文档与代码严重漂移** — `README.md` 仍声称 SQLite / claude-haiku / Week1-2 待办清单,且**明文泄漏了 LLM API Key 与 JWT 密钥**。新人照 README 上手会被全程误导。
2. **运维/安全默认值不达生产标准** — 全后端 80 处 `verify=False`(TLS 校验关闭)、Fernet 加密默认值 `default-key-change-in-production-32b`、无数据库迁移框架(alembic),靠 `database.py` 里一长串 `try: ALTER TABLE ... except: pass` 兜底。
3. **少量超大文件成为可维护性黑洞** — `mcp_server.py` 8007 行 / 115 工具、`ChatPage.vue` 14758 行,接手者难以安全改动。

**值得肯定的是**: `docs/audit-2026-05-29-codebase-health.md` 列的 P0/P1 高危项,**绝大多数已在 2026-05-29→05-30 的 20+ 个 commit 里修掉了**(详见 §3)。该体检报告本身已**部分过时**,不能直接当"未修待办"用——这点务必向客户/接手人说明,否则会重复劳动或误判风险。

---

## 1. 技术栈与版本

### 1.1 后端(`backend/requirements.txt`)

| 依赖 | 版本 | 评价 |
|------|------|------|
| fastapi | 0.115.0 | 较新,健康 |
| uvicorn[standard] | 0.32.0 | 健康 |
| pydantic | >=2.11,<3 | v2,健康(范围锁版,见下) |
| pydantic-settings | 2.6.0 | 健康 |
| sqlalchemy | 2.0.36 | 2.0 async,健康 |
| aiomysql | 0.2.0 | 生产 MySQL 驱动 |
| aiosqlite | 0.20.0 | 仅本地/测试用 SQLite |
| cryptography | **同时写了 `>=43.0.0` 和 `==43.0.1` 两行** | ⚠️ 重复声明(第 8、15 行),pip 以最后一行为准=钉死 43.0.1,但属书写卫生问题,应合并 |
| python-jose[cryptography] | 3.3.0 | ⚠️ **偏旧**,3.3.0 是 2021 年版本,历史上有 CVE(算法混淆/JWT 校验),JWT 鉴权核心依赖建议升级评估 |
| passlib[bcrypt] | 1.7.4 | ⚠️ **偏旧**(2020),与较新 bcrypt 后端有兼容告警的已知问题 |
| httpx | 0.27.2 | 健康 |
| python-multipart | 0.0.12 | ⚠️ 该库历史有 DoS CVE(CVE-2024-53981 等),建议确认 >=0.0.18 |
| playwright | >=1.49.0 | 浏览器自动化,体积大 |
| mcp[cli] | >=1.27.0 | MCP server 协议库 |
| kubernetes-asyncio | >=31.0.0 | vibe-coding pod 沙箱 |
| python-docx | **未钉版本** | ⚠️ 无版本约束,构建不可复现 |

**要点**:
- `pydantic`、`mcp`、`kubernetes-asyncio`、`pytest*`、`cryptography>=43`、`playwright` 用了**下限范围(`>=`)而非精确钉版**,叠加 `python-docx` 完全无版本 → **构建不可复现**。交付客户前应产出 `requirements.lock` / `pip freeze` 冻结全量传递依赖。
- 认证相关的 `python-jose 3.3.0` / `passlib 1.7.4` 是整套 JWT 鉴权的根基,**版本偏旧**,交付前应过一遍 `pip-audit` / `safety`。

### 1.2 前端(`frontend/package.json`)

技术栈很新:Vue **3.5.25** + Vite **7.3.1** + TypeScript 5.9 + Element Plus **2.13.5** + Pinia **3.0.4** + vue-router **5.0.3** + @antv/x6 3.1(流程图)。版本均为 2025 末较新档,无明显偏旧。

注意点:
- `playwright ^1.59.1` 被列进**前端运行时 dependencies**(非 devDependencies),前端打包产物不需要 Playwright,应确认这是有意(可能给某 E2E/preview 用)还是错置。
- `build` 脚本 = `vue-tsc -b && vite build`,即**构建即类型检查**(`vue-tsc -b` 是真编译,符合 MEMORY 里记的"真基线 402"基线),这是好实践;同时保留了 `build:nocheck` 逃生口。

### 1.3 admin-spa(`admin-spa/package.json`)

独立的 MCP 管理后台 SPA,**技术栈整体落后于主前端一个大版本**:Vue **3.4** / Vite **5.2** / Element Plus **2.7** / Pinia **2.1** / vue-router **4.3** / vue-tsc **2.1**。与主前端(Vue3.5/Vite7/Pinia3/router5)**不一致**,两套前端版本分叉,长期会增加维护与升级成本。属次要问题(admin-spa 是内部运维界面)。

---

## 2. 架构总览

### 2.1 组成与组合方式

```
┌─────────────── 前端层 ───────────────┐
│ frontend/ (Vue3.5/Vite7, 124 个 .vue) │  主搭建台: Landing / ChatPage / AIChatPage / CodingPage / Designer 面板群
│ admin-spa/ (Vue3.4)                    │  MCP 运营后台(给管理员看 71 工具/环境/智能体)
└───────────────────────────────────────┘
              │ axios / SSE (EventSource)
┌─────────────── 后端层 FastAPI ───────────────┐
│ main.py: 40+ include_router               │  REST + SSE 流式
│   routes/ (auth/chat/ai_chat/applications/ │
│            coding/coding_v2/spec/...)      │
│   agents/ (brainstorm / coding /           │  内置 agent 流水线(头脑风暴→编码→验证→迭代)
│            verification / iteration)       │
│   coding/ (workspace/pipeline/generator/   │  低代码生成引擎 + vibe-coding 工作区
│            apaas_tools/form_component_editor)│
│   mcp_server.py (8007 行 / 115 @mcp.tool)  │  对外 MCP 工具供应商(给 dolphin 等 agent 平台调)
└────────────────────────────────────────────┘
        │                          │                       │
   ┌────┴─────┐            ┌───────┴────────┐      ┌────────┴─────────┐
   │ apaas 平台 │            │ dolphin (LLM网关 │      │ MySQL (生产)      │
   │ (低代码 PaaS)│           │  + agent 运营)   │      │ / SQLite (本地)   │
   └───────────┘            └────────────────┘      └──────────────────┘
```

**架构定位(来自代码注释与 MEMORY)**: 本仓是 **"MCP 工具供应商"**,dolphin 是 agent 运营平台;内置的 AIChatPage/CodingPage 对话是"过渡形态"。`mcp_server.py` 用 `FastMCP` 实例暴露领域能力,经 `admin_mcp` / `builder_mcp` / `mcp_platform` / `mcp_hub` 几个 router 挂载/代理出去。dolphin 把本仓当作 OpenAI 兼容 LLM provider + MCP 工具源使用,不构成双向深度耦合(`config.py:93-98` 注释明确)。

### 2.2 数据流(对话 → 生成 → apaas)

1. **对话/需求收集**: 前端 ChatPage/AIChatPage → `routes/chat.py` / `routes/ai_chat` → LLM(经 `anthropic_base_url`,实际指 MiniMax 或 dolphin omnigate),SSE 流式回传。需求沉淀为 SPEC(`routes/spec.py` + `models/spec*`)。
2. **生成**: SPEC/配置 → `coding/pipeline.py` / `generator_v2.py` / `step_executor.py` → 产出模型/表单/字典/流程/权限配置。`skills/orchestrator.py` 编排"建模型→建表单→配权限→发布"四阶段。
3. **落 apaas**: `apaas_client.py`(2429 行 APaaSClient)+ `coding/apaas_tools.py` → 调得帆云 REST 接口真实创建应用并发布版本。增量改动走 `incremental_executor.py`。

### 2.3 数据库(`config.py` + `database.py`)

- **prod = MySQL,dev = SQLite,二者共用同一套 SQLAlchemy 模型**。`config.py:41` 默认 `mysql+aiomysql://root:password@localhost:3306/apaas_builder`,通过 `.env` 的 `DATABASE_URL` 覆盖。`_normalize_database_url()` 把相对 SQLite 路径锚到 backend 目录(防 cwd 漂移)。
- **连接池**: 非 SQLite 时自动加 `pool_pre_ping=True` + `pool_recycle=1800` + `pool_size=10/max_overflow=20`(`database.py:11-23`),正确防 MySQL `wait_timeout` 僵尸连接 —— 这是**生产级配置,做得好**。
- **⚠️ 无迁移框架(无 alembic)**: 已确认仓库**没有 `alembic/` 也没有 `alembic.ini`**。schema 演进靠两条腿:
  1. `init_db()` 里 `Base.metadata.create_all`(只建新表,不改既有表);
  2. 紧跟一长串硬编码 `ALTER TABLE ... ADD COLUMN` 包在 `try/except Exception: pass` 里(`database.py:64-167`,约 40+ 条),"列已存在就吞掉异常"。
  - 风险: 这种"幂等靠吞异常"的迁移**不可回滚、无版本记录、无法审计、改列/改类型/删列做不了**(`MODIFY COLUMN` 在 SQLite 上直接静默失败)。客户环境一旦 schema 漂移很难诊断。`backend/scripts/` 下另有零散 `migrate_*.sql/.py` 手工脚本,与 `database.py` 内联迁移**双轨并存**,无单一事实源。**交付客户前强烈建议引入 alembic**。

---

## 3. 代码健康(对 `audit-2026-05-29` 的复核)

### 3.1 重要更正:体检报告已部分过时

`docs/audit-2026-05-29-codebase-health.md` 自称"待办清单,大部分尚未修复"(P0×1 / P1×26 / P2×28 / P3×3)。**本次逐条复核发现:其最高优先级的若干项在过去 24 小时内已被修复**。`git log --since=2026-05-29` 有 20+ 个 `fix(...)` commit。逐项对照:

| 体检条目 | 体检结论 | **2026-05-30 实际状态** |
|---------|---------|------------------------|
| **P0 SSRF**(`auth.py` 用户传任意 `apaas_base_url`) | 未修,medium | ✅ **已加白名单** `_is_allowed_apaas_base_url()`(`auth.py:159`),origin 校验兜底。但 `verify=False` 仍在(见下) |
| **P1-A 401 自愈核心**(`coding/tools.py:_make_platform_executor`) | "一处修覆盖 11 工具" | ✅ **已实现**(`tools.py:178-237`):`is_apaas_token_error` + `_relogin_apaas_env(env_id, db)` 重登重试,与体检建议的修法完全一致 |
| **P1-A 401**(MCP `list_apaas_app_processes` / `get_apaas_process_detail`) | 裸调真漏 | ✅ **已套** `call_apaas_with_relogin`(`mcp_server.py:1490/1553`,注释标 2026-05-29) |
| **P1-C 逻辑 bug #1**(`orchestrator.py` 失败 yield 'done') | 失败伪装成功 | ✅ **已修**:`orchestrator.py:133/145` 现在权限/发布失败 yield `status:"error"`,带注释"状态必须标 error 否则掩盖失败" |
| **P2 吞异常**(`generation_steps.py:901 except: pass` token 刷新静默) | 静默吞 | ✅ **已修**:改为 `logger.warning`(`generation_steps.py:904`) |
| **P2 重试风暴**(`incremental_executor.py` 无熔断/退避) | 30 次重试风暴 | ✅ **已加** `MAX_RETRIES=2` + 指数退避 + jitter(`incremental_executor.py:35/518-533`) |
| **P2 死代码**(backend 根 19 个调试脚本) | 可删 | ✅ **已删**:backend 根目录现仅剩 `apaas_builder_cli.py` / `conftest.py` / `run.py` 三个正经文件 |

> **给接手人的告诫**: 不要把 `audit-2026-05-29` 当"未修待办"直接派活——它是一份**已被后续提交大量消化**的快照。真正动手前,务必对每条 `git blame` / 读真代码确认当前状态(本报告 §3.1 表是 05-30 的复核结果)。

### 3.2 体检中**仍然有效**的关切

- **吞异常(把失败伪装成功)的体量仍大**: 全后端仍有约 **88 处 `except Exception: pass`**(粗筛)。虽然几个被点名的具体位置修了,但"吞异常"是这个代码库的**系统性风格**(连 `database.py` 的迁移都靠它)。对客户生产部署而言,这意味着**故障会被静默吃掉、问题现场难以还原**。建议落一条规则:吞异常处至少 `logger.warning(..., exc_info=True)`。
- **401 自愈仍有零散缺口**: 体检列的 `platform_sync.py:287`(`sync_from_platform_full` 裸调 `query_menus`,导入应用时断)、`incremental_executor.py` 的 query_dicts/models/menus、`mcp_server.py` 的 `deploy_process_to_apaas`/`upload_external_zip_to_apaas`/`publish_dev_package` 等**写接口与部分读接口本次未见全部收口**——需逐个核。核心 agent 路径已堵,但"导入/同步/发布"边缘路径仍可能 401 中断。
- **前端"假功能"(9 处)**: 体检列的 ListDesigner/DataModel/Dict/Process 等面板"点了只 alert / disabled"。注意 `git log` 里 `6ab0ad8`/`9fc668d` 已**删掉一批纯 alert 死按钮**,但权限矩阵"显示推断值假数据、只有 form 权限能真存"(`RoleManagePanel.vue`)等**产品级不完整仍在**。交付客户前必须界定:**哪些 designer 面板是"可演示但不可用"**,避免客户误以为是完整功能(这是交付沟通问题,不全是代码问题)。

### 3.3 超大文件抽查(可维护性)

| 文件 | 行数 | 评价 |
|------|------|------|
| `backend/app/mcp_server.py` | **8007 行 / 115 个 `@mcp.tool()`** | 🔴 **可维护性黑洞**。单文件承载全部对外 MCP 工具,接手者要改一个工具得在 8000 行里定位;115 个工具的鉴权/401 自愈/错误码逻辑散落其中。强烈建议按域拆分(apaas / coding / vibe / design 各一模块,`FastMCP` 支持多实例 mount) |
| `backend/app/coding/workspace.py` | 5532 行 | 🟠 偏大,vibe-coding 工作区逻辑,建议拆分 |
| `backend/app/routes/applications/__init__.py` | 3882 行 | 🟠 单 router 文件过大 |
| `frontend/src/views/ChatPage.vue` | **14758 行** | 🔴 **前端第一巨石**。MEMORY 多处记载"13K 行 ChatPage 全 reactive、0 逻辑改重构"——说明团队**不敢动它**,这本身就是接手风险信号。一个 1.5 万行的 SFC 几乎无法被新人安全修改 |
| `frontend/src/views/CodingPage.vue` | 4648 行 | 🟠 偏大 |

体量数据印证:核心业务都压在极少数巨型文件里,**卡车系数(bus factor)低**——少数文件只有原作者能安全改。

---

## 4. 可维护性风险

### 4.1 死代码 / 残留物

- ✅ **backend 根 19 个调试脚本已清理**(体检后已删,见 §3.1)。
- 🔴 **`backend/form_config_before.json`(117KB)+ `form_config_after.json`(125KB)仍被 git 跟踪** —— 这是某次表单权限调试的 before/after 快照(时间戳 Mar 17),**纯调试垃圾,共 242KB**,应从仓库删除。
- 🟡 **`frontend/src/api/incremental.ts` 的运行时部分是死代码**:文件导出 `incrementalApi` 对象 + 一组 interface。复核确认 `ChatPage.vue:957` 与 `ConfigDiff.vue:282` **只 import 了 TypeScript 类型(ChangeItem/DiffResponse/...),从未调用 `incrementalApi.xxx` 运行时方法**(`grep "incrementalApi\."` 0 命中)。即:**类型定义活着、运行时 API 客户端已死**。可拆分(类型留下,死 API 删掉),但需谨慎(体检也提醒过 aiChat.ts/proposals.ts 曾被误判为死代码)。
- 🟡 `frontend/src/api/workState.ts` 仅 1 处引用(体检 P3,可选清理)。

### 4.2 文档与代码漂移(交付的最大软肋)

**`README.md` 已严重过时且危险**,是新人接手第一份会读、却会被全程误导的文档:

| README 声称 | 代码实际 |
|------------|---------|
| 数据库 = **SQLite + aiosqlite**(第 54、81、110 行) | prod = **MySQL**(`config.py:41`),SQLite 仅本地 |
| LLM = **claude-haiku-4-5**(第 83、107 行) | 默认 **MiniMax-M2.7**(`config.py:33-38`) |
| 前端 **http://localhost:5173**(第 42、87 行) | dev 实际 `127.0.0.1` + base `/ai-builder/`(`package.json:7`) |
| LLM_API_BASE = `api.jiekou.ai`(第 106 行) | 默认 `api.minimaxi.com/anthropic` |
| "Week 1-2 / Week 3-4 开发计划",大量未勾选 `[ ]`(第 122-136 行) | 这些功能(得帆云登录/多轮对话/5 tab 预览/应用管理)**早已全部上线** |

🔴 **README 第 104-114 行明文写出了真实的 `LLM_API_KEY=sk_PR…...` 和 `JWT_SECRET_KEY=STJN…...`**。虽然真正的 `.env` **没有**被 git 跟踪(已确认,这点是好的,且有 `backend/.env.example` 1KB 模板),但**密钥被硬编码进了入库的 README**——等同泄漏。**交付前必须:① 从 README 删除所有真实密钥;② 轮换(rotate)这两个已泄漏的凭据**(LLM key + JWT secret 都应作废重签)。

> 其余文档基本健康:README 引用的 `DEVELOPMENT.md` 存在(链接不断);`docs/` 下有大量 handoff/audit 文档,信息密度高但**以"开发日志"形式存在,缺一份面向接手人的"当前架构事实"总览**(本系列 deploy-readiness 文档正好填补)。

### 4.3 安全/运维默认值(命名/耦合外的硬伤)

- 🔴 **80 处 `verify=False`**(全后端 `httpx.AsyncClient(verify=False)`):对 apaas / dolphin 的所有出站 HTTPS 请求**全部关闭了 TLS 证书校验**。生产环境这是中间人攻击(MITM)敞口。即便内网可信,也应改为可配置(默认 `True`,仅自签名内网环境显式关)。
- 🔴 **Fernet 加密 key 默认值 = `"default-key-change-in-production-32b"`**(`config.py:53`):用于加密平台密码(`platform_password_enc`)。若客户部署忘了在 `.env` 覆盖 `ENCRYPTION_KEY`,**所有落库的平台密码等于明文**。代码没有"启动时拒绝默认 key"的 fail-fast 保护,建议加。
- 🟡 **JWT 默认 HS256 + `jwt_secret_key` 为必填**(`config.py:44`,无默认值,好)。但 `python-jose 3.3.0` 偏旧(§1.1)。
- 🟡 admin-spa 与主前端**版本分叉**(§1.3),两套构建工具链,长期维护成本。

---

## 5. 给客户的就绪度评分(主观)

| 维度 | 评级 | 说明 |
|------|------|------|
| 功能完整度(主链路) | 🟢 良好 | 对话→生成→上线 apaas E2E 打通,149 测试文件 |
| 架构清晰度 | 🟡 中等 | 分层合理,但巨型文件 + 双轨迁移拉低 |
| 安全默认值 | 🔴 不达标 | verify=False ×80 / Fernet 默认 key / README 泄密 |
| 可复现构建 | 🟡 中等 | 依赖未全锁版;前后端版本分叉 |
| 文档可信度 | 🔴 不达标 | README 反映的是 6+ 个月前的早期形态 |
| 可接手性 | 🟡 中等 | handoff 文档丰富,但巨石文件 + bus factor 低 |

---

## 6. 交付客户前最该收口的 5 件代码质量事项

> 按"风险×对交付的杀伤力"排序。前 3 件**必须做**,后 2 件强烈建议。

### 1. 🔴 重写 README + 轮换已泄漏密钥(成本最低、杀伤最大)
   `README.md` 明文写着真实 `LLM_API_KEY` 与 `JWT_SECRET_KEY`,且通篇声称 SQLite/claude-haiku/Week1-2 待办——**新人照着上手会被全程误导,密钥等于公开泄漏**。动作: 删 README 里的真实密钥 → 立即**轮换这两个凭据** → 把"SQLite/haiku/端口/Week 计划"全部改成现状(MySQL/MiniMax/`/ai-builder/`/已上线)。改文档零代码风险,却直接决定客户/接手人的第一印象与安全底线。

### 2. 🔴 关掉/可配置化 `verify=False`(80 处)+ 给 Fernet 默认 key 加 fail-fast
   全后端 80 处对 apaas/dolphin 的出站请求**关闭了 TLS 校验**;Fernet 加密 key 默认值是 `default-key-change-in-production-32b`,客户漏配则**所有落库平台密码近乎明文**。动作: 抽一个 `settings.tls_verify`(默认 `True`)统一替换 `verify=False`;启动时若 `encryption_key` 仍是默认值则**拒绝启动并报错**(fail-fast)。这是"客户生产部署"最直接的安全敞口。

### 3. 🟡→🔴 引入数据库迁移框架(alembic),替换"吞异常 ALTER TABLE"
   当前 schema 演进靠 `database.py` 里 40+ 条 `try: ALTER TABLE ... except: pass`,**不可回滚、无版本、无审计、改列/删列做不了**,且与 `backend/scripts/migrate_*.sql` 双轨并存无单一事实源。客户环境一旦 schema 漂移极难诊断。动作: 接入 alembic,把现有内联迁移固化为初始 revision。这是"他人接手后还能安全演进数据库"的地基。

### 4. 🟡 拆分两个可维护性黑洞:`mcp_server.py`(8007 行/115 工具)与 `ChatPage.vue`(14758 行)
   团队 MEMORY 已自陈"13K 行 ChatPage 不敢动、0 逻辑改重构"——这是 bus factor 过低的明确信号。`mcp_server.py` 单文件 115 个工具,改一个要在 8000 行里翻。动作: `mcp_server.py` 按域(apaas/coding/vibe/design)拆成多个 `FastMCP` 子模块 mount;`ChatPage.vue` 至少把 Designer 子面板、对话列表、blueprint 适配拆成独立 SFC。不要求一次到位,但交付前应**至少拆掉这两个最危险的**,否则接手人无从下手。

### 5. 🟡 清理死代码/残留 + 锁定依赖版本(可复现交付)
   动作两件: ①删 `backend/form_config_before.json`+`form_config_after.json`(242KB 调试垃圾)、清理 `incremental.ts` 已死的运行时 `incrementalApi`(保留其类型);②给 `requirements.txt` 产出 `pip freeze` 全量锁版(消除 `python-docx` 无版本、`cryptography` 重复声明、多个 `>=` 下限),并评估 `python-jose 3.3.0`/`passlib 1.7.4`/`python-multipart` 这几个偏旧且涉安全的依赖是否升级。让客户能拿到**可复现、无已知 CVE 惊吓**的构建。

---

## 附:本报告事实核查命令(可复现)

- 巨型文件: `find backend/app -name '*.py' | xargs wc -l | sort -rn | head`
- MCP 工具数: `grep -c "@mcp.tool()" backend/app/mcp_server.py` → 115
- TLS 关闭点: `grep -rn "verify=False" backend/app | wc -l` → 80
- 吞异常: `grep -rnE "except Exception:?\s*$" backend/app -A1 | grep -cE "pass"` → ~88
- 迁移框架: `ls backend/alembic backend/alembic.ini` → 不存在(确认无 alembic)
- README 密钥: `README.md:106,113`
- 体检后修复证据: `git log --oneline --since="2026-05-29"`
