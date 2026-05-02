# Vibe Coding (`/vibe-coding`)

**对话式全代码开发——AI 给方案建议，你拍板，沙箱里跑代码。** 类似 Claude Code / Codex / Lovable 的开发体验。

## 核心特点

- **完整应用**：不是组件，是带前端 + 后端 + 数据库的完整 Web 应用
- **Docker 沙箱**：每个工作区一个隔离容器，独立运行，互不影响
- **9 个工具的 Agent loop**：read_file / write_file / edit_file / run_command / list_dir / search_files / todo_write / ask_clarifying_question / present_plan
- **Split preview**：对话区右边可拆出预览面板，看 dev server 跑起来的效果（前端 :6173 / 后端 :6300 等）
- **多模态输入**：图片可粘贴（截图 → AI 看着图开始改）

## 默认进入体验

`/vibe-coding` 直接进入工作台 layout：左侧 sidebar 列出所有工作区，右侧是新建工作区表单（无 id 时）或当前工作区主区。

## 两种新建方式

- **从零开始**：留空 Git 地址，AI 从空目录脚手架开始搭
- **导入 Git 仓库**：填 Git 地址 + Token（如私仓），AI 在已有仓库基础上增改

> Git 不是前置项，可以开发完再提交。

## 典型流程

1. `/vibe-coding` 进入 → 看到左侧已有工作区 + 右侧"新建"表单
2. 填"开发目标"（如"做一个报销系统"），可选填 Git 仓库
3. 点"直接打开 IDE 开始对话开发" → 进入对话视图
4. AI 先用 `present_plan` 给方案：技术栈选型 + 任务清单
5. 你说"继续" → AI 按任务清单依次写代码 + 运行 dev server
6. 任务完成后右上"预览"按钮亮 → 打开 split preview 看跑起来的效果
7. 不满意继续对话，AI 改

## 视图

- **对话**：默认视图，看消息流 + 工具调用 + 任务清单 + ask_user
- **IDE**：code-server 直接编辑代码
- **预览**：split panel 在右侧，可拖拽宽度，多端口（前端 / 后端）切换

## 默认进入体验

打开任一工作区**默认是 chat 视图**，IDE 由你主动切（避免 IDE iframe 一上来就接管屏幕）。如果 URL 带 `?view=ide`（比如刷新前你在 IDE 视图），会保留 IDE 视图。

## 已知能力上限

- 单工作区文件系统隔离，资源充裕
- Agent loop 思考过程透明可见
- 任务清单实时更新（`todo_write` 工具）
- 每条 ask_user 都是一个可点击的选项卡

## 与 AI 编码的差异

- Vibe Coding = 完整应用、自由度高、Docker 沙箱
- AI 编码 = 单组件 / 单页面、模板严格、产物上传到 aPaaS 平台
