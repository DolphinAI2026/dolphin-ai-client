# 设计：配置工作区改为内嵌 apaas 原生编辑器（删自渲染面板）

日期：2026-06-24
状态：设计待评审
作者：大明哥 + Claude

## 1. 概述与目标

把 Builder 的「应用配置工作区」（ChatPage）从一堆**自渲染的只读配置面板**，改成**直接 iframe 内嵌 apaas 原生低代码编辑器**：

- 左侧保留菜单目录（`ApaasMenuSidebar`）。
- 点某个菜单 → 右侧 iframe 加载该菜单对应的 apaas 原生编辑器页（即「表单设计 / 列表设计 / 流程设计 / 页面设置」一体页，apaas 自带）。
- AI 配置助手（`AppAssistantPanel`）改完配置 → 刷新 iframe 即可看到最新原生页。
- 用户在 iframe 内第一次手动登录一次 apaas，之后免登。

同时附带一个**独立的小修**（Builder 设计稿 HTML 预览能多页切换），与上面解耦、可单独发布。

### 非目标
- 不改 AI 配置助手改配置那条链路（走 MCP，不动）。
- 不解决 apaas 编辑器引擎自身的偶发崩溃（闭源、非我们的代码）。提供「用系统浏览器打开」兜底。
- 不做单点登录（SSO）自动注入。用户登一次即可。

## 2. 背景：这是一次方向反转，必须知道为什么

### 2.1 当前设计（要被替换的）的由来
2026-06-04 落地了「配置面板全只读自渲染 + 深链低代码后台」（plan `2026-06-04-readonly-panels-deeplink.md`）。它**不是**因为不想内嵌，而是因为**内嵌会崩**：

- 经 `platform_proxy.py` 反向代理把 apaas 编辑器代理到**我们自己的 origin**（为了注入登录态 `localStorage['__vuex__local']`），渲染一下就 `TypeError: Cannot read properties of undefined (reading 'type')` 刷几十次然后回首页。
- 根因 = **apaas 渲染引擎自身的闭源 bug**（实测 app_id=26，0 自开发组件也崩），我们改不了。
- 代理还把插件资源的 `versionCode` 搞坏 + trial 环境缺 2 个业务组件 → 404 重试风暴，叠加引擎 bug 一起崩。

于是改成只读自渲染 + 每面板「打开低代码后台」深链新标签页，删掉了整套内嵌 + 代理（`ApaasEmbedIframe.vue` / `platformIframe.ts` / `platform_proxy.py` 全删）。

### 2.2 为什么这次的「直接 iframe」不一样、大概率能成
本方案要的内嵌跟当年崩的那个**机制不同**：

- 当年：反向代理到**我们的 origin**（同源剥壳），代理篡改资源 → 触发 404 风暴 + 引擎 bug。
- 本次：**直接 iframe apaas 真实 URL**（跨源，不代理，资源 versionCode 由真主机给、正常解析），用户在 iframe 内用 apaas 自己的登录流程登一次。这跟今天「打开低代码后台」按钮干的事一模一样 —— 它现在就是把同一个真实编辑器 URL（`getEditorUrl` 生成）直接丢进一个 Tauri 窗口打开，没走代理。

**风险判定锚点**：今天点「打开低代码后台」弹出的那个原生编辑器窗口，已被实际使用且稳定。把同一个 URL 从弹窗挪进工作区内嵌 iframe，是同引擎、同 URL、同 origin，只是容器不同 → 预期同样稳定。引擎偶发 bug 仍非我们能根治，故保留系统浏览器兜底。

### 2.3 登录与刷新（已验证可行）
- 登一次免登：apaas 登录态写在它自己 origin 的 `localStorage`，持久化（memory 实测确认）；生产环境睿鲸挂在低代码后台下本就是已登录态 → 免登。
- 助手改完刷新：`AppAssistantPanel` 已有 `@refresh-iframe` emit（旧内嵌时代留的钩子），复活它 → iframe key 自增重载即可。

## 3. 新架构：配置工作区 = 菜单目录 + 内嵌原生编辑器 + AI 助手

ChatPage 的「设计」配置区由当前的「顶部多 tab（设计/数据/流程/权限/日志/SPEC/数据源）+ 设计 tab 内 6 个自渲染设计面板」收敛为：

```
┌──────────────┬───────────────────────────────┬──────────────┐
│ ApaasMenu    │  内嵌 apaas 原生编辑器 iframe   │ AppAssistant │
│ Sidebar      │  (该菜单的表单/列表/流程/页面)  │ Panel (AI)   │
│ (菜单目录)    │  地址栏(可隐)+刷新+系统浏览器兜底│ 改完→刷新     │
└──────────────┴───────────────────────────────┴──────────────┘
```

- 点 **MODEL 类菜单** → iframe 加载 `getEditorUrl(appId, {menu_type, menu_id, form_id})` 返回的真实编辑器 URL。该 URL 由后端现成的 `build_editor_path` 生成（`backend/app/apaas_editor_url.py`，MODEL → `data-model-fn-config`，带 menuId/formId）。
- 点 **CUSTOM 类菜单（自开发 Vue 页面）** → 仍走我们自己的 `CustomPagePreviewPanel`（不变，见保留清单）。

不再需要把「数据/流程/权限」做成独立顶部 tab —— 原生编辑器一体页内部已含这些模块。

## 4. 组件设计

### 4.1 共享组件 `InAppBrowser.vue`（新建）
从 `RunDebugPanel.vue` 的「地址栏 + iframe」核心抽出一个通用内嵌浏览器：

- Props：
  - `mode: 'trusted-url' | 'untrusted-html'`
  - `url?: string`（trusted-url 模式：iframe `src=url`，**无 sandbox**；外站/原生编辑器跨源，浏览器同源策略保证读不到 SPA token）
  - `srcdoc?: string`（untrusted-html 模式：iframe `srcdoc`，`sandbox="allow-scripts allow-popups"`，**不带 allow-same-origin** → opaque origin，脚本能跑、导航能切，但碰不到父页）
  - `showAddress?: boolean`、`title?: string`
- UI：地址栏（可隐）+ 刷新 + 「用系统浏览器打开」（调 `openExternal`，兜底）。
- 内部维护 `reloadKey`，暴露 `reload()`（供父组件在助手改完后刷新）。

**安全要点（务必写进实现）**：`allow-scripts` 与 `allow-same-origin` 绝不同给（同给 = 沙箱逃逸，脚本能读父页 token）。桌面包里 SPA 与后端 sidecar **同源**，所以不可信的 AI HTML 一律走 srcdoc + 仅 `allow-scripts`（opaque），不可走「后端真实 URL + 无 sandbox」。

可选收尾任务：让 `RunDebugPanel` 复用 `InAppBrowser` 核心（有 `RunDebugPanel.spec.ts` 兜底）。Codex UI 刚稳定、较脆，此重构放最后、绿不了就跳过，不影响功能。

### 4.2 ChatPage 改造
- 「设计」tab：保留 `ApaasMenuSidebar`；MODEL 菜单的内容体由「designer shell + 6 sub-tab 自渲染面板」换成一个 `InAppBrowser`（trusted-url，绑 `getEditorUrl` 结果）。CUSTOM 菜单分支保留 `CustomPagePreviewPanel`。
- 删除「数据/流程/权限」顶部 tab 及其面板体。
- `getEditorUrl` 取 `url`（具体菜单编辑器）；其 `entry_url` 用于返回历史，内嵌场景非必需。
- 助手刷新：把现有 `@refresh-iframe="refreshPlatformAndSidebar"` 接到新内嵌 iframe 的 `reload()`（并刷新菜单目录）。
- 顶部 tab 收敛建议（评审确认）：配置（设计）/ SPEC / 自开发 / 体检 / 日志 /（数据源？）。原 `dev`、`health` 这两个从「designer sub-tab」提升为顶部入口（因为承载它们的 designer shell 被删）。

### 4.3 AIChatPage 设计稿 HTML 预览（独立小修）
`AIChatPage.vue` 的设计稿 HTML 产物预览（如 `MES系统V0界面原型.html`）当前 iframe sandbox = `allow-same-origin allow-popups`（无脚本）→ 多页导航点不动。改为 `allow-scripts allow-popups`（去掉 same-origin）→ opaque origin 安全、脚本可跑、多页能切。可直接改属性，或复用 `InAppBrowser` 的 untrusted-html 模式。**此项与第 3、4.2 节解耦，可单独提交/发布。**

## 5. 数据流

1. 用户在菜单目录点菜单 → `onApaasMenuSelected({menu_id, menu_type, form_id, ...})` 存 selected 状态。
2. MODEL 菜单 → 调 `getEditorUrl(appId, {menu_type, menu_id, form_id})` → 拿 `url` → `InAppBrowser(mode='trusted-url', url)`。
3. 首次 iframe 内显示 apaas 登录页 → 用户登录 → apaas 写自己 origin 的 localStorage → 之后免登。
4. AI 助手对话改配置（MCP，不变）→ 完成后 emit `refresh-iframe` → `InAppBrowser.reload()` → 原生页重载显示新配置。
5. CUSTOM 菜单 → `CustomPagePreviewPanel`（自开发渲染，不变）。

## 6. 删除 / 保留清单

### 删除（apaas 原生配置自渲染，被内嵌编辑器取代）
- 面板：`FormDesignerPanel`、`ListDesignerPanel`、`ProcessDesignerPanel`、`DataSchemaEditor`、`FormPermPanel`、`BusinessEventPanel`、`DataModelDetailPanel`、`DictEditorPanel`、`RoleManagePanel`。
- 深链按钮：`OpenLowcodeBackendButton`（编辑器已内嵌，深链多余）。前端 `editorUrl.ts` 的 `getEditorUrl` **保留**（内嵌要用它生成 URL）。
- ChatPage 顶部「数据 / 流程 / 权限」tab 及其内容分支；designer sub-tab 中 form/list/process/event/data/perm。
- 连带的死状态/导入（随删随清，按实现期 grep 核）。

### 保留（不是 apaas 配置自渲染 —— 我们自己做的）
- `CustomPagePreviewPanel`（自开发 Vue 页面预览 / 跳 IDE）。
- `AppDevWorkspacePanel`（自开发资产 / IDE）。
- `AppHealthPanel`（应用体检）。
- `SpecDesignPanel`（SPEC 设计层）。
- `LogsPanel`（日志）。
- `AppAssistantPanel`（AI 配置助手）、`ApaasMenuSidebar`（菜单目录）。
- `AppDatasourcePanel`（数据源只读）—— 评审确认是否保留。

### 后端编辑器 URL（保留并可能补全）
- `backend/app/apaas_editor_url.py` 的 `build_editor_path` / `getEditorUrl` 接口保留。
- MCP 配置工具（add/update/disable model field、set role permission 等）保留（AI 助手改配置用）。

## 7. 风险与缓解
- **apaas 引擎偶发崩（回首页）**：闭源、非我们能修；用户已接受。缓解 = `InAppBrowser` 留「用系统浏览器打开」兜底。
- **非 MODEL 菜单类型编辑器 URL 落点不精准**：`build_editor_path` 对未知 menu_type 回退到通用 `fn-config` / 应用编辑总览。实现期在真实 app 上逐菜单类型核对，必要时补 `_MENU_TYPE_TO_EDITOR_PATH` 映射。
- **内嵌 iframe 的 apaas「关闭」按钮**（`$router.go(-1)`）在无历史时可能空操作 —— 我们的菜单目录才是真导航，可接受；必要时先载 `entry_url` 再载具体编辑器。
- **登录态**：内嵌 iframe 用主 webview 的 cookie/storage 分区，登一次后会话内持久；生产挂 apaas 下免登。
- **删除面积大**：是一个大 PR，前后端测试都要跟（删测试 + 新内嵌渲染测试）。

## 8. 测试策略
- 单元/组件：`InAppBrowser.vue`（两种 mode 的 sandbox 属性正确、reload 生效、系统浏览器兜底调用 `openExternal`）。
- ChatPage：选 MODEL 菜单 → 渲染 InAppBrowser 且 src = getEditorUrl 结果；选 CUSTOM 菜单 → 仍走 CustomPagePreviewPanel；refresh-iframe → reload 调用。
- AIChatPage：HTML 产物预览 sandbox = `allow-scripts allow-popups`（不含 allow-same-origin）。
- 删除项：移除对应面板的 import/测试，确保 `build:nocheck` 通过、无悬空引用（grep 守卫）。
- 真机验收（用户）：2-3 个真实 app，逐菜单点开内嵌编辑器，确认渲染稳定、可编辑保存、AI 改完刷新生效、登一次免登。

## 9. 实现期细化（不阻塞设计）
- 顶部 tab 最终列表与 `dev`/`health` 的安置。
- `AppDatasourcePanel` 去留。
- `RunDebugPanel` 是否复用 `InAppBrowser`（可选、最后做）。
- 删除后 ChatPage 脚本里随之变成孤儿的状态/函数清理范围。
