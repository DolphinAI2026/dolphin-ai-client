# AI Code 主工作台 · Walking Skeleton — 设计 Spec

**日期**：2026-05-28
**分支**：`local/ui-redesign-2026-05-20`
**状态**：待用户评审
**所属**：PRD《AI Coding 整体产品设计》主线 → 子项目 A（主工作台外壳，walking skeleton）
**方向锚**：memory `ai-coding-prd-direction` + `docs/handoff-2026-05-28-ai-coding.md`

---

## 一句话

把现在 `/vibe-coding` 那个"单列聊天 + IDE 切换"的简陋沙箱，换成 PRD ② 的「**左对话主线 + 右 6 标签 + 底部全宽输入**」主工作台外壳。**这一刀只搭骨架**：外壳真做、进度/预览真接，引擎仍用现有单 agent，需求/工具链/可观测先占位。

---

## 背景

当前 ai-code 线有三套并存（详见探查）：

- **live 单 agent**：`/vibe-coding` → `OnlineCodingWorkspacePage.vue` → `online_coding.py` + `vibe_coding_chat.py` → `vibe_coding/agent.run_agent`。点 ai-code 应用现在落这里。产物 = 独立 Next.js/React 应用 + dev server 预览。**这是本刀复用的地基。**
- **休眠 3-agent 流水线**：`coding_v2.py` + `orchestrator/` + `agents/`（Brainstorm→Coding→Verify+autofix），后端完备但**无 live 前端**，且 Spec 场景偏 apaas 产物。本刀**只复用其运行时**（BaseAgent loop / 并行 tool / EventPublisher SSE / TraceWriter）做后续 Swarm，本刀不动。
- **搁置 6-tab 骨架**：`AICodingWorkspace.vue` + `components/ai-coding/WorkspaceTabs.vue`，上一刀错接到低代码 `SpecChatPanel` + 静态 HTML 原型。**本刀复用其左右可拖布局脚手架，重建标签 + 换掉左侧面板。**

**产物方向（已定）**：标准 Web 应用（standalone Next.js/React），延续 vibe-coding 线。

---

## 范围

### 真做（能用）
1. **极简想法入口页**：一个「描述你要做的应用」大输入框 → 创建 workspace + 把这句话作为首条消息 → 跳转新壳。
2. **新工作台外壳**：复用 `AICodingWorkspace.vue` 左右布局；左 = 现有 vibe 聊天；右 = 顶部横向 6 标签；底部 = 全宽输入 composer（方案 B）。成为 ai-code 应用的主工作台页。
3. **「进度」标签**：把现有单 agent 的真实执行事件（tool call / 写文件 / 起服务）渲染成一条执行时间线 / 日志。**真数据。**
4. **「预览」标签**：复用现有 dev server 预览。
5. **路由**：点 ai-code 应用 → 进新壳（按 workspace id 定位）。

### 浅做（占位）
6. **「产出」标签**：嵌现有 code-server IDE（IDE 的新家）。
7. **「需求」「工具链」「可观测」**：占位「建设中」说明，留后续子项目。

### 明确不做（后续子项目）
并行 Swarm DAG（子项目 D）、预览点选改（④深做）、场景推荐 / 原型-MVP-生产路径分级（子项目 B）、需求基线编辑（C）、token/成本统计（F）、6 个治理页。

---

## 目标体验（用户可见，验收即此）

1. 应用列表点「新建 AI 应用」→ 大输入框，打一句"做个报销系统" → 确定。
2. 后台建好 workspace，**直接进入新工作台**，那句话已作为首条消息发出。
3. 工作台 = 左聊天 + 右 6 标签（需求/进度/预览/产出/工具链/可观测）+ 底部全宽输入。
4. AI 开始干活，「进度」标签**实时滚出真实步骤**（读需求 → 写文件 → 启动服务）。
5. 切「预览」看跑起来的应用；切「产出」看/改代码（IDE）。

---

## 架构

### 前端（主战场）

| 部件 | 处理 |
|---|---|
| 入口页 `AiCodeEntryPage.vue`（新） | 想法输入框 → 调 `online_coding` 建 workspace（带首条消息）→ 路由进新壳 |
| 外壳 `AICodingWorkspace.vue`（重写） | 移除 `SpecChatPanel` 导入；改 key 为 workspace id；左插 vibe 聊天，右插 6 标签 + 底部 composer |
| 左侧聊天 | **复用**现有 vibe 聊天（`OnlineCodingWorkspacePage` 里的聊天体 / `vibe_coding_chat` 链路）。需确认能否干净抽到左栏 |
| 6 标签组件（新） | 进度(真)、预览(复用)、产出(IDE)、需求/工具链/可观测(占位) |
| 底部 composer | 全宽输入，接到聊天 send |
| 路由 | ai-code 应用点击目标改指新壳（按 ws id）；`/vibe-coding/workspaces/:id` 老沙箱保留为过渡 fallback |

### 后端（最小改动）

- **复用** `online_coding`（建 workspace + `_register_ai_code_app`）+ `vibe_coding_chat`（`chat/send` SSE）。
- 「进度」标签消费 `chat/send` **同一条 SSE 事件流**渲染时间线。若历史事件需回放，可能加一个轻量读取接口。
- **铁律**：完全不碰 apaas / 低代码（`SpecChatPanel`、`spec_*`、`custom-page`、`SpecDesignPanel`）。

### 数据流

```
想法输入 → 建 workspace(online_coding, 带首条消息) → 跳新壳(wsId)
   → chat/send SSE ─┬→ 左聊天渲染消息
                    └→ 进度标签渲染 tool/file/serve 事件(同一流)
   → 预览标签加载 dev server url
   → 产出标签加载 IDE url
```

### 引擎说明（关键）

本刀干活的仍是**现有单 agent**。「进度」标签按"渲染一条事件流"来设计 —— 这样**以后 Swarm（D）把引擎换成并行多 agent、发出更丰富事件时，进度标签升级成 DAG 视图，无需重构外壳**。外壳为 Swarm 预留了位置。

---

## 验收标准

新建 ai-code 应用 → 想法输入 → 落到新 6 标签工作台 → 跟 agent 说需求 → 「进度」看到真实执行 → 「预览」看到跑起来的应用 → 「产出」打开 IDE。**整条走通 = 本刀完成。**

---

## 待澄清 / 风险（实现时解决）

1. **左聊天可复用性**：现有 vibe 聊天体跟 `OnlineCodingWorkspacePage` 耦合多深？能否干净抽到新壳左栏？（写实现计划前快速核一下）
2. **进度事件结构**：现有 `chat/send` SSE 是否已携带够结构化的 tool/file 事件供进度标签渲染，还是要补字段？
3. **路由 / 主键**：新壳按 workspace id（`oc_...`）定位；ai-code 应用点击 → 取 `source_workspace_id` → 进新壳。

---

## 文件影响（预估）

- **新增**：`AiCodeEntryPage.vue`、6 个标签组件、可能 `useAiCodeWorkspace` composable
- **修改**：`AICodingWorkspace.vue`（重写）、`router/index.ts`（路由 + ai-code 应用点击目标）、应用列表点击处（17cf16b 的分流逻辑）
- **复用**：vibe 聊天组件、预览、IDE url 逻辑、`online_coding` 建 workspace、`vibe_coding_chat` SSE
- **后端**：最小 —— 可能加进度事件读取接口
