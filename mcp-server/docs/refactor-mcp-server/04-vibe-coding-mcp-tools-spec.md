# 04 · Vibe Coding 9 个 MCP 工具规范

> Phase 3 实施。把现有 `backend/app/vibe_coding/` 的内置 agent 工具升级为对外 MCP 工具，dolphin agent 可调。
> 实现思路：包装 `DockerRuntime` (podman 沙箱) + `vibe_coding/tools.py` 现有 execute_* helper + `WorkspaceManager` (workspace CRUD)。

## 设计原则

1. **多 tenant 隔离**：每个沙箱 workspace 物理目录 = `_online_coding/{tenant_id}/{user_id}_{ws_id}/`，跟现有 dev-coding workspace 同隔离模型
2. **复用现有沙箱基础设施**：不重建 podman 接入，包装 `DockerRuntime.exec` / `ensure_container` / `host_port` 现成方法
3. **resource limits**：每个工具调用有 timeout（exec ≤ 60s）+ output truncate（≤ 8KB），避免 dolphin omnigate 30s 超时
4. **身份解析**：复用 `_resolve_identity` 走 caller-trusted user_id/tenant_id 或 ContextVar；沙箱 owner = user_id

## 9 个 MCP 工具签名

```python
@mcp.tool()
async def vibe_create_sandbox(
    project_name: str,                  # kebab-case，如 "vue-todo-app"
    git_url: str = "",                  # 可选，import 已有 Git repo
    git_branch: str = "main",
    template: str = "vite-vue-ts",      # 内置模板：vite-vue-ts / next-ts / express / fastapi / java-spring
    display_name: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """🆕 起 podman 沙箱给 dolphin agent 跑全代码项目。

    用户："给我用 Vue3 + Vite 起一个 todo app"
    → dolphin agent 调本工具 → 拿 ws_id → vibe_run_in_sandbox 写代码 + npm install + npm run dev
    → vibe_get_preview_url 拿沙箱 URL 给用户

    返回：{"ok": true, "ws_id": "...", "preview_url_hint": "...", "container_status": "running"}
    """


@mcp.tool()
async def vibe_list_sandboxes(
    status: str = "",                   # "running" / "stopped" / ""=全部
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列当前用户的 Vibe Coding 沙箱（受 tenant 隔离）。

    返回：{"ok": true, "sandboxes": [{ws_id, project_name, container_status, created_at, ...}]}
    """


@mcp.tool()
async def vibe_run_in_sandbox(
    ws_id: str,
    command: str,                       # bash 命令
    timeout: int = 30,                  # 秒，max 60
    background: bool = False,           # 后台跑（适合 npm run dev / build watcher）
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """在沙箱内执行 shell 命令。

    与 dev-coding `run_workspace_command` 区别：dev-coding 是 host shell（受限），
    本工具是 podman 沙箱（隔离）。

    返回：{"ok": true, "stdout": "...", "stderr": "...", "exit_code": 0, "truncated": false}
    """


@mcp.tool()
async def vibe_read_sandbox_file(
    ws_id: str,
    file_path: str,
    max_bytes: int = 65536,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """读沙箱内文件内容（仅文本）。

    返回：{"ok": true, "content": "...", "size": 1234, "truncated": false}
    """


@mcp.tool()
async def vibe_write_sandbox_files(
    ws_id: str,
    files: list[dict],                  # [{file_path, content}, ...]
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """批量写沙箱内多个文件（覆盖）。

    入参示例：
      files=[
        {"file_path": "src/App.vue", "content": "<template>..."},
        {"file_path": "src/main.ts",  "content": "import { createApp ..."},
      ]

    返回：{"ok": true, "files_written": 2, "files_failed": []}
    """


@mcp.tool()
async def vibe_glob_sandbox(
    ws_id: str,
    pattern: str = "**/*",              # 如 "**/*.vue" / "src/**/*.ts"
    max_results: int = 200,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """找沙箱内文件（按 glob pattern）。

    返回：{"ok": true, "files": ["src/App.vue", ...], "total": 12, "truncated": false}
    """


@mcp.tool()
async def vibe_get_preview_url(
    ws_id: str,
    container_port: int = 3000,         # 默认 vite/next dev server port
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """拿沙箱预览 URL（基于 podman 端口映射 + vibe-first.cn 子域反代）。

    返回：{"ok": true, "preview_url": "https://abc123.vibe-first.cn", "host_port": 32768}

    用户在 dolphin chat 拿 URL → 浏览器新 tab 打开 → 看跑起来的应用。
    """


@mcp.tool()
async def vibe_destroy_sandbox(
    ws_id: str,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """销毁沙箱（停 + 删 podman container + 不动 workspace 源码目录）。

    返回：{"ok": true, "ws_id": "...", "freed_disk_mb": 234}

    业务用例：用户"做完了，关掉这个沙箱"。源码保留作历史，下次可以重新 vibe_create_sandbox + import。
    """


@mcp.tool()
async def vibe_get_logs(
    ws_id: str,
    tail: int = 200,                    # 拉最后 N 行
    container_or_command: str = "container",  # "container"=podman logs / "命令名"=后台命令日志
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """拉沙箱日志（podman container 日志 或 后台命令日志）。

    适用：vibe_run_in_sandbox(command, background=true) 后查 build 输出 / 服务运行日志。

    返回：{"ok": true, "logs": "...", "tail": 200, "truncated": false}
    """
```

## 实现要点

### `vibe_coding_mcp.py` 新文件（mcp_server.py 太长，独立文件）

```python
# backend/app/vibe_coding_mcp.py

from app.mcp_server import mcp, _resolve_identity, _business_error, logger
from app.vibe_coding.docker_runtime import get_runtime
from app.vibe_coding.workspace import find_workspace, get_repo_dir
from app.vibe_coding import tools as vibe_tools  # 现有 9 个 execute_* helper

@mcp.tool()
async def vibe_create_sandbox(...):
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    # 调内部 endpoint /api/vibe-coding/workspaces 起 workspace
    # 或者直接调 vibe_coding.workspace 内的 helper（如果有 create_workspace）
    ...

@mcp.tool()
async def vibe_run_in_sandbox(ws_id: str, command: str, ...):
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    # 权限校验：workspace owner 必须是当前 user
    ok, reason = workspace_member_can_access(ws_id, uid, tid)
    if not ok: return _business_error(op="run_in_sandbox", error_text=reason)
    # 调 DockerRuntime.exec
    runtime = get_runtime()
    if not await runtime.is_available():
        return _business_error(op="run_in_sandbox", error_text="podman 沙箱运行时不可用")
    result = await runtime.exec(ws_id, command=command, timeout=timeout)
    # 截断输出（≤ 8KB 避免 dolphin 超长 input）
    return {
        "ok": result.exit_code == 0,
        "stdout": _truncate(result.stdout, 8192),
        "stderr": _truncate(result.stderr, 4096),
        "exit_code": result.exit_code,
        "truncated": len(result.stdout) > 8192 or len(result.stderr) > 4096,
    }
```

### 内置模板

`vibe_create_sandbox(template="vite-vue-ts")` 后端起容器时拉对应模板：

| template | 镜像 | 默认端口 |
|----------|------|---------|
| `vite-vue-ts` | `node:20-alpine` + Vite + Vue 3 + TypeScript 模板 | 5173 |
| `next-ts`     | `node:20-alpine` + Next.js 14 + TypeScript 模板 | 3000 |
| `express`     | `node:20-alpine` + Express + TypeScript 模板 | 3001 |
| `fastapi`     | `python:3.13-slim` + FastAPI 模板 | 8000 |
| `java-spring` | `eclipse-temurin:21-jdk` + Spring Boot 模板 | 8080 |
| `blank`       | `node:20-alpine` 空容器（用户自己 init） | - |

模板内容存在 `backend/templates/vibe-coding/{name}/` 目录，create_sandbox 时 copy 进容器。

### 安全限制

| 限制 | 值 | 实现 |
|------|-----|------|
| 单 tenant 最多沙箱数 | 10 | `tenant_quota.py` 加查 vibe_workspaces count |
| 单沙箱 CPU | 2 core | `podman run --cpus=2.0` |
| 单沙箱内存 | 2GB | `podman run --memory=2g` |
| 单沙箱磁盘 | 5GB | `podman run --storage-opt size=5G` |
| 沙箱网络 | 限制出站（白名单 npm/pypi/maven/git） | podman bridge + iptables |
| 沙箱超时 idle | 30 分钟 | `_vibe_reap_loop` 已经实现，自动 stop 闲置容器 |
| 单 exec 命令 timeout | 60s 上限 | 工具签名 max 60 |
| 输出截断 | 8KB stdout / 4KB stderr | helper `_truncate` |

### dolphin 30s timeout 适配

跟 `deploy_application` 同样问题：长命令（如 `npm install`）可能跑 60s 也跑不完。

**策略**：所有可能长跑的命令默认 `background=true`，立即返 `{ok:true, status:'started'}`，让 agent 后续调 `vibe_get_logs(ws_id, "command_name")` 轮询查进度。

agent 在 prompt 里需要被教：
- `npm install` / `pip install` / `mvn package` → 总是 background=true
- `git clone` → 短时间内能完，background=false
- `npm run dev` / `python main.py` (server 启动) → background=true 永久跑

## 数据模型新增（可选）

复用 `coding_workspaces` 表（已有 dev-coding workspace 用了），加一列区分：

```sql
ALTER TABLE coding_workspaces
  ADD COLUMN workspace_kind VARCHAR(20) DEFAULT 'dev_coding' COMMENT 'dev_coding / vibe_coding';
```

或者**新建独立表** `vibe_workspaces` 跟 dev-coding 解耦：

```sql
CREATE TABLE vibe_workspaces (
  id INT PRIMARY KEY AUTO_INCREMENT,
  ws_id VARCHAR(64) UNIQUE NOT NULL,
  tenant_id INT NOT NULL,
  user_id INT NOT NULL,
  project_name VARCHAR(128),
  display_name VARCHAR(128),
  template VARCHAR(32),
  git_url VARCHAR(255),
  container_status VARCHAR(32) DEFAULT 'created',
  container_name VARCHAR(64),
  preview_url VARCHAR(255),
  storage_dir VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  last_active_at DATETIME,
  INDEX idx_tenant_user (tenant_id, user_id, container_status)
);
```

**建议独立表**，跟 dev-coding workspace 分离，避免互相影响。

## Phase 3 工作量分解

| 子任务 | 估时 |
|--------|------|
| 新建 `vibe_workspaces` 表 + migration | 0.5h |
| 新建 `vibe_coding_mcp.py` 文件 + 9 工具签名 | 2h |
| 复用 `DockerRuntime` 实现 9 工具内部逻辑 | 6h |
| 5 个内置模板 (template/vibe-coding/{name}) | 4h |
| 沙箱多 tenant 隔离 + 配额检查 | 2h |
| podman 网络白名单（出站限制） | 2h |
| 长命令 background + 日志轮询协议 | 2h |
| MCP 工具描述 + prompt 提示 | 1h |
| 单元测试 / 集成测试 | 2h |

**合计 ~ 21.5h = 3 工作日**。

## 测试场景

部署后跑这些验证：

```
用户: 给我用 vite + vue3 起一个 todo app
agent: > 🔍 起沙箱 vibe_create_sandbox(template="vite-vue-ts", project_name="todo-app")
agent: ✅ 沙箱 ws_id=23_t0d0 已就绪
agent: > 🔍 写代码 vibe_write_sandbox_files(files=[App.vue, main.ts, ...])
agent: > 🔍 启动 dev server vibe_run_in_sandbox(command="npm install && npm run dev", background=true)
agent: > 🔍 拿预览 URL vibe_get_preview_url(ws_id="23_t0d0", container_port=5173)
agent: 你的 todo app 已经跑起来了：<a href="https://abc123.vibe-first.cn" target="_blank">预览</a>

用户: 我想再加个删除按钮
agent: > 🔍 read App.vue / glob src/**/*.vue
agent: > 🔍 edit_workspace_files 加 delete handler
agent: > 🔍 vite hot reload 自动生效
agent: 改完了，刷新预览页面看效果

用户: 不要这个沙箱了
agent: > 🔍 vibe_destroy_sandbox(ws_id="23_t0d0")
agent: ✅ 沙箱已销毁，释放 230MB 磁盘
```

## 不实现的能力（明确范围）

❌ **持久化部署**：Vibe Coding 沙箱定位是"快速 prototype"，不做生产部署。生产请走 apaas 低代码 + dev-coding 自开发或独立 K8s 集群。

❌ **多容器 docker-compose**：单沙箱单容器。如果用户要 frontend + backend + db，建议分开起 3 个沙箱用 host network 互连。

❌ **GPU 沙箱**：trial 阶段不支持。

❌ **用户上传文件**：用户不能传任意文件进沙箱（避免恶意），只能通过 vibe_write_sandbox_files 写文本/代码文件。
