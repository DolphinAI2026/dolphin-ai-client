# 桌面「打开本地文件夹」工作区设计

- 日期: 2026-06-17
- 分支: `feat/desktop-login-mvp`（桌面工作分支；本设计是桌面交付驾驶舱方向的一部分）
- 关联背景: [[desktop_delivery_cockpit_2026_06_16]]、[[coding_workspace_changes_git_baseline]]、[[arch_hardening_2026_06_14]]
- 来源: 用户问「要不要打通 desktop 和用户电脑、直接用本地文件夹当工作区」。澄清后确认：工作区文件**早已在本地磁盘**（原生 fs 读写，无 DB blob），真正缺的是「让用户用**自己选的文件夹**就地干活」（VS Code / Claude Code 的 open-folder 模型），而非现在的「app 托管隐藏目录」。

## 背景与现状（已核实）

- 工作区文件是**真实本地文件**：coding 工具走原生 fs（`backend/app/coding/tools.py` `read_text`/`write_text`/`open`），无任何把文件内容存进 DB 的 blob 表。
- 工作区**靠扫文件系统发现**：`WorkspaceManager._iter_workspace_dirs()`（`backend/app/coding/workspace.py`）扫 `WORKSPACE_SEARCH_ROOTS` 下**带 `.workspace.json` 的子目录**。DB 只有指针列（`AIChatSession.workspace_dir` String(500)、各表 `workspace_id`）。
- 工作区根：`WORKSPACE_ROOT` = `os.environ["APAAS_WORKSPACE_ROOT"]`（`workspace.py:34`）或回落 `REPO_ROOT/workspaces`（`workspace.py:30`）。
- 路径牢笼**已有**：`_resolve_safe(file_path, workspace_path)`（`tools.py:201`）逃出工作区即 `raise ValueError`。
- 桌面 sidecar **不注入 `APAAS_WORKSPACE_ROOT`** → 打包后 app 托管工作区落到 `REPO_ROOT/workspaces`，在冻结 .app 里是相对二进制的诡异/易失路径（一并修）。
- Tauri 当前插件：shell/updater/process（`src-tauri/Cargo.toml`），**无 dialog** → 原生文件夹选择器需新增 `tauri-plugin-dialog`。

## 已定决策（brainstorm）

1. **双模并存（增量）**：保留 app 托管目录做 0→1 脚手架新建；新增「打开本地文件夹」给「本地已有项目就地改」。不改现有创建流程。
2. **元数据只进 DB，不写用户文件夹**：用户文件夹保持干净（不写 `.workspace.json`），指针/归属进 SQLite（VS Code 模型）。代价：文件夹移动/重命名后链接断 → 重新打开即可（本轮非目标自动重连）。
3. **路径牢笼 + 写前确认高危**：读写锁在用户选定文件夹内（复用 `_resolve_safe`）；删除/批量覆盖/移动走确认门；普通编辑在牢笼内自动应用。
4. **可选关联 aPaaS 应用**：打开的文件夹可绑一个 aPaaS 应用，agent 拿其模型/菜单上下文做二次开发（复用现有 app-context 喂 codegen 机制）；不绑 = 纯本地。

核心架构选择 = **DB 注册表**（而非 app 目录放 JSON 索引）：与「指针进 DB」一致，租户作用域/归属/查询都顺。

## 范围

- Part A — 数据模型：`registered_workspace` DB 表。
- Part B — WorkspaceManager 识别 external 工作区（DB 优先）+ 列表合并。
- Part C — 打开文件夹流程：Tauri 文件夹选择器 + 后端注册端点 + 前端入口（仅 `__DESKTOP__`）。
- Part D — 安全边界：路径牢笼（复用）+ 写前确认高危 + 选目录敏感校验。
- Part E — app 关联：external workspace ↔ aPaaS 应用（喂 codegen 上下文）。
- Part F — 顺带修：桌面 `APAAS_WORKSPACE_ROOT` 落点。

### 非目标（本轮明确不做）

- Windows 文件夹选择器（先 macOS，与桌面整体一致，后置）。
- 多文件夹 / multi-root workspace（先单文件夹）。
- 在线版「打开本地文件夹」（无本地文件夹概念）。
- 工作区文件夹移动/重命名后的自动重连（断了重新打开）。
- 把现有 app 托管创建流程改造成「用户可见文件夹」（那是「本地文件夹为主」模型，本轮选了双模并存）。
- **约束 run_command / 运行时沙箱 / 敏感路径隔离**（P2，对齐竞品分析 WorkBuddy 沙箱缺口）——本轮 run_command 维持开口 shell，安全靠路径牢笼+软删除+打开时确认。

---

## Part A — 数据模型：`registered_workspace`

新增表（SQLAlchemy 模型 + `database.py` 幂等迁移）：

| 列 | 类型 | 说明 |
|---|---|---|
| `ws_id` | String(60) PK | 工作区 id（与现有 `workspace_id` 列同形态，便于 session 复用）|
| `abs_path` | String(1000) | 用户选的文件夹绝对路径 |
| `user_id` | Int FK users.id | 归属用户 |
| `tenant_id` | Int FK tenants.id, index | 租户作用域 |
| `workspace_type` | String(40) default `'external'` | 区分 app 托管 / external |
| `apaas_app_id` | String(60) nullable | 可选关联的 aPaaS 应用（Part E）|
| `display_name` | String(200) | 列表展示名（默认取文件夹名）|
| `created_at` / `last_opened_at` | DateTime | |

唯一约束：`(tenant_id, abs_path)`——同租户同一文件夹只注册一次（重复「打开」复用既有行、更新 `last_opened_at`）。

## Part B — WorkspaceManager 识别 external

- `get_workspace_path(ws_id)`：**先查 `registered_workspace`**（按 ws_id），命中 external → 返回 `abs_path`（先校验目录仍存在，不存在抛可读错误「文件夹已移动/删除，请重新打开」）；未命中 → 走现有文件系统扫描（app 托管）。
- 工作区**列表** = 文件系统发现（app 托管，现有 `_iter_workspace_dirs`）∪ DB 注册（external，按 tenant 过滤）。两边都打 `workspace_type` 标识，前端区分展示。
- ⚠️ external 工作区**不参与** `_iter_workspace_dirs` 扫描（它们不在 WORKSPACE_SEARCH_ROOTS、也无 `.workspace.json`）——只经 DB 注册表识别。
- `_resolve_safe(file_path, workspace_path)` 不改：external workspace 的 `workspace_path` = 用户文件夹，牢笼自动生效。

## Part C — 打开文件夹流程

1. **Tauri 文件夹选择器**：`Cargo.toml` 加 `tauri-plugin-dialog`，`lib.rs` 注册，capability 加 `dialog:allow-open`。前端经 `@tauri-apps/plugin-dialog` 的 `open({ directory: true })` 弹原生选择器，拿绝对路径。仅 `__DESKTOP__`（动态 import，在线 build tree-shake）。
2. **后端注册端点**：`POST /api/coding/workspaces/open-local` `{ abs_path, apaas_app_id? }` → 校验（目录存在、非敏感目录、租户配额）→ upsert `registered_workspace` → 返回 `ws_id`。tenant_admin/owner 作用域。
3. **前端入口**：`WorkspaceCatalogPage`（自开发资产库）加「打开本地文件夹」按钮（仅桌面）→ 选目录 → 调注册端点 → 进 coding 工作区（复用现有 session→workspace 链路，原生文件树/viewer/diff 直接读 abs_path）。

## Part D — 安全边界

> ⚠️ 规划期核实修正：coding agent **没有交互式确认门**（配置侧 SpecApplyModal 是另一条 batch plan→apply 链；coding 侧 run_agent 自主跑工具、写/删自动应用，只有 `tools.py` 的「补丁守卫」软警告 write_file >50% 重写）。且 `run_command` 是开口 shell——路径牢笼 `_resolve_safe` 只管文件工具，管不了 shell（agent 可经绝对路径 `rm -rf ~` 绕过）。故原「写前确认门」不可复用。本轮采用**能落地的安全姿态**（用户已拍板：本轮不约束 run_command）：

1. **路径牢笼（文件工具）**：复用 `_resolve_safe`（`tools.py:201`，已 raise on escape）。external root = abs_path。read/write/edit/glob/grep 等文件工具经它解析，禁 `..`/绝对路径越界。external 与 app 托管共用同一牢笼，零新增。
2. **软删除回收站**：external 工作区里文件删除（`_edit_file` 的 `resolved.unlink()` 路径，`tools.py:358`）改为**移到可恢复回收站**（app_data_dir 下 `.trash/<ws_id>/<时间戳>/`），不硬删。给「误删可恢复」的安全网，无需不存在的交互确认门。app 托管工作区维持现状（爆炸半径本就在 app 目录内）。
3. **打开文件夹一次性风险确认**：前端打开本地文件夹流程里，选目录后弹一次确认——「AI 可在此文件夹内读写并运行命令（run_command 不受沙箱限制），建议选用 git 管理或已备份的目录」。用户确认后才注册。设定预期，是本轮对 run_command 开口的主要缓解。
4. **选目录敏感校验**：注册端点拒绝高风险根（`/`、用户家目录根 `~`、`/System`、`/Library`、卷根 `/Volumes/*` 顶层等）——避免误把整个家目录交给 agent。给可读错误，不静默放行。
5. **run_command 不约束（本轮）+ 真沙箱后置 P2**：run_command 仍是开口 shell（已知限制，文档明示）。真正约束 run_command / 运行时沙箱 / 敏感路径隔离 = 独立 P2（对齐竞品分析里 WorkBuddy 三维安全那个缺口），本轮不做。

## Part E — app 关联

- 注册时可带 `apaas_app_id`，写入 `registered_workspace.apaas_app_id`。
- coding agent 启动时若 workspace 绑了 app → 经现有「app 上下文喂 codegen」机制（见 [[coding_app_context_into_codegen]]）把该应用的模型/菜单/场景作为只读上下文喂入，agent 据此做二次开发。
- 不绑 = 纯本地开发，agent 只看文件夹内容。
- 解绑/换绑：列表项可改 `apaas_app_id`（PATCH 注册行）。

## Part F — 顺带修：桌面 `APAAS_WORKSPACE_ROOT`

`backend/desktop_sidecar.py` `build_env` 设 `APAAS_WORKSPACE_ROOT = <data_dir>/workspaces`（app_data_dir 下，稳定持久），修「冻结包里 app 托管工作区落到相对二进制诡异路径」。这是 Mode 1（app 托管）的桌面落点，与本设计的 external 工作区（Mode 2）正交但一并定清楚。

## 测试策略

- Part A：`registered_workspace` 迁移幂等；唯一约束 `(tenant_id, abs_path)` 去重。
- Part B：`get_workspace_path` external 优先；目录不存在抛可读错误；列表合并（app 托管 ∪ external）按 tenant 过滤。
- Part C：注册端点 upsert（重复打开复用行 + 更新 last_opened_at）；租户作用域 403。
- Part D：`_resolve_safe` 对 external root 拒 `..`/越界（已有逻辑回归 + external root 用例）；external 工作区删除走软删除回收站（文件移到 `.trash` 可恢复、源消失）、app 托管维持硬删；敏感目录（`/`、家目录根、`/System` 等）注册被拒；打开流程含一次性风险确认（前端）。
- Part E：绑 app 的 workspace agent 上下文含该 app 模型；不绑不含。
- Part F：`build_env` 设 `APAAS_WORKSPACE_ROOT` 指向 data_dir/workspaces。

## 风险

- DB 注册表与现有「扫 .workspace.json」两套发现机制并存：`get_workspace_path` 与列表必须两边都查，漏一处会出现「列表有但打不开」或反之。按 grep 校验所有 `get_workspace_path`/列表入口都走合并逻辑。
- run_command 开口 shell 是已知未闭合风险（本轮不约束）：用户的真实文件夹下 agent 经 run_command 仍能触达机器任意路径。软删除只覆盖文件工具删除路径，不覆盖 `rm` via run_command。主要缓解是打开时风险确认 + 用户选 git/备份目录。真闭合需 P2 沙箱。
- Tauri dialog 插件 + capability：桌面包 JS 调 dialog 命令同样要 capability 覆盖（参考 [[desktop_auto_update_2026_06_16]] 的 remote.urls ACL 坑——sidecar 远程源下 Tauri 命令要 capability 放行）。
- 敏感目录黑名单是兜底非万能；用户仍可能选含敏感数据的项目目录——牢笼限制爆炸半径是主要防线，黑名单只挡最离谱的根目录。
