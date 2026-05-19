# aPaaS Builder Helper Chrome 扩展 — 安装指引

让 AI 配置助手操作你**正在用的 Chrome**（不再需要独立 9222 Chrome）。

## 一次性安装（5 分钟）

1. 打开 Chrome，地址栏输入 `chrome://extensions/`
2. 右上角打开「**开发者模式**」开关
3. 点「**加载已解压的扩展程序**」
4. 选择项目里的 `chrome-extension/` 文件夹（完整路径见下）
5. 扩展卡片应该出现 `aPaaS Builder Helper`，状态绿色
6. 点扩展图标，弹窗应显示 `backend 在线`

**扩展路径**：
```
/Users/mars/Vibe Coding/apaas-builder-ai/chrome-extension
```

## 验证连接

backend 启动后（uvicorn 8000），打开任意 tab，看 Chrome DevTools console 应有：
```
[apaas-helper bg] connecting ws://localhost:8000/ws/browser-ext
[apaas-helper bg] connected
```

backend 日志会有：
```
browser-ext connected: {'version': '0.1.0', 'ua': '...'}
```

## 工作原理

```
你正在用的 Chrome
├── ai-builder /chat tab (你看着) ──┐
├── 任意网页 / iframe              │ extension 注入 content.js
└── 任意 service workers           │
   │                               │
   ▼                               │
apaas-builder-helper extension      │
├── background.js (service worker)  │
│   └── WebSocket → backend         │
└── content.js (注入每个页 + iframe)│
    └── 接 backend 命令操作 DOM ────┘

Backend
├── /ws/browser-ext (FastAPI)
└── ExtensionRouter (单例)
    └── browser_snapshot/click/type/screenshot 优先走它
        chrome-devtools-mcp 当 fallback
```

## 跟 9222 chrome-devtools-mcp 的对比

| 方案 | 操作哪个 Chrome | 跨 origin iframe | 多 tab | 易部署 |
|---|---|---|---|---|
| chrome-devtools-mcp + 9222 | 独立 profile clone Chrome | ✓ | ✓ | 中（要 clone profile） |
| **本 extension** | **你的主 Chrome** | ✓ | ✓ | **易**（一次性装） |

config-chat 现在**自动检测**：extension 连着就用 extension，否则降级 chrome-devtools-mcp。

## 限制 (POC 阶段)

- 单用户（多用户隔离 Phase 2）
- 没有 confirm dialog（高危操作 AI 可能误删 — 用着小心）
- 录制功能在 content.js 里，但完整 demonstration learning 跟 backend 整合留 Phase 2
- 截图 (browser_screenshot) 暂没接 extension — chrome.tabs.captureVisibleTab 需要 background 处理，POC 还没写

## 卸载

`chrome://extensions/` → 找到卡片 → 点「移除」。
