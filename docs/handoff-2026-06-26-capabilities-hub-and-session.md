# 交接 — 2026-06-26 大会话(后台配置 tab + 知识库评审修复 + 能力中心 hub)

> 换会话接手必读。本会话很长,做了三大块。**能力中心 hub 11 个文件未提交**,其余已推 origin/dev。

## 一句话状态

- **已推 origin/dev**(`cf762c50` = local dev = origin/dev,已同步):①后台配置 tab + 其 TDZ 白屏修复 + 去 FAB;②知识库评审后的修复。
- **未提交**(working tree,dev 上):**能力中心(Capabilities Hub)** 11 个文件 —— 功能完成、build+测试过、真机验过(MCP 那 tab 用户重登后亲验原生不套娃)。**待提交推送**。
- 本机 `:8000` 后端是本会话重启的进程(pid 93128,含知识库路由+表);本地知识库已 seed 7 篇。前端 dev `:5173` 在跑(预览会话 token 已过期,要看需重登)。
- ⚠️ 工作树里还有**别会话的未提交工作**(git-P3 git_connection/GitCredentialPicker 等)——别碰,提交时只 `git add` 自己的文件。多会话并发同一工作树,见 [[concurrent_sessions_shared_worktree_git_hazard]]。

## 一、后台配置 tab(已推)

- `50d1faef` feat:ChatPage 顶部加第三 tab「后台配置」(code=`admin`),内嵌 apaas 应用管理后台 `app-store/edit-app`。复用 `InAppBrowser`(trusted-url)+ 后端 `GET /applications/{id}/editor-url`(不传 menu → admin 总览),**host/tid/appId 全来自绑定 PlatformEnv,动态不写死域名**。
- `90e0e90a` fix:**进应用即白屏的 TDZ bug** —— `watch([topTab, existingAppId], …)` 放在了 `existingAppId` 的 `const` 声明之前 → setup 执行到 watch 时 TDZ 崩。修=watch 移到声明后。见 [[chatpage_setup_tdz_whitescreen]]。build:nocheck/vue-tsc 抓不到(运行时),改 ChatPage 必 preview 真跑 `/chat`。
- `201ac548` style:后台配置 tab 不显配置助手悬浮 FAB(FAB 的 v-if 再排除 `topTab==='admin'`)。
- DMG:`Dolphin Code_0.2.37_aarch64.dmg` 打过(`src-tauri/target/release/bundle/dmg/`),但**那是后台配置时打的,不含能力中心**。打包坑:`bundle_dmg.sh` 失败常因**残留挂载卷**(`/Volumes/Dolphin Code*`)占名,`hdiutil detach` 清掉再打;签名 exit 1 是老问题(DMG 在那之前已生成)。

## 二、知识库评审 + 修复(已推 `cf762c50`)

知识库模块是**别会话**做的(`84048d12..20152681`,已在 dev)。本会话评审后修了:
- **#1 必修**:seed 7 篇 slug 带 `category/` 前缀(含 `/`)→ 与 `/docs/{slug}` 路由不兼容,管理页对默认文档编辑/删除/详情全 404。改无斜杠 kebab slug + 正文互链同步 + `test_seed_slugs_are_route_safe` 守卫。
- **#3**:权限测试偏弱 → 补 `test_all_endpoints_require_auth` + `test_authenticated_non_admin_forbidden`(真 require_platform_admin 对非管理员 403)。
- **#4**:前端 3 处 catch 改取 `err.response.data.detail`。
- **#2 防漂移**:记入 plan 为后续项 + 标「知识库版为唯一权威」(不动退役引擎 prompt)。
- ⚠️ 评审还发现:**本机 :8000 后端曾是知识库合入前的旧进程**(404 + 无表)。本会话已重启(create_all 建表)+ `python backend/scripts/seed_knowledge_docs.py` seed 7 篇。memory 老坑:**改后端必重启进程**(run.py reload=False)。
- 详见 [[knowledge_base_2026_06_26]]。

## 三、能力中心 Capabilities Hub(⚠️未提交,11 文件)

把「技能库/知识库/MCP/AI网关」收进一个 hub 页,补齐 RailSidebar 早规划但延后的「完整 hub」。spec/plan:
`docs/superpowers/specs/2026-06-26-capabilities-hub-design.md` + `docs/superpowers/plans/2026-06-26-capabilities-hub.md`。

### 最终形态(几轮迭代后)
- 路由 `/hub`(`CapabilitiesHubPage.vue`),顶部 tab 条 `?tab=`;`/skills`、`/knowledge` redirect 进对应 tab;RailSidebar 入口「**能力中心**」(改过名,原「得小帆·共性能力」)链 `/hub` + 删独立知识库 footer 入口。
- **4 个 tab 全部原生组件就地渲染,零 iframe / 零 admin-spa 套娃**:
  - 技能库 → `SkillLibraryPage`(access=all)
  - 知识库 → `KnowledgeBasePage`(platformAdmin,desktop 隐藏)
  - MCP → `McpToolsPage`(platformAdmin,desktop 隐藏)
  - AI网关 → `PlatformEnvs only="llm"`(tenantAdmin)= 模型配置
- tab 可见性按 `isPlatformAdmin`/`isTenantAdmin`/`isDesktop` 过滤(纯函数 `useCapabilitiesHub.ts` + spec,9 测)。

### 关键设计点 / 踩坑(durable)
- **原生页都自带壳**:`SkillLibraryPage`/`KnowledgeBasePage`/`PlatformEnvs`/`McpToolsPage` 都 `<BuilderFrame>`,而 `BuilderFrame` 内部包 `<WorkbenchShell>`(=带左栏 rail 的整壳)。所以它们是**整页**,不是可嵌内容。直接塞进 hub tab → iframe tab 没壳没左栏、原生 tab 壳套壳。
  - **修法**:`WorkbenchShell` `provide('inWorkbenchShell', true)`;`BuilderFrame` `inject` 到则**不再套第二层壳**(只渲 builder-view);`CapabilitiesHubPage` 自己包一层 `<WorkbenchShell>`。→ 唯一左栏 + tab 条 + 内容,4 tab 布局一致。
- **MCP/AI网关 曾走 admin-spa iframe 内嵌(chromeless 去壳),已废弃**:实测把整个 admin-spa 平台管理控制台套进 tab=套娃,且 chromeless 在真机没生效。改全原生后,**删了 `AdminSpaEmbedFrame.vue`、回滚了 `buildPlatformAdminIframeSrc` 的 chromeless 参数 + admin-spa `AdminLayout` 的 chromeless 改动**(故 platformAdminEmbedState.ts / AdminLayout.vue 不在改动集)。
- **el-button is-link 配色 bug(全局,顺手修)**:`.el-button--primary/--danger` 用 `background !important`,而 `.el-button.is-link` 只改 color 没重置背景 → link 型按钮变实心色块、文字色=背景色不可见(暗色尤甚)。`styles/builder.css` 给 is-link 补 `background/border 透明 !important`。
- **isActive 修**:RailSidebar hub 入口的 `<a>` href/isActive 原写死 `/skills`,改 `/hub`(否则进 hub 不高亮)。

### 11 个未提交文件
改:`BuilderFrame.vue`、`WorkbenchShell.vue`、`components/v2/RailSidebar.vue`、`router/index.ts`、`styles/builder.css`、`views/PlatformEnvs.vue`(加 `only` prop)。
新:`composables/useCapabilitiesHub.ts` + `.spec.ts`、`views/CapabilitiesHubPage.vue`、上述 spec + plan 文档。
(`McpToolsPage.vue` 只是被 import,未改;`AdminSpaEmbedFrame.vue` 已删。)

### 验证状态
- 全量前端 vitest **296 passed**(1 个 `TenantLogsPage` 预存失败,无关);build:nocheck ✓;vue-tsc 新符号零错。
- preview 真机验过:能力中心 4 tab、技能/知识原生单壳 + 左栏常驻、AI网关原生模型配置、`/skills`+`/knowledge` 重定向、能力中心改名 + 高亮、暗色 link 按钮修复。**MCP tab 用户重登后亲验:原生、不套娃 ✓**。

### 待办 / 决策
1. **提交 + 推送这 11 文件**(只 `git add` 自己的,别带 git-P3)。建议 commit msg:`feat(hub): 能力中心 hub(技能/知识/MCP/AI网关 4 tab 全原生)+ BuilderFrame 嵌套壳收敛 + link 按钮配色修复`。
2. **AI网关「看不到接入的模型」**(用户提):根因=`/llm-configs`(本租户自管)空 vs `/llm-configs/options`(含**平台共享兜底**)有 3 个(gpt5.5-dfy 默认/fandian-gpt-5.5/minimax3)。模型配置页只列本租户自己加的。**可选增强**:AI网关 tab 显示 effective/available 模型(含共享默认),而非本租户自管空列表。见 [[llm_config_own_vs_shared_2026_06_26]]。
3. **「新加 MCP」新功能**(用户问):现**无**接外部/第三方 MCP server 的能力(122 工具是后端内置 FastMCP;服务清单主/问题分诊是 `mcp_platform.py:460` 硬编码的对外暴露端点)。要做=独立新需求(后端存外部 MCP 配置 + MCP client 连 + 工具发现 + 并进 agent;前端增删 UI),需单独 brainstorm→spec→plan。
4. 状态列暗色下 el-tag 标签看不见(疑似同 link 按钮类的暗色对比度),未修。
5. 能力中心要进桌面包需**重打 DMG**(当前 DMG 不含它)。

## 工程纪律提醒
- 多会话共享同一工作树:提交只 `git add` 指定文件(禁 `-A`);改前验 HEAD 稳定;见 [[concurrent_sessions_shared_worktree_git_hazard]]。
- 改 ChatPage / 巨型 SFC 必 preview 真跑;改后端必重启 :8000。
- 本地 DB = SQLite `/tmp/fb_demo.db`;前端 dev 经 vite 代理 `/api`、`/ai-builder/admin` → :8000。
