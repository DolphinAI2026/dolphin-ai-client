# 交接 · 桌面 IA 重设计(2026-06-21)— 换会话必读

## 一句话
新桌面 UI 设计(`~/Downloads/AI Builder Desktop.html`,三模式同壳 Builder/Agent/Code + 项目→产物视图)正在落地。**第2块(项目→产物视图)已完整 + 第1块(三模式壳)大半完成**,全在分支 `feat/project-artifact-view`(未推 origin)。**下一步:把 Code 模式的会话也收进左栏(同 Builder 的做法)**,外加几项收尾。

## git 状态
- 分支 `feat/project-artifact-view`(从 dev/0.2.19 拉出,**未合未推**)。工作树干净。
- 关键 commit(新→旧):
  - `c1426ce2` 重命名 应用资产库→我的应用 / 自开发资产库→我的开发
  - `5a47e69d` 首页用现有欢迎页 + 会话栏折叠/按应用分组 + 页脚收进头像菜单
  - `84c96573` 去掉 Agent 入口 + 会话目录收进单一左栏
  - `aa0d8ba4` 修首页发送没反应(KeepAlive)+ 模式切换丢能力
  - `d353caa2`/`d7853a09` 模式首页 composer(已撤)/ 三模式壳第一刀
  - `e100d078`..`6930b3bf` 第2块「项目→产物视图」全套(后端+前端,见 spec/plan)
- spec/plan:`docs/superpowers/specs/2026-06-21-project-artifact-view-design.md` + `docs/superpowers/plans/2026-06-21-project-artifact-view.md`。记忆:`[[project_artifact_view_2026_06_21]]`。

## 已完成
**第2块 项目→产物视图**(完整 + opus 评审 READY TO MERGE):后端 `ProjectArtifactDependency` 表 + decompose 声明依赖 + orchestrate 落库 + `GET /projects/:id/dependencies`;前端 `ProjectOverview.vue` 重写(产物按模式分组 + 跨产物依赖图)+ `composables/projectVM.ts`(projectTypeToMode/buildArtifacts/resolveDependencies)。⏳唯一待验:真 LLM 多产物分解端到端(本地 tenant1 gpt-5.5)。

**第1块 三模式壳**(用户用 dmg 真机迭代了多轮):
- `stores/mode.ts`:模式态(builder/code;**Agent 暂撤**,MODE_META.agent 保留)+ 持久化 + ⌘1/2/3。
- `components/v2/RailSidebar.vue`:顶部 Builder/Code 切换器(模式色)+ 每模式导航(我的应用/我的开发等)+ **会话历史单一左栏**(日期/应用分组切换 + 可折叠 + 删除,数据 `aiChatApi.listSessions`)+「得小帆·共性能力」常驻入口(先链 /skills)+ **页脚收进头像点开菜单**(租户/平台管理/主题/检查更新/退出)。
- `views/AIChatPage.vue`:`/` 即新建欢迎草稿页(说出目标…);`useRailSessions=true` 隐掉内层 SessionSidebar + `.no-aside` 主区铺满;route watch 无 id→清会话显欢迎。「新建应用」→ /ai-chat 草稿。
- `App.vue`:`/` 与 `/ai-chat` 同 AIChatPage,共用 ai-chat 单例 KeepAlive。

## 🎯 下一步(本次交接重点):Code 模式会话收进左栏
用户已要求:Code 模式也跟 Builder 一样,会话收进左栏单边栏,隐掉页面内层 SessionSidebar。**比 Builder 难一点**——Code 会话是另一套系统:
- 数据源:`codingApi.getConversations()`(不是 aiChatApi)。见 `views/CodingPage.vue:1337` → `sidebarCodingItems`(1344)/`sidebarCodingActiveId`(1360)。
- 新建:`codingApi.createConversation(modelId)`(1432/996)。删除:`codingApi.deleteConversation`(1504)。
- **选中一个 coding 会话 ≠ 简单 router.push**:`onSidebarCodingSelect`(1446)要 `codingApi.getConversationWorkspace` 解析 workspace 再打开。所以 rail 在 code 模式点会话,建议**导航到 /coding 带 conversation_id 参数,让 CodingPage 自己消费**(查 CodingPage 是否已支持 `?conversation_id=`/`?workspace_id=` 入参;若无则加一个 onMounted 消费,镜像 onSidebarCodingSelect)。
- 隐内层侧栏:`views/CodingPage.vue:32` 的 `<SessionSidebar v-if="!embedMode && !embeddedAppId && !codeFirst">` 加 `&& !useRailSessions`,并定义 `const useRailSessions = true`;`.coding-body` 布局在隐侧栏后让主区铺满(类比 AIChatPage 的 `.no-aside`)。
- RailSidebar:`showRecent` 现在是 `currentMode !== 'code'`;改成 code 模式也显,但数据/跳转走 coding 分支。建议在 RailSidebar 里按 `currentMode` 切换会话源(builder/agent→aiChatApi;code→codingApi),分组复用 `sessionGroups`(coding 会话也有时间字段)。

## 其余收尾(按优先级,用户会挑)
1. 得小帆·共性能力 **完整 4-tab hub 弹窗**(技能/MCP/AI网关/知识库),现在入口先链 /skills。
2. 第2块「项目→产物视图」接进 Builder 左栏「项目」入口(现在 `/project/:id` 还没正式入口)。
3. Agent 接得小帆真能力后**恢复 Agent 入口**(MODE_ORDER 加回 'agent',MODE_META.agent 已在)。
4. 第2块运行态验收(真 LLM 多产物分解)。

## 关键踩坑 / 操作法(durable)
- **改首页别再造新组件**:用 AIChatPage 的草稿欢迎页(`/`)。之前造了个 ModeHome,用户嫌重复,已删。
- **KeepAlive 单例坑**:`App.vue` isAiChatRoute 把 `/`+`/ai-chat` 当一个 `key="ai-chat-singleton"`。改 `/` 的组件时要同步,否则跳转复用缓存实例、新组件不 mount。
- **本地预览**(改前端实时看):`preview_start` backend(8000)+ frontend(5173);⚠️preview server 跨 turn 常被回收要重起。免登:铸 token `cd backend && ./.venv/bin/python -c "from app.auth import create_access_token; print(create_access_token(2,tenant_id=73,expire_minutes=600,username='18661220521',apaas_user_id='100243738643582156800',apaas_tenant_id='241250891594727425'))"`,预览浏览器先导航到 origin 再 `localStorage.setItem('token',…)` 再 `location.replace('/ai-builder/')`。组件测试无 DOM 走 `?raw`。
- **打 dmg 看效果**(用户反复要):`sed -i '' 's/"createUpdaterArtifacts": true/"createUpdaterArtifacts": false/' src-tauri/tauri.conf.json && bash scripts/build-desktop.sh`(~80s)→ `git checkout -- src-tauri/tauri.conf.json` 恢复 → `open -R "src-tauri/target/release/bundle/dmg/睿鲸 Builder_0.2.19_aarch64.dmg"`。**签名 key 加密 + createUpdaterArtifacts:true 会卡签名,所以打本地包前必须临时关掉再恢复**。未做 Apple 签名→首开右键打开过 Gatekeeper。
- 改后端必重启进程(run.py reload=False);本地 DB 是 SQLite(/tmp/fb_demo.db);.venv 是 py3.13。
- 用户偏好:**直接干、快出可见效果、反复打 dmg 真机看**,不走重流程;朴实沟通。
