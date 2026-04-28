# Vibe Preview Runtime Plan

更新时间：2026-04-28

## 目标

为 Vibe Coding 在线 Git 工作区补齐应用运行沙箱能力，先形成内部可用的
`AI 改代码 -> 启动应用 -> 查看预览/日志 -> 浏览器观察 -> 继续修复` 闭环。
第一阶段采用本机进程 runner，但所有接口和数据结构按可替换 Docker/K8s runner 设计。

## 契约

- 工作区来源：优先支持 `online-coding` 的 `oc_*` Git 工作区，后续再兼容旧 Coding 模板工作区。
- Preview Runtime 不直接信任用户命令，先通过项目检测产生命令建议，再由 runner 执行。
- 本机 runner 只作为内部 MVP；生产 runner 必须可替换为容器/Pod。
- 预览能力必须包含：状态、启动命令、端口、预览 URL、日志路径、错误信息、停止/清理。
- 浏览器调试在 Preview Runtime 成功运行后再接入，不能把 BrowserService 当成运行沙箱。

## 原子任务

[x] 建立独立分支 `codex/vibe-preview-runtime`

[x] `backend/app/coding/preview_runtime/contracts.py`
定义 Preview Runtime 的状态模型、项目检测结果、runner 能力边界和 URL 契约。

[x] `backend/app/coding/preview_runtime/project_detector.py`
根据 `package.json`、lockfile 和常见目录结构识别包管理器、工作目录、install/build/start 命令。

[x] `backend/tests/test_preview_runtime_contract.py`
覆盖 Vite/npm、pnpm、frontend 子目录、无启动脚本等检测场景。

[x] `backend/app/coding/preview_runtime/local_runner.py`
实现内部 MVP runner：端口分配、进程启动、日志落盘、状态查询、停止服务。

[x] `backend/app/routes/online_coding_runtime.py`
新增 `start/status/stop/logs/preview-url` API，并挂到在线工作区鉴权和 `oc_*` repo 路径。

[ ] `backend/app/coding/browser_service.py`
补 console/page error/network 摘要采集接口，为 AI 观察页面提供结构化证据。

[ ] `extensions/ruijing-ai/src/*`
让在线工作区也能走后端工具链，新增 `start_preview/read_preview_logs/open_preview/inspect_browser` 能力入口。

[x] `frontend/src/api/onlineCoding.ts`, `frontend/src/views/OnlineCodingWorkspacePage.vue`
在 Vibe Coding 页面展示运行状态、预览 URL、日志和启动/停止操作。

[ ] 部署方案文档
补 Docker/K8s runner 的生产替换方案、资源限制、网络策略、清理策略和阿里云部署建议。

## 第一阶段验收

1. 导入一个 Vite/React/Vue 仓库后，系统能识别启动命令和工作目录。
2. 点击启动后返回稳定预览 URL，并能看到启动日志。
3. 停止后端口和进程被释放。
4. BrowserService 能打开预览 URL 并返回截图/错误摘要。
5. 后续切换 Docker runner 时，不需要重写前端和 IDE 工具调用契约。
