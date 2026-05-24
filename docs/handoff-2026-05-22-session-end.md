# Handoff · 2026-05-22 session — Phase 3c/3d/4 + 多个 UX 修复

> 上接 [handoff-2026-05-21-evening-session-end.md](handoff-2026-05-21-evening-session-end.md)。
> HEAD `0fa4087` push origin/local/ui-redesign-2026-05-20。
> 本 session 34 commits / 37 files / +4746 / -825 (含同事 xhh 并行 2 commit + 我做 + 自己/夜班 admin UI 修复)。

## TL;DR

下次 session 接手 4 句话：

1. **Phase 3c Chrome Extension 实测打通** — 用户装了 aPaaS Builder Helper 扩展 (Dia/Chrome 都 ok), backend `ExtensionRouter` 接收 WS, `browser_list_pages` 返 `source: "extension"` 真在 Dia 操作用户真 Chrome (不需开 `--remote-debugging-port=9222`).
2. **Phase 3d MVP Browser viewport mini preview** — ConfigAssistantPanel 加实时 MJPEG 流嵌 agent 操作 viewport.
3. **Phase 4 #4 TabStrip Cmd+click 真开 chrome tab** + admin-spa 也加多 tab — 工作台 + 平台管理 sidebar 都改 `<a href>`, modifier key 让浏览器原生处理.
4. **多 P0 修**: SPEC 一气呵成 2 阶段拆 + 用户审核点 / artifact_id 引用模式省 token / iframe 优先 prompt / 切租户整页 reload / dark 模式跨 SPA 联动 / Element Plus dark token override / ChangePlan stub 按钮删 / admin-spa sidebar 下划线修.

---

## 关键架构 + 决策

### Phase 3c 现状 (完整通)
```
用户 Chrome (Dia / Google Chrome) 装 aPaaS Builder Helper extension v0.1.0
  ↓ WebSocket
backend /ws/browser-ext (ExtensionRouter 单例)
  ↓ ext_router.call(cmd, args)
chrome.tabs / chrome.scripting / chrome.debugger API
  → list_tabs / select_tab / snapshot / click / type / navigate /
    screenshot (chrome.tabs.captureVisibleTab) /
    start_recording / stop_recording

agent 调 browser_* 工具时:
  _browser_tool_via_ext_or_cdm("cmd", args)
    → if ext_router.is_connected: 走扩展 (return source:"extension")
    → else: fallback chrome-devtools-mcp + :9222 (扩展没装时)
```

工程量从立项 5-7 天压到实际 ~2-3h — 因为 2026-05-19 扩展骨架 + WS endpoint 都早写好, 本 session 只补 screenshot/list/select 3 工具 prefer-ext + 安装文档 + 扩展端 select_tab cmd.

### Phase 3d Browser viewport mini preview MVP
backend `browser_viewport_stream.py` 起 MJPEG 端点 `/api/browser-viewport/mjpeg`, frontend ConfigAssistantPanel 顶部加 `<img>` 标签直接 stream, agent 操作时浏览器 viewport 实时回放到 panel (默认 5fps).

### Phase 4 多 tab 整体设计

| | 工作台 frontend | 平台管理 admin-spa |
|---|---|---|
| Sidebar 元素 | `<a href>` ✓ | `<a href>` ✓ |
| TabStrip 元素 | `<a href>` ✓ | `<a href>` ✓ |
| Cmd+click 开新 chrome tab | ✓ | ✓ |
| TabStrip localStorage key | `ai-builder-tabs-v1` | `admin-tabs-v1` (隔离) |
| Tab list 刷新恢复 | ✓ localStorage | ✓ localStorage |
| Watch route.path → auto openTab | ✓ | ✓ (deep link) |
| Tab × 关闭 | ✓ | ✓ |
| Dark 模式联动 | localStorage 'theme' key + storage event | ✓ 联动 (本 session 修) |

### Dark 模式跨 SPA 联动机制
两个 SPA 用同 origin localStorage 共享 key `'theme'`. frontend themeStore 早有 storage event listener; admin-spa AdminLayout 本 session 补上 — 工作台切 dark → 写 localStorage → admin-spa iframe 收 event → 同步 applyTheme.

加 `admin-spa/src/styles/element-plus-dark.css` 把 Element Plus CSS variables (`--el-color-primary` 等) 在 dark mode 映射到 design-v3-token (`--brand` 等). 修 53 处 .vue 硬编码 hex (Element 默认色) dark 不切换的断裂问题. (53 处源头改成 token 是 P2 留尾)

---

## 本 session 完整 commit 列表 (34)

按时间顺序:

| 时间 | Commit | 内容 |
|---|---|---|
| 早上 | `6fe8010` | Phase 1 config-chat prompt 主动多步 + MAX_TURNS 15→25 |
| | `535f9f1` | Phase 2 plan 卡片 + hero CTA (Claude-in-Chrome 视觉) |
| | `4b55d1d` | Phase 3 立项文档 + gap 重估 |
| | `25d8bb2` | handoff 230 行 |
| | `9737e4b` | online-coding workspace 404 silent toast |
| | `f42fd48` | asyncio.shield 包 db.commit 防 cancel (后来发现是误诊但 fix 无害) |
| | `23f98ea` | SYSTEM_PROMPT 一气呵成铁律 + write_artifact 文案 |
| | `959b470` | lastEventIsAsk race typing bubble fix |
| | `75d966a` | validate/submit artifact_id 引用模式省 token |
| | `b0d6294` | SPEC 拆 2 阶段 + 用户审核点 (用户反馈) |
| | `fc31b23` | Phase 3c Chrome Extension 立项 |
| | `a393c25` | Phase 3c 补齐 screenshot/list/select 走 ext |
| | `0158780` | Task #13 删 ChangePlan stub 按钮 |
| | `a0f0578` | iframe 优先铁律 |
| (xhh) | `8e700b3` | improve design export + tenant app lookup |
| (xhh) | `6a35c59` | skip env lookup for tenant app list |
| 下午 | `87b6f17` | **Phase 3d MVP Browser viewport mini preview MJPEG** |
| | `6cb7ce0` | platform_envs.token 空时自动 login (首次自愈) |
| | `26802ce` | **Phase 4 #4 TabStrip Cmd+click 真开 chrome tab** |
| | `014e88a` | admin-spa dark 联动 + Element Plus token override |
| | `c5af563` | **admin-spa 多 tab 支持 (TabStrip + Cmd+click)** |
| | `ccb3758` | admin-spa sidebar rail-item 下划线 fix |
| | `0fa4087` | 切租户整页 reload (数据不刷新 fix) |

(中间 admin 风格修复 9 个 commit 跨 session 提交的, 不重复列)

---

## 留尾任务 (下次 session)

### P0 (建议优先)
- **Phase 4 #1 刷新 tab 各内部 path 还原**: 当前 tabs 列表 localStorage 持久化但各 tab 内部 path / view state 没还原. 1-2h
- **frontend RailSidebar 也改 `<a href>`**: 跟 admin-spa 一致, 让 Cmd+click sidebar 也开新 chrome tab. 30min
- **ai-chat agent 慢 / final summary 不出现** (Task #8): 用户实测 agent 调完 validate_builder_doc + write_artifact + submit_design_doc 后没 final summary. 复现 + 修 frontend SSE handler 或 backend prompt.

### P1
- **mcp-server feat ↔ main merge**: feat/mcp-tools-batch-2026-05-14 跟 origin/main 42 commit 差距大 (main 重组了 k8s 目录, legacy-apaas-builder/ + cutover/), 需要 careful rebase. 半天.
- **Phase 4 #5 URL ↔ tab 1:1 严格映射**: 当前 URL 是单一 path 切 active tab 时变化, 但是分享 URL 时不带 tab list. 1-2h
- **53 处 .vue 硬编码 hex 改成 token**: dark mode 兜底 CSS 已覆盖, 但源头改更彻底. 2-3h

### P2
- **Phase 4 #2 KeepAlive LRU 缓存策略**: 防止打开 10+ tab 内存爆.
- **Phase 4 #3 后台 tab SSE 节流 + badge**: 切走 tab agent 继续跑时不被错过.
- **Phase 4 #6 Cmd+Shift+T reopen 关闭 tab**.
- **ai-builder ↔ main merge**: 304 个 commit 差距, 需要专门 session.

### P3
- **Phase 3b server-side headless Playwright fallback**: 等真用户需求触发 (≥3 移动用户 / cron / SaaS).

---

## 关键文件

### Backend
- `backend/app/mcp_server.py:_browser_tool_via_ext_or_cdm` line 4332 — 扩展优先路由
- `backend/app/routes/browser_ext_ws.py` — WebSocket endpoint + ExtensionRouter 单例
- `backend/app/browser_viewport_stream.py` — Phase 3d MJPEG 流 (本 session 新增)
- `backend/app/mcp_server.py:_call_apaas_platform_tool` line 998 — env.token 自愈 (空 / 401)
- `backend/app/routes/applications/__init__.py:_config_chat_event_stream` — config-chat prompt + iframe 铁律
- `backend/app/ai_chat/agent.py:SYSTEM_PROMPT_UNIFIED` — ai-chat prompt 2 阶段 + 用户审核点 + artifact_id token 节省

### Frontend
- `frontend/src/components/v2/TabStrip.vue` — `<a href>` + onTabClick 检测 modifier (Cmd+click 开新 chrome tab)
- `frontend/src/stores/tabs.ts` — TabStore localStorage `ai-builder-tabs-v1`
- `frontend/src/stores/theme.ts` — themeStore + storage event 跨 tab 同步
- `frontend/src/stores/user.ts:switchTenant` — 切租户后整页 reload
- `frontend/src/views/AIChatPage.vue` — lastEventIsAsk computed (考虑 user 已答) + thinkingLabel fallback (write_artifact 5000+ 字)
- `frontend/src/components/v2/ConfigAssistantPanel.vue` — plan 卡片 + hero CTA + ChangePlan 改纯信息卡片

### Admin-spa
- `admin-spa/src/components/AdminLayout.vue` — sidebar `<a href>` + storage event 联动 + watch route.path auto openTab
- `admin-spa/src/components/TabStrip.vue` — 跟 frontend 同款 (admin- 前缀, admin icon set)
- `admin-spa/src/stores/tabs.ts` — useAdminTabsStore (localStorage `admin-tabs-v1`, 跟 frontend 隔离)
- `admin-spa/src/styles/element-plus-dark.css` — Element Plus dark mode 用 design-v3 token override

### Chrome Extension
- `chrome-extension/manifest.json` — v0.1.0 Manifest V3
- `chrome-extension/background.js` — service worker + WebSocket + dispatchCommand (select_tab / screenshot 用 chrome.tabs API)
- `chrome-extension/content.js` — DOM 操作 + snapshot 注入到所有 frames
- `chrome-extension/INSTALL.md` — 用户安装文档 (217 行)

### Docs
- `docs/plan-2026-05-21-config-assistant-agent-mode.md` — 3 phase 立项 218 行
- `docs/plan-2026-05-21-phase3-playwright-poc.md` — Phase 3 立项 + 3c + 3d
- `docs/rfc-2026-05-19-browser-control-poc.md` — 浏览器控制 RFC 138 行
- `docs/handoff-2026-05-21-evening-session-end.md` — 早 session handoff
- `docs/handoff-2026-05-22-session-end.md` — **本文档**

---

## ⚠️ 提示下次接手

1. **Phase 3c 扩展只在用户本机 Chrome 起作用** — backend restart 时 ExtensionRouter 单例会断, 扩展自动 5s 重连. 跨 chrome instance 隔离 (Dia / Google Chrome 各自连一个 WS).
2. **Phase 3d MJPEG 流性能开销** — agent 操作时 5fps 截图, 持续 30+ min 会占用一定 CPU. 暂未做 idle stop.
3. **Tabs localStorage 跨 chrome tab 共享** — 同 origin 多 chrome tab 看到同一份 tab list (storage event 实时同步). 但 admin-spa 跟 frontend 隔离 (key 不同).
4. **切租户 reload 副作用**: in-flight SSE 断 / 表单丢. 用户期望可接受. P2 优雅方案是发 tenant-switched event 让各 store invalidate, 工程量 1-2h.
5. **xhh 并行修了 backend `tools.py +915` 反向导出 `export_apaas_app_design_doc`** — 用户给已有应用让 agent 反向写 SPEC md. 测试场景 + 调优是 P1.
6. **mcp-server repo main 跟 feat 差距大** — 别盲目 merge, 先看 k8s 目录重组冲突.
