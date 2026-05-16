# 当前状态（STATE.md）

> 更新时间：2026-05-16（夜 — ai-chat 切流 v2 + 3 UX fix + 92→82 工具裁剪 完结）
> 维护规则：每次重大上线 / 决策后追加；只写 fact，不写 plan。
> 关系：`README.md` 是入门文档（已过期）；`PLAN.md` 是治理目标（Phase 1+ 未启动）；**本文件是现状的 source of truth**。

## TL;DR

ai-builder 当前定位是 **MCP 工具供应商**，对接 dolphin 作为 agent 运营平台。**ai-chat 是产品保留功能**（5/16 晚拍板修正），不再视为过渡形态。生产部署完全在公司 KubeSphere k8s，**3 个 deployment 跑 MCP**（5/16 晚摸清拓扑发现实际比之前 STATE 描述多 1 个）：

- `apaas-builder/apaas-builder-ming`（本 repo） — backend + frontend + admin SPA + 内置 `mcp_server.py` 80 工具。**5/16 晚切流后 ai-chat loopback 也不再用本机 80 工具**，改走 v2 svc → 本机 mcp_server.py 实际无 caller，**可以进入退役**
- `apaas-builder/apaas-builder-mcp-server`（独立 repo `apaas-builder-mcp-server`，**ming 内 admin SPA + ai-chat 切流后的真实 backend**） — 5/16 夜升 `:20260516-e35cca2-deterministic-md` image 后 **81 工具**（92 - 删 10 - 隐藏 check_model_codes 1 个，避免 LLM 篡改 md modelCode）
- `apaas-mcp-server/apaas-mcp-server-v2`（同 repo 不同 ns，**dolphin agent 公网 `/mcp-server-v2/*` 入口**） — 跑 `:20260515-user-token` 68 工具，**比 apaas-builder ns 那个落后**，下次 sync

4 个客户租户共享 3 个 dolphin agent，全在线。**ai-chat 切流后两边主 source of truth 收敛到 v2 repo**，dual repo drift 痛点缓解但未消除（68 vs 82 仍 drift 等下次同步）。

## 一、当前部署（事实）

### 网络入口

| 域名 / 路径 | 现状 | 后端 |
|---|---|---|
| `agent.dfy.definesys.cn/ai-builder/*` | **公网主入口** | ming pod (backend + frontend) |
| `agent.dfy.definesys.cn/mcp-server-v2/*` | **dolphin agent 实际调** | `apaas-mcp-server/apaas-mcp-server-v2` (68 工具，落后版) |
| `agent.dfy.definesys.cn/mcp-server/*` | **5/16 实测：不是 v2 alias**，是独立 deployment | `apaas-builder/apaas-builder-mcp-server` (82 工具，5/16 夜裁剪) |
| `agent.dfy.definesys.cn/ai-builder/api/mcp/mcp` | 公网仍 listen 401。**5/16 晚 ai-chat 切流后内置 mcp 实际无 caller** | ming pod 内置 mcp (4241 行 80 工具，可退役) |
| `df-aigc.dfy.definesys.cn/*` | StatefulSet `apaas-builder-0`，跑 stale image | df-aigc 团队不归本项目 |
| `*.vibe-first.cn` | DNS 仍指老阿里云 ECS，已断 | 待 K8s 迁移落地 |

阿里云 ECS `39.103.201.110` 还活作公网入口反代 + 24-48h 热备，不是业务跑在那。**注**：今天实测 SSH 22 端口 banner timeout（sshd hang 或 fail2ban），上次确认 work 的 5/15 之后状态可能变了。

### Pod / 最新 image（5/16 晚实测）

| Deployment | Namespace | Image | 备注 |
|---|---|---|---|
| `apaas-builder-ming` | `apaas-builder` | `hub.dfy.definesys.cn/ai-builder/apaas-builder:20260516-uxfix` | HEAD `def942c`（含 3 UX fix + ai-chat v2 切流配置） |
| `apaas-builder-mcp-server` | `apaas-builder` | `hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:20260516-e35cca2-deterministic-md` | **81 工具**（v2 repo HEAD `e35cca2`：删 10 工具 → 修 9 docstring → 隐藏 check_model_codes）。**tag 用 commit hash 后缀防覆盖**。registry: `hub.dfy.definesys.cn/ai-builder/` |
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

2. **ai-chat 跟 dolphin 调同一批 MCP 工具**（2026-05-16 晚）
   - 实现层：ai-chat 通过 `MCP_INTERNAL_BASE=http://apaas-builder-mcp-server:8004/api/mcp/mcp` 走 v2 svc
   - 不再调本机 `mcp_server.py` 80 工具，两边收敛到 v2 repo 92 工具
   - dual repo 同步痛点缓解；本机 `mcp_server.py` 4241 行可退役

3. **vibe-coding 用 K8s pod-per-workspace**（2026-05-15）
   - 设计稿：`docs/vibe-k8s-migration/00-design.md`
   - 不修补 docker 路线（老 ECS 已死，不恢复）

4. **多租户身份 1:1:1 强绑**（2026-05-13）
   - ai-builder tenant ↔ aPaaS 租户 ↔ dolphin customerName 严格 1 对 1
   - 切租户 = 切真实 aPaaS 租户落地

5. **mcp-server-v2 是新主线**（2026-05-11 立项 / 5-14 切流 / 5-16 晚 ai-chat 也切流）
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
- **🆕 5/16 晚 image 覆盖事故**：`apaas-builder-mcp-server` deployment 没有 GitOps 锁，任何 session/人 set image 立即生效覆盖。需要：(1) 制定 push 流程规范（git tag 必带 commit hash 后缀）；(2) 考虑 ArgoCD / FluxCD 锁定 deployment image 来自 git；(3) `mcp-server-config` secret 的 ALLOWED_HOSTS 已加内部短名 6 个（5/16 晚），不需要再补

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
| **要改 v2 image** | **先 `kubectl -n apaas-builder get deployment apaas-builder-mcp-server -o jsonpath='{.spec.template.spec.containers[0].image}'` 看当前 tag，再决定改不改**（5/16 晚被覆盖过一次）。**新 tag 规范**：`:YYYYMMDD-<git_short_sha>-<topic>`（5/16 夜起强制） |
| ai-chat UX 进一步优化 | 5/16 已修 duration/chunk/scroll 3 个 P1。剩 P0 LLM 首轮推理 14s 是 admin UI 换模型动作（gpt-5.5 → gpt-4o-mini / haiku-3.5） |
| sync v2 公网入口 image | `apaas-mcp-server/apaas-mcp-server-v2` 还跑 68 工具 stale 版，dolphin agent 公网入口看不到 82 工具新版。需 build v2 image 也 push hub-snapshots/mars + set image |

## 关联资源

- `PLAN.md` — 2026-04-23 治理 plan，Phase 0 完成，Phase 1+ 未启动
- `PLAN.vibe-preview-runtime.md` — 2026-04-28 plan，已被 K8s 迁移覆盖
- `docs/vibe-k8s-migration/00-design.md` — K8s 迁移设计稿
- `docs/dolphin-pg-migration/agent-merged-prompt-v4.1-env-discipline.md` — dolphin prompt v4.1（待用户贴）
- Memory index：`/Users/mars/.claude/projects/-Users-mars-Vibe-Coding-apaas-builder-ai/memory/MEMORY.md`
