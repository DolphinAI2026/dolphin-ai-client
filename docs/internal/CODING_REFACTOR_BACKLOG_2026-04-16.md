# 智能开发模块重构记录 — 三轮全部完成

> 2026-04-16 完整记录。本文档按时间线记录三轮重构的成果和结构。

---

## 第一轮（低风险快速优化）

| 项 | 位置 | 改动 |
|---|---|---|
| **B2** | `workspace.py` | 新增 `_safe_read_json()` 辅助函数，7 处替换 `try: json.loads(...); except: {}` 样板 |
| **F1** | `CodingPage.vue` | 抽 `scrollStreamToBottom()`，4 处重复 `nextTick + scrollHeight` 归一 |
| **F2** | `FileCard.vue`（新建） | `file_write` / `file_edit` 两处 99% 相同模板抽成组件 |
| **锦上添花** | `vibe_agent.py` | 3 处局部 `import asyncio` 合并到顶部 |

---

## 第二轮（中等规模重构）

| 项 | 位置 | 改动 |
|---|---|---|
| **B3** | `workspace.py:build_project` | 拆 110 行单函数 → `_build_dual_project()` + `_build_single_project()` + `_finalize_build()`；消除 5 处重复 `meta["status"]=...; _write_meta` |
| **B1** | `workspace.py:build_project` 开头 | 新增 `_run_workspace_compat_handlers()` 字典派发；6 次顺序调用 → 1 次 O(1) 查表；减少 5 次冗余 `_read_meta` |
| **F3** | `CodingPage.vue:sendMessage` | 150 行 SSE 事件 if/else 链 → `sseHandlers` dispatch map + `STEP_HANDLERS` / `TOOL_HANDLERS` / `playDoneChime` 子结构 |

---

## 第三轮（大规模重构，L1 + L2）

### L1 — `sendMessage` 拆分

**起点**：`sendMessage` 275 行单函数，上传/请求/SSE/IDE 加载/错误处理混在一起。

**拆分步骤**（每步独立 HMR 验证）：

- **L1.A**：`sseHandlers` / `STEP_HANDLERS` / `TOOL_HANDLERS` / `playDoneChime` 从 sendMessage 内部提到 setup 顶层
- **L1.B**：提取 `uploadAttachmentIfPresent()` — 纯函数，做附件上传 + 组装 finalMessage
- **L1.C**：提取 `buildPipelineRequest()` — 纯函数，构建 pipeline 请求 body
- **L1.D**：提取 `consumePipelineSse()` + `loadIdeUrlAfterPipeline()`，简化 sendMessage 为编排

**结果**：`sendMessage` 从 **275 行 → 52 行**，只做编排：
```ts
async function sendMessage() {
  // 前置校验 / 状态重置
  // addStreamMsg user / status
  try {
    const finalMessage = await uploadAttachmentIfPresent(...)
    const body = buildPipelineRequest(finalMessage, sceneKey)
    const response = await fetch(harnessApi.codingPipelineUrl, { ... })
    if (!response.ok) throw ...
    await consumePipelineSse(response)
    await loadIdeUrlAfterPipeline()
  } catch (error) { ... } finally { ... }
}
```

### L2 — `CodingPage.vue` 拆分为 5 个 composable

**起点**：3789 行 `.vue` 单文件，`<script setup>` 1823 行，100+ ref 混杂。

**拆分顺序**（耦合从小到大）：

- **L2.1** — [`coding/useCodingModel.ts`](../../frontend/src/views/coding/useCodingModel.ts)（156 行）
  - 模型选择、规范化、持久化、切换
  - 暴露：codingModelOptions / selectedCodingModelValue / codingModelHint / loadCodingModelOptions / handleCodingModelChange / selectCodingModel 等

- **L2.2** — [`coding/useStreamMessages.ts`](../../frontend/src/views/coding/useStreamMessages.ts)（271 行）
  - streamMessages 列表、addStreamMsg、append delta、step/tool replay、自动滚动
  - 导出函数级工具：`formatSceneType()` / `renderMarkdown()`

- **L2.3** — [`coding/useIdeManager.ts`](../../frontend/src/views/coding/useIdeManager.ts)（114 行）
  - IDE iframe 加载、30 秒超时、重试、cache-busting
  - activeView 视图切换

- **L2.4** — [`coding/useCodingWorkspace.ts`](../../frontend/src/views/coding/useCodingWorkspace.ts)（90 行）
  - allWorkspaces 列表、按 app 过滤
  - 工作区 formatter（displayName / codeName / tooltip / typeLabel）
  - downloadWorkspaceArtifact

- **L2.5** — [`coding/useCodingPipeline.ts`](../../frontend/src/views/coding/useCodingPipeline.ts)（385 行）
  - SSE 事件 dispatch map（12 种事件）
  - STEP_HANDLERS / TOOL_HANDLERS / playDoneChime
  - uploadAttachmentIfPresent / buildPipelineRequest / consumePipelineSse / loadIdeUrlAfterPipeline
  - sendMessage / sendSuggestion 编排
  - **依赖前面 4 个 composable**，通过 deps 参数显式传入

### 最终指标

| 指标 | 重构前 | 重构后 |
|---|---|---|
| CodingPage.vue 总行数 | 3789 | 3094（含 2042 行 CSS） |
| CodingPage.vue `<script>` 行数 | 1823 | **505**（减少 72%） |
| composable 总行数 | 0 | 1016（分 5 个文件） |
| sendMessage 行数 | 275 | **52** |
| 最大 composable | — | useCodingPipeline 385 行 |

### CodingPage.vue 现状

`<script setup>` 只剩 505 行，包含：
- 导入声明（~30 行）
- 5 个 composable 调用解构（~80 行）
- 场景选择 / scene category map（~50 行）
- 附件 / 文件上传 UI 状态（~40 行）
- 平台环境 / upload-to-platform 流程（~80 行）
- 项目删除 / 下载 / workspace 打开（~80 行）
- onMounted / onUnmounted / 路由切换处理（~100 行）
- 其他 UI 辅助函数（~45 行）

进一步拆分（useUploadPlatform / useAttachment 等）收益递减，建议停在这里。

---

## 维护指引

### 加一个新的 SSE 事件类型

1. 在 [useCodingPipeline.ts](../../frontend/src/views/coding/useCodingPipeline.ts) 的 `sseHandlers` map 里加一项
2. 不需要碰 CodingPage.vue 或 sendMessage

### 加一个新的 step（如 auto_test）

1. 在 `STEP_HANDLERS` 配置里加一项：
```ts
auto_test: { running: '正在跑测试...', done: '测试通过', onDone: async (data) => { ... } },
```
2. 后端 pipeline.py 发 `{type: "step", step: "auto_test", status: "running" | "done"}`

### 改 IDE iframe 加载逻辑

只改 [useIdeManager.ts](../../frontend/src/views/coding/useIdeManager.ts)

### 改工作区卡片展示

只改 [useCodingWorkspace.ts](../../frontend/src/views/coding/useCodingWorkspace.ts)（text 格式）或 CodingPage.vue template（DOM 结构）

### 加新 project_type 类型的 label

- 前端：[useCodingWorkspace.ts](../../frontend/src/views/coding/useCodingWorkspace.ts) 的 `WS_TYPE_GROUP_MAP`
- 后端兼容：[workspace.py](../../backend/app/coding/workspace.py) 的 `_run_workspace_compat_handlers` 字典
- prompt：[vibe_agent.py](../../backend/app/coding/vibe_agent.py) 的 `_build_prompt` 新增 workflow 分支

---

## 验证清单

✅ 静态验证：
- 后端 `:8000/docs` 返回 200
- 前端 `:5173` 返回 200
- 所有 Vite HMR 更新无错误
- Python 全部 import 成功

⏳ 待人工冒烟测试：
- 新建工作区 → 生成代码 → 打开 IDE
- 已有工作区 → 追加需求 → 热更新
- 附件上传 → 提交 → 检查消息组装
- 模型切换 → 切换后首条消息使用新模型
- 工作区下载 zip（dist / src）
- 上传到平台环境

建议用户按上述列表手动冒烟一次，发现 bug 可以精确定位到某个 composable。
