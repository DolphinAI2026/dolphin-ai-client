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
from pathlib import Path
from typing import Awaitable, Callable, Optional

DEFAULT_NPM_REGISTRY = os.environ.get("APAAS_NPM_REGISTRY", "https://registry.npmmirror.com")
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


async def _write_file(args: dict, workspace_path: Path) -> str:
    file_path = args.get("file_path", "")
    content = args.get("content", "")
    if not file_path:
        return "Error: file_path is required"
    try:
        resolved = _resolve_safe(file_path, workspace_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
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
        resolved.write_text(new_content, encoding="utf-8")
        return f"Successfully edited {file_path}"
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


def _build_command_env() -> dict[str, str]:
    env = {**os.environ}
    env.setdefault("npm_config_registry", DEFAULT_NPM_REGISTRY)
    env.setdefault("npm_config_cache", DEFAULT_NPM_CACHE_DIR)
    env.setdefault("npm_config_prefer_offline", "true")
    env.setdefault("npm_config_audit", "false")
    env.setdefault("npm_config_fund", "false")
    env.setdefault("FORCE_COLOR", "0")
    return env


def _is_plain_npm_install(command: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False

    if len(tokens) < 2 or tokens[0] != "npm" or tokens[1] not in {"install", "i"}:
        return False

    return all(token.startswith("-") for token in tokens[2:])


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
        if _is_plain_npm_install(command):
            from app.coding.workspace import WorkspaceManager

            result = await WorkspaceManager().install_deps(
                workspace_path.name,
                progress_callback=progress_callback,
            )
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
    if tool_name == "run_command":
        return await executor(arguments, workspace_path, progress_callback)
    return await executor(arguments, workspace_path)
