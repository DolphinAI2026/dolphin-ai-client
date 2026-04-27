"""read_workspace_context tool — 迭代场景读 workspace 当前产物。

用途：
- Phase ITERATE（用户在既有 workspace 上提新需求）时，先读 apaas.json /
  widget.config.json / 关键源码，让 agent 理解现状再决定怎么改
- 首轮（无 workspace_id）场景下此 tool 不可用（返回错误）

复用：调用 app.coding.workspace.WorkspaceManager 读文件，避免新造一套。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.brainstorm.state import BrainstormState
from app.agents.types import AgentContext, Tool, ToolResult

# 白名单：只允许读这些路径下的文件（防止 agent 误读 / 性能/安全）
_ALLOWED_PREFIXES: tuple[str, ...] = (
    "apaas.json",
    "widget.config.json",
    "package.json",
    ".cursor/rules/",
    "src/",
    "web/src/",
    "mobile/src/",
    "backend/",
)

# 单次读取字节上限（防止大文件爆 context）
_FILE_MAX_BYTES = 20_000

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "要读取的相对路径列表（相对 workspace 根）。"
                "仅允许读 apaas.json / widget.config.json / package.json / "
                ".cursor/rules/ / src/ / web/src/ / mobile/src/ / backend/ 下的文件。"
                "不传时仅返回 workspace 摘要（project_name / project_type / files 目录）。"
            ),
        },
    },
    "additionalProperties": False,
}


def _is_path_allowed(rel_path: str) -> bool:
    return any(rel_path == p or rel_path.startswith(p) for p in _ALLOWED_PREFIXES)


def _read_safe(full_path: Path) -> str:
    try:
        data = full_path.read_bytes()
    except Exception as e:
        return f"<read error: {e}>"
    if len(data) > _FILE_MAX_BYTES:
        head = data[:_FILE_MAX_BYTES].decode("utf-8", errors="replace")
        return head + f"\n\n<... truncated at {_FILE_MAX_BYTES} bytes>"
    return data.decode("utf-8", errors="replace")


def build_read_workspace_context_tool(state: BrainstormState) -> Tool:
    async def execute(args: dict[str, Any], ctx: AgentContext) -> ToolResult:
        if not ctx.workspace_id:
            return ToolResult(
                success=False,
                content="当前没有 workspace_id（首轮场景），此 tool 不可用。",
                error="no_workspace",
            )

        # 延迟 import，避免 coding 模块在 brainstorm 包初始化期被拉起
        from app.coding import workspace as ws_module

        ws_mgr = ws_module.WorkspaceManager()
        try:
            info = ws_mgr.get_workspace_info(ctx.workspace_id)
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"读取 workspace 信息失败：{e}",
                error=str(e),
            )

        ws_root = Path(ws_mgr.get_workspace_path(ctx.workspace_id))
        state.workspace_context_read = True

        paths: list[str] = args.get("paths") or []
        if not paths:
            # 只返回摘要
            lines = [
                f"Workspace: {info.get('project_name', '(unknown)')}",
                f"project_type: {info.get('project_type', '(unknown)')}",
                f"root: {ws_root}",
                "",
                f"文件总数: {len(info.get('files') or [])}",
                "（传 paths 参数来读具体文件内容）",
            ]
            return ToolResult(
                success=True,
                content="\n".join(lines),
                data={"info": info, "root": str(ws_root)},
            )

        # 按 paths 读文件
        results: list[dict[str, Any]] = []
        content_chunks: list[str] = []
        for rel in paths:
            rel = rel.strip().lstrip("/")
            if not _is_path_allowed(rel):
                results.append({"path": rel, "ok": False, "error": "path_not_allowed"})
                content_chunks.append(f"### `{rel}`\n<拒绝读取：不在白名单>")
                continue
            full = ws_root / rel
            if not full.exists():
                results.append({"path": rel, "ok": False, "error": "not_found"})
                content_chunks.append(f"### `{rel}`\n<文件不存在>")
                continue
            if full.is_dir():
                children = sorted(p.name for p in full.iterdir())[:50]
                results.append({"path": rel, "ok": True, "is_dir": True, "children": children})
                content_chunks.append(f"### `{rel}/` (目录)\n- " + "\n- ".join(children))
                continue
            try:
                text = _read_safe(full)
                # 对 JSON 文件做一层 pretty print（控制 size）
                if rel.endswith(".json") and len(text) < _FILE_MAX_BYTES:
                    try:
                        parsed = json.loads(text)
                        text = json.dumps(parsed, ensure_ascii=False, indent=2)[:_FILE_MAX_BYTES]
                    except Exception:
                        pass
                results.append({"path": rel, "ok": True, "is_dir": False, "size": len(text)})
                content_chunks.append(f"### `{rel}`\n```\n{text}\n```")
            except Exception as e:
                results.append({"path": rel, "ok": False, "error": str(e)})
                content_chunks.append(f"### `{rel}`\n<读取失败：{e}>")

        return ToolResult(
            success=True,
            content="\n\n".join(content_chunks) or "（无内容）",
            data={"results": results, "root": str(ws_root)},
        )

    return Tool(
        name="read_workspace_context",
        description=(
            "读取当前 workspace 的产物文件（仅迭代场景可用）。"
            "不传 paths 仅回摘要；传 paths 读具体文件内容（受白名单限制，单文件 ≤20KB）。"
            "典型用法：先不传 paths 看摘要，再针对性读 apaas.json / widget.config.json。"
        ),
        parameters_schema=_SCHEMA,
        execute=execute,
        idempotent=True,
    )
