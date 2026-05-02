# 常见问题 / FAQ

## 我应该从哪里开始？

**取决于你有什么**：

- 只有想法 → AI 对话（Chat 模式）和 AI 一起聊出来
- 有一堆杂乱材料 → AI 对话（Cowork 模式）整合
- 已经有 PRD / 设计稿 → AI 搭建直接上传 .md
- 要做组件 / 页面扩展 → AI 编码
- 要做完整 Web 应用（带数据库） → Vibe Coding

## AI 对话和 AI 搭建有啥区别？

- AI 对话产出**标准 .md 设计文档**（不直接生成应用）
- AI 搭建吃 .md 或对话产出 **SPEC + 配置 + 应用**

可以跳过 AI 对话直接在 AI 搭建上传 .md。但用 AI 对话整理后的 .md 解析准确率更高，因为它符合 Builder 解析规范。

## 怎么把 AI 对话产出的文档交给 AI 搭建？

- 在 AI 对话的设计文档 inline 卡片上点「→ Builder」按钮
- 或者下载 .md 文件再到 AI 搭建上传

## AI 编码和 Vibe Coding 有啥区别？

| 维度 | AI 编码 | Vibe Coding |
|---|---|---|
| 产物 | 单个组件 / 页面 / 接口 | 完整 Web 应用 |
| 模板 | 严格（5 种 df-apaas-cli 模板） | 自由（任意 Vue + Express 项目） |
| 运行 | 上传到 aPaaS 平台 | Docker 沙箱内独立跑 |
| 数据库 | 没有，依赖 aPaaS 平台 | SQLite / 任意 |
| 谁写 | df-apaas-cli 模板 + AI | 完全 AI |

简单说：Vibe Coding 是"做一个独立产品"，AI 编码是"给 aPaaS 平台加扩展"。

## 怎么把应用部署上线？

1. AI 搭建 → 应用搭好（status=draft）
2. 顶部「部署到预览」按钮 → 配置推到平台（status=completed）
3. 想改 SPEC？编辑后 → DevOps 创建提案 → 评审 → Apply → 自动同步到平台

## 我改了 SPEC 但 DevOps 创建提案按钮亮不了 / 报"无可 promote 的 draft"？

- 确认你在 AI 搭建里**保存了改动**（生成了 `kind='draft'` 的 BuilderSpec）
- 如果改动只在前端 store 里没持久化，后端不会有 draft

## DevOps 提案 promote 后 git 没有自动 push？

- 检查应用是否已绑定 `git_repo_url`（DevOps Git 仓库 tab 看）
- 如果没初始化，先点「初始化仓库」（前提：项目已绑定 Git PAT）

## Vibe Coding 工作区跑不起来 dev server？

- Docker 状态看后端日志
- 工作区会自动跑 `npm install` + 启 dev server，如果失败会在对话流里提示
- 可以让 AI"重启 dev server"或手动在 IDE 终端跑

## 模型怎么切换？

任何 AI 模块的输入框附近都有模型选择器。切换只影响**当前会话之后**的消息。新会话首次发送会用当前选择。

## 找不到我的应用？

- `/apps` 默认 include_remote=true，会拉平台 remote 应用
- 如果平台凭证过期会降级（log 看到 "拉取得帆云应用列表失败"）
- 本地应用永远显示

## 黑暗模式？

左下角太阳 / 月亮按钮切换。状态 localStorage 持久化。

## 命令面板？

`⌘K` 任何页面都能用，搜索 + 快速跳转。
