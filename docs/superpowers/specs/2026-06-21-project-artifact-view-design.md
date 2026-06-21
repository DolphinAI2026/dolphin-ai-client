# 设计:项目 → 产物视图(含跨产物依赖)

- 日期:2026-06-21
- 状态:设计已与用户(大明哥)分节确认,待 spec 复核 → writing-plans
- 分支:`feat/project-artifact-view`(从 dev/0.2.19 拉出,不动 origin)
- 所属:桌面 UI/IA 重设计的第 1 块(共 5 块,见文末「上下文」)

## 1. 背景与动机

用户提供了一份完整的桌面 UI 重设计原型(`AI Builder Desktop.html`,Claude Design 导出)。整份原型是多子系统大工程(三模式同壳 / 项目-产物视图 / 能力中心 / 各模式详情),已拆成 5 个独立 sub-project,本 spec 只覆盖**第 1 块:项目 → 产物视图**。

选它打头阵的理由:

- **自包含**:复用已有路由 `/project/:id`(当前 `ProjectOverview.vue`),不需要先动新壳/导航 rail。
- **价值最高**:它是已落地的「多产物分解」后端(`backend/app/coding/decompose.py` + `orchestrate.py`,`run_multi_artifact`)的展示层,也是竞品分析里点名的护城河(把混合交付收进一个项目 + 跨产物依赖,三家竞品都不做)。
- **先验证视觉**:在一个小而高价值的屏上先验证新视觉语言,认可后再把语言铺到全壳——刻意避开上一版「先整壳结果难看被否」的坑。

原型里这一屏的内容(参考截图):项目标题 + 描述 + meta(N产物·M成员·创建日);产物按模式分组的网格(低代码产物·Builder / 全代码产物·Code),每张卡有模式图标、模式标签、名称、摘要、状态点+标签+时间;底部「跨产物依赖」区(配置端暴露 `/api/ticket` → 用户端 consume ticketApi,并提示「改配置端字段会影响用户端」)。

## 2. 范围(v1)

确认的四个范围决策:

- **落地方式**:就地升级 `/project/:id`(`ProjectOverview.vue`),不碰新壳 / rail。
- **动作范围**:展示 + 导航。产物网格 + 分组 + 状态 + 依赖图展示;点产物跳现有页面;新增动作按钮(重新部署/继续构建/新建产物)置灰带 tooltip「下一阶段」。
- **跨产物依赖**:声明式——分解时由 LLM/元数据声明产物间关系,存库,前端渲染。**不**做自动扫码探测。
- **复用**:cherry-pick origin/dev 的非视觉地基(`projectVM.ts` 适配器 + 模式色 token),视觉那层重做;**不**搬 ProjectRail/ProjectSessionsPanel/ProjectView(属后续「同壳」sub-project)。

**明确不在 v1**:自动探测依赖;新增/部署/继续构建等写动作;新壳与 rail;手动在 UI 里声明依赖边;成员管理写操作。

## 3. 统一「产物」模型

一个项目的产物是混合的,来自三处,前端用复用的 `projectVM` 适配器拼成统一列表:

| 来源 | 产物 | 模式(色) | 数据 |
|---|---|---|---|
| `project.platform_app`(若 `platform_connected`) | aPaaS 低代码应用 | Builder/低代码(青 `--build`) | 名称、部署状态;实体/页面/业务流计数 = best-effort 富化,拿不到只显状态 |
| `listWorkspaces` 中 `project_type` 属低代码二开类 | 低代码二开工作区 | 低代码二开(靛 `--lowcode`) | `status`、`updated_at` |
| `listWorkspaces` 中全代码类 | 全代码工作区 | 全代码(紫 `--fullcode`) | `status`、`updated_at` |

- 模式映射复用 `projectVM.ts` 的 `sceneToMode()`(已存在于 origin/dev)。
- 分组按 mode 落到设计的两/三大组;未知 `project_type` → 落「其他」组兜底,绝不丢产物。
- 智能体(琥珀 `--agent`)模式色保留在 token 里,但 v1 项目下一般无智能体产物,出现则归对应组。

**点产物去向**:
- 低代码应用 → `/chat?app_id=…`(配置详情)。
- 工作区(低代码二开 / 全代码)→ `/coding`(复用现有 `openWorkspace`/dispatch 跳转)。

## 4. 后端设计(声明式依赖:存 + 吐)

仓库无 alembic,用 `Base.metadata.create_all`(`app/database.py:63`)。新表由 create_all 自动建表(零迁移);给已有表加列则要手写 ALTER——故选**新表**而非在 Project 上加 JSON 列。

### 4.1 新表 `ProjectArtifactDependency`

位于 `app/models/__init__.py`,仿 `ProjectMember`(:207)款式。字段:

- `id` PK
- `project_id` FK → `projects.id`,`ondelete=CASCADE`,index
- `from_ref` str:产物引用,`workspace:<id>` 或 `app:<platform_app_id>`
- `to_ref` str:同上
- `expose_label` str:如「暴露 /api/ticket」
- `consume_label` str:如「consume ticketApi」
- `note` str:如「改配置端字段会影响用户端」
- `created_at` datetime

### 4.2 分解器声明边(`decompose.py`)

- `_DECOMPOSE_PROMPT` 增补:让 LLM 在 `artifacts` 之外**可选**输出
  `dependencies: [{from, to, expose, consume, note}]`,`from`/`to` 用 artifact 的 index 引用(例:admin 暴露工单接口、user 消费)。
- `parse_decomposition` 扩展为返回 `{artifacts, dependencies}`(或并列解析函数),`dependencies` 非法/缺失 → 空数组。延续现有「非法即回落、永不更糟」风格;index 越界、自引用、引用不存在的 artifact 一律丢弃该边。

### 4.3 编排时落库(`orchestrate.py`)

- `run_multi_artifact` 跑完已持有 `results`(每个 artifact 的 `index → workspace_id`)。
- 新增一步:把声明的边按 index 解析成 `from_ref=workspace:<ws_id>` / `to_ref=workspace:<ws_id>`,写入 `ProjectArtifactDependency`。
- 失败非致命(延续现有 best-effort:落库异常只 log,不影响产物生成与汇总事件)。

### 4.4 读接口

- `GET /projects/:id/dependencies` → 返回该项目边列表 `[{from_ref, to_ref, expose_label, consume_label, note}]`,租户/权限作用域同其他 project 子接口。
- 前端 `projectsApi` 加 `listDependencies(id)`。

### 4.5 v1 诚实边界

依赖**只对本次改动之后新生成的多产物项目**有数据(需 decompose 声明)。老项目 / 单应用项目 → 无边 → 前端依赖区隐藏(优雅降级)。此边界写入 spec 与验收说明,避免被当成 bug。

## 5. 前端设计(`ProjectOverview.vue` 重做)

把当前 757 行单文件拆成各司其职的小件(顺手理清):

```
ProjectOverview.vue            页面容器(薄,只编排)
├─ ProjectHeader.vue           面包屑 + 成员N + ⋯ 溢出菜单
├─ ProjectHero.vue             图标 + 标题 + 描述 + meta(N产物·M成员·创建日)
├─ ArtifactGroup.vue × N       每个模式组一个(低代码产物·Builder / 全代码产物·Code …)
│   └─ ArtifactCard.vue × M     单产物卡:模式图标 + 模式标签 + 名称 + 摘要 + 状态点·标签·时间
└─ ArtifactDependencyGraph.vue 跨产物依赖区(无边则整块隐藏)
    └─ from-chip → 箭头(标签) → to-chip + note 行
```

每个单元的职责边界清晰、可独立理解/测试:`ArtifactCard` 只画一张卡;`ArtifactGroup` 只画一个模式组;`ArtifactDependencyGraph` 只画边;`ProjectHero/Header` 只画 chrome;数据全在 composable。

### 5.1 数据流 — `useProjectArtifacts(projectId)`

- 并行拉 `projectsApi.get` + `listWorkspaces` + `listMembers` + `listDependencies`。
- 经 `projectVM` 适配器把 `[platform_app]` + `[workspaces]` 拼成统一产物列表,按 `sceneToMode()` 分组。
- 把依赖边按 `from_ref`/`to_ref` 解析挂到产物(用于 chip 渲染);悬空 ref 跳过。
- 返回 `{ project, groups, dependencies, members, loading, error }`。页面只渲染,不算逻辑。
- 四个请求各自独立降级(成员挂了显 0、工作区挂了只显应用……),沿用 `useProjectsVM` 的失败降级风格。

### 5.2 状态归一(纯函数 `normalizeArtifactStatus`)

原始 `workspace.status` / app 部署态 → 设计词表 `{ label, tone }`:

- 构建中 / 已完成 / AI 在写 / 已部署 / 草稿(尚未部署)。
- `tone` 决定状态点颜色(live/building/done/draft/error)。
- 未知状态 → 中性 tone + 原文标签,不崩。

### 5.3 复用 origin/dev 地基(cherry-pick,不重写)

- `frontend/src/composables/projectVM.ts`(ProjectVM 类型 + `sceneToMode` + 适配器)。可能按本设计需求轻量扩展(产物摘要 + 状态字段)。
- `frontend/src/styles/design-v3-tokens.css` 的模式色新增(`--build/--lowcode/--fullcode/--agent` + `-bg`,含 light/dark)。
- **不**搬 `ProjectRail.vue` / `ProjectSessionsPanel.vue` / `ProjectView.vue`(那是后续「同壳」sub-project;搬来 = 范围蔓延 + 带上已被否的视觉)。

## 6. 错误处理 / 边界

- 项目不存在 / 无权限 → 错误态(复用现有)。
- 未连平台 → 无低代码应用产物,只渲工作区;两者皆空 → 空态「还没有产物」(纯提示)。
- `listDependencies` 失败或空 → 依赖区整块隐藏,不影响其余。
- 依赖边引用的 ref 在产物列表里找不到(工作区已删)→ 静默跳过 + 日志。
- 四个请求各自独立降级,全程不白屏。
- 未知 `project_type` → 「其他」组兜底;未知状态 → 中性 tone + 原文标签。

## 7. 测试策略

仓库 vitest 是 `environment:'node'` 无 DOM:组件测试只能 `?raw` 源码字符串检查,**不能** `@vue/test-utils` mount(durable 踩坑)。

- **纯函数真单测**(高价值靶子):
  - 前端 `normalizeArtifactStatus()`(全词表 + 未知兜底)、`buildArtifacts()`(应用+工作区→分组排序)、`resolveDependencies()`(边+产物→解析,悬空 ref 跳过)。
  - 后端 `parse_decomposition` 扩展(解析 dependencies、非法忽略、index 越界/自引用丢弃)、orchestrate 边解析(假 results 数组 → 正确 ref)。
- **后端接口测**:`GET /projects/:id/dependencies` 返回正确、租户/权限作用域、空时空数组。
- **组件**:`?raw` 源码检查关键绑定/类(轻量,非行为)。
- **端到端真验(验收门)**:本地 tenant1 gpt-5.5 omnigate 真跑一次多产物分解,确认依赖边显示 + 产物卡片能跳。改后端必重启进程(`run.py` reload=False)。

## 8. 上下文:5 块拆分(本 spec = 第 1 块)

1. 三模式同壳 + 项目主导左栏(容器:Builder/Agent/Code 切换 + rail 替换 + 模式色铺底)
2. **项目 → 产物视图 + 跨产物依赖** ← 本 spec
3. 三模式首页 + composer + 自动路由
4. 得小帆能力中心(技能/MCP/AI 网关/知识库,三档共用)
5. 各模式详情套壳打磨(Builder 构建详情 / Agent 配置器 / Code reskin)

每块各自 spec → plan → 实现。第 2 块刻意先行以验证视觉语言。

## 9. 后续(明确延后)

- 自动探测跨产物依赖(扫代码/接口推断暴露-消费)。
- 写动作:新建产物(走多产物分解)、重新部署、继续构建、成员管理。
- 接入新壳与 rail 后,本视图作为 rail「项目」入口的落点。
- 富化低代码应用摘要(实体/页面/业务流计数)。
