# Codex 风 Code 模式 — 设计系统抽取 (design-system spec)

# Codex 风 Code 模式 — Design System Spec

后续所有 Phase 引用本文件。所有数值均直接从 `frontend/dist/aichat-mockup.html`(938 行)抽取，标注「来源行号」。落地约束见末尾「与现有主题的集成」。

---

## 0. 关键决策(先读)

1. **Codex 观感 = 固定深色**。mockup 是单一深色稿，无明暗切换。现有 app 默认 light、`data-theme="dark"` 才暗。Code 模式应在根容器**强制 Codex 深色作用域**(见 §6 落地方案 B：`.coding-codex` scope，不依赖全局 theme)，避免被 light 主题污染，也不破坏其它页面。
2. **新增一套 `--cx-*` 前缀 token**(Codex 专用)，而不是改 `--t-*` / `--brand`。理由：CodingPage 现有 CSS(`CodingPage.styles.css` 2538 行)重度依赖 `--t-*`(42×`--t-border-subtle`、33×`--t-text-primary`…)，直接改全局会波及配置面板/Builder/对话页。`--cx-*` 独立命名零冲突，逐组件迁移可控。
3. **橙色 accent 是现有体系完全缺失的**(grep `--accent` 全仓 0 命中)。`--cx-accent: #f0824a` 为新增，仅 Code 模式用(工具名/品牌点/头像)。
4. 字体：mockup 正文用系统 sans，**等宽用 `ui-monospace`**。现有已有 `--font-mono`(Geist Mono → ui-monospace fallback)，可直接复用，但 Codex 观感建议 `--cx-mono` 指向纯 `ui-monospace` 栈(更贴近 Codex/VS Code 默认 SF Mono)。

---

## 1. 设计 Token（完整抽取，来源行 8–24）

### 1.1 表面 / Surfaces
| Token | 值 | 用途(来源) |
|---|---|---|
| `--cx-bg-0` | `#0a0a0c` | 最深底：chat-main、消息区、输入区、tool pre 代码块底(行 9, 130, 329) |
| `--cx-bg-1` | `#111114` | 侧栏 sidebar、产物面板、tool-call 卡底(行 10, 46, 251, 526) |
| `--cx-bg-2` | `#16171b` | 输入卡、用户气泡、header-pill、artifact-link/card、小按钮(行 11, 155, 187, 378, 424) |
| `--cx-bg-3` | `#1d1e23` | 新会话按钮、active 会话项、AI 头像底、输入内 chip、表头(行 12, 68, 102, 199, 442, 603) |
| `--cx-bg-hover` | `rgba(255,255,255,.04)` | 所有 hover 高亮 + attach-chip 底(行 13, 230) |
| `--cx-bg-sunken` | `rgba(0,0,0,.25)` | tool-body 展开区底(行 312) |

### 1.2 边框 / Borders（行 14–15）
| Token | 值 | 用途 |
|---|---|---|
| `--cx-border` | `rgba(255,255,255,.06)` | 默认所有分隔/卡片边 |
| `--cx-border-hi` | `rgba(255,255,255,.1)` | hover 态边、输入卡边、artifact-link 边、滚动条 thumb、表格线 |

### 1.3 文字 / Text（行 16–18）
| Token | 值 | 用途 |
|---|---|---|
| `--cx-text-1` | `#e8eaed` | 主文字 / 标题 / 用户气泡正文 |
| `--cx-text-2` | `#a1a4ad` | 次要：会话项、工具参数、attach-chip、icon-btn |
| `--cx-text-3` | `#6c707a` | 弱：标签、时长、meta、placeholder、folder 路径、toggle 箭头 |

### 1.4 品牌 / 强调 / 状态（行 19–22）
| Token | 值 | 用途 |
|---|---|---|
| `--cx-brand` | `#5a78ff` | 蓝紫：发送按钮、focus 边、artifact 链接箭头、running 状态、ask-opt hover |
| `--cx-accent` | `#f0824a` | 橙：品牌点、AI 头像字、工具名(tool-name)、头像渐变(**新增，全仓无**) |
| `--cx-green` | `#34d399` | diff +、tool ok 状态点 |
| `--cx-red` | `#f87171` | diff −、tool err、stop 按钮渐变 |

### 1.5 派生 / 半透明（散落用，集中定义以便复用）
| Token | 值 | 来源 |
|---|---|---|
| `--cx-brand-soft` | `rgba(90,120,255,.06)` | ask-card 底(行 341) |
| `--cx-brand-line` | `rgba(90,120,255,.25)` | ask-card 边(行 342) |
| `--cx-brand-focus` | `rgba(90,120,255,.5)` | 输入卡 focus 边(行 430) |
| `--cx-brand-run` | `rgba(90,120,255,.18)` | running 状态点底(行 299) |
| `--cx-green-soft` | `rgba(52,211,153,.15)` | ok 状态点底(行 298) |
| `--cx-red-soft` | `rgba(248,113,113,.18)` | err 状态点底(行 300) |
| `--cx-accent-grad` | `linear-gradient(135deg,#f0824a 0%,#d96a30 100%)` | 用户头像(行 116) |
| `--cx-stop-grad` | `linear-gradient(135deg,#ef4444 0%,#dc2626 100%)` | 中断按钮(行 510) |

### 1.6 字体
```css
--cx-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;  /* 行 29 */
--cx-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;  /* 行 23 */
```
正文 `font-size:14px; line-height:1.6`(行 30–31)。assistant 正文 `line-height:1.7`(行 213)。

---

## 2. 排版尺度（实测抽取）

### 2.1 字号阶梯（mockup 实际只用这些值）
| 级别 | px | 出现处 |
|---|---|---|
| 微 | `11` | session-label、artifact-card meta、tool-section-label、input-meta 弱 |
| 小弱 | `11.5` | header-pill、tool-args code、tool-duration、small-btn、preview 正文 |
| 小 | `12` / `12.5` | input-attach-chip(12) / 工具卡多数文本(12.5) |
| 基准 | `13` | 会话项、新会话、tool-head、artifact 名、面板标题 |
| 正文 | `14` | body、chat-title、输入框、用户气泡 |
| 标题 | `16` | preview h1 |
> 结论：Codex 字号阶梯 = **11 / 11.5 / 12.5 / 13 / 14 / 16**。落地建议固化成 `--cx-fs-micro:11; --cx-fs-xs:11.5; --cx-fs-sm:12.5; --cx-fs-base:13; --cx-fs-md:14; --cx-fs-lg:16`。等宽块统一 `12`(tool pre 行 333)。

### 2.2 行高
- body `1.6`；assistant 正文 `1.7`；代码 pre `1.55`(行 335)；preview `1.65`(行 577)。

### 2.3 字重
- `400`(folder 路径、attach name) / `500`(标题、ask-q、artifact 名、面板标题) / `600`(brand、头像字、tool 无)。三档，不用 700。

### 2.4 间距尺度（padding/gap 实测）
高频值：`4 / 6 / 8 / 10 / 12 / 16 / 24`px。
- 卡内 padding：tool-head `8/12`、tool-body `12`、ask-card `12/14`、artifact-link `10/12`、用户气泡 `12/16`。
- 区域 padding：sidebar `16/12`、chat-header `12/24`、messages `24/0`、input-area `16/24/20`、artifacts-header `14/18`、artifact-preview `16/18`。
- 消息流：`.msg max-width:760px; margin:0 auto 24px; padding:0 24px`(行 182–185)。输入卡同宽 `760px`(行 422)。
- gap：图标行多用 `gap:10` 或 `gap:6/8/12`。

### 2.5 圆角（实测，零散）
| px | 处 |
|---|---|
| `2` | 品牌方点 |
| `3` | tool-args code、header-pill(4) |
| `4` | header-pill、icon-btn、滚动条 |
| `5` | small-btn |
| `6` | 会话项、attach-chip、input chip、tool pre、artifact-card(7) |
| `8` | 新会话、tool-call 卡、input-icon-btn、send-btn、artifact-link |
| `10` | ask-card |
| `12` | 用户气泡 |
| `14` | 输入卡、ask-opt(胶囊感) |
| `50%` | 头像、状态点、typing dots |
> 阶梯：`--cx-r-xs:4; --cx-r-sm:6; --cx-r-md:8; --cx-r-lg:12; --cx-r-xl:14; --cx-r-full:50%`。

### 2.6 阴影
mockup **几乎不用阴影**(纯描边分层)。唯一“浮起”用 `transform: translateY(-1px)`(send-btn hover，行 508)。命令面板/下拉等浮层需新增阴影(mockup 无)，建议 `--cx-shadow-pop: 0 16px 48px rgba(0,0,0,.6), 0 0 0 .5px rgba(255,255,255,.08)`(对齐 Codex 深色浮层)。

### 2.7 过渡
统一 `0.15s`(背景/边框/transform)。会话项更快 `0.1s`(行 97)。toggle 箭头 `transform .15s`(行 304)。

### 2.8 滚动条（行 178–179）
```css
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-thumb { background: var(--cx-border-hi); border-radius: 4px; }
/* track 透明 */
```

---

## 3. 组件样式规格（逐组件，可照抄）

### 3.1 三栏布局（行 37–42）
`display:grid; grid-template-columns:240px 1fr 380px; height:100vh; overflow:hidden`。
- 左 240(sidebar `--cx-bg-1`，右边框)、中 1fr(`--cx-bg-0`)、右 380(产物面板 `--cx-bg-1`，左边框)。
- **Code 模式映射**：左=会话栏；中=对话流；右=四面板(审查/终端/浏览器/文件)的容器。380 可调宽(现有 CodingPage 有树可拖宽逻辑，沿用)。

### 3.2 会话项 session-item（行 88–103）
`padding:7/10; radius:6; color:--cx-text-2; font:13; 单行省略`。hover→`bg-hover`；active→`bg:--cx-bg-3; color:--cx-text-1`。分组 label：`font:11; color:--cx-text-3; uppercase; letter-spacing:.4px; padding:6/8/4`。

### 3.3 工具调用卡 tool-call（行 247–336）★核心
- 容器：`border:--cx-border; radius:8; bg:--cx-bg-1; overflow:hidden`。hover→`border-color:--cx-border-hi`。
- head(行)：`flex; gap:10; padding:8/12; cursor:pointer; font:13`。结构：`icon(13) · tool-name · tool-args(flex:1省略) · duration · status点 · toggle▶`。
- `tool-name`：`--cx-mono; 12.5; color:--cx-accent`(橙)。
- `tool-args code`：`--cx-mono; 11.5; bg:rgba(255,255,255,.04); padding:1/6; radius:3`。
- `duration`：`--cx-mono; 11.5; color:--cx-text-3`。
- 状态点 `14×14 圆`：ok=`--cx-green-soft`底/`--cx-green`字；run=`--cx-brand-run`底/`--cx-brand`字；err=`--cx-red-soft`底/`--cx-red`字。
- toggle 箭头：`color:--cx-text-3; 10px`；展开态(`.expanded`)`rotate(90deg)`。
- body(展开)：`display:none→block; border-top:--cx-border; padding:12; bg:--cx-bg-sunken`。内含 `tool-section`(label uppercase 11 + `pre`)。`pre`: `bg:--cx-bg-0; border:--cx-border; radius:6; --cx-mono 12; line-height:1.55; overflow-x:auto`。
> **Code 模式复用**：读取/写入/run_python 工具卡直接用此规格。**diff 富 input**(harness 已带红绿)渲到 body pre 内，+ 行用 `--cx-green`、− 行用 `--cx-red`。

### 3.4 diff 卡（Codex「已编辑 N 个文件 +X −Y」——mockup 未画，按观察新建，复用 tool-call 骨架）
- 用 §3.3 容器；head 左侧文案「已编辑 N 个文件」+ 右侧 `+X`(green) `−Y`(red) + 「撤销↩ / 审核」按钮(用 §3.10 small-btn 样式)。
- 展开后每文件一行：`路径(--cx-text-2, mono 12.5) · 右侧 +N(green)/−M(red)`。末行「再显示 N 个文件 ⌄」= `--cx-text-3` 可点。
- **数据源**：已有 changes / file-diff 路由(见 CodingPage 现有「本轮改动」机制，git 基线)。

### 3.5 用户气泡 / AI 消息（行 181–216）
- user：`flex; justify-content:flex-end`；气泡 `bg:--cx-bg-2; border:--cx-border; radius:12; padding:12/16; max-width:85%; width:fit-content; margin-left:auto`。
- assistant：`flex; gap:12`；头像 `28×28 圆; bg:--cx-bg-3; border:--cx-border; color:--cx-accent; font:11/600`；bubble `flex:1; line-height:1.7; 段落 margin 0 0 12`。

### 3.6 附件 chip（气泡内 行 219–244 / 输入内 行 432–456）
- 气泡内 attach-chip：`inline-flex; gap:8; padding:5/10/5/8; bg:rgba(255,255,255,.04); border:--cx-border; radius:6; font:12.5; color:--cx-text-2`，name 省略(max 280)。
- 输入内 input-attach-chip：`bg:--cx-bg-3; border:--cx-border; radius:6; padding:3/6/3/8; font:12; color:--cx-text-1` + `×` 删除按钮(`color:--cx-text-3`)。

### 3.7 ask_user 澄清卡（行 338–371）
`bg:--cx-brand-soft; border:--cx-brand-line; radius:10; padding:12/14`。问句 `font:500`。选项 `ask-opt`：`bg:--cx-bg-2; border:--cx-border-hi; radius:14(胶囊); padding:5/12; font:12.5`；hover→`bg:--cx-brand; border:--cx-brand; color:#fff`。
> Code 已有 ask_clarifying_question，直接套此卡。

### 3.8 artifact 链接 / 卡（行 373–391 / 549–569）
- 消息内 artifact-link：`flex; gap:10; bg:--cx-bg-2; border:--cx-border-hi; radius:8; padding:10/12`；hover→`border:--cx-brand; bg:--cx-bg-3`。结构 `icon(18) · 名(13/500)+meta(11.5/text-3) · 「查看 →」(--cx-brand 12.5)`。
- 面板内 artifact-card：`padding:9/11; radius:7`；hover→`bg-hover`；active→`bg:--cx-bg-3`。

### 3.9 typing 指示（行 393–413）
`inline-flex; gap:10`；三点 `6×6 圆; bg:--cx-text-3`，`@keyframes pulse 1.4s`(opacity .3↔1，delay -.16/-.32s)；meta `--cx-text-3 12`，文案「AI 思考中 · Ns · 已调用 N 个工具」。

### 3.10 输入区（行 415–522）★核心
- input-area：`border-top:--cx-border; padding:16/24/20; bg:--cx-bg-0`。
- input-card：`max-width:760; margin:0 auto; bg:--cx-bg-2; border:--cx-border-hi; radius:14; padding:8`；focus-within→`border:--cx-brand-focus`。
- input-row：`flex; align-items:flex-end; gap:6; padding:4/4/4/8`。
- input-icon-btn(＋/麦克风)：`32×32; radius:8; color:--cx-text-2; font:16`；hover→`bg-hover; color:--cx-text-1`。
- textarea：`flex:1; transparent; 无边; color:--cx-text-1; font:14; line-height:1.5; min-h:22; max-h:160; padding:6/8`；placeholder `--cx-text-3`。
- send-btn：`32×32; radius:8; bg:--cx-brand; color:#fff`；hover→`translateY(-1px)`；`.stop`→`--cx-stop-grad`(红渐变，方块 icon)。
- input-meta：`flex; gap:8; padding:4/12/0; color:--cx-text-3; font:11.5`，`model-tag`=`--cx-mono; --cx-text-2`，`·` 分隔。
> **Codex 增项(mockup 无，后续 Phase 加)**：访问模式 chip(⚠️橙 `--cx-accent` 完全访问)、模型选择器(⚡)。这些放 input-row 左侧或 meta 行，复用 §3.6 chip 样式 + `--cx-accent` 警示色。

### 3.11 按钮族
- icon-btn(header)：`transparent; color:--cx-text-2; padding:4/6; radius:4`；hover→`bg-hover; color:--cx-text-1`。
- small-btn：`bg:--cx-bg-2; border:--cx-border; color:--cx-text-2; padding:4/10; radius:5; font:11.5`；hover→`color:--cx-text-1; border:--cx-border-hi`。
- new-session：`bg:--cx-bg-3; border:--cx-border; radius:8; padding:8/12; font:13; text-align:left`；hover→`bg-hover`。
- header-pill(模型标签)：`bg:--cx-bg-2; border:--cx-border; padding:3/10; radius:4; --cx-mono 11.5`。

### 3.12 头部栏（行 132–171）
chat-header：`padding:12/24; border-bottom:--cx-border; flex space-between`。title `14/500`，folder 前缀 `--cx-text-3/400`。actions `gap:12; color:--cx-text-3; 12`。
> Codex 右上角全屏/最小化/布局切换 = 三个 icon-btn(§3.11) 放 actions 区。

### 3.13 命令面板浮层（mockup 无，新建，对齐截图）
- 容器：`bg:--cx-bg-2; border:--cx-border-hi; radius:12; padding:6; box-shadow:--cx-shadow-pop`。
- 行：`flex; gap:10; padding:8/10; radius:8; font:13`；hover→`bg-hover`。结构 `icon · 名(--cx-text-1) · flex spacer · 快捷键chip`。
- 快捷键 chip：`bg:--cx-bg-3; border:--cx-border; --cx-mono 11; padding:2/6; radius:4; color:--cx-text-3`(如 ⌃⇧G / ⌘T / ⌘P / ⌥⌘S)。
- 条目：审查/终端/浏览器/文件/侧边聊天 → 映射到右侧四面板切换。

### 3.14 文件/代码面板（mockup 仅有 md preview 行 571–603，代码面板按截图+复用现有 FileTree/CodeViewer）
- 顶部 tab 条：每 tab `flex; padding:6/10; radius:6 6 0 0(顶角); font:12.5`，active=`bg:--cx-bg-0`、其余 `--cx-text-3`；末尾 `＋` 新建 tab(input-icon-btn 缩小版)。
- 面包屑：`--cx-text-3 11.5`，分隔 `›`，末段文件名 `--cx-text-2`；右侧 `…` / 「打开」下拉 / 复制 = icon-btn。
- 代码区：行号 `--cx-text-3 --cx-mono`；底 `--cx-bg-0`；语法高亮沿用现有 CodeViewer(highlight.js/shiki)，但底色覆写为 `--cx-bg-0`、文字 `--cx-text-1`。
- 右侧文件树:「筛选文件…」输入(input-card 缩小版) + 树(文件夹/文件 icon + 彩色类型角标)。沿用现有 FileTree 的 M/A/D 徽标(green/blue/red 用 `--cx-green/--cx-brand/--cx-red`)。
- preview(md，行 571–603)：`--cx-mono 12; line-height:1.65; color:--cx-text-2`；h1/h2/h3 用 sans + `--cx-text-1`(16/14/13)；表格 `border:--cx-border-hi; td/th padding:4/8`，th `bg:--cx-bg-3`。

---

## 4. Codex Token ↔ 现有变量 映射表

> 原则：Code 模式**新增 `--cx-*`**，不动现有。下表给出「若想复用现有暗色 token」的对应关系，供逐步收敛参考。差异大的标注 ⚠️ 不建议直接复用。

| Codex token | 值 | theme-vars.css(dark) 最近邻 | design-v3(dark) 最近邻 | 建议 |
|---|---|---|---|---|
| `--cx-bg-0` #0a0a0c | 最深 | `--t-bg-base` #090b10 ✅近 | `--bg` #0B1224 ⚠️偏蓝 | 复用 `--t-bg-base` 可，但 Codex 更中性黑→建议独立 |
| `--cx-bg-1` #111114 | 面板 | `--t-bg-panel` #111318 ✅近 | `--surface` #131A2E ⚠️蓝 | 近 `--t-bg-panel` |
| `--cx-bg-2` #16171b | 抬升 | `--t-bg-elevated` #171a21 ✅近 | `--surface-2` ⚠️ | 近 `--t-bg-elevated` |
| `--cx-bg-3` #1d1e23 | hover底 | `--t-bg-panel-hover` #1a1d24 ✅近 | `--surface-3` ⚠️ | 近 `--t-bg-panel-hover` |
| `--cx-bg-hover` rgba(255,255,255,.04) | = | `--t-bg-subtle` 同值 ✅ | — | 直接等价 |
| `--cx-border` rgba(255,255,255,.06) | = | `--t-border-subtle` rgba(148,163,184,.14) ⚠️偏蓝灰且更亮 | `--line` rgba(255,255,255,.07) ✅几乎相同 | 复用 `--line` 最贴 |
| `--cx-border-hi` rgba(255,255,255,.1) | = | `--t-border-strong` ⚠️ | `--line-strong` rgba(255,255,255,.13) ✅近 | 近 `--line-strong` |
| `--cx-text-1` #e8eaed | 主 | `--t-text-primary` rgba(248,250,252,.94) ✅近 | `--text` #E8EEFB ⚠️偏蓝 | 近 `--t-text-primary` |
| `--cx-text-2` #a1a4ad | 次 | `--t-text-secondary` ✅近 | `--text-2` #A8B4D0 ⚠️蓝 | 近 `--t-text-secondary` |
| `--cx-text-3` #6c707a | 弱 | `--t-text-muted` ⚠️更淡 | `--text-3` #6F7DA0 ⚠️蓝 | 近 `--text-3`(中性度稍差) |
| `--cx-brand` #5a78ff | 蓝紫 | `--t-brand` #7c8cff ⚠️更亮更紫 | `--brand` #60A5FA ⚠️更天蓝 | **差异明显→独立**(Codex 偏靛蓝紫) |
| `--cx-accent` #f0824a | 橙 | ❌ 无 | ❌ 无 | **必须新增** |
| `--cx-green` #34d399 | 绿 | `--t-success` #34d399 ✅完全相同 | `--ok` #34D399 ✅相同 | 直接复用任一 |
| `--cx-red` #f87171 | 红 | `--t-danger` #f87171 ✅相同 | `--err` #F87171 ✅相同 | 直接复用任一 |
| `--cx-mono` ui-monospace 栈 | | `--font-mono`(Geist Mono → ui-monospace) ⚠️先 Geist | 同 | 可复用 `--font-mono`；要纯 Codex 观感则独立指 ui-monospace |
| `--cx-sans` 系统栈 | | `--font-sans`(Geist Sans → 系统) | 同 | 复用 `--font-sans` 即可 |

**结论**：
- 绿/红/sans 字体 → 直接复用现有(`--t-success`/`--t-danger`/`--font-sans`)。
- bg 系列、border、text → 与现有 dark token 数值接近但**色相不同**(现有偏蓝)。Codex 是中性偏冷灰黑。**建议独立定义 `--cx-*`** 以保住 Codex 中性观感，不要硬塞进 `--t-*`。
- `--cx-brand`(靛蓝紫)、`--cx-accent`(橙) → **现有体系无等价**，必须新增。

---

## 5. 落地 token 块（可直接放入新文件）

建议新建 `frontend/src/styles/codex-tokens.css`，在 `main.ts` 于 `design-v3-tokens.css` **之后** import(确保不被覆盖)。作用域用 `.coding-codex`(不污染全局)：

```css
/* codex-tokens.css — Code 模式专用 Codex 风格 token。作用域隔离，不影响其它页面。 */
.coding-codex {
  /* surfaces */
  --cx-bg-0:#0a0a0c; --cx-bg-1:#111114; --cx-bg-2:#16171b; --cx-bg-3:#1d1e23;
  --cx-bg-hover:rgba(255,255,255,.04); --cx-bg-sunken:rgba(0,0,0,.25);
  /* borders */
  --cx-border:rgba(255,255,255,.06); --cx-border-hi:rgba(255,255,255,.1);
  /* text */
  --cx-text-1:#e8eaed; --cx-text-2:#a1a4ad; --cx-text-3:#6c707a;
  /* brand / accent / status */
  --cx-brand:#5a78ff; --cx-accent:#f0824a; --cx-green:#34d399; --cx-red:#f87171;
  /* derived */
  --cx-brand-soft:rgba(90,120,255,.06); --cx-brand-line:rgba(90,120,255,.25);
  --cx-brand-focus:rgba(90,120,255,.5); --cx-brand-run:rgba(90,120,255,.18);
  --cx-green-soft:rgba(52,211,153,.15); --cx-red-soft:rgba(248,113,113,.18);
  --cx-accent-grad:linear-gradient(135deg,#f0824a 0%,#d96a30 100%);
  --cx-stop-grad:linear-gradient(135deg,#ef4444 0%,#dc2626 100%);
  /* fonts */
  --cx-sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  --cx-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
  /* type scale */
  --cx-fs-micro:11px; --cx-fs-xs:11.5px; --cx-fs-sm:12.5px; --cx-fs-base:13px; --cx-fs-md:14px; --cx-fs-lg:16px;
  /* radii */
  --cx-r-xs:4px; --cx-r-sm:6px; --cx-r-md:8px; --cx-r-lg:12px; --cx-r-xl:14px;
  /* shadow (浮层用，mockup 无，对齐 Codex 深色) */
  --cx-shadow-pop:0 16px 48px rgba(0,0,0,.6),0 0 0 .5px rgba(255,255,255,.08);
  /* motion */
  --cx-ease:0.15s; --cx-ease-fast:0.1s;
  /* 强制本作用域为深色基底，不随全局明暗 */
  background:var(--cx-bg-0); color:var(--cx-text-1);
  font-family:var(--cx-sans); font-size:var(--cx-fs-md); line-height:1.6;
}
.coding-codex ::-webkit-scrollbar{width:8px;}
.coding-codex ::-webkit-scrollbar-thumb{background:var(--cx-border-hi);border-radius:4px;}
.coding-codex ::-webkit-scrollbar-track{background:transparent;}
```

---

## 6. 与现有主题的集成 / 落地方案

**方案 B(推荐)：作用域隔离，固定深色。** CodingPage 根容器加 class `coding-codex`，Codex token 只在该子树生效。优点：(1) 不依赖全局 `data-theme`，light 模式下 Code 模式仍 Codex 深色(符合 Codex 单一深色观感)；(2) 零污染其它页面/Builder/配置面板；(3) 现有 CodingPage 的 `--t-*` 引用可保留过渡期，逐组件迁移到 `--cx-*`。

迁移策略：
- 第一刀只改新写的 Codex 组件(工具卡/diff卡/输入区/命令面板/四面板 tab)，全用 `--cx-*`。
- 现有 CodingPage 旧 CSS(`CodingPage.styles.css` 用 `--t-*`)可后续逐块替换；过渡期两套并存不冲突(前缀不同)。
- Element Plus 组件在 Code 模式内若需深色，沿用现有 `element-plus/theme-chalk/dark/css-vars.css`(已 import)，但注意：light 全局态下 EP 默认 light，需要在 `.coding-codex` 内补 EP 深色变量覆写(单独小块，后续 Phase 处理)。

**冲突核查结论**：`--cx-*` 前缀在全仓 grep 0 命中(全新)；`--accent` 0 命中(可安全新增为 `--cx-accent`)；`--bg-0/1/2/3`、`--text-1/2/3`、`--mono` 这些 mockup 裸名**在现有体系部分已被占用**(如 design-v3 有 `--text-2/3`、theme-vars 有 `--mono` 通过 `--font-mono`)——**因此必须加 `--cx-` 前缀，禁止照搬 mockup 裸 token 名**，否则会与 design-v3 的 `--text-2/--text-3` 撞名(值不同→串色)。

---

## 7. 给后续 Phase 的引用清单
- **Phase 审查**：用 §3.4 diff 卡 + §3.3 tool-call 骨架；数据=现有 changes/file-diff。
- **Phase 终端**：输出区用 §3.3 body `pre`(`--cx-bg-0` + `--cx-mono`)；数据=`/serve-logs` SSE + `get_runtime_errors`(错误行 `--cx-red`)。
- **Phase 浏览器**：面板容器用 §3.1 右栏；地址/工具条用 §3.12 + §3.11；数据=`start_serve` 返回 URL。
- **Phase 文件**：§3.14 tab+面包屑+代码区+文件树；复用现有 FileTree/CodeViewer，底色覆写 `--cx-bg-0`。
- **命令面板**：§3.13；条目映射四面板切换 + 侧边聊天。
- **输入区 Codex 增项**：§3.10 末尾(访问模式 chip 用 `--cx-accent`、模型选择器)。