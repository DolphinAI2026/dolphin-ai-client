# AI Code 需求基线（③）— 设计 Spec

**日期**：2026-05-28
**分支**：`local/ui-redesign-2026-05-20`
**状态**：待用户评审
**所属**：PRD《AI Coding 整体产品设计》主线 → 子项目 C（③需求基线 tab）
**前置**：子项目 A（walking skeleton 主工作台）已完成 —— 6 标签壳 + 进度/预览/产出已接。本刀填「需求」tab。

---

## 一句话

给 vibe 单 agent 加一个 `requirement_write` 工具（**完全照搬现成的 `todo_write` 机制**），让 AI 边聊边把需求结构化成「需求基线」（6 项），实时显示在只读的「需求」tab；改需求走对话（AI 再调工具更新）。**不阻塞编码、不做 tab 内编辑、不做确认闸门。**

---

## 决策（brainstorm 已定）

| 维度 | 决策 |
|---|---|
| 角色定位 | **活文档** —— AI 边聊边结构化，实时显示，非阻塞 |
| 生成机制 | **新增 agent 工具 `requirement_write`**，照搬 `todo_write`（存 thread + SSE 实时渲染） |
| 字段 | PRD 6 项：角色 / 功能 / 流程 / 外部交互 / AI决策点 / 验收标准（后两项简单应用可空） |
| 编辑方式 | 「需求」tab **只读**；改需求在对话里说 → AI 调 `requirement_write` 更新 → tab 刷新 |
| v1 不做 | tab 内直接编辑、确认闸门、结构化富条目 |

---

## 数据 schema

`requirement_baseline` —— 每项一个**字符串数组**（v1 求稳；结构化条目以后再说）：

```json
{
  "roles":      ["管理员 — 管理用户与权限", "员工 — 提交报销单"],
  "features":   ["报销单提交", "主管审批", "财务打款", "统计看板"],
  "flows":      ["员工提交 → 主管审批 → 财务打款 → 归档"],
  "external":   [],
  "ai_points":  [],
  "acceptance": ["提交后主管能看到待审", "驳回需填原因"]
}
```

字段固定 6 个 key；值为 `string[]`，可空数组。存储位置见下（thread JSON 列，跟 `todos` 并排）。

---

## 后端（3 处改动 + 1 处序列化，全部对照 `todos` 现成实现）

> **实现参照锚点**（写计划时逐一读取对齐）：
> - 工具定义：`backend/app/vibe_coding/tools.py` 里的 `todo_write`
> - agent loop SSE：`backend/app/vibe_coding/agent.py:475-476`（`todos_updated`）+ `ask_clarifying_question`/`todo_write` 的特判（agent.py:460-476）
> - 模型字段：`VibeCodingThread.todos`（models）
> - 序列化：`vibe_coding_chat` 的 `getThread` 返回 thread（含 todos）

1. **模型**：`VibeCodingThread` 加 `requirement_baseline` JSON 列（默认 `{}` 或带 6 个空数组的 dict）。启动迁移自动加列（跟 app_type 那次同款）。
2. **工具 `requirement_write`**（`tools.py`）：参数 = 6 个 `string[]`（roles/features/flows/external/ai_points/acceptance），**整体覆盖式**写入 `thread.requirement_baseline`。返回简短确认。
3. **agent loop**（`agent.py`）：工具成功后 `yield _sse("requirement_updated", {"requirement": thread.requirement_baseline})`，与 `todos_updated`（agent.py:475-476）并列。
4. **序列化**：`getThread` 返回的 thread 带上 `requirement_baseline`。
5. **prompt**（`prompts.py`）：在"澄清完、todo_write 之前/之后"加规则 —— 调 `requirement_write` 把需求结构化记录；需求有变（用户改、范围调整）就再调更新。给出 6 字段含义 + 简单应用 external/ai_points 可空。

---

## 前端（1 新组件 + 2 处接线）

1. **新建 `frontend/src/components/ai-coding/RequirementTab.vue`**：
   - props `{ workspaceId: string }`
   - `vibeCodingChatApi.getThread(wsId)` → 读 `thread.requirement_baseline`
   - **只读**渲染 6 个分区（角色/功能/流程/外部交互/AI决策点/验收标准），每区一组条目；空区不显示或显示"—"
   - 全空时空态："AI 还没产出需求基线 —— 去左边描述你的应用"
   - 挂载拉一次 + AI 运行时轮询刷新（跟 `ProgressTab` 同款 2s 轮询 + busy 判断；或复用 thread 拉取）
2. **`WorkspaceTabs.vue`**：`requirement` 分支从占位换成 `<RequirementTab :workspace-id="workspaceId" />`。
3. **类型**：`vibeCodingChat.ts` 的 `VibeChatThread` 加 `requirement_baseline: { roles:string[]; features:string[]; flows:string[]; external:string[]; ai_points:string[]; acceptance:string[] }`。

---

## 数据流

```
描述应用 → AI 澄清 → AI 调 requirement_write(6字段)
   → 写 thread.requirement_baseline + SSE requirement_updated
   → 「需求」tab 实时渲染
用户："加个管理员角色" → AI 调 requirement_write(更新后的基线) → tab 刷新
基线 = AI 自己的上下文（它产出的，在对话历史里）→ 指导后续编码
```

---

## 验收标准

描述一个应用 → AI 澄清后，「需求」tab 出现结构化的角色/功能/流程/验收（真数据，AI 调 `requirement_write` 产生）→ 在对话里说"加一个 X 角色" → tab 实时多出该角色。端到端走通 = 本刀完成。

---

## 铁律 / 非目标

- 只动 vibe-coding / ai-code（`vibe_coding/*`、ai-coding 前端组件）。不碰 apaas / 低代码。
- 不做 tab 内直接编辑、确认闸门。

---

## 待澄清 / 风险（实现时解决）

1. **todo_write 的覆盖语义**：确认 `todo_write` 是整体覆盖（requirement_write 照此），还是增量；对齐。
2. **基线是否需回灌 agent 上下文**：v1 靠"AI 自己产出、在历史里"即可；若发现跨多轮后 AI 忘了基线，再考虑把当前基线注入 system 提醒（留作增强）。
3. **轮询 vs 事件**：RequirementTab v1 用轮询（同 ProgressTab）；后续可改成监听 SSE `requirement_updated`。
