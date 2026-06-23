All key facts confirmed. Critical correction: dark `--t-success` IS `#34d399` and `--t-danger` IS `#f87171` (matching Codex green/red), but dark `--t-brand` is `#7c8cff` (NOT Codex `#5a78ff`). The run-card `--ok/--err/--line/--surface-2` tokens exist in global.css. The right pane is `.ws-pane` with `wsPaneTab: 'files'|'run'` + `codePaneOpen` + `RunDebugPanel`. Now I have enough to write the master plan.

I also note a real conflict between the two token strategies across specs that must be adjudicated. Here is the master plan.

---

# Code 模式 Codex 化 · 主实施计划

> 综合 6 份 Codex 复刻设计稿(1 份设计系统 + Phase1 对话流 + Phase2 外壳/命令面板 + 3 份四面板)。已对照真实代码核验关键事实,纠正 spec 中的 2 处口径冲突。面向后续 autonomous 分阶段实现。

## 0. 已核验的代码事实(裁决依据)

| 断言 | 核验结果 |
|---|---|
| `--cx-*` token / `codex-tokens.css` 是否已存在 | **不存在**。全部 6 份均为提案,设计系统 spec 的「新建文件」尚未落地 |
| 暗色 `--t-success` / `--t-danger` | `#34d399` / `#f87171` —— **与 Codex green/red 完全一致**(可直接复用) |
| 暗色 `--t-brand` | `#7c8cff` —— **≠ Codex `#5a78ff`**(设计系统 spec 已正确标注「差异明显→独立」,Phase1 spec 把 `--t-brand` 重映射到 `--cx-brand` 也成立) |
| run-card 老 token `--line/--surface-2/--ok/--err` | 真实存在于 `CodingPage.global.css`(line 25/473/477),Phase1 桥接需覆盖它们 |
| 右侧面板现状 | `.ws-pane` + `wsPaneTab: 'files'\|'run'` + `codePaneOpen: ref(false)` + `RunDebugPanel`(line 345-388, 514, 823) |
| 懒加载/串台守卫 | `watch(codePaneOpen, ...)` 驱动 `ensureCodePaneData`(line 781/794/809/818)—— Phase2 替换状态时**必须语义等价** |
| 预览自动切位 | line 1094/1112 现写 `wsPaneTab='run'; codePaneOpen=true` |
| embed 模式 | `embedMode`(`?embed=true`) / `embeddedAppId` 已有 `v-if` 排除链,新组件需挂同条件 |
| main.ts CSS 顺序 | `theme-vars.css` 在 line 17 import(注:`design-v3-tokens.css` 已因远程字体被移除,设计系统 spec「在 design-v3 之后 import」的措辞需改为「在 theme-vars.css 之后」) |
| `npm run build`(完整 vue-tsc) | **预存坏**,全程以 `build:nocheck` 为准 |

---

## 1. 统一设计系统口径(裁决)

### 1.1 两套对立的 token 策略 —— 裁决:**Phase1 用「桥接重映射」,Phase2/3 新组件用「原生 --cx-」**

6 份稿存在根本分歧:

- **A. 设计系统 spec + Phase1 spec**:作用域内把现有 `--t-*` / 老 `--line/--surface-2` **重映射**到 Codex 值,旧组件「无感切肤」。
- **B. Phase2 spec**:新组件**直接引用 `--t-*`**(`--cph-bg: var(--t-bg-panel)`),不引入 `--cx-`。
- **C. Phase3(文件/审查/终端浏览器)spec**:新组件**直接引用 `--cx-*` 原始盘**,或在面板根「语义→cx 重绑」。

**裁决:两者并存,分层定责,单一来源。**

1. **`--cx-*` 原始盘 = 唯一权威定义,只定义一次**,放在 Phase1 新建的共享文件 `frontend/src/styles/codex-tokens.css`,作用域 `.codex-skin`(对话流根)。Phase2/3 的面板宿主挂在同一 `.codex-skin` 子树内 → 直接继承 `--cx-*`,**严禁二次定义同名 token**(否则双源漂移,这是 Phase3 两份 spec 各自列出的风险)。
2. **Phase1 的「桥接重映射」保留**,但定位收窄为「让**不改的旧共享组件**(ToolCard/FileCard/AgentConversation 里硬编码灰之外、走 `--t-*` 的部分)切肤」。即在 `.codex-skin` 内把 `--t-bg-base/--t-brand/--line/--surface-2/--ok/--err...` 重指向 `var(--cx-*)`。
3. **Phase2/3 的新组件一律直接用 `--cx-*`**,放弃 spec B 里 `--cph-*` 这层多余别名(否则出现 `--cx-` / `--cph-` / `--t-` 三套)。Phase2 的 `--cph-*` 块**删除**,改为直接 `var(--cx-*)`。

### 1.2 token 值裁决(纠正 spec 错误)

| token | 终值 | 说明 |
|---|---|---|
| 绿/红 | `--cx-green:#34d399` / `--cx-red:#f87171` | 与暗色 `--t-success/--t-danger` **恰好相同**(核验确认);桥接时 `--t-success/--t-danger` 在 `.codex-skin` 内**无需改**,但为统一仍可显式重指 |
| brand | `--cx-brand:#5a78ff` | **必须独立**(暗 `--t-brand` 是 `#7c8cff`,色相偏紫);桥接里 `--t-brand→var(--cx-brand)` |
| accent 橙 | `--cx-accent:#f0824a` | 现有体系**完全无等价**,新增。grep 确认 `--accent` 0 命中 |
| sans/mono | 复用 `--font-sans`/`--font-mono`;`--cx-mono` 指纯 `ui-monospace` 栈 | Geist Mono 已 self-host,纯 Codex 观感用 `ui-monospace` |
| 裸名禁用 | 禁止 `--bg-0/--text-1/--mono` 裸名 | 与现有 `--text-2/--text-3`(design-v3 残留)/`--mono` 撞名串色,**一律 `--cx-` 前缀** |

### 1.3 恒暗决策

Code 模式**恒为 Codex 深色**(`.codex-skin { background:var(--cx-bg-0); color:var(--cx-text-1) }`),不随全局 light/dark。需在文档明示并处理两处溢出:
- **append-to-body 的 EP 浮层**(el-drawer/el-dialog/el-dropdown popper)在 `.codex-skin` 作用域外 → 需给这些 popper 加 class 套 Codex token(Phase2 命令面板若用自写 div 则免疫;Phase3 文件面板「打开/⋯」下拉若用 `el-dropdown` 必须处理 popper class)。
- **CodeViewer 的 shiki 主题**:全局 light 时 `:dark=themeStore.isDark` 会传 false → 文件面板内**改传 `:dark="true"` 恒暗**,并确认 `shikiHighlight.ts` 支持强制暗主题。

---

## 2. 实现顺序 + 文件级改动清单

### Phase 0(前置,必须最先做)— 共享 token 文件

**这是所有 Phase 的地基,单独成一步,先合并。**

| 文件 | 改动 |
|---|---|
| `frontend/src/styles/codex-tokens.css` | **新增**。`.codex-skin { --cx-* 原始盘 (§1.2 终值) + 字号/圆角/阴影/motion 阶梯 + 滚动条 + 恒暗基底 }`。这是 `--cx-*` 的**唯一定义处** |
| `frontend/src/main.ts` | **新增 import**,放在 `theme-vars.css`(line 17)**之后** |

验收:import 后全站无变化(`.codex-skin` 未挂任何元素),`build:nocheck` 通过。

### Phase 1 — 对话流 restyle(只改呈现,0 改共享 .vue)

| 文件 | 改动 |
|---|---|
| `CodingPage.vue` | **仅 1 行**:`.coding-body` 加 `:class="{ 'codex-skin': true }"`(恒挂)。不动任何数据逻辑/props/SSE |
| `CodingPage.styles.css` | 新增 `.coding-body.codex-skin` 段:① §1.1 桥接重映射(`--t-*`/`--line`/`--surface-2`/`--ok`/`--err`→`var(--cx-*)`)② `:deep()` 覆盖共享组件硬编码灰(ToolCard `.tc-sep/.tc-args/.tc-meta/.tc-duration`、`.tc-name`橙、`.tool-card` radius 999→8;AgentConversation `.ac-avatar.brand` 圆形橙字、`.ac-bubble.user-bubble`、`.ac-ask-opt`、`.ac-tool-group`、`.ac-typing`;FileCard `.msg-file-card`/行号灰)③ 命令/思考/SPEC/ask 卡微调 ④ 输入区 `:deep(.ucc-box/.ucc-input/.ucc-send)` + model-picker/token-usage |
| `CodingPage.global.css` | run-card(line 473-484)若被桥接覆盖即可;残余裸 `--surface-2` 等已在桥接处理 |

**边界**:不造「N 文件聚合 diff 卡」(归 Phase3 审查),不造窗口控件(Tauri 壳职责),不改 light theme。

### Phase 2 — 外壳 + 命令面板(改 CodingPage 状态机)

| 文件 | 改动 |
|---|---|
| `frontend/src/views/coding/useCodexPanels.ts` | **新增**。状态机 `open/active/paletteOpen` + 快捷键注册(⌘K/⌃⇧G/⌘P/⌘T,输入框聚焦守卫,⌘P/⌘T `preventDefault`)+ 命令注册表。`active: 'review'\|'terminal'\|'browser'\|'files'` |
| `useCodexPanels.spec.ts` | **新增**。快捷键 match / 命令表纯函数单测 |
| `CodexPanelHost.vue` | **新增**。替换 `.ws-pane` 内部:段控顶栏 + `v-show` 路由四面板 + `.cph-resizer`(沿用 `onCodePaneResizeStart`) |
| `CommandPalette.vue` | **新增**。Teleport 浮层,⌘K,↑↓Enter/Esc,快捷键 chip。**用自写 div + `--cx-shadow-pop`**(免 EP popper 溢出) |
| `CodingPage.vue` | 删 `codePaneOpen`/`wsPaneTab` 裸 ref → 接 `useCodexPanels`;`.ws-pane` 块(345-388)换 `CodexPanelHost`;`.coding-chat-actions` 加布局切换按钮;挂 `CommandPalette`;**迁移 line 1094/1112 `wsPaneTab='run'`→`show('browser')`、line 719 `'files'`→`show('files')`、`watch(codePaneOpen)`→`watch(panelOpen)`(语义等价,守护懒加载/串台)**;embed 条件排除 |
| `CodingPage.styles.css` | `.codex-panel-host`/`.cph-*`/段控样式(用 `--cx-*`) |

**关键风险护栏**:`panelOpen` 必须 1:1 语义替换 `codePaneOpen`,否则 `ensureCodePaneData` 懒加载 + 切会话 attach/detach 串台守卫回归。

### Phase 3 — 四面板(部分可并行,见 §4)

四面板均挂进 Phase2 的 `CodexPanelHost`,各自独立组件:

**3a 文件面板**

| 文件 | 改动 |
|---|---|
| `coding/CodexFilePanel.vue` | **新增**。包编辑器 tab 条(MVP 单 tab) + `.ws-pane-files`(FileTree+resizer+CodeViewer) |
| `CodeViewer.vue` | 改:`.cv-head` 路径→面包屑 + 「⋯/打开/复制」;`load()` 存 `rawContent` 供复制;`:dark` 恒 true |
| `FileTree.vue` / `FileTreeNode.vue` | 改:`.ftn-icon` 按扩展名彩色角标;placeholder 改「筛选文件…」 |
| `coding/filePreview.ts` | 可选:抽 `fileIcon/iconTone` 共享 |

**3b 审查面板**

| 文件 | 改动 |
|---|---|
| `coding/ReviewSummaryCard.vue` + `.css` | **新增**。「已编辑 N 个文件 +X −Y」+ 文件行 + 审核/(撤销禁用) |
| `coding/changeGroups.ts` | **新增**。抽 source/artifact/totals 纯函数(FileTree 与 Card 共用,避双写) |
| `DiffView.vue` / `CodeViewer.vue`(cv-head) / `FileTree.vue`(.wft-changes) | restyle scoped → `--cx-*` |
| `coding/ReviewPanel.vue`(Phase2 spec 命名) | 与 ReviewSummaryCard 合一:**审查面板 = 顶栏摘要 + 文件清单**,挂 `CodexPanelHost` 的 `review` 槽 |
| (仅选方案 A 时)`backend/.../git_changes.py` + `routes/coding.py` | 加 `discard` 端点 |

**3c 终端 + 浏览器面板**

| 文件 | 改动 |
|---|---|
| `coding/useWorkspaceServe.ts` | **新增**。共享 serve 生命周期(start/stop/booting/devUrl/status),搬 RunDebugPanel 逻辑。**单一真相源 = `codingStore.activePreview`** |
| `coding/TerminalPanel.vue` + `.spec.ts` | **新增**。消费 `/serve-logs` SSE(`serveLogsUrl`,`last_seen_seq` 续传,ring 1000)+ runtime 报错;stdout/stderr/runtime 分色;自动滚 |
| `coding/BrowserPanel.vue` + `.spec.ts` | **新增**。地址栏 + iframe + 启动预览带入 devUrl;`↗` openExternal;error 不拼假地址 |
| `coding/RunDebugPanel.vue` | **退役**(或薄包装过渡;删前 grep 全量引用,含 embed 入口) |
| `CodingPage.vue` / `CodingPage.global.css` | `RunDebugPanel` 引用迁移;tab 三态(已由 Phase2 `active` 承接) |

---

## 3. 跨 Phase 共享件(必须先建)

| 共享件 | 建于 | 被谁依赖 | 强制约束 |
|---|---|---|---|
| **`codex-tokens.css`(`--cx-*` 唯一定义)** | Phase 0 | 全部 Phase | 唯一定义处,任何 Phase 不得二次定义同名 `--cx-` |
| **`.codex-skin` 作用域 + 桥接段** | Phase 1 | Phase2/3 的宿主继承 | Phase2/3 面板必须挂在 `.codex-skin` 子树内才能拿到 `--cx-*` |
| **`useCodexPanels.ts`(面板状态机)** | Phase 2 | Phase3 四面板的挂载契约(props/events 形状) | Phase3 抽组件依赖此契约;Phase2 未定型则 Phase3 先原地改造留接缝 |
| **`CodexPanelHost.vue`(shell 容器)** | Phase 2 | Phase3 四面板的物理挂载点 | — |
| **`changeGroups.ts`** | Phase 3b | FileTree + ReviewSummaryCard | 抽出避免分组逻辑双写 |
| **`useWorkspaceServe.ts`** | Phase 3c | TerminalPanel + BrowserPanel | 两面板共享,防止各自 startServe 起多进程 |

> **顺序硬依赖**:Phase 0 → Phase 1(挂 `.codex-skin`)→ Phase 2(shell + 状态机)→ Phase 3(挂进 shell)。Phase 1 与 Phase 2 之间无强耦合(Phase1 只改样式,Phase2 改状态机),但 **Phase 0 必须最先**,否则全部 `var(--cx-*)` 取不到值回退 fallback 旧色。

---

## 4. 并行 vs 串行

### 可并行(独立新组件,文件不冲突)

- **Phase 3b 审查** ⟂ **Phase 3c 终端+浏览器**:不同新文件(`ReviewSummaryCard/changeGroups` vs `TerminalPanel/BrowserPanel/useWorkspaceServe`),后端互不触碰。**可两 agent 并行**。
- **Phase 3a 文件面板**:`CodexFilePanel/CodeViewer/FileTree/FileTreeNode` —— 与 3b 有**交集冲突**:3b 也 restyle `FileTree.vue`(`.wft-changes`)和 `CodeViewer.vue`(`.cv-head`)。→ **3a 与 3b 串行或同一 agent 做**(都碰 FileTree.vue + CodeViewer.vue)。
- `useCodexPanels.spec.ts` / `TerminalPanel.spec.ts` / `BrowserPanel.spec.ts` 纯新增,随各自组件走。

### 必须串行(改同一文件)

- **`CodingPage.vue`** 是最大串行瓶颈:Phase1(加 class)、Phase2(状态机大改 345-388/719/1094/1112/watch)、Phase3(各面板挂载 + RunDebugPanel 迁移)全改它。→ **Phase 间对 CodingPage.vue 严格串行**,不可并行编辑。
- **`CodingPage.styles.css`** / **`CodingPage.global.css`**:Phase1/2/3 均追加段落 → 串行,或各 Phase 用清晰段落注释边界(`/* ===== Phase N ===== */`)降低 merge 冲突。
- **`CodeViewer.vue` / `FileTree.vue`**:3a(结构+面包屑)+ 3b(diff restyle)同碰 → 同 agent 串行。

> **autonomous 编排建议**:Phase0→1→2 单线串行;Phase3 启两条线 —— 线 A =「文件面板 3a + 审查 3b」(共享 FileTree/CodeViewer,串行),线 B =「终端+浏览器 3c」(独立);最后串行收口 `CodingPage.vue` 的 RunDebugPanel 迁移。

---

## 5. 每 Phase 验收标准

**通用门(每 Phase 必过)**:`npm run build:nocheck` 通过;vue-tsc 触及文件零**新增**类型错;既有关联测试不回归(`CodingPage.token.spec.ts`、`codingLayout.spec.ts`、`serveLogsUrl.spec.ts`、`fileTree.spec.ts`、`unifiedDiff.spec.ts` 等);切到 Builder/AIChat 页观感不变(skin 未泄漏)。完整 `vue-tsc` build 预存坏,不作门。

| Phase | 视觉/功能核对要点 |
|---|---|
| **0** | import 后全站零变化;`.codex-skin` 类挂测试元素能取到 `--cx-bg-0` 等值 |
| **1** | 对照 `aichat-mockup.html`:整页底 `#0a0a0c`;AI 头像圆形橙字;工具名橙 mono、状态绿/红/蓝、卡 8px 圆角、展开 pre 纯黑;diff +绿/−红;ask 卡蓝调、选项 hover 蓝实底;输入框 14px 圆卡聚焦蓝边、停止键红渐变;light 全局下 Code 区恒暗且周边不破 |
| **2** | ⌘K 弹命令面板(5 行 + 快捷键 chip,↑↓Enter/Esc/点击);⌃⇧G/⌘P/⌘T 直达对应面板且输入框聚焦时不抢焦点(⌘K 仍可用);布局键开关宿主;`v-show` 切面板不断 SSE/不重载 iframe;embed 模式不渲染宿主与浮层;**懒加载/切会话 attach-detach 不回归**(panelOpen 等价 codePaneOpen) |
| **3a** | tab 条显当前文件名+类型图标+×、顶 2px brand;代码区头面包屑 `ai-builder › … › x.html`;复制写全文入剪贴板+反馈;文件树彩色角标(json 橙/vue·html 绿/ts 蓝紫/图片紫)、selected brand 竖条、git A/M/D 绿/橙/红;shiki 恒暗;light 全局下文件面板恒暗、对话流/配置面板无外溢 |
| **3b** | DiffView/FileTree 改动组/CodeViewer 头全 `--cx-*`,无旧硬编码色残留;审查面板显「已编辑 N +X −Y」(数字==`changes.total`);点文件行选中并进 diff 对比;「审核」走 `acceptWorkspaceChanges` 后刷新;「再显示 N 个」+构建产物折叠正常;撤销按钮按裁决态(B 禁用带 tooltip / A popconfirm);`changes.enabled=false` 全隐藏不报错;**摘要卡与树内分组不出现两处「接受全部」歧义** |
| **3c** | 终端实时滚 stdout(默认色)/stderr(橙)/runtime(红);断线 `last_seen_seq` 补发不重不漏;浏览器地址栏手输回车加载、启动预览带入 devUrl、`↗` 外开、`⟳` 刷新;error 显真实 message 不白屏不拼假址;runtime 报错只在终端出现一次但仍 `ingestRuntimeErrors` 上报;Terminal/Browser 对 serve 状态一致(一处停两处同步);不新增后端端点、不碰 `CustomPagePreviewPanel` |

---

## 6. 风险汇总 + 缓解

| # | 风险 | 缓解 |
|---|---|---|
| R1 | **token 双源漂移**(`--cx-*` 在 Phase0/1/3 多处被各 spec 各自定义) | **铁律:`--cx-*` 只在 `codex-tokens.css` 定义一次**;Phase2 删 `--cph-*` 别名直接用 `--cx-*`;Phase3 面板只做「语义→cx 重绑」或直引,不重定义原始盘 |
| R2 | **状态机替换回归**(`panelOpen` 替 `codePaneOpen` 破坏懒加载/切会话串台守卫,line 781/794/809/818) | Phase2 改后专项回归 `ensureCodePaneData` 触发时机 + 切会话 attach/detach;`panelOpen` 严格 1:1 语义等价;保留 `previewEpoch`/`lastChangedFile` 自动切位行为 |
| R3 | **共享组件硬编码灰**(ToolCard/FileCard/AgentConversation 内 `rgba(116,128,171,…)` 桥接覆盖不到) | Phase1 用 `:deep()` 逐处覆盖;`grep -n "rgba(116,128,171" frontend/src/components` 核对清单,逐条消灭;部分用 `!important` 的(如 `.ac-avatar.brand`)覆盖需同级 `!important` |
| R4 | **恒暗 vs EP append-to-body 浮层溢出**(el-drawer/dialog/dropdown popper 在 `.codex-skin` 外不继承) | 命令面板用自写 div 免疫;Phase3「打开/⋯」下拉给 el-dropdown popper 加 class 套 `--cx-*`;文件/设置抽屉单独处理或文档注明保持原样 |
| R5 | **shiki 全局 light 下传 false 致文件面板变白** | 文件面板 `CodeViewer` 恒传 `:dark="true"`,先确认 `shikiHighlight.ts` 支持强制暗主题 |
| R6 | **撤销(revert)缺口**(后端只有 accept,无 discard) | **默认方案 B**:审查卡撤销按钮禁用 + tooltip「即将上线」,画出槽位;选 A 时后端加 `discard`(`git reset --hard`/`clean`/`checkout`,**数据销毁必 popconfirm**)。**需用户决策** |
| R7 | **⌘P/⌘T 与系统/浏览器冲突** | `preventDefault`;Web 预览(非 Tauri)下真机验是否被系统抢 |
| R8 | **serve-logs SSE 在桌面 sidecar 内可达性**(首次有前端消费者) | EventSource token 走 query;桌面包真机验 SSE 是否经 sidecar 正确转发;ring 1000 对齐后端 `_SERVE_LOG_RING_MAX` |
| R9 | **路径归一坑**(basename↔全路径,审查卡 emit 必须全路径) | ReviewSummaryCard 文件行 emit 全路径,与 `onTreeSelect`/`inChanges`(line 702)归一一致,否则点击选不中 |
| R10 | **mockup 不含文件/审查/终端/浏览器面板**(只能按文字描述 + 截图复刻) | tab 高亮/面包屑间距/彩色角标具体色值需真机截图二次像素校准,列为各面板验收的人工核对项 |
| R11 | **RunDebugPanel 退役引用残留**(embed/WorkspaceShell 可能也引用) | 删前 `grep -rn "RunDebugPanel" frontend/src`;过渡期保留薄包装 |
| R12 | **dev working tree 脏态**(方案 B「SPEC 确认门去按钮」未提交,agentMessages/CSS 脏) | 接线前先 `git status` 确认,Phase 改动别覆盖未提交的 specgate 改动;新工作建议从干净分支起 |
| R13 | **审查卡 vs 树内分组功能重叠**(两处「接受全部」) | 裁决:审查面板摘要卡为主 Codex 形态,树内分组保留作树上下文,逻辑经 `changeGroups.ts` 单源;UI 上避免并列两个等效按钮 |
| R14 | **`--font-mono` 是 Geist Mono 优先**(非纯 Codex `ui-monospace`) | `--cx-mono` 独立指 `ui-monospace` 栈,Codex 组件用 `--cx-mono` 而非 `--font-mono` |

---

## 7. 待用户决策(阻塞项)

1. **R6 撤销端点**:方案 A(后端加 discard,有数据销毁风险)还是 B(本期禁用撤销)?计划默认 B。
2. **侧边聊天 ⌥⌘S**:Phase2 只留命令桩(noop),确认本期不实现真功能?
3. **Code 模式恒暗**:确认 Code 模式不随全局主题(始终 Codex 深色)?计划默认恒暗。

相关文件锚点(均绝对路径):
- `/Users/mars/Vibe Coding/ai-builder/frontend/src/styles/codex-tokens.css`(待新增,Phase0)
- `/Users/mars/Vibe Coding/ai-builder/frontend/src/styles/theme-vars.css`(token 现状,line 150 起暗色块)
- `/Users/mars/Vibe Coding/ai-builder/frontend/src/main.ts`(line 17 import 锚点)
- `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/CodingPage.vue`(最大串行瓶颈:line 345-388/719/776/823/1094/1112/watch)
- `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/CodingPage.styles.css` · `CodingPage.global.css`(line 473 run-card)
- `/Users/mars/Vibe Coding/ai-builder/frontend/src/views/coding/`(四面板新组件目标目录 + 复用 RunDebugPanel/FileTree/CodeViewer/DiffView/serveLogsUrl)
- `/Users/mars/Vibe Coding/ai-builder/frontend/dist/aichat-mockup.html`(938 行设计稿,token 权威来源 line 8-24)