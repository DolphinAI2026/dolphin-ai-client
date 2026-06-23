# Phase 3 — Codex 风格文件面板复刻(FileTree + CodeViewer restyle + 编辑器 tab/面包屑外壳)

## Phase 3 — Codex 风格「文件面板」设计 spec

### 0. 现状(已核验)

文件面板现由 `CodingPage.vue` 的 `.ws-pane > .ws-pane-files` 承载,内含三件套:
- `frontend/src/views/coding/FileTree.vue`(顶部「筛选文件…」+ 本轮改动分组 + 文件树 body) — 内部递归用 `FileTreeNode.vue`(彩色图标 `AppIcon`、git A/M/D 角标、selected 左侧 brand 竖条)。
- `frontend/src/views/coding/CodeViewer.vue`(头部 `.cv-head` 单行路径 + body 代码区,shiki 高亮 + sticky 行号 gutter,已是 Codex 式)。对比模式委托 `DiffView.vue`。
- 布局:`.ws-pane-files { display:flex }` → 左 `FileTree`(宽度 `treePaneWidth`,可拖)、`.tree-resizer`、右 `CodeViewer`(flex:1)。

关键事实:
1. 三件套已全部走**语义 token**(`--bg`/`--bg-sub`/`--fg`/`--fg-dim`/`--fg-faint`/`--line`/`--brand`/`--brand-ink`/`--brand-soft`/`--font-mono`/`--t-success`/`--t-danger`/`--warn`),这些 token 在 `frontend/src/styles/theme-vars.css` 的 `html[data-theme="dark"]` 里已映射成一套 oklch 暗色盘。
2. Codex 设计稿(`frontend/dist/aichat-mockup.html`)的 token(`--bg-0:#0a0a0c` … `--brand:#5a78ff` `--accent:#f0824a` `--green:#34d399` `--red:#f87171`)**未在全站定义**,组件里仅作为 `var(--text-1, fallback)` 的兜底字面量出现 → 复刻策略 = 在文件面板根容器上**注入一层 Codex token 映射**,把语义 token 重绑到 Codex 数值。组件几乎不用改色值。
3. 设计稿 `aichat-mockup.html` 只覆盖会话栏+对话流+工具卡+输入区,**不含文件面板** → 文件面板的 Codex 观感按用户给的「Codex 实际界面观察」逐项复刻,token 沿用设计稿那一套。
4. 当前**缺失**的 Codex 结构件:① 编辑器 tab 条(文件名 tab + 新建 ＋);② 代码区头的面包屑(目录链 ›);③「打开」下拉 + 复制按钮(`.cv-head` 现在只有路径 + diff 切换,无这俩)。

---

### 1. 设计 token(在 Phase 2 外壳的文件面板根节点注入)

在 Phase 2 外壳给文件面板根容器(下文 `.cxfp` = codex-file-panel)加一个 `data-skin="codex"` 或直接 class,内部用 `:where()` 重绑语义 token,使三件套自动变 Codex 色。新增 CSS 写进 `CodingPage.global.css`(项目惯例 CSS 外置,文件面板的样式都在这):

```css
.cxfp {
  /* —— Codex 暗色盘(取自 aichat-mockup.html) —— */
  --cx-bg-0:#0a0a0c; --cx-bg-1:#111114; --cx-bg-2:#16171b; --cx-bg-3:#1d1e23;
  --cx-text-1:#e8eaed; --cx-text-2:#a1a4ad; --cx-text-3:#6c707a;
  --cx-brand:#5a78ff; --cx-accent:#f0824a; --cx-green:#34d399; --cx-red:#f87171;
  --cx-border:rgba(255,255,255,.06); --cx-border-hi:rgba(255,255,255,.1);
  --cx-bg-hover:rgba(255,255,255,.04);
  --cx-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;

  /* —— 把组件用的语义 token 重绑到 Codex 值(组件零改色) —— */
  --bg:var(--cx-bg-1); --bg-sub:var(--cx-bg-2); --bg-inset:var(--cx-bg-0);
  --bg-hover:var(--cx-bg-hover);
  --fg:var(--cx-text-1); --fg-dim:var(--cx-text-2); --fg-faint:var(--cx-text-3);
  --line:var(--cx-border); --line-strong:var(--cx-border-hi);
  --brand:var(--cx-brand); --brand-ink:var(--cx-brand); --brand-soft:rgba(90,120,255,.16);
  --t-success:var(--cx-green); --t-danger:var(--cx-red); --warn:var(--cx-accent);
  --font-mono:var(--cx-mono);
}
```

注意:这层只作用于文件面板,不污染对话流/配置面板。若 Phase 1/2 已在更高层注入了同套 Codex token,则此处只补文件面板特有的(tab/面包屑),不重复定义,避免双源漂移。**Token 单源**:把上面 `--cx-*` 原始盘放在 Phase 2 外壳顶层一次,文件面板只做「语义→cx」重绑。

---

### 2. 编辑器 tab 条(新增结构,Codex「文件名 tab + 新建 ＋」)

位置:替换现有 `.ws-pane-tabs`(现在是「文件/代码」「预览」两个模式 tab + 关闭)。Codex 把这两件事分两层:
- **外层模式切换**(文件/代码 ↔ 预览 ↔ 终端 ↔ 审查 ↔ 浏览器)归 Phase 2 外壳/命令面板管,Phase 3 不做。
- **内层编辑器 tab** = 已打开文件的 tab 列表。本期做**单 tab 显示当前文件**(MVP),结构留出多 tab 扩展位:

```
.cxfp-tabs (高 36, bg=--cx-bg-1, border-bottom=--cx-border)
  └ .cxfp-tab.active  [AppIcon 文件类型] 文件名  [×]
  └ .cxfp-tab-new     ＋   (title="新建标签",MVP 可禁用/灰显,留扩展)
```

CSS 要点:active tab `bg:--cx-bg-2; color:--cx-text-1; 顶部 2px brand 高亮条(box-shadow inset 0 2px 0 --cx-brand 或 ::after)`;非 active `color:--cx-text-3; hover bg=--cx-bg-hover`;tab 名用 `--cx-mono` 13px;`×` hover 才显形。tab 文案 = `selectedFile` 的 basename,图标复用 `CodeViewer` 现成的 `fileIcon` 逻辑(可抽到 `coding/filePreview.ts` 复用,避免重复)。

数据:当前只有 `selectedFile` 单值。MVP 单 tab 直接绑 `selectedFile`;多 tab 留 TODO(需要 `openTabs: string[]` 状态,本期不引入以免动 CodingPage 状态机)。

---

### 3. 代码区头 → 面包屑 + 「…」+ 「打开」下拉 + 复制(改 `CodeViewer.vue` 的 `.cv-head`)

现状 `.cv-head` = 图标 + 单行路径(目录灰 + 文件名加粗)+ diff 切换/接受按钮。Codex 头部布局(从左到右):

```
[面包屑]  ai-builder › frontend › dist › x.html          [现有 +N/-M 计数] [对比/全文] [接受]   [⋯] [打开 ⌄] [复制]
```

改动:
1. **面包屑**:把 `.cv-path` 的「目录(rtl 截断)+ 文件名」结构升级为分段面包屑。把 `filePath` 按 `/` split,渲染 `<span class="cxfp-crumb">seg</span>` 用 `›`(或现成 chevron path)分隔,最后一段 = 文件名(加粗 `--cx-text-1`),前缀段 `--cx-text-3`,可点(emit `crumb-click(path)` 暂只做 hover 态,点击 = no-op 或定位树,本期 hover-only)。中间过长时折叠成 `…`(超过 N 段时首段 + `…` + 末两段,Codex 行为)。复用现有 `dir`/`baseName` computed。
2. **「⋯」按钮**:`AppIcon name="more"`,放右侧动作组首位,点开一个小菜单(Element `el-dropdown` 或纯 CSS popover),菜单项至少:在文件树中定位、复制路径(MVP 可只放「复制路径」「下载」,行为复用已有 `downloadFile`)。
3. **「打开 ⌄」下拉**:文案「打开」+ 下拉箭头(inline chevron svg,沿用 FileTreeNode 的 caret path `M9 6l6 6-6 6`)。菜单项:在系统编辑器打开 / 在新标签打开预览 / 复制为链接 —— **MVP 只接已有能力**:`下载原文件`(`downloadWorkspaceFileRaw` 已有)、桌面端「在 Finder 显示」(若 Phase 2 暴露了 tauri 能力则接,否则灰显)。不要造没有后端的项。
4. **复制按钮**:`AppIcon name="clipboard"`,点 = 复制当前文件**全文**到剪贴板(读 `html` 来源的原始 content——注意 `CodeViewer` 现在只存高亮后的 `html`,需要在 `load()` 里把 `res.content` 原文也存一个 `rawContent` ref 供复制;diff 模式复制 diff 文本)。用 `navigator.clipboard.writeText`,复制后图标短暂变 check(800ms)。

CSS:`.cv-head` 高 44 不变,bg 改 `--cx-bg-1`(经 token 重绑自动生效),底边 `--cx-border`;面包屑分隔符 `›` 用 `--cx-text-3`;右侧动作按钮统一 `.cxfp-head-btn`(28×28,圆角 6,hover bg=--cx-bg-hover,color=--cx-text-2→hover --cx-text-1)。

---

### 4. 文件树 restyle(`FileTree.vue` + `FileTreeNode.vue` — 多为 CSS,经 token 自动暗化)

结构基本不动,经 §1 token 重绑后:
- 搜索框 `.ws-file-tree-search`:bg=--cx-bg-2,border=--cx-border,focus 时 border/ring 用 `--cx-brand`(现成 `color-mix(... var(--brand)...)` 自动生效)。placeholder「筛选文件…」(现文案「筛选文件，Enter 搜内容…」可保留,Codex 只显示「筛选文件…」→ 改 placeholder 为「筛选文件…」)。
- 文件树整体背景 `.ws-file-tree` 现在是 `linear-gradient(180deg,var(--bg-sub)...)` → 暗化后为 `--cx-bg-2` 渐变,OK。
- **彩色类型角标**:Codex 的「彩色类型角标」要比现在单色 `--fg-faint` 图标更鲜明。在 `FileTreeNode.vue` 给 `.ftn-icon` 按扩展名上色(新增):
  - `.json/.yaml/.yml` → `--cx-accent`(橙);`.vue/.html` → `--cx-green`;`.ts/.tsx/.js` → `--cx-brand`(蓝紫);`.md/.txt` → `--cx-text-2`;`.png/.svg/...` → `#c084fc`(紫,可加 `--cx-img` token);其余 → `--cx-text-3`。
  - 实现:`iconName` computed 已按扩展名分类,扩展为同时返回一个 `iconTone`(或加 `:class="'tone-'+ext分类"`),CSS 里 `.ftn-icon.tone-config{color:var(--cx-accent)}` 等。folder 图标保持 `--cx-text-2`,hover→`--cx-brand`(现成)。
- selected 行:现成左侧 3px brand 竖条 + brand 渐变底,暗化后 brand=`--cx-brand`,对齐 Codex 高亮。
- git A/M/D 角标颜色经 token 自动变 `--cx-green`/`--cx-accent`/`--cx-red`,符合 Codex diff 绿红。
- 「本轮改动」分组保留(这是项目特有、比 Codex 更强的能力,不删)。

---

### 5. 代码区(`CodeViewer.vue` body — 基本零改,经 token 自动暗化)

- shiki 高亮:`CodeViewer.load()` 传 `props.dark`(已绑 `themeStore.isDark`)。**坑**:Codex 面板要恒暗,但全局可能是 light 主题。需要让面板内 shiki 走暗色主题 → 给 `CodeViewer` 传一个 `forceDark` prop(Phase 2 外壳传 `true`),或文件面板恒传 `:dark="true"`。检查 `shikiHighlight.ts` 是否支持强制暗主题;`CodingPage.vue:378` 现传 `:dark="themeStore.isDark"` → 文件面板内改传 `:dark="true"`(Codex 恒暗)。
- sticky 行号 gutter 已是 Codex/VS Code 式,gutter 背景 `var(--bg)` → 暗化为 `--cx-bg-1`,行号色 `--fg-faint`→`--cx-text-3`,OK。
- 代码字体 `--font-mono`→`--cx-mono`,12.5px 不变。
- 空态/二进制/图片预览/错误态经 token 自动暗化,无需改。

---

### 6. 布局接入 Phase 2 外壳

文件面板作为 Phase 2 命令面板「文件 ⌘P」对应的视图挂载。Phase 3 交付一个自包含组件树:`CodingPage.vue` 现有 `.ws-pane-files`(FileTree + resizer + CodeViewer)即文件面板主体。建议**抽成一个 `coding/CodexFilePanel.vue`** 包住 tab 条 + `.ws-pane-files`,对外暴露 props(`wsId` / `tree` / `changes` / `selectedFile` / `selectedGitChange` / `forceDark`)和 events(透传现有 `@select`/`@select-line`/`@accept-all`/`@quote`/`@accept-change`),Phase 2 外壳直接挂这个组件,`CodingPage.vue` 改为引用它(减少 CodingPage 体积,符合 MEMORY 里 7A/7B CSS 外置+瘦身方向)。若 Phase 2 尚未定型,则先在 `CodingPage.vue` 原地改造,留好抽组件的接缝。

---

### 7. 交互/状态

- tab × → `emit('close-file')` → Phase 2/CodingPage 清 `selectedFile`(回空态)。MVP 单 tab。
- 面包屑段 hover 显下划线;点击本期 no-op(或定位文件树,二期)。
- 「打开」「⋯」下拉用 Element `el-dropdown`(项目已用 Element Plus),trigger=click,popper 暗色(给 popper 加 class 套 Codex token,Element 暗色弹层需显式样式)。
- 复制成功 toast 可用 `ElMessage`(现成),或图标内联变 check 800ms(更轻,推荐)。
- 内容搜索(Enter)结果视图、本轮改动分组、diff/全文切换 —— 全部保留,只过 token 暗化。

---

### 8. 验收标准

1. 文件面板整体呈 Codex 极深底(`#0a0a0c/#111114/#16171b`),蓝紫 brand `#5a78ff`,diff 绿 `#34d399`/红 `#f87171`,等宽字体 `ui-monospace`;与设计稿 `aichat-mockup.html` 同盘。
2. 顶部有编辑器 tab 条:active tab 显当前文件名 + 类型图标 + ×,顶部 2px brand 高亮;右侧「新建 ＋」。
3. 代码区头是面包屑(`ai-builder › … › x.html`,末段加粗),右侧有「⋯」「打开 ⌄」「复制」三个动作,复制能把当前文件全文写入剪贴板并给出反馈。
4. 右侧文件树有「筛选文件…」搜索框 + 文件夹/文件图标带**按类型彩色角标**(json 橙 / vue·html 绿 / ts 蓝紫 / 图片紫 等),selected 行 brand 高亮竖条,git 改动 A/M/D 角标绿/橙/红。
5. 代码区行号 sticky gutter + shiki 暗色高亮,横向滚动行号不跑;选中代码仍可「引用到对话」。
6. light/dark 全局主题下,文件面板**恒为 Codex 暗色**(不随全局主题翻白);对话流/配置面板不受本面板 token 注入影响(无外溢)。
7. `npm run build:nocheck` 通过;vue-tsc 触及文件零新增类型错;现有 FileTree/CodeViewer 的 spec(`fileTree.spec.ts` 等)仍绿;真机:打开工作区 → 文件面板能选文件、看高亮代码、看 diff、搜索、复制路径/全文、下载文件。
8. 复用而非重写:FileTree/FileTreeNode/CodeViewer/DiffView 仍是同一组件,后端调用零新增。