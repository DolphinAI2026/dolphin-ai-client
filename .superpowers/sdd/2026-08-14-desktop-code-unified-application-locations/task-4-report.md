# 任务 4 实施报告：统一应用列表和首次位置选择

## 状态

已完成统一 Code 应用投影、位置筛选、独立来源加载、首次位置选择、pending 位置偏好和单一添加应用菜单接线。未修改 `CodeConversationPage`、Runtime 或后端。

## 实现

- 新增统一应用合并算法：仅按 `linked_remote_application_id` 或相同非空 `logical_application_id` 合并；同名、同编码但无稳定关系的记录保持独立。
- 位置对象保留各自的 `external_application_id` 和原始应用记录；打开会话始终使用用户所选位置的 ID。
- 远程记录缺少逻辑 ID 时，使用 `remote:<deployment>:<external_application_id>` 生成兼容逻辑 ID。
- 桌面并行加载本机、远程来源，Web 只加载远程；来源分别维护 `loading/error/retry`，单侧失败不清空另一侧结果。
- 已知远程关联在远程来源失败时保留为 `linked`，远程位置标记 `unavailable`，本机可用性不受污染。
- `Apps.vue` 删除来源互斥和旧来源记忆控制，改为 `全部 / 本机可用 / 远程可用`位置筛选。
- 双位置无记忆时不设主位置，必须从按钮旁菜单选择；有效记忆作为主操作；记忆位置不可用时显示不可用且不静默回退。
- 新增单个“添加应用”菜单；桌面提供“新建本地项目 / 打开已有项目 / 添加远程应用”，Web 仅远程入口。两个本机入口复用同一个 `LocalCodeApplicationDialog`，通过初始 `directory_mode` 区分。

## RED / GREEN

### RED 1

指定 Vitest 首次失败，原因符合预期：

- 合并与偏好模块不存在。
- store 缺少双来源并行结果接口。
- `Apps.vue` 仍使用来源互斥状态和旧来源记忆。

### RED 2

补充首次选择决策测试后失败：`resolveCodeApplicationOpenState` 不存在。该测试证明双位置无记忆不能默认位置，并覆盖失效记忆不得回退。

### RED 3

补充远程来源失败测试后失败：已知远程关联错误投影成 `local_only`。实现后改为保留 `linked` 且远程位置 `unavailable`。

### GREEN

```text
Test Files  4 passed (4)
Tests       25 passed (25)
Duration    1.39s
```

执行命令：

```bash
cd frontend && npm test -- codeApplicationLocations.spec.ts codeApplicationLocationPreference.spec.ts codeApplications.spec.ts Apps.codeMode.spec.ts
```

按简报要求未运行 build、宽泛测试或额外测试套件。

## 首次选择与 ready 记忆边界

- Apps 成功创建 shell 会话后仅调用 `stageCodeApplicationLocationPreference`，pending 记录包含 deployment、user、logical application、选择位置和 shell session ref。
- stage 不修改 durable preference。
- `commitCodeApplicationLocationPreference` 只有在 application scope 与 shell session ref 均匹配时才写 durable preference。
- `discardPendingCodeApplicationLocationPreference` 可在会话失败或取消时清理 pending，且不改变既有 durable preference。
- 本任务未接入 durable commit。任务 5 必须在可信 `builder.ready` 到达后，使用相同 scope 和 shell session ref 调用 commit；ready 前失败应调用 discard 或保留待恢复策略。

## 文件

- `frontend/src/api/codeRuntime.ts`
- `frontend/src/components/code/codeApplicationLocations.ts`
- `frontend/src/components/code/codeApplicationLocations.spec.ts`
- `frontend/src/components/code/codeApplicationLocationPreference.ts`
- `frontend/src/components/code/codeApplicationLocationPreference.spec.ts`
- `frontend/src/composables/useUnifiedCodeApplications.ts`
- `frontend/src/components/code/CodeApplicationActions.vue`
- `frontend/src/components/code/AddCodeApplicationMenu.vue`
- `frontend/src/components/code/LocalCodeApplicationDialog.vue`
- `frontend/src/components/code/LocalCodeApplicationDialog.spec.ts`
- `frontend/src/stores/codeApplications.ts`
- `frontend/src/stores/codeApplications.spec.ts`
- `frontend/src/views/Apps.vue`
- `frontend/src/views/Apps.codeMode.spec.ts`

## 自检

- 新增文件均低于 500 行。
- `Apps.vue` 只保留统一列表、偏好 scope、打开与菜单接线；合并、来源状态、位置决策和偏好持久化均在小模块中。
- Builder/低代码路径继续使用原列表、导入、历史、构建、发布和删除逻辑。
- 未修改后端、Runtime、设置或 `CodeConversationPage`。
- 旧 `dolphin-code-application-source-v1` 仍保留兼容 API，但不再控制 Apps 列表或打开位置。

## 疑虑

- durable preference 尚未生效是有意边界，必须由任务 5 的 `builder.ready` 接入完成。
- 指定测试命令不包含 `LocalCodeApplicationDialog.spec.ts`；本轮遵守只运行指定命令，菜单到对话框的接线由 `Apps.codeMode.spec.ts` 覆盖，未额外执行该测试文件。
- 按要求未运行类型构建或浏览器验收；当前结论仅基于聚焦 Vitest 与差异自检。
