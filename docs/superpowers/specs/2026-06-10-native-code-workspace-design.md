# 原生代码工作区设计 — 替换 code-server fork

日期: 2026-06-10
分支: dev
状态: 设计待评审

## 背景与决策

放弃 fork code-server 这条路(workbench 补丁脆弱、ruijing 扩展在线上扩展宿主里无法激活、live-patch 易碎)。改为在 ai-builder 内做一个原生的「代码展示工作区」,通过已有的 AI 对话链路改代码,体验对标 Claude Code。

调研确认引擎大半已存在,本次主要是前端新增 + 在 CodingPage 内做替换。四个已拍板的方向:

1. **落点**: 改造现有 `frontend/src/views/CodingPage.vue`,把其中的 code-server IDE iframe 抽屉换成原生文件树 + 代码查看器。聊天 / pipeline / diff 全复用。
2. **编辑能力**: 只读展示 + 对话改。代码查看器只读;改代码全部经 agent 对话(已有 `edit_file` / `write_file` 工具)。
3. **布局**: 三栏 —— 左文件树、中只读代码查看器(agent 改动时就地红绿 diff)、右聊天。顶栏保留工作区名 + 编译/运行。
4. **语法高亮**: Shiki(VS Code 同源语法,`.vue` / `.ts` 保真最好)。

## 目标

- CodingPage 内提供:浏览工作区文件树 → 点开只读查看代码 → 在右侧对话让 agent 改 → 改动文件在树上标记、在查看器就地显示红绿 diff、改完显示最新内容。
- 完全复用现有后端(无新后端接口)与现有聊天/流式/diff 渲染。
- 删除 code-server fork 相关代码(分阶段,原生版跑通后再删)。

## 非目标

- 不做浏览器内手改代码(无 Monaco / 无写回 / 无脏态)。架构上 CodeViewer 是只读组件;若将来要手改是单独项目。
- 不改 coding agent 的循环、工具集、token 采集、租户隔离。
- 不动业务事件 / 配置助手 / 0-1 生成等其他链路。

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

## 测试

- 组件级:CodeViewer 只读渲染 / diff 渲染 / 错误态 / 大文件降级;FileTree 渲染 + 选中 + 改动标记;useWorkspaceChanges 由模拟流事件聚合出正确的 changedFiles。
- 集成(preview 实测):打开 CodingPage → 选工作区 → 点文件看高亮 → 对话「给表格加排序」→ 看树标记 + 查看器 diff → 确认改后内容正确。
- 现有后端 `/workspace/{ws_id}/files` `/file` 不改,沿用其既有测试。

## 清理(分阶段,原生版跑通并验证后)

- 删 `frontend/src/views/coding/useIdeManager.ts`、`frontend/src/components/common/WorkspaceIdeDrawer.vue`、CodingPage 内 IDE iframe 抽屉相关模板/逻辑。
- 删部署侧 code-server:`deploy/docker/supervisord.conf` 的 `[program:code-server]`、Dockerfile 里 code-server 下载 + 扩展安装 + `patch_all.js` 阶段、nginx 的 `/ai-builder/ide/` 反代。
- 删 `scripts/patch_all.js` 及 `scripts/patch_vscode_*`、`scripts/lib/codeServerResolver.js`、`extensions/ruijing-ai` 的镜像构建接入(扩展源码可留存归档)。
- 该阶段单独成一个 PR/提交,与新增解耦,确保新原生工作区先在 dev 上验证可用再砍旧路径。

## 风险 / 待定

- Shiki 在 Vite 下的加载方式(按需载 grammar/theme,避免拖慢首屏)—— 实现计划里定 import 策略。
- 聊天流 edit/write 事件的确切字段(file_path / diff 结构)以现有 harness/sse_adapter 实际输出为准,实现首步先打印核对(见 [[harness_tool_event_rich_input_2026_06_03]] 的字段约定)。
- 改代码是否要「接受/拒绝」门:本设计沿用现状(agent 直接写 + 显示 diff),不新增门;若后续要门再单独加。
