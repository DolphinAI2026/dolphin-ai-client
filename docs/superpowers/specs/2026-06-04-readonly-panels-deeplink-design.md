# 配置面板去内嵌编辑 → 只读自渲 + 深链低代码后台 — 设计

> 日期: 2026-06-04
> 状态: 待用户 review spec
> 范围: ai-builder「应用调整/应用配置」的所有面板改为只读自渲 + 每面板「打开低代码后台」深链；删掉整个反向代理内嵌编辑（崩溃源）。

## 背景

应用配置区（`/chat` ChatPage 宿主）今天是**混合**架构：每个设计面板有「业务/设计」开关——「业务」侧是我们自己的只读 Vue 组件渲我们自己的数据，「设计」侧挂 `ApaasEmbedIframe`（经 `platform_proxy.py` 反向代理内嵌 aPaaS 原生编辑器）。内嵌编辑器经反向代理渲染**极易崩溃回首页**——根因是 aPaaS 渲染引擎自身 bug（闭源、改不了，见记忆 `apaas_editor_embed_crash_2026_05_30`）。

用户实测又遇到：流程图渲染位置跑偏（需手点「适应」才出来）；且重申内嵌方式不稳。

### 关键事实（来自架构调查 2026-06-04）
- 面板在 `frontend/src/components/v3/`：`FormDesignerPanel.vue`、`ListDesignerPanel.vue`、`ProcessDesignerPanel.vue`、`DataSchemaEditor.vue`、`FormPermPanel.vue`、`RoleManagePanel.vue`。
- **每个面板的"业务/只读"侧已是我们自己的组件、读自己的数据**——只读 UI 大部分已存在。崩溃只在"设计"侧的 `ApaasEmbedIframe`。
- 内嵌全走反向代理 `backend/app/routes/platform_proxy.py`（~865 行：代理 + `_inject_sso_script` SSO 注入 + 藏 header + 静态缓存）。编辑器 URL 由 `platformIframe.ts` 构造、`ApaasEmbedIframe.vue` 挂载。
- `_build_menu_redirect_path`（`platform_proxy.py:418-462`）已能产每资源 URL：`/platform/{tid}/default/data-model-fn-config?appId=&menuId=&formId=&embed=1&hideClose=1`、总览 `/platform/{tid}/admin/app-store/edit-app?appId=`。
- runtime 深链已上线：`GET /{app_id}/apaas-access-url`（`section_content.py:723`）→ `{host}/app/{tenantCode}/{appCode}/`；`ListDesignerPanel.openApaasApp()`（:495-508）`window.open(access_url, '_blank')`。
- SSO 桥：用户持 live `ctx.user.apaas_token`；`POST /auth/exchange-apaas-token`（`auth.py:1107`）。
- 流程时间轴：真拓扑（`/processes/{id}/definition` + `/apaas-detail`，`tryLoadLocalDefinition` :1095）；**但实例进度是 mock**（`mockInstance` :319-332、`calcMockInstanceProgress` :665 硬编造"张三/李四/SQDH-2026-001"）。
- 「适应」按钮 `onFitContent()` :894 是我们 x6 画布的、**仅手动**——`renderDefinition()` :1031 渲完从不 `zoomToFit`，故新图可能在视口外（point 1 的 bug，1 行修）。

## 目标

app 内 = **只读展示** + AI 配置（对话）；手动编辑 = **真低代码后台**（深链新标签页、SSO 免登）。所有配置面板改成只读自渲 + 每面板「打开低代码后台」深链。删掉整个反向代理内嵌编辑链路。

用户决策（已确认）：
1. 3 个没有原生只读视图的 tab（字段权限/菜单可见性/业务事件）**也改深链**——以便**彻底删代理**。
2. 深链**每面板各一个**，直落对应资源编辑器（非全局总览）。
3. **全部面板只读+深链**（含我们自己写的 schema CRUD / 角色权限编辑器也去掉编辑、统一深链）——心智统一。
4. 流程时间轴**去掉 mock 实例进度**，只留真拓扑 + 节点角色。

## 设计

### 原则与边界
- 凡"编辑"一律 → 深链低代码后台。app 内零内嵌、零反向代理。
- 只读渲染尽量复用现有"业务视角"组件；移除编辑控件/写路径。
- 低代码后台编辑器本身不动；本设计只改"怎么进编辑"。

### 单元 1：后端深链接口 `GET /applications/{app_id}/editor-url`
- **职责**：给定 `menu_type` / `menu_id` / `form_id`（可空，按面板类型传），返回**host-absolute**的 aPaaS 原生编辑器 URL（开在真主机、新标签页用）。
- **接口**：`GET /api/applications/{app_id}/editor-url?menu_type=MODEL&menu_id=...&form_id=...` → `{ "url": "{host}/{tid}/default/data-model-fn-config?appId=...&menuId=...&formId=..." }`。
- **实现**：把 `platform_proxy._build_menu_redirect_path` 的路径拼装逻辑**抽成可独立调用的纯函数**（如 `app/apaas_editor_url.py::build_editor_path(menu_type, app_id, menu_id, form_id) -> str`），新接口用它 + 解析本 app 绑定环境的 `base_url`(host) 与 aPaaS `tid` 拼成 host-absolute URL。**去掉 `embed=1&hideClose=1`**（那是内嵌剥壳用的；真标签页要完整编辑器）。
- **依赖**：app→环境（`PlatformEnv`）解析 host/tid；`ctx`。无反向代理依赖。
- **抽取时序**：必须在删 `platform_proxy.py` **之前**把 `_build_menu_redirect_path` 逻辑迁到 `apaas_editor_url.py`，否则删代理会带走它。
- **SSO 关键风险**（见"实施顺序"）：新标签页开真主机编辑器靠用户浏览器的 aPaaS 会话免登。runtime 深链（openApaasApp）已证同模式可行，但编辑器 URL 首次实测；若不免登，需在 URL 带 auth 参数或先 `exchange-apaas-token` 建会话——Phase A 验证时定。

### 单元 2：共享「打开低代码后台」按钮组件
- **职责**：各面板放一个统一按钮，点 → 调单元 1 接口拿 URL → `window.open(url, '_blank')`。
- **接口**：`<OpenLowcodeBackendButton :app-id :menu-type :menu-id :form-id />`（props 各面板按类型传；缺失时按面板默认）。
- **依赖**：单元 1 接口；现有 request 封装。
- **复用**：runtime 深链 `openApaasApp`（ListDesignerPanel:495）的 window.open 模式照搬。

### 单元 3：面板改只读 + 挂按钮
- **表单/列表/流程**（`FormDesignerPanel`/`ListDesignerPanel`/`ProcessDesignerPanel`）：删「业务/设计」开关与 `ApaasEmbedIframe` 分支（FormDesignerPanel:128-141/58-76、ListDesignerPanel:264-276/34-60、ProcessDesignerPanel:88-106/175-186），保留现有只读渲染为唯一视图，挂单元 2 按钮。
- **数据 schema / 角色 / 权限**（`DataSchemaEditor`/`RoleManagePanel`/`FormPermPanel`）：删编辑控件 + 前端写调用（`DataSchemaEditor` 的 `/crud/model-field/*`、`RoleManagePanel` 的写），保留只读渲染（字段表 / 矩阵），挂按钮。`FormPermPanel` 本已只读，仅加按钮。
- **3 非原生 tab（字段权限/菜单可见性/业务事件）**：删 `ChatPage.vue:327-365` 的 legacy 整页 iframe 分支与 `legacyMode`，换成**轻量占位面板**（一句说明 + 单元 2 深链按钮，无 app 内只读视图）。

### 单元 4：流程时间轴去 mock 实例
- 在 `ProcessDesignerPanel.vue` 去掉 `mockInstance`（:319-332）与 `calcMockInstanceProgress`（:665）相关的"谁批/何时/当前节点"假进度渲染；时间轴只保留**真拓扑节点 + 节点审批角色**（结构是真的）。顶部"业务视角预览 — 申请单 SQDH-... 等待赵六审批"那条假横幅一并去掉。

### 单元 5：删反向代理 + 内嵌（简化主体）
- 前端：删 `ApaasEmbedIframe.vue`、`platformIframe.ts` 的代理 URL builders（`buildPlatformProxyMenuUrl/EntryUrl/StepUrl`）、ChatPage legacy iframe 路径。
- 后端：删 `platform_proxy.py` 整文件（**在单元 1 抽走 `_build_menu_redirect_path` 之后**）；从 `main.py` 摘 `platform_proxy` 路由注册；删随之 dead 的自写编辑端点（`/crud/model-field/*`、角色/权限写接口——计划时逐一确认无其他调用方再删）。
- 删后全局搜残引用（import / 路由 / iframe src / `platform-proxy` 字符串）确保无悬挂。

### 单元 6：修「适应」自动适应（point 1）
- `ProcessDesignerPanel.renderDefinition()`（:1031）末尾、只读态自动调一次 `onFitContent()`（:894，`zoomToFit({padding:32,maxScale:1.2})`），新图加载即居中，不用手点适应。

## 实施顺序（去风险 —— 关键）

**先深链、验证、再删**，避免"删了内嵌兜底但深链不免登 = 没法编辑"的空窗：

- **Phase A（加 + 验证，内嵌还留着）**：抽 `apaas_editor_url.py`（单元 1 纯函数）→ 加 `editor-url` 接口 → 加共享按钮 → 各面板挂按钮（先与现有"设计"模式并存）。**preview 实测**：每面板按钮开真主机编辑器、新标签页 **SSO 免登能正常编辑**。若不免登，先解决（URL 带 token / 先 exchange 建会话）。
- **Phase B（删，验证通过后）**：删「业务/设计」开关与 `ApaasEmbedIframe`、面板编辑控件、legacy iframe、`platform_proxy.py` + 路由 + dead 编辑端点；3 非原生 tab 改占位+按钮；流程去 mock 实例；修适应。
- Phase B 删完跑全量 + preview 回归。

## 测试
- 前端：vue-tsc 类型检查无新错（仓库整体预存坏，只看改动文件）；删代理后全局无 `platform_proxy`/`ApaasEmbedIframe`/代理 URL builder 残引用。
- 后端：全量 pytest 无回归（基线 6 预存失败）；`import app.main` OK（代理路由摘除后）。
- preview 端到端：每面板只读渲染正常（含流程真拓扑、去 mock 后无假进度）；每面板「打开低代码后台」开真主机编辑器、免登可编辑；3 非原生 tab 占位+按钮可用；流程图加载即自动适应。

## 风险 / 注意
- **深链 SSO 免登是承重假设**：Phase A 必须先实测编辑器新标签页确实免登，再进 Phase B 删兜底。runtime 深链同模式已可行但编辑器首次验证。
- 删 `platform_proxy.py` 前务必先抽走 `_build_menu_redirect_path`。
- 删自写编辑端点（schema CRUD / 角色权限写）前逐一确认无其他调用方（可能别处也用）。
- 数据 schema 改只读 = 失去 app 内字段 CRUD（用户已选"全部只读+深链"统一）；确认无依赖 app 内 schema 编辑的下游流程。

## 不在范围
- 真实例进度追踪（需 runtime 实例 API，另议）。
- 低代码后台编辑器本身的任何改动（崩溃是内嵌用法、非编辑器本身）。
- AI 配置（对话改配置）链路不动——它仍是 app 内改配置的主路径。

## 开放问题
- 深链免登的具体落地（依赖会话 vs URL 带 token）——Phase A 实测后定，不阻塞设计。
- dead 编辑端点是否真的全删 vs 留着——计划时按"无调用方"逐一定。
