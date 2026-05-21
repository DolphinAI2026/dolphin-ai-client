# Session Handoff · 2026-05-21（接续 2026-05-20 v2 之后的 10 commits）

> 接 `docs/handoff-2026-05-20-v2-session-end.md`（v2）。本次 session 把 0-1 创建应用的全链路体验做透，外加按用户 audit 反馈派 3 个 agent 并行修了 P0 UX 缺陷。

---

## 🚀 接手快速指南

### 仓库 + 分支
- **GitHub**: https://github.com/Mars-hub404/apaas-builder-ai
- **分支**: `local/ui-redesign-2026-05-20`（继续用这个，没新开）
- **最新 HEAD**: `de3a041`
- **主分支**: `main`（**不要 PR / 不要 merge 到 main**——还有 P2 留尾）

### 拉代码

```bash
cd /path/to/apaas-builder-ai
git fetch origin
git checkout local/ui-redesign-2026-05-20
git pull --ff-only origin local/ui-redesign-2026-05-20

git log --oneline -1
# 应看到: de3a041 feat(builder-chat): 删左右重复的部署进度面板 + 完成态 hero CTA
```

### 起服务（3 个进程）

```bash
# Terminal 1: backend
cd backend && source venv/bin/activate && python -m uvicorn app.main:app --reload --port 8000

# Terminal 2: frontend
cd frontend && pnpm dev

# Terminal 3: admin-spa (可选)
cd admin-spa && pnpm dev
```

- 主入口: http://localhost:5173/ai-builder/
- 后端 API: http://localhost:8000/api/
- aPaaS 环境: `https://apaas-trial.definesys.cn/backend`（trial）

### 登录账号

- admin / dVZePRG1Pdgrp4（aPaaS trial 平台管理员，能看 45+ 个 customer 租户）

---

## 📋 本次 session 改了什么（10 个 commit，时间倒序）

| Commit | 范围 | 改的核心点 |
|--------|------|----------|
| `de3a041` | **frontend ChatPage** | 删左右重复的「创建过程」/「部署进行中」面板；部署完成态加 hero CTA（🎉 + 「{app}」已部署完成 + 大蓝按钮"打开应用 →"）|
| `525a214` | **frontend AIChatPage + 通用组件** | 工具卡 "0.0s" 升级为中文摘要 chip（按工具名解析）；应用就绪自动 inline CTA 卡片 |
| `03cba9c` | **backend ai_chat agent** | agent loop 末尾如果 LLM 返回空 content → inject 强制总结 system reminder；`generate_app_from_doc` / `update_app_from_doc` 的 `md_content` 自动落 AIChatArtifact 表 |
| `3a7a3d4` | **frontend App.vue** | 下线 dolphin agent 浮窗 (HelpAssistant)。dolphin_sso 后端路由 + HelpAssistant.vue + DolphinAgentEmbed.vue 全保留可逆 |
| `90c1eda` | **frontend ChatPage** | apaas_app_id=NULL 的 draft 应用隐藏 "→ 自开发" 按钮（formId/uuid 还没生成） |
| `cb7746c` | **frontend Apps** | 状态文案 "SPEC 设计 42%" → "待部署 70%"（避免用户误以为反复生成 SPEC） |
| `07b7574` | **frontend AIChatPage** | artifact 头加「→ 生成应用」按钮，一键触发 generate_app_from_doc |
| `5521d0b` | **frontend (tabs system)** | 浏览器风格多 tab 顶栏；左 nav + 应用都 tab 化；KeepAlive max=10 LRU 缓存 |
| `10b3562` | **backend platform_proxy** | env.tmpl.js script src 加 `?_cb=<ts>` 绕过浏览器 disk cache，根治 iframe 跨环境跑 dev8 |
| `8980c38` | **backend platform_proxy** | URL rewrite + Cache-Control: no-cache + html script rewrite |

---

## 🎯 本次 session 的 4 个里程碑

### 1. aPaaS 环境从 POC 切到 trial（包含一系列连环 bug）

- `backend/.env`: `APAAS_BASE_URL=https://apaas-trial.definesys.cn/backend`
- 修了 3 处副作用：
  - `auth.py` 平台管理员的 membership 现在能拿全部 trial 租户（不再只 default 一个）
  - `auth.py` + `mcp_platform.py` PlatformEnv.base_url 保留 `/backend` 后缀
  - `platform_proxy.py` iframe env.tmpl.js URL rewrite + 缓存绕过

实测：admin 登录 → 切租户 → /apps 看应用列表 → 进应用看 iframe 全链路通。

### 2. Tab 系统 Scope B（KeepAlive 多 tab 浏览器化）

- 新文件 `frontend/src/stores/tabs.ts`（Pinia store，localStorage 持久）
- 新文件 `frontend/src/components/v2/TabStrip.vue`
- `App.vue` 把 RouterView 包进 `<KeepAlive :max="10">` + `:key="$route.fullPath"`
- `RailSidebar.vue` 的 `go(path)` 同时调 `tabsStore.openTab(...)`
- `Apps.vue` 的 openApp / openDialog 都走 tab

效果：左侧 nav 7 项各自 tab 化 + 打开的应用每个一个独立 tab，切来切去都是缓存的，不重 mount。

### 3. dolphin agent 浮窗下线 + /ai-chat 接 MCP 工具

**关键发现**：之前以为 dolphin agent 浮窗（HelpAssistant.vue）是唯一能调 MCP 工具的入口。E2E audit 后才发现 `/ai-chat` 内置 gpt-5.5 通过 `backend/app/ai_chat/mcp_bridge.py` 已经 lazy 拉本机 MCP server 71 工具，能调 generate_app_from_doc / deploy_application / publish_application 等。

所以浮窗其实是冗余的入口，跟 Landing 输入 → /ai-chat 那条路径是平行轨道。决策：下线浮窗，统一一条路。

实测 0-1 创建"物料管理系统"：Landing 输入 → /ai-chat → gpt-5.5 自动调 5 个工具 → app_id=6 + apaas_app_id=845288026266402816 + iframe 能打开。

### 4. 3 个 agent 并行修 P0 UX 缺陷

E2E audit 发现 3 个 UX 痛点 → 派 3 个独立 agent 修：
- **Agent A**（backend agent.py + tools.py）：跑完工具 LLM 沉默时强制总结 + md 落 artifact
- **Agent B**（AIChatPage + ToolCard）：工具卡摘要 chip + 应用就绪 CTA 卡片
- **Agent C**（ChatPage）：删左右重复面板 + 完成态 hero CTA

3 个 agent 操作独立文件 0 冲突，各自跑完 typecheck 都过。

---

## 📊 关键架构 / 数据流（一句话提示）

### 0-1 创建低代码应用的工具链

```
用户 Landing 输入 → /ai-chat/X (gpt-5.5)
    ↓ (agent.py loop + mcp_bridge.py)
agent 自动按 ai-builder prompt 调：
    1. list_platform_envs       → 默认环境
    2. validate_builder_doc     → 校验 agent 内部生成的 SPEC md
    3. generate_app_from_doc    → 解析 md + 落 ai-builder DB（拿 app_id）
                                  ★ 03cba9c 后：md 自动落 AIChatArtifact 表
    4. deploy_application       → SSE 25s 早返 + 后台续跑（拿 apaas_app_id）
    5. get_application          → 拿应用 URL
    ↓
agent 最终总结 + CTA 卡 "打开应用 →"（525a214）
    ↓
用户点 → /chat?app_id=X iframe 加载得帆云后台
```

### 三个关键页面区分

| 路径 | 文件 | 用途 |
|------|------|------|
| `/ai-chat/X` | `AIChatPage.vue` | 跟 gpt-5.5 + MCP 工具 agent 对话，**0-1 创建应用** |
| `/chat?app_id=X` | `ChatPage.vue` | 已有应用进入后看 aPaaS iframe + 配置助手 |
| `/landing` | `Landing.vue` + `LandingComposer.vue` | 入口，3 mode picker + 输入框 |

千万**别搞混 AIChatPage 和 ChatPage**——名字几乎一样但完全不同代码路径。

### dolphin 浮窗虽然下线但后端保留

- `App.vue` 的 `<HelpAssistant>` 组件渲染已删
- 文件全留：`frontend/src/components/HelpAssistant.vue`、`DolphinAgentEmbed.vue`、`backend/app/routes/dolphin_sso.py`、`tenant_dolphin_agents` 表
- 想恢复就在 App.vue 加回 import + `<HelpAssistant v-if="showAssistant" />`

---

## 🚧 留尾 / 下次接手做什么

### P0（用户 audit 还在 backlog 的）

- [ ] **验证 Agent A 的 final summary 注入实际效果** — 创建新应用看 agent 跑完 5 工具后是否真有总结文字 + 右侧产物面板自动出现 SPEC md（本次 session 只做了 smoke test，没在 live 浏览器跑完整新流程）
- [ ] **验证 Agent C 的 hero CTA** — 新建应用部署"中间窗口"显示是否正确（现有 app_id=6 已经 isPostDeploy，走 iframe 分支不显示 hero）

### P1（task #4 + #5）

- [ ] **task #4**: P1 Stage 1 余 — backend parser `models.py` add_rewrite 接入
- [ ] **task #5**: P2 ChatPage orphan script 清理（28+ 死 computed / function / ref）
- [ ] **工具卡 0.0s** 现在改成中文摘要 chip 了，但工具实际耗时还想看的话可以同时显示（chip + 时长两边都有）

### P2（中等优先级）

- [ ] **Landing 输入区跳转过渡** — 现版本点"开始对话"是硬跳 `/ai-chat/X`，用户视觉上 prompt 从屏幕中央跳到右上，没动画。可以加个 fade/slide
- [ ] **工具卡的 0.0s** 工具实际耗时短不显示也可以接受，但建议至少保留时长字段（现版本被中文摘要覆盖了）
- [ ] **AIChatPage tool_call_delta** 一段疑似 stale orphan 代码（Agent B 报告里提到，未清）

### P3（探索）

- [ ] **builder agent prompt 升级**：现 SYSTEM_PROMPT_UNIFIED 在 `backend/app/ai_chat/agent.py:35-130`，针对 0-1 创建可以再补强（"创建完务必告诉用户 app_view_url"等约束）。但 Agent A 已经加了系统级 fallback，prompt 层可以慢慢迭代
- [ ] 0-1 创建支持上传 docx/pdf 设计稿 → 先 read_attachment + run_python 解析 → 再 generate_app_from_doc

---

## 🔑 关键提示（避免重复踩坑）

1. **`/ai-chat` ≠ `/chat`** — 大部头文件名几乎一样但完全两条路径，编辑前确认
2. **`/chat?app_id=X` 有 3 个状态**：
   - 未部署（apaas_app_id=NULL）— 显示 SPEC 创建过程
   - 部署中（isDeploying）— 显示 placeholder
   - 已部署（isPostDeploy）— 显示 iframe + 配置助手（hero CTA 不显示）
3. **MCP_API_KEYS 必须在 backend/.env**，否则 mcp_bridge 拉不到工具列表，agent 退化到 base 4 工具（只能 write_artifact / read_attachment / run_python / ask_clarifying_question）
4. **不要碰 `mcp_server.py` 里的 generate_app_from_doc 工具实现** — 那个对 dolphin/Cursor/Claude 外部 client 也共用。Side effect（如 artifact 落表）放 ai-chat 层做
5. **tsbuildinfo / pnpm-lock 别提交** — admin-spa/tsconfig.tsbuildinfo 是构建产物每次 build 都变；pnpm-lock.yaml 是 pnpm 自动写的（项目用 npm）
6. **trial 平台 admin 看到 45+ 个租户** — 这是平台管理员的实际权限，不是 bug。切租户 dropdown 会显示一长串

---

## 📞 联系方式

有问题问 Mars（chenqingyu219@gmail.com）。

session 12（/ai-chat/12 物料管理系统搭建）保留在 DB 里，可以拿来回放 + 看工具卡新摘要效果。
