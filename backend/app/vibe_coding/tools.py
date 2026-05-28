"""Vibe Coding agent 工具集。

9 个工具：
  read_file / write_file / edit_file / glob / grep
  run_command / todo_write / http_check / ask_clarifying_question

设计原则：
- 每个工具失败只返回字符串，不抛 HTTPException（这是 agent 层不是 route 层）
- 长输出统一截断，给 LLM 留 token
- 路径都是相对于 workspace 根（repo_dir）的相对路径
- v1 阶段 run_command 跑 host subprocess；Step 2 替换为 docker exec
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import shlex
import time
from pathlib import Path
from shlex import quote as shlex_quote
from typing import Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import VibeCodingThread
from app.vibe_coding.docker_runtime import get_runtime as get_docker_runtime
from app.vibe_coding.k8s_runtime import PRIMARY_PREVIEW_PORT
from app.vibe_coding.workspace import find_workspace, get_repo_dir, resolve_path

logger = logging.getLogger(__name__)


def _record_background_command(workspace_id: str, command: str, log_rel: str) -> None:
    """记录 agent 后台启动的命令到 workspace meta。

    用途：沙箱监控页"启动"按钮重启 sandbox 时，从这里读出命令逐条 docker exec 重跑，
    自动恢复 dev server 等常驻服务。

    去重逻辑：同一条 command 已存在则**移到末尾**（避免列表无限膨胀），用 list 保序。
    """
    from app.routes.online_coding import _find_workspace_dir, _write_workspace

    try:
        ws_dir, meta = _find_workspace_dir(workspace_id)
    except Exception:
        return
    bg = meta.get("bg_commands") or []
    # 去重：同 command 已有则删旧
    bg = [b for b in bg if b.get("command") != command]
    bg.append({
        "command": command,
        "log_path": log_rel,
        "started_at": time.time(),
    })
    # 上限 16 条防膨胀
    if len(bg) > 16:
        bg = bg[-16:]
    meta["bg_commands"] = bg
    _write_workspace(ws_dir, meta)


# 进程内缓存：本会话期间检测到的 runtime（'docker' / 'host'），避免每次工具调用都探测 docker daemon
_runtime_cache: dict[str, str] = {}


async def _resolve_runtime(workspace_id: str) -> str:
    """根据 settings.vibe_coding_runtime 选择 k8s / docker / host。
    auto 模式下检测一次就缓存，避免每次都跨 API 探测。

    优先级（2026-05-15 重排）：
    - 显式 "k8s" / "docker" / "host" — 强制用对应 runtime
    - "auto" — 优先 k8s（in-cluster 环境）→ docker（本机有 daemon）→ host（兜底）
    """
    mode = (settings.vibe_coding_runtime or "auto").lower()
    if mode == "host":
        return "host"
    if mode == "docker":
        return "docker"
    if mode == "k8s":
        return "k8s"
    # auto
    cached = _runtime_cache.get(workspace_id)
    if cached:
        return cached
    # 优先 K8s（k8s_runtime 自身没装 kubernetes-asyncio 时 is_available 会优雅返 False）
    try:
        from app.vibe_coding.k8s_runtime import get_k8s_runtime
        k8s_rt = get_k8s_runtime()
        if await k8s_rt.is_available():
            _runtime_cache[workspace_id] = "k8s"
            return "k8s"
    except ImportError:
        # kubernetes-asyncio 没装 — 继续 fallback
        pass
    except Exception as e:
        logger.debug("k8s runtime probe failed (fallback): %s", e)
    rt = get_docker_runtime()
    if await rt.is_available():
        _runtime_cache[workspace_id] = "docker"
        return "docker"
    _runtime_cache[workspace_id] = "host"
    return "host"


# ─────────────────────────── Tool schemas (OpenAI 格式) ───────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "读取 workspace 内某个文件的文本内容。"
                "支持指定行范围（offset/limit），用于分段读大文件。"
                "禁止读 .git 内部、禁止越界。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 内的相对路径"},
                    "offset": {"type": "integer", "description": "起始行（1-based），默认 1"},
                    "limit": {"type": "integer", "description": "读取行数上限，默认 2000"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "把一段文本完整写入 workspace 内的文件（覆盖式）。"
                "目录不存在会自动创建。已有文件会被完整覆盖——只改一小段时优先用 edit_file。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "workspace 内相对路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "在已存在的文件中做精确字符串替换。"
                "old_string 必须在文件中唯一出现，否则报错（除非 replace_all=true）。"
                "比 write_file 更安全——不会误覆盖未读到的部分。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string", "description": "被替换内容（必须精确匹配）"},
                    "new_string": {"type": "string", "description": "替换为的新内容"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "若为 true，替换所有出现，且不要求唯一",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": (
                "用 glob pattern 在 workspace 内匹配文件路径列表。"
                "示例 pattern：'**/*.ts'、'src/**/*.vue'、'*.json'。"
                "结果按修改时间倒序，最多 200 条。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "在 workspace 内搜索文本/正则。返回命中文件的行列表。"
                "支持限定 path 子目录、glob 过滤文件类型、忽略大小写。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "正则表达式（Python re 语法）"},
                    "path": {"type": "string", "description": "限定子目录（可选）"},
                    "glob": {"type": "string", "description": "glob 过滤文件名，如 '*.py'（可选）"},
                    "ignore_case": {"type": "boolean"},
                    "max_results": {"type": "integer", "description": "命中行上限，默认 80"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "在 workspace 根目录执行 shell 命令。"
                "默认前台同步执行（最多等 timeout 秒，超时杀掉）。"
                "对于 dev server / watch 这种长任务，传 run_in_background=true，"
                "立即返回 pid 并把输出落到日志文件，可以稍后用 tail 命令查看。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "完整命令行（用 sh -c 执行）"},
                    "timeout": {"type": "integer", "description": "前台超时秒数，默认 120"},
                    "run_in_background": {"type": "boolean"},
                    "description": {
                        "type": "string",
                        "description": "5-10 字简述，给用户看",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": (
                "维护当前会话的 TODO 清单——拆解复杂任务，跟踪进度。"
                "每次调用都会**完整覆盖**当前清单（不是增量）。"
                "状态：pending / in_progress / completed。"
                "请保持同时只有一个 in_progress；做完就立刻置 completed。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["id", "content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "requirement_write",
            "description": (
                "维护当前应用的「需求基线」——把用户需求结构化记录，实时显示在用户的「需求」tab。"
                "每次调用都会**完整覆盖**当前基线（不是增量）。"
                "澄清完关键点后调用一次；之后需求有变（用户改、范围调整）就再调更新。"
                "所有字段都是字符串数组，可空；简单应用 external/ai_points 可留空。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "roles":      {"type": "array", "items": {"type": "string"}, "description": "使用角色，如 '管理员 — 管理用户与权限'"},
                    "features":   {"type": "array", "items": {"type": "string"}, "description": "功能点列表"},
                    "flows":      {"type": "array", "items": {"type": "string"}, "description": "关键业务流程，如 '员工提交 → 主管审批 → 财务打款'"},
                    "external":   {"type": "array", "items": {"type": "string"}, "description": "外部交互/集成（第三方 API 等），无则空"},
                    "ai_points":  {"type": "array", "items": {"type": "string"}, "description": "需要 AI 能力的决策点，无则空"},
                    "acceptance": {"type": "array", "items": {"type": "string"}, "description": "验收标准"},
                },
                "required": ["roles", "features", "flows", "acceptance"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_check",
            "description": (
                "HTTP GET 一个 URL，验证服务起没起来。"
                "返回状态码 + 响应前 1000 字符。"
                "典型用法：跑 dev server 之后 http_check http://localhost:5173 看 200。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 10"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_clarifying_question",
            "description": (
                "向用户提一个澄清问题，可附候选答案。"
                "调用后 agent loop 会暂停，等用户回复才继续。"
                "重要假设/技术栈选型/需求边界要拍板时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "候选答案（推荐 2-4 项）",
                    },
                },
                "required": ["question"],
            },
        },
    },
]


# ─────────────────────────── 实现 ───────────────────────────

# 长结果统一截断尺寸
_MAX_RESULT_CHARS = 8000
_MAX_FILE_READ_CHARS = 40000


def _truncate(text: str, limit: int = _MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[输出已截断，原长度 {len(text)} 字符]"


def _err(msg: str) -> str:
    return f"错误：{msg}"


async def _ensure_repo(thread: VibeCodingThread) -> tuple[Optional[Path], Optional[str]]:
    repo = get_repo_dir(thread.workspace_id)
    if not repo:
        return None, _err("workspace 不存在或未初始化")
    return repo, None


async def execute_read_file(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    repo, e = await _ensure_repo(thread)
    if e:
        return e
    path, perr = resolve_path(repo, args.get("path", ""))
    if perr:
        return _err(perr)
    if not path.exists():
        return _err(f"文件不存在: {args.get('path')}")
    if not path.is_file():
        return _err("路径不是文件")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return _err(f"读取失败: {exc}")
    offset = max(int(args.get("offset") or 1), 1)
    limit = max(int(args.get("limit") or 2000), 1)
    lines = text.splitlines()
    sliced = lines[offset - 1 : offset - 1 + limit]
    out = "\n".join(f"{offset + i:6d}\t{line}" for i, line in enumerate(sliced))
    if offset == 1 and limit >= len(lines):
        meta = f"[读取 {len(lines)} 行 / 共 {len(lines)} 行]"
    else:
        meta = f"[读取 {offset}-{offset + len(sliced) - 1} 行 / 共 {len(lines)} 行]"
    full = f"{meta}\n{out}"
    return _truncate(full, _MAX_FILE_READ_CHARS)


async def execute_write_file(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    repo, e = await _ensure_repo(thread)
    if e:
        return e
    path, perr = resolve_path(repo, args.get("path", ""))
    if perr:
        return _err(perr)
    content = args.get("content")
    if content is None:
        return _err("缺少 content")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception as exc:
        return _err(f"写入失败: {exc}")
    return f"已写入 {args.get('path')}（{len(content)} 字符）"


async def execute_edit_file(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    repo, e = await _ensure_repo(thread)
    if e:
        return e
    path, perr = resolve_path(repo, args.get("path", ""))
    if perr:
        return _err(perr)
    if not path.exists():
        return _err(f"文件不存在: {args.get('path')}")
    old = args.get("old_string")
    new = args.get("new_string")
    replace_all = bool(args.get("replace_all"))
    if old is None or new is None:
        return _err("缺少 old_string 或 new_string")
    if old == new:
        return _err("old_string 与 new_string 相同")

    text = path.read_text(encoding="utf-8", errors="replace")
    if replace_all:
        if old not in text:
            return _err("old_string 在文件中未找到")
        new_text = text.replace(old, new)
        count = text.count(old)
    else:
        count = text.count(old)
        if count == 0:
            return _err("old_string 在文件中未找到")
        if count > 1:
            return _err(
                f"old_string 在文件中出现 {count} 次，不唯一。"
                "扩大 old_string 范围让它唯一，或用 replace_all=true。"
            )
        new_text = text.replace(old, new, 1)
    try:
        path.write_text(new_text, encoding="utf-8")
    except Exception as exc:
        return _err(f"写入失败: {exc}")
    return f"已编辑 {args.get('path')}（替换 {count} 处）"


async def execute_glob(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    repo, e = await _ensure_repo(thread)
    if e:
        return e
    pattern = args.get("pattern", "")
    if not pattern:
        return _err("缺少 pattern")
    matches: list[tuple[Path, float]] = []
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(repo).as_posix()
        # skip noisy dirs
        if any(part in {".git", "node_modules", "dist", "build", ".venv", "__pycache__"} for part in rel.split("/")):
            continue
        if fnmatch.fnmatch(rel, pattern):
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0
            matches.append((p, mtime))
    matches.sort(key=lambda item: item[1], reverse=True)
    matches = matches[:200]
    if not matches:
        return f"无匹配 (pattern={pattern})"
    return "\n".join(p.relative_to(repo).as_posix() for p, _ in matches)


async def execute_grep(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    repo, e = await _ensure_repo(thread)
    if e:
        return e
    raw_pattern = args.get("pattern", "")
    if not raw_pattern:
        return _err("缺少 pattern")
    flags = re.IGNORECASE if args.get("ignore_case") else 0
    try:
        regex = re.compile(raw_pattern, flags)
    except re.error as exc:
        return _err(f"正则错误: {exc}")

    sub = args.get("path") or ""
    base = repo
    if sub:
        sub_path, perr = resolve_path(repo, sub)
        if perr:
            return _err(perr)
        if not sub_path.exists() or not sub_path.is_dir():
            return _err("path 子目录不存在")
        base = sub_path

    glob_filter = args.get("glob")
    max_results = int(args.get("max_results") or 80)

    results: list[str] = []
    skip_dirs = {".git", "node_modules", "dist", "build", ".venv", "__pycache__", ".next"}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if glob_filter and not fnmatch.fnmatch(fname, glob_filter):
                continue
            fpath = Path(root) / fname
            try:
                with fpath.open("r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if regex.search(line):
                            rel = fpath.relative_to(repo).as_posix()
                            results.append(f"{rel}:{lineno}: {line.rstrip()}")
                            if len(results) >= max_results:
                                results.append(f"[已达上限 {max_results} 条]")
                                return _truncate("\n".join(results))
            except (OSError, UnicodeDecodeError):
                continue
    if not results:
        return f"无命中 (pattern={raw_pattern})"
    return _truncate("\n".join(results))


# 后台进程注册：{key: {"pid": int, "log_path": str, "command": str, "started_at": float}}
# v1 用进程内字典，简单够用——单 worker 部署。Step 2 docker 化时换成 docker ps 查询。
_BACKGROUND_PROCS: dict[str, dict] = {}


def _bg_key(workspace_id: str, command: str) -> str:
    return f"{workspace_id}:{hash(command) & 0xFFFFFFFF:x}"


async def execute_run_command(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    repo, e = await _ensure_repo(thread)
    if e:
        return e
    cmd = (args.get("command") or "").strip()
    if not cmd:
        return _err("缺少 command")
    timeout = int(args.get("timeout") or 120)
    background = bool(args.get("run_in_background"))

    runtime = await _resolve_runtime(thread.workspace_id)
    if runtime == "docker":
        return await _run_command_docker(thread, repo, cmd, timeout=timeout, background=background)
    if runtime == "k8s":
        # 2026-05-18: exec 前主动 probe Pod 是否真 Running — 修 evicted pod 假装 exit 0
        # 的 bug。节点 MemoryPressure 时 Pod 被 SIGKILL 后 phase=Failed，但 K8s
        # exec websocket 仍可能"连接成功立即 EOF"，agent 当成命令跑通造 hallucinate。
        from app.vibe_coding.k8s_runtime import get_k8s_runtime
        rt = get_k8s_runtime()
        try:
            status = await rt.container_status(thread.workspace_id)
        except Exception:
            status = None
        if status != "running" and status is not None:
            # exited / failed / evicted — 让 ensure_container 走删+重建逻辑后再判一次
            try:
                await rt.ensure_container(thread.workspace_id, repo, tenant_id=thread.tenant_id or 1)
            except Exception as exc:
                return _err(f"K8s 沙箱 Pod 异常无法重建（节点可能内存压力）: {exc}")
            status = await rt.container_status(thread.workspace_id)
            if status != "running":
                return _err(
                    f"K8s 沙箱 Pod 未进入 Running（当前状态: {status or 'NotFound'}）。"
                    f"常见原因：节点内存压力 (kubectl describe node 看 MemoryPressure)。"
                    f"沙箱重建失败前不要假装命令跑过了。"
                )
        return await _run_command_k8s(thread, repo, cmd, timeout=timeout, background=background)
    return await _run_command_host(thread, repo, cmd, timeout=timeout, background=background)


async def _run_command_docker(
    thread: VibeCodingThread, repo: Path, cmd: str, *, timeout: int, background: bool
) -> str:
    """通过 docker exec 在 vibe-sandbox 容器内执行。"""
    rt = get_docker_runtime()
    try:
        await rt.ensure_container(thread.workspace_id, repo)
    except RuntimeError as exc:
        return _err(f"docker 容器启动失败: {exc}")

    if background:
        # 容器内 .vibe-logs 跟 host 同一挂载点，host 端可以直接 tail
        ts = int(time.time())
        log_rel = f".vibe-logs/dev-{ts}.log"
        try:
            await rt.exec_background(thread.workspace_id, cmd, log_path=log_rel)
        except RuntimeError as exc:
            return _err(f"容器内后台启动失败: {exc}")
        # 记到 workspace meta — 沙箱监控页面"启动"按钮重启 sandbox 时自动恢复这些后台服务
        try:
            _record_background_command(thread.workspace_id, cmd, log_rel)
        except Exception as e:
            logger.warning("记录后台命令失败 (workspace=%s): %s", thread.workspace_id, e)
        return (
            f"已在容器内 detach 后台启动，日志: {log_rel}\n"
            f"等 3-5 秒后用 run_command 'sleep 4 && tail -n 50 {log_rel}' 看启动是否成功。\n"
            f"再用 http_check 验证服务真起来了。"
        )

    result = await rt.exec(thread.workspace_id, cmd, timeout=timeout)
    if result.timed_out:
        return _err(f"执行超时（{timeout} 秒）")

    parts: list[str] = []
    if result.stdout:
        parts.append(f"[stdout]\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr.rstrip()}")
    parts.append(f"[exit code: {result.returncode}]")
    return _truncate("\n\n".join(parts))


async def _run_command_k8s(
    thread: VibeCodingThread, repo: Path, cmd: str, *, timeout: int, background: bool
) -> str:
    """通过 K8s exec API 在 vibe-sandbox-{ws_id} Pod 内执行。

    跟 _run_command_docker 同结构，差异：
    - 用 KubernetesRuntime 而非 DockerRuntime
    - ensure_container 多接 tenant_id 让 PVC subPath 隔离
    - host_workspace_dir 参数对 K8s 无意义（subPath 由 ws_id 决定），但保留对齐签名
    """
    from app.vibe_coding.k8s_runtime import get_k8s_runtime
    rt = get_k8s_runtime()
    try:
        await rt.ensure_container(
            thread.workspace_id,
            repo,
            tenant_id=thread.tenant_id or 1,
        )
    except Exception as exc:
        return _err(f"K8s 沙箱启动失败: {exc}")

    if background:
        ts = int(time.time())
        log_rel = f".vibe-logs/dev-{ts}.log"
        try:
            await rt.exec_background(thread.workspace_id, cmd.split() if isinstance(cmd, str) else cmd, log_path=log_rel, cwd="/workspace")
        except Exception as exc:
            return _err(f"K8s 沙箱内后台启动失败: {exc}")
        try:
            _record_background_command(thread.workspace_id, cmd, log_rel)
        except Exception as e:
            logger.warning("记录后台命令失败 (workspace=%s): %s", thread.workspace_id, e)
        public_url = f"http://{rt.ingress_host(thread.workspace_id)}"
        return (
            f"已在 K8s 沙箱内 detach 后台启动，日志: {log_rel}\n"
            f"等 3-5 秒后用 run_command 'sleep 4 && tail -n 50 {log_rel}' 看启动是否成功。\n"
            f"再用 http_check http://localhost:{PRIMARY_PREVIEW_PORT} 验证服务起在 pod 内。\n"
            f"用户浏览器入口: {public_url} (vibe-first.cn 通配 → ingress 路由到 pod {PRIMARY_PREVIEW_PORT} 端口)"
        )

    # 前台 exec — K8s exec 命令是 list[str]，shell 命令包成 sh -c
    cmd_list = ["sh", "-c", cmd] if isinstance(cmd, str) else list(cmd)
    result = await rt.exec(thread.workspace_id, cmd_list, timeout=timeout, cwd="/workspace")
    if result.timed_out:
        return _err(f"执行超时（{timeout} 秒）")

    parts: list[str] = []
    if result.stdout:
        parts.append(f"[stdout]\n{result.stdout.rstrip()}")
    if result.stderr:
        parts.append(f"[stderr]\n{result.stderr.rstrip()}")
    parts.append(f"[exit code: {result.returncode}]")
    return _truncate("\n\n".join(parts))


async def _run_command_host(
    thread: VibeCodingThread, repo: Path, cmd: str, *, timeout: int, background: bool
) -> str:
    """host shell 兜底（dev 环境 / docker 不可用）。"""
    if background:
        log_dir = repo / ".vibe-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        key = _bg_key(thread.workspace_id, f"{cmd}@{time.time()}")
        log_path = log_dir / f"{key}.log"
        try:
            log_fh = open(log_path, "ab")
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(repo),
                stdout=log_fh,
                stderr=log_fh,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0"},
            )
        except Exception as exc:
            return _err(f"启动失败: {exc}")
        _BACKGROUND_PROCS[key] = {
            "pid": proc.pid,
            "log_path": str(log_path),
            "command": cmd,
            "started_at": time.time(),
        }
        return (
            f"已在后台启动（pid={proc.pid}），日志: .vibe-logs/{key}.log\n"
            f"等几秒后用 run_command 'tail -n 50 .vibe-logs/{key}.log' 看输出。"
        )

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(repo),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "FORCE_COLOR": "0"},
        )
    except Exception as exc:
        return _err(f"启动失败: {exc}")
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return _err(f"执行超时（{timeout} 秒）")

    out = stdout.decode("utf-8", errors="replace")
    err_s = stderr.decode("utf-8", errors="replace")
    parts: list[str] = []
    if out:
        parts.append(f"[stdout]\n{out.rstrip()}")
    if err_s:
        parts.append(f"[stderr]\n{err_s.rstrip()}")
    parts.append(f"[exit code: {proc.returncode}]")
    return _truncate("\n\n".join(parts))


async def execute_todo_write(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    todos = args.get("todos")
    if not isinstance(todos, list):
        return _err("todos 必须是数组")
    # 标准化 + 校验
    cleaned: list[dict] = []
    for item in todos:
        if not isinstance(item, dict):
            return _err("每条 todo 必须是 object")
        tid = str(item.get("id") or "").strip()
        content = str(item.get("content") or "").strip()
        status = str(item.get("status") or "pending").strip()
        if not tid or not content:
            return _err("每条 todo 需要 id 和 content")
        if status not in {"pending", "in_progress", "completed"}:
            status = "pending"
        cleaned.append({"id": tid, "content": content, "status": status})

    thread.todos = cleaned
    await db.commit()
    summary = ", ".join(
        f"{t['id']}({t['status']})" for t in cleaned
    )
    return f"TODO 已更新（{len(cleaned)} 条）: {summary}"


_REQ_FIELDS = ["roles", "features", "flows", "external", "ai_points", "acceptance"]


async def execute_requirement_write(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    cleaned: dict[str, list[str]] = {}
    for key in _REQ_FIELDS:
        val = args.get(key)
        if val is None:
            cleaned[key] = []
            continue
        if not isinstance(val, list):
            return _err(f"{key} 必须是字符串数组")
        cleaned[key] = [str(x).strip() for x in val if str(x).strip()]
    thread.requirement_baseline = cleaned
    await db.commit()
    counts = ", ".join(f"{k}:{len(cleaned[k])}" for k in _REQ_FIELDS if cleaned[k])
    return f"需求基线已更新（{counts or '空'}）"


async def execute_http_check(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    url = (args.get("url") or "").strip()
    if not url:
        return _err("缺少 url")
    timeout = int(args.get("timeout") or 10)

    # docker / k8s runtime 下：URL 里 localhost / 127.0.0.1 都是容器视角，host 端 backend 直接 curl
    # 是访问不到容器内 dev server 的（容器内的 6173 host 端是 5xxxx 动态映射）。
    # 走 `exec curl` 在容器内自检最准。
    runtime = await _resolve_runtime(thread.workspace_id)
    if runtime == "docker":
        rt = get_docker_runtime()
        repo, e = await _ensure_repo(thread)
        if e:
            return e
        try:
            await rt.ensure_container(thread.workspace_id, repo)
        except RuntimeError as exc:
            return _err(f"docker 容器启动失败: {exc}")
        cmd = (
            f"curl -sS -o /tmp/.http_body --max-time {timeout} "
            f"-w 'STATUS:%{{http_code}}\\n' "
            f"{shlex_quote(url)} "
            f"&& head -c 1000 /tmp/.http_body"
        )
        result = await rt.exec(thread.workspace_id, cmd, timeout=timeout + 5)
        if result.returncode != 0 and not result.stdout:
            return _err(f"请求失败: {result.stderr.strip() or result.stdout.strip() or 'unknown'}")
        # 把 stdout 里的 STATUS:xxx 提取出来作为状态码
        status_code = "?"
        body_lines: list[str] = []
        for line in result.stdout.splitlines():
            if line.startswith("STATUS:"):
                status_code = line[len("STATUS:") :].strip() or "?"
            else:
                body_lines.append(line)
        body = "\n".join(body_lines)[:1000]
        return f"[status {status_code}] {url}\n{body}"

    if runtime == "k8s":
        # 2026-05-18: K8s 分支 — 之前没写这条 fall through 到 host 分支直接 httpx.get(localhost:6173)
        # 等于在 ming pod 上访问自己的 6173 → 永远 connection refused → agent hallucinate
        # "dev server 没起来"。改成在 sandbox pod 内 exec curl，跟 docker 分支同结构。
        from app.vibe_coding.k8s_runtime import get_k8s_runtime
        rt = get_k8s_runtime()
        # pod 状态先 probe — 死 pod 直接报错让 agent 别 hallucinate
        try:
            status = await rt.container_status(thread.workspace_id)
        except Exception:
            status = None
        if status != "running":
            return _err(
                f"K8s 沙箱 Pod 未 Running（当前: {status or 'NotFound'}），无法 http_check。"
                f"先 run_command 重新启动 sandbox 或等 ensure_container 完成。"
            )
        cmd_str = (
            f"curl -sS -o /tmp/.http_body --max-time {timeout} "
            f"-w 'STATUS:%{{http_code}}\\n' "
            f"{shlex_quote(url)} "
            f"&& head -c 1000 /tmp/.http_body"
        )
        result = await rt.exec(thread.workspace_id, ["sh", "-c", cmd_str], timeout=timeout + 5)
        if result.returncode != 0 and not result.stdout:
            return _err(f"请求失败: {result.stderr.strip() or 'unknown'}")
        status_code = "?"
        body_lines: list[str] = []
        for line in result.stdout.splitlines():
            if line.startswith("STATUS:"):
                status_code = line[len("STATUS:") :].strip() or "?"
            else:
                body_lines.append(line)
        body = "\n".join(body_lines)[:1000]
        # 顺带告诉 agent 公网入口 URL，让对话里给用户提的是 vibe-first.cn 不是 localhost
        public_url = f"http://{rt.ingress_host(thread.workspace_id)}"
        return (
            f"[status {status_code}] {url} (pod 内)\n{body}\n"
            f"[公网入口] 用户在浏览器打开 {public_url} 验证（{PRIMARY_PREVIEW_PORT} 端口已通过 ingress 暴露）"
        )

    # host 模式：原行为
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.RequestError as exc:
        return _err(f"请求失败: {exc}")
    body = resp.text[:1000]
    return f"[status {resp.status_code}] {url}\n{body}"


async def execute_ask_clarifying_question(args: dict, thread: VibeCodingThread, db: AsyncSession) -> str:
    """伪 result——agent loop 检测到这条 tool result 后会暂停 loop。"""
    return json.dumps(
        {
            "_special": "ask_user",
            "question": args.get("question", ""),
            "options": args.get("options") or [],
        },
        ensure_ascii=False,
    )


# ─────────────────────────── Dispatcher ───────────────────────────

TOOL_HANDLERS = {
    "read_file": execute_read_file,
    "write_file": execute_write_file,
    "edit_file": execute_edit_file,
    "glob": execute_glob,
    "grep": execute_grep,
    "run_command": execute_run_command,
    "todo_write": execute_todo_write,
    "requirement_write": execute_requirement_write,
    "http_check": execute_http_check,
    "ask_clarifying_question": execute_ask_clarifying_question,
}


async def execute_tool(
    tool_name: str, args: dict, thread: VibeCodingThread, db: AsyncSession
) -> str:
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return _err(f"未知工具 '{tool_name}'")
    try:
        return await handler(args, thread, db)
    except Exception as exc:
        logger.exception("vibe_coding tool %s failed", tool_name)
        return _err(f"工具 '{tool_name}' 执行异常: {exc}")
