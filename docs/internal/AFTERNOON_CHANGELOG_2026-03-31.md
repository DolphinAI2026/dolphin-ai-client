# 2026-03-31 下午改动总结

## 概览

本次改动主要集中在 4 个方向：

1. 模型配置链路打通
2. 智能搭建 / 需求分析 / AI Coding 的模型选择增强
3. code-server / 工作区 / 扩展链路问题修复
4. 模型管理与前端交互体验优化

## 主要改动

### 1. 模型配置接入统一

- 智能搭建、需求分析、AI Coding 三条链路统一接入租户模型配置，不再只依赖后端环境变量。
- 运行时模型解析优先级统一为：
  1. 当前会话显式选择的模型
  2. 当前租户默认的对应用途模型
  3. 当前租户默认的 `all` 模型
  4. 环境变量兜底
- 智能开发链路补齐了租户维度模型读取，不再写死读取固定租户配置。

### 2. 会话级模型切换

#### 需求分析

- 增加了当前会话模型选择器。
- 支持在首条消息前预选模型。
- 已有会话切换模型后，仅影响后续对话与文档生成，不影响历史结果。

#### 智能搭建

- 增加了当前会话模型选择器。
- 普通聊天、生成配置、确认生成等链路统一使用当前会话所选模型。
- 仅展示 `builder` 和 `all` 用途下可用的模型。

#### AI Coding

- 首页欢迎页增加模型选择器。
- 新建 coding 会话时会携带当前选择的模型。
- 已有会话支持恢复对应模型选择。
- 模型选择与后续 `auto-pipeline -> conversation -> IDE 默认模型` 链路打通。

### 3. 模型管理能力增强

#### 环境管理 / 模型配置

- 新增模型启用 / 禁用能力，全局生效。
- 禁用后的模型会从智能搭建、需求分析、AI Coding 的可选列表中移除。
- 禁止将未启用模型设为默认模型。
- 如果禁用的是当前默认模型，会自动清理默认标记，并尝试补一个同用途的可用默认模型。

#### 内置模型同步

- 调整了启动时内置模型同步逻辑。
- 前台手动将模型设为 `inactive` 后，服务重启不会再被强制改回 `active`。

#### 模型补充

- 增加了新的通用模型：
  - `内置通用模型 (Qwen 3.5 Plus)`
- 用于让搭建类页面不只显示 MiniMax 一条通用模型。

### 4. 模型测试与端点兼容修复

- 修复了 Qwen 测试连接时因 URL 拼接不完整导致的 `404` 问题。
- 修复了 Codex 测试错误走 `chat/completions` 导致的兼容问题，改为使用正确端点。
- 标准化了部分运行时的模型请求 URL 拼接逻辑，降低不同供应商的兼容风险。

### 5. code-server / 工作区问题修复

#### 工作区路径空格问题

- 修复了 code-server 工作区目录路径包含空格时导致构建失败的问题。
- workspace 默认根目录会在必要时切换到无空格路径。

#### 静态资源兜底

- 修复了组件模板 `copyAssets` 指向空目录时触发的构建报错。
- 增加占位资源策略，避免空目录拷贝导致“看起来像构建失败”的误报。

### 6. AI Coding 扩展上下文能力优化

- 将本地 `ruijing-ai` 扩展源码正式纳入仓库版本管理。
- 修复了扩展上下文缓存过于粗糙的问题，减少错误复用旧上下文。
- 优化了工作区上下文排序逻辑，优先注入真正相关源码，而不是只给文件列表。
- 遇到 `.umd.js`、`dist/build` 等构建产物时，不再优先拿它们当默认源码目标。
- 降低了“明明工程里已经有文件，模型还继续向用户索要文件内容”的概率。

### 7. `/platform-envs` 页面路由修复

- 修复了开发环境下 `/platform-envs` 被 Vite 代理规则误伤的问题。
- 页面现在会正确走前端路由，而不是被错误代理到后端接口后返回 `Not Found`。

### 8. 前端下拉与主题样式优化

- 统一了需求分析、智能搭建、AI Coding 三个页面的模型下拉样式。
- 修复了下拉面板由于 teleport 到 `body` 后没有正确继承主题变量，导致深浅色主题显示异常的问题。
- 优化了 AI Coding 页面模型下拉的视觉结构：
  - 选中态更简洁
  - 下拉项分层更清晰
  - hover / selected / 阴影 / 边框更接近产品化控件

## 影响范围

### 后端

- `backend/app/routes/chat.py`
- `backend/app/routes/requirements.py`
- `backend/app/routes/coding.py`
- `backend/app/routes/conversations.py`
- `backend/app/routes/llm_configs.py`
- `backend/app/seed_data.py`
- `backend/app/models/__init__.py`
- `backend/app/coding/workspace.py`
- `backend/app/coding/templates.py`
- `backend/app/coding/vibe_agent.py`

### 前端

- `frontend/src/views/ChatPage.vue`
- `frontend/src/views/RequirementsPage.vue`
- `frontend/src/views/CodingPage.vue`
- `frontend/src/views/PlatformEnvs.vue`
- `frontend/src/api/llmConfig.ts`
- `frontend/src/api/conversation.ts`
- `frontend/src/api/requirements.ts`
- `frontend/src/api/coding.ts`
- `frontend/src/style.css`
- `frontend/vite.config.ts`

### 扩展 / IDE

- `extensions/ruijing-ai/src/*`
- `extensions/ruijing-ai/dist/extension.js`

## 验证情况

已完成的验证包括：

- Python 路由与配置相关文件 `py_compile` 通过
- `frontend` 执行 `npx vite build` 通过
- `extensions/ruijing-ai` 执行 `npm run build` 通过
- 后端健康检查通过
- 前端 dev server 正常启动

## Git 信息

- 分支：`codex/afternoon-model-runtime-polish`
- 提交：`db09490`
- 提交信息：`feat: unify model routing and polish AI workflows`

## 备注

本次提交刻意未包含以下未整理内容：

- `backend/app/harness/` 相关草稿
- `docs/` 下尚未归整的草稿文档
- `.playwright-mcp/`
- 临时脚本和 `.vsix` 产物

这样可以保证本次提交聚焦于“今天下午已完成并验证过的功能与修复”。
