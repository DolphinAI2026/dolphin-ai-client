# 上传新设计文档更新已有应用 — 入口重新接线 + 端到端验证

- 日期：2026-05-29
- 状态：设计待评审
- 关联：appCode 身份化 (c772cf1) / 超大文档 verbatim 喂 generate (4e243bc) / 进度面板真实重建 (a1965e4)

## 背景与问题

用户在已生成的应用里想「上传一份新版设计文档（含完整 132 模型的 .md）→ 让应用按新文档更新」，但：

1. 应用内「配置助手」面板纯文字、工具白名单不含 `update_app_from_doc`，没有上传入口。
2. 用户在整个应用配置视图里都找不到上传文档的按钮。

调研发现：**完整的 "上传新 md → 语义 diff → 变更计划 → 勾选审核 → 执行/取消" 管线其实早已存在**，只是入口按钮在 design-v3/v4 重构时被删掉，留下一套"没接线的机器"。

### 现存可复用资产（已确认）

后端（全在）：
- `POST /applications/{id}/upload-doc-version`：multipart 上传 .md → `doc_pipeline.parse_document`（verbatim 全量解析，**超大文档天然 OK，不走 LLM 重抄、不截断**）→ 语义 diff → 生成 change_plan，SSE 流式返回进度 + 计划。
- `GET /applications/{id}/change-plans/{plan_id}`：取计划。
- `PUT .../change-plans/{plan_id}/selections`：勾选哪些变更生效。
- `POST .../change-plans/{plan_id}/execute`：执行（SSE）。
- `POST .../change-plans/{plan_id}/cancel`：取消并回滚到 from_version。

前端 `ChatPage.vue`（基本全在）：
- `handleDocUpload`（SSE handler，含进度跟踪 + `DOC_NOT_STANDARD` 友好报错）。
- 隐藏文件输入 `docVersionInputRef`（accept=".md,.markdown"）+ `handleDocVersionInputChange`。
- `triggerDocVersionUpload()`：进入更新模式 + 打开文件选择器（**已定义，但 template 无任何按钮调用 → 孤儿**）。
- change_plan 审核状态与 UI：`store.changePlan` / `store.showChangePlan` / `isUpdateReviewMode` / 右侧"更新概览"审核面板（template 557–625 渲染中）/ `showExecuteUpdateButton` / 取消 / 执行（`executeChangePlanUrl`）/ 勾选（`updateSelections`）。
- `showUpdateButton = existingAppId && isPlatformDeployed && !isUpdateReviewMode`（**已定义，但 template 无绑定 → 孤儿**）。

## 目标 / 非目标

目标：
- 让用户在已部署应用里**找得到**「更新文档」入口，上传新 md → 走现有 diff/审核/执行管线。
- 确认这条孤儿管线在 redesign 之后仍能跑通；坏了就修。

非目标：
- 不重写 diff/change_plan/审核任何已有逻辑（除非验证发现 bug）。
- 不在配置助手（config-chat）里塞整文档更新（它定位是细粒度对话改，保持不变）。
- 不支持 .docx/.pdf 直传（`upload-doc-version` 仅 .md；用户的文件就是 .md，超出范围另议）。

## 方案

### 1. 重新接线入口按钮（顶部工具栏）
- 在应用顶部工具栏（`保存 / 发布到生产 / 历史 / 更多` 那一排）加「更新文档」按钮。
- 复用现成 `showUpdateButton` 控制可见（已部署 + 非审核态才显示），`@click="triggerDocVersionUpload()"`。
- 不新增 store/函数，纯把孤儿函数接到一个可见按钮上。

### 2. 端到端验证（本方案主要风险/工作量在此）
用 535KB 的 `集成数据管理系统` md 实跑：上传 → 看进度 → diff 出 change_plan → 右侧"更新概览"勾选 → 执行 → apaas 真实变更。
- 验证孤儿管线 redesign 后是否仍健康（SSE handler 引用的变量、审核面板渲染、execute 链路）。
- 发现 rot 就定点修（不扩大重写）。

### 3.（可选，看时间）配置助手轻提示
配置助手面板加一句引导/小入口指向顶部「更新文档」（用户最初在这找）。默认先不做，验证完再定。

## 数据流

```
用户点[更新文档] → triggerDocVersionUpload()
  → 进入更新模式 (startApplicationUpdateChat) + 文件选择器
  → 选 .md → handleDocUpload → POST upload-doc-version (multipart, SSE)
      后端: parse_document(verbatim) → 语义 diff → change_plan(add/modify/delete)
  → 前端 store.changePlan + isUpdateReviewMode → 右侧"更新概览"审核面板
  → 勾选 (updateSelections) → [执行] (execute SSE) 或 [取消] (cancel 回滚)
      后端: 对 apaas 应用增量增/改 (删除受 apaas 限制，顶多停用)
```

## 风险
- **孤儿管线 rot**（主要风险）：redesign 删入口时可能连带改动/破坏了下游，需实跑确认。
- **diff 质量**：132 模型大文档的语义 diff 可能慢或产生大量变更项；验证时观察。
- **删除语义**：apaas 删不掉应用/模型，change_plan 里的"删除"动作顶多停用——验证时确认行为不报错、文案诚实。

## 验收
- 顶部有可见「更新文档」按钮（已部署应用）。
- 上传 535KB md → 出 change_plan → 审核面板可勾选 → 执行成功，apaas 反映变更。
- vue-tsc 0 错；不回归现有部署/审核流程。
