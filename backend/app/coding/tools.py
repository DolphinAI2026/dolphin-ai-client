"""
Tool definitions and executors for the VibeCodingAgent.

Provides 6 tools in OpenAI function-calling format:
  read_file, write_file, edit_file, run_command, glob_files, grep_search

All file operations are sandboxed to the workspace directory.
"""

import asyncio
import glob as glob_mod
import inspect
import os
import re
import shlex
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.coding.form_component_editor import (
    normalize_form_component_editor_artifacts,
    normalize_form_component_generated_file,
    validate_form_component_editor_workspace,
)
from app.coding.runtime_env import ensure_node_tool_env, resolve_executable

FALLBACK_NPM_REGISTRY = "https://registry.npmmirror.com"
DEFAULT_NPM_CACHE_DIR = os.environ.get(
    "APAAS_NPM_CACHE_DIR",
    str(Path.home() / ".apaas-builder" / "npm-cache"),
)
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function calling format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Returns the file text. The file_path is relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file (relative to workspace root)",
                    }
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, creating it (and parent directories) if it doesn't exist, or overwriting if it does. The file_path is relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file (relative to workspace root)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file",
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Find and replace a string in a file. The old_string must match exactly (including whitespace and indentation). The file_path is relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file (relative to workspace root)",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact text to find in the file",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The text to replace old_string with",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command in the workspace directory and return stdout+stderr. Timeout is 120 seconds.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "Find files matching a glob pattern. Returns a newline-separated list of matching file paths relative to the workspace root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern, e.g. '**/*.vue' or 'src/**/*.js'",
                    },
                    "path": {
                        "type": "string",
                        "description": "Subdirectory to search in (relative to workspace root). Defaults to workspace root.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search file contents using a regex pattern. Returns matching lines with file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory to search in (relative to workspace root). Defaults to workspace root.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_serve",
            "description": "Start the development server for local preview and hot-reload debugging. Use this when the user wants to preview the component, run it locally, enable debugging, or start the dev server. Automatically reuses an already-running server for the same workspace instead of starting a duplicate.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Security helper
# ---------------------------------------------------------------------------

def _resolve_safe(file_path: str, workspace_path: Path) -> Path:
    """
    Resolve a file path relative to workspace_path.
    Raises ValueError if the resolved path escapes the workspace.
    """
    resolved = (workspace_path / file_path).resolve()
    ws_resolved = workspace_path.resolve()
    if not str(resolved).startswith(str(ws_resolved)):
        raise ValueError(f"Path '{file_path}' is outside the workspace")
    return resolved


# ---------------------------------------------------------------------------
# Individual tool executors
# ---------------------------------------------------------------------------

async def _read_file(args: dict, workspace_path: Path) -> str:
    file_path = args.get("file_path", "")
    if not file_path:
        return "Error: file_path is required"
    try:
        resolved = _resolve_safe(file_path, workspace_path)
        if not resolved.exists():
            return f"Error: file not found: {file_path}"
        if not resolved.is_file():
            return f"Error: not a file: {file_path}"
        content = resolved.read_text(encoding="utf-8", errors="replace")
        if len(content) > 10000:
            return content[:10000] + f"\n\n... (truncated, {len(content)} chars total)"
        return content
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error reading file: {e}"


def _validate_json_config_file(file_path: str, content: str) -> list[str]:
    """对 widget.config.json / editor.config.json 做 Pydantic 结构校验，返回错误列表"""
    import json as _json
    errors: list[str] = []

    if file_path.endswith(".widget.config.json"):
        try:
            from app.coding.validator import WidgetComponentConfig
            data = _json.loads(content)
            WidgetComponentConfig.model_validate(data)
        except _json.JSONDecodeError as e:
            errors.append(f"{file_path} 不是合法的 JSON：{e}")
        except Exception as e:
            for err in getattr(e, "errors", lambda: [{"msg": str(e)}])():
                loc = " -> ".join(str(x) for x in err.get("loc", []))
                msg = err.get("msg", str(err))
                errors.append(f"{file_path}: {loc} — {msg}" if loc else f"{file_path}: {msg}")

    elif file_path.endswith(".editor.config.json"):
        try:
            data = _json.loads(content)
            for field in ("code", "editorConfigType", "componentName", "configProperty"):
                if field not in data:
                    errors.append(f"{file_path} 缺少必填字段 \"{field}\"")
            if data.get("configProperty") != "customComponentConfig":
                errors.append(f"{file_path} 的 configProperty 必须为 \"customComponentConfig\"")
            if data.get("code") != data.get("editorConfigType"):
                errors.append(f"{file_path} 的 code 与 editorConfigType 必须保持一致")
        except _json.JSONDecodeError as e:
            errors.append(f"{file_path} 不是合法的 JSON：{e}")

    return errors


async def _write_file(args: dict, workspace_path: Path) -> str:
    file_path = args.get("file_path", "")
    content = args.get("content", "")
    if not file_path:
        return "Error: file_path is required"
    try:
        file_path, content = normalize_form_component_generated_file(file_path, content, workspace_path)
        resolved = _resolve_safe(file_path, workspace_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        normalize_form_component_editor_artifacts(workspace_path)
        contract_errors = validate_form_component_editor_workspace(workspace_path)
        if contract_errors:
            return "Error: " + "; ".join(contract_errors)
        # JSON config 结构校验
        json_errors = _validate_json_config_file(file_path, content)
        if json_errors:
            return "Error: " + "; ".join(json_errors)
        lines = content.count("\n") + 1
        return f"Successfully wrote {len(content)} chars ({lines} lines) to {file_path}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error writing file: {e}"


async def _edit_file(args: dict, workspace_path: Path) -> str:
    file_path = args.get("file_path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    if not file_path:
        return "Error: file_path is required"
    if not old_string:
        return "Error: old_string is required"
    try:
        resolved = _resolve_safe(file_path, workspace_path)
        if not resolved.exists():
            return f"Error: file not found: {file_path}"
        content = resolved.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {file_path}"
        if count > 1:
            return f"Error: old_string found {count} times in {file_path}. Provide a more unique string."
        new_content = content.replace(old_string, new_string, 1)
        target_file_path, normalized_content = normalize_form_component_generated_file(
            file_path,
            new_content,
            workspace_path,
        )
        target_resolved = _resolve_safe(target_file_path, workspace_path)
        target_resolved.parent.mkdir(parents=True, exist_ok=True)
        target_resolved.write_text(normalized_content, encoding="utf-8")
        if target_resolved != resolved and resolved.exists():
            resolved.unlink()
        normalize_form_component_editor_artifacts(workspace_path)
        contract_errors = validate_form_component_editor_workspace(workspace_path)
        if contract_errors:
            return "Error: " + "; ".join(contract_errors)
        return f"Successfully edited {target_file_path}"
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error editing file: {e}"


async def _emit_progress(
    progress_callback: Optional[Callable[[str], Awaitable[None] | None]],
    chunk: str,
):
    if not progress_callback or not chunk:
        return
    maybe_awaitable = progress_callback(chunk)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


@lru_cache(maxsize=1)
def _resolve_default_npm_registry() -> str:
    explicit_registry = (
        os.environ.get("APAAS_NPM_REGISTRY")
        or os.environ.get("npm_config_registry")
        or os.environ.get("NPM_CONFIG_REGISTRY")
        or ""
    ).strip()
    if explicit_registry:
        return explicit_registry

    try:
        env = ensure_node_tool_env()
        npm_exec = resolve_executable("npm", env)
        if not npm_exec:
            return FALLBACK_NPM_REGISTRY
        result = subprocess.run(
            [npm_exec, "config", "get", "registry"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        resolved_registry = (result.stdout or "").strip()
        if result.returncode == 0 and resolved_registry and resolved_registry != "undefined":
            return resolved_registry
    except Exception:
        pass

    return FALLBACK_NPM_REGISTRY


def _build_command_env() -> dict[str, str]:
    env = ensure_node_tool_env()
    default_registry = _resolve_default_npm_registry()
    env.setdefault("npm_config_registry", default_registry)
    env.setdefault("NPM_CONFIG_REGISTRY", default_registry)
    env.setdefault("npm_config_cache", DEFAULT_NPM_CACHE_DIR)
    env.setdefault("npm_config_prefer_offline", "true")
    env.setdefault("npm_config_audit", "false")
    env.setdefault("npm_config_fund", "false")
    env.setdefault("FORCE_COLOR", "0")
    return env


def _is_plain_npm_install(command: str) -> bool:
    tokens = _extract_primary_shell_tokens(command)
    if tokens and tokens[0] == "npm" and len(tokens) >= 2 and tokens[1] in {"install", "i"}:
        return all(token.startswith("-") for token in tokens[2:])
    # 复合命令中包含 npm install
    import re
    return bool(re.search(r'\bnpm\s+(?:install|i)\b', command))


def _extract_primary_shell_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []

    if len(tokens) >= 3 and tokens[0] == "cd":
        for operator in ("&&", ";"):
            if operator in tokens:
                tokens = tokens[tokens.index(operator) + 1:]
                break

    primary_tokens: list[str] = []
    for token in tokens:
        if token in {"|", "||", "&&", ";"}:
            break
        if ">" in token or "<" in token:
            continue
        primary_tokens.append(token)

    return primary_tokens


def _is_npm_install_and_build(command: str) -> bool:
    """匹配 npm install && npm run build 复合命令（顺序必须是 install 在前，build 在后）"""
    import re
    return bool(re.search(r'\bnpm\s+(?:install|i)\b.*&&.*\bnpm\s+run\s+build\b', command))


def _is_plain_npm_build(command: str) -> bool:
    # 精确匹配，或者是包含 npm run build 的复合命令（如 export PATH=... && npm run build）
    tokens = _extract_primary_shell_tokens(command)
    if tokens == ["npm", "run", "build"]:
        return True
    # 复合命令：只要最终执行的是 npm run build（不含其他 npm 子命令）
    import re
    return bool(re.search(r'\bnpm\s+run\s+build\b', command)) and "vue-cli-service" not in command


async def _stream_process_output(
    proc: asyncio.subprocess.Process,
    progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
) -> str:
    if proc.stdout is None:
        await proc.wait()
        return ""

    output_chunks: list[str] = []

    while True:
        chunk = await proc.stdout.read(1024)
        if not chunk:
            break
        text = _strip_ansi(chunk.decode("utf-8", errors="replace"))
        if not text:
            continue
        output_chunks.append(text)
        await _emit_progress(progress_callback, text)

    await proc.wait()
    return "".join(output_chunks)


async def _run_command(
    args: dict,
    workspace_path: Path,
    progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
) -> str:
    command = args.get("command", "")
    if not command:
        return "Error: command is required"
    try:
        if _is_npm_install_and_build(command):
            from app.coding.workspace import WorkspaceManager
            ws_mgr = WorkspaceManager()
            install_result = await ws_mgr.install_deps(
                workspace_path.name,
                progress_callback=progress_callback,
            )
            if install_result["status"] != "ok":
                return f"Error: {install_result['message']}"
            await _emit_progress(progress_callback, "[build] 依赖安装完成，开始构建...\n")
            build_result = await ws_mgr.build_project(workspace_path.name)
            await _emit_progress(progress_callback, f"[build] {build_result['message']}\n")
            if build_result["status"] == "ok":
                return build_result["message"]
            return f"Error: {build_result['message']}"

        if _is_plain_npm_install(command):
            from app.coding.workspace import WorkspaceManager

            result = await WorkspaceManager().install_deps(
                workspace_path.name,
                progress_callback=progress_callback,
            )
            if result["status"] == "ok":
                return result["message"]
            return f"Error: {result['message']}"

        if _is_plain_npm_build(command):
            from app.coding.workspace import WorkspaceManager

            await _emit_progress(
                progress_callback,
                "[build] 检测到 npm run build，已切换为兼容构建流程。\n",
            )
            result = await WorkspaceManager().build_project(workspace_path.name)
            await _emit_progress(progress_callback, f"[build] {result['message']}\n")
            if result["status"] == "ok":
                return result["message"]
            return f"Error: {result['message']}"

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workspace_path),
            env=_build_command_env(),
        )
        try:
            output = await asyncio.wait_for(
                _stream_process_output(proc, progress_callback=progress_callback),
                timeout=120,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return "Error: command timed out after 120 seconds"
        exit_info = f"[exit code: {proc.returncode}]"
        if len(output) > 10000:
            output = output[:10000] + f"\n... (truncated)"
        return f"{output}\n{exit_info}" if output else exit_info
    except Exception as e:
        return f"Error running command: {e}"


async def _start_serve(
    args: dict,
    workspace_path: Path,
    progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
) -> str:
    """启动 dev server，复用已有进程，流式输出启动日志，返回 JSON 含公网 URL。"""
    import json as _json

    from app.coding.workspace import WorkspaceManager
    from app.config import settings

    ws_id = workspace_path.name
    ws_mgr = WorkspaceManager()

    # 已在运行 → 直接复用
    status = ws_mgr.is_serve_running(ws_id)
    if status["running"]:
        port = status["port"]
        proxy_base = (settings.code_server_base_url or "").rstrip("/")
        url = f"{proxy_base}/proxy/{port}/"
        await _emit_progress(progress_callback, f"调试服务已在运行（端口 {port}），复用现有进程。\n")
        return _json.dumps({"status": "already_running", "url": url, "port": port})

    # 读取 PROXY_BASE
    proxy_base = (settings.code_server_base_url or "").rstrip("/")
    vibe_cfg = workspace_path / "vibe-serve-config"
    if vibe_cfg.exists():
        for line in vibe_cfg.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^PROXY_BASE=(.+)$", line)
            if m:
                proxy_base = m.group(1).strip()
                break

    # 启动命令：优先 vibe-serve.js，回退到 npx vue-cli-service
    vibe_js = workspace_path / "vibe-serve.js"
    if vibe_js.exists():
        cmd = ["node", "vibe-serve.js", "src/index.js"]
    else:
        cmd = ["npx", "vue-cli-service", "serve", "src/index.js"]

    env = _build_command_env()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except Exception as e:
        return _json.dumps({"status": "error", "message": f"启动失败: {e}"})

    detected_port: Optional[int] = None
    deadline = asyncio.get_event_loop().time() + 90  # 90 秒超时

    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)  # type: ignore[union-attr]
        except asyncio.TimeoutError:
            if proc.returncode is not None:
                break
            continue
        if not raw:
            break

        text = _strip_ansi(raw.decode("utf-8", errors="replace")).rstrip("\n")
        await _emit_progress(progress_callback, text + "\n")

        # 检测端口
        m = re.search(r"Local:\s+https?://localhost:(\d+)", text)
        if m and detected_port is None:
            detected_port = int(m.group(1))

        # 出现 Public URL 说明启动完成，停止阻塞
        if "Public:" in text or ("App running at" in text and detected_port):
            await asyncio.sleep(0.3)
            break

    if proc.returncode is not None:
        return _json.dumps({"status": "error", "message": "serve 进程意外退出"})

    port = detected_port or 8082
    ws_mgr._serve_processes[ws_id] = {"process": proc, "port": port}
    url = f"{proxy_base}/proxy/{port}/"
    return _json.dumps({"status": "ok", "url": url, "port": port})


async def _glob_files(args: dict, workspace_path: Path) -> str:
    pattern = args.get("pattern", "")
    sub_path = args.get("path", "")
    if not pattern:
        return "Error: pattern is required"
    try:
        if sub_path:
            search_root = _resolve_safe(sub_path, workspace_path)
        else:
            search_root = workspace_path.resolve()
        matches = sorted(glob_mod.glob(str(search_root / pattern), recursive=True))
        ws_resolved = workspace_path.resolve()
        # Convert to relative paths
        rel_paths = []
        for m in matches:
            mp = Path(m)
            if mp.is_file():
                try:
                    rel_paths.append(str(mp.relative_to(ws_resolved)))
                except ValueError:
                    pass
        if not rel_paths:
            return "No files matched the pattern"
        result = "\n".join(rel_paths)
        if len(result) > 5000:
            result = result[:5000] + f"\n... (truncated, {len(rel_paths)} files total)"
        return result
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error in glob: {e}"


async def _grep_search(args: dict, workspace_path: Path) -> str:
    pattern = args.get("pattern", "")
    sub_path = args.get("path", "")
    if not pattern:
        return "Error: pattern is required"
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    try:
        if sub_path:
            search_root = _resolve_safe(sub_path, workspace_path)
        else:
            search_root = workspace_path.resolve()

        ws_resolved = workspace_path.resolve()
        results = []
        max_results = 200

        # Skip binary/heavy directories
        skip_dirs = {"node_modules", ".git", "__pycache__", "dist", "build", ".next"}

        for dirpath, dirnames, filenames in os.walk(str(search_root)):
            # Prune dirs in-place
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fname in filenames:
                if len(results) >= max_results:
                    break
                fpath = Path(dirpath) / fname
                # Skip binary files (heuristic: check extension)
                if fpath.suffix in (".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".zip", ".tar", ".gz", ".lock"):
                    continue
                try:
                    rel = str(fpath.relative_to(ws_resolved))
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if regex.search(line):
                            results.append(f"{rel}:{i}: {line.rstrip()}")
                            if len(results) >= max_results:
                                break
                except (UnicodeDecodeError, PermissionError, OSError):
                    continue

        if not results:
            return "No matches found"
        output = "\n".join(results)
        if len(output) > 5000:
            output = output[:5000] + f"\n... (truncated, {len(results)} matches total)"
        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error in grep: {e}"


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

_EXECUTORS = {
    "read_file": _read_file,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "run_command": _run_command,
    "glob_files": _glob_files,
    "grep_search": _grep_search,
    "start_serve": _start_serve,
}


async def execute_tool(
    tool_name: str,
    arguments: dict,
    workspace_path: Path,
    progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
) -> str:
    """Execute a tool and return the result as a string."""
    executor = _EXECUTORS.get(tool_name)
    if not executor:
        return f"Error: unknown tool '{tool_name}'"
    if tool_name in ("run_command", "start_serve"):
        return await executor(arguments, workspace_path, progress_callback)
    return await executor(arguments, workspace_path)
