# AI Coding 自开发「分场景入口 + 装回应用 + 重新发布」接入 — 设计 spec

> **状态**:设计已与用户对齐(2026-06-02,v2 — 借鉴 Claude Design 原型修订),待写实施计划。
> **缘由**:AI Coding 已能生成 + 构建自开发包,但「装回应用 + 重新发布」只接了一半(只有上传到组件库 `upload-to-platform`,attach / 建菜单 / 重新发布 没接进 AI Coding)。本 spec 把完整链路接进 AI Coding,**并借鉴 `docs/design-refs/2026-06-02-coding-prototype/`(Claude Design 原型)里 Coding 模块的两处交互**:① 分场景入口(在应用上定制 / 做通用组件);② 「装回应用」确认弹窗。

## 借鉴的原型交互(来源:`screens_coding.jsx`)
1. **分场景入口**(`CodingEntry`):进入 AI Coding 先选两种模式 —— **在应用上定制**(绑定已有 app、复用其模型/接口/枚举)/ **做通用组件**(不绑 app、产物进自开发资产库、跨应用复用)。入口顶部有「目标应用 / 产物去向」反映当前选择,示例 chips 随模式切换。
2. **「装回应用」InstallModal**(`InstallModal`):点「装回应用」弹确认框,明确列出后果(应用页面挂到哪个菜单 / 路由 / 权限继承 / 资产登记)+「编译通过」badge → 取消 / 确认装回。
3. (顺手)**上下文 banner**:Coding 会话顶部持久显示绑定的 app 上下文(如 `上下文 · 销售 CRM · 4 模型 / 1 审批流 / 4 角色`)。

## 目标
AI Coding **进入时分场景**(绑定 app 定制 / 做通用组件),决定产物去向;开发完成后,用户**显式点「装回应用」**,在确认弹窗里看清后果并确认,系统把自开发包**上传 → attach 到应用 → 页面类建菜单 → 重新发布**让组件生效。覆盖全场景类型(组件 / 页面 / 后端)。

## 已对齐的关键决策
1. **分场景入口**:在应用上定制(bound)/ 做通用组件(lib)二选一,**决定是否有 attach 目标**:bound → 部署到该 app;lib → 只进自开发资产库(不 attach 到具体 app)。
2. **触发 = 显式按钮**(借鉴原型,修订原 v1 的「build 后自动」):codegen build 只产出 workspace 产物;用户点**「装回应用」**(在 InstallModal 确认后)才走完整 `build_and_package → 上传 → attach → 建菜单 → republish`。整条链路都在确认之后,不在 build 时自动发生。
3. **republish 必须在确认弹窗里点确认**(唯一改 live 应用的动作)。
4. **agent 边界**:codegen agent 工具集**保持只读不变**;部署编排走**后端路由**,不走 agent 工具(守 v2「Coding=纯开发」)。
5. **目标 app 解析(两个 id 别混)**:bound 模式从「目标应用」选择器拿**本地 app_id** → 查 `Application` → 得 `apaas_app_id = Application.platform_app_id`。attach/enable/建菜单走 **apaas_app_id**;republish/广播走**本地 app_id**。**绝不用 hardcode 默认 app `806997227284201472`**。
6. **范围**:全类型(form-component/dual、menu-page/form-page/mobile-page、backend-*)。
7. **落点**:新增后端编排端点(方案 A),`upload-to-platform` 原端点保持「纯上传」语义不动。

## 现状:积木齐全,缺「编排 + AI Coding 侧接线」
**已有(直接复用)**:
- 上传:`backend/app/routes/coding.py:upload_workspace_to_platform`(2541)—— 构建 + 打包 + `selfdevelopment/add|update/developmentKit`,含 dual / jar / token 自愈 `_refresh_env_token` / `_query_existing_development_kits` / `_find_kit_by_filename` / `_build_upload_form_data` / `_PROJECT_TYPE_TO_FILE_TYPE`(2424)。
- attach / 建菜单 / enable:`backend/app/apaas_client.py` —— `attach_apaas_source_relation`(1181)、`enable_self_dev_config`(1127)、`create_self_dev_menu`(1255)。
- 重发 + 广播:`backend/app/routes/applications/extension.py` —— `POST /{app_id}/republish`、`publish_extension_update(app_id, event_type, payload)`(99)、`/extension-update-events`(SSE)。
- 构建打包:`backend/app/coding/workspace.py` —— `build_and_package` / `build_and_package_dual` / jar 输出目录。
- 前端:`frontend/src/api/coding.ts:uploadToPlatform`、`frontend/src/api/extension.ts:republishApplication`、`frontend/src/components/v2/ExtensionSectionPanel.vue`(republish 交互范式)。
- 设计参考:`docs/design-refs/2026-06-02-coding-prototype/`(原型源)。

**缺(本 spec 要建)**:分场景入口(模式 + 目标应用)、部署编排端点、「装回应用」InstallModal、context banner。

## 设计

### ⓪ 分场景入口(AI Coding 新会话)
进入 AI Coding 时,顶部两模式卡(借鉴原型 `CodingEntry` 视觉,用真实 design-v3 tokens):
- **在应用上定制(bound)**:下方出「目标应用」选择器(默认 = 会话/handoff 绑定的 app,可改)。产物部署目标 = 该 app。
- **做通用组件(lib)**:下方出「产物去向 = 自开发资产库」。无 attach 目标。

模式 + `detect_scene` 的场景类型(页面/组件/接口)共同决定后续部署步骤(见 ③)。
> 现状 CodingPage 是「直接输入需求」单入口;本 spec 在其前面加这层轻量分场景选择(可折叠,熟练用户直接输入仍走默认 bound + 当前绑定 app)。

### ① 后端编排端点(方案 A)
新增 `POST /workspace/{ws_id}/deploy-to-app`(admin 权限,复用 `_ensure_workspace_access`):
```
入参: { local_app_id? }   # bound 模式传;lib 模式不传
1. 解析目标:
     bound + local_app_id → 查 Application → apaas_app_id(=platform_app_id)
       任一拿不到 → 报错「应用未绑定 / 未配 platform_app_id」(不静默 fallback)
     lib(无 local_app_id) → 走「只上传」分支(step 5)
2. build_and_package(复用;dual / jar 分支)
3. 上传 developmentKit(复用 upload_workspace_to_platform 上传逻辑,update-if-exists + token 自愈)→ kit_id(s)
4. bound:
   a. attach_apaas_source_relation(apaas_app_id, object_ids=[kit_id...])
   b. 页面类(menu-page/form-page/mobile-page):enable_self_dev_config(apaas_app_id,"ENABLE") + create_self_dev_menu(apaas_app_id, 菜单名=display_name)
   c. republish:调用现有 republish 逻辑(/applications/{local_app_id}/republish 复用,或同等 APaaSClient 调用)
   d. publish_extension_update(local_app_id, "republish_done", {...})  # 广播给开着的 ExtensionSectionPanel
   e. return { status:"installed", app:{local_app_id,name}, route, menu, kits }
5. lib / 无 app:
   return { status:"uploaded_only", hint:"已传到自开发资产库,可在表单设计器引用 / 去 Builder 关联应用" }
```
> 本端点 = 「确认装回」的动作:**只由 InstallModal 的「确认装回」触发**,一次跑完 step 2-5(含 republish)。codegen build 阶段**不调本端点**(只把产物留在 workspace)。这样唯一改 live 应用的动作(republish)永远在用户确认之后。

### ② 「装回应用」InstallModal(借鉴原型,部署确认 UX)
点「装回应用」→ 弹确认框,**确认前**先 dry-run 算出后果并列出:
- **应用页面**:`OpportunityBoard.vue → 挂在「X」模块菜单下`(页面类才有)
- **路由**:`/{app_code}/.../board`(页面类)
- **权限**:沿用应用现有角色的数据范围
- **资产登记**:同时登记到自开发资产库,可跨应用复用
- 顶部「编译通过 / 编译失败」badge(build 状态)
- 取消 / **确认装回** → 确认即调 `deploy-to-app` 端点(执行 attach+菜单+登记+republish)→ 成功 toast + 可跳「自开发资产库」。
> lib 模式无「装回应用」按钮,代之以「发布到资产库」(只上传)。

### ③ 场景类型分支(全类型)
| project_type | fileType | bound 部署步骤 |
|---|---|---|
| form-component / form-component-dual | FRONTCOMPONENT(双端各一) | upload → attach |
| menu-page / form-page | FRONTENGINE | upload → attach → enable_self_dev_config + create_self_dev_menu |
| mobile-page | MFRONTENGINE | 同上 |
| form-list / layout / plugin | FRONTLISTVIEW / FRONTLAYOUT / FRONTTENANTCOMPONENT | upload → attach |
| backend-api / feign / scheduled | BACKENDENGINE | jar upload → attach |
(fileType 复用现有 `_PROJECT_TYPE_TO_FILE_TYPE`;最后都需 republish 生效。)

### ④ 前端(CodingPage)
- **新会话入口**:分场景两模式卡 + 目标应用选择器(⓪)。
- **会话顶部 context banner**:bound 模式持久显示 `上下文 · {app名} · N 模型 / …`(借鉴原型)。
- **产物面板 / IDE topbar**:`bound` → 「装回应用」按钮(→ InstallModal);`lib` → 「发布到资产库」按钮。复用现有 `cap-*` 产物面板区,不新开页面。
- republish 成功后 toast;同时后端广播让 Builder 侧 ExtensionSectionPanel 同步。

### ⑤ 错误处理
upload / attach / menu / republish **各步独立 try**,失败给人话提示(带 error_code/message),**不连带回滚**(已上传 kit 留着可重试);token 过期复用 `_refresh_env_token`。build 失败 → InstallModal 显「编译失败」且禁用「确认装回」。

### ⑥ 人工闸门 & 边界
- codegen build:只产出 workspace 产物,不碰平台。
- 上传 + attach + 建菜单 + 登记 + **republish**:**全部在用户点「确认装回」之后**由 `deploy-to-app` 一次跑完(InstallModal 是唯一闸门)。
- codegen agent 工具集**不变(只读)**;`upload-to-platform` 原端点**不动**;composer / 历史回放 / 会话区 native 渲染(本 session 已统一)/ IDE(code-server)**不动**。

## 关键文件
- 新增/改:`backend/app/routes/coding.py`(新 `deploy-to-app` 端点,抽出上传逻辑复用)
- 复用:`backend/app/apaas_client.py`(attach/enable/menu)、`backend/app/routes/applications/extension.py`(republish/broadcast)、`backend/app/coding/workspace.py`(build/package)
- 前端:`frontend/src/api/coding.ts`(加 `deployToApp`)、`frontend/src/views/CodingPage.vue`(分场景入口 + context banner + 装回应用按钮 + InstallModal)、`frontend/src/api/extension.ts:republishApplication`(复用)
- 设计参考:`docs/design-refs/2026-06-02-coding-prototype/`(`screens_coding.jsx` = CodingEntry + InstallModal + context banner;`tokens.css` = design-v3)

## 风险 / 约束
- **republish 改 live 应用**:必须在 InstallModal 确认,且列清后果。
- **目标 app 误判**:绝不自动 attach 到 hardcode 默认 app;bound 解析不到就报错,lib 走只上传。
- **场景类型多**:页面类的 enable+建菜单 与组件类不同,后端 jar 路径不同 —— 用 project_type 显式分支,缺映射的类型走「只上传 + 提示」。
- **CodingPage 已超大**:分场景入口 + InstallModal 抽成独立组件/composable,产物面板改动控制在 `cap-*` 区,不动消息区。
- 验证:后端 `deploy-to-app` 各分支手测;前端 `npx vite build`;真实 trial 跑 组件 + 页面 两类 build→装回→republish 端到端;入口分场景 + InstallModal 对照 `docs/design-refs/.../screens_coding.jsx` 视觉。

## 范围外(v1 不做)
- 组件版本管理 / 回滚 UI。
- 多 app 批量部署。
- 给 codegen agent 写/部署权限(刻意不做,守 v2 边界)。
- 原型里的 Builder 屏 / 资产库屏 / 首页定位屏的视觉重做(本 spec 只接 Coding 的部署链路 + 分场景入口)。
