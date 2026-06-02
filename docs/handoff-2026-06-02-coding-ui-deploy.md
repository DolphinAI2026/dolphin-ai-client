# Handoff 2026-06-02 — Coding 会话区 UI 统一 + 自开发「装回应用/重新发布」+ 分场景入口

> 一个超长 session 的交接。两条线都已 **合入 `dev`**(工作树干净,`dev` 领先 `origin/dev` 约 33 commit,**push 自便**)。新 session 拿这份 + 下面的 spec/plan 就能直接接着干。

## TL;DR
- **线 A — Coding↔Builder 会话区 UI 统一**:已完成并验证(commit `8759790`)。Coding 消息区的 thinking/tool/status 切到 AgentConversation **原生 kind**,删了 ~165 行死 CSS。
- **线 B — AI Coding 自开发「装回应用 + 重新发布」+ 分场景入口**:T1–T6 已完成并验证(后端 pytest 3 绿 + 前端 build 绿 + 分场景入口 live 目视对齐原型),合入 `dev`(`369b68f`→`a5638e3`)。**T7(真实 trial 部署 e2e)未跑,需你监督**。
- **两个 follow-up**:① 真实 e2e(下面有步骤);② `df-apaas-cli` build 失败会卡住部署(已 spawn 一个任务 chip,标题「调查自开发包 npm build 失败(df-apaas-cli E404)」)。

---

## 线 A:Coding 会话区 UI 统一(已完成 `8759790`)
**背景**:用户反馈 Coding 和 Builder 会话区不一致。**关键发现**:Coding 早就用了 `<AgentConversation :messages="agentMessages">`,只是把所有消息塞进 `#custom` slot 重渲自有 markup,所以 native 样式没生效。
**做法**:`CodingPage.vue` 的 `agentMessages` 映射里,把有 native 对应的类型改走原生 kind:
- `thinking` → `kind:'thinking'`(原生斜体);`tool` → `kind:'tool'`(ToolCard 芯片「已完成 · 读取 X ›」,`toolPayloadFromStreamMsg` 去 emoji 解析 content);`status` → `kind:'status'`(居中 pill,stepDone 补 ✓)。
- `#custom` slot 精简到只剩 `file_write/file_edit` + `command`(native 无对应 kind)。
- `ToolCard.vue`:`verbLabel` 遇 name 含中文时不叠动词(避免「调用 读取 X」);Builder/AIChat 的 ASCII 工具名不受影响。
- `read_query.py`:READ 应用列表 prompt 固定 4 列 `序号|应用名称|应用编码|状态`。
- 删了 CodingPage 里随之失效的 `.msg-thinking-card/.msg-status/.msg-step-badge/.msg-tool-row` 等死 CSS。
**验证**:用一个完整 BUILD 会话(公告通知,conversation_id=10)replay 53 行逐项目视 + `vite build` 多次绿 + live READ 正常。
> 注:user/assistant/error 本来就已是 native。spec:`docs/superpowers/specs/2026-06-02-coding-builder-ui-unification.md`(文末有「已落地记录」)。

## 线 B:自开发「装回应用 + 重新发布」+ 分场景入口(T1–T6 完成 `369b68f`→`a5638e3`)
**目标**:Coding 生成自开发包后,用户显式点「装回应用」→ 确认弹窗 → 上传组件库 → attach 到应用 →(页面类)建菜单 → republish 让组件生效;进入 Coding 时先分「在应用上定制 / 做通用组件」两场景。**借鉴了 Claude Design 原型**(见 `docs/design-refs/2026-06-02-coding-prototype/screens_coding.jsx` 的 CodingEntry + InstallModal)。

**后端**(`backend/app/routes/coding.py`,pytest 见 `backend/tests/test_coding_deploy_to_app.py` 3 绿):
- `_build_and_upload_kits(*, ws_mgr, ws_id, env, db)`:build_and_package → 上传 `selfdevelopment/add|update/developmentKit` → 用 fileName 反查 kit_id;返回 `{kit_ids, file_type, project_type, display_name, file_names, register_name}`。
- `_deploy_to_app_impl(ws_id, local_app_id, ctx, db)` + `POST /coding/workspace/{ws_id}/deploy-to-app`:
  - **bound**(传 local_app_id):`_load_app_and_env` 拿本地 app + 平台 `apaas_app_id` → `enable_self_dev_config` → `attach_apaas_source_relation(kit_ids)` →(页面类)`create_self_dev_menu(link_url=register_name)` → republish(`query_app_detail.currentVersion` → `deploy_app`,版本冲突 patch+1)→ `publish_extension_update(app.id,'republish_done')`。
  - **lib**(不传):只上传到组件库,返回 `uploaded_only`。
  - **两个 id 别混**:attach/enable/menu 走平台 `apaas_app_id`;republish/广播走本地 `app_id`。**绝不**自动 attach 到 hardcode 默认 app。
  - 复用了 `extension.py` 的 `_load_app_and_env / _ensure_env_token / publish_extension_update`(已确认无循环依赖)。

**前端**:
- `api/coding.ts`:`deployToApp(wsId, localAppId?)`。
- `views/coding/InstallModal.vue`:装回确认弹窗(rows:应用页面/路由/权限/资产登记 + 编译 badge + 取消/确认),design-v3 token,对照原型 InstallModal。**注:还没在 live 见过**(要有 artifacts 的 BUILD 才会弹),只过了编译。`compiled` 目前写死 true(没接真实构建状态)。
- `views/coding/CodingSceneEntry.vue`:分场景入口(在应用上定制 bound / 做通用组件 lib + 目标应用 select + 示例),对照原型 CodingEntry。**已 live 目视,和用户给的原型截图一致**。目标应用 selector 用的是原生 `<select>`(原型是 chip 风),可后续打磨成 chip。
- `views/CodingPage.vue` 接线:空态挂 CodingSceneEntry(entry 时隐藏底部 composer;handoff 是 auto-send 所以不受影响);产物面板(`cap-*`)加「装回应用/发布到资产库」CTA → InstallModal → `deployToApp`;`onSceneSubmit` 设 deployMode/deployAppId 后灌 userInput + sendMessage;apps 列表用**单独的 onMounted**(`applicationApi.list()`,additive)加载。

---

## 待办 follow-up
### 1. T7 — 真实 trial 端到端验证(需你监督,会改 live 应用)
- **组件类**:新会话「做通用组件」→ 生成 → 产物面板「发布到资产库」→ 看平台组件库出现该 kit。
- **页面类**:新会话「在应用上定制」绑定一个**有 apaas_app_id 的应用** → 生成 → 「装回应用」→ InstallModal 确认 → 看平台:kit 已 attach、菜单已建、应用版本 +1(republish)。
- **回归**:READ 路径 / 历史回放 / 消息区 native 渲染 / composer / dolphin.ai / 产物面板 原功能无伤。
- 验证 plan 见 `docs/superpowers/plans/2026-06-02-coding-deploy-republish.md` 的 Task 7。

### 2. df-apaas-cli build 失败(已 spawn 任务 chip)
- 现象:form-page 自开发会话里 `npm run build` → `df-apaas-cli build` → `npm error 404 df-apaas-cli`。源码文件能写出,但构建工具拿不到,打包失败。
- 影响:`_build_and_upload_kits` 走 `build_and_package`(=这个 build),**构建失败就拿不到 zip,装回 e2e 走不通**。
- 要查:df-apaas-cli 从哪装 / 为什么 404 / coding workspace 构建工具链在本地+trial 怎么备齐。相关:`backend/app/coding/workspace.py`(`build_and_package` / `_uses_df_apaas_cli_build` / `_run_build_process`)+ 脚手架模板的 package.json build 脚本。

### 3. 可选打磨
- CodingSceneEntry 的「目标应用」改成原型那种 chip + 下拉(现在是原生 select)。
- InstallModal 接真实构建状态(`compiled`)+ 真实 menu/route 预览(现在 rows 是通用描述)。
- 线 A 遗留:`.ac-status` 给长 ✅ 输出加 max-width+省略;live tool 在 pipeline 落 `toolName` + 抽 `summarizeToolResult` 共享(出「✓ 找到 N」结果摘要)。详见 UI 统一 spec 文末。

---

## 关键文件 / 文档
- spec:`docs/superpowers/specs/2026-06-02-coding-builder-ui-unification.md`(线 A)、`docs/superpowers/specs/2026-06-02-coding-deploy-republish-design.md`(线 B,v2)
- plan:`docs/superpowers/plans/2026-06-02-coding-deploy-republish.md`(线 B,7 任务,backend TDD + 前端对照原型)
- 设计原型参考:`docs/design-refs/2026-06-02-coding-prototype/`(Claude Design 导出的睿鲸AI 原型;`screens_coding.jsx` = CodingEntry/InstallModal/context banner 的视觉来源;`tokens.css` = design-v3)
- 代码:`backend/app/routes/coding.py`、`backend/tests/test_coding_deploy_to_app.py`、`frontend/src/api/coding.ts`、`frontend/src/views/coding/{InstallModal,CodingSceneEntry}.vue`、`frontend/src/views/CodingPage.vue`、`frontend/src/components/common/agent-conversation/ToolCard.vue`、`backend/app/coding/read_query.py`

## 踩坑 / gotchas(给新 session)
- **本 session 卡过登出态**;这台机器现在是**登录态**:frontend dev :5173(base `/ai-builder/`)、backend :8000、code-server :8080、admin-spa :5174 都在跑(`.claude/launch.json` / preview_start)。`backend/.env` 配了 `APAAS_BASE_URL=apaas-trial` 所以走真 aPaaS。
- **验证用 `npx vite build`,别靠 vue-tsc**(dev 上 vue-tsc 有 400+ 陈旧错)。后端有 pytest(`backend/tests/`,`asyncio_mode=auto`,`.venv/bin/python -m pytest`)。
- **既有坏测试**(与本次无关,别被吓到):`tests/test_spec_section_o1.py` 收集报错(`SpecSection` 缺,来自别的 commit)+ `test_auth_switch_tenant / test_platform_admin_tenant_context / test_step_executor_model_merge` 共 6 个失败;已用 stash 实证是 pre-existing。跑本次测试:`pytest tests/test_coding_deploy_to_app.py`。
- **design-v3 tokens**(`--brand/--surface/--blue-*/--sh-*/--r-*/--text*/--font-mono`)在 `main.ts` 全局 import,新组件直接用,和原型同名。CodingPage 老 CSS 里还有 `--t-*` 一套,两套并存。
- **HMR 会重挂 CodingPage、清掉当前会话选择**;想看某会话用**直达 URL replay**:`http://localhost:5173/ai-builder/coding?conversation_id=<id>&workspace_id=<wid>`(F2 已让直达 URL 走富回放)。线 A 验证就是用 conversation_id=10。
- **dolphin.ai 是预期的模型名,别改**(底部 composer)。
- 改 CodingPage(4662 行,巨大)要小心;新 UI 都抽成了 `views/coding/*.vue` 独立组件。

## 怎么接着干
1. 先处理 df-apaas-cli build(否则 e2e 卡在打包)——可点那个 spawn 的 chip。
2. build 能出产物后,跑 T7 真实 e2e(组件类 + 页面类各一遍),你盯着平台结果。
3. e2e 通过后按需打磨(目标应用 chip、InstallModal 真实状态)。
4. 合适时机 `git push`(dev 领先 origin ~33 commit)。
