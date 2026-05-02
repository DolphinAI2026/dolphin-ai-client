# 沙箱监控 (`/vibe-coding/sandboxes`)

**管理你（或本租户 / 全平台）跑着的 Vibe Coding 沙箱容器，避免资源泄漏。**

入口：左侧导航栏「**沙箱监控**」（仪表盘图标）。所有用户都能看到入口，但能管理的范围按角色分级。

## 权限分层

| 角色 | 可见范围 | 标识 |
|---|---|---|
| **平台管理员**（`is_platform_admin=true` 或 `tenant_role=platform_admin`） | 所有租户的所有 sandbox | 顶部显示"平台管理员视角 — 所有租户的所有 sandbox" |
| **租户管理员**（`tenant_role=tenant_admin`） | 本租户内所有用户的 sandbox | 顶部显示"租户管理员视角 — 本租户内所有用户的 sandbox" |
| **普通用户** | 只显示自己创建的 sandbox | 顶部显示"只显示你自己创建的 sandbox" |

## 表格列说明

- **Workspace**：工作区标题（点击可跳进 chat） + workspace_id
- **Owner**（admin 视角）：sandbox 所属用户名
- **Tenant**（platform 视角）：sandbox 所属租户 ID
- **状态**：
  - 🟢 **运行中**：容器跑着 + 容器内有进程在监听端口
  - **已停止**：容器 exited
  - **未启动**：容器从未创建过
  - **已暂停**：podman pause 状态（少见）
- **端口映射**：容器内端口 → host 端口（如 `6173 → :39321`）；只列**真正在监听**的（避免死链接）
- **更新时间**：sandbox 元数据上次变化时间（人类可读相对时间）
- **操作**：见下

## 操作按钮（按状态显示）

| 状态 | 启动 | 停止 | 删除容器 |
|---|---|---|---|
| 运行中 | — | ✓ 停止 | ✓ 删除容器 |
| 已停止 / 未启动 | ✓ 启动（绿色） | — | ✓ 删除容器 |

### 启动

- 容器不存在 → 创建并启动（podman run）
- 容器 exited → 直接 start 复用（之前装的 node_modules 都还在）
- **自动恢复 dev server**：之前 agent 跑过的 `npm run dev` 等后台命令会被记录到 workspace meta，启动时自动 docker exec 重跑，几秒后端口监听回归

### 停止

- 保留容器壳（node_modules 不丢、container 文件系统保留）
- 下次"启动"会自动恢复之前的 dev server

### 删除容器

- 彻底清理容器（包括 node_modules 等容器层数据）
- **workspace 用户代码不动**（host 上的 repo 文件保留）
- 下次启动需重新 npm install 装依赖

## 自动刷新

- 默认每 5 秒自动拉一次状态
- 顶部统计卡：运行中 / 已停止 / 总计
- 复选框可关闭自动刷新；旁边有手动 ↻ 刷新按钮

## 常见疑问

### 显示"运行中"但端口映射 = "—"

容器活着，但里面**没进程在监听端口**——通常是 dev server 没跑（或者 agent 在装依赖）。
- 等 agent 跑完 `npm run dev`
- 或者点"停止"再点"启动"自动恢复 dev server

### 启动后预览还看不到

- 强刷浏览器（`Cmd + Shift + R`）
- 检查工作区里 `vite.config.ts` 是否包含 `server.allowedHosts: ['.vibe-first.cn']`，不包含 vite 会拒绝域名访问
- F12 看 console 报错

### 资源紧张时如何快速腾资源

按更新时间倒序排表格，**找最久没动过的 sandbox 点"停止"**（保留代码 + node_modules 但释放内存 / CPU）。彻底不要的点"删除容器"。

## 后端 API

- `GET /api/online-coding/sandboxes` — 列表（按权限过滤）
- `POST /api/online-coding/sandboxes/{id}/start` — 启动 + 自动恢复 dev server
- `POST /api/online-coding/sandboxes/{id}/stop` — 停止（保留容器壳）
- `DELETE /api/online-coding/sandboxes/{id}` — 强删容器（不删 workspace 代码）
