# aPaaS Builder AI Harness 统一改造内部评审文档 v1

## 1. 文档目的

本文档用于 `apaas-builder-ai` 的内部架构评审，目标是回答以下问题：

1. 我们当前系统已经具备哪些能力。
2. 当前四块业务能力的边界、实现方式和主要问题是什么。
3. 为什么现在需要引入统一 Harness Core，而不是继续在四条链路上各自演进。
4. 统一改造后的目标架构是什么。
5. 这次改造具体要改哪些模块、数据表、接口和页面。
6. 实施应如何分阶段推进，才能做到可落地、可回退、不中断业务。

本文档既面向产品/业务负责人，也面向前后端、平台集成和架构负责人。


## 2. 一页结论

### 2.1 当前系统结论

`apaas-builder-ai` 目前不是单一产品流，而是四块业务能力并行存在：

1. 智能搭建
2. 辅助搭建
3. 智能开发
4. 需求分析

这四块能力已经形成了可用产品，但它们在运行时层面仍是分裂的：

- 智能搭建有自己的 SSE 阶段式生成与执行逻辑
- 辅助搭建暂时主要依赖 iframe 嵌入平台后台
- 智能开发有自己的 agent loop、workspace、tool 调用和 IDE 接入
- 需求分析有自己的对话和文档生成链路

从产品上看，这是”四块能力”；从系统实现上看，这是”四套半运行时”。

### 2.2 核心问题

当前的核心问题不是“某一块能力不足”，而是：

- 运行时分裂
- 事件协议分裂
- 工具体系分裂
- 审批策略缺失统一抽象
- artifact 和可观测性没有统一模型
- 辅助搭建长期停留在 iframe 过渡态
- 模型适配分裂：不同模块使用不同 LLM API 格式（Anthropic 原生 /v1/messages vs OpenAI 兼容 /chat/completions），导致环境变量冲突

### 2.3 评审建议

建议将 `apaas-builder-ai` 的下一阶段架构正式定义为：

**一个平台级 Harness Core + 四个业务 profile**

- `builder_profile`
- `platform_profile`
- `coding_profile`
- `requirements_profile`

而不是：

**四块业务分别继续长成四套独立 runtime**

### 2.4 本次评审建议通过的事项

建议本次评审重点确认以下事项：

1. 四块业务统一接入 Harness Core 的方向是否成立。
2. 迁移顺序是否按”智能开发 -> 智能搭建 -> 辅助搭建 -> 需求分析”推进。
3. 第一阶段是否接受”前端入口不改、后端先统一”的策略。
4. 是否同意为 Harness Core 新增独立数据表。
5. 是否同意辅助搭建短期保留 iframe，但中期必须演进为真实的 `platform_profile`。
6. 是否同意把审批作为统一 runtime 必做能力，而不是等后面补。
7. 是否同意需求分析模块作为第四个 profile 接入 Harness Core。


## 3. 产品现状与业务边界

## 3.1 当前产品由四块主业务能力组成

### A. 智能搭建

产品定位：

- 通过对话、文档解析和配置预览，帮助用户快速生成和部署低代码应用

当前用户入口：

- `ChatPage`

当前输出对象：

- 应用概览
- 数据模型
- 表单配置
- 流程配置
- 权限配置
- 文档版本
- 增量变更计划
- 平台部署结果

### B. 辅助搭建

产品定位：

- 在应用已经部署到平台后，辅助用户进入平台后台做进一步配置与操作

当前用户入口：

- `ChatPage` 中的 `辅助搭建` tab

当前主要承载方式：

- iframe 嵌入平台后台页面

当前本质：

- 一个过渡态方案
- 更像“低代码后台嵌入视图”，而不是“平台操作智能体”

### C. 智能开发

产品定位：

- 为组件、页面、接口等自开发内容提供 AI 生成、工作区管理、代码对话和 IDE 入口

当前用户入口：

- `CodingPage`
- 在 `ChatPage` 中通过 iframe 打开 `CodingPage`
- 通过 `ProjectOverview` 进入项目级 coding 入口

当前输出对象：

- 工作区
- 代码文件
- 预览页面
- debug 结果
- 构建包
- 发布包
- IDE 会话入口


### D. 需求分析

产品定位：

- 通过苏格拉底式多轮对话，帮助用户梳理业务需求，生成结构化设计文档

当前用户入口：

- `RequirementsPage`

当前输出对象：

- 需求会话
- 结构化设计文档

代码：

- `backend/app/routes/requirements.py`
- `frontend/src/views/RequirementsPage.vue`


## 3.2 当前还有一批关键支撑模块

这些不是主业务 tab，但对整体系统是关键底座：

- 对话与消息体系
- 应用管理
- 项目管理
- 项目成员协作
- 平台环境管理
- LLM 模型配置管理
- 文档版本管理
- 变更计划管理
- 增量执行
- API 调用日志
- 组件市场

这些模块意味着：

`apaas-builder-ai` 已经不是简单 demo，而是一个具备“平台化产品雏形”的系统。


## 4. 当前功能清单

本节从产品能力角度盘点现有功能，作为后续统一改造的基线。

## 4.1 智能搭建现有功能清单

### 4.1.1 对话与上下文

- 支持创建 builder 类型对话
- 支持对话历史切换
- 支持关联应用的对话列表
- 支持用户多轮补充需求
- 支持消息流式返回

### 4.1.2 文档驱动搭建

- 支持上传 `.md` 设计文档
- 支持 AI 解析文档为 preview 配置
- 支持首次上传文档创建对话
- 支持同一对话下的文档版本迭代
- 支持文档 V1/V2 章节级 diff
- 支持只解析变化章节
- 支持基于上一版结果合并配置

### 4.1.3 配置生成

- 支持分阶段生成配置
- 支持 skeleton 阶段
- 支持 dicts 阶段
- 支持 models 阶段
- 支持 complete 阶段
- 支持生成过程 SSE 进度输出
- 支持 preview 写回应用配置

### 4.1.4 预览面板

当前预览面板包含这些 tab：

- docs：文档版本
- overview：应用概览
- models：模型配置
- forms：表单预览/配置
- workflow：流程预览
- perms：权限预览

### 4.1.5 配置编辑

- 支持角色增删
- 支持数据字典增删改
- 支持模型局部 patch
- 支持 workflow / permission 的 patch 应用
- 支持配置变更后重新部署

### 4.1.6 部署与执行

- 支持从 preview 配置生成平台应用
- 支持部署面板分步骤执行
- 支持一键执行全部步骤
- 支持单步执行/重试/重做
- 支持查看应用
- 支持查看 API 日志

### 4.1.7 文档版本与增量更新

- 支持文档版本列表
- 支持版本预览
- 支持版本 diff
- 支持 Change Plan
- 支持对 Change Plan 勾选确认
- 支持执行变更计划
- 支持增量 diff 预览
- 支持增量执行进度展示

### 4.1.8 异常处理

- 支持部分编码冲突修复交互
- 支持平台未连接提醒
- 支持 Token 过期时的部分自动刷新与失败提示


## 4.2 辅助搭建现有功能清单

### 4.2.1 平台环境能力

- 支持平台环境 CRUD
- 支持环境连接测试
- 支持账号密码登录平台获取 token
- 支持设为默认环境
- 支持按租户隔离环境配置

### 4.2.2 应用与平台关联

- 应用可绑定平台环境
- 已部署应用可获取嵌入 URL
- 支持从应用上下文定位平台页面

### 4.2.3 ChatPage 中的辅助搭建入口

- 支持在 ChatPage 中显示 `辅助搭建` tab
- 支持获取 iframe embed URL
- 支持首次登录提示
- 支持在 iframe 中加载平台后台
- 支持跳转到应用配置页
- 支持在新窗口打开平台

### 4.2.4 当前不足

当前辅助搭建的核心不足是：

- 没有独立 AI runtime
- 没有平台只读工具集
- 没有平台写工具集
- 没有页面/对象状态理解
- 没有浏览器自动化闭环

也就是说：

当前“辅助搭建”功能上可用，但架构上仍然是过渡态。


## 4.3 智能开发现有功能清单

### 4.3.1 场景与脚手架

- 支持开发场景列表
- 支持场景识别
- 支持模板生成
- 支持创建工作区
- 支持按项目类型生成脚手架
- 支持 df-apaas-cli 标准模板脚手架（表单组件/菜单页面/列表视图/页面布局/前端插件）

### 4.3.2 工作区管理

- 支持列出工作区
- 支持打开已有工作区
- 支持按项目查看工作区
- 支持删除工作区
- 支持读取工作区关联对话

### 4.3.3 智能开发对话

- 支持 `auto-pipeline`
- 支持 detect-scene -> create-workspace -> generate 的链路
- 支持 iteration 模式
- 支持携带工作区上下文继续修改
- 支持流式返回 tool 调用过程
- 支持流式返回 thinking / delta
- 支持实时对话流展示 AI 编码过程（stream-pane）

### 4.3.4 Agent 能力

当前 coding agent 已具备：

- autonomous agent loop
- 工具调用
- 文件读写
- shell 命令执行
- glob
- grep
- 重复读取拦截
- 上下文压缩
- loop 检测与 nudge
- 断线后 SSE 重连回放
- 支持 Claude Sonnet 4.6 via jieko.ai 作为编码模型

### 4.3.5 IDE / Web IDE

- 支持生成 IDE URL
- 支持 code-server 场景接入
- 支持把 workspace / token / conversation 上下文注入 IDE
- 支持 IDE 内聊天模型选择
- 支持 IDE image context

### 4.3.6 代码资产能力

- 支持列出文件
- 支持读取文件
- 支持写文件
- 支持源码 zip 下载
- 支持 dist zip 下载
- 支持 marketplace 发布组件

### 4.3.7 本地运行与预览

- 支持 install
- 支持 build
- 支持 serve 启停
- 支持 serve 状态查询
- 支持 preview
- 支持 preview sandbox
- 支持构建产物分发

### 4.3.8 Debug 能力

- 支持 debug 模式选择
- 支持 app debug
- 支持 platform debug
- 支持浏览器预览页
- 支持 debug 截图访问
- 支持平台注入和联调

### 4.3.9 输入增强

- 支持上传文档/图片类附件
- 支持图片上下文
- 支持 suggestion 快速发起


## 4.4 项目级与支撑能力清单

### 4.4.1 项目管理

- 支持项目 CRUD
- 支持项目连接平台
- 支持获取平台应用列表
- 支持项目成员管理
- 支持项目工作区列表
- 支持从项目总览进入“应用搭建 / 组件开发 / 页面开发”

### 4.4.2 平台环境管理

- 支持环境列表
- 支持环境创建
- 支持环境更新
- 支持环境删除
- 支持测试连接
- 支持登录
- 支持设默认环境
- 支持 embed URL 获取

### 4.4.3 模型配置

- 支持 LLM 配置 CRUD
- 支持测试模型连接
- 支持设默认模型
- 支持按用途区分 builder/coding/all

### 4.4.4 组件市场

- 支持市场列表
- 支持发布组件
- 支持下载组件
- 支持下架组件
- 支持查看我发布的组件


## 4.5 需求分析现有功能清单

### 4.5.1 会话管理

- 支持创建需求分析会话
- 支持会话列表
- 支持多轮对话

### 4.5.2 需求对话

- 支持苏格拉底式引导提问
- 支持流式 AI 回复

### 4.5.3 文档生成

- 支持根据对话内容生成结构化设计文档

### 4.5.4 当前不足

- 没有与智能搭建的衔接
- 没有纳入统一 runtime


## 5. 当前系统架构现状

## 5.1 前端现状

当前前端核心页面：

- `Landing`
- `ChatPage`
- `CodingPage`
- `ProjectOverview`
- `PlatformEnvs`
- `Apps`
- `MarketplacePage`
- `RequirementsPage`

现状特点：

- `ChatPage` 同时承载“智能搭建 + 辅助搭建 + 智能开发嵌入入口”
- `CodingPage` 是相对独立的 coding runtime UI
- `ProjectOverview` 是项目级工作台入口

前端问题：

- ChatPage 职责过重
- ChatPage 同时管理 builder 状态、platform iframe 状态、coding iframe 状态
- ChatPage 和 CodingPage 使用不同的 runtime 事件语义
- 现有前端没有统一 harness event adapter


## 5.2 后端现状

当前后端核心 route 模块：

- `chat.py`
- `applications.py`
- `coding.py`
- `platform_envs.py`
- `projects.py`
- `requirements.py`
- `conversations.py`

现状特点：

- `chat.py` 直接承载 builder 生成流程
- `applications.py` 直接承载应用生成、文档版本、change plan、增量执行
- `coding.py` 同时承载模型路由、workspace、agent、SSE、IDE 接入、preview/debug/publish

后端问题：

- route 层承载了过多 orchestration 逻辑
- builder 与 coding 两条链路没有共享 runtime
- model adapter 没有统一抽象
- approvals 没有统一抽象
- artifact 没有统一模型


## 5.3 数据模型现状

现有核心表：

- `conversations`
- `messages`
- `applications`
- `projects`
- `project_members`
- `platform_envs`
- `document_versions`
- `change_plans`
- `llm_configs`
- `api_call_logs`
- `marketplace_components`

现状特点：

- 会话模型已存在
- 应用模型已存在
- 文档版本与变更计划已存在
- 但缺少统一 runtime 级别的 thread / turn / item / artifact / approval 模型


## 5.4 执行流现状

### 智能搭建执行流

用户 -> ChatPage -> chat / applications 路由 -> 分阶段生成 / 变更执行 -> preview / deploy / logs

### 辅助搭建执行流

用户 -> ChatPage platform tab -> 获取 embed URL -> iframe 平台后台

### 智能开发执行流

用户 -> CodingPage -> auto-pipeline -> VibeCodingAgent -> tools/workspace -> IDE/preview/debug

### 需求分析执行流

用户 -> RequirementsPage -> 创建会话 -> 多轮苏格拉底式对话 -> 生成结构化设计文档

现状结论：

当前四块业务都已经有”执行流”，但没有统一执行内核。


## 6. 现状问题分析

## 6.1 运行时分裂

这是当前最核心的问题。

表现：

- builder 自己维护阶段生成与执行链路
- coding 自己维护 agent loop
- platform 仍然主要靠 iframe

结果：

- 无法共享 thread / turn / item 语义
- 无法共享 approval
- 无法共享 artifact
- 无法统一做 replay 和 observability


## 6.2 route 过重

尤其是 `coding.py` 和 `applications.py`。

问题表现：

- route 层中有大量 orchestration
- route 层直接操作模型协议适配
- route 层直接输出 SSE 细节
- route 层难以测试和复用


## 6.3 事件协议分裂

表现：

- builder 有自己的 phase/progress 语义
- coding 有自己的 `agent_tool / agent_thinking_delta / agent_done`
- incremental 又有自己的 `stage/status/step`

结果：

- 前端页面里有大量硬编码 if-else 分支
- 难以统一接入新 mode
- 难以做统一历史回放和审计


## 6.4 辅助搭建长期停留在过渡态

当前辅助搭建能用，但不是长期可持续架构。

主要问题：

- AI 不理解平台当前状态
- 没有对象级/资源级抽象
- 没有写操作工具
- 没有审批
- 没有浏览器操作闭环

如果不引入统一 Harness Core，辅助搭建很难真正演进为“平台操作智能体”。


## 6.5 工具体系没有统一策略中心

表现：

- coding tools 自己定义
- builder 的执行工具散落在不同 service
- platform tools 基本还没形成体系

缺失：

- 统一 registry
- 统一 executor
- 统一 policy
- 统一 approval


## 6.6 缺少统一 artifact 体系

现在系统里已经存在很多值得沉淀的运行时产物：

- config diff
- 代码 diff
- 截图
- preview URL
- build 包
- API 调用日志
- 执行日志

但当前它们没有统一归档模型，因此：

- 不利于回放
- 不利于追踪
- 不利于产品化展示


## 6.7 缺少统一的企业可控性

这对后续规模化很关键。

当前不足：

- shell 命令没有统一审批抽象
- 平台写操作没有统一审批抽象
- 发布没有统一审批抽象
- destructive action 没有统一规范


## 6.8 模型适配分裂

表现：

- LLMClient 使用 Anthropic 原生格式（/v1/messages）
- VibeCodingAgent 使用 OpenAI 兼容格式（/chat/completions）
- ANTHROPIC_* 环境变量被多个模块共用导致冲突
- 已临时通过 VIBE_AGENT_* 拆分，但需要统一 adapter

结果：

- 新增模型时需要同时适配两套协议
- 环境变量命名空间混乱，容易配置出错
- 缺少统一的模型路由和适配抽象层


## 7. 为什么现在要引入 Harness Core

不是因为“某一个模块写得不好”，而是因为产品已经进入下一个阶段：

- 不再是单点 AI 功能
- 而是一个包含搭建、操作、开发、需求分析四类 runtime 的平台

当产品进入这个阶段时，统一运行时就会成为新的基础设施。

如果现在不统一，后续会出现：

- builder、platform、coding 继续各自演化
- 每增加一个新模式都要再写一套 event 和 state
- 辅助搭建始终卡在 iframe 形态
- 研发成本和认知成本持续升高


## 8. 目标定义

## 8.1 总体目标

建设一个平台级 Harness Core，统一承载四块业务能力：

- 智能搭建 -> `builder_profile`
- 辅助搭建 -> `platform_profile`
- 智能开发 -> `coding_profile`
- 需求分析 -> `requirements_profile`

## 8.2 目标能力

Harness Core 统一提供：

- thread / turn / item 生命周期
- 模型适配层
- 工具注册与执行
- 上下文组装
- 审批与策略
- artifact 归档
- 事件流与回放
- 可观测性与评估

## 8.3 非目标

第一阶段不做：

- 不推翻现有前端入口结构
- 不删除 iframe fallback
- 不重写全部 builder/coding 业务逻辑
- 不强依赖 OpenAI 官方 App Server


## 9. 目标架构

```text
Frontend
  ChatPage / CodingPage / ProjectOverview / IDE
    ↓
Gateway API
  /harness/threads
  /harness/turns
  /harness/events
  /harness/approvals
    ↓
Harness Core
  manager
  turn runner
  context builder
  event bus
  approvals
  policy
  artifacts
    ↓
Profiles
  builder_profile
  platform_profile
  coding_profile
  requirements_profile
    ↓
Toolpacks
  builder tools
  platform tools
  coding tools
  requirements tools
    ↓
Adapters
  model adapters
  platform adapters
  workspace adapters
```


## 10. 目标功能清单

## 10.1 所有 mode 共享功能

- 统一 thread / turn / item 模型
- 统一事件协议
- 统一 replay / reconnect
- 统一 artifact 展示
- 统一 approval
- 统一日志与 metrics
- 统一 model routing

## 10.2 Builder Mode 目标功能

- 对话式需求理解
- 文档上传与增量文档理解
- phased config generation
- 配置 patch 与结构化变更计划
- 变更选择与确认
- 平台执行 orchestration
- 执行过程 artifact 化
- 平台部署与增量更新纳入统一 runtime

## 10.3 Platform Mode 目标功能

### 第一阶段

- 读取当前平台应用状态
- 读取菜单/模型/字段/表单/流程/权限
- 生成当前状态摘要
- 生成操作建议
- iframe fallback 持续保留

### 第二阶段

- 平台对象级写操作
- 高风险操作审批
- 浏览器自动化补齐设计器能力
- 支持“AI操作 + 人工接管”混合模式

## 10.4 Coding Mode 目标功能

- 工作区管理
- 智能编码 turn
- 工具调用标准化
- 代码 diff / 构建包 / preview artifact
- IDE 接入
- debug / preview / publish 纳入统一 runtime


## 11. 落地方案

## 11.1 新增模块

建议新增：

```text
backend/app/harness/
  contracts.py
  manager.py
  session_store.py
  events.py
  context.py
  policy.py
  approvals.py
  artifacts.py

  core/
    runtime.py
    turn_runner.py

  profiles/
    builder.py
    platform.py
    coding.py
    requirements.py

  models/
    base.py
    openai_chat.py
    openai_responses.py
    minimax.py

  tools/
    registry.py
    executor.py
    builder_tools.py
    platform_tools.py
    coding_tools.py
```

前端新增：

```text
frontend/src/api/harness.ts
frontend/src/lib/harnessEventAdapter.ts
frontend/src/stores/harness.ts
```


## 11.2 数据表改造

建议新增：

- `harness_threads`
- `harness_turns`
- `harness_items`
- `harness_artifacts`
- `harness_approvals`

保留现有：

- `conversations`
- `messages`
- `applications`
- `projects`
- `document_versions`
- `change_plans`

迁移策略：

- 旧表继续作为业务实体和兼容查询入口
- 新表作为 runtime 真正状态源


## 11.3 接口改造

建议新增标准接口：

- `POST /harness/threads`
- `GET /harness/threads/{thread_id}`
- `POST /harness/threads/{thread_id}/turns`
- `GET /harness/threads/{thread_id}/events`
- `GET /harness/threads/{thread_id}/artifacts`
- `POST /harness/approvals/{approval_id}/decide`

兼容策略：

- 现有 `chat.py` builder 接口内部转发到 `builder_profile`
- 现有 `coding.py` auto-pipeline 内部转发到 `coding_profile`
- platform 新增 `platform_profile` 接口，逐步替代 iframe-only 模式


## 11.4 文件级改造重点

### 后端重点改造文件

- `backend/app/routes/chat.py`
- `backend/app/routes/applications.py`
- `backend/app/routes/coding.py`
- `backend/app/coding/vibe_agent.py`
- `backend/app/coding/tools.py`
- `backend/app/config_assembler.py`
- `backend/app/incremental_executor.py`

### 前端重点改造文件

- `frontend/src/views/ChatPage.vue`
- `frontend/src/views/CodingPage.vue`
- `frontend/src/api/coding.ts`
- `frontend/src/api/application.ts`
- `frontend/src/api/platformEnv.ts`


## 12. 分阶段实施方案

## Phase 0：评审定稿

目标：

- 确认方向、边界、迁移顺序、回滚预案

产出：

- 通过本评审文档
- 通过 backlog 拆解文档

## Phase 1：Harness Core 基础设施

目标：

- 建立统一 contracts / manager / events / session store / migrations

产出：

- 能跑最小 thread -> turn -> event 流程

## Phase 2：先迁移智能开发

目标：

- 把 coding runtime 迁入 `coding_profile`

原因：

- 当前智能开发最接近真实 harness
- 工具、workspace、agent loop 已具备基础

产出：

- 智能开发跑在 Harness Core 上
- 旧接口兼容

## Phase 3：迁移智能搭建

目标：

- 把 phased generation、change plan、incremental execute 迁入 `builder_profile`

产出：

- 智能搭建也跑在 Harness Core 上

## Phase 4：辅助搭建从 iframe 过渡到 platform runtime

目标：

- 创建 `platform_profile`
- 先实现平台只读工具

产出：

- 辅助搭建具备“理解平台当前状态”的能力

## Phase 5：迁移需求分析

目标：

- 把需求分析对话和文档生成迁入 `requirements_profile`
- 打通需求分析到智能搭建的衔接链路

产出：

- 需求分析跑在 Harness Core 上
- 需求文档可作为智能搭建的输入

## Phase 6：审批、artifact、前端协议统一

目标：

- 完成 shell / publish / platform write 审批
- 前端接统一 adapter
- artifact 和 observability 完整可用

产出：

- 四个 mode 在同一 runtime 体系下可审计、可回放、可控


## 13. 可执行排期建议

### Week 1

- 评审通过
- 新建 harness 模块
- 设计 DB migration

### Week 2

- 统一事件协议
- SSE 兼容适配器
- 前端 adapter 预埋

### Week 3

- coding_profile 初版
- `coding.py` 兼容接入

### Week 4

- coding tools / model adapters / artifact
- shell / publish 基础策略

### Week 5

- builder_profile 初版
- phased generation 纳入 harness

### Week 6

- change plan / incremental execute 纳入 harness
- builder artifact 接入

### Week 7

- platform_profile 只读能力
- iframe fallback 整合

### Week 8

- platform 写能力基础
- 高风险操作审批

### Week 9

- requirements_profile 初版
- 需求对话和文档生成迁入 harness

### Week 10

- 需求分析到智能搭建的衔接链路
- 统一模型适配 adapter 替代 VIBE_AGENT_* 临时方案

### Week 11

- approval 完成
- artifact 统一归档
- 前端协议统一收尾

### Week 12

- 可观测性与评估接入
- 四 mode 联合验收
- 文档与交接


## 14. 评审决策点

本次内部评审建议明确拍板以下事项：

1. 是否同意以统一 Harness Core 为下一阶段架构方向。
2. 是否同意先迁移智能开发，再迁移智能搭建。
3. 是否同意辅助搭建短期保留 iframe，但明确要求中期升级为 platform runtime。
4. 是否同意新增 runtime 数据表，而不是继续只用 `conversations/messages`。
5. 是否同意 route 层逐步瘦身，只保留 transport 职责。
6. 是否同意把审批作为统一 runtime 必做能力，而不是等后面补。
7. 是否同意需求分析模块作为第四个 profile 接入 Harness Core。


## 15. 里程碑验收标准

## M1：Harness Core 可运行

- 能创建 thread
- 能创建 turn
- 能发事件
- 能回放事件

## M2：Coding Mode 接入完成

- `auto-pipeline` 跑在 Harness Core 上
- CodingPage 不需要大改即可继续工作
- IDE / workspace / preview / debug 能继续工作

## M3：Builder Mode 接入完成

- 文档上传、配置生成、change plan、增量执行都进入统一 runtime
- ChatPage 预览和部署面板继续可用

## M4：Platform Mode 初版完成

- 辅助搭建可以读取平台状态
- 可以生成当前状态摘要和建议
- iframe 仍可作为 fallback

## M5：Requirements Mode 接入完成

- 需求对话和文档生成进入统一 runtime
- 需求文档可流转到智能搭建

## M6：统一可控性完成

- shell / publish / platform write 有审批
- artifact 统一归档
- 核心指标可观测


## 16. 风险与应对

### 风险 1：一次性改动过大

应对：

- 先 coding，后 builder，再 platform
- 保留兼容接口

### 风险 2：前端改动范围过大

应对：

- 先做 adapter，不先改页面结构

### 风险 3：辅助搭建一直停留在过渡态

应对：

- 把 `platform_profile` 单独作为明确里程碑

### 风险 4：运行时与业务实体状态不一致

应对：

- 新 runtime 表作为状态源
- 老表保留兼容语义


## 17. 建议结论

从现状看，`apaas-builder-ai` 已经具备足够的产品复杂度，必须从“功能拼接阶段”进入“统一运行时阶段”。

建议本次评审结论为：

**通过 Harness 统一改造方向，并按”智能开发 -> 智能搭建 -> 辅助搭建 -> 需求分析”的顺序推进。**

同时要求：

- 第一阶段必须保守迁移，保证现有入口可继续工作
- 第二阶段必须把 builder 接入统一 runtime
- 第三阶段必须推动辅助搭建脱离纯 iframe 过渡态
- 第四阶段必须把需求分析接入统一 runtime，并打通到智能搭建的衔接


## 18. 关联文档

- `docs/internal/HARNESS_UNIFICATION_PLAN_V1.md`
- `docs/internal/HARNESS_UNIFICATION_BACKLOG_V1.md`

