# 用 Claude Code 构建 AI 低代码平台：aPaaS Builder AI 实践案例

> 本文介绍如何将 Claude Code 深度融入企业级低代码平台的 AI 功能开发全流程，涵盖项目背景、工程实践、效果对比与推广建议。

---

## 一、项目背景

### 1.1 业务场景

**得帆云**是一款面向企业的低代码开发平台（aPaaS），提供数据模型、表单设计、流程编排、权限管理等核心能力。然而，传统低代码平台的学习曲线依然陡峭——用户需要手动配置数十个参数才能搭建一个完整的业务应用。

**aPaaS Builder AI** 正是为解决这一问题而生：通过对话式 AI 助手，让用户用自然语言描述需求，系统自动生成完整的应用配置并一键部署至平台。

### 1.2 核心能力

| 模块 | 功能描述 |
|------|----------|
| **智能搭建** | 多轮对话收集需求 → AI 生成应用配置 → 一键创建数据模型、表单、权限 |
| **Vibe Coding** | 对话式自开发：AI Agent 编写 Vue 组件代码，实时预览，一键上传至平台 |
| **应用管理** | 查询、更新、增量修改已有应用配置 |
| **多环境管理** | 支持多个 aPaaS 平台实例，灵活切换 LLM 供应商 |

### 1.3 技术架构

```
┌─────────────────────────────────────────────────┐
│                   前端（Vue 3）                   │
│  ChatPage · CodingPage · ApplicationsPage        │
└────────────────────┬────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────┐
│                后端（FastAPI）                    │
│  config_assembler → incremental_executor         │
│  VibeCodingAgent → WorkspaceManager              │
└──────┬───────────────────────┬──────────────────┘
       │                       │
┌──────▼──────┐        ┌──────▼──────┐
│  LLM API    │        │  aPaaS API  │
│ MiniMax     │        │ 得帆云平台   │
│ Claude      │        └─────────────┘
│ Qwen / DS   │
└─────────────┘
```

---

## 二、Claude Code 的应用方式

### 2.1 为什么选择 Claude Code

在项目启动初期，团队面临以下挑战：

- **AI 功能复杂**：需要同时实现"配置生成"和"代码编写"两套 Agent 系统
- **aPaaS API 学习成本高**：平台 API 接口众多，参数复杂，文档分散
- **快速迭代压力**：用户反馈需要快速响应，不能有漫长的开发周期

Claude Code 的优势恰好覆盖了这些痛点：**深度代码理解 + 多文件协作编辑 + 长上下文对话**。

---

### 2.2 具体应用场景

#### 场景一：Skills 文档驱动的 API 集成

项目在 `skills/` 目录维护了 **28 个 Markdown 技能文件**，每个文件精确描述一个 aPaaS API 的调用方式、参数规范和注意事项。

```
skills/
├── apaas-create-model-field.md    # 创建数据模型字段
├── apaas-create-dict-value.md     # 创建数据字典值
├── apaas-create-permission.md     # 创建权限组
├── apaas-comp-checkbox.md         # 复选框组件规范
├── apaas-comp-association.md      # 关联字段组件规范
├── apaas-deploy-app.md            # 应用部署流程
└── ...（共 28 个）
```

**使用方式**：将 skill 文件作为上下文喂给 Claude Code，让其在编写 `apaas_client.py` 时精确对应 API 签名，避免参数错误。

**效果**：API 集成正确率从人工查文档的约 60% 提升至首次成功率 90%+。

---

#### 场景二：VibeCodingAgent 的设计与实现

这是项目最核心的 AI 功能——一个能编写 Vue 组件代码的 Agent。

**挑战**：业界常见的 Agent 框架（LangChain、Claude Agent SDK）在国内网络环境下稳定性差，成本高。

**Claude Code 辅助下的解决方案**：

通过与 Claude Code 深度协作，团队从零实现了一套轻量 Agent 框架：

```python
# backend/app/coding/vibe_agent.py
class VibeCodingAgent:
    """
    直接调用 OpenAI 兼容 API，不依赖任何 Agent SDK
    参考 Claude Code 的以下设计：
    - 分层上下文压缩（超过10条消息自动截断早期结果）
    - 循环检测（连续2轮只读不写，自动注入 Nudge）
    - 并行文件写入（强制模型一次写完所有文件）
    """
    async def run(self, task: str) -> AsyncGenerator:
        # 多轮对话循环
        # tool call 执行
        # SSE 实时推送
        ...
```

Claude Code 在这里扮演的角色：
1. **参考自身设计模式**：Claude Code 本身就是一个优秀的 Coding Agent，团队直接向其请教循环检测、上下文压缩的实现思路
2. **快速迭代 Prompt**：system prompt 经过 10+ 轮与 Claude Code 的协作打磨，最终形成稳定版本
3. **工具函数实现**：`read_file`、`write_file`、`edit_file`、`run_command` 等工具函数，由 Claude Code 协助编写并验证安全性

---

#### 场景三：系统提示词（Prompt）工程

`backend/app/coding/prompts.py` 中包含针对 Vibe Coding 场景精心设计的 system prompt，其中多处灵感来源于与 Claude Code 的对话：

| 优化点 | 问题 | 解决方案 |
|--------|------|----------|
| 轮数限制 | Agent 反复读文件，消耗大量 token | "最多 8 轮对话，立即并行写完所有文件" |
| 依赖管理 | 模型手动修改 package.json 导致版本冲突 | "第三方依赖必须用 npm install，禁止手动编辑" |
| 参考隔离 | 模型参考已有组件结构，引入污染 | "不要读取其他组件目录，只看自己的工作区" |
| 错误反馈 | 上传失败信息不透传 | 明确要求原始错误信息直接返回给用户 |

---

#### 场景四：CLAUDE.md 规范治理

项目根目录的 `CLAUDE.md` 文件作为 Claude Code 的"宪法"，规定了 AI 在此项目中的行为边界：

```markdown
# CLAUDE.md（节选）

## 禁止事项
- 禁止参考已有工作区的组件代码（防止污染）
- 禁止手动编辑 package.json（必须用 npm install）
- 禁止生成伪全局变量（this.$xxx 不可用）
- widget.config.js 中的元数据必须与实际功能一致

## 开发规范
- 第三方依赖安装后必须 import，不能假设全局可用
- 组件必须通过 npm run build 验证后再上传
```

这些规则直接来自真实的 Bug 复盘——每次 Claude Code 犯了一个错误，就在 `CLAUDE.md` 中增加一条约束，形成"经验沉淀"机制。

---

#### 场景五：增量更新与配置差异对比

`config_diff.py` 和 `incremental_executor.py` 实现了对已有应用的增量修改能力。这两个模块的设计和实现完全由 Claude Code 协作完成：

1. **需求描述**：用自然语言告诉 Claude Code"我需要比较两个 AppConfig 的差异，找出新增/删除/修改的字段"
2. **方案设计**：Claude Code 输出完整的数据结构设计和算法思路
3. **代码实现**：Claude Code 直接生成 Python 代码，人工审核后合并
4. **测试验证**：Claude Code 帮助编写测试用例，验证边界情况

---

### 2.3 工程化实践

#### CLAUDE.md 的价值

不同于通用 AI 助手，Claude Code 能够读取项目中的 `CLAUDE.md` 文件，将其作为持久化的上下文规范。这意味着：

- 每次新对话无需重复交代背景
- 团队规范自动注入 AI 行为
- Bug 经验自动成为约束条件

#### 多文件协作编辑

Claude Code 的多文件编辑能力使得重构变得简单：

> "将 VibeCodingAgent 的工具执行逻辑从 `vibe_agent.py` 中提取到独立的 `tools.py`，同时保持接口兼容"

这样的任务，传统开发需要手动协调多个文件的修改；Claude Code 能一次性理解依赖关系并完成所有改动。

#### Git 提交规范

项目所有 commit 均遵循 Conventional Commits 规范，Claude Code 在提交时自动生成符合规范的 commit message，团队无需额外约定。

---

## 三、效果对比

### 3.1 开发效率对比

| 任务类型 | 传统开发 | Claude Code 辅助 | 效率提升 |
|----------|----------|-------------------|----------|
| aPaaS API 封装（单接口） | 2-4 小时 | 20-40 分钟 | **4-6x** |
| Agent 工具函数编写 | 1 天 | 2-3 小时 | **4x** |
| Prompt 工程迭代 | 多次人工测试 | 对话式即时调整 | **显著** |
| Bug 定位与修复 | 30-60 分钟 | 5-15 分钟 | **4-6x** |
| 功能模块重构 | 半天至 1 天 | 1-2 小时 | **4-6x** |

### 3.2 代码质量对比

**引入前**：
- API 参数经常遗漏或错误，需要多次调试
- `apaas_client.py` 中存在大量重复的 HTTP 请求模板代码
- 错误处理不一致，部分接口失败后不抛出异常

**引入后**：
- 每个接口首次实现即符合 API 规范（得益于 skill 文件作为上下文）
- 重复代码通过 Claude Code 自动识别并提取为公共方法
- 统一的异常处理模式（Claude Code 在编写新接口时自动沿用）

### 3.3 知识传承对比

| 维度 | 传统方式 | Claude Code 方式 |
|------|----------|-----------------|
| 新人上手 | 需要 1-2 周熟悉代码库 | CLAUDE.md + 对话即可快速定位 |
| API 文档使用 | 频繁切换标签页查文档 | skill 文件作为上下文，AI 自动对应 |
| Bug 经验沉淀 | 散落在 PR 评论、Wiki | 固化在 CLAUDE.md 的约束规则 |
| 技术决策记录 | 依赖会议纪要 | 代码注释 + commit message 自动生成 |

### 3.4 典型案例：Vibe Coding 功能的交付周期

**背景**：Vibe Coding 是项目中技术难度最高的功能——需要实现一个能在沙箱中编写和预览 Vue 组件的 AI Agent。

| 阶段 | 预估（传统） | 实际（Claude Code） |
|------|-------------|---------------------|
| Agent 框架设计 | 3 天 | 0.5 天 |
| 工具函数实现 | 2 天 | 0.5 天 |
| Prompt 调优 | 1 周 | 2 天 |
| 预览沙箱实现 | 2 天 | 1 天 |
| 联调与修复 | 3 天 | 1 天 |
| **合计** | **约 3 周** | **约 5 天** |

---

## 四、推广建议

### 4.1 适合引入 Claude Code 的场景

| 适合 | 不适合 |
|------|--------|
| 有清晰 API 文档的集成工作 | 需要大量人工判断的产品决策 |
| 多文件的重构和代码迁移 | 高度定制化的底层性能优化 |
| 重复性的模板代码生成 | 需要深度领域专家知识的算法设计 |
| 测试用例编写 | 初次接触的全新技术栈探索 |
| Prompt 工程迭代 | 安全敏感的核心加密逻辑 |

### 4.2 落地路径建议

#### 阶段一：个人试用（第 1-2 周）
- 选择一个中等复杂度的功能模块，用 Claude Code 辅助实现
- 观察：哪些任务效率提升最明显？哪些场景 Claude Code 容易出错？
- 产出：个人使用经验文档

#### 阶段二：团队规范（第 3-4 周）
- 建立团队共用的 `CLAUDE.md`，沉淀 API 规范、代码风格、禁止事项
- 建立 skill 文件库，将内部 API 文档转化为 Claude Code 可直接使用的格式
- 产出：`CLAUDE.md` 初版 + skill 文件库

#### 阶段三：流程融合（第 5-8 周）
- 将 Claude Code 纳入日常 Code Review 流程（辅助检查代码规范）
- 建立"Bug → CLAUDE.md 规则"的经验沉淀机制
- 评估 ROI，形成可量化的效率报告

### 4.3 CLAUDE.md 编写建议

好的 `CLAUDE.md` 应该具备以下特征：

```markdown
# 好的 CLAUDE.md 结构

## 项目概述（1段话）
让 AI 快速理解项目是什么

## 技术栈（列表）
明确版本号和选型原因

## 禁止事项（重要！）
来自真实 Bug 的经验教训，越具体越好

## 开发规范
目录结构、命名约定、代码风格

## 常用命令
启动、测试、部署命令

## 注意事项
API 特殊行为、已知坑点
```

**关键原则**：
- **禁止事项优先于规范**：AI 遵守禁令的效果优于遵守正向规范
- **来自真实经验**：每条规则背后都应有一个真实发生过的问题
- **持续更新**：每次 Claude Code 犯新错误，就增加一条新规则

### 4.4 skill 文件最佳实践

将内部 API 文档转化为 skill 文件时，遵循以下格式：

```markdown
# skill: 创建数据模型字段

## 接口
POST /xdap-app/model/field/create

## 参数说明
- fieldName: 字段名（英文，小驼峰）
- fieldType: 字段类型（TEXT/NUMBER/DATE/...）
- required: 是否必填（true/false）

## 注意事项
- fieldName 不能以数字开头
- 关联字段需要额外传 relatedModelId

## 示例
{
  "fieldName": "customerName",
  "fieldType": "TEXT",
  "required": true
}
```

### 4.5 常见误区

**误区一："Claude Code 能替代开发者"**
> 实际上，Claude Code 更像一个"10x 效率的结对伙伴"——它需要开发者提供清晰的需求、审核输出结果、处理边界情况。

**误区二："直接用，不需要额外配置"**
> 没有项目上下文的 Claude Code 效果有限。投入 1-2 天建立 `CLAUDE.md` 和 skill 文件，是获得长期收益的关键投资。

**误区三："生成的代码不需要 Review"**
> Claude Code 偶尔会引入安全漏洞（如命令注入）或逻辑错误。保持 Code Review 习惯，重点关注安全边界和业务逻辑。

**误区四："只能用于新功能开发"**
> 重构、测试、文档生成、Bug 定位往往是 Claude Code ROI 最高的场景。

---

## 五、总结

aPaaS Builder AI 项目是一个"用 AI 构建 AI 产品"的典型案例。

Claude Code 在其中不仅是开发工具，更是**架构决策的协作者**——VibeCodingAgent 的设计借鉴了 Claude Code 自身的 Agent 模式，Prompt 工程的最佳实践来自与 Claude Code 的深度对话，CLAUDE.md 的规则体系则是团队与 AI 共同进化的经验结晶。

**核心结论**：
- Claude Code 在有清晰文档和规范的工程任务上，能实现 **4-6x** 的效率提升
- `CLAUDE.md` + skill 文件库是投资回报最高的配置工作
- "Bug → 规则"的经验沉淀机制让 AI 越用越聪明
- 适合在有一定工程规范的团队中推广，而非替代工程规范

---

*项目线上地址：[agent.dfy.definesys.cn/ai-builder](https://agent.dfy.definesys.cn/ai-builder/)*
*技术栈：Vue 3 + FastAPI + Claude / MiniMax + 得帆云 aPaaS*
