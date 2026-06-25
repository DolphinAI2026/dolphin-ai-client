# 代码会话 · 工作区/分支/git 打通设计(Codex 式)

日期:2026-06-25
状态:设计待用户确认 → writing-plans
作者:大明哥 + Claude(brainstorming)
关联:统一外壳 [[unify-code-into-builder]](docs/superpowers/specs/2026-06-25-unify-code-into-builder-sp1-session-layer-design.md);现有 git 骨架 `app/routes/git_connection.py` / `app/git/provider/{github,gitlab}.py` / `app/git/workspace_sync.py`

## 1. 背景与目标

统一外壳(SP2b)已让代码会话在 Builder 里跑起来:从「我的开发」进 → 绑 `workspace_id` → agent 锁在该工作区读改代码,右栏 Codex 面板看文件/diff。**但输入框缺 Codex 那行 `[📁 项目 ▾] [⎇ 分支 ▾] [git]`**:看不到/不能切工作区、不能切分支、没跟公司 git 打通。

目标:给代码会话补上 Codex 式的**工作区 + 分支 + git 远程**能力。**模型 = 工作区级(Approach B,已确认)**:代码工作区本身是 git 仓,直连公司自建 GitLab/GitHub,切分支、push/pull;凭证/provider 复用现有骨架,但「连哪个仓 + 分支」记在工作区上(不绑应用也能用)。

## 2. 已确认决策

1. **模型 B(工作区级 git)**,非应用级。provider/PAT 那层复用现有,绑定记工作区。
2. **📁 切工作区 = 打开那个工作区的代码会话**(不改当前会话的绑定),像 Codex 切项目。
3. **git 用户驱动**:连/切分支/push/pull 走 UI。**agent 只改文件**;允许 agent `commit`(它已有 `run_workspace_command`),但 **push 必须用户点**(不自动 push、不 force)。
4. **三阶段全做**(P1 本地分支+工作区指示 / P2 远程 connect+push/pull / P3 clone-from-repo)。
5. 自建 host:`remote_url` 带公司域名;provider 客户端支持 self-hosted base。

## 3. 数据模型

新表 `workspace_git_remote`(一个工作区 0..1 条远程绑定):
| 列 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `ws_id` | String(64), unique index | 工作区 id(WorkspaceManager slug) |
| `tenant_id` / `user_id` | int, index | 作用域 |
| `provider` | String(20) | `github` / `gitlab` |
| `remote_url` | String(500) | 远程仓 URL(含自建 host) |
| `default_branch` | String(120) | 远程默认分支 |
| `git_connection_id` | int FK→`git_connections.id` | **复用现有 GitConnection 的加密 PAT** |
| `created_at`/`updated_at` | DateTime | |

- **当前分支不存库**:实时 `git rev-parse --abbrev-ref HEAD` 读,避免库/盘不一致。
- 凭证不在本表,引用 `GitConnection`(PAT 已 encrypt,不落明文、不进前端)。
- 迁移:`database.py` `init_db` 幂等 `ADD COLUMN`/建表 + `scripts/migrate_*.sql`(对齐 SP2a 经验:**既有库靠 init_db 建表/加列**)。

## 4. 后端

新 `app/git/workspace_git.py` —— 薄封装本地 git CLI(远程操作把 PAT 注入 remote URL,绝不打印):
- `current_status(ws_id)` → {branch, ahead, behind, dirty, has_remote, remote_url}
- `list_branches(ws_id)` → {local: [...], remote: [...]}(remote 需先 fetch)
- `checkout(ws_id, name, create: bool)`
- `connect_remote(ws_id, provider, remote_url, git_connection_id)` → 校验(provider 客户端验 host/PAT 可达)→ `git remote add/set-url` → fetch → 落 `workspace_git_remote`
- `push(ws_id)` / `pull(ws_id)` → 当前分支,PAT 注入,**只推当前分支、不 force**
- `clone(provider, remote_url, git_connection_id, ...)` → clone 成新工作区(P3,见 §6)

端点(挂 coding 路由,鉴权 + 工作区归属校验,复用 `_load`/relogin 模式):
- `GET  /coding/workspace/{ws}/git/status`
- `GET  /coding/workspace/{ws}/git/branches`
- `POST /coding/workspace/{ws}/git/checkout`  {name, create}
- `POST /coding/workspace/{ws}/git/connect`   {provider, remote_url, git_connection_id}
- `POST /coding/workspace/{ws}/git/push` / `…/pull`
- `POST /coding/workspaces/git/clone`          {provider, remote_url, git_connection_id, name}(P3)

复用:`GitConnection`(凭证 CRUD 已在 `git_connection.py`)、`git/provider/github.py`/`gitlab.py`(host/PAT 校验、self-hosted base)。**不复用** app 级 `sync-to-repo`/drift(那是应用→仓方向,本设计是工作区直连)。

## 5. 前端

新组件 `frontend/src/views/coding/CodeSessionGitBar.vue`,只在 `isCodeSession` 时挂在**输入框上方一行**(Codex 样):
```
[📁 工作区名 ▾]   [⎇ 当前分支 ▾]   [git: clean / ↑2 ↓0  · push · pull]
```
- **📁 工作区**:显当前绑定工作区名;下拉 = 工作区列表(`codingApi`)+「我的开发」,选一个 → `router.push(/ai-chat?workspace_id=X&mode=code)`(复用 SP2b 的入口 → 开/载该工作区的代码会话)。
- **⎇ 分支**:显 `git/status.branch`;下拉列 `git/branches`(本地+远程),点切(`checkout`),底部「+ 新建分支」。
- **git 区**:
  - 未连远程 → `[连接 git]` → 弹窗:provider + 仓库 URL(含自建 host)+ 选/新增 PAT 凭证(复用 GitConnection)→ `connect`。
  - 已连 → 显 clean/↑n↓n/dirty + `[push]` `[pull]`(用户点)。
- 状态懒拉(面板/输入区可见时 `status`;切分支/push/pull 后刷新)。

## 6. 分阶段(三件一起设计,分着上;每阶段一份 implementation plan)

- **P1 — 工作区指示 + 本地分支**(纯本地,无远程):`CodeSessionGitBar` 显 📁 工作区(+切)、⎇ 列/切/建**本地**分支;后端 `status`/`branches`(local)/`checkout`。工作区本就是 git 仓 → 不碰远程、不建新表。**立刻补「绑定看得见 + 能切分支」。**
- **P2 — 连公司 GitLab/GitHub + push/pull**:`workspace_git_remote` 表 + `connect`/`push`/`pull`/remote `branches`/ahead-behind;前端「连接 git」弹窗 + push/pull。**git 打通核心。**
- **P3 — clone-from-repo**:从远程仓 clone 起一个新工作区(Codex「打开 repo」)。`clone` 端点 + 「我的开发」加「从 git 仓打开」入口 → clone 进 workspaces → 建 code 会话绑它。**最 Codex,最后上。**

每阶段自带可独立验收的产物;P1 不依赖 P2/P3。

## 7. agent 边界
- agent 维持现状:dev-apaas profile,改文件/读代码/跑命令(含 `git` 只读/`git commit`)。
- **不给 agent push/连远程的自动权**:push/pull/connect 只走 UI 用户点。防误推公司仓。
- (后续可选)给 agent 一个「提议 push」→ 用户确认的工具,不在本 spec。

## 8. 安全
- PAT:复用 `GitConnection` 加密存;后端注入 remote URL 时用,**不进日志、不回前端**。
- 自建 host:`remote_url` / provider base 支持公司域名(provider 客户端已支持)。
- push:只当前分支、需用户点、不 `--force`。
- 工作区归属:所有端点校验 ws 属当前 user/tenant。

## 9. 测试
- 后端:`workspace_git.py` 纯函数/CLI 封装单测(用临时 git 仓 fixture):status/branches/checkout/connect(mock provider)/push-pull(mock remote 或 bare 本地远程)。
- 前端:`CodeSessionGitBar` 组件测(显当前分支、切分支调 API、未连/已连两态)。
- 真机:P1 切本地分支;P2 连一个真自建 GitLab 仓 push/pull;P3 clone 一个仓起工作区。

## 10. 验收标准
- 代码会话输入框上方有 `[📁 工作区 ▾][⎇ 分支 ▾][git]` 一行,Codex 样。
- 能看到当前工作区、切到别的工作区(开对应会话)。
- 能列/切/建本地分支(P1)。
- 能连公司 GitLab/GitHub、push/pull、看 ahead/behind(P2)。
- 能从远程仓 clone 起一个工作区并进代码会话(P3)。
- PAT 不泄露;agent 不自动 push。
