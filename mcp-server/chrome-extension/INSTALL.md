# apaas-builder-helper · Chrome 扩展安装指南

> 装一次永久无感，消掉「每次重启 Chrome 都要带 `--remote-debugging-port=9222`」痛点。
> 同 Anthropic Claude in Chrome 同款架构。

---

## 1. 装扩展（一次性，~30 秒）

### 步骤
1. 打开 Chrome → 地址栏输入 `chrome://extensions/` 回车
2. 右上角打开 **「开发者模式」** 开关
3. 左上角点 **「加载已解压的扩展程序」**（Load unpacked）
4. 选 `/Users/mars/Vibe Coding/apaas-builder-ai/chrome-extension/` 目录
5. 扩展卡片出现：**aPaaS Builder Helper** v0.1.0 — 应该是绿色已启用

### 验证装好了
- Chrome 右上角扩展图标里能看到一个新图标（地址栏右侧拼图样图标 → 一个新条目）
- 点这个图标弹出 popup 应该显示「✅ 已连接 backend ws://localhost:8000/ws/browser-ext」
- 没连上就检查 backend 是否跑着（`curl http://localhost:8000/api/health` 应返 200）

---

## 2. 装完做啥（什么都不用做）

扩展 background service worker 自动连后端 WebSocket `ws://localhost:8000/ws/browser-ext`。
连上后，AI 配置助手 (ConfigAssistantPanel) 调 `browser_*` 工具时就走你这个 Chrome 而不是
chrome-devtools-mcp 的 `:9222` 端口。

### 测试 agent 真用上了扩展
1. backend running + 扩展装好 + 你 Chrome 开着任意 tab（建议留一个 aPaaS 平台 tab）
2. 打开 `localhost:5173/ai-builder/chat?app_id=N` 任意已部署应用
3. 配置助手发：**「列出当前打开的所有 tab」**
4. agent 调 `browser_list_pages` 应该返:
   ```json
   {"ok": true, "source": "extension", "count": N, "pages": [...]}
   ```
   `source: "extension"` 就是走扩展了 ✅。如果是 `source: "cdm"` 说明扩展没连上，agent
   降级到 chrome-devtools-mcp + :9222 路径。

---

## 3. 工作原理（架构）

```
┌─ Chrome (你的本地浏览器)
│  ├─ 任意 tab 跑用户内容 (aPaaS 平台 / 别的网站)
│  └─ apaas-builder-helper extension
│     ├─ background.js (service worker)  ── WebSocket ──┐
│     ├─ content.js (注入每个 tab 做 DOM 操作)         │
│     └─ chrome.tabs / chrome.scripting / chrome.debugger API
└─ 通过 WS 跟 backend 双向通信                          │
                                                       │
┌─ Backend (uvicorn :8000)                              │
│  ├─ /ws/browser-ext WebSocket endpoint  ──────────────┘
│  │  └─ ExtensionRouter (单例) — backend.call(cmd, args) → ext
│  └─ MCP tool browser_* (snapshot / click / type / screenshot /
│       navigate / list_pages / select_page / start_recording /
│       stop_recording)
│     ├─ 优先 ext_router.call() 走扩展 (用户真 Chrome + SSO)
│     └─ fallback chrome-devtools-mcp + :9222 (扩展没装时)
```

### 跟 :9222 路径对比

| 维度 | 扩展路径 (推荐) | :9222 路径 (fallback) |
|---|---|---|
| 用户参与 | **装一次永久无感** | 每次重启 Chrome 都要带 flag |
| SSO 复用 | ✅ 用你 Chrome cookie | ✅ |
| 跨平台 | ✅ Chrome 装扩展即用 | ❌ mac/win/linux 启动命令各异 |
| 截图速度 | ✅ `chrome.tabs.captureVisibleTab` 直接拿 dataUrl | 慢 (CDP take_screenshot + 落盘 + 读回) |
| 工具集 | 9 个 browser_* 已通 | 同 |

---

## 4. 卸载

`chrome://extensions/` 找到 **aPaaS Builder Helper** → 「移除」按钮。Backend 那边
`ExtensionRouter.is_connected` 自动变 false，agent 调 browser_* 工具会自动降级到 :9222 路径
（要降级生效你得另外启动带 `--remote-debugging-port=9222` 的 Chrome）。

---

## 5. 常见问题

### Q1: popup 显示「未连接」
- Backend 没跑：`curl http://localhost:8000/api/health` 应返 200
- Backend 跑了但 WS endpoint 没注册：grep `backend/app/main.py` 应该 import `browser_ext_ws`
- 扩展 background.js 报错：`chrome://extensions/` → 「Service worker」链接 → 看 console

### Q2: agent 调 browser_screenshot 返 `EXTENSION_RUNTIME` error "captureVisibleTab failed"
- Chrome 不允许在 `chrome://` 协议页面截图（chrome 扩展安全限制）
- 切到 http/https/file 协议 tab 再试

### Q3: agent 调 browser_click(uid) 返 "no element with uid"
- uid 由 browser_snapshot 返回，跨 snapshot 不稳定（每次新 snapshot 会重置 uid）
- agent prompt 已写明「每次 click/type 前重新 snapshot 拿当前 uid」
- 检查是不是用了旧 snapshot 的 uid

### Q4: 扩展装在公司电脑没权限装第三方扩展
- 走 Chrome Web Store 路径（需要先把扩展打包成 .crx + 上传 Web Store）— 待 Phase 3c.2 做
- 或者用本机 chrome-devtools-mcp + :9222 fallback 路径

---

## 6. 开发者：扩展改动后怎么 reload

1. 改 `background.js` / `content.js` / `popup.js` / `manifest.json` 后
2. `chrome://extensions/` 找到 **aPaaS Builder Helper** → 点 **🔄 重新加载** 按钮
3. background service worker 会重启（注意 WS 重连，约 5s）

改后端 (`mcp_server.py` / `browser_ext_ws.py`) 要重启 uvicorn 才生效。

---

## 7. 相关文档

- Phase 3 立项: `docs/plan-2026-05-21-phase3-playwright-poc.md`（含 3c 章节）
- 浏览器控制 RFC: `docs/rfc-2026-05-19-browser-control-poc.md`
- Backend WS endpoint: `backend/app/routes/browser_ext_ws.py`
- Backend browser_* tools: `backend/app/mcp_server.py` line 4340-4790
- Extension 主代码: `chrome-extension/background.js` + `content.js`
