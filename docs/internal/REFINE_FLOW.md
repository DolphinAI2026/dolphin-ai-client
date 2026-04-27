# Spec 版本链 / Refine 流程（前后端契约）

> 写于 2026-04-24。前端 v2、后端 coding_v2 路由。
>
> **核心模型**：用户和 AI 共同共创一份契约，每次纠正/迭代产出一个新版本。
> 对话里所有 Spec 版本按时序列出，永远只有最新一版可操作（确认生成代码），
> 历史版本永久保留并以折叠形式展示。

---

## 1. 数据模型

### 1.1 后端（DB）

`spec` 表存的就是版本链：每条记录是一版独立 Spec。
- `id`：spec_id（如 `spec_20260424xxx_xxxxxx`）
- `version`：本版本号（1, 2, 3, ...）
- `parent_version`：从哪一版派生（首版为 NULL）
- `brainstorm_session_id`：归属的 brainstorm 会话
- `content`：完整 envelope JSON

一条 brainstorm 会话可能产出多个 Spec 版本（用户在 CONFIRM 阶段反复 refine）。
`brainstorm_session.final_spec_id` 只在用户**点过确认**之后才写入，所以**不能**当作"该会话最新 Spec"的索引——要找最新 Spec，用 `spec_service.get_latest_spec_for_session(bs_id)`（按 version DESC 取一条）。

### 1.2 前端（store.specVersions）

```ts
interface SpecCardData {
  spec_id: string
  version: number
  parent_version: number | null
  envelope: SpecEnvelope | null      // 异步拉取，null 时显示骨架屏
  emitted_at: number
  source: 'brainstorm_initial' | 'brainstorm_iterate' | 'trivial_patch'
  rationale: string | null           // 一行变更摘要（trivial 来自 classification.rationale）
  isLatest: boolean                  // 全局有且只有一张 true
  isConfirmed: boolean               // 用户点过确认 → 进入了代码生成
  collapsed: boolean                 // UI 折叠状态
}
```

`store.specVersions` 是按 `emitted_at` 升序排列的版本列表。
`store.currentSpec` / `store.currentSpecId` 已降级为 computed，等价于"isLatest 那张卡"。

**架构不变量**：版本只增不删；`isLatest` 始终只有一张 true（或全部 false，初始状态）。

---

## 2. 事件契约

### 2.1 `brainstorm.spec_emitted`（emit_spec tool 触发）

发自：`orchestrator/driver.py` 的 `drive_brainstorm`，在 Spec 持久化后立刻发。

```json
{
  "spec_id": "spec_20260424xxx_yyyyyy",
  "scene_type": "web_component_dual",
  "confidence": 0.85,
  "version": 2,
  "parent_version": 1,        // null = 首版
  "core_purpose": "用户的核心意图一句话总结"
}
```

前端处理：调用 `pushSpecVersion`，`source = parent_version ? 'brainstorm_iterate' : 'brainstorm_initial'`。

### 2.2 `iteration.trivial_patched`（trivial 分类触发）

发自：`routes/coding_v2.py` 的 `_run_iterate_dispatch_task`，`classify_iteration` 判定 `level=trivial` 时。

```json
{
  "new_spec_id": "spec_20260424xxx_yyyyyy",
  "new_version": 3,
  "parent_version": 2,
  "patch_ops_count": 2,
  "rationale": "明确现有配置项的组件类型约束与数据结构",
  "stay_in_confirm": true       // CONFIRM 阶段 refine 时为 true，DONE 后 iterate 时省略
}
```

前端处理：调用 `pushSpecVersion`，`source = 'trivial_patch'`，rationale 显示在 divider 文案中。

### 2.3 `iteration.classified`（任何 iterate 都先发）

```json
{
  "level": "trivial" | "minor" | "major" | "cross_scene",
  "rationale": "...",
  "confidence": 0.9,
  "has_patch": true
}
```

前端处理：推一个 iteration banner 到对话；同时把 `specRefineInFlight` 翻 true（仅作纯视觉提示用，不影响按钮互斥）。

### 2.4 `iteration.cross_scene_warning`

```json
{
  "message": "你的修改跨场景了...",
  "rationale": "..."
}
```

前端处理：推一个 banner，**不产新版**；`specRefineInFlight` 清零。

### 2.5 `iteration.patch_failed` / `iteration.failed`

trivial patch 应用异常（前者）或 classify 阶段异常（后者）。前端展示错误提示。

### 2.6 下游事件（标记"已确认"）

`scaffold.*` / `coding.*` / `verification.*` / `agent_*` 任一 → 当前 isLatest 那张卡的 `isConfirmed` 翻 true。

---

## 3. UI 行为规范

### 3.1 Spec 卡的状态切换

| 状态 | isLatest | isConfirmed | 表现 |
|---|---|---|---|
| **A. 最新未确认（可操作）** | true | false | 完整展开 + 蓝色 v 徽章 + `✅ 确认生成代码` 按钮 |
| **B. 最新未确认 + 正在生成新版** | true | false | A 的样式 + 顶部琥珀色提示条"AI 正在生成新版方案"，按钮 disabled |
| **C. 已被确认（用于代码生成）** | true 或 false | true | 绿色 v 徽章 + 绿色背景 + `✓ 已用于代码生成` 标签（不可再点）|
| **D. 历史未确认（被新版替代）** | false | false | 灰色背景 + 默认折叠 + `已被 v{N} 替代` 标签 |

### 3.2 用户操作

- **点击卡 header**：折叠/展开
- **点击确认按钮**：仅在状态 A 下可点。点击后 `confirmingSpec=true`，`apiConfirmSpec(spec_id)` + `startCodingFromSpec(spec_id)`，phase → generate
- **历史卡按钮区**：只显示状态标签，无可点按钮

### 3.3 Divider 文案

- `brainstorm_initial`：`📋 设计方案 v1 已生成，请确认`
- `brainstorm_iterate`：`🔄 重新梳理 v{n}（基于 v{parent}）`
- `trivial_patch`：`✏️ 小幅修改 v{n} · {rationale 截断到 40 字}`

---

## 4. 流程图

### 4.1 CONFIRM 阶段 refine（用户在 Spec 上还没点确认就发新消息）

```
用户在 v1 卡上发消息
   ↓
HTTP POST /coding/v2/message → action=refine_brainstorm
   ↓
后端 _run_iterate_dispatch_task(from_confirm_phase=True)
   ↓
classify_iteration → level
   ├── trivial: apply_patch_as_new_spec → v2 落盘 → SSE iteration.trivial_patched
   │     → 前端 pushSpecVersion(source='trivial_patch')
   │     → v1 卡 isLatest=false + 折叠；v2 卡 isLatest=true
   │     → 用户在 v2 上重新决定是否确认
   │
   ├── minor / major: 起新 brainstorm session（带 base_spec_brief）
   │     → BrainstormAgent 反问 0~N 轮 → emit_spec → SSE brainstorm.spec_emitted
   │     → 前端 pushSpecVersion(source='brainstorm_iterate')
   │     → 同上效果
   │
   └── cross_scene: SSE iteration.cross_scene_warning（不产版本，给用户警告）
```

### 4.2 用户点 v_n 卡的"确认生成代码"

```
SpecPreview emit confirm(spec_id=v_n.spec_id)
   ↓
ChatFlow forward → CodingPageV2.onConfirmSpec(specId)
   ↓
校验 specId === currentSpecId（防 stale 事件）
   ↓
apiConfirmSpec(specId) → 后端 mark_session_completed(final_spec_id=spec_id)
   ↓
startCodingFromSpec(specId) → 后端启动 coding pipeline
   ↓
SSE coding.start 到达 → 前端把 v_n 卡 isConfirmed=true
   ↓
v_n 卡按钮区切换为 "✓ 已用于代码生成"，永久不可再点
```

### 4.3 DONE 后 iterate（已生成代码，用户继续改）

```
phase=done，用户发消息
   ↓
HTTP POST → action=iterate（注意不是 refine_brainstorm）
   ↓
后端 _run_iterate_dispatch_task(from_confirm_phase=False)
   ↓
trivial: apply_patch + phase auto-advance to GENERATE → 自动跑 _run_coding_task
        + SSE iteration.trivial_patched → 前端 push 新版 v_{n+1} 卡
        + coding.start 立即到达 → v_{n+1} 卡 isConfirmed=true（自动确认）
minor/major: 同 4.1 流程，但走完 emit 后停 CONFIRM 等用户再次确认
```

---

## 5. 不变量（违反任一意味着 Bug）

1. `specVersions` 中 `isLatest=true` 的卡有且只有 0 或 1 张
2. 一旦某卡 `isConfirmed=true`，永远不会变回 false
3. 任何按钮的可操作性必须能从 `(isLatest, isConfirmed, phase)` 三元组推出，不依赖任何全局 flag
4. SSE 事件回放产出的 UI 状态必须和 live 路径产出相同（`pushSpecVersion` 是幂等的：相同 spec_id 重入只刷新元数据）
5. `currentSpecId` 永远等于"isLatest 那张卡的 spec_id"（前端 computed 保证）

---

## 6. 已废弃 / 兼容性

### 6.1 已废弃

- `store.specConfirmedLocally` 全局 flag → 拆为 per-card `isConfirmed`
- `ChatMessage.kind = 'spec-ready'` → 替换为 `'spec-version'`（带 `specCardId` 引用）
- `SpecPreview` 的 `envelope` / `allowActions` props → 统一收到 `cardData`

### 6.2 仍保留但语义降级

- `store.specRefineInFlight`：仅用于在最新卡顶部展示"AI 正在生成新版…"提示条，**不再用于按钮互斥**

### 6.3 旧会话回放

老会话历史里的 `brainstorm.spec_emitted` / `iteration.trivial_patched` 事件没有 `version` / `parent_version` / `rationale` 字段——前端兜底：
- `version` 缺失：用 `specVersions.length + 1`（按入场顺序兜底编号）
- `parent_version` 缺失：从前一张最新卡的 version 推断
- `rationale` 缺失：divider 不显示摘要

无回放破坏。

---

## 7. 待办（Phase 2）

- 版本对比 / diff 视图（"v3 ↔ v5 差在哪"）
- 历史版本回滚 UI（后端 API `rollback_to_version` 已就绪）
- 分支探索（"基于 v3 开新线"，需要新增 branch 概念）
- 后端事件直接带完整 envelope（省一次 HTTP）

---

## 8. 文件导航

```
前端
  src/stores/codingV2.ts                          SpecCardData / specVersions / pushSpecVersion / setSpec
  src/components/coding-v2/SpecPreview.vue        卡 UI + 三态切换 + 折叠
  src/components/coding-v2/ChatFlow.vue           spec-version 渲染分支 + getCard
  src/views/coding-v2/CodingPageV2.vue            loadSpecEnvelope（按 spec_id 拉填卡）+ onConfirmSpec(specId)

后端
  app/orchestrator/driver.py                      brainstorm.spec_emitted 事件携带 version/parent_version/core_purpose
  app/routes/coding_v2.py                         iteration.trivial_patched 事件携带 rationale/parent_version
  app/services/spec_service.py                    get_latest_spec_for_session（refine_brainstorm 找 base spec 用）
  app/services/brainstorm_session_service.py      mark_session_completed（仅在用户点确认后调）
```
