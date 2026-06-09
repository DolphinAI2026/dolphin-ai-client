# 应用管理 (`/apps`)

我的所有应用列表 — local builder 应用 + 平台 remote 应用合并视图。

## 三种应用 source

- **local**：本地搭的，还没部署到平台
- **linked**：本地搭的 + 已部署到平台（双向关联）
- **remote**：直接在平台导入的，本地无 builder 上下文

## 关键操作（每张卡 / 每行）

- **打开应用**：点卡片或行进编辑页（`/chat?app_id=xxx`）— 双栏布局：左栏 dolphin AI 助手对话调整应用，右栏实时 SPEC 视图
- **🤖 AI 调整**（紫色机器人 icon）：跟"打开应用"等价，进编辑页直接打开 dolphin 助手对话
- **跳平台**：在新窗口打开应用在 aPaaS 平台的运行界面
- **部署**：未部署应用一键推到平台
- **成员管理**：管理应用的协作成员（owner / maintainer / contributor / viewer）
- **删除**：仅草稿 / 失败状态可删；已部署应用要先在 DevOps 走下线流程

## 进入 AI 搭建的路由约定

- 未生成应用：`/chat?app_id=123` → 搭建会话视图
- 已生成应用：`/chat?app_id=123&tab=spec&workspace=update` → SPEC 编辑工作台

DevOps 里 sidebar 选应用、首页打开应用，都遵循这个约定。

## 团队 / 个人 / 项目维度

应用支持归属：
- **个人**：只有创建者能看
- **团队**：team 成员能看
- **项目**：project_id 关联项目（项目下管理 git 凭证 / 多应用）
