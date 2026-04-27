"""grep_code tool — 在 workspace 内搜索代码。

不用 shell ripgrep 避免依赖外部 binary；Python stdlib 递归匹配 + fnmatch。
性能对小 workspace（~100 文件）足够，大 workspace 由 coding 层另外处理。
"""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any

from app.agents.types import AgentContext, Tool, ToolResult
from app.agents.verification.config import GREP_MAX_MATCHES
from app.agents.verification.state import VerificationState

logger = logging.getLogger(__name__)


# 默认跳过的目录（不扫 node_modules / dist / .git 等）
_DEFAULT_SKIP_DIRS = {
    "node_modules", "dist", "build", "__pycache__", ".git", ".idea", ".vscode",
    "target", "out", "venv", ".venv", "coverage",
}

# 默认只看源码/配置扩展名
_DEFAULT_EXTS = {
    ".vue", ".js", ".ts", ".tsx", ".jsx", ".json", ".html", ".css", ".scss",
    ".java", ".xml", ".yaml", ".yml", ".py", ".md", ".mdc",
}

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索字符串（大小写敏感）。不是正则，是字面匹配；想要正则请用 Python re 语法写在 regex 参数",
        },
        "regex": {
            "type": "boolean",
            "description": "True 时 query 作正则处理",
        },
        "glob": {
            "type": "string",
            "description": "可选 — 只在匹配 glob 的文件内搜（例：'src/**/*.vue'）。不传则所有源文件",
        },
        "max_matches": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "description": f"返回匹配行数上限，默认 {GREP_MAX_MATCHES}",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


def _should_skip_dir(dir_name: str) -> bool:
    return dir_name in _DEFAULT_SKIP_DIRS or dir_name.startswith(".")


def _file_ok(rel_path: str, glob: str | None) -> bool:
    path = Path(rel_path)
    if glob and not fnmatch.fnmatch(rel_path, glob):
        return False
    if path.suffix.lower() not in _DEFAULT_EXTS:
        return False
    return True


def build_grep_code_tool(state: VerificationState, workspace_root: Path) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        import re

        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(success=False, content="query 不能为空", error="empty_query")

        use_regex = bool(args.get("regex"))
        glob = args.get("glob")
        max_matches = int(args.get("max_matches", GREP_MAX_MATCHES))
        max_matches = max(1, min(100, max_matches))

        # 记录 query（供 agent 自查）
        if query not in state.grep_queries:
            state.grep_queries.append(query)

        # 编译 regex（若需要）
        regex_obj = None
        if use_regex:
            try:
                regex_obj = re.compile(query)
            except re.error as e:
                return ToolResult(success=False, content=f"正则不合法：{e}", error="bad_regex")

        if not workspace_root.exists():
            return ToolResult(
                success=False,
                content=f"workspace 不存在：{workspace_root}",
                error="no_workspace",
            )

        # 扫描
        matches: list[dict[str, Any]] = []
        total_files_scanned = 0
        for root, dirs, files in __import__("os").walk(workspace_root):
            # 跳过目录
            dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
            for name in files:
                full = Path(root) / name
                try:
                    rel = str(full.relative_to(workspace_root))
                except ValueError:
                    continue
                if not _file_ok(rel, glob):
                    continue
                try:
                    text = full.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                total_files_scanned += 1
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if regex_obj:
                        if not regex_obj.search(line):
                            continue
                    else:
                        if query not in line:
                            continue
                    matches.append({
                        "file": rel,
                        "line": lineno,
                        "text": line[:300],
                    })
                    if len(matches) >= max_matches:
                        break
                if len(matches) >= max_matches:
                    break
            if len(matches) >= max_matches:
                break

        if not matches:
            return ToolResult(
                success=True,
                content=(
                    f"未找到匹配：query={query!r}，scan={total_files_scanned} files。"
                    "可能：查询词写错了 / 代码里没实现 / 写在你还没扫的文件里（改 glob 再试）。"
                ),
                data={"matches": [], "scan_files": total_files_scanned},
            )

        lines = [f"找到 {len(matches)} 条匹配 (scan={total_files_scanned} files)："]
        for m in matches:
            lines.append(f"- {m['file']}:{m['line']}: {m['text']}")
        return ToolResult(
            success=True,
            content="\n".join(lines),
            data={"matches": matches, "scan_files": total_files_scanned},
        )

    return Tool(
        name="grep_code",
        description=(
            "在 workspace 里搜索字符串或正则。只扫常见源码扩展名（.vue/.ts/.java 等），"
            "自动跳过 node_modules/dist 等目录。"
        ),
        parameters_schema=_SCHEMA,
        execute=execute,
        idempotent=True,
    )
