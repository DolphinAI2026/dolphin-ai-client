"""Vibe Coding MCP Tools — Phase 3 (2026-05-11)

把 `app.vibe_coding/` 现有 podman/docker 沙箱基础设施包装为 MCP 工具暴露给
dolphin agent。dolphin agent 调这 9 个工具可以「起沙箱 → 写代码 → 跑命令
→ 拿预览 URL」一站式落地用户的 vibe coding 需求。

规约：
  - 多 tenant 隔离：workspace 物理目录 = `_online_coding/{tenant_id}/{slug}__{ws_id}/`，
    跟现有 online-coding workspace 同隔离模型
  - 权限：每个工具先 `_resolve_identity` → 拿 (tid, uid)，对 workspace 必须 owner=uid
  - 资源：复用 DockerRuntime 单镜像 `vibe-sandbox:latest`，单容器 2g/2cpu 限制
  - 输出截断：stdout ≤ 8KB / stderr ≤ 4KB，避免 dolphin 30s timeout + 长 input

设计文档：`docs/refactor-mcp-server/04-vibe-coding-mcp-tools-spec.md`
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.mcp_server import mcp, mcp_vibe, _resolve_identity, _business_error
from app.vibe_coding.docker_runtime import get_runtime
from app.vibe_coding.workspace import find_workspace, get_repo_dir, resolve_path, member_can_access

logger = logging.getLogger(__name__)


# ─────────────────────────── 内部 helper ───────────────────────────

_STDOUT_LIMIT = 8192
_STDERR_LIMIT = 4096
_FILE_READ_LIMIT_DEFAULT = 65536
_GLOB_MAX_DEFAULT = 200

# 支持的内置模板（v1 只占位，实际行为都是空目录 + 容器自带 node/npm；
# Phase 3.2 再实现 template/vibe-coding/{name}/ 内容复制）
_TEMPLATES = {"blank", "vite-vue-ts", "next-ts", "express", "fastapi", "java-spring"}
_DEFAULT_PORTS = [6173, 6300, 6400, 6500]


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """返回 (截断后文本, 是否截断)。"""
    if not text:
        return text or "", False
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n... (truncated, original {len(text)} chars)", True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _online_coding_module():
    """延迟 import routes.online_coding，避免循环依赖。"""
    from app.routes import online_coding as oc
    return oc


def _public_workspace_view(meta: dict, container_status: Optional[str]) -> dict:
    """给 MCP 工具返回的精简 workspace 视图（subset of OnlineCodingWorkspace）。"""
    return {
        "ws_id": meta.get("id"),
        "project_name": meta.get("task") or meta.get("repo_url") or "",
        "user_id": int(meta.get("user_id") or 0),
        "tenant_id": int(meta.get("tenant_id") or 0),
        "status": meta.get("status") or "created",
        "sandbox_status": meta.get("sandbox_status") or "not_configured",
        "container_status": container_status,
        "template": meta.get("template") or "blank",
        "git_url": meta.get("repo_url") or "",
        "created_at": meta.get("created_at") or "",
        "updated_at": meta.get("updated_at") or "",
    }


async def _require_workspace(ws_id: str, uid: int, tid: int) -> tuple[Optional[Path], Optional[dict], Optional[dict]]:
    """工具入口统一 workspace + 权限校验。

    返回 (ws_dir, meta, None) 成功；(None, None, business_error_dict) 失败。
    """
    found = find_workspace(ws_id)
    if not found:
        return None, None, _business_error(
            op="vibe_workspace",
            error_text=f"沙箱 ws_id={ws_id} 不存在",
            extra={"error_code": "VIBE_WS_NOT_FOUND"},
        )
    ws_dir, meta = found
    ok, reason = member_can_access(ws_id, uid, tid)
    if not ok:
        return None, None, _business_error(
            op="vibe_workspace",
            error_text=reason or "无权访问该沙箱",
            extra={"error_code": "VIBE_WS_FORBIDDEN", "ws_id": ws_id},
        )
    return ws_dir, meta, None


# ─────────────────────────── 9 个 MCP 工具 ───────────────────────────


@mcp.tool()
async def vibe_create_sandbox(
    project_name: str,
    git_url: str = "",
    git_branch: str = "main",
    template: str = "blank",
    display_name: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """🆕 起一个 podman/docker 沙箱跑全代码项目。

    用户场景："给我用 Vue3 + Vite 起一个 todo app"
    → agent 调本工具拿 ws_id → vibe_write_sandbox_files 写代码 → vibe_run_in_sandbox 跑 npm install + npm run dev
    → vibe_get_preview_url 拿预览 URL 给用户

    参数：
      - project_name: kebab-case，如 "vue-todo-app"
      - git_url: 可选，给定时 clone 进沙箱（git_branch 默认 main）
      - template: "blank" / "vite-vue-ts" / "next-ts" / "express" / "fastapi" / "java-spring"
        v1 只接受参数 + 记录到 meta，模板文件复制留 Phase 3.2
      - display_name: 用户面可读名（不传则用 project_name）

    返回：{ok, ws_id, preview_url_hint, container_status, template, ports}
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)

    name = (project_name or "").strip()
    if not name:
        return _business_error(
            op="vibe_create_sandbox",
            error_text="project_name 不能为空（用 kebab-case，如 'vue-todo-app'）",
            extra={"error_code": "VIBE_BAD_NAME"},
        )

    tpl = (template or "blank").strip()
    if tpl not in _TEMPLATES:
        return _business_error(
            op="vibe_create_sandbox",
            error_text=f"未知 template={tpl}；候选：{sorted(_TEMPLATES)}",
            extra={"error_code": "VIBE_BAD_TEMPLATE"},
        )

    oc = _online_coding_module()
    workspace_id = f"oc_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    ws_dir = oc._workspace_dir(workspace_id, tid, git_url or None, name)
    repo_dir = oc._repo_path(ws_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": workspace_id,
        "repo_url": git_url or None,
        "task": display_name or name,
        "project_name": name,
        "template": tpl,
        "user_id": uid,
        "tenant_id": tid,
        "status": "created",
        "sandbox_status": "starting",
        "created_at": now,
        "updated_at": now,
        "kind": "vibe_coding_mcp",
    }
    oc._write_workspace(ws_dir, meta)

    # 可选：git clone 进 repo/
    if git_url:
        try:
            oc_meta = await oc._import_repository(ws_dir, meta, git_auth=None)
            meta.update(oc_meta or {})
        except Exception as exc:
            logger.warning("vibe_create_sandbox git clone 失败 ws=%s: %s", workspace_id, exc)
            meta["import_error"] = str(exc)[:300]

    # 起容器
    runtime = get_runtime()
    container_status: Optional[str] = None
    try:
        if not await runtime.is_available():
            meta["sandbox_status"] = "runtime_unavailable"
            container_status = None
        else:
            await runtime.ensure_container(workspace_id, repo_dir, ports=_DEFAULT_PORTS)
            container_status = await runtime.container_status(workspace_id)
            meta["sandbox_status"] = "running" if container_status == "running" else "started"
    except Exception as exc:
        logger.warning("vibe_create_sandbox ensure_container 失败 ws=%s: %s", workspace_id, exc)
        meta["sandbox_status"] = "container_failed"
        meta["container_error"] = str(exc)[:300]

    meta["updated_at"] = _now_iso()
    oc._write_workspace(ws_dir, meta)

    preview_url_hint = (
        f"调 vibe_get_preview_url(ws_id={workspace_id}, container_port=<dev_port>) "
        f"拿真 URL，dev_port 用 {_DEFAULT_PORTS[0]} 起步"
    )

    return {
        "ok": True,
        "ws_id": workspace_id,
        "container_status": container_status,
        "sandbox_status": meta["sandbox_status"],
        "template": tpl,
        "ports": _DEFAULT_PORTS,
        "preview_url_hint": preview_url_hint,
        "import_error": meta.get("import_error"),
    }


@mcp.tool()
async def vibe_list_sandboxes(
    status: str = "",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """列当前用户的 Vibe Coding 沙箱（受 tenant 隔离）。

    参数：
      - status: "running" / "stopped" / ""=全部 — 客户端过滤（基于 container_status）

    返回：{ok, sandboxes: [{ws_id, project_name, container_status, ...}]}
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    oc = _online_coding_module()
    oc.ONLINE_CODING_ROOT.mkdir(parents=True, exist_ok=True)
    runtime = get_runtime()

    items: list[dict] = []
    for ws_dir in oc._iter_workspace_meta_dirs():
        try:
            meta = oc._read_workspace(ws_dir)
        except Exception:
            continue
        if int(meta.get("user_id") or 0) != uid:
            continue
        if meta.get("tenant_id") is not None and int(meta["tenant_id"]) != tid:
            continue
        ws_id = meta.get("id")
        try:
            cs = await runtime.container_status(ws_id) if ws_id else None
        except Exception:
            cs = None
        view = _public_workspace_view(meta, cs)
        if status:
            want_running = status.lower() == "running"
            is_running = cs == "running"
            if want_running != is_running:
                continue
        items.append(view)

    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"ok": True, "sandboxes": items, "count": len(items)}


@mcp.tool()
async def vibe_run_in_sandbox(
    ws_id: str,
    command: str,
    timeout: int = 30,
    background: bool = False,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """在沙箱内执行 shell 命令。

    与 dev-coding `run_workspace_command` 区别：dev-coding 是 host shell（受限），
    本工具是 podman/docker 沙箱（隔离）。

    参数：
      - command: bash 命令，会被包成 `cd /workspace && <command>` 执行
      - timeout: 秒，前台命令上限 60s（dolphin omnigate 限制）
      - background: True 表示后台跑（适合 `npm run dev` / build watcher / 长任务）

    长跑命令建议：
      - `npm install` / `pip install` / `mvn package` → background=True
      - `npm run dev` (server) → background=True 永久跑
      - `git status` / `ls` → background=False

    返回：
      - 前台：{ok, stdout, stderr, exit_code, truncated, timed_out}
      - 后台：{ok, status:"started", log_path}
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    ws_dir, meta, err = await _require_workspace(ws_id, uid, tid)
    if err:
        return err
    assert ws_dir is not None and meta is not None

    cmd = (command or "").strip()
    if not cmd:
        return _business_error(
            op="vibe_run_in_sandbox",
            error_text="command 不能为空",
            extra={"error_code": "VIBE_BAD_COMMAND"},
        )

    runtime = get_runtime()
    try:
        if not await runtime.is_available():
            return _business_error(
                op="vibe_run_in_sandbox",
                error_text="podman/docker 沙箱运行时不可用（runtime is_available=False）",
                extra={"error_code": "VIBE_RUNTIME_UNAVAILABLE"},
            )
        oc = _online_coding_module()
        repo_dir = oc._repo_path(ws_dir)
        await runtime.ensure_container(ws_id, repo_dir, ports=_DEFAULT_PORTS)
    except Exception as exc:
        return _business_error(
            op="vibe_run_in_sandbox",
            error_text=f"沙箱容器启动失败: {exc}",
            extra={"error_code": "VIBE_CONTAINER_FAILED", "ws_id": ws_id},
        )

    if background:
        # 用命令前 32 字符做 key，stable 化日志文件名
        safe_key = "".join(c if c.isalnum() else "_" for c in cmd[:32]).strip("_") or "bg"
        log_rel = f".vibe-logs/{safe_key}.log"
        try:
            await runtime.exec_background(ws_id, cmd, log_path=log_rel)
        except Exception as exc:
            return _business_error(
                op="vibe_run_in_sandbox",
                error_text=f"后台启动失败: {exc}",
                extra={"error_code": "VIBE_BG_FAILED"},
            )
        return {
            "ok": True,
            "status": "started",
            "background": True,
            "log_path": log_rel,
            "hint": f"调 vibe_get_logs(ws_id={ws_id}, container_or_command='{safe_key}') 查日志",
        }

    # 前台同步执行
    eff_timeout = max(1, min(int(timeout or 30), 60))
    try:
        result = await runtime.exec(ws_id, cmd, timeout=eff_timeout)
    except Exception as exc:
        return _business_error(
            op="vibe_run_in_sandbox",
            error_text=f"exec 异常: {exc}",
            extra={"error_code": "VIBE_EXEC_FAILED"},
        )

    out, out_trunc = _truncate(result.stdout or "", _STDOUT_LIMIT)
    err_, err_trunc = _truncate(result.stderr or "", _STDERR_LIMIT)
    return {
        "ok": result.returncode == 0,
        "stdout": out,
        "stderr": err_,
        "exit_code": result.returncode,
        "truncated": out_trunc or err_trunc,
        "timed_out": getattr(result, "timed_out", False),
    }


@mcp.tool()
async def vibe_read_sandbox_file(
    ws_id: str,
    file_path: str,
    max_bytes: int = 65536,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """读沙箱内单个文件内容（仅文本）。

    file_path 是相对沙箱 /workspace（即 repo/ 目录）的路径，禁止绝对路径 / `..` /
    访问 `.git/`。

    返回：{ok, content, size, truncated, encoding}
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    ws_dir, _meta, err = await _require_workspace(ws_id, uid, tid)
    if err:
        return err
    assert ws_dir is not None

    repo_dir = get_repo_dir(ws_id)
    if repo_dir is None:
        return _business_error(
            op="vibe_read_sandbox_file",
            error_text="沙箱 repo 目录不存在",
            extra={"error_code": "VIBE_REPO_MISSING"},
        )
    target, path_err = resolve_path(repo_dir, file_path or "")
    if path_err or target is None:
        return _business_error(
            op="vibe_read_sandbox_file",
            error_text=path_err or "路径非法",
            extra={"error_code": "VIBE_BAD_PATH"},
        )
    if not target.exists() or not target.is_file():
        return _business_error(
            op="vibe_read_sandbox_file",
            error_text=f"文件不存在或不是普通文件: {file_path}",
            extra={"error_code": "VIBE_FILE_NOT_FOUND"},
        )

    limit = max(1, min(int(max_bytes or _FILE_READ_LIMIT_DEFAULT), _FILE_READ_LIMIT_DEFAULT * 4))
    try:
        raw = target.read_bytes()
    except Exception as exc:
        return _business_error(
            op="vibe_read_sandbox_file",
            error_text=f"读文件失败: {exc}",
            extra={"error_code": "VIBE_READ_FAILED"},
        )
    size = len(raw)
    truncated = size > limit
    chunk = raw[:limit]
    try:
        content = chunk.decode("utf-8")
        enc = "utf-8"
    except UnicodeDecodeError:
        content = chunk.decode("utf-8", errors="replace")
        enc = "utf-8-replace"
    return {
        "ok": True,
        "content": content,
        "size": size,
        "truncated": truncated,
        "encoding": enc,
    }


@mcp.tool()
async def vibe_write_sandbox_files(
    ws_id: str,
    files: list[dict],
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """批量写沙箱内多个文件（覆盖现有内容）。

    files 元素：{file_path: 相对 repo/ 的路径, content: 文本内容}

    返回：{ok, files_written, files_failed:[{file_path, error}]}
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    ws_dir, _meta, err = await _require_workspace(ws_id, uid, tid)
    if err:
        return err

    if not isinstance(files, list) or not files:
        return _business_error(
            op="vibe_write_sandbox_files",
            error_text="files 必须是非空 list[dict]",
            extra={"error_code": "VIBE_BAD_FILES"},
        )

    repo_dir = get_repo_dir(ws_id)
    if repo_dir is None:
        return _business_error(
            op="vibe_write_sandbox_files",
            error_text="沙箱 repo 目录不存在",
            extra={"error_code": "VIBE_REPO_MISSING"},
        )

    written = 0
    failures: list[dict] = []
    for item in files:
        if not isinstance(item, dict):
            failures.append({"file_path": str(item)[:80], "error": "条目应是 dict"})
            continue
        fp = (item.get("file_path") or "").strip()
        content = item.get("content")
        if not fp or content is None:
            failures.append({"file_path": fp or "<empty>", "error": "缺 file_path 或 content"})
            continue
        target, path_err = resolve_path(repo_dir, fp)
        if path_err or target is None:
            failures.append({"file_path": fp, "error": path_err or "路径非法"})
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            written += 1
        except Exception as exc:
            failures.append({"file_path": fp, "error": str(exc)[:200]})

    return {
        "ok": written > 0 or not failures,
        "files_written": written,
        "files_failed": failures,
    }


@mcp.tool()
async def vibe_glob_sandbox(
    ws_id: str,
    pattern: str = "**/*",
    max_results: int = 200,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """按 glob pattern 找沙箱内文件。

    pattern 示例："**/*.vue" / "src/**/*.ts" / "package.json"

    返回：{ok, files: [...], total, truncated}
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    ws_dir, _meta, err = await _require_workspace(ws_id, uid, tid)
    if err:
        return err

    repo_dir = get_repo_dir(ws_id)
    if repo_dir is None:
        return _business_error(
            op="vibe_glob_sandbox",
            error_text="沙箱 repo 目录不存在",
            extra={"error_code": "VIBE_REPO_MISSING"},
        )

    pat = (pattern or "**/*").strip()
    limit = max(1, min(int(max_results or _GLOB_MAX_DEFAULT), 2000))

    matched: list[str] = []
    try:
        for path in repo_dir.glob(pat):
            if not path.is_file():
                continue
            # 跳过常见噪音目录
            rel = path.relative_to(repo_dir)
            parts = rel.parts
            if any(p in {".git", "node_modules", "dist", "build", ".next", ".nuxt"} for p in parts):
                continue
            matched.append(str(rel))
            if len(matched) >= limit + 1:  # +1 检测是否截断
                break
    except Exception as exc:
        return _business_error(
            op="vibe_glob_sandbox",
            error_text=f"glob 失败: {exc}",
            extra={"error_code": "VIBE_GLOB_FAILED"},
        )

    truncated = len(matched) > limit
    return {
        "ok": True,
        "files": matched[:limit],
        "total": len(matched[:limit]),
        "truncated": truncated,
    }


_PREVIEW_DOMAIN = "vibe-first.cn"  # ECS nginx vibe-preview.conf 配的通配子域
_PREVIEW_PORT_MIN = 30000           # podman/docker 自动分配段（nginx 正则强制）
_PREVIEW_PORT_MAX = 65999


@mcp.tool()
async def vibe_get_preview_url(
    ws_id: str,
    container_port: int = 6173,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """拿沙箱预览 URL（基于 podman/docker 端口映射 + vibe-first.cn 子域反代）。

    container_port 默认 6173（vite 端口在沙箱标准映射段 6100-6999）。
    其它候选端口：6300（next/express）/ 6400 (fastapi 转 8000) / 6500 (java)。

    返回：{ok, preview_url, host_port, container_port, all_ports}
      - preview_url 是公网可访问的 https URL，格式 `https://p<host_port>.vibe-first.cn`
        前提：ECS nginx 已配好 `/etc/nginx/conf.d/vibe-preview.conf` 通配反代
        + DNS *.vibe-first.cn 通配解析到 ECS
        + SSL 通配证书 *.vibe-first.cn
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    ws_dir, _meta, err = await _require_workspace(ws_id, uid, tid)
    if err:
        return err

    runtime = get_runtime()
    try:
        host_port = await runtime.host_port(ws_id, int(container_port))
        all_ports = await runtime.all_host_ports(ws_id)
        try:
            listening = await runtime.listening_ports(ws_id)
        except Exception:
            listening = set()
    except Exception as exc:
        return _business_error(
            op="vibe_get_preview_url",
            error_text=f"查端口失败: {exc}",
            extra={"error_code": "VIBE_PORT_FAILED"},
        )

    if not host_port:
        return _business_error(
            op="vibe_get_preview_url",
            error_text=(
                f"沙箱 ws={ws_id} 未映射 container_port={container_port}。"
                f"现有映射: {all_ports}；候选端口段 6100-6999"
            ),
            extra={"error_code": "VIBE_PORT_NOT_MAPPED", "all_ports": all_ports},
        )

    # 公网预览 URL：走 nginx 通配子域反代到 host_port
    # nginx vibe-preview.conf 限制 host_port ∈ [30000, 65999]，落区间外就只能给内网链接
    if _PREVIEW_PORT_MIN <= host_port <= _PREVIEW_PORT_MAX:
        preview_url = f"https://p{host_port}.{_PREVIEW_DOMAIN}"
        hint = "公网 https 直连，浏览器打开即可看 dev server"
    else:
        preview_url = f"http://127.0.0.1:{host_port}"
        hint = (
            f"host_port={host_port} 不在 vibe-first.cn 反代区间 "
            f"[{_PREVIEW_PORT_MIN}, {_PREVIEW_PORT_MAX}]，仅返内网 URL；"
            f"用户在 ECS 同网或加 ssh tunnel 才可访问"
        )

    return {
        "ok": True,
        "preview_url": preview_url,
        "host_port": host_port,
        "container_port": int(container_port),
        "is_listening": int(container_port) in listening,
        "all_ports": all_ports,
        "hint": hint,
    }


@mcp.tool()
async def vibe_destroy_sandbox(
    ws_id: str,
    keep_source: bool = True,
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """销毁沙箱（停 + 删 podman/docker container）。

    参数：
      - keep_source: True（默认）保留 workspace 源码目录给将来重新 vibe_create_sandbox 重启用；
                     False 同时删源码目录。

    返回：{ok, ws_id, freed_disk_mb}
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    ws_dir, meta, err = await _require_workspace(ws_id, uid, tid)
    if err:
        return err
    assert ws_dir is not None and meta is not None

    runtime = get_runtime()
    try:
        await runtime.stop(ws_id, timeout=5)
    except Exception as exc:
        logger.warning("vibe_destroy stop 失败 ws=%s: %s", ws_id, exc)
    try:
        await runtime.remove(ws_id, force=True)
    except Exception as exc:
        logger.warning("vibe_destroy remove 失败 ws=%s: %s", ws_id, exc)

    freed_mb = 0
    if not keep_source:
        try:
            import shutil
            # 估磁盘
            total = 0
            for p in ws_dir.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
            freed_mb = int(total / (1024 * 1024))
            shutil.rmtree(ws_dir, ignore_errors=True)
        except Exception as exc:
            logger.warning("vibe_destroy rmtree 失败 ws=%s: %s", ws_id, exc)
    else:
        # 只更新 meta 标记 destroyed
        meta["sandbox_status"] = "destroyed"
        meta["updated_at"] = _now_iso()
        oc = _online_coding_module()
        oc._write_workspace(ws_dir, meta)

    return {
        "ok": True,
        "ws_id": ws_id,
        "keep_source": keep_source,
        "freed_disk_mb": freed_mb,
    }


@mcp.tool()
async def vibe_get_logs(
    ws_id: str,
    tail: int = 200,
    container_or_command: str = "container",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """拉沙箱日志（容器日志或后台命令日志）。

    container_or_command:
      - "container" → 拉容器 `docker logs --tail N`（容器 PID 1 是 tail -f /dev/null，
        实际几乎无内容；主要看启动错误）
      - "<command_key>" → 拉后台命令日志文件 `.vibe-logs/<key>.log`
        key = vibe_run_in_sandbox(background=True) 返回的 log_path 文件名（无扩展名）

    返回：{ok, logs, source, tail, truncated}
    """
    tid, uid = await _resolve_identity(tenant_id or None, user_id or None)
    ws_dir, _meta, err = await _require_workspace(ws_id, uid, tid)
    if err:
        return err

    runtime = get_runtime()
    n = max(1, min(int(tail or 200), 5000))
    key = (container_or_command or "container").strip()

    if key == "container":
        try:
            # docker logs 直接走 CLI，需要 _run（私有），改用 exec 跑 tail /dev/null 也无用，
            # 用 runtime._run 间接调（DockerRuntime 没暴露 logs 方法，临时用 _run 内部 API）
            ok, out, err_ = await runtime._run(
                ["docker", "logs", "--tail", str(n), runtime.container_name(ws_id)],
                timeout=10,
            )
        except Exception as exc:
            return _business_error(
                op="vibe_get_logs",
                error_text=f"docker logs 失败: {exc}",
                extra={"error_code": "VIBE_LOGS_FAILED"},
            )
        body = (out or "") + ("\n--- stderr ---\n" + err_ if err_ else "")
        truncated_text, was_trunc = _truncate(body, _STDOUT_LIMIT * 2)
        return {
            "ok": ok,
            "logs": truncated_text,
            "source": "docker_logs",
            "tail": n,
            "truncated": was_trunc,
        }

    # 后台命令日志文件
    log_rel = f".vibe-logs/{key}.log"
    try:
        result = await runtime.exec(ws_id, f"tail -n {n} {log_rel} 2>/dev/null || echo '[log not found]'", timeout=10)
    except Exception as exc:
        return _business_error(
            op="vibe_get_logs",
            error_text=f"读后台命令日志失败: {exc}",
            extra={"error_code": "VIBE_LOGS_FAILED"},
        )
    body = result.stdout or ""
    truncated_text, was_trunc = _truncate(body, _STDOUT_LIMIT * 2)
    return {
        "ok": result.returncode == 0,
        "logs": truncated_text,
        "source": f"file:{log_rel}",
        "tail": n,
        "truncated": was_trunc,
    }


# 2026-05-31 本地镜像：vibe_* 已通过上方 @mcp.tool 挂到统一主 MCP；
# 这里额外挂到 mcp_vibe，仅用于旧 split endpoint 兼容。
for _fn in [
    vibe_create_sandbox, vibe_list_sandboxes, vibe_run_in_sandbox,
    vibe_read_sandbox_file, vibe_write_sandbox_files, vibe_glob_sandbox,
    vibe_get_preview_url, vibe_destroy_sandbox, vibe_get_logs,
]:
    mcp_vibe.tool()(_fn)
