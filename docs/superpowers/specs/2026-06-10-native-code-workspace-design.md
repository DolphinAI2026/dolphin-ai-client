# 原生代码工作区设计 — 替换 code-server fork

日期: 2026-06-10
分支: dev
状态: 设计待评审

## 背景与决策

放弃 fork code-server 这条路(workbench 补丁脆弱、ruijing 扩展在线上扩展宿主里无法激活、live-patch 易碎)。改为在 ai-builder 内做一个原生的「代码展示工作区」,通过已有的 AI 对话链路改代码,体验对标 Claude Code。

调研确认引擎大半已存在,本次主要是前端新增 + 在 CodingPage 内做替换。四个已拍板的方向:

1. **落点**: 改造现有 `frontend/src/views/CodingPage.vue`,把其中的 code-server IDE iframe 抽屉换成原生文件树 + 代码查看器。聊天 / pipeline / diff 全复用。
2. **编辑能力**: 只读展示 + 对话改。代码查看器只读;改代码全部经 agent 对话(已有 `edit_file` / `write_file` 工具)。不做浏览器内手改代码。
3. **布局**: 三栏 —— 左文件树、中只读代码查看器(agent 改动时就地红绿 diff)、右聊天。顶栏保留工作区名 + 编译/运行。
4. **语法高亮**: Shiki(VS Code 同源语法,`.vue` / `.ts` 保真最好)。
5. **逐条确认门(Claude Code 式 HITL)**: agent 改文件/跑命令前先提议、暂停等用户 接受/拒绝;接受才落盘/执行,拒绝则跳过并把结果回给 agent。带「自动接受」开关。门覆盖 `edit_file` / `write_file` / `run_command`。

## 阶段划分

- **Phase 1 — 原生工作区**: 文件树 + 只读代码查看器 + 接现有聊天/流式/diff。agent 沿用现状(直接写),先把展示链路跑通上线。无后端改动。
- **Phase 2 — 确认门(HITL)**: 在工具执行边界加提议-等待-决定的人在回路 + 「自动接受」开关。含后端改动。Phase 1 不被它阻塞。

## 目标

- (Phase 1) CodingPage 内提供:浏览工作区文件树 → 点开只读查看代码 → 在右侧对话让 agent 改 → 改动文件在树上标记、在查看器就地显示红绿 diff、改完显示最新内容。Phase 1 最大化复用现有后端,无新后端接口。
- (Phase 2) agent 改文件/跑命令前逐条提议、用户 接受/拒绝;带「自动接受」开关。
- 删除 code-server fork 相关代码(分阶段,原生版跑通后再删)。

## 非目标

- 不做浏览器内手改代码(无 Monaco / 无写回 / 无脏态)。架构上 CodeViewer 是只读组件;若将来要手改是单独项目。
- 不改 coding agent 的循环结构(Phase 2 只在工具执行边界加「提议-等待」,不重排 9 个退出点的循环;不动 token 采集、租户隔离)。
- 不动业务事件 / 配置助手 / 0-1 生成等其他链路。
- 「自动接受」不等于无门:它只把决定自动解析为「接受」,提议/diff 仍照常展示。

## 架构

### 复用(不新增后端)

| 能力 | 现有实现 | 用途 |
| --- | --- | --- |
| 文件树数据 | `GET /workspace/{ws_id}/files` → `workspace_mgr.list_files` (`backend/app/routes/coding.py:1950`) | 渲染左侧文件树 |
| 文件内容 | `GET /workspace/{ws_id}/file?file_path=` → `workspace_mgr.read_file` (`coding.py:1964`) | 查看器读单文件 |
| agent / 改代码 / 流式 | coding pipeline + harness + `edit_file`/`write_file` (`backend/app/coding/tools.py`, `pipeline.py`, `routes/harness.py`) | 对话改代码 |
| 红绿 diff 渲染 | `frontend/src/components/SideBySideDiff.vue` + 流里已带的 diff 富 input | 查看器内就地 diff |
| 工作区身份 / 列表 | `frontend/src/views/coding/useCodingWorkspace.ts` | 当前工作区上下文 |

### 新增(纯前端 3 件 + 1 处替换)

1. **`frontend/src/views/coding/FileTree.vue`** —— 读 `/workspace/{ws_id}/files`,渲染目录/文件;点击发出 `open-file` 事件;接收「本轮改动文件集合」给改动文件打小圆点。职责单一:展示文件树 + 选中态 + 改动标记。

2. **`frontend/src/views/coding/CodeViewer.vue`** —— 输入 `{ wsId, filePath, diff? }`。无 diff 时:拉 `/workspace/{ws_id}/file` 并用 Shiki 只读高亮渲染。有 diff 时(该文件本轮被 agent 改过):渲染 `SideBySideDiff`。职责单一:只读显示一个文件的内容或 diff。

3. **`frontend/src/views/coding/useWorkspaceChanges.ts`** —— 监听现有聊天流的 edit/write 工具事件,维护 `changedFiles: Map<path, diff>` 与 `lastChangedFile`,供文件树标记 + 查看器自动打开使用。职责单一:把流事件聚合成「本轮改了哪些文件 / 各自 diff」。

4. **CodingPage 替换** —— 把 IDE iframe 抽屉(`openIdeDrawer` / `useIdeManager` / `ide-pane` `<iframe>`)替换为 `FileTree` + `CodeViewer` 两栏;聊天栏沿用现有 `agentMessages` 渲染。顶栏「打开 IDE」按钮改为不需要(代码常驻可见),编译/运行复用现有 `run_command` 路径。

### 数据流(agent 改 → 查看器)

```
用户在聊天输入 → 现有 coding pipeline/harness → agent 调 edit_file/write_file
   → 后端写工作区文件 + 流式回 edit 事件(含 file_path + 红绿 diff)
   → 前端 useWorkspaceChanges 收事件: changedFiles.set(path, diff), lastChangedFile=path
   → FileTree: 该文件打圆点; CodeViewer: 自动打开 lastChangedFile, 显示 diff
   → 本轮结束/用户点开该文件再看: CodeViewer 无 diff 态, 重新拉 /file 显示最新内容
```

用户手动点文件树里任意文件 → CodeViewer 拉 `/file` 只读高亮显示(无 diff)。

### Phase 2 — 确认门(HITL)

门加在**工具执行边界**,不重排 agent 循环。`edit_file` / `write_file` / `run_command` 执行器改成「提议 → 等待 → 落盘/执行」:

新增(后端):

1. **决定登记表(per run/session)** —— `pending_decisions: dict[tool_use_id, Future]`。工具执行器注册 future 并 await 它,因此 agent 循环在这条工具结果上自然暂停。
2. **提议事件** —— 执行器先经现有 `_emit_progress` 通道发 `tool_proposal` 事件(含 `tool_use_id`、工具名、目标文件/命令、红绿 diff 或命令文本),前端据此渲染门;然后 await future。
3. **决定接口** —— `POST /coding/.../tool-decision` body `{run_id|session_id, tool_use_id, decision: "accept"|"reject"}`,resolve 对应 future。接受 → 执行器写文件/跑命令、返回成功 tool_result;拒绝 → 不动、返回「用户拒绝了此操作」给 agent。
4. **自动接受开关** —— 每 run/session 一个 `auto_accept` 标志;为真时执行器跳过 await、直接按接受走(仍发 `tool_proposal` 供展示)。开关由前端经决定接口或 run 启动参数设置。

新增(前端):

5. **门 UI** —— 收到 `tool_proposal`:在聊天消息里(和查看器 diff 旁)渲染 接受/拒绝 按钮;`run_command` 渲染命令文本 + 接受/拒绝。点击 → POST 决定。
6. **自动接受模式** —— 顶栏/输入区一个 Auto 开关;开了之后新提议自动接受(本地仍显示提议+diff),并把 `auto_accept` 同步给后端。

Phase 2 数据流:

```
agent 调 edit_file → 执行器: _emit_progress(tool_proposal, diff) + 注册并 await future[tool_use_id]
   → 前端门 UI 显示 接受/拒绝(或 Auto 模式自动接受)
   → POST /coding/.../tool-decision {tool_use_id, accept} → resolve future
   → 执行器: 接受→写文件→返回成功; 拒绝→不写→返回"用户拒绝"
   → agent 收到 tool_result 继续 / 调整
```

关键实现风险(实现计划里定):提议事件必须在执行器 await 期间真正流到前端 —— 即 `_emit_progress` 队列的抽取要和执行器的 await **并发**,不能被 await 阻塞。沿用现有 SSE 生成器 + 进度队列的抽取机制,确认其在工具执行期间持续 drain。

### 边界与隔离

- CodeViewer 不知道 agent、不知道流;只接受 `{wsId, filePath, diff?}`,可独立测试。
- FileTree 不读文件内容,只列树 + 标记;通过 `open-file` 事件与外层通信。
- useWorkspaceChanges 是唯一「理解流事件 → 改动集合」的地方;CodingPage 把它的输出分发给两个展示组件。
- 改动后查看器的「最新内容」始终来自后端 `/file`(单一事实源),不在前端拼装。

## 错误处理

- `/files` / `/file` 失败:查看器/树显示行内错误态 + 重试,不白屏。
- 大文件(超阈值,如 >1MB):查看器提示「文件过大,仅显示前 N 行」或拒绝高亮(Shiki 对超大文件降级为纯文本),避免卡渲染。
- 二进制 / 非文本文件:树可点但查看器显示「不支持预览」。
- agent 改了一个查看器没打开的文件:只在树上标记,不强制抢占当前查看;`lastChangedFile` 自动打开仅针对单文件改动,多文件改动只标记、由用户点选。

Phase 2 门相关:

- **SSE 断连/超时挂起 future**:执行器 await future 时若客户端断连(GeneratorExit/CancelledError)或超过超时阈值 → future 以「拒绝(或中止)」收尾,执行器不落盘并返回中止,避免 agent 永久卡 running(参照 [[agent_observability_phase1]] 里 end_run 用 `asyncio.shield` 抗断连的处理)。
- **重复/迟到决定**:同一 `tool_use_id` 的第二次决定忽略(future 已 resolved);未知 tool_use_id 的决定返回 404,不影响在跑的 run。
- **拒绝语义**:拒绝只跳过该次操作并据实告知 agent,不回滚之前已接受的改动;agent 据 tool_result 自行决定后续。

## 测试

Phase 1:

- 组件级:CodeViewer 只读渲染 / diff 渲染 / 错误态 / 大文件降级;FileTree 渲染 + 选中 + 改动标记;useWorkspaceChanges 由模拟流事件聚合出正确的 changedFiles。
- 集成(preview 实测):打开 CodingPage → 选工作区 → 点文件看高亮 → 对话「给表格加排序」→ 看树标记 + 查看器 diff → 确认改后内容正确。
- 现有后端 `/workspace/{ws_id}/files` `/file` 不改,沿用其既有测试。

Phase 2:

- 后端:工具执行器在 await 决定期间不落盘;接受 → 写 + 返回成功;拒绝 → 不写 + 返回拒绝;auto_accept=true → 不 await 直接接受;断连/超时 → 中止不落盘。用 StaticPool 共享内存库 + 模拟决定接口测(参照 recorder/run_agent 测试基建)。
- 前端:收 `tool_proposal` 渲染门;点接受/拒绝 POST 正确 body;Auto 模式不再逐条点且同步 auto_accept。
- 集成(preview 实测):对话改文件 → 出现 接受/拒绝 → 拒绝则文件未变、agent 收到拒绝;接受则落盘 + diff;开 Auto 后连续改不再弹门。

## 清理(分阶段,原生版跑通并验证后)

- 删 `frontend/src/views/coding/useIdeManager.ts`、`frontend/src/components/common/WorkspaceIdeDrawer.vue`、CodingPage 内 IDE iframe 抽屉相关模板/逻辑。
- 删部署侧 code-server:`deploy/docker/supervisord.conf` 的 `[program:code-server]`、Dockerfile 里 code-server 下载 + 扩展安装 + `patch_all.js` 阶段、nginx 的 `/ai-builder/ide/` 反代。
- 删 `scripts/patch_all.js` 及 `scripts/patch_vscode_*`、`scripts/lib/codeServerResolver.js`、`extensions/ruijing-ai` 的镜像构建接入(扩展源码可留存归档)。
- 该阶段单独成一个 PR/提交,与新增解耦,确保新原生工作区先在 dev 上验证可用再砍旧路径。

## 风险 / 待定

- Shiki 在 Vite 下的加载方式(按需载 grammar/theme,避免拖慢首屏)—— 实现计划里定 import 策略。
- 聊天流 edit/write 事件的确切字段(file_path / diff 结构)以现有 harness/sse_adapter 实际输出为准,实现首步先打印核对(见 [[harness_tool_event_rich_input_2026_06_03]] 的字段约定)。
- Phase 2 提议-等待是否会和 omnigate 网关的 30s 超时冲突(慢命令历史上踩过,见 [[run_workspace_command_async_fix_2026_05_13]]):门的 await 是等用户、不是等 LLM,需确认它不被网关侧 timeout 误杀;实现计划里定 await 的取消/超时边界。
- `run_command` 是否纳入门:本设计默认纳入(Claude Code 行为);评审若要只管改文件、放行命令,可缩到 `edit_file`/`write_file`。
