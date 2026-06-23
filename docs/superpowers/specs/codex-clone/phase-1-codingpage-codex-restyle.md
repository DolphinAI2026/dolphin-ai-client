# Phase 1: CodingPage 中间对话主工作区 Codex 风格 restyle

# Phase 1 — 中间对话主工作区 Codex restyle 设计 spec

## 0. 关键现状(读码确认)

中间对话流不是一坨手写 HTML,而是 **`AgentConversation`(共享组件) + `#custom` slot 里的 5 类特殊卡** 拼起来的:

| 区域 | 渲染者 | 关键 class |
|---|---|---|
| 会话头 | CodingPage 模板 `<header class="coding-session-header">` | `.coding-session-kicker` / `.coding-session-title` / `.coding-chat-actions` / `.cca-btn` |
| AI 消息(裸 markdown) | `AgentConversation` | `.ac-row.assistant` / `.ac-bubble.assistant-naked` / `.ac-text` / `.ac-avatar.brand` |
| 用户消息(右气泡) | `AgentConversation` | `.ac-row.user` / `.ac-bubble.user-bubble` / `.ac-user-tag` / `.ac-attach-chip` |
| 工具卡 | `AgentConversation` → `ToolCard.vue` | `.tool-card` / `.tc-head` / `.tc-status-label` / `.tc-name` / `.tc-toggle` / `.tc-body pre` |
| 工具分组 | `AgentConversation` | `.ac-tool-group` / `.ac-tool-head` / `.ac-group-count` |
| ask 澄清卡 | `AgentConversation` | `.ac-ask-card` / `.ac-ask-q` / `.ac-ask-opt` |
| diff/新建文件卡 | `FileCard.vue`(#custom) | `.msg-file-card` / `.file-card-header` / `.fc-diff-line.fc-add/fc-del` / `.fc-stat-add/del` |
| 命令卡 | CodingPage 模板(#custom) | `.msg-command-card` / `.command-prompt` / `.command-output` |
| 思考链卡 | CodingPage 模板(#custom) | `.msg-reasoning-card` / `.mrc-head` / `.mrc-body` |
| 开发 SPEC 卡 | CodingPage 模板(#custom) | `.msg-spec-card`(复用 `.mrc-*`) |
| run 运行卡 | CodingPage 模板(#custom) | `.coding-run-card` / `.rc-head` / `.rc-dot.ok/error/running` / `.rc-link` / `.rc-url` / `.rc-errs`(样式在 **CodingPage.global.css:473-484**,用旧 `--line/--surface-2/--text-1` 老 token!) |
| typing 指示器 | `AgentConversation` | `.ac-typing-row` / `.ac-typing span` / `.ac-typing-secs` |
| 输入区 | `UnifiedChatComposer`(`.ucc-*`) + CodingPage footer slot | `.chat-input-bar` / `.ucc-box` / `.ucc-input` / `.ucc-send` / `.coding-model-picker` / `.coding-token-usage` / `.coding-queue-banner` / `.ctx-warn-banner` |

主题 token 定义在 `frontend/src/styles/theme-vars.css`:`html[data-theme="dark"]` 已是 `--t-bg-base:#090b10` / `--t-brand:#7c8cff` / `--t-success:#34d399` / `--t-danger:#f87171` —— **跟 Codex 调色板已经非常接近**。所以 restyle 不是重写组件,而是 **token 重映射 + 局部微调**。

## 1. 总策略:作用域 skin + token 桥接

**不改任何 .vue 模板的数据逻辑、不动 props、不改组件结构。** 在 CodingPage 根容器加一个 skin 类,在该作用域内重新声明 token 值,让所有子组件(含 `:deep()` 的共享组件)继承新值。

### 1.1 挂 skin 类
`CodingPage.vue` 模板 `<div class="coding-body" :class="{ 'code-first': codeFirst }">` → 追加 `'codex-skin': true`(或 `codeFirst` 时才挂,二选一由实现时定;建议恒挂,Code 模式整页统一)。

### 1.2 token 桥接表(写进 CodingPage.styles.css 顶部新段 `/* ===== Codex skin token bridge ===== */`)
仅在 `.coding-body.codex-skin` 作用域内覆盖,**不污染全局**、不影响 Builder/AIChat:

```
.coding-body.codex-skin {
  /* Codex 原始 token,供新写样式直接引用 */
  --cx-bg-0:#0a0a0c; --cx-bg-1:#111114; --cx-bg-2:#16171b; --cx-bg-3:#1d1e23;
  --cx-border:rgba(255,255,255,.06); --cx-border-hi:rgba(255,255,255,.1);
  --cx-text-1:#e8eaed; --cx-text-2:#a1a4ad; --cx-text-3:#6c707a;
  --cx-brand:#5a78ff; --cx-accent:#f0824a; --cx-green:#34d399; --cx-red:#f87171;
  --cx-mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;

  /* 把现有 --t-* / 老 --bg/--line 全部重映射到 Codex 值 —— 子组件无感切肤 */
  --t-bg-base:var(--cx-bg-0); --t-bg-panel:var(--cx-bg-1); --t-bg-panel-hover:var(--cx-bg-3);
  --t-bg-elevated:var(--cx-bg-1); --t-bg-nav:var(--cx-bg-0); --t-bg-code:#000;
  --t-bg-soft:var(--cx-bg-2); --t-text-primary:var(--cx-text-1);
  --t-text-secondary:var(--cx-text-2); --t-text-muted:var(--cx-text-3);
  --t-border-subtle:var(--cx-border); --t-border-soft:var(--cx-border);
  --t-brand:var(--cx-brand); --t-brand-text:var(--cx-brand); --t-brand-subtle:rgba(90,120,255,.12);
  --t-success:var(--cx-green); --t-danger:var(--cx-red); --t-warning:var(--cx-accent);
  /* run-card 老 token */
  --line:var(--cx-border); --surface-2:var(--cx-bg-1);
  --text-1:var(--cx-text-1); --text-2:var(--cx-text-2); --text-3:var(--cx-text-3);
  --brand:var(--cx-brand); --ok:var(--cx-green); --err:var(--cx-red);
  background:var(--cx-bg-0); color:var(--cx-text-1);
}
```

> 桥接后,`ToolCard`/`FileCard`/`AgentConversation` 里那些 `rgba(116,128,171,…)` **硬编码灰**(占了相当一部分)不会自动变 —— 见 §3 逐组件补丁。但状态色/背景/边框/文字主色立即贴稿。

## 2. 逐区域设计(class → 新样式)

### 2.1 会话头 `.coding-session-header`(对齐 mockup `.chat-header`)
- 背景 `--cx-bg-0`,下边框 `1px solid --cx-border`,`min-height:48px`,`padding:12px 24px`。
- `.coding-session-kicker`(代码工作区):改成 mockup 的 `.title-folder` 灰色弱化 —— `color:var(--cx-text-3); font-weight:400; font-size:13px`,与标题同一行用 `/` 分隔的观感(当前是上下两行;Phase 1 保持两行结构,只调色,**不强行重排**避免改模板)。
- `.coding-session-title` → `font-size:14px; font-weight:500; color:var(--cx-text-1)`。
- 右侧 `.coding-chat-actions .cca-btn` → 对齐 mockup `.icon-btn`:`color:var(--cx-text-2); border:none; bg transparent; hover→bg var(--cx-bg-3)`。
- 模型展示若放头部,用 mockup `.header-pill`:`bg var(--cx-bg-2); border var(--cx-border); font-family var(--cx-mono); font-size:11.5px; radius:4px`(本项目模型选择在底部输入区,头部可不放,保持现状)。
- **新增(可选,贴 Codex 截图右上三控件)**:Tauri 壳已有窗口控件,Phase 1 不在对话区重复造,**标注为非目标**。

### 2.2 AI 消息 `.ac-row.assistant`
- `.ac-avatar.brand`:mockup 是圆形 28px、`bg var(--cx-bg-3)`、边框 `--cx-border`、文字 `--cx-accent`、内容 "AI"。当前是方形蓝实底 "A"。**改 `:deep()` 覆盖**:`border-radius:50%; background:var(--cx-bg-3)!important; color:var(--cx-accent)!important; border:1px solid var(--cx-border); font-size:11px`。(内容 "A" vs "AI" 不改,免动组件。)
- `.ac-bubble.assistant-naked .ac-text`:文字色 `--cx-text-1`,行高 1.7;`:deep(p)` 间距 `0 0 12px`;`:deep(pre)` → `bg #000; border 1px var(--cx-border); radius:6px; font-family var(--cx-mono)`;`:deep(code:not(pre code))` → `bg rgba(255,255,255,.04)`。
- `.ac-feedback .ac-fb-btn`:`color var(--cx-text-3); hover bg var(--cx-bg-3) color var(--cx-text-1)`。

### 2.3 用户消息 `.ac-row.user`
- `.ac-bubble.user-bubble`:mockup `bg var(--cx-bg-2); border 1px var(--cx-border); radius:12px; padding:12px 16px`(当前是半透明紫底)。`:deep()` 覆盖背景与边框。
- `.ac-user-tag`("我"圆头像):mockup 用户侧无头像、靠右对齐即可;Phase 1 保留头像但调色 `bg var(--cx-bg-3); color var(--cx-text-2)`,或 `display:none` 更贴稿(实现时二选一,建议隐藏更像 Codex)。
- `.ac-attach-chip`(附件):对齐 mockup `.attach-chip` → `bg rgba(255,255,255,.04); border 1px var(--cx-border); radius:6px; color var(--cx-text-2); padding:5px 10px 5px 8px`。

### 2.4 工具卡 `ToolCard.vue`(对齐 mockup `.tool-call`)
mockup 状态点是「绿圆点 ✓」在右侧,本项目是「已完成 · 读取 X · 工具调用 · 0.3s ›」一行文字状态。**保留本项目信息密度更高的文字状态,只改色**:
- `.tool-card`:`bg var(--cx-bg-1); border 1px var(--cx-border); radius:8px`(当前 pill 999px → 改 8px 更像 Codex 卡)。`hover` border `--cx-border-hi`。
- `.tc-status-label.success`→`var(--cx-green)`;`.error`→`var(--cx-red)`;`.running`→`var(--cx-brand)`。这些已用 `--ok/--err/--info` token,桥接后自动生效,**但硬编码的 `rgba(116,128,171,…)` 灰(`.tc-sep/.tc-args/.tc-meta/.tc-duration/.tc-toggle`)要改成 `var(--cx-text-3)`**。
- `.tc-name`:`color var(--cx-accent); font-family var(--cx-mono)`(mockup `.tool-name` 橙色 mono)。
- `.tc-body pre`:`bg #000; border 1px var(--cx-border); color var(--cx-text-1); font-family var(--cx-mono)`。
- `.tc-section-label`:`color var(--cx-text-3); text-transform:uppercase; letter-spacing:.4px`(已是)。
- **补丁方式**:这些是 ToolCard scoped 样式,CodingPage 改不到 → 见 §3.1。

### 2.5 工具分组 `.ac-tool-group`
- `bg var(--cx-bg-1); border 1px var(--cx-border); radius:8px`;`.ac-tool-name` 橙 `--cx-accent`;`.ac-group-count` chip → `bg rgba(90,120,255,.12); color var(--cx-brand)`。AgentConversation scoped,见 §3.2。

### 2.6 diff / 新建文件卡 `FileCard.vue`(对齐 Codex「已编辑 N 文件 +X -Y」)
- `.msg-file-card`:`bg var(--cx-bg-1); border 1px var(--cx-border); radius:8px`。
- `.file-card-header`:`font-family var(--cx-mono); hover bg var(--cx-bg-3)`。
- `.fc-stat-add`→`var(--cx-green)`;`.fc-stat-del`→`var(--cx-red)`(已用 `--t-success/--t-danger`,桥接后生效)。
- diff 行:`.fc-add` 背景 `color-mix(in srgb,var(--cx-green) 16%,transparent)`、文字 `--cx-green`;`.fc-del` 同理红。已用 token,桥接生效。
- `.file-card-code`:`bg #000; font-family var(--cx-mono)`。
- 行号 `.fc-ln`:`color var(--cx-text-3)`。
- FileCard scoped,见 §3.3。
- **Codex「撤销↩ / 审核」按钮 + 「再显示 N 个文件 ⌄」聚合卡**:本项目一个 file_write/edit = 一张独立 FileCard,没有「N 文件聚合卡」概念。Phase 1 **不新造聚合卡**(那是数据聚合,越界);标注为 Phase 2/审查面板候选。FileCard 头部的折叠 chevron 已具备「展开/收起」语义,贴稿够用。

### 2.7 命令卡 `.msg-command-card`
- `bg #000; border 1px var(--cx-border); radius:8px`;`.command-prompt` `$` → `var(--cx-green)`;`.command-text` `var(--cx-text-2)`;`.command-output` `var(--cx-text-3); font-family var(--cx-mono)`。(在 CodingPage.styles.css,直接改。)

### 2.8 思考链卡 `.msg-reasoning-card` + SPEC 卡 `.msg-spec-card`
- `.mrc-head`:`color var(--cx-text-3)`;`.mrc-body`:`border-left 2px solid var(--cx-border-hi); color var(--cx-text-3); font-style:italic`。
- SPEC 卡可参考 mockup `.ask-card` 的蓝调容器突出:Phase 1 仅给 `.msg-spec-card .mrc-body` 一个 `bg rgba(90,120,255,.06); border-left-color var(--cx-brand)`,与思考卡区分。(在 styles.css 直接改。)

### 2.9 ask 澄清卡 `.ac-ask-card`(对齐 mockup `.ask-card`)
- 容器:`bg rgba(90,120,255,.06); border 1px rgba(90,120,255,.25); radius:10px; padding:12px 14px`。
- `.ac-ask-q`:`font-weight:500; color var(--cx-text-1)`。
- `.ac-ask-opt`:`bg var(--cx-bg-2); border 1px var(--cx-border-hi); color var(--cx-text-1); radius:14px`;hover→`bg var(--cx-brand); border-color var(--cx-brand); color #fff`。AgentConversation scoped,见 §3.2。

### 2.10 run 运行卡 `.coding-run-card`(在 global.css,用老 token)
桥接里已补 `--line/--surface-2/--text-1/--brand/--ok/--err`,**自动贴肤**。额外微调:`.rc-dot.ok`→绿、`.error`→红、`.running` 可加脉冲;`.coding-run-card` `radius:8px; bg var(--cx-bg-1)`(global.css 里调或被桥接覆盖)。`.rc-url/.rc-errs` mono 已具备。

### 2.11 typing 指示器 `.ac-typing`
- 三点 `background var(--cx-text-3)`;`.ac-typing-secs` `color var(--cx-text-3)`(mockup `.typing-meta`)。AgentConversation scoped,见 §3.2。文案「AI 思考中 Ns」已有,贴稿。

### 2.12 输入区(对齐 mockup `.input-card`)
- `.chat-input-bar`:`bg var(--cx-bg-0); border-top 1px var(--cx-border); padding:16px 24px 20px`。
- `:deep(.ucc-box)`:`bg var(--cx-bg-2); border 1px var(--cx-border-hi); radius:14px; padding:8px`;`focus-within` border `rgba(90,120,255,.5)`。当前已有 `html:not([data-theme=dark])` 分支,需在 codex-skin 下统一覆盖(skin 是暗底,走暗分支即可,补 codex 值)。
- `:deep(.ucc-input)`:`color var(--cx-text-1)`;placeholder `var(--cx-text-3)`。
- `:deep(.ucc-send)`:`bg var(--cx-brand); radius:8px; 32x32`;`.is-stop` → 红渐变 `linear-gradient(135deg,#ef4444,#dc2626)`(mockup `.send-btn.stop`)。
- `.coding-model-picker .coding-model-trigger`:对齐 mockup `.input-meta .model-tag` 风格 —— 文字 `var(--cx-text-2); font-family var(--cx-mono); font-size:11.5px`;菜单 `.coding-model-menu` `bg var(--cx-bg-2); border var(--cx-border-hi); radius:8px`,`option:hover bg var(--cx-bg-3)`,`is-selected color var(--cx-brand)`(命令面板浮层观感)。
- `.coding-token-usage`:`color var(--cx-text-3); font-family var(--cx-mono)`(mockup `.input-meta`「已使用 12.3k tokens」)。`.lvl-warn`→`--cx-accent`,`.lvl-danger`→`--cx-red`。
- `.coding-queue-banner` / `.ctx-warn-banner`:`bg var(--cx-bg-1); border var(--cx-border); radius:10px; color var(--cx-text-2)`,danger 级用 `--cx-red`。

## 3. 需要新增/触达的子组件补丁(scoped 样式 CodingPage 改不到)

共享组件 scoped 样式里有大量 `rgba(116,128,171,…)` 硬灰,桥接 token 改不动它们。两条路,**推荐 A**:

### 3.1 ToolCard.vue —— 加可选 skin prop(推荐 A)或全局穿透(B)
- **A(干净,推荐)**:`ToolCard` 不动数据;在其 `<style scoped>` 末尾追加一段 `:global(.codex-skin) .tool-card { … }` 覆盖块,把硬灰 `rgba(116,128,171,…)` 处用 `var(--cx-text-3)`、name 用 `var(--cx-accent)`、卡片 radius 999px→8px、pre bg #000。因为是同一组件的 scoped 文件,`:global()` 选择器作用域安全。
- **B**:在 CodingPage.styles.css 用 `:deep(.tool-card)` 链覆盖(组件被 `:deep()` 能命中)。**B 更省事,优先用 B**(不改共享组件文件,符合「只改 CodingPage 呈现」边界)。

### 3.2 AgentConversation.vue —— 同 §3.1,用 CodingPage `:deep()` 覆盖
`.stream-pane :deep(.ac-avatar.brand)` / `:deep(.ac-bubble.user-bubble)` / `:deep(.ac-ask-opt)` / `:deep(.ac-tool-group)` / `:deep(.ac-typing span)` / `:deep(.ac-tool-name)` / `:deep(.ac-group-count)` 等,全部在 CodingPage.styles.css 的 `.coding-body.codex-skin` 段里写 `:deep()` 覆盖。**首选,零触达共享组件。**

### 3.3 FileCard.vue —— 同上,`:deep(.msg-file-card)` 链覆盖
diff/stat 色靠桥接 token 已生效,仅需覆盖 `bg/border/radius/mono/行号灰`。

> 结论:**Phase 1 可做到 0 改共享 .vue 文件**,全部走 CodingPage.styles.css 内 `.coding-body.codex-skin` 作用域(含 `:deep()`)+ token 桥接。唯一在 .vue 改的是 §1.1 一行 `:class`。这严格守住「不改数据逻辑只改呈现」边界。

## 4. 不改 / 越界(明确边界)
- 不改 `agentMessages` computed、`streamCustom`、SSE 流、`sendOrQueue`、模型逻辑、任何 props/emit。
- 不新造「N 文件聚合 diff 卡 + 撤销/审核按钮」(数据聚合,属审查面板/Phase 2)。
- 不在对话区造窗口控件(全屏/最小化/布局切换 = Tauri 壳职责)。
- 不动命令面板浮层、文件/代码面板、终端、浏览器(Phase 2-5)。
- 不引入新依赖、不改 light theme(skin 仅暗)。

## 5. 验收标准(可视觉核对,对照 aichat-mockup.html)
1. Code 模式整页底色 = `#0a0a0c`,会话头底 = 同色 + 顶细线。
2. AI 头像 = 圆形深灰底、橙字 "A/AI";AI 正文 mono 代码块为纯黑底 + 细灰边。
3. 用户消息 = 右对齐、`#16171b` 底 + 细边 12px 圆角气泡;附件 chip 半透明白底。
4. 工具卡:工具名 **橙色 mono**,状态字「已完成/失败/执行中」分别绿/红/蓝,卡片 8px 圆角、`#111114` 底,展开区 pre 纯黑底。
5. diff 卡:`+` 行绿底绿字、`-` 行红底红字,头部 `+N`/`-M` 绿/红统计,mono 字体。
6. ask 卡:蓝调半透明容器,选项 pill hover 变蓝实底白字。
7. run 卡:状态点绿/红/蓝,链接蓝色,URL/错误 mono。
8. 输入框:`#16171b` 圆角 14px 卡,聚焦蓝边;发送键蓝色圆角,流式时变红渐变方块停止键;模型/token 区为 mono 灰小字。
9. typing:三点灰 + 「AI 思考中 Ns」灰字。
10. 全程切到 Builder/AIChat 页面观感不变(skin 未泄漏);light/dark 全局切换不破坏(skin 强制暗底,文档需注明 Code 模式恒暗)。
11. `npm run build:nocheck` 通过;`CodingPage.token.spec.ts` / `CodingPage.styles` 关联测试不回归。

## 6. 实施顺序建议
1. §1 桥接段 + §1.1 挂类 → 立即 80% 贴肤(token 驱动的色全变)。
2. §3.2/3.1/3.3 的 `:deep()` 覆盖块清掉硬编码灰 + name 橙 + 卡片圆角 → 工具卡/diff/分组贴稿。
3. §2.7-2.9 命令/思考/SPEC/ask 卡微调(styles.css 直接改)。
4. §2.12 输入区。
5. 截图自测对照 mockup 逐条过验收。