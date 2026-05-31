"""read_file tool — 读 workspace 内单文件（带长度限制）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.types import AgentContext, Tool, ToolResult
from app.agents.verification.config import READ_MAX_BYTES
from app.agents.verification.state import VerificationState

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "相对 workspace 根的路径（如 `web/src/form-component/rating-star/edit.vue`）",
        },
        "start_line": {
            "type": "integer",
            "minimum": 1,
            "description": "可选 — 从第几行开始读（1-based）",
        },
        "end_line": {
            "type": "integer",
            "minimum": 1,
            "description": "可选 — 读到第几行（含）",
        },
    },
    "required": ["path"],
    "additionalProperties": False,
}


def build_read_file_tool(state: VerificationState, workspace_root: Path) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        rel = str(args.get("path", "")).strip().lstrip("/")
        if not rel:
            return ToolResult(success=False, content="path 不能为空", error="empty_path")

        full = workspace_root / rel
        # 路径穿越保护
        try:
            full_resolved = full.resolve()
            ws_resolved = workspace_root.resolve()
            if not str(full_resolved).startswith(str(ws_resolved)):
                return ToolResult(
                    success=False,
                    content=f"非法路径（越界）：{rel}",
                    error="path_traversal",
                )
        except Exception as e:
            return ToolResult(success=False, content=f"路径解析失败：{e}", error="bad_path")

        if not full.exists():
            return ToolResult(
                success=False,
                content=f"文件不存在：{rel}",
                error="not_found",
                data={"path": rel},
            )
        if full.is_dir():
            children = sorted(p.name for p in full.iterdir())[:50]
            return ToolResult(
                success=True,
                content=f"`{rel}/` 是目录，包含：\n" + "\n".join(f"- {c}" for c in children),
                data={"path": rel, "is_dir": True, "children": children},
            )

        state.read_files.add(rel)

        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(
                success=False, content=f"读文件失败：{e}", error=str(e),
            )

        start = args.get("start_line")
        end = args.get("end_line")
        if start or end:
            lines_all = text.splitlines()
            s = max(1, int(start or 1)) - 1
            e = min(len(lines_all), int(end or len(lines_all)))
            segment = "\n".join(lines_all[s:e])
            if len(segment) > READ_MAX_BYTES:
                segment = segment[:READ_MAX_BYTES] + f"\n<... 从第{s+1}行的 {READ_MAX_BYTES} 字节后截断>"
            return ToolResult(
                success=True,
                content=f"`{rel}` [lines {s+1}..{e}]:\n```\n{segment}\n```",
                data={"path": rel, "start_line": s + 1, "end_line": e, "size": len(segment)},
            )

        if len(text) > READ_MAX_BYTES:
            head = text[:READ_MAX_BYTES]
            remaining = len(text) - READ_MAX_BYTES
            return ToolResult(
                success=True,
                content=f"`{rel}` (前 {READ_MAX_BYTES} 字节，剩余 {remaining}):\n```\n{head}\n```",
                data={"path": rel, "size": len(text), "truncated": True},
            )

        return ToolResult(
            success=True,
            content=f"`{rel}`:\n```\n{text}\n```",
            data={"path": rel, "size": len(text)},
        )

    return Tool(
        name="read_file",
        description=(
            "读 workspace 内单个文件（最多 16KB）。可选 start_line / end_line 只读片段。"
            "对大文件（超 16KB），用 line 范围精读；不要一次 dump。"
        ),
        parameters_schema=_SCHEMA,
        execute=execute,
        idempotent=True,
    )
