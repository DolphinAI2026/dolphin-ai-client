# RFC: 配置助手浏览器控制能力 (chrome-devtools-mcp 接入)

**日期**: 2026-05-19
**状态**: POC 阶段，骨架已落，端到端待用户协作测试
**作者**: 同 ce session
**触发原因**: image #41 — 助手说"工具够不到，没法把模型字段拖到表单"。MCP API 盲区导致 80% 的精细化操作做不了。

---

## 1. 问题

当前 ConfigAssistantPanel 有 22 个 MCP 工具白名单（model 字段 CRUD、字典、角色、form_component 部分属性更新）。但 apaas 平台没暴露：

- 加 form_component (把模型字段拖到表单)
- 调整组件位置 / 顺序
- 改菜单结构 / 排版
- 配置流程节点拓扑
- ... 等所有"通过 UI 操作完成"但 backend 没单独 API 的事

→ AI 看到任务 → 用人话出操作步骤 → 用户自己点 → 体验割裂。

## 2. 选型对比

| 方案 | 工作量 | 解决盲区 | 长期可持续性 |
|---|---|---|---|
| **A**. 给得帆要 add_form_component 等结构化 API | 1-2 周（等得帆 PR） | 70% | 每个新场景要新 API |
| **B**. chrome-devtools-mcp 接入 → AI 真操作浏览器 | 3-5 天 POC | 95% | 自主可控 |
| **C**. iframe postMessage 桥 (designer 内注入 listener) | 1-2 周（要得帆配合） | 95% | 跨团队协作 |

**决策**：先做 B，因为 chrome-devtools-mcp 是 Anthropic 主推的成熟方案，1.0.1 已 GA。我们这边技术栈跑得起来，不依赖得帆。

## 3. 架构

```
┌──────────────────────────────────────────────────────────┐
│ 用户浏览器 Chrome (--remote-debugging-port=9222)         │
│                                                          │
│  Tab 1: ai-builder /chat?app_id=X                       │
│         └─ ConfigAssistantPanel (右栏聊天)               │
│  Tab 2: apaas-platform designer iframe                  │
│         └─ AI 真正操作的目标 (拖拽 / 点击)               │
└──────────────────────────────────────────────────────────┘
                          ↑
                   CDP (DevTools Protocol) on :9222
                          ↓
┌──────────────────────────────────────────────────────────┐
│ 我们的 backend (uvicorn :8000)                          │
│                                                          │
│  ┌─ chrome-devtools-mcp (sidecar)                       │
│  │  npm package, stdio MCP server                        │
│  │  暴露 26 工具: take_snapshot / click / type / drag / │
│  │             screenshot / hover / select / wait_for / │
│  │             navigate / press_key / ...               │
│  │                                                       │
│  └─ browser_mcp_bridge.py (新增)                        │
│     async ChromeDevToolsClient + stdio asyncio          │
│     把 26 工具暴露成 ai-builder MCP 工具 schema          │
│                                                          │
│  config-chat agent loop                                  │
│   ├─ 现有 22 MCP 工具 (apaas API)                       │
│   └─ + 8-10 browser_* 工具 (新增白名单)                  │
│     → vision LLM 看 screenshot → 决策点击坐标            │
└──────────────────────────────────────────────────────────┘
```

## 4. 实施计划

### Phase 0: 骨架 (本次 session 已落)

- [x] `docs/rfc-2026-05-19-browser-control-poc.md` (本文档)
- [ ] `backend/app/browser_mcp_bridge.py` — stdio MCP client 雏形（连 chrome-devtools-mcp）
- [ ] `backend/app/mcp_server.py` 加 4 个 browser_* 工具桩 (snapshot/click/type/screenshot)
- [ ] config-chat 白名单增 browser 工具
- [ ] README/handoff 教用户开 chrome remote debug port

### Phase 1: 端到端联通 (1-2 天)

- [ ] backend lifespan 启动 chrome-devtools-mcp child process (stdio)
- [ ] 实现 stdio MCP client (asyncio subprocess + jsonrpc framing)
- [ ] browser_snapshot 实测能拿到 apaas designer 页面的 a11y tree
- [ ] browser_click 实测能点中元素
- [ ] LLMClient 加 vision content block 支持 (screenshot → image_url)
- [ ] 第一个真用例：让 AI "在 apaas designer 把『备注』字段拖到表单"

### Phase 2: 多用户 / 安全 / 生产化 (3-5 天)

- [ ] 每用户独立 chrome session (multi-tenant 隔离)
- [ ] 操作前 confirm dialog (高风险动作 — 删除 / 发布 / 改权限) — 防 AI 误操作
- [ ] action audit log (谁、什么时候、AI 做了啥)
- [ ] chrome 进程健康监控 + auto restart
- [ ] 生产部署方案 (docker compose / k8s sidecar)

### Phase 3: prompt + agent 调优 (持续)

- [ ] 配置助手 prompt 加 "优先用 MCP API，做不到再用 browser_*"
- [ ] AI 看 snapshot 找元素的命中率优化（让它先选 selector 候选再选最优）
- [ ] failure recovery — 找不到元素 / 拖拽失败时反馈给用户而不是死循环

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 用户必须开 `chrome --remote-debugging-port=9222` | 提供脚本/扩展自动起；mac 上 `open -a 'Google Chrome' --args --remote-debugging-port=9222` |
| 多用户并发 → chrome 实例隔离 | 每用户独立 user-data-dir + 独立 chrome-devtools-mcp instance；或用 isolated mode |
| AI 误删数据 / 误发布 | 操作前 confirm dialog；危险动作 prompt 警告 |
| chrome 升级 break CDP 协议 | chrome-devtools-mcp 1.x 已稳定；锁版本 |
| Vision LLM 成本 | 截图 1 张 ~1500 tokens ≈ $0.005；agent loop 5 轮 = ~$0.025/会话；可接受 |
| 截图传 LLM 时延 | 比 API call 慢 2-5 倍；用户预期就好 |
| 隐私 — AI 看到屏幕内容 | 类似 Anthropic Claude for Chrome 既有的 policy；产品上说清楚 |

## 6. 不在范围内（明确 OUT）

- 不替代现有 22 个 MCP 工具 — 优先 API，浏览器是兜底
- 不做 Anthropic Computer Use 那种 headless 自托管浏览器 — 用用户自己的 Chrome
- 不做生产灰度策略本期 — POC 阶段先打通技术路径

## 7. 开发任务清单

可在 issue tracker 拆分：

1. **#B-1** backend/app/browser_mcp_bridge.py — chrome-devtools-mcp stdio client
2. **#B-2** mcp_server.py 暴露 browser_* tools
3. **#B-3** config-chat 白名单接入 + prompt
4. **#B-4** LLMClient vision support (image_url content block)
5. **#B-5** 用户启动 Chrome remote debug 文档 + 脚本
6. **#B-6** 端到端测试：拖拽『备注』字段到报销单表单

---

## 附：相关代码位置

- 现有 MCP bridge: `backend/app/ai_chat/mcp_bridge.py`
- ConfigAssistantPanel agent loop: `backend/app/routes/applications/__init__.py:2271-2533` (sync) + `:_config_chat_event_stream` (SSE)
- Tool whitelist: `_CONFIG_CHAT_TOOL_WHITELIST` `:2238`
- chrome-devtools-mcp upstream: https://github.com/ChromeDevTools/chrome-devtools-mcp
- npm: `chrome-devtools-mcp@1.0.1` (Apache-2.0)
- CLI: `npx chrome-devtools-mcp@latest --browserUrl http://127.0.0.1:9222`
- 工具集 (snapshot/click/type/drag/...): 26 tools，按 category 可裁剪
