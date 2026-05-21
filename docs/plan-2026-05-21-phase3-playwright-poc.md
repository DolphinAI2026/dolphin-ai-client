# Plan · Phase 3 浏览器控制 — Playwright headless fallback 评估

> 2026-05-21 立项。Phase 1+2 已上线，本文回答 Plan 文档第 115-149 行 Phase 3 假设
> 跟当前实际架构的 gap，决定是否真的需要 "4-6 周从零搭 Playwright proxy"。

## TL;DR

Plan 文档假设 Phase 3 是 4-6 周从零搭 Playwright headless proxy + pool + LRU + vision fallback。
**实际现状**：2026-05-19 已经落 chrome-devtools-mcp 接入，9 个 browser_* 工具白名单已开，
用户 Chrome `--remote-debugging-port=9222` 路线**已在跑**，能在 ConfigAssistantPanel 直接调
snapshot/click/type/screenshot/navigate/list_pages/select_page/start_recording/stop_recording。

**Plan 的 4-6 周大投入实际上是错误估计**。真实剩余工作量：
- 现状路线 Phase 1+2 收尾 (3-5 天)
- 是否真要 Playwright headless server-side fallback (1-2 周技术 POC，可选)

---

## 1. 当前架构（已落地）

### 1.1 已通的链路

```
config-chat agent (backend/app/routes/applications/__init__.py:_config_chat_event_stream)
   ↓ browser_* 工具调用 (白名单 _CONFIG_CHAT_TOOL_WHITELIST line 2238-2293)
backend/app/browser_mcp_bridge.py (BrowserMcpBridge 单例)
   ↓ asyncio subprocess + jsonrpc stdio
chrome-devtools-mcp@latest (npm package, sidecar process)
   ↓ CDP (DevTools Protocol)
用户的 Chrome (--remote-debugging-port=9222)
   ↓
  Tab 1: ai-builder /chat?app_id=X (用户当前页面)
  Tab 2: apaas-platform designer iframe (AI 真操作的目标)
```

### 1.2 已支持的工具集 (9 个)

```python
# _CONFIG_CHAT_TOOL_WHITELIST 已有
"browser_snapshot",         # 拿当前 tab a11y tree (含 uid)
"browser_click",            # 点击 uid 指定的元素
"browser_type",             # 输入文本
"browser_navigate",         # 跳转 URL
"browser_screenshot",       # 截图 (data URL 直接渲染到 ConfigAssistantPanel)
"browser_list_pages",       # 列所有 tab (pageId + URL)
"browser_select_page",      # 切到指定 tab
"browser_start_recording",  # 演示式学习：录用户点击/输入序列
"browser_stop_recording",   # 停止录制 → 返 event 数组给 AI 总结成 steps_md
```

### 1.3 已落地的高级能力

- **Image content block 自动转 data URL** — chrome-devtools-mcp 的 take_screenshot 返
  `{ type: "image", data: "<base64>" }`，bridge 自动包装成 `data:image/png;base64,...`
  让前端 `<img src>` 直接渲染缩略图（Claude in Chrome 风格）
- **Skill 自学习闭环** — save_config_skill / get_config_skill / delete_config_skill 已通，
  AI 自己沉淀"用户教过的操作" 成 steps_md
- **演示式学习** — start_recording → 用户点 → stop_recording → AI 推断 selector +
  总结 steps_md → save_config_skill 一条龙
- **uid 跨 snapshot 不稳定的 prompt 规则** — system_prompt 已写明"每次 click/type
  前重新 snapshot 拿当前 uid"，避免 stale uid 误点

---

## 2. Plan 文档 vs 实际架构的 gap

### 2.1 Plan 假设了哪些（第 115-149 行）

```
- 起一个 headless browser
- 跑 Playwright/Puppeteer
- 登 aPaaS, 操作 UI, 截图回传
- per-tenant pool + LRU
- vision-based fallback (UI 变了 selector 失效)
- 用户级权限 → API key 不能漏到客户端
- 凭证 / SSO 怎么处理
```

### 2.2 实际架构的差异

| Plan 假设 | 实际落地 | 差异点 |
|---|---|---|
| 后端 headless Chrome pool | **用户本机 Chrome** | 不需要 headless / pool — 用户已开的 tab 自带 SSO 凭证 |
| Playwright / Puppeteer | **chrome-devtools-mcp** | 用 Anthropic 主推 + GA 的方案，不自己造 |
| 4-6 周工程 | **已落 Phase 0 + Phase 1 部分** | RFC 写完是 2026-05-19，3 天前 |
| 6 个 apaas_ui_* 工具 (Plan 列) | **9 个 browser_* 工具已开** | screenshot / drag / hover 等 chrome-devtools-mcp 26 工具集子集 |
| 凭证 / SSO 难题 | **复用用户 Chrome cookie** | 用户已登录 → 不需要后端拿 token |

### 2.3 Plan 假设的"Phase 3 难点"——重估

| Plan 提到的难点 | 现实 |
|---|---|
| 凭证 / SSO | ✅ 用户 Chrome 已登 — 不存在 |
| 每用户独立 chrome 实例 | ⚠️ 真实问题但 POC 阶段单进程足够（每用户用自己本机 Chrome） |
| UI 变了 selector 失效 | ✅ chrome-devtools-mcp 用 a11y tree uid 不是 CSS selector — UI 改动 robust |
| Vision fallback (LLM 看截图判断) | ✅ screenshot 已能 data URL 渲染到对话面板 — LLM vision capability 可用 |
| API key 不能漏到客户端 | ✅ chrome 跑用户本机，backend 只走 CDP 协议 — 无 key 泄露面 |

**结论**：Plan 的 4-6 周估时主要假设是从零搭 server-side headless 全套，但实际已经选了
"用户本机 Chrome" 路线避开 90% 的难题。

---

## 3. 现状路线的真实 limit

不是没问题，只是 Plan 列错了。**真正剩余的卡点**：

### 3.1 用户本机依赖 ⚠️

- 用户必须在 mac 上跑 `open -a 'Google Chrome' --args --remote-debugging-port=9222`
- 用户在公网 SaaS 场景（手机 / 平板 / 远程办公）没办法配
- 多用户共享一个 backend 时 chrome-devtools-mcp 单例只能连一个 :9222 端口

### 3.2 多用户并发 ⚠️

- 当前 `BrowserMcpBridge` 是单例（line 41-56 注释明确写 "多用户隔离暂不在 POC 范围"）
- 生产 SaaS 多租户时会冲突 — 用户 A 的 click 可能打到用户 B 的 page

### 3.3 后台 batch / 定时任务 ❌

- 没有用户 Chrome 在跑时，整个 browser_* 全降级失败 `BRIDGE_NOT_STARTED`
- 不能跑"每天凌晨自动巡检 50 个应用的菜单结构"这种场景

### 3.4 多 tab 状态污染 ⚠️

- 用户 Chrome 多 tab — AI 可能操作错 tab
- `browser_select_page` 已加 fallback 但要 AI 严格走"先 list_pages → 找对的 tab → select_page" 流程
- 还是有 stale active page 撞 `No page selected` 错误的可能

---

## 4. 真要做 Playwright headless server-side fallback 吗？

按现状路线的 3 个 limit 反推：

| 场景 | 现状 (用户 Chrome) | 是否要 headless fallback |
|---|---|---|
| 桌面用户 + 本机 Chrome | ✅ 完美 | ❌ 不需要 |
| 移动 / 平板用户 | ❌ 不能配 | ✅ 需要 |
| 后台 batch / CI / 定时任务 | ❌ 不可能 | ✅ 需要 |
| 严格多租户 SaaS 多并发 | ⚠️ 单例冲突 | ✅ 需要 (or per-user user-data-dir) |
| 演示 / sales demo (跑 trial 应用看效果) | ⚠️ 销售本机也要配 | 🤔 可选 |

**真实需求评估**：当前用户量 ≤ 10 (trial 阶段)，全是技术型用户能本机配 chrome remote debug。
移动端 / 后台 batch 场景**还没真实需求**。

→ Playwright headless fallback **现阶段不是阻塞项**，可以等真有用户提才做。

---

## 5. 推荐路径（cut + 阶段）

### Phase 3a 现状路线收尾 (3-5 天) — 推荐立即做

1. **完成 RFC Phase 1**（端到端联通验证）
   - 已有但没充分测：browser_drag 拖拽（apaas designer 拖字段到表单）— 跑通真用例
   - 写"开 Chrome remote debug" 用户文档 + mac/windows 一键脚本
2. **完成 RFC Phase 2 部分**
   - 操作前 confirm dialog（删除 / 发布 / 改权限类高风险动作）
   - action audit log（写 db / 至少 backend log structured 输出）
3. **prompt 调优**
   - 现 Phase 1 prompt 已写"MCP API 够不到再用 browser_*"
   - 加"高风险动作先 ask_clarifying_question"

### Phase 3b 真用户提需求后启动 (1-2 周技术 POC) — 暂不动手

触发条件（任一）：
- ≥ 3 个移动端用户提"我想在手机上让 AI 帮我改配置"
- 团队真要 cron job 自动巡检应用
- 进入正式 SaaS 多租户阶段（trial → 付费）

技术路径：
- 路径 A: chrome-devtools-mcp 自起 headless chrome（同 mcp 工具集，只改 `--browserUrl` →
  `--launch` flag 自起 chromium）— 最小改动
- 路径 B: 替换为 Playwright + Anthropic Computer Use → 全套换技术栈，工作量大
- **推荐路径 A** — 复用 9 个 browser_* 工具 + skill / recording 体系不重写

不要做（明确 cut）：
- 不做 Plan 第 137-141 行的"自建 apaas_ui_* 6 工具" — chrome-devtools-mcp 26 工具集已覆盖
- 不做 per-tenant browser pool + LRU — 真有量级再加，POC 阶段单进程
- 不做自己的 vision fallback layer — LLM 自己看 screenshot 决策已足够

### Phase 3c · Chrome Extension 路径 — 消掉"每次开端口"用户痛点 (1-2 周) — 中期推荐

**触发场景 (2026-05-21 用户实测反馈)**: 用户发现 `chrome-devtools-mcp + :9222` 路线要求用户
**每次重启 Chrome 都带 --remote-debugging-port=9222**, 体验对比:

| 方案 | 用户参与 | SSO 复用 | 隐私 | 工程量 |
|---|---|---|---|---|
| Claude in Chrome 扩展 (Anthropic 官方) | 装一次, 永久无感 | ✅ | ✅ 本机跑 | — |
| ChatGPT Operator (云端 Chrome) | 无 | ❌ 拿不到 cookie | ❌ 服务器跑 | — |
| **我们 chrome-devtools-mcp + :9222 (Phase 3a)** | **每次开端口** | ✅ | ✅ | 低 |
| Anthropic Computer Use (后端 VM) | 无 | ❌ | ❌ | 高 |

用户原话"Claude / GPT 都不需要开"指 Claude 扩展 + ChatGPT Operator 路线。要追平用户体验
只有 "**我们自己写浏览器扩展**" 这一条路径 (ChatGPT Operator 模式因为拿不到企业 SSO 不适用).

**架构设计 (Chrome Extension v1)**:

```
┌─ Chrome Extension (apaas-ai-builder-helper)   manifest_version: 3
│  ├─ background service_worker                  长期监听 cdp / native messaging
│  ├─ content scripts (匹配 *.apaas-platform.* / localhost) 注入 DOM 监听 + RPC
│  ├─ chrome.tabs API                            列 tab / 切 tab
│  ├─ chrome.scripting.executeScript             跑任意 JS in target tab (含 DOM 操作)
│  ├─ chrome.debugger API                        DevTools Protocol (snapshot / click 底层走它)
│  └─ Native Messaging Host → 我们 backend       双向 jsonrpc 替代 stdio chrome-devtools-mcp
└─ 用户安装: chrome://extensions/ 加载 .crx 或 Chrome Web Store 发布
```

后端从 `chrome-devtools-mcp + stdio` 切到 `native messaging + extension`:
- 9 个 `browser_*` 工具 schema 保留不变 (agent prompt 不动)
- `backend/app/browser_mcp_bridge.py` 内部实现换: 不再 spawn `npx chrome-devtools-mcp`,
  改成 `native_messaging_send(action, args)` 走 extension
- chrome.debugger.attach API 可以做跟 CDP 等价的事 (snapshot / click / type / drag)
- 截图用 `chrome.tabs.captureVisibleTab` 比 CDP `Page.captureScreenshot` 更快

**工程拆解 (5-7 天)**:

1. 扩展骨架 (Manifest V3) + background service_worker + content script — 1 天
2. 9 个 browser_* RPC handler 实现 (snapshot / click / type / navigate / screenshot /
   list_pages / select_page / start_recording / stop_recording) — 2 天
3. Native Messaging Host 配置 + backend bridge.py 切到 native messaging — 1 天
4. 用户安装文档 + 一键 .crx 打包脚本 — 1 天
5. 兼容旧 chrome-devtools-mcp + :9222 路径 (fallback) — 0.5 天 (扩展没装 → 降级到 CDP)
6. 跨平台测试 (mac / windows / linux Chrome) — 1 天

**Phase 3a vs 3c trade-off**:

| 维度 | 3a (CDP + :9222) | 3c (Extension) |
|---|---|---|
| 用户教育 | 每次重启带 flag (脚本帮也要点击运行) | 装一次永久 |
| 跨用户隔离 | 共用 :9222 端口 单实例 | 每用户独立扩展 instance |
| 高级能力 | CDP 26 工具够用 | 还能用 chrome.* API 做更多 (history / cookies / downloads) |
| 工程量 | 已落 (POC) | 5-7 天 |
| 上线分发 | 终端跑命令 | Chrome Web Store / 企业内部 .crx |

**推荐**: Phase 3a 收尾后立即启动 3c — 3c 是消掉用户痛点的真正路径, ChromeExtension 也是
Anthropic Claude in Chrome 同款架构, 是行业 standard practice.

**Phase 3c 完成后 Phase 3a 仍保留** — 扩展没装的用户降级到 CDP + :9222 路径仍 work,
两套并行没冲突 (browser_mcp_bridge 内部判断 extension 是否 connected, 没连就 fallback 走 stdio).

---

## 6. 关键文件清单

| 文件 | 作用 | 状态 |
|---|---|---|
| `backend/app/browser_mcp_bridge.py` | chrome-devtools-mcp stdio client | ✅ 已落 |
| `backend/app/routes/applications/__init__.py:_CONFIG_CHAT_TOOL_WHITELIST` | 工具白名单 (9 browser_*) | ✅ 已开 |
| `backend/app/routes/applications/__init__.py:_config_chat_event_stream` | prompt + agent loop | ✅ 已含 browser 规则 |
| `frontend/src/components/v2/ConfigAssistantPanel.vue` | screenshot data URL 渲染 + 截图缩略图 | ✅ 已落 |
| `docs/rfc-2026-05-19-browser-control-poc.md` | 完整 RFC (138 行) | ✅ 已写 |
| `docs/plan-2026-05-21-config-assistant-agent-mode.md` | 上层愿景 (218 行) | ✅ 已写 |
| `docs/plan-2026-05-21-phase3-playwright-poc.md` | **本文档** | ✅ 已写 |

## 7. 决策 summary

**给下个 session 的 explicit decision tree**:

1. Phase 1 (主动多步 prompt) 已 commit `6fe8010` + push origin — 等 deploy 验证
2. Phase 2 (plan 卡片 + hero CTA) 已 commit `535f9f1` + push origin — 等 deploy 视觉跟 user 对齐
3. Phase 3a (chrome-devtools-mcp Phase 1+2 收尾) **推荐立即做** — 3-5 天工作量
4. **Phase 3c (Chrome Extension 消"开端口"痛点) 中期推荐** — 5-7 天, 3a 收尾后立即启动. 同 Claude in Chrome 架构, 行业 standard.
5. Phase 3b (server-side headless fallback) **暂不启动** — 等真用户需求
5. 不要按 Plan 文档第 115-149 行假设跑 4-6 周从零搭 Playwright proxy — 是过时认知

---

## 8. 参考

- RFC 2026-05-19: `docs/rfc-2026-05-19-browser-control-poc.md`
- Plan 2026-05-21: `docs/plan-2026-05-21-config-assistant-agent-mode.md`
- chrome-devtools-mcp upstream: https://github.com/ChromeDevTools/chrome-devtools-mcp
- Anthropic Claude in Chrome 设计参考
