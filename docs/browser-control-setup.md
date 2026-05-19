# 配置助手浏览器控制 — 启动指引

## 你为什么需要这个

配置助手 (`/chat?app_id=X` 右侧聊天面板) 现在能调 4 个浏览器工具:
- `browser_snapshot` — 看当前页面 a11y tree
- `browser_click(uid)` — 点击元素
- `browser_type(uid, text)` — 输入文本
- `browser_screenshot` — 截图

这让 AI 能做 MCP API 够不到的事情：
- 把模型字段拖到表单画布
- 调整流程节点顺序
- 改菜单结构
- ... 等所有"手动 UI 操作完成"的事

## 启动 Chrome with remote debug

### ⚠️ Chrome v136+ 安全限制

Chrome 从 v136 起拒绝给**默认 user-data-dir** 开 `--remote-debugging-port`
（防 cookie 被远程偷）。直接传 `--remote-debugging-port=9222` 启用户主 Chrome 会**静默失败**
(进程跑但 9222 不 listen)。

### 推荐方案：clone profile + 用 clone

把用户主 Chrome profile rsync 到非默认路径，从那启 — 保留 cookies / 书签 / 扩展 /
密码管理器 (autofill)，但 ai-builder 等 localStorage token 可能需重新登一次。

**Mac**:
```sh
# 1. 关掉所有 Chrome
pkill -f 'Google Chrome'
sleep 3

# 2. clone profile 到非默认路径 (Cache / Service Worker / IndexedDB 排除，省空间)
TARGET="$HOME/.chrome-ai-debug-profile-real"
mkdir -p "$TARGET"
rsync -a --delete \
  --exclude='Cache' --exclude='Code Cache' --exclude='Service Worker' \
  --exclude='GPUCache' --exclude='ShaderCache' --exclude='File System' \
  --exclude='IndexedDB' --exclude='blob_storage' \
  "$HOME/Library/Application Support/Google/Chrome/Default" \
  "$TARGET/"

# 3. 从 clone 启 Chrome + 开 9222
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$TARGET"

# 4. 验证
curl -s http://127.0.0.1:9222/json/version | head -c 200
```

### 兜底方案：纯隔离 profile

如果不需要继承主 Chrome 状态，直接用隔离 profile（空白 Chrome）:
```sh
pkill -f 'Google Chrome' && sleep 3
open -na "Google Chrome" --args --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-remote-debug-profile" --no-first-run
```

**Windows**:
```cmd
taskkill /F /IM chrome.exe
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

**Linux**:
```sh
pkill -f 'google-chrome'
google-chrome --remote-debugging-port=9222 &
```

## 验证

```sh
curl http://127.0.0.1:9222/json/version
```

应返 Chrome version + WebSocket URL。看到 `webSocketDebuggerUrl` 就成。

## backend 验证桥接

```sh
# 拉本地 MCP 工具列表，应能看到 browser_* 4 个工具
curl -s -X POST http://127.0.0.1:8000/api/mcp/mcp \
  -H 'Authorization: Bearer YOUR_MCP_KEY' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | python3 -m json.tool | grep -E '"name":.*browser_'
```

## 端到端验证 (跑 chrome-devtools-mcp 实际通讯)

```sh
# 直接调 browser_snapshot 工具
curl -s -X POST http://127.0.0.1:8000/api/mcp/mcp \
  -H 'Authorization: Bearer YOUR_MCP_KEY' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"browser_snapshot","arguments":{}}}' \
  | head -c 2000
```

第一次调用会自动启动 chrome-devtools-mcp sidecar（npx 拉包，可能要 10-30 秒）。

如果返 `BRIDGE_NOT_STARTED`:
- 检查 node + npm 在 PATH (`which npx`)
- 检查 Chrome remote debug 真开了 (`curl http://127.0.0.1:9222/json/version`)
- 看 backend 日志 `tail -f /tmp/apaas-backend.log | grep BrowserMcp`

## 在配置助手里用

进 `/chat?app_id=X` 右侧助手，问类似：
- "看看当前 apaas designer 页面有什么"
- "把『备注』字段拖到报销单表单上"
- "在审批流程里加一个抄送节点"

AI 会先调 `browser_snapshot` 看页面，再 `browser_click` / `browser_type` 操作。

## 风险与限制 (POC 阶段)

- **单实例**：进程内只跑一个 chrome-devtools-mcp，多用户并发会撞车
- **状态依赖**：AI 看不到的 Chrome state 它就操作不到（譬如别的 tab）
- **没有 confirm**：AI 可能误操作，做完后自己检查或截图给用户看
- **生产部署难**：需要每用户启专属 Chrome session — Phase 2 任务

详细架构：见 `docs/rfc-2026-05-19-browser-control-poc.md`。
