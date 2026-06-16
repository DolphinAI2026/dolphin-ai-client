# 桌面交付驾驶舱 Phase 0 打包 Spike — 验收记录

- 日期：2026-06-16
- 分支：`feat/desktop-phase0-spike`（基于 dev，未 push）
- 计划：`docs/superpowers/plans/2026-06-16-desktop-phase0-packaging-spike.md`
- 设计：`docs/superpowers/specs/2026-06-16-desktop-delivery-cockpit-design.md`

## 结论

**地基成立。** Phase 0 要证明的「Tauri(macOS) + PyInstaller sidecar + WKWebView 同源加载现有前端」这条链路端到端跑通了，产出可双击运行的 `.app`（53MB）+ `.dmg`（45.6MB）。Task 1–8（自动化部分）已全部实现，每个任务过了 spec 合规 + 代码质量两道审查，外加一次全实现终审（READY FOR E2E，无阻塞项）。**唯一剩 Task 9** = 需要真实 trial 凭据的人工端到端验收（见下）。

## 已验证的事实（证据）

- **打包**：`backend/ruijing-sidecar.spec` 用 PyInstaller onefile 把 FastAPI + 前端打成 38MB 单体二进制，排除 playwright(改惰性 import)/k8s/重文档库。冻结二进制独立实测：`/api/health`→`{"status":"ok"}`、`/` 返回前端 HTML(`<div id="app">`)、`/assets/*.js`→200。
- **同源前端**：`frontend/dist-desktop`（`VITE_BASE_URL=/` 构建，资产根相对、`/ai-builder/` 计数为 0）由 sidecar 的 FastAPI 在 `DESKTOP_MODE=1` 下用现成 `_SpaStaticFiles` 挂到 `/`，前端零改、无需 CORS/反代。
- **Tauri 壳**：Rust setup 选空闲端口 → spawn sidecar(传 `--port`/`--data-dir`) → 轮询 `/api/health` → 就绪后建名为 `"main"` 的窗加载 `http://127.0.0.1:<port>/` → 退出 kill sidecar。`cargo build` 干净通过。
- **运行链路（独立验证 + 视觉确认）**：双击 `.app` → Tauri 拉起 sidecar(引导进程 + uvicorn 子进程) → app.db/jwt_secret 落盘 → **WKWebView 渲染出完整「睿鲸 AI」登录页**（账号/密码/登录/夜间切换都在）→ 优雅退出后无残留进程（跨多个开/退循环验证）。
- **在线版安全**：所有桌面逻辑由 `DESKTOP_MODE` 门控 + playwright 改惰性 import（行为不变）。后端测试套件 **875 passed / 1 failed / 7 skipped**，唯一失败是预存的 `test_tool_registry`（app-health 白名单漂移，与本工作无关，零新增失败）。
- **kill-on-exit 真 bug 修复**：PyInstaller onefile fork 子 uvicorn，`CommandChild::kill()` 只杀引导进程 → 修 `kill_sidecar_deep`（杀引导前先 `pgrep -P` 收集子进程，再一起 SIGKILL，`ExitRequested`+`Exit` 双事件触发）。
- **隔离**：sidecar 只绑 `127.0.0.1`；`jwt_secret` 文件权限 `0o600`。

## 提交（8 个任务 + 1 个可复现性修复，分支 feat/desktop-phase0-spike）

1. `refactor(coding): playwright 改惰性 import`
2. `feat(desktop): DESKTOP_MODE 下 FastAPI 同源托管前端 SPA`
3. `feat(desktop): sidecar 入口 desktop_sidecar.py`
4. `build(desktop): 增 build:desktop (base=/)`
5. `build(desktop): PyInstaller spec 打 sidecar onefile`
6. `build(desktop): Tauri 脚手架 + externalBin/ATS/shell 权限配置`
7. `feat(desktop): Tauri setup 拉起 sidecar/等就绪/建窗/退出清理`
8. `build(desktop): 一键构建脚本 build-desktop.sh` + kill_sidecar_deep 修复
9. `build(desktop): build-desktop.sh 缺 pyinstaller 时自动补装`

## 如何构建 / 运行

```bash
# 前置: rustc/cargo, node/npm(根目录 npm install 装好 @tauri-apps/cli), backend/.venv
./scripts/build-desktop.sh
# 产物: src-tauri/target/release/bundle/macos/睿鲸 Builder.app + .../dmg/*.dmg
# 首次打开(未签名): xattr -dr com.apple.quarantine "<.app>" 或右键→打开
open "src-tauri/target/release/bundle/macos/睿鲸 Builder.app"
```

## Task 9 — 待你做的人工端到端验收（需真实凭据）

aPaaS/LLM **全部在应用内 UI 配置**（不写 env 文件，复用现成 `platform_envs`/`llm_configs`）：

1. 启动 `.app`（boot 不带任何 aPaaS/LLM env，自动 local-only 登录页）。
2. 用本地种子管理员账号 local-only 登录（凭据见 `backend/app/seed_data.py`）。
3. 「平台管理 → 模型配置」新增一个 LLM 配置：填 trial 可用的 base_url/api_key/model，设为默认。**必须先配 LLM**。
4. 「平台管理 → aPaaS 环境」新增平台环境：base_url=trial 的 aPaaS 地址、platform_tenant_id=mars 租户、username/password=mars 的 aPaaS 账密；保存后「登录/测试」确认 connected。
5. 进低代码配置主路径，把某应用绑到该 aPaaS 环境，做一次最小配置动作（让配置助手读 trial 上某表单 / 做一次字段级变更）。
6. 预期：能列出 trial 真实应用/表单（aPaaS 连通）+ 配置助手能调 LLM（LLM 连通）+ 动作落到 trial。
> 注：spike 用默认 ENCRYPTION_KEY（见 Phase-1 债 #1），此次 E2E 填的凭据当 throwaway 看待，等 #1 落地再正式用。

## Phase 1 债（终审汇总）

1. **`ALLOW_DEFAULT_ENCRYPTION_KEY=1`**（`desktop_sidecar.py`）→ 改成每实例持久化生成 `ENCRYPTION_KEY`（仿 `ensure_jwt_secret`）。DB 里的 aPaaS/LLM 凭据现在是用默认 key 加密的。
2. **ATS `exceptionDomain: ""`**（`tauri.conf.json`）放行了所有明文 http，不只 loopback → 收窄到 `127.0.0.1`/`localhost`。
3. **签名/公证**：对外卖前需 Apple Developer Program（99 美元/年）做 Developer ID 签名 + 公证（非 App Store）。
4. **aiomysql 瘦身**：`quick_db.py` 顶层 import aiomysql 导致 SQLite-only 的 sidecar 仍带 MySQL 驱动 → 可改惰性 import。
5. **清理**：删 `src-tauri/Cargo.toml` 未用依赖（`tauri-plugin-log`/`serde_json`）+ 脚手架占位（`authors=["you"]` 等）；考虑 onedir(更快启动) vs onefile。
6. **fresh sqlite 的 `no such table: coding_sessions`** 非致命 recovery sweep 告警（不影响 health/serving），可在桌面态静默或建表顺序修。
7. 多 profile 切换 UX + 首屏引导（设计文档 SP1）。

## 注意

- 工作树里有一批**与本工作无关的未提交改动**（`admin-spa/*`、`frontend/src/views/PlatformAdminEmbed.vue`、`vite.config.ts`、untracked `platformAdminEmbedState.*`），疑似并发的另一拨工作（Codex），全程未纳入本分支提交，原样保留。`src-tauri/Cargo.toml` 有个 `features = []` 的 no-op 未暂存改动（工具自动加），也未提交。
- 本分支未 push，未合并 dev（待 finishing-a-development-branch 决策）。
