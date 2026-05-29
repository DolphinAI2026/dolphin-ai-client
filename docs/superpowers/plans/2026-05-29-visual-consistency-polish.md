# 视觉一致性收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans（本刀视觉+preview 验证，inline 执行最合适）或 superpowers:subagent-driven-development。Steps 用 checkbox（`- [ ]`）跟踪。

**Goal:** 让 `components/v3/` 的 designer 面板用回已有的 v3 token + 状态组件，并把二级 tab / 徽章 / chip 三类共享样式归一、修首页过期 SPEC 文案 —— 纯视觉，零行为变更。

**Architecture:** 设计系统（`design-v3-tokens.css` + `components/states/`）已存在且良好；本刀是"采用"不是"新建系统"。新增 4 个顶层 `Base*` 原语（对齐已有 BaseDialog/BaseToast 约定），逐处替换分叉样式；designer 面板硬编码色/间距迁到 token；删 v2 死代码。

**Tech Stack:** Vue 3 `<script setup lang="ts">` SFC、scoped CSS、v3 CSS 变量、Element Plus（保留）、preview MCP 截图验证、vue-tsc 类型基线对比。

**Spec:** [docs/superpowers/specs/2026-05-29-visual-consistency-polish-design.md](../specs/2026-05-29-visual-consistency-polish-design.md)（commit `8249281`）

---

## 铁律（每个 Task 都适用）

1. **纯表现层，零行为变更**：只动颜色/间距/圆角/阴影值 + 把手搓状态 markup 换成等价状态组件（喂同样 `v-if`/loading/error/文案）+ tab/徽章/chip 呈现样式。**禁止**改 props/emit/v-model/API/数据流/业务逻辑/组件拆分重命名。
2. **先读真代码再改**：本机工具间歇返损坏输出 + line 会漂。下文 file:line 是**起点提示不是圣旨**，每次改前先 Read 实际区域核对，grep 枚举真实命中。
3. **共享分支提交**：每个 commit **路径限定** `git commit -m "..." -- <path1> <path2>`，绝不裸 `git add -A`。
4. **token 全程 `var(--xxx)`**：不写新 hex、不写 theme 分支（v3 token 自带浅/暗）。

---

## 已解（brainstorm/计划阶段定）

| 待澄清 | 结论 |
|---|---|
| 新原语落点 | 顶层 `components/Base*.vue`（对齐已有 `BaseDialog.vue`/`BaseToast.vue`；`common/` 是功能目录不用） |
| `data-design="v2"` 全集 | **4 个真属性**：`components/WorkbenchShell.vue`、`components/v2/OnboardingTour.vue`、`components/v2/ConfigAssistantPanel.vue`、`components/v2/config-assistant/ConfigAssistantSessionDrawer.vue`（`design-v3-tokens.css` 里的是注释文档，不算） |
| 首页 SPEC 指标 | 底层 `specs: conversations.length`（`Landing.vue:100`）。指标标签「SPEC 版本」→「对话次数」（值不变）；流程「02 生成 SPEC」→「02 AI 生成应用」 |

---

## token 速查（已 grep 实证存在于 design-v3-tokens.css）

**间距**（编号 = px/4）：`--s-1`4 `--s-2`8 `--s-3`12 `--s-4`16 `--s-5`20 `--s-6`24 `--s-8`32 `--s-10`40 `--s-12`48 `--s-16`64 `--s-20`80
**圆角**：`--r-1`4 `--r-2`6 `--r-3`8 `--r-4`12 `--r-5`16 `--r-full`999
**色**：`--brand --brand-hover --brand-soft --brand-ring`、`--ok/--ok-soft --warn/--warn-soft --err/--err-soft`、`--text --text-2 --text-3 --text-4 --text-inverse`、`--surface --surface-2 --surface-3`、`--line --line-strong --line-focus`、`--fw-medium --fw-semibold --ease`

**迁移映射**：
- `var(--ai)` / `var(--ai, #1D89A8)` / 裸 `#1D89A8` → `var(--brand)`
- 文本色 `#fff`/`#ffffff` → `var(--text-inverse)` **仅当背景是暗色感知 token**（`--brand`/`--surface*` 等，暗色下也变）；背景是固定浅彩色则保留固定白
- 背景 `#fff`/`#ffffff` → `var(--surface)`
- 裸 px（padding/margin/gap）→ 最近的 `--s-*`（非网格值如 14px 可留）

---

## Verification Protocol（每个 Task 引用，不重复抄）

**P-视觉**：preview 截图 before/after，**浅色 + 暗色各一**。
- 取 frontend serverId：`preview_list`（本 session 是 `430acc99-c9a7-46fa-bb49-a0b63d7f9f90`，跨 session 会变，务必现取）
- 各面 URL：首页 `/ai-builder/` · 应用列表 `/ai-builder/apps` · 表单设计 `/ai-builder/chat?app_id=22`（默认功能/表单）· Coding `/ai-builder/coding`
- 权限/日志子页：先到 `chat?app_id=22`，再 `preview_eval`：`[...document.querySelectorAll('[role=tab]')].find(e=>e.textContent.trim()==='权限').click()`（或 '日志'）
- 暗色：`preview_resize` `colorScheme:'dark'`（先在 Task 0 确认暗色开关真生效）

**P-类型**：`cd frontend && npx vue-tsc --noEmit 2>&1 | grep -c "error TS"` —— 必须 **≤ Task 0 记录的基线**（零新增）。

**P-diff**：`git diff -- <file>` 通读，确认纯呈现层（无 props/emit/API/逻辑变更）。

---

## File Structure

**新建（4 个顶层原语）**
- `frontend/src/components/BaseBadge.vue` — 语义状态徽章
- `frontend/src/components/BaseTag.vue` — 中性标签
- `frontend/src/components/BaseChip.vue` — 可点击建议/动作 chip
- `frontend/src/components/BaseSubTabs.vue` — 下划线二级 tab

**修改（呈现层）**
- `frontend/src/styles/design-v3-tokens.css`、`theme-vars.css`、`builder.css` — token 合并/去重
- `frontend/src/components/v3/`：`FormDesignerPanel.vue` `ListDesignerPanel.vue` `DataSchemaEditor.vue` `RoleManagePanel.vue` `DictEditorPanel.vue` `ProcessDesignerPanel.vue`（SVG 最后）`LogsPanel.vue`
- `frontend/src/views/Landing.vue`（文案）`Apps.vue`（徽章/标签）`CodingPage.vue`（chip）`ChatPage.vue`（权限二级 tab / 部署徽章）
- `frontend/src/components/v2/ConfigAssistantPanel.vue`、`LandingComposer.vue`（chip/composer）
- `data-design="v2"` 4 文件（删死属性）

---

## Task 0：基线 + 暗色确认（preflight）

**Files:** 无改动（只测量）

- [ ] **Step 1** `preview_list` 取 frontend serverId。
- [ ] **Step 2** 记录类型基线：`cd "frontend" && npx vue-tsc --noEmit 2>&1 | grep -c "error TS"` → 记下数字 N（预期 ~166 区域）。**这是后续"零新增"的基准。**
- [ ] **Step 3** 确认暗色生效：到 `/ai-builder/apps`，`preview_resize colorScheme:'dark'`，截图确认页面真变暗（不变则改用应用内 ThemeToggle：`components/ThemeToggle.vue`，先 `preview_eval` 找触发；确认暗色机制后再继续，否则暗色验收降级为"手动 ThemeToggle 后截图"）。
- [ ] **Step 4** 截 6 个面浅色 before 基线图（首页/应用列表/表单设计/权限/日志/Coding），留作全程对照。
- [ ] **Step 5** 无提交（仅测量）。

---

## Task 1：BaseBadge + BaseTag（greenfield，零风险）

**Files:** Create `frontend/src/components/BaseBadge.vue`、`frontend/src/components/BaseTag.vue`

- [ ] **Step 1** 写 `BaseBadge.vue`：

```vue
<!-- frontend/src/components/BaseBadge.vue
     语义状态徽章。替代散落的 成功/失败、部署/待部署、已发布 等胶囊。
     用法：<BaseBadge variant="success">成功</BaseBadge> / <BaseBadge variant="warn" size="sm">待部署</BaseBadge>
     token 全程 var() — 浅/暗自适配。 -->
<template>
  <span class="base-badge" :class="[`is-${variant}`, `sz-${size}`]"><slot /></span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  variant?: 'success' | 'warn' | 'error' | 'info' | 'neutral'
  size?: 'sm' | 'md'
}>(), { variant: 'neutral', size: 'md' })
</script>

<style scoped>
.base-badge {
  display: inline-flex; align-items: center; gap: var(--s-1, 4px);
  font-weight: var(--fw-medium, 500); line-height: 1.4;
  border-radius: var(--r-full, 999px); white-space: nowrap;
  border: 1px solid transparent;
}
.sz-md { font-size: 12px; padding: 2px var(--s-3, 12px); }
.sz-sm { font-size: 11px; padding: 1px var(--s-2, 8px); }
.is-success { background: var(--ok-soft);    color: var(--ok); }
.is-warn    { background: var(--warn-soft);  color: var(--warn); }
.is-error   { background: var(--err-soft);   color: var(--err); }
.is-info    { background: var(--brand-soft); color: var(--brand); }
.is-neutral { background: var(--surface-3);  color: var(--text-3); }
</style>
```

- [ ] **Step 2** 写 `BaseTag.vue`：

```vue
<!-- frontend/src/components/BaseTag.vue
     中性标签（非状态）。替代 低代码 / PC页面 等。
     用法：<BaseTag>低代码</BaseTag> / <BaseTag tone="brand">PC页面</BaseTag> -->
<template>
  <span class="base-tag" :class="`tone-${tone}`"><slot /></span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ tone?: 'neutral' | 'brand' }>(), { tone: 'neutral' })
</script>

<style scoped>
.base-tag {
  display: inline-flex; align-items: center;
  font-size: 11px; font-weight: var(--fw-medium, 500); line-height: 1.5;
  padding: 1px 7px; border-radius: var(--r-1, 4px); white-space: nowrap;
}
.tone-neutral { background: var(--surface-3);  color: var(--text-3); }
.tone-brand   { background: var(--brand-soft);  color: var(--brand); }
</style>
```

- [ ] **Step 3** P-类型（零新增）。
- [ ] **Step 4** Commit：`git commit -m "feat(ui): 加 BaseBadge/BaseTag 语义徽章原语" -- frontend/src/components/BaseBadge.vue frontend/src/components/BaseTag.vue`

---

## Task 2：BaseChip（greenfield，零风险）

**Files:** Create `frontend/src/components/BaseChip.vue`

- [ ] **Step 1** 写 `BaseChip.vue`：

```vue
<!-- frontend/src/components/BaseChip.vue
     可点击建议/动作 chip。统一 配置助手 / 首页 / Coding 三处建议 chip。
     用法：<BaseChip @click="send('...')">开发一个头像上传组件</BaseChip> -->
<template>
  <button type="button" class="base-chip" :disabled="disabled" @click="$emit('click', $event)">
    <slot />
  </button>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false })
defineEmits<{ click: [e: MouseEvent] }>()
</script>

<style scoped>
.base-chip {
  display: inline-flex; align-items: center; gap: var(--s-2, 8px); max-width: 100%;
  padding: var(--s-2, 8px) var(--s-3, 12px);
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-full, 999px);
  color: var(--text-2); font-size: 12.5px; font-weight: var(--fw-medium, 500);
  font-family: inherit; cursor: pointer; text-align: left;
  transition: background .14s var(--ease, cubic-bezier(.2,.8,.2,1)),
              border-color .14s var(--ease, cubic-bezier(.2,.8,.2,1)),
              color .14s var(--ease, cubic-bezier(.2,.8,.2,1));
}
.base-chip:hover:not(:disabled) {
  background: var(--brand-soft); border-color: var(--brand-ring, var(--brand)); color: var(--brand);
}
.base-chip:disabled { opacity: .5; cursor: not-allowed; }
.base-chip:focus-visible { outline: 2px solid var(--line-focus, var(--brand-ring)); outline-offset: 2px; }
</style>
```

- [ ] **Step 2** P-类型（零新增）。
- [ ] **Step 3** Commit：`git commit -m "feat(ui): 加 BaseChip 建议 chip 原语" -- frontend/src/components/BaseChip.vue`

---

## Task 3：BaseSubTabs（greenfield，零风险）

**Files:** Create `frontend/src/components/BaseSubTabs.vue`

- [ ] **Step 1** 写 `BaseSubTabs.vue`：

```vue
<!-- frontend/src/components/BaseSubTabs.vue
     下划线二级 tab。统一权限（胶囊→下划线）与日志的二级导航。
     用法：<BaseSubTabs :tabs="[{key:'role',label:'角色'},...]" v-model="active" /> -->
<template>
  <div class="base-subtabs" role="tablist">
    <button
      v-for="t in tabs" :key="t.key"
      type="button" role="tab"
      class="bst-tab" :class="{ 'is-active': t.key === modelValue }"
      :disabled="t.disabled" :aria-selected="t.key === modelValue"
      @click="t.disabled || $emit('update:modelValue', t.key)"
    >{{ t.label }}</button>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  tabs: { key: string; label: string; disabled?: boolean }[]
  modelValue: string
}>()
defineEmits<{ 'update:modelValue': [key: string] }>()
</script>

<style scoped>
.base-subtabs { display: flex; align-items: center; gap: var(--s-1, 4px); border-bottom: 1px solid var(--line); }
.bst-tab {
  position: relative; padding: var(--s-2, 8px) var(--s-3, 12px);
  background: transparent; border: none; border-bottom: 2px solid transparent; margin-bottom: -1px;
  color: var(--text-3); font-size: 13px; font-weight: var(--fw-medium, 500); line-height: 1.4;
  font-family: inherit; cursor: pointer;
  transition: color .14s var(--ease, cubic-bezier(.2,.8,.2,1));
}
.bst-tab:hover:not(:disabled) { color: var(--text); }
.bst-tab.is-active { color: var(--brand); border-bottom-color: var(--brand); font-weight: var(--fw-semibold, 600); }
.bst-tab:disabled { opacity: .45; cursor: not-allowed; }
.bst-tab:focus-visible { outline: 2px solid var(--line-focus, var(--brand-ring)); outline-offset: -2px; border-radius: var(--r-1, 4px); }
</style>
```

- [ ] **Step 2** P-类型（零新增）。
- [ ] **Step 3** Commit：`git commit -m "feat(ui): 加 BaseSubTabs 下划线二级 tab 原语" -- frontend/src/components/BaseSubTabs.vue`

---

## Task 4：首页 SPEC 文案对齐（`Landing.vue`，低风险）

**Files:** Modify `frontend/src/views/Landing.vue`（~29 流程标签、~152 指标标签、~91 注释）

- [ ] **Step 1** P-视觉 before：截首页浅色。
- [ ] **Step 2** Read `Landing.vue` 实际区域核对行号。改三处：
  - 流程：`{ n: '02', label: '生成 SPEC', tone: 'brand' }` → `label: 'AI 生成应用'`
  - 指标标签：`<div class="stat-lbl">SPEC 版本</div>` → `对话次数`
  - 注释 `// - specs: total conversation count ...` → 改为 `// - 对话次数: total builder conversation count`（保持代码注释与 UI 一致）
  - **不动** `stats.value.specs = conversations.length` 的取值逻辑（仅改标签）。
- [ ] **Step 3** P-类型（零新增）。
- [ ] **Step 4** P-视觉 after：截首页，确认显示「02 AI 生成应用」「对话次数」；P-diff 纯文案。
- [ ] **Step 5** Commit：`git commit -m "fix(ui): 首页文案对齐现状 — SPEC→AI生成应用/对话次数（SPEC tab 已隐藏）" -- frontend/src/views/Landing.vue`

---

## Task 5：徽章/标签落地（`Apps.vue` + `ChatPage.vue` + `LogsPanel.vue`，低-中风险）

**Files:** Modify `frontend/src/views/Apps.vue`、`frontend/src/components/v3/LogsPanel.vue`、`frontend/src/views/ChatPage.vue`

- [ ] **Step 1** P-视觉 before：应用列表 + 日志 + 构建器顶栏（部署徽章）。
- [ ] **Step 2** grep 定位各处胶囊：`grep -n "阶段\|部署\|待部署\|低代码" views/Apps.vue`；`grep -n "成功\|失败\|status" components/v3/LogsPanel.vue`；`grep -n "已发布\|未提交\|徽章\|badge" views/ChatPage.vue`。
- [ ] **Step 3** 替换（先 import）：`import BaseBadge from '@/components/BaseBadge.vue'`、`import BaseTag from '@/components/BaseTag.vue'`（路径别名以仓库实际为准，grep 现有 import 确认 `@/` 还是相对路径）。
  - Apps 阶段：部署→`<BaseBadge variant="success">`，待部署→`variant="warn"`；`低代码` 标签→`<BaseTag>低代码</BaseTag>`
  - 日志状态：成功→`variant="success"`，失败→`variant="error"`
  - 构建器部署徽章：已发布→`variant="success"`；"有 N 个未提交"→`variant="warn" size="sm"`
  - **只换呈现**：原有 `v-if`/计算值/文案不变，删掉被替代的旧 class CSS。
- [ ] **Step 4** P-类型（零新增）。
- [ ] **Step 5** P-视觉 after（三处，浅+暗）+ P-diff 纯呈现。
- [ ] **Step 6** Commit：`git commit -m "refactor(ui): 状态徽章/标签归一到 BaseBadge/BaseTag" -- frontend/src/views/Apps.vue frontend/src/components/v3/LogsPanel.vue frontend/src/views/ChatPage.vue`

---

## Task 6：chip 归一（`ConfigAssistantPanel.vue` + `Landing.vue`/`LandingComposer.vue` + `CodingPage.vue`，中风险）

**Files:** Modify 上述四文件

- [ ] **Step 1** P-视觉 before：配置助手空态 chip / 首页流程+快捷 chip / Coding 试问 chip。
- [ ] **Step 2** grep 各处 chip 渲染：`grep -n "chip\|快捷\|建议\|试问\|suggest\|example" components/v2/ConfigAssistantPanel.vue views/CodingPage.vue components/v2/LandingComposer.vue views/Landing.vue`。
- [ ] **Step 3** 各处把"自定义 chip 按钮"换成 `<BaseChip @click="原回调">原文案</BaseChip>`，**回调/数据源不变**；删旧 chip class CSS。
  - ⚠️ 首页"流程条"（01→02→03→04）若是**展示性非可点**，保留原样**不**换 BaseChip（BaseChip 是可点击语义）；只换真正可点击的建议/快捷 chip。
- [ ] **Step 4** P-类型（零新增）。
- [ ] **Step 5** P-视觉 after（三处，浅+暗）+ P-diff 纯呈现。
- [ ] **Step 6** Commit：`git commit -m "refactor(ui): 建议 chip 归一到 BaseChip（配置助手/首页/Coding）" -- <四文件>`

---

## Task 7：二级 tab 归一（权限胶囊→下划线 + 日志收编，中风险）

**Files:** Modify 权限二级 tab 宿主（先 grep 定位：`grep -rn "字段权限\|菜单可见性" components/ views/ChatPage.vue`）、`frontend/src/components/v3/LogsPanel.vue`

- [ ] **Step 1** P-视觉 before：权限（胶囊）+ 日志（下划线）。
- [ ] **Step 2** 定位权限二级 tab 实际渲染处（角色/字段权限/菜单可见性）与其当前 active state 变量。
- [ ] **Step 3** 引入 `import BaseSubTabs from '@/components/BaseSubTabs.vue'`，把权限的胶囊组替换成：`<BaseSubTabs :tabs="[{key:'role',label:'角色'},{key:'field',label:'字段权限'},{key:'menu',label:'菜单可见性'}]" v-model="原active变量" />`（key 用原代码已有的 value，**别新造**；切换逻辑/watch 不变）。日志的二级 tab 同样收编到 `BaseSubTabs`。
- [ ] **Step 4** P-类型（零新增）。
- [ ] **Step 5** P-视觉 after：权限/日志二级 tab 现在**同一种下划线**（浅+暗）+ P-diff 纯呈现。
- [ ] **Step 6** Commit：`git commit -m "refactor(ui): 二级 tab 统一为下划线 BaseSubTabs（权限+日志）" -- <文件>`

---

## Task 8：状态组件落地（designer 面板，中风险）

**Files:** Modify `FormDesignerPanel.vue`、`RoleManagePanel.vue`、`DataSchemaEditor.vue`、`ListDesignerPanel.vue`、`DictEditorPanel.vue`（逐个，可拆成多个 commit）

状态组件 API（已读真代码）：
- `<EmptyState title desc? variant?="first|filtered">` + `#icon`/`#cta` slot
- `<SkeletonCard :lines? :withAvatar? :withFooter? :delay?=200 @cancel>`
- `<ErrorCard level="err|warn|info" title code? message :actions?>`（action=`{label,primary?,danger?,onClick}`）

- [ ] **Step 1** P-视觉 before：每个面板的空/加载/错误态（如权限「加载权限矩阵...」、表单未选菜单空态）。
- [ ] **Step 2** 逐面板 Read 手搓状态区（如 `FormDesignerPanel.vue:25-42` 的 `fbp-empty`/`fbp-state`/`fbp-spinner`），替换为状态组件，**条件/文案照搬**：
  - 例 表单未选菜单：`<EmptyState title="选择一个表单" desc="从左侧菜单列表点击某个表单…">` + `#icon` 放原 📝
  - 例 加载：原 `loading` 分支 → `<SkeletonCard v-if="loading" :lines="6" />`
  - 例 权限矩阵加载：`<SkeletonCard v-if="loading" :lines="5" />` 替代裸「加载权限矩阵...」
- [ ] **Step 3** 删被替换的旧 `fbp-empty`/`fbp-state`/`dse-empty` 等 class CSS。
- [ ] **Step 4** P-类型（零新增）。
- [ ] **Step 5** P-视觉 after（逐面板，浅+暗）+ P-diff：确认仅状态 markup 替换、`v-if` 条件未变。
- [ ] **Step 6** Commit（逐面板路径限定）：`git commit -m "refactor(ui): <面板> 空/加载/错误态用回 states 组件" -- <文件>`

---

## Task 9：token 迁移 — FormDesigner / List / DataSchema / Role / Dict（5 面板，逐个 commit，中风险）

**Files:** Modify `components/v3/FormDesignerPanel.vue`、`ListDesignerPanel.vue`、`DataSchemaEditor.vue`、`RoleManagePanel.vue`、`DictEditorPanel.vue`（**不含 ProcessDesigner，见 Task 11**）

热点（agent 给的起点，先 Read 核对）：
- `FormDesignerPanel.vue`：`--ai/#1D89A8` @1250,1263,1271,1318,1325,1374,1402,1427,1469；`#fff` @1375,1428；`padding:48px 16px` @813
- `ListDesignerPanel.vue`：`#fff` @1021,1166（+ 9 处 hex 全扫）
- `DataSchemaEditor.vue`：`#fff`/`#fff背景` @1640,2363
- `RoleManagePanel.vue`：`#fff` @1083
- `DictEditorPanel.vue`：1 处 hex

- [ ] **Step 1**（逐面板）grep 枚举：`grep -nE "#[0-9a-fA-F]{3,6}|var\(--ai|[0-9]+px" components/v3/<面板>.vue`
- [ ] **Step 2** 按"迁移映射"逐处替换；`#fff` 文本色**逐处看背景 token** 决定 `--text-inverse` vs 保留固定白。
- [ ] **Step 3** P-类型（零新增）。
- [ ] **Step 4** P-视觉 after（该面板浅+暗，重点看暗色不再破）+ P-diff 纯呈现。
- [ ] **Step 5** Commit（逐面板）：`git commit -m "refactor(ui): <面板> 硬编码色/间距迁到 v3 token" -- components/v3/<面板>.vue`

---

## Task 10：删 v2 死代码 + token 去重（低-中风险）

**Files:** Modify `WorkbenchShell.vue`、`v2/OnboardingTour.vue`、`v2/ConfigAssistantPanel.vue`、`v2/config-assistant/ConfigAssistantSessionDrawer.vue`、`styles/theme-vars.css`、`styles/design-v3-tokens.css`、`styles/builder.css`

- [ ] **Step 1** 删 4 文件的 `data-design="v2"` 属性（grep 确认无 CSS selector 依赖：`grep -rn '\[data-design' styles/ components/`）。
- [ ] **Step 2** token 去重：确认 `theme-vars.css` 与 `design-v3-tokens.css` 都被全局 import 的顺序（`grep -rn "theme-vars\|design-v3-tokens" main.ts src/**/*.ts styles/`），**定 v3 为赢家**，删 theme-vars 里与 v3 重复的 `--brand-soft/--ok-soft/--warn-soft/--err-soft/--text-inverse` 等（先逐个 grep 全仓引用确认不破）。
- [ ] **Step 3** `--b-teal`：`grep -rn "b-teal" .` 若 0 引用则从 `builder.css` 删。
- [ ] **Step 4** P-类型（零新增）+ P-视觉 全 6 面快速回归（浅+暗，确认去重没改观感）。
- [ ] **Step 5** Commit：`git commit -m "chore(ui): 删死的 data-design=v2 + token 去重收口到 v3" -- <文件>`

---

## Task 11：ProcessDesigner SVG（隔离，最后做，最高风险）

**Files:** Modify `frontend/src/components/v3/ProcessDesignerPanel.vue`

热点：39 处 SVG 节点填充硬色 @435,458,480,487,503,510 等（`#ffffff/#fffbeb/#faf5ff/#eff6ff/#f8fafc/#92400e` 等）+ `padding:32px 24px` @1380 等。

- [ ] **Step 1** P-视觉 before：流程设计 tab，浅 + **暗**（重点记录暗色当前破的样子）。
- [ ] **Step 2** grep 全枚举：`grep -nE "#[0-9a-fA-F]{3,6}" components/v3/ProcessDesignerPanel.vue`
- [ ] **Step 3** 逐节点映射：白底 `#ffffff`→`var(--surface)`；浅彩底（`#fffbeb`黄/`#eff6ff`蓝/`#faf5ff`紫/`#f8fafc`灰）→对应 `--warn-soft/--brand-soft/--surface-2`；深字色（`#92400e` 等）→`--warn`/`--text` 等。⚠️ SVG 内联 `fill` 若由 JS 生成（非 CSS），需改成读 `getComputedStyle` 或映射常量到 token —— **先 Read 确认是 CSS 还是 JS 注入**，JS 注入的逐个换成 token 字符串或 CSS class。
- [ ] **Step 4** P-类型（零新增）。
- [ ] **Step 5** P-视觉 after：流程图浅 + 暗逐节点确认不再破 + P-diff 纯呈现。
- [ ] **Step 6** Commit：`git commit -m "refactor(ui): ProcessDesigner SVG 节点色迁到 token（暗色实测）" -- components/v3/ProcessDesignerPanel.vue`

---

## Task 12：全量回归 + 收尾

- [ ] **Step 1** P-类型最终：`npx vue-tsc --noEmit 2>&1 | grep -c "error TS"` = Task 0 基线 N（零新增）。
- [ ] **Step 2** 6 面 × 浅/暗 after 全套截图，与 Task 0 before 对照成一份对比。
- [ ] **Step 3** 核验收：二级 tab 仅一种；徽章/chip 仅一套来源；首页无 SPEC 旧文案；暗色无破图。
- [ ] **Step 4** `git log --oneline` 确认全 commit 路径限定、无误卷文件。
- [ ] **Step 5** 写交接（memory + 可选 docs/handoff），更新 spec 状态为"已落地"。

---

## Self-Review（计划 vs spec）

- **Spec 覆盖**：token 合并(T10)/色·间距迁移(T9,T11)/删死代码(T10) = Phase1 ✓；状态组件(T8)/tab(T7)/徽章(T5)/chip(T6)/首页文案(T4)/SVG(T11) = Phase2 ✓；验收(T0,T12) ✓。composer hero 视觉对齐 spec 列为 Phase2#10 —— **本计划降级**：grep 发现 `LandingComposer.vue` 可能已是共享组件，chip 归一(T6)后两 composer 主要分叉点（chip）已收；剩余 composer 字阶/输入框 chrome 差异留作 T6 内顺手或单独跟进，不单列 task（YAGNI）。
- **占位扫描**：无 TBD；热点 file:line 均标"先 Read 核对"（因 line 漂 + 工具损坏风险，这是必要前置不是占位）。
- **类型一致**：新组件 props/emit 在 T1-3 定义，T5-8 引用一致（BaseBadge variant、BaseChip @click、BaseSubTabs v-model）。

**执行顺序**：T0 → T1-3（greenfield 原语）→ T4（文案，秒过）→ T5/T6/T7（采用，可见）→ T8（状态）→ T9（token）→ T10（去重）→ T11（SVG，最后）→ T12（回归）。原语先行，可见层快速兑现，风险递增、SVG 垫底。
