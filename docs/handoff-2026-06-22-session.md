# 交接 · 2026-06-22 会话(Code 模式对话优先重做 + 登录页统一 + 切会话抖动根治 + 发版 0.2.20~0.2.22 + dev 收口)

## 一句话
桌面端 Code(全代码)模式从「IDE 为主」重做成「对话为主 + 代码并排侧栏」(对齐 Claude Code/Codex),修了一连串切会话抖动,统一了桌面登录页,发了 **0.2.20 / 0.2.21 / 0.2.22** 三版(线上现 **0.2.22**),最后把 `feat/project-artifact-view` 合进 dev 并 force-push origin/dev(丢弃旧 IA)。**dev = origin/dev = 0.2.22,干净同步。**

## 当前 git 状态(已收口)
- **`dev` == `origin/dev` == `feat/project-artifact-view` == `52236490`(0.2.22)**,工作树干净,`dev` 正常 tracking `origin/dev`(无 ahead/behind)。
- **force-push 过 origin/dev**:`2b79db6e`(旧 IA Phase 1 tip)→ `52236490`。丢弃的 11 个 commit 全是 Mars 自己回退掉的旧 IA(ProjectRail/ProjectView/ProjectVM/spec/plan),已被新三模式 IA 取代。
- **`backup/dev-ia-wip-2026-06-21`(`1faa84b8`)保着那 11 个旧 IA + 并行会话 WIP,可恢复。别删。** 只在本地,没推 origin —— 要更稳可推一份(纯新增分支)。
- ⚠️**同事若基于旧 dev 在改**:他们 `git pull` 会因历史改写需 `git fetch && git reset --hard origin/dev` 对齐。提醒一下。
- `main` 没动(ahead 43 / behind 1313,跟本次无关)。

## 本会话做了什么(主题分组)

### 1. Code 模式会话收进单一左栏(`27287d73`)
RailSidebar 按 `currentMode` 切会话源:builder/agent→`aiChatApi`,code→`codingApi`。抽纯函数 `composables/railSessions.ts`(normalize/target/active/fallback)。点 code 会话导航 `/coding?conversation_id=N`。CodingPage 加 `useRailSessions=true` 隐内层 SessionSidebar。

### 2. Code 模式「对话优先」重做(用户真机反复迭代)
- **新建会话对话优先(`3b876f9e`)**:删死板「未选择会话」占位,stream-pane 永远渲染。全新会话 = `.coding-new-welcome` hero(全代码开发 + **打开本地文件夹**[桌面端 `pickDirectory`+`openLocalFolder`]/ 我的开发·导入源码)+ 底部 composer 非嵌入永远可见(`sendMessage` 自动识别场景+建工作区)。抽纯函数 `isCodingWelcome`/`shouldShowCodingComposer` 进 `coding/codingLayout.ts`。
- **工作区对话优先**:删内嵌「文件树为主 + 对话 420px 窄栏」三栏。
  - 第一版做成**覆盖式抽屉(el-drawer)**(`e93ec921`+`bda7739f`)→ 用户真机反馈「盖住对话没法聊」**驳回**。
  - **终版 = 并排侧栏(`5efc0211`)**:对话常驻主列 `flex:1` 永远能输入;代码作右侧 `.ws-pane` 内联并排侧栏(`codePaneOpen`,宽度 `codePaneWidth` 可拖,默认 640),× 收起回全宽对话。触发=头部「代码」按钮 / 对话里写改文件卡(`openFileFromChat`)/ 产物清单文件行 / `focusPreview` / 点本地预览链接 / AI 跑完预览(`previewEpoch` watcher)。
  - **durable 教训**:「对话 + 代码并排」必须用内联 flex 兄弟(push 布局),**不能用 el-drawer(overlay 会盖住对话)**。

### 3. 切会话抖动 —— 两层根因,逐个根治
- **抖动① 左栏宽度(`474c4c07`,0.2.21)**:`WorkbenchShell.vue` 的 `codingFocus` 把左栏宽绑在 `route.query.workspace_id`(有=176px / 无=224px)。换会话导航中途路由没 workspace_id → 左栏 176↔224 闪。**修=删 codingFocus + 整套 `.workbench-coding-focus` 压缩 CSS,左栏恒定 224px。**
- **抖动② 整页 remount(`e9d9dbd5` + 对抗评审 `ecf78a32`,0.2.22)**:`App.vue` 里 `/coding` 走 `v-else` 的 `:key="$route.fullPath"`,换会话 query 一变就**整页 remount**。**修=给 /coding 单列稳定 key `coding-stable`**(query 变化复用实例不 remount;不进 KeepAlive,离开 /coding 仍正常卸载)+ CodingPage 抽 `resolveCodingRouteSession()`(原地解析 query→会话/工作区,用 `syncCodingUrl`=history.replaceState 同步地址栏不二次导航)+ onMounted 首解析 + `watch(route.query)` 处理后续切换 + `resetCodingToWelcome()`(裸 /coding 新建)。
  - **对抗评审(workflow)揪出我引入的两 bug 并修**:
    - **Critical**:原地切会话不再 remount → **旧 SSE 没人 abort**,回调继续往切到的新会话共享 `streamMessages/conversationId` 写 = 串台(旧靠 remount 销毁 pipeline 闭包白捡 abort)。修=`abortInflightStream()`=`isStreaming` 时 `stopStream()`,在各切换函数 same-id 守卫**之后**调。
    - **Important**:流式建会话后地址栏仍裸 /coding,之后点 rail 新建(也裸 /coding)query 没变 watcher 不触发 → 残留清不掉。修=`onAfterPipeline` 里 `syncCodingUrl(conversationId)`。
  - **durable 教训**:把组件 remount 当「免费清理(abort SSE / 清状态)」是隐性依赖;改稳定 key 复用实例后,这些清理必须**显式补上**(尤其 in-flight SSE / 定时器)。
  - **preview 验证抖动/remount 的法子**:给 `.coding-body` 打 `dataset` 标记,切会话后标记仍在 = 同一实例没 remount(确凿)。⚠️preview 计时器被节流到 ~1Hz,抓不了动画帧,改测「两路由稳态宽度差 / DOM 节点身份」。

### 4. 桌面登录页统一 web UI(`85a458cc`)
桌面登录原是朴素小卡(`DesktopLogin.vue`),web 是品牌分屏(`Login.vue`)。两者只差认证调用(web=`login` 可能选租户 / desktop=`desktopLogin` account-service)。**删 `DesktopLogin.vue`,/login 恒用 `Login.vue`,`handleLogin` 按 `isDesktop` 分支**。单一组件 = 两端 UI 必然一致不再漂移。⚠️web preview(`isDesktop=false`)跑不到桌面分支,桌面认证只能真机验。

### 5. 发版(全走 `scripts/release-desktop.sh`)
- **0.2.20**:三模式壳 + 项目→产物视图 + Code 三件(收左栏/新建对话优先/工作区对话优先+代码侧栏)。
- **0.2.21**:修左栏宽度抖动。
- **0.2.22**:登录页统一 + 切会话 remount 抖动根治 + SSE 串台修。
- 线上 manifest `agent.dfy.definesys.cn/account-api/desktop-updates/latest.json` 现 **0.2.22**,arm64+x86_64 双架构签名齐。自动更新走 minisign(非 Apple 公证),老用户直接弹更新。

## 关键踩坑 / 操作法(durable)
- **发版**:`VERSION=0.2.x NOTES="..." bash scripts/release-desktop.sh`(arm+x64 双签名 updater 产物 + 拼 latest.json + 平台管理员登录 account-service 上传 + 校验)。签名 key=`keys/ruijing-updater.key`(脚本自 export `TAURI_SIGNING_PRIVATE_KEY`);凭据=`keys/release.env`(ADMIN_USER/PASS);`createUpdaterArtifacts` 必须 true(本地「看效果」包才临时改 false)。
- **本地看效果 dmg**(不上传):`sed -i '' 's/"createUpdaterArtifacts": true/.../false/' src-tauri/tauri.conf.json && bash scripts/build-desktop.sh`(~80-90s)→ `git checkout -- src-tauri/tauri.conf.json` → `open -R "src-tauri/target/release/bundle/dmg/睿鲸 Builder_0.2.x_aarch64.dmg"`。
- **preview 验证法**:`preview_start` backend(8000)+frontend(5173);免登铸 token `cd backend && ./.venv/bin/python -c "from app.auth import create_access_token; print(create_access_token(2,tenant_id=73,expire_minutes=600,username='18661220521',apaas_user_id='100243738643582156800',apaas_tenant_id='241250891594727425'))"`,浏览器 `localStorage.setItem('token',…)`。⚠️**preview_click 合成点击不触发本 app 的 Vue @click** → 用 eval 派发 `new MouseEvent('click',{bubbles:true,view:window})` 或直接改路由。计时器节流 ~1Hz。组件测试无 DOM 走 `?raw`。
- **账号管理台(开桌面登录账号)在 `https://agent.dfy.definesys.cn/account-api/admin-ui`**(后端 `backend/services/account_service/admin_ui.py` 自渲;别加结尾 `/` 会 307)。**不是** `/ai-builder/account-service`(那地址不存在,落 ai-builder SPA 无路由 = 白屏)。account-service 是独立后端,本次没动。
- 改后端必重启进程(run.py reload=False);本地 DB 是 SQLite;.venv 是 py3.13。

## 预存问题(非本次,别误判回归)
- 前端 `TenantLogsPage.spec.ts` 1 个 `?raw` 测一直红(IA 改造时租户日志入口从 rail 移走的陈旧测)——全量测「247 通过 / 1 红」里那个 1 就是它。
- `vue-tsc -b` 有 2 个预存类型错:`DesktopSetupWizard.vue` / `workspace/WorkspaceShell.vue`(与本次无关)。
- router `index.ts` 的 `@/views/*.vue` LSP 诊断是预存别名噪声,vue-tsc 能解析,非真错。

## 下一步 / 遗留(用户可挑)
- **真机回归 0.2.22**:① 切会话顺不顺(应原地、不闪)② 趁一个会话正在生成时切到别的会话,确认新会话不混入旧任务内容(SSE 串台修的边界)③ 桌面登录页 UI + 能正常登进去。
- **Minor 清理(评审标的,非阻断)**:`codingLayout.ts` 的 `getCodingMainPaneStyle`/`shouldShowWorkspacePane` 已无人引仍有单测;CodingPage 内 SessionSidebar 死块(`useRailSessions` 恒真,但 `sidebarCodingItems` 仍被 onMounted 恢复引用,删前需核);onSidebarCodingSelect/createCodingConversation 用 router.replace 触发一次冗余 resolve(guard 跳过,无害)。
- 更早遗留(本会话前):得小帆完整 4-tab hub 弹窗、把项目→产物视图接进 Builder 左栏「项目」入口、Agent 接真能力恢复入口、第2块真 LLM 多产物分解运行态验收、Apple 代码签名/私有化/Windows。
- 关联记忆:`[[project_artifact_view_2026_06_21]]`(本会话进度全在内)、`[[handoff_2026_06_21_session]]`(上一会话,部分已被本次收口作废)。
