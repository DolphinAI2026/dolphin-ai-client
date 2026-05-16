# 当前状态（STATE.md）

> 更新时间：2026-05-16
> 维护规则：每次重大上线 / 决策后追加；只写 fact，不写 plan。
> 关系：`README.md` 是入门文档（已过期）；`PLAN.md` 是治理目标（Phase 1+ 未启动）；**本文件是现状的 source of truth**。

## TL;DR

ai-builder 当前定位是 **MCP 工具供应商**，对接 dolphin 作为 agent 运营平台。生产部署完全在公司 KubeSphere k8s，两个 pod：

- `apaas-builder-ming`（本 repo） — backend + frontend + admin SPA + 内置 `mcp_server.py` 80 工具，**目前仅 ai-chat loopback 在用**
- `apaas-builder-mcp-server-v2`（独立 repo） — 5 个 FastMCP 实例合并暴露 71 工具，dolphin agent 实际入口

4 个客户租户共享 3 个 dolphin agent，全在线。两个 MCP server 在 53 个工具上重复（双向漏同步是当前最痛的运维 bug 源）。

## 一、当前部署（事实）

### 网络入口

| 域名 / 路径 | 现状 | 后端 |
|---|---|---|
| `agent.dfy.definesys.cn/ai-builder/*` | **公网主入口** | ming pod (backend + frontend) |
| `agent.dfy.definesys.cn/mcp-server-v2/*` | **dolphin agent 实际调** | mcp-server-v2 pod (FastMCP) |
| `agent.dfy.definesys.cn/mcp-server/*` | v1 alias，已 stale | 同 v2 pod |
| `agent.dfy.definesys.cn/ai-builder/api/mcp/mcp` | 公网仍 listen 401，dolphin 已不走 | ming pod 内置 mcp |
| `df-aigc.dfy.definesys.cn/*` | StatefulSet `apaas-builder-0`，跑 stale image | df-aigc 团队不归本项目 |
| `*.vibe-first.cn` | DNS 仍指老阿里云 ECS，已断 | 待 K8s 迁移落地 |

阿里云 ECS `39.103.201.110` 还活作公网入口反代 + 24-48h 热备，不是业务跑在那。

### Pod / 最新 image

| Pod | Image | 备注 |
|---|---|---|
| `apaas-builder-ming` | `hub.dfy.definesys.cn/ai-builder/apaas-builder:20260516-admin-mcp-dotenv` | 当前 HEAD `692c361` |
| `apaas-builder-mcp-server-v2` | `:20260514-v2` + user-token 补丁 `:20260515-user-token` | 独立 repo |
| `apaas-builder-mcp-server` (同 deploy 别名) | `:20260516-templatetype-fix` | |

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
   - 不再演进 AIChatPage / VibeChatPanel / CodingPage 内置对话
   - 不在 ai-builder 复刻 dolphin agent 能力
   - 不做双向集成幻想

2. **vibe-coding 用 K8s pod-per-workspace**（2026-05-15）
   - 设计稿：`docs/vibe-k8s-migration/00-design.md`
   - 不修补 docker 路线（老 ECS 已死，不恢复）

3. **多租户身份 1:1:1 强绑**（2026-05-13）
   - ai-builder tenant ↔ aPaaS 租户 ↔ dolphin customerName 严格 1 对 1
   - 切租户 = 切真实 aPaaS 租户落地

4. **mcp-server-v2 是新主线**（2026-05-11 立项 / 5-14 切流）
   - 本 repo `mcp_server.py` 4241 行 + 80 工具是历史遗留

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

🔒 **A 方案锁定（2026-05-16）**：跟 5-14 锁定决策一致 — ai-chat 内置对话不再演进，整条链路待 K8s 收尾后一次性 PR 清掉（净删 ~6000 行）。

后端：
- `mcp_server.py` 4241 行 + 80 工具（删它前提：ai-chat / mcp_bridge 也删）
- `routes/ai_chat.py` + `ai_chat/mcp_bridge.py` + `ai_chat/` 整目录
- `routes/vibe_coding_chat.py`
- `routes/online_coding.py` + `routes/online_coding_runtime.py`（前端已 redirect /vibe-coding/*，后端命名 stale）

前端：
- `views/AIChatPage.vue` + `components/HelpAssistant.vue`
- `views/CodingPage.vue`（旧 SPEC 双栏，已被 ChatPage 覆盖）
- `router/index.ts` 里 `/ai-chat/:id?` `/coding` 路由 + `main.py` 路由注册

### ❓ 死代码（删之前先 grep 引用）

- `views/WorkspaceShell.vue`（router 直接 redirect 走，无引用）
- `vibe_coding/docker_runtime.py`（K8s 迁移落地后整文件删）
- `generator_v2.py` 的 v1 残迹（未扫）
- 7 条历史 router redirect：`/online-coding/*`、`/ide`、`/generate/:id`、`/work/:appId`、`/settings?tab=envs` 等

### 🗑️ 已删（2026-05-16）

- `routes/app_adjust_chat.py` (-371 行)
- `components/AppAdjustDrawer.vue` (-594 行)

## 五、双 MCP server 53 工具重复（最痛运维 bug 源）

- ai-builder-ai 独有 **27 个**（含 vibe_* 10 个老 host docker 工具 + aPaaS 精细 CRUD 16）
- v2 独有 **24 个**（含 draft 流程 5 / handoff 2 / 救援 / lookup 等新工具）
- 重叠 **53 个** — 每次 bug 修要改两个 repo

**典型漏同步案例**：

- 5/16 `_get_build_output_dir` PAGE_CUSTOM_DEV：v2 早修，ai-builder-ai 漏改 → 误报 BUILD_FAILED
- 5/15 token 自愈 wrapper：ai-builder-ai 改了，v2 没移植 → admin token 过期要手动 db update

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

### ai-chat 路线决策（卡总闸）

只要决策出来，后面可一口气清掉 ~5000 行代码（`mcp_server.py` 4241 + `routes/ai_chat.py` + `views/AIChatPage.vue` + `HelpAssistant.vue` + `ai_chat/mcp_bridge.py`）。

选项：
- **A. 彻底废 ai-chat**：清完。dolphin 是唯一对话入口。
- **B. ai-chat 迁 v2**：改 `mcp_bridge.py` 走外部 v2 svc，保留 ai-chat 作为本地调试 / 对外演示用。但 v2 缺 11 个 ai-builder-ai 独有的查询工具，迁前要先并 v2。

## 七、已知问题 / 留尾

### 🔴 P0

- **`DOLPHIN_SERVICE_TOKEN` 2026-08-30 过期**
- **ming workspaces 不在 PVC**：`/root/apaas-builder/workspaces/` 是容器 overlay，restart 丢

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
| ai-chat 路线决策（卡总闸） | 见第六节，需要用户拍板 |

## 关联资源

- `PLAN.md` — 2026-04-23 治理 plan，Phase 0 完成，Phase 1+ 未启动
- `PLAN.vibe-preview-runtime.md` — 2026-04-28 plan，已被 K8s 迁移覆盖
- `docs/vibe-k8s-migration/00-design.md` — K8s 迁移设计稿
- `docs/dolphin-pg-migration/agent-merged-prompt-v4.1-env-discipline.md` — dolphin prompt v4.1（待用户贴）
- Memory index：`/Users/mars/.claude/projects/-Users-mars-Vibe-Coding-apaas-builder-ai/memory/MEMORY.md`
