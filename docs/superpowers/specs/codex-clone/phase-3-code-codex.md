# Phase 3 — Code 模式「审查面板」Codex 风格复刻方案

# Phase 3 — 审查面板 Codex 风格复刻 spec

## 0. 现状盘点（复用，不重造）

审查 = 「本轮改动」的 diff 呈现。整条链路已存在，本 Phase 只 restyle + 加一个摘要卡组件。

后端（全部复用，零改动即可跑）：
- `backend/app/coding/git_changes.py` — git 当改动数据库：`collect_changes`(A/M/D + 逐文件 additions/deletions + binary + artifact 标记 + total 汇总)、`file_diff`(单文件 unified diff 文本)、`accept_changes`(收进基线，可整体或单文件)。
- `backend/app/routes/coding.py`
  - `GET /coding/workspace/{ws_id}/changes` → `WorkspaceChanges`
  - `POST /coding/workspace/{ws_id}/changes/accept` body `{file_path?}` → 接受后的 `WorkspaceChanges`
  - `GET /coding/workspace/{ws_id}/file-diff?file_path=` → `WorkspaceFileDiff`(enabled/path/status/diff/binary)

前端（复用 + restyle）：
- `frontend/src/api/coding.ts` — `getWorkspaceChanges` / `acceptWorkspaceChanges` / `getWorkspaceFileDiff` + 类型 `WorkspaceChanges` / `WorkspaceChangeEntry` / `WorkspaceFileDiff`（行 354-387）。**不改**。
- `frontend/src/views/coding/unifiedDiff.ts` — `parseUnifiedDiff` → `DiffRow[]`(hunk/add/del/ctx + oldNo/newNo) + `diffCounts`。**不改**，是 diff 渲染数据源。
- `frontend/src/views/coding/DiffView.vue` — 已逐行渲染红绿 + 行号 gutter + hunk 折叠行。**只 restyle**(scoped `<style>`)。
- `frontend/src/views/coding/FileTree.vue` — `<section class="wft-changes">` 已是「本轮改动」分组：置顶汇总(标题 + 计数 chip + +/− stats + 接受全部按钮) + 逐文件行(M/A/D + basename + 行 stats) + 构建产物折叠尾部。**restyle + 复用其数据计算**(`changeEntries`/`sourceEntries`/`artifactEntries`/`sourceTotals`/`changeMap`/`changedDirs`，行 171-189)。
- `frontend/src/views/coding/CodeViewer.vue` — 头部已有 `cv-counts`(+/−) / `cv-accept`(接受此文件) / `cv-toggle`(对比·全文) / `cv-badge`(已删除/改动)；body 已有 git diff 模式 + 全文模式。**只 restyle**。
- `frontend/src/views/CodingPage.vue` — 已 wire：`wsGitChanges`(行 633)、`loadWsGitChanges`/`scheduleGitChangesRefresh`(800ms 防抖)、`selectedGitChange`(行 651)、`acceptWorkspaceChange`/`acceptAllWorkspaceChanges`(行 657-683)、路径归一 `inChanges`(行 702)、改动后建议「评审一下本轮改动」(行 744)。右栏 tab=「文件/代码 | 预览」(行 350-352)。

设计稿 token（`frontend/dist/aichat-mockup.html` `:root`，行 8-22，权威）：
```
--bg-0:#0a0a0c  --bg-1:#111114  --bg-2:#16171b  --bg-3:#1d1e23
--bg-hover:rgba(255,255,255,.04)  --border:rgba(255,255,255,.06)  --border-hi:rgba(255,255,255,.1)
--text-1:#e8eaed  --text-2:#a1a4ad  --text-3:#6c707a
--brand:#5a78ff  --accent:#f0824a  --green:#34d399  --red:#f87171
mono: ui-monospace
```

## 1. 缺口（必须先和用户对齐的唯一决策点）

Codex「审查」卡右上有两个动作：**撤销 ↩** 和 **审核**。
- **审核** = 把改动收进基线 → 直接复用 `acceptWorkspaceChanges`（已有）。
- **撤销 ↩** = revert/discard 改动，把文件还原到基线 → **后端没有这个端点**（git_changes.py 只有 accept，没有 reset/discard）。

两条路（spec 给两套，建议默认 B 先落地）：
- **A（完整复刻）**：后端 `git_changes.py` 加 `discard_changes(ws_path, rel_path|None)`（整体 `git reset --hard HEAD` + `git clean -fd`；单文件 `git checkout HEAD -- path` / 未跟踪文件 `rm`），新增 `POST /coding/workspace/{ws_id}/changes/discard`。**有数据销毁风险**，必须二次确认弹窗（el-popconfirm）。
- **B（本期降级，推荐）**：只保留「审核（接受）」单动作，撤销按钮置灰带 tooltip「撤销改动即将上线」或直接不渲染。视觉上仍画出 Codex 双按钮槽位，撤销走 A 的后端落地后再点亮。

> 本 spec 的验收标准默认按 B 写；选 A 时把「撤销」从禁用改为接 discard + popconfirm。

## 2. 新增组件：ReviewSummaryCard（Codex「审查摘要卡」）

**新文件** `frontend/src/views/coding/ReviewSummaryCard.vue` + 同名 `.css`（CSS 外置惯例）。

数据：直接吃 `WorkspaceChanges`（`props.changes`），内部按 `artifact` 拆 source/artifact（复用 FileTree 同款 computed 逻辑，可抽到 `frontend/src/views/coding/changeGroups.ts` 共享纯函数，避免 FileTree 与本卡重复）。

布局（对照 Codex）：
```
┌─ review-card ────────────────────────────────────────────┐
│ ● 已编辑 {total.files} 个文件   +{additions} −{deletions}  [撤销↩] [审核] │  ← 头部
│ ─────────────────────────────────────────────────────────│
│  src/views/CodingPage.vue            +42  −7               │  ← 文件行(点击→选中并打开 diff)
│  src/api/coding.ts                   +5   −0               │
│  …                                                         │
│  再显示 {hiddenCount} 个文件  ⌄                            │  ← 默认显示前 N(=8)，其余折叠
│  ▸ 构建产物 {artifactCount} 个（已折叠）                   │  ← artifact 单独折叠组
└───────────────────────────────────────────────────────────┘
```

行为：
- 头部状态点：有改动=`--green`；无改动隐藏整卡。
- 文件行点击 → `emit('select', path)`，由 CodingPage 设 `selectedFile` 并确保右栏在「文件/代码」tab + CodeViewer 进 diff 模式（复用现有 `onTreeSelect` 同路径）。
- 「审核」→ `emit('accept-all')`（接 `acceptAllWorkspaceChanges`，已有确认逻辑见 CodingPage 行 672-683）。
- 「撤销」→ B 期禁用 / A 期 `emit('discard-all')` + popconfirm。
- 「再显示 N 个」展开/收起本地 `expanded` ref；artifact 组独立 `artifactOpen` ref，默认收起。
- 行内 stats：`+N` 用 `--green`、`−M` 用 `--red`、binary 显示「二进制」灰字、status=D 文件名加删除线 + 灰。

**挂载位置（两选一，建议都支持，CodingPage 控制）**：
1. **对话流内**（Codex 主形态）：当一轮 codegen 结束且 `wsGitChanges.enabled && sourceEntries.length` 时，在 streamMessages 末尾插一张 ReviewSummaryCard。**本 Phase 最小实现可只做形态 2**，形态 1 涉及消息流插卡时机，留作增量。
2. **右栏顶栏摘要条**：在「文件/代码」tab 顶部、FileTree 之上放一条精简版（仅头部行，无文件列表，点击展开），点「审核」即接受全部。

## 3. Restyle 规格（像素级对齐 Codex）

所有色值改用 §0 token；mono 字体统一 `--font-mono: ui-monospace, SFMono-Regular, Menlo, monospace`。

### 3.1 DiffView.vue（`<style scoped>` 改写）
- 容器：`background: var(--bg-1)`；`font-family: var(--font-mono)`；`font-size:12.5px; line-height:1.5`。
- 行号 gutter `.dv-no`：`color: var(--text-3)`；sticky 背景 `var(--bg-1)`。
- `.dv-ctx`：`background: var(--bg-1); color: var(--text-2)`。
- `.dv-add`：`background: color-mix(in srgb, var(--green) 12%, var(--bg-1))`；`.dv-add .dv-sign,.dv-text { color: var(--green) }`。
- `.dv-del`：`background: color-mix(in srgb, var(--red) 12%, var(--bg-1))`；红字 `var(--red)`。
- `.dv-hunk`：`background: var(--bg-2); color: var(--text-3); border-top/bottom:1px solid var(--border)`。
- 左侧加 add/del 行的 1px 色条（Codex 质感）：`.dv-add{box-shadow: inset 2px 0 0 var(--green)}`，del 同理 `--red`。

### 3.2 CodeViewer.vue 头部 `.cv-head`（scoped restyle）
- 头部：`background: var(--bg-2); border-bottom:1px solid var(--border); height:38px`。面包屑式路径：`.cv-path-dir{color:var(--text-3)}` `.cv-path-name{color:var(--text-1)}`，分隔用 `›`（可选，把 `/` 渲染成 `›`）。
- `.cv-counts-add{color:var(--green)}` `.cv-counts-del{color:var(--red)}`，mono。
- `.cv-toggle`（对比/全文 段控）：`background:var(--bg-3); border:1px solid var(--border); border-radius:8px`；`.active{background:var(--brand); color:#fff}`。
- `.cv-accept`：`border:1px solid var(--border); color:var(--text-2); background:transparent`；hover `border-color:var(--brand); color:var(--text-1)`。
- `.cv-badge` / `.cv-badge-del`：`--bg-3` 底，del 用 `color-mix(--red 18%)`。

### 3.3 FileTree.vue 改动分组 `.wft-changes`（scoped restyle）
- `border-bottom:1px solid var(--border)`。
- `.wftc-toggle`：`color:var(--text-1); font-weight:600`；hover `background:var(--bg-hover)`。
- `.wftc-caret`：`color:var(--text-3)`。
- `.wftc-count` chip：`background: color-mix(in srgb, var(--brand) 16%, transparent); color:var(--brand)`。
- `.wftc-add{color:var(--green)} .wftc-del{color:var(--red)}`。
- `.wftc-accept`：同 cv-accept 描边风格，hover 点亮 `--brand`。
- `.wftc-row` hover：`background:var(--bg-hover); color:var(--text-1)`；选中行 `background: color-mix(in srgb, var(--brand) 12%, transparent)`。
- M/A/D 徽标颜色：M=`--accent`、A=`--green`、D=`--red`（与文件树角标一致）。

### 3.4 ReviewSummaryCard.css（新）
- 卡：`background:var(--bg-2); border:1px solid var(--border); border-radius:12px; overflow:hidden`。
- 头部：`background:var(--bg-3); padding:10px 14px; display:flex; align-items:center; gap:10px`。状态点 8px 圆 `var(--green)`。
- 「已编辑 N 个文件」`color:var(--text-1); font-weight:600`；右侧 `+X` green `−Y` red，mono。
- 动作区 `margin-left:auto`：撤销=ghost(`color:var(--text-3)`，B 期 `opacity:.4; cursor:not-allowed`)，审核=`background:var(--brand); color:#fff; border-radius:8px; padding:5px 12px`，hover 提亮。
- 文件行：`padding:7px 14px; font-family:var(--font-mono); font-size:12.5px; color:var(--text-2)`；hover `background:var(--bg-hover)`。
- 「再显示 N 个文件 ⌄」/「构建产物」折叠行：`color:var(--text-3); font-size:12px`，caret 旋转动画。

## 4. 交互状态（状态机）
- changes.enabled=false（git 不可用）→ 整个审查 UI 隐藏，CodingPage 回退会话流追踪（已有逻辑，不动）。
- enabled=true & sourceEntries.length=0 & artifact 也空 → 摘要卡不渲染；FileTree 分组不显示。
- 接受中 `acceptingWorkspaceChanges`（CodingPage 已有）→ 审核按钮 loading + disabled。
- 选中文件 status=D → CodeViewer 只给 diff 模式（已有，行 352）。
- binary → diff 区显示「二进制文件改动，不支持对比」（已有）。

## 5. 验收标准
1. 暗色模式下 DiffView/FileTree 改动组/CodeViewer 头部全部用 §0 token 渲染，无残留旧 `--brand:#4f6ef7`/`#16a34a`/`#e5484d` 硬编码可见差异；add 绿=`#34d399`、del 红=`#f87171`、brand 蓝紫=`#5a78ff`、accent 橙=`#f0824a`。
2. 一轮 codegen 后右栏「文件/代码」tab 顶部出现 ReviewSummaryCard（或对话流末卡），显示「已编辑 N 个文件 +X −Y」，数字 == `changes.total`。
3. 点摘要卡某文件行 → 右栏选中该文件并默认进「对比」模式，红绿 diff 正确。
4. 点「审核」→ 调 `acceptWorkspaceChanges(wsId,null)`，成功后摘要卡按新 changes 刷新（files 归零则卡消失）。
5. 「再显示 N 个文件」展开/收起正常；构建产物(artifact) 默认折叠、可展开。
6. 撤销按钮：B 期禁用且 tooltip 说明；选 A 时点击弹 popconfirm，确认后调 discard 端点并刷新。
7. `npm run build:nocheck` 通过，无新增 console 错误（项目惯例：full `vue-tsc` build 预存坏，以 build:nocheck 为准）。
8. changes.enabled=false 时审查 UI 全隐藏不报错。

## 6. 不做（边界）
- 不改后端 collect_changes/file_diff/accept 逻辑（除非选 A 加 discard）。
- 不动 unifiedDiff.ts 解析逻辑。
- 不做终端/浏览器/文件面板（那是 Phase 1/2/4/5）。
- 不做对话流插卡的精确时机编排（最小实现走右栏顶栏形态）。