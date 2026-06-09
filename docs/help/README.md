# aPaaS Builder AI 知识库

这个目录是 AI 助手 (`HelpAssistant`) 的知识源。`docs/help/*.md`（除本文件）会在 backend 启动时合并为 system prompt 注入到对话上下文。

## 文件清单

- `00-overview.md` — 产品总览、模块关系
- `01-ai-chat.md` — AI 对话（Chat / Cowork 模式 + 设计文档产出）
- `02-ai-builder.md` — AI 搭建（SPEC 4 阶段流水线）
- `03-coding.md` — AI 编码 / 睿鲸 IDE（自开发组件 / 页面）
- `04-vibe-coding.md` — Vibe Coding（全代码沙箱）
- `05-apps.md` — 应用管理
- `06-devops.md` — DevOps（提案 / 审批 / Apply / Git / 环境）
- `07-settings.md` — LLM / 平台环境 / 成员
- `08-faq.md` — 常见问题

## 维护准则

- 每个文件控制在 200-400 行内（避免 prompt 太长）
- 改产品功能后**同步更新对应章节**（特别是新加 tab / 新加按钮 / 改默认行为）
- 保持"人话"风格，不堆术语；目标读者：第一次用产品的人
