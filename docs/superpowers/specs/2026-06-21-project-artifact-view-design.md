# 设计:项目 → 产物视图(含跨产物依赖)

- 日期:2026-06-21
- 状态:设计已与用户分节确认;经 4 视角评审(可行性/一致性/范围/设计)修订;待用户复核 → writing-plans
- 分支:`feat/project-artifact-view`(从 dev/0.2.19 拉出,不动 origin)
- 所属:桌面 UI/IA 重设计的第 1 块(共 5 块,见 §8)

## 术语(先统一,避免混用)

- **产物(artifact)**:一个 Project 下网格里的一张卡 = 一个**工作区**,或该项目绑定的**那一个 aPaaS 应用**。
- **工作区(workspace)**:`listWorkspaces` 返回的一条 coding workspace(自开发扩展或全代码)。
- **应用(app)**:项目绑定的 aPaaS `platform_app`(低代码应用本体)。
- **模式(mode)**:每个产物属一个模式 —— build(应用本体)/ lowcode(低代码二开)/ fullcode(全代码)/ agent(智能体);各有色标。

## 1. 背景与动机

用户提供了一份完整的桌面 UI 重设计原型(`AI Builder Desktop.html`,Claude Design 导出)。整份是多子系统大工程,已拆成 5 个 sub-project,本 spec 只覆盖**第 1 块:项目 → 产物视图**。

选它打头阵:**自包含**(复用已有 `/project/:id`,不需先动新壳/rail)、**价值最高**(它是已落地的多产物分解后端的展示层,也是竞品分析点名的护城河)、**先验证视觉**(在一个高价值小屏上先验证新视觉语言,刻意避开上一版「先整壳结果难看被否」的坑)。

原型里这一屏:项目标题+描述+meta(N产物·M成员·创建日);产物按模式分组网格;每卡有模式图标、模式标签、名称、摘要、状态点+标签+时间;底部「跨产物依赖」区(配置端暴露 `/api/ticket` → 用户端 consume ticketApi + 提示「改配置端字段会影响用户端」)。

## 2. 范围(v1)

确认的四个范围决策:

- **落地方式**:就地升级 `/project/:id`(`ProjectOverview.vue`),不碰新壳 / rail。
- **动作范围**:展示 + 导航。产物网格+分组+状态+依赖图展示;点产物跳现有页面;新增动作按钮(重新部署/继续构建/新建产物)置灰带 tooltip(文案见 §5.4)。
- **跨产物依赖**:声明式——分解时由 LLM 声明产物间关系,存库,前端渲染;**不**自动扫码探测。
- **复用**:cherry-pick origin/dev 的非视觉地基(`projectVM.ts` 的类型/适配器骨架 + 模式色 token),视觉层重做;**不**搬 ProjectRail/ProjectSessionsPanel/ProjectView(属后续「同壳」sub-project)。

**明确不在 v1**:自动探测依赖;写动作(新建产物/重新部署/继续构建/成员管理写);新壳与 rail;UI 里手动声明依赖边;低代码应用的实体/页面/业务流计数富化(§9)。

## 3. 统一「产物」模型

一个项目的产物混合来自两处,前端用复用的适配器拼成统一列表 `ArtifactVM[]`:

| 来源 | 产物 | 模式由 §3.1 决定 | 摘要(§3.2)、状态(§5.2) |
|---|---|---|---|
| `project.platform_app`(若 `platform_connected && platform_app_id`) | aPaaS 低代码应用 | build(青 `--build`) | 摘要=「低代码应用」(计数富化延后 §9);状态=已部署/草稿 |
| `listWorkspaces` 每条工作区 | 工作区 | 见 §3.1 表 | 摘要=类型标签;状态=由 `WorkspaceStatus` 归一 |

### 3.1 模式映射 `projectTypeToMode(project_type)`(纯函数,替代 sceneToMode)

> 评审 blocker:工作区数据只有 `project_type` 没有 `scene`,且 origin/dev 的 `sceneToMode(scene)` 正则会误分(backend-* 落 lowcode、mobile-page 落 fullcode)。故**新写** `projectTypeToMode(project_type)`,用 `ProjectType` 枚举值精确映射,不复用 `sceneToMode`。

| project_type 值 | 模式 | 说明 |
|---|---|---|
| `backend-api` / `backend-feign` / `backend-scheduled` | **fullcode**(紫) | 后端自开发代码 |
| `form-component-dual` / `form-page` / `menu-page` / `mobile-page` / `form-list` / `layout` / `plugin` / `web-login` | **lowcode**(靛) | 前端 aPaaS 低代码二开扩展 |
| (`platform_app` 应用本体,单独处理,非工作区) | **build**(青) | |
| 未知值 | **lowcode**(兜底) | 不丢产物,记 log |

> **⚠️ 待你拍板的分组决策**:按上表,招聘 dogfood 的两端(admin=`form-list` / user=`mobile-page`)都落 **lowcode**,会同进「低代码」一组,而非设计稿画的「低代码配置端 vs 全代码用户端」两组。这是因为 `mobile-page` 真实身份是 aPaaS 低代码移动页,不是全代码。
> - **方案 1(v1 采用,推荐)**:按 project_type 真实语义分组,组 = 实际出现的模式。诚实、零后端。设计稿的低/全代码逐产物切分视为示意。
> - **方案 2(延后)**:让 decompose 每个 artifact 多声明一个 `mode`,存进工作区 meta,严格还原设计稿分组。+ 一点后端。
> 本 spec 按方案 1 写;复核时若你要严格还原设计稿,改走方案 2。

### 3.2 摘要 `projectTypeToLabel(project_type)`(纯函数)

> 评审 blocker:产物卡「摘要」全链路无数据源(工作区 meta 不存 description/sub_request)。v1 摘要 = project_type 的人类可读标签,零后端:

`form-list`→「表单列表页」/ `mobile-page`→「移动端页面」/ `form-page`·`menu-page`→「菜单页面」/ `form-component-dual`→「自开发组件」/ `layout`→「自定义布局」/ `plugin`→「插件」/ `web-login`→「登录页」/ `backend-api`→「后端接口」/ `backend-feign`→「外部调用」/ `backend-scheduled`→「定时任务」/ 应用本体→「低代码应用」/ 未知→原值。

### 3.3 点产物去向(真复用现有跳转)

- 低代码应用本体 → 复用 `ProjectOverview` 现有 `goToAppBuilder`:`router.push({path:'/chat',query:{project_id}})`。
- 工作区(任意模式)→ 复用现有 `openWorkspace`:`router.push({path:'/coding',query:{workspace_id}})`(CodingPage onMounted 已消费 workspace_id)。

## 4. 后端设计(声明式依赖:存 + 吐)

仓库无 alembic,用 `Base.metadata.create_all`(`app/database.py:63`):**新表**自动建(零迁移),给已有表加列要手写 ALTER —— 故选新表,不在 Project 上加 JSON 列。

### 4.1 新表 `ProjectArtifactDependency`(`app/models/__init__.py`,仿 `ProjectMember`:207)

字段:`id` PK / `project_id` FK→`projects.id` `ondelete=CASCADE` index / `from_ref` str / `to_ref` str / `expose_label` str / `consume_label` str / `note` str / `created_at`。

**ref 形式**:`workspace:<ws_id>`。`app:<platform_app_id>` 形式在 schema 里**保留作前向兼容,但 v1 不产生**(见 §4.5)。多租户:经 `project_id` FK 随 project 作用域隔离,v1 不加 `tenant_id` 列;删项目时 CASCADE 连带删边。

### 4.2 分解器声明边(`decompose.py`)—— 用并列函数,不动现有契约

> 评审 major:把 `parse_decomposition` 返回从 `list[Artifact]` 改成 dict 会破坏 `decompose()`/`run_multi_artifact`/6 个现有单测。故**新增独立纯函数**,`parse_decomposition` 签名与返回**不变**:

- `_DECOMPOSE_PROMPT` 增补:让 LLM 在 `artifacts` 外**可选**输出 `dependencies:[{from,to,expose,consume,note}]`,`from`/`to` 是 artifact 的 **index**(整数,0 起)。
- 新增 `parse_dependencies(raw_json, n_artifacts) -> list[dict]`:解析 `dependencies`,逐条校验 `from`/`to` 是 `[0,n_artifacts)` 内整数、非自引用、`expose`/`consume`/`note` 转字符串;任一非法 → 丢弃该条;整体非法/缺失 → 空列表(延续「非法即回落、永不更糟」)。
- `decompose()` 同时返回 artifacts 与 dependencies(用元组或在外层多 parse 一次);**v1 仅工作区间依赖,index 引用 index**(应用不在分解计划里、无 index)。

### 4.3 编排时落库(`orchestrate.py`)

`run_multi_artifact` 跑完已持有 `results`(每 artifact 的 `index → workspace_id`)。在 `yield summary` 前新增一步:把声明的边按 index 取两端 `workspace_id`,组成 `from_ref=workspace:<ws_id>` / `to_ref=workspace:<ws_id>` 批量写入新表;某端 ws_id 缺失(该产物失败)→ 跳过该边;落库异常仅 log 不中断(best-effort,延续现有风格)。

### 4.4 读接口

- `GET /projects/:id/dependencies` → 返回边列表 `[{from_ref,to_ref,expose_label,consume_label,note}]`;鉴权同其他 `/projects/:id` 子接口(`can_view`)。挂到现有 projects 路由文件(plan 阶段定位,与 `listWorkspaces`/`listMembers` 端点同处)。
- 前端 `projectsApi` 加 `listDependencies(id)` + `ArtifactDependency` 类型。

### 4.5 v1 诚实边界

- 依赖只对**本次改动之后新生成的多产物项目**有数据(需 decompose 声明);老项目 / 单应用项目 → 无边 → 前端依赖区隐藏(优雅降级)。
- v1 依赖边**仅 workspace↔workspace**;低代码应用本体仍作产物卡展示+可跳转,但 v1 不参与依赖边(`app:` ref 不产生)。
- 以上写入验收说明,免得被当 bug。

## 5. 前端设计(`ProjectOverview.vue` 重做)

### 5.1 组件边界(避免过度拆分)

> 评审范围:ProjectHeader/ProjectHero 在 v1 只有 ProjectOverview 一个消费方 = 过早抽象。故**不**新建这两个文件,作为页面内模板分段;跨视图共享 header 等到「同壳」sub-project 再提取。

独立单元(有真实复用或独立逻辑,才单列):
```
ProjectOverview.vue            页面容器:面包屑+成员+溢出菜单(页内段)、Hero(页内段)、编排
├─ ArtifactGroup.vue × N       每个模式组一个 → 渲染 ArtifactCard 网格
│   └─ ArtifactCard.vue × M     单产物卡(N组×M卡,真复用)
└─ ArtifactDependencyGraph.vue 跨产物依赖区(独立逻辑;无边整块隐藏)
纯逻辑(可单测,不进组件):
  composables/useProjectArtifacts.ts   数据编排
  projectVM 内:projectTypeToMode / projectTypeToLabel / normalizeArtifactStatus / buildArtifacts / resolveDependencies
```

### 5.2 数据流 `useProjectArtifacts(projectId)`

- 并行拉 `projectsApi.get` + `listWorkspaces` + `listMembers` + `listDependencies`。
- `buildArtifacts(project, workspaces)`:`[platform_app?]` + `[workspaces]` → `ArtifactVM[]`,按 `projectTypeToMode` 分组、每卡填 `projectTypeToLabel` 摘要 + `normalizeArtifactStatus` 状态。
- `resolveDependencies(edges, artifacts)`:边按 `from_ref`/`to_ref` 解析到产物;悬空 ref(产物已删)跳过。
- 返回 `{ project, groups, dependencies, members, loading, error }`;四请求**各自独立降级**(成员挂显 0、工作区挂只显应用…),沿用 origin/dev `useProjectsVM` 的降级范式(见 §5.5)。

### 5.3 状态归一 `normalizeArtifactStatus`(纯函数)

输入 `WorkspaceStatus`(creating/installing/ready/building/error)或应用部署态 → `{label, tone}`:

| 原始 | label | tone |
|---|---|---|
| `creating`/`installing` | AI 在写 | building |
| `building` | 构建中 | building |
| `ready` | 已完成 | done |
| 应用已部署 | 已部署 | live |
| 应用未部署 / 无状态 | 草稿 | draft |
| `error` | 失败 | error |
| 未知 | (原值) | draft |

tone→状态点色 + 文案;同时存在多状态时优先级 `error > building > live > done > draft`。

### 5.4 渲染细节与无障碍(评审 design 补)

- **依赖图**:线性列表(from-chip → 箭头+标签 → to-chip,下一行 note)。分解 N≤4 → 边通常 ≤6;超 6 条折叠「展开更多」。`expose_label`/`consume_label` 单行截断(line-clamp:1,≤24 字)。自环后端已滤、前端再跳过。
- **产物卡**:名称 line-clamp:2;卡 min-height ~80px(无摘要也不塌)、min-width ~200px;网格 `auto-fill,minmax(200px,1fr)`,窗口 <600px 退单列。
- **状态**:点 + 文案**始终并排**,不许只剩色点;点带 `aria-label`/`title`;`error` 额外加 `!` 图标(不只靠红色)。
- **loading**:Hero 的 meta(N产物·M成员)数据到达前显「—」;每个 ArtifactGroup 出 2 张 skeleton 卡;依赖区在 `listDependencies` 返回前隐藏(无论有无边)。
- **模式色用法**:仅用于装饰性图标 / 边框 / chip 背景(对比度 ≥3:1 即可),**不**作正文文字色;深色模式沿用 token(若某色将来要做文字色,再在 `[data-theme=dark]` 重定义提亮变体)。
- **置灰按钮 tooltip 文案**:新建产物→「即将支持:当前请在对话里发起多产物分解」;重新部署→「即将支持」;继续构建→「即将支持」。

### 5.5 复用 origin/dev 地基(cherry-pick,不重写)

- `frontend/src/composables/projectVM.ts`:复用 `ArtifactVM`/`ProjectVM` 类型与适配器骨架;**`sceneToMode` 不用,改写 `projectTypeToMode`**(§3.1),并加 `projectTypeToLabel`/`normalizeArtifactStatus`/`resolveDependencies`。
- `frontend/src/styles/design-v3-tokens.css` 的模式色(`--build/--lowcode/--fullcode/--agent` + `-bg`)。
- `frontend/src/composables/useProjectsVM.ts`:**仅参考**其失败降级范式(不直接调用,可不 cherry-pick)。
- **不**搬 `ProjectRail.vue`/`ProjectSessionsPanel.vue`/`ProjectView.vue`。

## 6. 错误处理 / 边界

- 项目不存在 / 无权限 → 错误态(复用现有)。
- 未连平台 → 无应用产物,只渲工作区;两者皆空 → 空态「还没有产物」(纯提示)。
- `listDependencies` 失败或空 → 依赖区整块隐藏。
- 依赖边引用的 ref 找不到产物(已删)→ 静默跳过 + log。
- 四请求各自独立降级,全程不白屏。
- 未知 `project_type` → lowcode 兜底 + log;未知状态 → draft tone + 原文标签。

## 7. 测试策略

仓库 vitest `environment:'node'` 无 DOM:组件测试只能 `?raw` 源码字符串检查,**不能** mount(durable 踩坑)。

- **纯函数真单测**(高价值靶子):
  - 前端 `projectTypeToMode`(每个枚举值 + 未知兜底)、`projectTypeToLabel`、`normalizeArtifactStatus`(全词表 + 优先级 + 未知)、`buildArtifacts`(应用+工作区→分组排序)、`resolveDependencies`(悬空 ref 跳过)。
  - 后端 `parse_dependencies`(index 越界/自引用/非法丢弃、空回落)、orchestrate 边解析(假 results → 正确 ref、某端缺失跳过)。
- **后端接口测**:`GET /projects/:id/dependencies` 返回正确、`can_view` 鉴权、空时空数组。
- **回归**:`parse_decomposition` 现有 6 单测必须零改动通过(证明并列函数没破坏契约)。
- **组件**:`?raw` 检查关键绑定/类(轻量,非行为)。
- **端到端真验(验收门)**:本地 tenant1 gpt-5.5 omnigate 真跑一次多产物分解,确认依赖边显示 + 产物卡能跳。改后端必重启进程(`run.py` reload=False)。

## 8. 上下文:5 块拆分(本 spec = 第 2 块)

1. 三模式同壳 + 项目主导左栏(容器:Builder/Agent/Code 切换 + rail 替换 + 模式色铺底)
2. **项目 → 产物视图 + 跨产物依赖** ← 本 spec(刻意先行以验证视觉语言)
3. 三模式首页 + composer + 自动路由
4. 得小帆能力中心(技能/MCP/AI 网关/知识库,三档共用)
5. 各模式详情套壳打磨(Builder 构建详情 / Agent 配置器 / Code reskin)

每块各自 spec → plan → 实现。

## 9. 后续(明确延后)

- 自动探测跨产物依赖(扫代码/接口推断暴露-消费)。
- 写动作:新建产物(走多产物分解)、重新部署、继续构建、成员管理。
- 接入新壳与 rail 后,本视图作为 rail「项目」入口落点。
- 富化低代码应用摘要(实体/页面/业务流计数);如需严格还原设计稿低/全代码逐产物分组 → §3.1 方案 2(decompose 声明 per-artifact mode)。

## 附:评审修订记录(4 视角)

- **blocker**(可行性/设计):`sceneToMode(scene)` 字段不存在且误分 → 改 `projectTypeToMode(project_type)` 完整映射表(§3.1)。
- **blocker**(设计/范围):产物卡摘要无数据源 → `projectTypeToLabel` 零后端摘要(§3.2)。
- **major**(可行性/一致性):`parse_decomposition` 改返回会破坏契约 → 并列 `parse_dependencies`,原函数不动(§4.2)。
- **major**(可行性):`app:` 边 v1 永不产生 → 明确 v1 仅 workspace↔workspace,`app:` 保留前向兼容(§4.1/§4.5)。
- **minor**(可行性):`/chat?app_id` 非复用 → 改回复用现有 `goToAppBuilder` 的 `/chat?project_id`(§3.3)。
- **major**(设计):依赖图多边/长标签/卡片截断/状态无障碍/loading 骨架/深色对比/窄屏 → §5.4 全覆盖。
- **minor**(一致性):状态 label↔tone 映射 + 优先级 → §5.3 表。
- **minor**(范围):ProjectHeader/Hero 过早抽象 → 收回页内段(§5.1)。
- **nit**:多租户/鉴权 → §4.1/§4.4 写明;useProjectsVM 降级范式引用 → §5.5。
- 一致性 lens 另列「ProjectArtifactDependency/listDependencies 等未在代码中实现」数条 —— 那是本 spec 待建项,非缺陷,不计。
