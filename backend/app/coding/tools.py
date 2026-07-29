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

from app import runtime
from app.coding.form_component_editor import (
    normalize_form_component_editor_artifacts,
    normalize_form_component_dual_apaas_json,
    normalize_form_component_generated_file,
    validate_form_component_editor_workspace,
)
from app.coding.runtime_env import ensure_node_tool_env, resolve_executable
from app.coding.command_sandbox import should_sandbox, wrap_command

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
                        "description": (
                            "Required. Path to the file relative to workspace root. "
                            "Example: 'web/src/form-component/form-editor/form-component-xxx-setting.vue'. "
                            "Omitting this parameter will cause an error."
                        ),
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
            "description": (
                "Find and replace a string in a file. "
                "IMPORTANT: You MUST call read_file on the target file first to obtain its exact current content — "
                "never construct old_string from memory or a previous read, as the file may have changed. "
                "If this tool returns 'Error: old_string not found', call read_file again to refresh the content "
                "and rebuild old_string from the refreshed content before retrying. "
                "The old_string must match exactly (including whitespace and indentation). "
                "The file_path is relative to the workspace root."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": (
                            "Required. Path to the file relative to workspace root. "
                            "The file must already exist. "
                            "Example: 'web/src/form-component/form-editor/form-component-xxx-setting.vue'. "
                            "Omitting this parameter will cause an error."
                        ),
                    },
                    "old_string": {
                        "type": "string",
                        "description": (
                            "The exact text to find in the file. "
                            "Must be copied verbatim from a read_file result — do not guess or reconstruct from memory."
                        ),
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


_FORBIDDEN_FORM_COMPONENT_FILES = {
    # Vue app 脚手架文件 — form-component 工程打包为独立 widget，不需要 App 壳
    "src/App.vue", "src/main.js", "src/index.html",
    "web/src/App.vue", "web/src/main.js", "web/src/index.html",
    "mobile/src/App.vue", "mobile/src/main.js", "mobile/src/index.html",
}


def _is_form_component_workspace(workspace_path: Path) -> bool:
    """判断工作区是否为 form-component 系列（单端或双端）。"""
    if (workspace_path / "shared" / "widget.config.json").exists():
        return True
    meta_file = workspace_path / ".workspace.json"
    if meta_file.exists():
        try:
            import json as _json
            meta = _json.loads(meta_file.read_text(encoding="utf-8"))
            ptype = meta.get("project_type", "")
            return ptype == "form-component-dual"
        except Exception:
            pass
    return False


async def _write_file(args: dict, workspace_path: Path) -> str:
    file_path = args.get("file_path", "")
    content = args.get("content", "")
    if not file_path:
        return "Error: file_path is required"
    # 拦截 Vue app 壳文件：form-component 工程不需要 App.vue/main.js
    normalized_rel = file_path.replace("\\", "/").lstrip("./").strip("/")
    if normalized_rel in _FORBIDDEN_FORM_COMPONENT_FILES and _is_form_component_workspace(workspace_path):
        return (
            f"Error: {file_path} 不应存在。form-component 工程打包为独立 widget，"
            "没有 App 壳也没有 main.js 入口。预览由平台注入，不要生成 App.vue / main.js / index.html。"
            "如果需要调试渲染，直接修改 form-component/ 下的 Vue 组件即可。"
        )
    try:
        file_path, content = normalize_form_component_generated_file(file_path, content, workspace_path)
        resolved = _resolve_safe(file_path, workspace_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        normalize_form_component_editor_artifacts(workspace_path)
        normalize_form_component_dual_apaas_json(workspace_path)
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
        normalize_form_component_dual_apaas_json(workspace_path)
        contract_errors = validate_form_component_editor_workspace(workspace_path)
        if contract_errors:
            return "Error: " + "; ".join(contract_errors)
        # JSON config 结构校验（和 _write_file 保持一致，避免 edit_file 改坏 JSON schema 不报错）
        json_errors = _validate_json_config_file(target_file_path, normalized_content)
        if json_errors:
            return "Error: " + "; ".join(json_errors)
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
            **runtime.subprocess_window_kwargs(),
        )
        resolved_registry = (result.stdout or "").strip()
        if result.returncode == 0 and resolved_registry and resolved_registry != "undefined":
            return resolved_registry
    except Exception:
        pass

    return FALLBACK_NPM_REGISTRY


def _build_command_env(command: str = "") -> dict[str, str]:
    env = ensure_node_tool_env()
    default_registry = _resolve_default_npm_registry()
    env.setdefault("npm_config_registry", default_registry)
    env.setdefault("NPM_CONFIG_REGISTRY", default_registry)
    env.setdefault("npm_config_cache", DEFAULT_NPM_CACHE_DIR)
    env.setdefault("npm_config_prefer_offline", "true")
    env.setdefault("npm_config_audit", "false")
    env.setdefault("npm_config_fund", "false")
    env.setdefault("FORCE_COLOR", "0")
    if _contains_maven_command(command):
        from app.coding.workspace import _apaas_backend_build_env
        env = _apaas_backend_build_env(env)
    return env


def _strip_env_assignments(tokens: list[str]) -> list[str]:
    while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
        tokens = tokens[1:]
    return tokens


def _contains_maven_command(command: str) -> bool:
    tokens = _strip_env_assignments(_extract_primary_shell_tokens(command))
    if tokens:
        executable = Path(tokens[0]).name
        if executable in {"mvn", "mvnw", "mvnw.cmd"}:
            return True
    return bool(re.search(r"(^|[;&|]\s*)(?:\./)?mvnw?\b", command))


def _is_maven_package_build(command: str) -> bool:
    tokens = _strip_env_assignments(_extract_primary_shell_tokens(command))
    if not tokens:
        return False
    executable = Path(tokens[0]).name
    if executable not in {"mvn", "mvnw", "mvnw.cmd"}:
        return False
    return any(t == "package" or t.endswith(":package") for t in tokens)


def _contains_npm_install(command: str) -> bool:
    tokens = _extract_primary_shell_tokens(command)
    if tokens and tokens[0] == "npm" and len(tokens) >= 2 and tokens[1] in {"install", "i"}:
        return True
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


def _contains_build_command(command: str) -> bool:
    """匹配 aPaaS 自开发常见构建命令。

    LLM 有时会传 `npm install && ./node_modules/.bin/vue-cli-service build ...`
    这类长命令。这里统一拦截，避免绕过 WorkspaceManager 的依赖缓存和兼容构建流程。
    """
    import re
    return bool(
        re.search(r'\bnpm\s+run\s+build\b', command)
        or re.search(r'(?:^|[/\s])vue-cli-service\s+build\b', command)
        or re.search(r'\bdf-apaas-cli\s+build\b', command)
    )


def _is_npm_install_and_build(command: str) -> bool:
    """匹配 install + build 复合命令（顺序不强依赖具体 build 写法）。"""
    return _contains_npm_install(command) and _contains_build_command(command)


def _is_plain_npm_build(command: str) -> bool:
    # 精确匹配，或者是包含 npm run build 的复合命令（如 export PATH=... && npm run build）
    tokens = _extract_primary_shell_tokens(command)
    if tokens == ["npm", "run", "build"]:
        return True
    # 复合命令：只要包含标准 build / vue-cli-service build / df-apaas-cli build，
    # 且没有 npm install，就交给 WorkspaceManager 的兼容构建流程。
    return _contains_build_command(command) and not _contains_npm_install(command)


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

        if _contains_npm_install(command):
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

        if _is_maven_package_build(command):
            from app.coding.workspace import WorkspaceManager

            await _emit_progress(
                progress_callback,
                "[build] 检测到 Maven 打包，已切换为统一 JDK 配置构建流程。\n",
            )
            result = await WorkspaceManager().build_project(workspace_path.name)
            await _emit_progress(progress_callback, f"[build] {result['message']}\n")
            if result["status"] == "ok":
                return result["message"]
            return f"Error: {result['message']}"

        if should_sandbox():
            # 桌面态(客户机)把通用命令写入限制在工作区,挡住写出工作区/rm 别的项目。
            proc = await asyncio.create_subprocess_exec(
                *wrap_command(command, workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(workspace_path),
                env=_build_command_env(command),
                **runtime.subprocess_window_kwargs(),
            )
        else:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(workspace_path),
                env=_build_command_env(command),
                **runtime.subprocess_window_kwargs(),
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


async def _spawn_one_serve(
    cmd: list,
    cwd: str,
    env: dict,
    progress_callback: Optional[Callable[[str], Awaitable[None] | None]],
    label: str = "",
):
    """启动单个 serve 子进程，流式输出日志，返回 (proc, detected_port)。
    启动失败时返回 (None, None)。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            **runtime.subprocess_window_kwargs(),
        )
    except Exception as e:
        await _emit_progress(progress_callback, f"[{label}] 启动失败: {e}\n")
        return None, None

    detected_port: Optional[int] = None
    deadline = asyncio.get_event_loop().time() + 90

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
        prefix = f"[{label}] " if label else ""
        await _emit_progress(progress_callback, prefix + text + "\n")

        m = re.search(r"Local:\s+https?://localhost:(\d+)", text)
        if m and detected_port is None:
            detected_port = int(m.group(1))

        if "Public:" in text or ("App running at" in text and detected_port):
            await asyncio.sleep(0.3)
            break

    if proc.returncode is not None:
        return None, None

    return proc, detected_port


async def _start_serve(
    args: dict,
    workspace_path: Path,
    progress_callback: Optional[Callable[[str], Awaitable[None] | None]] = None,
) -> str:
    """启动 dev server，复用已有进程，流式输出启动日志，返回 JSON 含公网 URL。
    双端工程（form-component-dual）并发启动 PC 端和移动端两个 serve 进程。
    """
    import json as _json

    from app.coding.workspace import WorkspaceManager

    ws_id = workspace_path.name
    ws_mgr = WorkspaceManager()

    # ── 检测是否双端工程 ──────────────────────────────────────────
    _is_dual = False
    _meta_file = workspace_path / ".workspace.json"
    if _meta_file.exists():
        try:
            _meta = _json.loads(_meta_file.read_text(encoding="utf-8"))
            _is_dual = _meta.get("project_type") == "form-component-dual"
        except Exception:
            pass

    # ── 读取 PROXY_BASE ──────────────────────────────────────────
    proxy_base = ""
    # 双端：从 web/ 子目录读取；单端：从工作区根目录读取
    _cfg_dir = workspace_path / "web" if _is_dual else workspace_path
    vibe_cfg = _cfg_dir / "vibe-serve-config"
    if vibe_cfg.exists():
        for line in vibe_cfg.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^PROXY_BASE=(.+)$", line)
            if m:
                proxy_base = m.group(1).strip()
                break

    # ── 已在运行 → 直接复用 ──────────────────────────────────────
    status = ws_mgr.is_serve_running(ws_id)
    if status["running"]:
        if status.get("dual"):
            parts = []
            if status.get("web"):
                parts.append(f"PC 端（端口 {status['web']['port']}）")
            if status.get("mobile"):
                parts.append(f"移动端（端口 {status['mobile']['port']}）")
            await _emit_progress(
                progress_callback,
                f"调试服务已在运行（{'、'.join(parts)}），复用现有进程。\n",
            )
            web_url = (
                f"{proxy_base}/proxy/{status['web']['port']}/"
                if status.get("web") else None
            )
            mobile_url = (
                f"{proxy_base}/proxy/{status['mobile']['port']}/"
                if status.get("mobile") else None
            )
            return _json.dumps({
                "status": "already_running",
                "web_url": web_url,
                "mobile_url": mobile_url,
            })
        else:
            port = status["port"]
            url = f"{proxy_base}/proxy/{port}/"
            await _emit_progress(
                progress_callback, f"调试服务已在运行（端口 {port}），复用现有进程。\n"
            )
            return _json.dumps({"status": "already_running", "url": url, "port": port})

    env = _build_command_env()

    # ══════════════════════════════════════════════════════════════
    # 双端工程：并发启动 web/ 和 mobile/ 两个独立 Vue CLI 项目
    # ══════════════════════════════════════════════════════════════
    if _is_dual:
        import socket as _socket

        def _find_free_port(start: int = 8082) -> int:
            """找一个本地可用端口，避免 web 和 mobile 争抢同一个端口。"""
            port = start
            while True:
                with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
                    if s.connect_ex(("localhost", port)) != 0:
                        return port
                    port += 1

        web_port_hint = _find_free_port(8082)
        mobile_port_hint = _find_free_port(web_port_hint + 1)

        def _make_cmd(sub: str) -> list:
            vibe_js = workspace_path / sub / "vibe-serve.js"
            if vibe_js.exists():
                return ["node", "vibe-serve.js", "src/index.js"]
            return ["npx", "vue-cli-service", "serve", "src/index.js"]

        # 各自设置不同的 PORT 环境变量，避免并发时两个进程争抢同一端口
        web_env = {**env, "PORT": str(web_port_hint)}
        mobile_env = {**env, "PORT": str(mobile_port_hint)}

        (web_proc, web_port), (mobile_proc, mobile_port) = await asyncio.gather(
            _spawn_one_serve(
                _make_cmd("web"), str(workspace_path / "web"), web_env, progress_callback, "PC端"
            ),
            _spawn_one_serve(
                _make_cmd("mobile"), str(workspace_path / "mobile"), mobile_env, progress_callback, "移动端"
            ),
        )

        if web_proc is None and mobile_proc is None:
            return _json.dumps({"status": "error", "message": "双端 serve 启动均失败"})

        dual_entry: dict = {}
        web_url = mobile_url = None
        if web_proc is not None:
            web_port = web_port or 8082
            dual_entry["web"] = {"process": web_proc, "port": web_port}
            web_url = f"{proxy_base}/proxy/{web_port}/"
        if mobile_proc is not None:
            mobile_port = mobile_port or 8083
            dual_entry["mobile"] = {"process": mobile_proc, "port": mobile_port}
            mobile_url = f"{proxy_base}/proxy/{mobile_port}/"

        ws_mgr._serve_processes[ws_id] = dual_entry
        return _json.dumps({
            "status": "ok",
            "web_url": web_url,
            "mobile_url": mobile_url,
        })

    # ══════════════════════════════════════════════════════════════
    # 单端工程：原有逻辑不变
    # ══════════════════════════════════════════════════════════════
    vibe_js = workspace_path / "vibe-serve.js"
    if vibe_js.exists():
        cmd = ["node", "vibe-serve.js", "src/index.js"]
    else:
        cmd = ["npx", "vue-cli-service", "serve", "src/index.js"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            **runtime.subprocess_window_kwargs(),
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

        m = re.search(r"Local:\s+https?://localhost:(\d+)", text)
        if m and detected_port is None:
            detected_port = int(m.group(1))

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
