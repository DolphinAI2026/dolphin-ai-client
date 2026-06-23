# 2026-06-22 会话交接(工具崩了,中途交接)

分支 `dev`,**所有改动已提交未推 origin**(顶 `652ce293`)。dev 后端 :8000 + vite :5173 都在跑(run-survival 版)。桌面 DMG 最新已含到「切会话串台修复」为止(`src-tauri/.../bundle/dmg/睿鲸 Builder_0.2.22_aarch64.dmg`,23:10 构建)。

## 本会话已完成(全部已提交,未推)

1. **白屏 + 真数据 + 老工作区自愈**(`4c896780`):见 memory [[preview_harness_white_screen_2026_06_22]]。form-page 等 serve 即白屏=两层(没挂载入口 + 平台组件 x-ag-grid 没桩);`workspace.py` 抽 `_inject_preview_harness` + `_PREVIEW_*` 常量搬进 CLI 模板路径。真数据=harness `$request` 走 `/apaas/backend/{tenant}/{app}` 同源代理(runtime_proxy 注 token),start_serve 按绑定 app 注 `VUE_APP_APAAS_API_BASE`+代理目标。自愈=start_serve `_ensure_preview_harness`+`_ensure_preview_element_ui`。🔑坑:harness 里 `process.env.VUE_APP_X` 别加 `typeof process` 守卫(webpack 恒假→短路成 mock)。

2. **切会话不丢 run(builder+code)**:见 memory [[run_survives_switch_2026_06_22]]。spec `docs/superpowers/specs/2026-06-22-run-survives-conversation-switch-design.md` + plan `docs/superpowers/plans/2026-06-22-run-survives-switch-phase1-code.md`。
   - Phase1 Code(`50bb4f18`→`e43e6bb0`):`app/harness/run_registry.py`(RunRegistry 强引用后台 task)+ manager.start_turn 注册/摘除 + `attach_stream`(补缺口+实时,断开不杀 task)+ routes/harness.py `GET /coding/run-status`、`GET /coding/attach`、`POST /coding/stop`(强引用后停止键 abort fetch 不再停 run→必须显式 cancel task)。前端 useCodingPipeline `detachStream`/`attachStream` + CodingPage `maybeAttachRunningRun`。
   - Phase2 Builder(`19233725`,`c751b757`):ai-chat 走 session_id≠conversation_id→自建 `app/ai_chat/run_bus.py`(AiChatRunBus + subscribe_run_events + ai_chat_run_registry)。`routes/ai_chat.py` send_message 解耦为后台 `_run_bg` 发 bus + run-status/attach + 守卫;停止键沿用既有 `/abort`。前端 aiChat.ts `_consumeSse`/getRunStatus/attachRun + AIChatPage loadSession 末 maybeAttachRunningRun。
   - 后端 15 TDD 测 + 252 关联回归全绿。

3. **切会话 attach 串台修复**(`652ce293`):run-survival 回归——CodingPage `maybeAttachRunningRun` 缺"await 回来仍是同一会话"守卫(ai-chat 版有)+ `attachStream` 写共享 streamMessages 没按会话过滤 + `createWorkspaceConversation` 没断旧流 → 异步竞态把别会话事件写进当前/空会话卡"正在思考"。三处加会话守卫。**已在 :5173 真机验证修复**。

4. **桌面打包**:`scripts/build-desktop.sh` 最小路径出 .app+.dmg。`EXIT=1` 仅因最后给 updater 产物签名缺私钥,`.dmg` 已在那之前完整产出,手动装无影响。⚠️改前端后桌面要重打(sidecar 内嵌 dist-desktop)。

## ✅ 2026-06-23 续:Code 切会话提速 + SPEC 折叠卡 + 删右侧产物面板(本会话,已 commit)

5. **markdown 渲染记忆化**:`utils/markdown.renderMd` 加按内容缓存(Map,上限 3000);`AgentConversation`/`useStreamMessages` 委托它,删各自重复 marked 配置。切会话/重渲染不再对每条消息重复 `marked.parse`。新增 `markdown.spec.ts`。(注:此刀对切会话卡顿无关,但本身是无害正确优化。)
6. **切会话卡顿根因修复(Claude-in-Chrome 真机埋点定位,实测 5.8s→1.1s)**:卡顿=网络 bound,**不是渲染/markdown**。①`changedPaths` watcher 加 `isStreaming` 守卫——切会话回放也会让 changedPaths 跳变,原来导致文件树/git 改动**各拉两遍**且并发争抢更慢;②文件树+git 改动从「切会话」关键路径移除,改成 `codePaneOpen` 打开代码面板时**按需懒加载**(`ensureCodePaneData`;切工作区/codegen 写文件后 `_codeDataLoadedFor` 失效重拉)。🔑**统一壳(BuilderFrame/RailSidebar)里 Code 切换走 CodingPage 的 `route.query` watcher → `resolveCodingRouteSession`,不是 `onSidebarCodingSelect`**(埋错过一次)。剩余 ~1.1s = `getWorkspace+getWorkspaceConversation`(消息载体,后端)。
7. **右侧产物面板(开发文档/产物清单/接入说明)整块删除**:SPEC → 对话可折叠卡(`#custom` slot 加 `isSpec` 分支,复用思维链卡 + `cap-spec-doc` 观感,默认展开供审阅);「回复开始」CTA 跟随;部署/发布入口(原**唯一**入口在面板内 `openInstallModal`)收进输入区上方 `coding-deploy-bar`(gate `codingArtifactsHasAny && !isStreaming`,同原门);删面板 state(`showCodingArtifactPanel`/`codingArtifactTab`/`specViewMode`/`specMarkdown` 等)+ ~280 行 `cap-*` CSS(**保留 `cap-spec-doc`**);步骤胶囊「待确认」→「已生成开发 SPEC」。浏览器实测 SPEC 卡展开/收起 + 面板已无 + 无报错;`build:nocheck`+`vue-tsc`(触及文件)+ 105 vitest 全过。
   - ⚠️ 部署栏(deploy-bar)没跑完整 codegen 实测(要几分钟),逻辑与原部署按钮同门,低风险。
   - ⚠️ **发布上线会一起带上「2026-06-22 run-survival(builder send 解耦等)」那批未推 commit**——那批没过浏览器 e2e(见上「未做」),发同事前注意。

## ✅ 已实现(2026-06-23,方案 B,已 commit)

**Code 的「SPEC 确认门」对齐 Builder = 保守版 B 已落地**(`CodingPage.vue` + `useCodingPipeline.ts` + `CodingPage.styles.css`,新增 `CodingPage.specgate.spec.ts`):
1. 删模板 SPEC 确认门 bar(原 250-266)+ `awaitingSpecConfirm` computed + `confirmSpec()` + 对应 CSS(`.coding-confirm-bar`/`.ccb-*`)。
2. `agentMessages`(原 1146)message 分支改对话式 + **去重只留最新**:循环前预扫 `lastSpecIdx`(最后一条匹配 `SPEC_RE` 的 message),只在 `i === lastSpecIdx && !isStreaming.value && !codingArtifactsHasAny.value` 时给对话式 CTA「📋 开发 SPEC 已生成…确认无误回复「开始」…要调整直接补充需求」;早期版本/已进 codegen → 收成一行里程碑「📋 已生成开发 SPEC」。**CTA 守卫复制了原确认门的逻辑门(不流式+无 codegen 产物)** → 写代码时不会再误喊「回复开始」。
3. live 流 brainstorm step label `开发 SPEC 待确认` → `已生成开发 SPEC`(CTA 交给对话消息)。
4. 顺手删死函数 `openCodingArtifactTab`(确认条/完成卡两调用方都已删)+ 无用 `CircleCheck` import。
5. 后端状态机**没动**:打字「开始/确认」→ `_classify_brainstorm_response` 判 confirm 触发 codegen;补充需求 → 判 revise 出新 SPEC。已用 4 个 Explore agent 核过后端意图分类确实认这些词。

**验证**:`npm run build:nocheck` ✓;`vue-tsc` 触及文件零新错;`vitest` 新增 specgate 7 测全过 + coding 全套 72 测过;全套 252 过(唯一失败 `TenantLogsPage.spec.ts` 已 stash 复核=committed HEAD 即坏的预存失败,与本改无关)。
**⏳ 未做**:①登录态真机 e2e(需求→SPEC→看到对话式无按钮→打「开始」→codegen 起;预览 harness 与用户在跑的 :5173 vite 抢端口,没去杀用户进程)②桌面重打 DMG(改了前端,sidecar 内嵌 dist-desktop)③git commit(用户没要求,留 working tree)。

---

## (历史)原"正在做"记录:方向敲定 = B

**Code 的「SPEC 确认门」对齐 Builder = 用户选了 B:去掉确认门、做成对话式。**

已查清(两个 Explore agent):
- Code **已有**和 Builder 一样的"正在跑时排队"(`sendOrQueue` CodingPage.vue:1305-1325 + banner + 跑完自动发)。真分歧只在 **SPEC 确认门**。
- 确认门:`awaitingSpecConfirm`(CodingPage.vue:1269-1271)→ confirm bar(CodingPage.vue **250-266**)。`confirmSpec()`(**1272-1276**)只发一句"确认,按这份开发 SPEC 开始生成代码"→ 后端 `_classify_brainstorm_response` 识别 confirm。
- 后端(pipeline.py ~2030-2159):brainstorm 出 SPEC → `waiting_confirmation=True`、**零工作区**;待确认再发 → revise(**append** 新 SPEC=孤儿堆叠)/ confirm(建 ws+codegen)/ abort。**对话式 confirm/revise 后端本来就支持**,按钮纯快捷。
- 用户的"乱"是我自测连发 3 个不同请求造的:孤儿"📋 已生成开发 SPEC"(history transform CodingPage.vue **1149**;live 流 brainstorm step label useCodingPipeline.ts **124-135**)+ revise 丢早先需求(LLM prompt 问题,先不修)。

**保守版 B(方向已定,细节落地)**:
1. 删 confirm bar(CodingPage.vue 250-266)+ `awaitingSpecConfirm`/`confirmSpec`。
2. "已生成 SPEC"消息改对话式 + **去重只留最新**(CodingPage.vue 1149 transform + live step label):文案如"📋 开发 SPEC 已生成(右侧「开发文档」看)。确认无误回复『开始』我就写代码,要调整直接补充需求。"
3. 确认走打字(回"开始/确认"→后端 confirm 意图,已通)。后端状态机不动→孤儿消失。
4. **保留**"确认前零工作区 + SPEC 审阅"价值(只去按钮门、不去逻辑门)。⚠️若用户其实要更激进(SPEC 不等确认直接 codegen)=动后端,先按保守版。

**下一步**:读 `useCodingPipeline.ts:122-220`(brainstorm step + content handler,看 live 流 SPEC 怎么成消息)→ 实现 1-3 → :5173 真机验(已登录态)→ 桌面重打 DMG。

## 关键环境/坑

- dev 后端 :8000(reload=False,**改后端必重启**);vite :5173(HMR);都跑 run-survival 版。
- :5173 登录页**预填** admin 账密(dev 便捷),点登录即进;本会话我用它真测过。
- dev DB 是 SQLite;.venv py3.13;`.venv/bin/python -m pytest`;后端有 6 个预存 SQLite 失败(非本次)。
- 桌面数据目录 `~/Library/Application Support/com.ruijing.builder/` ≠ dev `~/.apaas-builder-ai/`。
- **没推 origin**;发版 `release-desktop.sh VERSION=0.2.x`(keys/ 里私钥+admin 凭据都在,publish 到 agent.dfy.definesys.cn 生产→同事自动更新)。**未验证核心改动别直接发同事**(尤其 builder send 解耦)。
- 我自测在 dev 列表建了几个测试会话(员工列表/部门管理/角色权限/hello,conversation_id=45),可清。
- 🚩**工具崩**:本会话 `AskUserQuestion`、`mark_chapter`、嵌套多 Agent 调用反复 malformed/卡死。下个会话避开复杂嵌套 XML 工具,简单 Read/Edit/Bash/Grep 正常。
