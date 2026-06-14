# Vibe Coding (`/vibe-coding`)

**对话式全代码开发——AI 给方案建议，你拍板，沙箱里跑代码。** 类似 Claude Code / Codex / Lovable 的开发体验。

## 核心特点

- **完整应用**：不是组件，是带前端 + 后端 + 数据库的完整 Web 应用
- **Docker / Podman 沙箱**：每个工作区一个隔离容器，独立运行，互不影响（线上用 podman，行为兼容 docker）
- **9 个工具的 Agent loop**：read_file / write_file / edit_file / run_command / list_dir / search_files / todo_write / ask_clarifying_question / present_plan
- **Split preview**：对话区右边可拆出预览面板，看 dev server 跑起来的效果
- **多模态输入**：图片可粘贴（截图 → AI 看着图开始改）

## 新建工作区（已简化为对话驱动）

`/vibe-coding` 进入后，**点左侧 sidebar 「+ 新建工作区」按钮直接创建空工作区，自动跳到对话区**。不再有"填写 Git 仓库 / 开发目标"的表单。

如果想接现有 Git 仓库或填详细需求，**直接在对话里跟 AI 说**：
- "先 clone https://github.com/xxx" → AI 在沙箱里 git clone
- "做一个 todo app，要支持登录" → AI 出方案，你拍板，开始写代码
- 写完想 push？跟 AI 说"提交到我的仓库"（首次需配置 Git 凭证）

## 典型流程

1. `/vibe-coding` → 点左侧"+ 新建工作区" → 自动跳到 `/vibe-coding/workspaces/{id}`
2. 在对话框直接描述需求，比如"做一个五子棋小程序"
3. AI 用 `present_plan` 给方案（技术栈 + 任务清单）
4. 你说"继续" → AI 按清单写代码 + 跑 npm install + 起 dev server
5. AI 起 dev server 成功后，**右上"预览"按钮**亮起 → 点开看效果
6. 不满意继续对话，AI 改代码（vite/HMR 自动热更新）

## 视图切换（顶部右侧）

- **对话**：默认视图，消息流 + 工具调用 + 任务清单
- **代码**：查看源码、diff 和工作区文件
- **预览**：split panel 在右侧（仅 chat 视图显示），可拖宽度，多端口（前端 / 后端）切换

打开任一工作区**默认是 chat 视图**，代码视图由你主动切。

## 工作区改名

左侧 sidebar 上 hover 工作区项，**点 ✎ 图标**重命名（弹出输入框）。

## 沙箱预览访问

dev server 起来后，预览 iframe 的 URL 是 `https://p<host_port>.vibe-first.cn/`（线上）或 `http://localhost:<port>`（本地 dev）。

- 线上每个 sandbox 容器内的 6173 端口（vite 等前端）会被 podman 映射到一个随机 host 端口
- nginx 用 server_name 正则把 `p<port>.vibe-first.cn` 反代到对应 host 端口
- 通配 SSL 证书 `*.vibe-first.cn`（Let's Encrypt，每 90 天自动续）
- 因此**多人多 workspace 同时预览**互不干扰

### 前后端通信约束（agent 写代码时遵循）

- 前端用相对路径 `fetch('/api/...')`、Socket.IO 用 `io()` 同源
- vite 配 proxy `/api` → `http://localhost:6300`，**不要**写死 `localhost:6300`（线上 host 不可达）
- vite 必须配 `server.allowedHosts: ['.vibe-first.cn', '.dfy.definesys.cn']`，否则线上访问报 `Blocked request`

## 与 AI 编码的差异

- **Vibe Coding** = 完整应用 + 自由度高 + Docker 沙箱
- **AI 编码** = 单组件 / 单页面 + 模板严格 + 产物上传到 aPaaS 平台

## 沙箱资源管理

每个 sandbox 占用磁盘 + 内存（每容器 cap 2GB）。**长时间不用记得停掉**避免资源浪费——见「沙箱监控」(`/vibe-coding/sandboxes`)。
