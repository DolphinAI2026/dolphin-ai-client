# AI Coding 自开发包「部署到应用 + 重新发布」接入 — 设计 spec

> **状态**:设计已与用户对齐(2026-06-02),待写实施计划。
> **缘由**:AI Coding 已能生成 + 构建自开发包,但「部署到应用 + 重新发布」目前只接了一半 —— 只有「上传到组件库」(`upload-to-platform`),attach 到应用 / 建菜单 / 重新发布 都没接进 AI Coding(留在老的 AI Chat 全栈助手 + Builder 侧 ExtensionSectionPanel,且自动广播钩子没接通)。本 spec 把完整链路接进 AI Coding。

## 目标
AI Coding 构建好自开发包后,能**自动部署到目标应用**(上传组件库 → attach 到 app → 页面类再建菜单),并在用户**确认**后**重新发布应用**让组件生效。覆盖全场景类型(组件 / 页面 / 后端)。

## 已对齐的关键决策
1. **触发**:codegen build 成功后**自动** upload + attach;**republish 必须用户点确认**(改 live 应用)。
2. **agent 边界**:codegen agent 工具集**保持只读不变**(不给写/部署权限,守住 v2「Coding=纯开发」)。部署编排走**后端路由**,不走 agent 工具。
3. **目标 app 解析**:`req.app_id`(前端传当前会话绑定的**本地 app_id**)→ 查 `Application` 记录 → 同时拿到**本地 app_id**(int,给 `/republish` + 广播用)和**平台 `apaas_app_id` = `Application.platform_app_id`**(string,给 attach / enable / 建菜单用)。拿不到本地绑定、或应用没配 `platform_app_id` → **只上传组件库 + 提示去关联**。**绝不用 hardcode 默认 app `806997227284201472`** 自动 attach。
   > ⚠️ 两个 id 别混:attach/enable/建菜单走**平台 apaas_app_id**;republish/广播走**本地 app_id**。
4. **范围**:全类型(form-component/dual、menu-page/form-page/mobile-page、backend-*)。
5. **落点**:新增后端编排端点(方案 A),`upload-to-platform` 原端点保持「纯上传」语义不动。

## 现状:积木齐全,缺「编排 + AI Coding 侧接线」
**已有(直接复用)**:
- 上传:`backend/app/routes/coding.py:upload_workspace_to_platform`(2541)—— 构建 + 打包 + `selfdevelopment/add|update/developmentKit`,含 dual / jar / token 自愈 `_refresh_env_token` / `_query_existing_development_kits` / `_find_kit_by_filename` / `_build_upload_form_data` / `_PROJECT_TYPE_TO_FILE_TYPE`(2424)。
- attach / 建菜单 / enable:`backend/app/apaas_client.py` —— `attach_apaas_source_relation`(1181)、`enable_self_dev_config`(1127)、`create_self_dev_menu`(1255)。
- 重发 + 广播:`backend/app/routes/applications/extension.py` —— `POST /{app_id}/republish`、`publish_extension_update(app_id, event_type, payload)`(99)、`/extension-update-events`(SSE)、`/extension-update-notify`。
- 构建打包:`backend/app/coding/workspace.py` —— `build_and_package` / `build_and_package_dual` / jar 输出目录。
- 前端:`frontend/src/api/coding.ts:uploadToPlatform`、`frontend/src/api/extension.ts:republishApplication`、`frontend/src/components/v2/ExtensionSectionPanel.vue`(republish 确认 UI 的现成范式,可参考其交互)。

**缺(本 spec 要建)**:把 upload→attach→(页面:enable+菜单)→广播 串成一个编排端点,并在 AI Coding 侧(CodingPage 产物面板)接上「自动部署 + 确认重发」的 UI/调用。

## 设计

### ① 后端编排端点(方案 A)
新增 `POST /workspace/{ws_id}/deploy-to-app`(admin 权限,复用 `_ensure_workspace_access`),按场景类型编排:
```
1. 解析目标应用:req.app_id(本地 app_id) → 查 Application 记录
     → local_app_id(int) + apaas_app_id(= Application.platform_app_id, string)
     → 任一拿不到 → 直接走「只上传」分支(step 5)
2. build_and_package(复用;dual → build_and_package_dual;backend → jar)
3. 上传 developmentKit(复用 upload_workspace_to_platform 的上传逻辑,含 update-if-exists + token 自愈)
     → 拿到 kit_id(s)
4. 有目标 app:
   a. client.attach_apaas_source_relation(apaas_app_id, object_ids=[kit_id...])
   b. 页面类(menu-page/form-page/mobile-page)再:
      client.enable_self_dev_config(apaas_app_id, "ENABLE")
      client.create_self_dev_menu(apaas_app_id, ...)   # 菜单名取 display_name
   c. publish_extension_update(local_app_id, "dev_kit_attached", {kits, ...})  # 广播给开着的 ExtensionSectionPanel
   d. return { status:"attached", needs_republish:true, app:{local_app_id, name}, kits:[...] }
5. 无目标 app:
   return { status:"uploaded_only", needs_republish:false, hint:"已传到组件库,去 Builder 关联到应用" }
```
> republish 由前端拿 `local_app_id` 调 `POST /applications/{local_app_id}/republish`。
> republish **不在此端点**。保持独立、用户确认后调现有 `POST /applications/{app_id}/republish`。

### ② 上传幂等性(消除「每次 build 都部署」的噪音顾虑)
build 成功**自动**调 deploy-to-app,但:上传是 **update-if-exists**(同 fileName 命中则 update 同一 kit、只换 versionCode)、attach 是**幂等**(重复 attach 同 kit 不新增)。所以迭代多次 build 只是**原地更新同一个组件库条目**,不会刷出一堆重复包。**真正让变更对终端用户生效的只有 republish,而 republish 永远要用户点** —— 用户迭代时随便 build,满意了再点一次重发。

### ③ 场景类型分支
| project_type | fileType | 步骤 |
|---|---|---|
| form-component / form-component-dual | FRONTCOMPONENT(双端各一) | upload → attach |
| menu-page / form-page | FRONTENGINE | upload → attach → enable_self_dev_config + create_self_dev_menu |
| mobile-page | MFRONTENGINE | 同上 |
| form-list / layout / plugin | FRONTLISTVIEW / FRONTLAYOUT / FRONTTENANTCOMPONENT | upload → attach |
| backend-api / feign / scheduled | BACKENDENGINE | jar upload → attach |

(fileType 复用现有 `_PROJECT_TYPE_TO_FILE_TYPE`。)

### ④ 前端(CodingPage 产物面板,复用 `cap-*` 区域,不新开页面)
- codegen build 成功(监听 `agent_done` / 产物就绪)→ 自动调 `deployToApp(wsId, appId)`。
- 产物面板顶部出**部署结果卡**:
  - 部署中:spinner「正在部署到应用…」
  - `attached`:「✓ 已部署到「X」· 重新发布让组件生效 [重新发布]」按钮 → 调 `republishApplication(appId)` → 成功 toast。
  - `uploaded_only`:「✓ 已传到组件库 · 去 Builder 关联到应用」提示(带跳 Builder 链接)。
- republish 确认 UI **就放在 AI Coding 产物面板**(用户在哪点哪),不依赖切到 Builder;同时广播让 Builder 侧 ExtensionSectionPanel 同步。

### ⑤ 错误处理
upload / attach / menu / republish **各步独立 try**,失败给明确人话提示(带 error_code/message),**不连带回滚**(已上传的 kit 留着,可重试 deploy)。token 过期复用现有 `_refresh_env_token` 自愈。无目标 app 不是错误(走 uploaded_only 分支)。

### ⑥ 人工闸门 & 边界
- upload + attach + 建菜单:**自动**,但结果在产物面板**可见**。
- republish:**必须用户点**(唯一改 live 应用的动作)。
- codegen agent 工具集**不变(只读)**;`upload-to-platform` 原端点**不动**;composer / IDE / 历史回放 / 产物面板结构**不动**。

## 关键文件
- 新增/改:`backend/app/routes/coding.py`(新 `deploy-to-app` 端点,抽出上传逻辑供复用)
- 复用:`backend/app/apaas_client.py`(attach / enable / menu)、`backend/app/routes/applications/extension.py`(broadcast / republish)、`backend/app/coding/workspace.py`(build/package)
- 前端:`frontend/src/api/coding.ts`(加 `deployToApp`)、`frontend/src/views/CodingPage.vue`(产物面板部署结果卡 + 自动触发)、`frontend/src/api/extension.ts:republishApplication`(复用)

## 风险 / 约束
- **republish 改 live 应用**:必须人工确认,且提示清楚影响。
- **目标 app 误判**:绝不自动 attach 到 hardcode 默认 app;解析不到就 uploaded_only。
- **场景类型多**:页面类的 enable+建菜单 与组件类不同;后端 jar 路径不同 —— 用 project_type 显式分支,缺映射的类型走「只上传 + 提示」。
- **CodingPage 已超大**:产物面板改动控制在 `cap-*` 区 + 一个 composable(deploy 状态),不动消息区。
- 验证:后端 `deploy-to-app` 各分支单测/手测;前端 `npx vite build`;真实 trial 环境跑一次 组件 + 页面 两类的 build→部署→重发 端到端。

## 范围外(v1 不做)
- 组件版本管理 / 回滚 UI。
- 多 app 批量部署。
- 给 codegen agent 写/部署权限(刻意不做,守 v2 边界)。
- 无 app 时的「在此选 app」选择器(v1 只提示去 Builder 关联;选择器留后续)。
