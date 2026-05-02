# aPaaS Builder AI 产品总览

aPaaS Builder AI 是一个面向应用搭建的 AI 协作平台，把"从需求到上线"的全流程拆成几个 AI 模块，每个模块解决一段具体问题，最终通过 DevOps 串成完整交付链路。

## 一句话定位

**用对话生成应用，用对话维护应用。** 用户对 AI 描述需求 / 上传资料 / 给反馈，AI 帮你产出设计文档、SPEC、配置、组件代码、甚至完整全代码沙箱里的 Vue + Express 应用，最后通过 DevOps 走审批 → Apply → Git 沉淀 → 部署到平台。

## 主要模块（左侧导航顺序）

| 入口 | 路由 | 主要解决 |
|---|---|---|
| 首页 | `/` | 入口聚合页（最近项目 / 推荐场景） |
| 应用 | `/apps` | 我的所有应用列表（local + 平台 remote 合并） |
| **AI 对话** | `/ai-chat` | 用对话和 AI 一起梳理需求 / 整合材料 → 产出标准设计文档 |
| **AI 搭建** | `/chat` | 把设计文档喂给 AI → 生成 SPEC / 模型 / 表单 / 流程 → 部署到平台 |
| **AI 编码** | `/coding` | 让 AI 写自开发组件 / 页面 / 接口（睿鲸 IDE）|
| **Vibe Coding** | `/vibe-coding` | 全代码沙箱：AI 直接搭 Vue + Express 应用，Docker / Podman 隔离运行 |
| **沙箱监控** | `/vibe-coding/sandboxes` | 管理跑着的 Vibe Coding 沙箱容器（启动 / 停止 / 删除），按角色分级权限 |
| DevOps | `/devops` | 提案 / 审批 / Apply / Git 同步 / 环境拓扑 |
| 设置 | `/platform-envs` | LLM 模型 / 平台环境 / 成员管理 |

## 4 段独立的 AI 流水线

不是一个超级 Agent 干所有事，而是 4 段各负其责，可以单独使用，也能串起来：

```
需求 ──[AI 对话]──> 设计文档.md ──[AI 搭建]──> SPEC + 配置 ──> 部署到平台
                                       │
                                       └──[DevOps]──> 提案 → 审批 → Apply → Git
                
组件需求 ──[AI 编码]──> 自开发组件代码 ──> aPaaS 平台
完整应用 ──[Vibe Coding]──> Docker 沙箱里跑的 Vue + Express
```

## 核心概念

- **应用 (Application)**：低代码应用，包含模型、表单、角色、字典、流程
- **SPEC**：应用的结构化设计描述（Pydantic 文档），分 `canonical`（已上线）和 `draft`（草稿）两种
- **提案 (ChangeProposal)**：把 draft 推到上线前的审批单元
- **平台环境 (PlatformEnv)**：得帆云 aPaaS 的目标环境，应用最终部署到这里
- **工作区 (Workspace)**：AI 编码 / Vibe Coding 的代码工作目录

## 谁应该用什么

- **从零搭一个企业应用**：AI 对话（梳理）→ AI 搭建（搭起来）→ DevOps（上线）
- **已有 PRD 想直接落地**：AI 搭建（直接上传 .md）
- **要写一个表单组件 / 页面**：AI 编码
- **要做一个完整的 Web 应用（带数据库 / 后端 API）**：Vibe Coding
- **管线上版本 / 审批 / 回滚**：DevOps
