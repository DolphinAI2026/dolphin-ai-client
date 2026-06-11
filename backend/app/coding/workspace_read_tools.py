"""工作区只读工具 —— 给 read_query 只读应答路径用。

纯函数实现（按 ws_path 操作），不依赖 WorkspaceManager 实例，方便单测。
跳过规则与 WorkspaceManager.list_files 对齐：node_modules / 顶层隐藏文件
（保留 .cursor/rules 规范文档）。所有输出都做截断，避免撑爆 LLM 上下文。
"""
from __future__ import annotations

import re
from pathlib import Path

_MAX_LIST_ENTRIES = 800
_MAX_READ_CHARS = 8000
_MAX_FILE_PROBE = 256 * 1024
_MAX_SEARCH_RESULTS = 50

# OpenAI function-calling 工具定义
WORKSPACE_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_workspace_files",
            "description": "列出当前代码工作区的所有文件（相对路径，已排除 node_modules 与隐藏文件）。回答工作区代码相关问题前先调它了解结构。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_workspace_file",
            "description": "读取工作区单个文件的文本内容（过长会截断）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件相对路径，如 src/page.vue"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_workspace_code",
            "description": "在工作区所有文本文件中按正则搜索代码，返回 路径:行号: 内容 列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "正则表达式（Python re 语法）"},
                },
                "required": ["pattern"],
            },
        },
    },
]

WORKSPACE_TOOL_NAMES = {t["function"]["name"] for t in WORKSPACE_TOOL_DEFINITIONS}

WORKSPACE_TOOL_DISPLAY = {
    "list_workspace_files": "列出工作区文件",
    "read_workspace_file": "读取文件",
    "search_workspace_code": "搜索代码",
}


def _iter_text_files(ws_path: Path) -> list[str]:
    """与 WorkspaceManager.list_files 同规则的相对路径清单。"""
    files: list[str] = []
    for p in sorted(ws_path.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(ws_path))
        if "node_modules" in rel:
            continue
        if rel.startswith(".") and not rel.startswith(".cursor/rules/"):
            continue
        files.append(rel)
    return files


def _safe_target(ws_path: Path, rel: str) -> Path:
    root = ws_path.resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"文件路径越界: {rel}")
    return target


def list_workspace_files(ws_path: Path) -> str:
    files = _iter_text_files(ws_path)
    out = files[:_MAX_LIST_ENTRIES]
    note = f"\n…(共 {len(files)} 个文件，仅显示前 {_MAX_LIST_ENTRIES} 个)" if len(files) > _MAX_LIST_ENTRIES else ""
    return "\n".join(out) + note if out else "(工作区为空)"


def read_workspace_file(ws_path: Path, rel: str) -> str:
    target = _safe_target(ws_path, rel)
    if not target.is_file():
        return f"Error: 文件不存在: {rel}"
    try:
        text = target.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return f"Error: {rel} 是二进制文件，无法以文本读取"
    if len(text) > _MAX_READ_CHARS:
        return text[:_MAX_READ_CHARS] + f"\n…(已截断，全文共 {len(text)} 字符)"
    return text


def search_workspace_code(ws_path: Path, pattern: str) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: 正则不合法: {exc}"
    hits: list[str] = []
    for rel in _iter_text_files(ws_path):
        p = ws_path / rel
        try:
            if p.stat().st_size > _MAX_FILE_PROBE:
                continue
            text = p.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                if len(hits) >= _MAX_SEARCH_RESULTS:
                    return "\n".join(hits) + f"\n…(已达 {_MAX_SEARCH_RESULTS} 条上限)"
    return "\n".join(hits) if hits else "(无匹配)"


def execute_workspace_tool(ws_path: Path, fn_name: str, args: dict) -> str:
    """统一入口：执行一个工作区只读工具，返回字符串结果（错误也以字符串返回）。"""
    try:
        if fn_name == "list_workspace_files":
            return list_workspace_files(ws_path)
        if fn_name == "read_workspace_file":
            return read_workspace_file(ws_path, str(args.get("file_path") or ""))
        if fn_name == "search_workspace_code":
            return search_workspace_code(ws_path, str(args.get("pattern") or ""))
        return f"Error: 未知工作区工具 {fn_name!r}"
    except Exception as exc:  # 路径越界等
        return f"Error: {exc}"
