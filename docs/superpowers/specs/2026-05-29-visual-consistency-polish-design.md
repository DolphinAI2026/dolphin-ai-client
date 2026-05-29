# 视觉一致性收口 — 设计 Spec

**日期**：2026-05-29
**分支**：`local/ui-redesign-2026-05-20`（⚠️ 共享分支 → 提交务必路径限定 `git commit -- <path>`）
**状态**：待用户评审
**所属**：UI 打磨独立刀（不属 PRD AI Coding 主线，也不改低代码业务线）
**前置**：上个 session 已落地嵌入式配置助手 / 隐藏 SPEC tab / 面包屑修复（HEAD `9fc668d`）。本刀只做视觉一致性。

---

## 一句话

设计系统（v3 token + `components/states/` 状态组件）**本来就存在且是好的**，但 `components/v3/` 的 designer 面板绕开它自己画（~72 处硬编码色、裸 px、手搓状态态、残留 v2 老青色 `#1D89A8` 兜底）。这一刀把这些面板**用回现成系统**，再统一二级 tab / 徽章 / chip 三类共享样式，并修首页过期 SPEC 文案。**纯视觉，零行为变更。**

---

## 范围铁律（最重要）

**纯表现层改动，零行为变更。** 即使改到低代码核心文件（`FormDesignerPanel.vue` 等），也只允许动：

- CSS 变量 / class / 内联 style 的**颜色、间距、圆角、阴影**值
- 把**手搓的状态 markup**（空/加载/错误的 `<div class="fbp-empty">…`）换成等价的 `<EmptyState>/<SkeletonCard>/<ErrorCard>`，但**喂给它的 `v-if` 条件、loading/error 变量、文案完全不变**
- 二级 tab / 徽章 / chip 的**呈现样式**统一

**禁止改动**：props、emit、`v-model`、API 调用、apaas 写逻辑、数据流、组件拆分/重命名、任何 `<script>` 里的业务逻辑。验收时每个文件 diff 必须能一眼看出是"纯呈现"。

---

## 决策（brainstorm 已定）

| 维度 | 决策 |
|---|---|
| 总方案 | **C：底子 + 可见层全做**，组织成 1 个 spec / 2 阶段（Phase 1 底子 → Phase 2 可见） |
| 二级 tab | **统一成下划线**（内容区二级导航；跟顶部主 tab 拉开层级）。现状：权限=胶囊、日志=下划线并存 |
| 首页 SPEC 文案 | **改写对齐现状**：`02 生成 SPEC` → `02 AI 生成应用`；`SPEC 版本` 指标 → 活数据（对话/迭代次数）。保 4 步节奏，以后恢复 SPEC 不冲突 |
| 流程设计器 SVG | **做**，但隔离成 Phase 2 **最后一个任务**，逐节点浅/暗色实测（39 处硬编码风险最高） |
| 暗色模式 | **纳入验收**（记忆载明 2026-05-22 暗色已跨 SPA 联动；硬编码 `#fff`/SVG 色在暗色下会破，是真 bug 不是洁癖） |
| token 迁移策略 | **别名先留为废弃 shim**，迁完所有引用最后再删（避免一刀切断引用） |

---

## 现状（已 grounded：6 界面像素审计 + 1 agent 代码扫）

**已存在、要复用（别推翻）**：

- `frontend/src/styles/design-v3-tokens.css` —— v3 单一真源：色（`--brand #1D4ED8`、`--ok/--warn/--err`、文字层级 `--text/--text-2..4`、`--line`、`--surface*`）、字号（`--t-display..--t-micro`）、间距（`--s-1..--s-20` = 4/8/12/16/20/24/32/40/48/64/80）、圆角（`--r-1..--r-full`）、阴影（`--sh-1..--sh-5`）。
- `frontend/src/components/states/`：`EmptyState.vue` / `ErrorCard.vue` / `SkeletonCard.vue`（均 token 合规）+ `BaseDialog.vue` / `BaseToast.vue`。
- `Apps.vue` 及多个 admin 页**已正确采用**上述。

**问题源（本刀目标）**：

- `frontend/src/components/v3/` 的 designer 面板绕开系统：硬编码 hex、裸 px、手搓状态、`#1D89A8` 老青色兜底。
- 遗留混乱：`theme-vars.css`（v2）与 v3 重叠；5 个文件残留死的 `data-design="v2"`（无 CSS selector 命中）；`builder.css` 的 `--b-teal` 等 stale。
- `Landing.vue` 过期 SPEC 文案。
- 跨界面样式分叉：二级 tab 两套、状态徽章多套、chip 三套。

---

## 架构

### A. token 单一真源

1. `theme-vars.css`（v2）的有效声明并入 `design-v3-tokens.css`；其余 v2 别名（`--border→--line`、`--ai→--brand`、`--amber/--emerald→--warn/--ok` 等）保留为**「废弃 shim」段**（注释标 DEPRECATED），Phase 1 末迁完引用后删除。
2. 清 `builder.css` 里确认无用的 stale token（如 `--b-teal`，需先 grep 确认 0 引用）。

### B. 共享原语（新增 4 个 + 复用现有 3 个状态组件）

新原语放 `frontend/src/components/base/`（**新目录；若仓库已有约定目录以仓库为准，写计划时确认**）：

- `Badge.vue` —— 语义状态徽章。props `{ variant: 'success'|'warn'|'error'|'info'|'neutral', size?: 'sm'|'md' }`，挂 `--ok/--warn/--err/--brand` 的 soft 变体 + `--r-full`。替代：日志成功/失败、阶段 部署/待部署、部署徽章 已发布/未提交。
- `Tag.vue` —— 中性标签（非状态）。props `{ tone?: 'neutral'|'brand' }`。替代：`低代码`、`PC页面`。
- `Chip.vue` —— 可点击建议/动作 chip。props `{ disabled?: boolean }` + click。替代：配置助手建议 chip、首页流程/快捷 chip、Coding `试问` chip 三套。
- `UnderlineSubTabs.vue` —— 下划线二级 tab。props `{ tabs: {key,label,disabled?}[], modelValue }` + `update:modelValue`。替代权限的胶囊二级 tab，并把日志现有下划线实现也收编到这一组件。

复用现有：`EmptyState` / `SkeletonCard` / `ErrorCard`。

---

## Phase 1 — 底子（任务，多数浅色界面看不见，但解锁一致性 + 修暗色破图）

> 实现锚点（写计划时逐一读真代码核对 file:line，本机工具间歇返损坏输出 → 改前先验）。

1. **token 合并**：`theme-vars.css` 有效内容并入 `design-v3-tokens.css`，v2 别名转 DEPRECATED shim 段。
   - ⚠️ **重复定义需仲裁**：两文件都定义了 `--brand-soft / --ok-soft / --warn-soft / --err-soft`（v3 用 hex/rgba，theme-vars 用 oklch）。先确认两者是否都被全局 import + 层叠顺序（谁后加载谁赢），**定 `design-v3-tokens.css` 为唯一赢家**，删 theme-vars 的重复项。`--text-inverse` 同样两边都有，统一到 v3。
2. **色归一**（按 agent 给的热点，逐文件）：
   - `--ai` / `#1D89A8` 老青兜底 → `--brand`：`FormDesignerPanel.vue:1250,1263,1271,1318,1325,1374,1402,1427,1469`
   - 硬编码 `#fff`（彩底白字）→ `--text-inverse`：`FormDesignerPanel.vue:1375,1428`、`ListDesignerPanel.vue:1021,1166`、`DataSchemaEditor.vue:1640,2363`、`RoleManagePanel.vue:1083`
     - ⚠️ **别无脑换**：`--text-inverse` 在暗色翻成深色（`#FFFFFF`→`#0B1224`）。**仅当白字配的背景是暗色感知 token（如 `--brand`，暗色下也变深）时才换**；若背景是固定浅彩色（暗色不变），白字要保留固定白（或用固定白 token）。逐处看背景 token 决定。
   - Tailwind 散色 / 其余 hex → 对应 `--surface*` / `--brand-soft` / `--warn-soft` 等
3. **间距归一**：裸 px → `--s-*`：`FormDesignerPanel.vue:813 (48px 16px)`、`ProcessDesignerPanel.vue:1380,1400,1411 (32px 24px / 8px 4px)` 等（DictEditor/DataSchema/ListDesigner 同扫）。
4. **删死代码**：5 个文件的 `data-design="v2"`（`WorkbenchShell.vue`、`ConfigAssistantPanel.vue`、`OnboardingTour.vue`、`ConfigAssistantSessionDrawer.vue` + 第 5 个，写计划时 grep 确认全集）；清 stale `--b-teal`（grep 确认 0 引用后删）。
5. **Phase 1 收尾**：grep 确认 v2 别名 0 引用后，删 DEPRECATED shim 段。

### ⚠️ 流程设计器 SVG（隔离任务，放 Phase 2 最后做）

`ProcessDesignerPanel.vue` 的 39 处 SVG 节点填充硬色（`#ffffff/#fffbeb/#faf5ff/#eff6ff/#f8fafc` 等，435/458/480/487/503/510 等）→ token 或主题感知逻辑。**单独成一个任务**，逐节点浅/暗色实测后再合。

---

## Phase 2 — 可见一致性（用户立刻看得到）

6. **状态组件落地**：把各 designer 面板手搓的空/加载/错误态换成 `<EmptyState>/<SkeletonCard>/<ErrorCard>`，喂同样的条件/文案：
   - `FormDesignerPanel.vue:25-42`（`fbp-empty` 未选菜单 / `fbp-state` 加载字段 / `fbp-spinner`）
   - `RoleManagePanel`（裸文字「加载权限矩阵...」→ `<SkeletonCard>`，实测确认现在的裸态）
   - `DataSchemaEditor` / `ListDesignerPanel` / `DictEditorPanel` 的手搓空/加载态同款替换
7. **二级 tab 统一**：新建 `UnderlineSubTabs.vue`；权限（角色/字段权限/菜单可见性）从胶囊换下划线；日志（部署历史/操作日志/AI行为/错误日志）收编到同组件。**只换呈现，tab 切换逻辑/状态不变。**
8. **徽章归一**：新建 `Badge.vue` + `Tag.vue`；替换 Apps 阶段、日志状态、构建器部署徽章、`低代码`/`PC页面` 标签。
9. **chip 归一**：新建 `Chip.vue`；统一配置助手建议 chip、首页流程/快捷 chip、Coding `试问` chip。
10. **两个 AI composer hero 视觉对齐**（**仅视觉**）：首页 hero composer 与 Coding hero composer 的输入框 chrome、标题字阶、chip 统一到上面的 token/`Chip`。**不合并组件、不动行为**。
11. **首页 SPEC 文案**：`Landing.vue:28`（`02 生成 SPEC`→`02 AI 生成应用`）、`:151`（`SPEC 版本` 指标 → 活数据，如对话/迭代次数；数据源写计划时确认）、`:91` 过期注释修正。
12. **SVG 任务**（见 Phase 1 末的隔离任务，实际排在最后执行）。

---

## 新原语规格（props / 落点）

| 组件 | props | 事件 | 替代对象 |
|---|---|---|---|
| `Badge.vue` | `variant: success\|warn\|error\|info\|neutral`、`size?: sm\|md` | — | 日志成功/失败、阶段 部署/待部署、部署徽章 |
| `Tag.vue` | `tone?: neutral\|brand` | — | `低代码`、`PC页面` |
| `Chip.vue` | `disabled?: boolean` | `click` | 配置助手 / 首页 / Coding 三套建议 chip |
| `UnderlineSubTabs.vue` | `tabs: {key,label,disabled?}[]`、`modelValue` | `update:modelValue` | 权限胶囊二级 tab + 日志下划线二级 tab |

落点目录 `components/base/` 待写计划时与仓库现有约定（`v2/`、`v3/`、`states/`）对齐确认。

---

## 验收标准

1. **逐界面 before/after 截图**（首页 / 应用列表 / 表单设计 / 权限 / 日志 / Coding 工作台），**浅色与暗色各一组**。
2. 暗色模式下：原硬编码白字 / SVG 节点不再破（对比 before）。
3. 二级 tab 全应用只剩**一种**（下划线）；徽章/chip 各只剩一套来源组件。
4. 首页不再出现 `生成 SPEC` / `SPEC 版本` 旧文案。
5. **vue-tsc 零新增错误**：基线 166 个预存（ChatPage 等），用 `git stash` 对比确认本刀 0 新增（同上个 session 做法）。
6. 每个改动文件的 diff 为纯呈现层（无 props/emit/API/逻辑变更）。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 改低代码核心文件触发"铁律" | 范围铁律 + diff 纯呈现层验收；逐文件小步 |
| 删 v2 别名/`--b-teal` 断引用 | 先 grep 确认 0 引用再删；别名走"shim→迁移→删"三步 |
| 共享 tab/徽章组件改动波及面广回归 | 先建新原语，逐处替换 + 逐处截图；不一次性全局替换 |
| SVG 39 处暗色逻辑复杂 | 隔离成最后单独任务，逐节点实测 |
| 本机工具间歇返损坏输出 | 精密改动前先验工具；关键 file:line 改前读真代码核对 |
| 暗色实际是否启用未亲验 | 写计划首步：preview `colorScheme:dark` 实测暗色当前状态，确认范围 |

---

## 铁律 / 非目标

- **不碰**：业务逻辑、数据流、apaas 写接口、低代码功能行为、组件拆分/重命名、SPEC/低代码核心线开关。
- **不做**：搭建台 IA 层级精简（4 层导航压缩）、死按钮做成真功能、配置助手对话路径增强 —— 均为 brainstorm 列出的**其它方向**，留各自单独刀。
- **不做**：两个 composer 的组件合并/行为统一（本刀只视觉对齐）。

---

## 待澄清（写计划时解决，非阻塞）

1. `SPEC 版本` 指标换成的"活数据"具体取哪个字段（对话数？迭代数？）—— 看 `Landing.vue` 现有数据源定。
2. `data-design="v2"` 第 5 个文件的确切路径（agent 列了 4 个 + 说 5 个）—— grep 定全集。
3. `components/base/` vs 复用现有目录 —— 对齐仓库约定。
