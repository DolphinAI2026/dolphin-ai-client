# 当前状态（STATE.md）

> 更新时间：2026-05-17 凌晨（**双轨分工最终架构**：mars 对内 / xhh 对外）
> 维护规则：每次重大上线 / 决策后追加；只写 fact，不写 plan。
> 关系：`README.md` 是入门文档（已过期）；`PLAN.md` 是治理目标（Phase 1+ 未启动）；**本文件是现状的 source of truth**。

## TL;DR

ai-builder 当前定位是 **MCP 工具供应商**，对接 dolphin 作为 agent 运营平台。**ai-chat 是产品保留功能**（5/16 晚拍板修正），不再视为过渡形态。生产部署完全在公司 KubeSphere k8s。

**5/17 凌晨双轨分工最终架构**（详见五点八节）：

| 轨道 | 主人 | 服务对象 | 部署 |
|---|---|---|---|
| **对内**：ai-chat / ming 自管 | mars (你) | ai-builder 平台内部用户 | ming pod 内置 `mcp_server.py` 80 工具 (loopback) |
| **对外**：v2 公网 svc | xhh | dolphin agent / 第三方 | `apaas-builder-mcp-server` (33 工具 strict auth) + `apaas-mcp-server-v2` (68 工具) |

ai-chat 5/17 凌晨从 v2 切回 ming loopback（撤销 5/16 晚切流决策）—— **两套互不依赖、互不阻塞，各自演进**。

3 个 MCP deployment 仍然存在但分工清晰：

- `apaas-builder/apaas-builder-ming`（本 repo） — backend + frontend + admin SPA + **内置 `mcp_server.py` 80 工具（ai-chat 主用）**。当前 image `:20260516-00fba76-deploy-env-token`
- `apaas-builder/apaas-builder-mcp-server`（**xhh 主线**） — 当前 `:20260517-0018-mcp-metadata-amd64`，33 工具 strict auth，给 ming 内部 admin SPA proxy 和 dolphin 公网入口用
- `apaas-mcp-server/apaas-mcp-server-v2`（**xhh 主线**） — `:20260515-user-token` 68 工具，dolphin agent 公网 `/mcp-server-v2/*` 入口

⚠️ **双 db 命名倒挂**：
- `apaas-builder/apaas-builder-mcp-server` pod 用 db `apaas_builder_mcp_server`（带后缀）
- `apaas-mcp-server/apaas-mcp-server-v2` pod 用 db **`apaas_builder`**（不带 _mcp_server 后缀）
- 同一个 app_code 可能在两个 db 各创建一个应用，互不感知

4 个客户租户共享 3 个 dolphin agent，全在线。

## 一、当前部署（事实）

### 网络入口

| 域名 / 路径 | 现状 | 后端 |
|---|---|---|
| `agent.dfy.definesys.cn/ai-builder/*` | **公网主入口** | ming pod (backend + frontend) |
| `agent.dfy.definesys.cn/mcp-server-v2/*` | **dolphin agent 公网入口（xhh 主线）** | `apaas-mcp-server/apaas-mcp-server-v2` (68 工具) |
| `agent.dfy.definesys.cn/mcp-server/*` | **xhh admin SPA + dolphin 备用入口** | `apaas-builder/apaas-builder-mcp-server` (33 工具 strict auth) |
| `agent.dfy.definesys.cn/ai-builder/api/mcp/mcp` | 公网仍 listen，**5/17 凌晨起 ai-chat 切回 loopback 重新成主 caller** | ming pod 内置 mcp_server.py 80 工具（mars 对内主线）|
| `df-aigc.dfy.definesys.cn/*` | StatefulSet `apaas-builder-0`，跑 stale image | df-aigc 团队不归本项目 |
| `*.vibe-first.cn` | DNS 仍指老阿里云 ECS，已断 | 待 K8s 迁移落地 |

阿里云 ECS `39.103.201.110` 还活作公网入口反代 + 24-48h 热备，不是业务跑在那。**注**：今天实测 SSH 22 端口 banner timeout（sshd hang 或 fail2ban），上次确认 work 的 5/15 之后状态可能变了。

### Pod / 最新 image（5/16 晚实测）

| Deployment | Namespace | Image | 备注 |
|---|---|---|---|
| `apaas-builder-ming` | `apaas-builder` | `hub.dfy.definesys.cn/ai-builder/apaas-builder:20260516-uxfix` | HEAD `def942c`（含 3 UX fix + ai-chat v2 切流配置） |
| `apaas-builder-mcp-server` | `apaas-builder` | `hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:20260517-0018-mcp-metadata-amd64` | **33 工具**（v2 repo `main` HEAD `41adef5`，xhh 推送）。强制 draft 流程独主 / strict end-user identity auth / admin SPA 重写含 CallLogs+McpServices+McpTester+Login。**5/17 凌晨决策：以 xhh 为准** — 我 feat 分支 81-工具版废。 |
| `apaas-mcp-server-v2` | `apaas-mcp-server` | `hub-snapshots.dfy.definesys.cn/mars/apaas-builder-mcp-server:20260515-user-token` | **68 工具，跟 apaas-builder ns 那个 drift**。registry: `hub-snapshots.dfy.definesys.cn/mars/`。dolphin agent 公网入口走它，**下次 sync 升 `:20260516-port-15-crud` (该 tag 已 cross-push 到这个 registry，待命)** |
| `apaas-mcp-server` | `apaas-mcp-server` | (v1, 历史遗留) | 老 deployment，未确认是否还有 client |

### MySQL

- db：`apaas_builder_mcp_server` @ `mysql.mysql.svc:3306`
- 用户：`apaas` / `apaas2024`
- **backend + mcp-server-v2 共写同一 db**（非隔离）
- 注意：mcp-server-v2 自己 db 名是 `apaas_builder`（**双 db 命名倒挂**，5/15 撞过 design-preview 404 bug）

### PVC

| 名字 | 用途 | 风险 |
|---|---|---|
| `apaas-workspaces-ming` 50Gi | 名义 ming 工作区 | **🔴 ming 实际跑在 `/root/apaas-builder/workspaces/`（容器 overlay 非 PVC），restart 风险丢** |
| `workspaces-v2` 492GB | mcp-server-v2 `/app/workspaces/` | 真 PVC，OK |

## 二、4 租户 + dolphin agent 接入清单

| ai-builder 租户 | id | aPaaS env id (alias) | aPaaS 租户 customerName | dolphin 真身用户 | 状态 |
|---|---|---|---|---|---|
| default | 1 | 44 (default) | 得帆体验 | admin/admin123 | ✅ |
| bj (宝洁中国) | 29 | 32 (baogong) | 宝洁（中国） | pg/B2VY^1obWycO%q | ✅ |
| saic (上汽) | 40 | 43 (saic) | 上汽大乘用车 | saic/welcome1 | ✅ |
| fudan (复旦) | 41 | 46 (fudan) | 复旦大学 | 用户未建 | ⏸️ |

3 个共享 dolphin agent（trial 省 9× 维护）：

- `23c93f30d8` — 智能搭建 (instance=ai-apaas-builder, nav=/ai-copilot)
- `f765238af4` — 智能开发 (instance=ai-apaas-coding, nav=/ai-coding)
- `3043cc6b09` — Vibe-Coding (instance=ai-apaas-vibe, nav=/agent/vibe)

`DOLPHIN_SERVICE_TOKEN` **2026-08-30 过期**，提前 1 个月续。

## 三、架构决策（锁定，不要翻案）

1. **ai-builder = MCP 工具供应商；dolphin = agent 运营平台**（2026-05-14）
   - **ai-chat 是产品保留功能**（5-16 晚拍板修正之前"不再演进"判断）
   - VibeChatPanel / CodingPage 内置对话仍是过渡形态
   - 不在 ai-builder 复刻 dolphin agent 能力
   - 不做双向集成幻想

2. ~~**ai-chat 跟 dolphin 调同一批 MCP 工具**（2026-05-16 晚）~~ **5/17 凌晨撤销**
   - 5/16 晚临时把 `MCP_INTERNAL_BASE` 切到 v2 svc，5/17 凌晨发现 xhh strict auth 卡 ai-chat 后**切回 loopback**
   - 当前 ai-chat 走 `http://127.0.0.1:8003/api/mcp/mcp` ming 内置 mcp_server.py 80 工具
   - mcp_bridge.py 的 env override 机制保留（万一以后想再切）

3. **双轨分工：对外以 xhh 为准 / 对内 mars 自管**（2026-05-17 凌晨决策）
   - 对外（v2 svc 给 dolphin / 公网）：xhh main 33 工具 + 强制 draft + strict auth + admin SPA 重写是主线
   - 对内（ai-chat / ming pod 自己用）：mars 自己说了算，走 ming 内置 80 工具，不依赖 v2
   - 两套各自演进 / 不互相 PR review / 不互相 push image 覆盖
   - 详见第五点七 + 五点八节

4. **vibe-coding 用 K8s pod-per-workspace**（2026-05-15）
   - 设计稿：`docs/vibe-k8s-migration/00-design.md`
   - 不修补 docker 路线（老 ECS 已死，不恢复）

5. **多租户身份 1:1:1 强绑**（2026-05-13）
   - ai-builder tenant ↔ aPaaS 租户 ↔ dolphin customerName 严格 1 对 1
   - 切租户 = 切真实 aPaaS 租户落地

6. **mcp-server-v2 是新主线**（2026-05-11 立项 / 5-14 切流 / 5-16 晚 ai-chat 也切流）
   - 本 repo `mcp_server.py` 4241 行 + 80 工具是历史遗留，**5/16 晚后无任何 caller**

## 四、代码层：活 / 过渡 / 死

### ✅ 活（生产关键路径，改要谨慎）

**Backend**
- `main.py` + `routes/*` 多数
- `routes/admin_mcp.py` / `routes/builder_mcp.py`（2026-05-16 改 HTTP proxy → v2）
- `coding/workspace.py` 5530 行（巨型但活着）
- `coding/pipeline.py` 1891 行
- `coding/form_component_editor.py` 2237 行
- `vibe_coding/k8s_runtime.py` 648 行（迁移中，含 WIP +7）
- ~~`mcp_server.py` 4241 行 + 80 工具（仅 ai-chat loopback 在用）~~ → 已移入"过渡形态"

**Frontend**
- `views/Landing.vue`、`ChatPage.vue`（2026-05-15 改 SPEC 单栏）、`Apps.vue`、`OnlineCodingWorkspacePage.vue`
- `views/PlatformEnvs.vue`、`TenantUsers.vue`、`PlatformTenants.vue`
- `components/DolphinAgentEmbed.vue`、`BuilderNavRail.vue`

### ⏸️ 过渡形态（已废，等 K8s 迁移端到端稳定 ≥ 1 周后一次清）

🔓 **5-16 晚修正**：ai-chat **保留为产品功能**，不再视为过渡。但实现已切流 v2 svc，本机 `mcp_server.py` 无 caller 可单独退役。

后端可退役（5/16 晚 ai-chat 切流后，**这些都无任何 caller**）：
- `mcp_server.py` 4241 行 + 80 工具（ai-chat 切流后 loopback 不再调）
- `routes/vibe_coding_chat.py`
- `routes/online_coding.py` + `routes/online_coding_runtime.py`（前端已 redirect /vibe-coding/*，后端命名 stale）

后端**仍活**（ai-chat 保留）：
- `routes/ai_chat.py` + `ai_chat/mcp_bridge.py` + `ai_chat/agent.py` + `ai_chat/tools.py`

前端可退役：
- `views/CodingPage.vue`（旧 SPEC 双栏，已被 ChatPage 覆盖）
- `components/HelpAssistant.vue`
- `router/index.ts` 里 `/coding` 路由 + `main.py` 路由注册

前端**仍活**（ai-chat 保留）：
- `views/AIChatPage.vue`
- `components/common/AgentConversation.vue`（5/16 晚加 ResizeObserver + content watch）
- `router/index.ts` 里 `/ai-chat/:id?` 路由

### ❓ 死代码（删之前先 grep 引用）

- `views/WorkspaceShell.vue`（router 直接 redirect 走，无引用）
- `vibe_coding/docker_runtime.py`（K8s 迁移落地后整文件删）
- `generator_v2.py` 的 v1 残迹（未扫）
- 7 条历史 router redirect：`/online-coding/*`、`/ide`、`/generate/:id`、`/work/:appId`、`/settings?tab=envs` 等

### 🗑️ 已删（2026-05-16）

- `routes/app_adjust_chat.py` (-371 行)
- `components/AppAdjustDrawer.vue` (-594 行)

## 五、MCP 工具 drift（5/16 晚部分收敛）

**5/16 晚切流前**：
- ai-builder-ai mcp_server.py 独有 27（含 vibe_* 10 老 docker + aPaaS 精细 CRUD 15 + 2 其他）
- v2 独有 28（含 draft 流程 5 / handoff 2 / 救援 / lookup 等）
- 重叠 53 — 每次 bug 修要改两个 repo

**5/16 晚切流后**：
- ai-chat 切走 v2 svc，ai-builder-ai mcp_server.py 80 工具**无 caller 可退役**
- 把 15 个 aPaaS CRUD port 到 v2（commit `d8561ae`），v2 升到 **92 工具**
- 剩 vibe_* 10 个老 docker 工具不 port（K8s 迁移要废）

**5/16 夜裁剪到 82**（commit `2ac7c47`）：发现 92 里有冗余 + dolphin agent prompt audit 后删 10 工具：

| 删除 | 数量 | 理由 |
|---|---|---|
| `save_design_draft` / `patch_design_draft` / `save_app_design_doc` / `apply_draft_to_live_app` / `promote_draft_to_app` / `get_draft_summary` | 6 | 新 draft 流程 — pricing doc 估过但 dolphin agent prompt 没切，推翻"未来主流程"plan |
| `handoff_to_builder` / `handoff_to_coding` | 2 | 跨 agent 接力 — dolphin prompt 完全没引用 |
| `lookup_user_by_username` / `grant_app_access` | 2 | 用户授权管理 — dolphin prompt 完全没引用 |

**保留作 dolphin 主流程**：`submit_design_doc` / `update_app_from_doc` / `execute_change_plan` / `get_change_plan`（dolphin agent prompt 结构性改动主路径，**重度引用不能删**）。

**5/16 夜再砍 1 个到 81**（commit `e35cca2`）：实测 LLM 看到 `check_model_codes` 独立工具就**预防式**改 md 里 modelCode（用户 md 写 `customer` → LLM 传 `service_customer` 给 check 拿到 no_conflict → 应用 modelCode 跟 md diverge）。修复：

- 去掉 `check_model_codes` 上的 `@mcp.tool()` 装饰器（LLM 看不见）
- 函数保留作 `generate_app_from_doc` 内部预检（其内部已有等价 `_APAAS_RESERVED_MODEL_PREFIXES` 检查逻辑）
- `generate_app_from_doc` docstring 加铁律：**md 内容 1:1 映射，agent 禁止预防式改任何 code 名**

**设计原则锁定（用户 5/16 夜拍板）**：md→app 走 deterministic 程序，不让 LLM 干预决策。LLM 角色 = 陪用户写 md；写完点"生成" → 整条链路纯程序。

**drift 现状**：`apaas-builder/apaas-builder-mcp-server` (81 工具) vs `apaas-mcp-server/apaas-mcp-server-v2` (68 工具，dolphin 公网入口仍走它) — 待下次 sync

**典型漏同步案例**（保留为教训）：

- 5/16 `_get_build_output_dir` PAGE_CUSTOM_DEV：v2 早修，ai-builder-ai 漏改 → 误报 BUILD_FAILED
- 5/15 token 自愈 wrapper：ai-builder-ai 改了，v2 没移植 → admin token 过期要手动 db update

## 五点五、5/16 晚 image 覆盖事故（教训）

**事件**：下午 15:00 我推 `apaas-builder-mcp-server:20260516-port-15-crud`（92 工具，soft auth — MCP_API_KEY 通过即 pass，user identity optional）。**17:45 另一个 session 推 `:20260516-1745-prune-tools`** 覆盖：33 工具（砍 60+ 个）+ strict auth（MCP_API_KEY 通过后**必须**有 end-user identity header 否则 401）。

**后果**：ai-chat + admin /mcp 全 401 一直到 22:30 我发现并回滚。

**回滚动作**：`kubectl -n apaas-builder set image deployment/apaas-builder-mcp-server mcp-server=hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:20260516-port-15-crud` → 92 工具 + soft auth 恢复。

**未解决**：
- `:20260516-1745-prune-tools` 来源不明（git history 找不到，可能其它 session / 手动 build / CI）
- 17:45 那个版本的"strict auth + 砍工具"方向其实是正确长期方向（5/14 commit `feat(auth): dolphin aPaaS-Token header 用户身份穿透` 的延续）—— 但**当时没改 ai-chat mcp_bridge / admin_mcp.py / builder_mcp.py 三处 caller 同步注入 user identity**，所以推上去就炸
- **下次再做 strict auth 切换前必须先改 caller 端 3 处**：mcp_bridge.py / admin_mcp.py / builder_mcp.py 加 user JWT 注入

**防御措施 P0**：
- v2 deployment 加 protection annotation 或者 GitOps 锁，防止单方面 set image
- 下次 push image **必带 git commit hash 在 tag**（`:20260516-abc1234-feat`），看 tag 就知道来源
- ✅ **5/16 夜已实施**：从 `:20260516-2ac7c47-prune-10` 起所有 tag 带 commit hash 可追溯

## 五点六、5/16 夜连环 3 故障链（重要教训）

**因果**：今晚做"prune 10 工具"动作 → 没想到连环触发 3 个故障：

```
故障 1: 删工具时漏更新 docstring
  ⤵ 9 个核心工具 docstring 仍写 [DEPRECATED] + 引用已删工具
  ⤵ LLM 看主流程"全废"就 hallucinate 兜底 "没有开放接口"
  → fix: commit bcf117a 修 9 工具 docstring

故障 2: mcp_bridge 进程内 cache 无 TTL
  ⤵ ming 进程内 _LOADED dict 一加载就持久
  ⤵ v2 升级 ming 不重启 → ai-chat agent 仍看老工具集（含 [DEPRECATED] 标记）
  → fix: kubectl rollout restart ming，进程重启清空 cache（治标）
  → 未做: mcp_bridge 加 5min TTL invalidate（治本，P2 留尾）

故障 3: check_model_codes 工具引诱 LLM 改 md
  ⤵ 工具 description 写"建议加业务前缀"
  ⤵ LLM 解读为"全部 modelCode 都加前缀避免冲突"
  ⤵ 用户 md 写 customer → LLM 传 service_customer → 应用 modelCode 跟 md diverge
  → fix: commit e35cca2 去掉 @mcp.tool() 装饰器隐藏，generate_app_from_doc
         docstring 加铁律"md 1:1 映射"
```

**关键教训**：
- 删工具时**必须 grep** `[DEPRECATED]` + 该工具名在所有 docstring/comment/error_message 的引用，同步清
- mcp_bridge cache TTL P2 留尾
- 工具 description 不要写"建议 agent 做 X"这种 vague guidance，LLM 会泛化执行；要写硬规则
- 凡是涉及 md→app 转换的工具，docstring 必须强调"deterministic / 1:1 / 禁止 agent 篡改"

## 五点七、5/17 凌晨：双开发者并行冲突的最终决策（以 xhh 为准）

**真相**：5/16 下午 + 凌晨两次"v2 image 被覆盖"事故的真凶**不是 CI / 不是另一个 Claude session / 不是 image 系统问题**，是**真人开发者 xhh**（commit author `admin@xhhMacBook-Air.local`）在 v2 repo `main` 分支并行做完整反向设计，互不通气。

**两条线对比**：

| | 我（Claude session, 用户 22:00 拍板）| xhh（main 分支）|
|---|---|---|
| v2 repo 分支 | `feat/mcp-tools-batch-2026-05-14` | `main` |
| 工具集 | 81（92 - 10 删 - 1 隐藏）| **33**（精简 70%）|
| draft 流程（save_design_draft / promote 等）| ❌ **删了**（按用户 22:00 决策）| ✅ **强制主流程**（删了 generate_app_from_doc）|
| 老 change_plan（update_app_from_doc 等）| ✅ 保留 dolphin 主路径 | ❌ 删了 |
| aPaaS 精细 CRUD 15 个 | ✅ 我今天 port 进来 | ❌ 完全没 |
| vibe sandbox 9 个 | ✅ 保留 | ❌ 删了 |
| check_model_codes | ❌ 我隐藏（防 LLM 篡改 md）| ❌ 也没暴露（一致）|
| md 1:1 铁律 | ✅ 我加在 generate_app_from_doc docstring | ❌ generate_app_from_doc 本身就删了 |
| auth | soft（MCP_API_KEY pass）| **strict**（必须 end-user identity 否则 401）|
| admin SPA | 老版本 | **重写**（CallLogs / McpServices / McpTester / Login 4 个新页面）|

**双方都各 5+ 个 commit 在并行 push image 覆盖对方**：
- 15:00 我推 `:port-15-crud` (92 工具) → 17:45 xhh 推 `:1745-prune-tools` (33 工具) 覆盖
- 22:39 我推 `:e35cca2-deterministic-md` (81 工具) → 5/17 00:18 xhh 推 `:0018-mcp-metadata-amd64` (33 工具) 覆盖

**5/17 凌晨用户拍板**：**以 xhh 为准**。
- v2 repo `feat/mcp-tools-batch-2026-05-14` 分支 4 个 commit（d8561ae port 15 / 2ac7c47 prune 10 / bcf117a 修 docstring / e35cca2 隐藏 check + md 1:1）方向**全废**
- 生产保持 xhh 的 33 工具 + draft 独主版本
- xhh 重写的 admin SPA（CallLogs / McpServices / McpTester / Login）成为新主线

**我今晚 ai-builder-ai repo 6 个 commit 的去留**：
- ✅ 保留 `e531487 feat(ai-chat): 切流 v2 bridge env 解耦`（跨 repo，不冲突 xhh）
- ✅ 保留 `def942c fix(ai-chat): 3 UX 痛点（duration / SSE chunk / auto-scroll）`（前端 ChatPage / AgentConversation，不冲突）
- ✅ 保留 `00fba76 fix(generate): SSE /generate 走 platform_envs.token`（ming backend bug fix，跟 xhh 路线不冲突）
- ⚠️ STATE.md 3 个 docs commit（`3aeb754` / `2e1e053` / `428118e`）描述被覆盖的方向，**被本节替代**
- 这些 ming 改动都在 `:20260516-uxfix` / `:20260516-00fba76-deploy-env-token` image 里跑着

**根本问题（P0）**：
- 没有**协作流程**让两人知道对方在做什么 — PR review / Slack 通知 / 站会都没
- 两人都直接往 main / feat 分支推 + 直接 push image set deployment image，没 GitOps 锁
- 这种情况 trial 阶段还行（两个 trial 应用），生产规模化必定爆

**5/17 上午行动项（用户负责）**：
1. 跟 xhh 当面同步：明确 ai-builder MCP server 主线设计方向（强制 draft / 还是删 draft 留 generate_app_from_doc / 还是 hybrid）
2. 商定**唯一一条 main 分支** + PR review 流程
3. v2 deployment 加 GitOps 锁防绕过 PR 直接 set image
4. 我 ming repo 的 commit (`e531487` / `def942c` / `00fba76`) 看 xhh 是否接受，决定是否 merge / 是否 deploy

**应用其实创建成功了**（用户发现的 28/28 SPEC 完成 + apaas_app_id 已分配）：
- `apaas_builder` db (xhh 那边) 有 app id=60 售后服务系统 status=completed
- `apaas_builder_mcp_server` db (我这边) 有 app id=74 售后服务系统 status=completed apaas_app_id=843747208942583808
- 两边主流程实际都 work，只是创建路径不同（xhh 走 save_design_draft → promote / 我走 generate_app_from_doc）

## 五点八、5/17 凌晨：双轨分工最终架构（mars 对内 / xhh 对外）

**用户分工定位**：
- **xhh 核心做对外**：v2 svc 给得小帆 dolphin 用 — strict auth + 33 工具精简 + admin SPA 重写
- **mars 核心做对内**：ai-builder 平台自身 (ai-chat / ming) — 不借助 dolphin 也能搭建/二开/全代码

按这个分工，**两套独立 MCP 实例各自服务各自的对象**：

### 对内轨道（mars）

- **实例**：ming pod 内置 `mcp_server.py` 80 工具
- **入口**：`http://127.0.0.1:8003/api/mcp/mcp`（ming 内 loopback）+ 公网 `agent.dfy.definesys.cn/ai-builder/api/mcp/mcp`
- **caller**：ai-chat agent (走 mcp_bridge.py)
- **ming env**：`MCP_INTERNAL_BASE=http://127.0.0.1:8003/api/mcp/mcp`（5/17 凌晨切回）
- **auth**：soft（Bearer MCP_API_KEY，无 strict user identity 要求）
- **改动主战场**：`apaas-builder-ai/backend/app/mcp_server.py` 和 `ai_chat/` 目录
- **deploy**：`apaas-builder-ai` repo build → ming image push → kubectl set image apaas-builder-ming

### 对外轨道（xhh）

- **实例 1**：`apaas-builder/apaas-builder-mcp-server`（33 工具 strict auth）
- **实例 2**：`apaas-mcp-server/apaas-mcp-server-v2`（68 工具）
- **入口**：`agent.dfy.definesys.cn/mcp-server/*` + `agent.dfy.definesys.cn/mcp-server-v2/*`
- **caller**：dolphin agent omnigate（带 user identity header）、第三方 SDK
- **auth**：strict（要求 X-AiBuilder-Token / X-APaaS-Token / dolphin user-token，否则 401）
- **改动主战场**：`apaas-builder-mcp-server` repo main 分支
- **deploy**：xhh 自管

### 协作铁律（避免再撞 5/16 反复覆盖事故）

1. **不互相直接动对方 deployment**：
   - mars 只动 `apaas-builder-ming` deployment
   - xhh 只动 `apaas-builder-mcp-server` + `apaas-mcp-server-v2` deployment
2. **不互相 push 对方 repo 的 main 分支**：
   - mars 改 `apaas-builder-ai`
   - xhh 改 `apaas-builder-mcp-server`
3. **共享资源（db / 用户表 / dolphin agent 配置）改动前互相通气**
4. **mcp_bridge env override 保留** — 万一以后想让 ai-chat 临时借 v2 某个特色工具，单独 env 灰度

### 历史决策回滚清单（5/17 凌晨）

- ❌ 撤销 5/16 晚"ai-chat 切流 v2"决策（实际只 work 几小时就撞 xhh strict auth）
- ❌ 撤销 5/16 夜"以 xhh 为准 = 完全跟 xhh"理解（实际是"对外以 xhh / 对内 mars 自管"）
- ❌ 撤销 5/16 夜"删 draft 流程"决策（这是 xhh 那条轨道的事，mars 不管）
- ❌ 撤销 5/16 夜"check_model_codes 改 internal-only / md 1:1 铁律"（同上）
- ✅ 保留 5/16 晚 3 个 ai-chat UX fix（duration / SSE chunk / auto-scroll）— ming repo 改动有效
- ✅ 保留 5/16 夜 `generate.py` 走 platform_envs 修法 — ming backend bug fix
- ✅ 保留双 db 命名倒挂的记录（重要历史事实）

## 六、进行中（mid-flight）

### K8s pod-per-workspace 迁移（vibe-coding 沙箱）

- 设计稿 ✅
- `vibe_coding/k8s_runtime.py` 648 行 ✅（Phase 2-4 实现）
- **Ingress 设计切方案 B**（2026-05-16）— 通配 `*.vibe-first.cn` 单 ingress 撞 5/15 "if is evil" 兼容性，改为 per-workspace 动态 ingress（k8s_runtime.py `_ensure_ingress` TODO 注释含完整骨架）
- 当前 WIP（未 commit）：
  - `k8s_runtime.py` +7 行 image fallback（hub.dfy `ai-builder/vibe-sandbox` 子 repo 未建，临时用 `apaas-builder:vibe-sandbox-20260515` tag）+ 55 行 ingress 动态化 TODO 注释
  - `61-vibe-ingress.yaml` 砍掉 dangerous ingress spec（-73），留 placeholder Service + 设计切换说明（+33）
- 未做：
  - `_ensure_ingress` / `_delete_ingress` 实现（~50 LOC）
  - 验证 sandbox image 是否真在 hub.dfy（`crane manifest hub.dfy.definesys.cn/ai-builder/apaas-builder:vibe-sandbox-20260515`）
  - DNS `*.vibe-first.cn` 切回公司公网入口
  - 阿里云 ECS nginx 反代加 vibe-first.cn 规则（SSH 运维）
  - 8 个现有 workspace 数据迁移到 subPath 路径
  - 端到端测试
- 跑通后整文件删 `docker_runtime.py`

### ai-chat 路线 ✅ 已决（5/16 晚）

**B 方案落地**：ai-chat 是产品保留功能，走 v2 svc。3 个 UX fix 上线：
- backend `agent.py`: `time.monotonic()` 算 duration（修 -0.1s 负值 bug）
- backend `agent.py`: SSE buffer 20 字符 / 40ms flush（合并细碎 chunk）
- frontend `AgentConversation.vue`: ResizeObserver + last-message-content watch（流式自动 scroll）

可退役（无 caller）：本机 `mcp_server.py` 4241 行 + `routes/online_coding.py` + `routes/vibe_coding_chat.py`。等观察 1 周再清。

## 七、已知问题 / 留尾

### 🔴 P0

- **`DOLPHIN_SERVICE_TOKEN` 2026-08-30 过期**
- **ming workspaces 不在 PVC**：`/root/apaas-builder/workspaces/` 是容器 overlay，restart 丢
- ~~**5/17 凌晨：双开发者协作流程缺失**~~ **已解决**：5/17 凌晨拍板"双轨分工"，mars 对内 / xhh 对外，各自演进 deployment 不互相覆盖。详见五点八节

### 🟡 P1

- mcp-server-v2 缺 token 自愈 wrapper（admin token 24h 过期要手动 db update）
- mcp-server-v2 `promote_draft_to_app` FK bug
- mcp-server-v2 `generate_app_from_doc` 缺 idempotency
- ming `/ai-builder/api/mcp/mcp` 公网仍 listen 401，确认无 client 后关 ingress
- v1 alias `/mcp-server/*` 已 stale，确认无 client 后清
- `routes/applications/generate.py:76` 还查 `current_user.apaas_token`（老链路）而不是 `platform_envs.token`（新链路），靠 SQL workaround 维持

### 🟡 P2

- README.md / PLAN.md 全过期，未与现状对齐
- `auth.py:632-638` `_tenant_admin_item` 校验跟 `tenant_dolphin_agents` 新表不一致
- admin UI 编辑租户 `update_tenant` 会新建 `platform_envs` 行而非 update
- fudan 用户账号未建
- mcp-server-v2 admin SPA UI 表单缺 alias 字段（ai-builder repo 已有，未移植 v2）
- **🆕 `mcp_bridge._LOADED` cache 无 TTL**（5/16 夜故障 2 教训）：进程内全局变量，v2 升级后 ming 不重启就一直 stale；加 5 min TTL invalidate（force_reload if elapsed > 5min）治本

### 🟢 P3 — 代码整洁（trial 阶段不动）

- `routes/coding.py` 3091 行 / `coding/workspace.py` 5530 行 — 巨型文件
- 4 套类 agent 目录（`agents/` / `orchestrator/` / `coding/` / `vibe_coding/`）边界混乱
- `routes/online_coding.py` 命名 stale（前端已迁 vibe-coding）
- 11 个 doc_* 模块 + 7 个 config_* 模块迭代痕迹
- `.serena/` 未加 .gitignore
- `routes/admin_mcp.py:6` 注释还写"77 工具"，5/16 union main+design 后实际 71（stale 注释，不影响逻辑）

## 八、下次接手第一步

| 场景 | 第一步 |
|---|---|
| 一般 bug fix / 改功能 | 看本文件 → 确认改的不是过渡/死代码 → 改 → **必要时同步 mcp-server-v2 repo** |
| 大架构动作 | 先确认第三节"锁定决策"是否仍 hold → 没翻案就照决策走 |
| vibe-coding K8s 收尾 | 看 `docs/vibe-k8s-migration/00-design.md` → WIP 在 `k8s_runtime.py` + `61-vibe-ingress.yaml` |
| **要改 ai-chat 工具集 / 行为** | 改 `apaas-builder-ai/backend/app/mcp_server.py` 或 `ai_chat/` 目录 → ming image rebuild + push hub.dfy + set image `apaas-builder-ming`。**完全不动 xhh 的 v2 svc** |
| **要改 v2 svc / 给 dolphin 加工具** | **跟 xhh 同步**，他主导 `apaas-builder-mcp-server` repo main + 自己 deploy。你不要直接动 |
| ai-chat UX 进一步优化 | 5/16 已修 duration/chunk/scroll 3 个 P1。剩 P0 LLM 首轮推理 14s 是 admin UI 换模型动作（gpt-5.5 → gpt-4o-mini / haiku-3.5） |

## 关联资源

- `PLAN.md` — 2026-04-23 治理 plan，Phase 0 完成，Phase 1+ 未启动
- `PLAN.vibe-preview-runtime.md` — 2026-04-28 plan，已被 K8s 迁移覆盖
- `docs/vibe-k8s-migration/00-design.md` — K8s 迁移设计稿
- `docs/dolphin-pg-migration/agent-merged-prompt-v4.1-env-discipline.md` — dolphin prompt v4.1（待用户贴）
- Memory index：`/Users/mars/.claude/projects/-Users-mars-Vibe-Coding-apaas-builder-ai/memory/MEMORY.md`
