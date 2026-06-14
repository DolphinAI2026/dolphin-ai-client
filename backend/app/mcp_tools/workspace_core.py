"""AI Coding workspace file, search, and status MCP tools."""

from __future__ import annotations

from typing import Any, Callable


_registered_tools_by_mcp: dict[int, dict[str, object]] = {}


def _as_nonempty_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_dev_workspace_lookup_text(value: Any) -> str:
    import re as _re

    return _re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "").lower())


def _dev_workspace_lookup_values(ws: dict[str, Any]) -> set[str]:
    import json as _json
    from pathlib import Path

    values = {
        _as_nonempty_str(ws.get("id") or ws.get("ws_id")),
        _as_nonempty_str(ws.get("folder_name")),
        _as_nonempty_str(ws.get("project_name")),
        _as_nonempty_str(ws.get("display_name")),
    }
    disk_path = _as_nonempty_str(ws.get("disk_path"))
    if disk_path:
        values.add(Path(disk_path).name)
    project_name = _as_nonempty_str(ws.get("project_name"))
    if project_name:
        values.add(f"{project_name}.zip")
        short_name = project_name
        for prefix in ("form-page-", "form-component-", "form-view-", "form-layout-", "frontend-plugin-"):
            if short_name.startswith(prefix):
                short_name = short_name[len(prefix):]
                break
        values.add(f"apaas-custom-{short_name}")
    if disk_path:
        for rel in ("src/apaas.json", "apaas.json"):
            cfg_path = Path(disk_path) / rel
            if not cfg_path.exists():
                continue
            try:
                cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            values.add(_as_nonempty_str(cfg.get("outputName")))
            components = cfg.get("components")
            if isinstance(components, dict):
                values.update(_as_nonempty_str(k) for k in components.keys())
                values.update(
                    _as_nonempty_str(v.get("name") or v.get("path"))
                    for v in components.values()
                    if isinstance(v, dict)
                )
    return {v for v in values if v}


def _dev_workspace_matches_query(ws: dict[str, Any], query: str) -> bool:
    q = _normalize_dev_workspace_lookup_text(query)
    if not q:
        return True
    for value in _dev_workspace_lookup_values(ws):
        normalized = _normalize_dev_workspace_lookup_text(value)
        if normalized and (q in normalized or normalized in q):
            return True
    return False


def register(
    mcp,
    resolve_identity: Callable[[int | None, int | None], tuple[int, int]],
    resolve_workspace_path: Callable,
    api_call: Callable,
) -> dict[str, object]:
    """Register workspace file/search/status tools on the shared FastMCP instance."""
    marker = id(mcp)
    if marker in _registered_tools_by_mcp:
        return _registered_tools_by_mcp[marker]

    @mcp.tool()
    async def list_dev_workspaces(
        app_id: int = 0,
        query: str = "",
        include_unbound: bool = True,
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """列当前用户可访问的自开发 workspace，支持按应用和页面/包名反查 ws_id。"""
        tid, uid = resolve_identity(tenant_id, user_id)
        from app.coding.workspace import WorkspaceManager

        project_ids = [int(app_id)] if app_id else None
        rows = WorkspaceManager().list_accessible_workspaces(uid, project_ids, tenant_id=tid)
        out: list[dict[str, Any]] = []
        for ws in rows:
            if not isinstance(ws, dict):
                continue
            project_id = ws.get("project_id")
            if app_id:
                if project_id not in (None, "") and str(project_id) != str(app_id):
                    continue
                if project_id in (None, "") and not include_unbound:
                    continue
            if query and not _dev_workspace_matches_query(ws, query):
                continue
            binding_status = (
                "bound"
                if app_id and str(project_id or "") == str(app_id)
                else "unbound_candidate"
                if project_id in (None, "")
                else "project_bound"
            )
            out.append({
                "ws_id": _as_nonempty_str(ws.get("id") or ws.get("ws_id")),
                "project_id": project_id,
                "binding_status": binding_status,
                "project_type": ws.get("project_type"),
                "project_name": ws.get("project_name"),
                "display_name": ws.get("display_name") or ws.get("project_name"),
                "status": ws.get("status"),
                "tenant_id": ws.get("tenant_id"),
                "user_id": ws.get("user_id"),
                "lookup_values": sorted(_dev_workspace_lookup_values(ws))[:12],
            })

        out.sort(key=lambda item: (item["binding_status"] != "bound", item.get("display_name") or ""))
        return {
            "ok": True,
            "app_id": app_id or None,
            "query": query,
            "count": len(out),
            "workspaces": out[:20],
            "next_steps": [
                "用 get_dev_workspace_status(ws_id) 查看工作区状态",
                "用 glob_workspace / grep_workspace / read_workspace_file 读取源码",
                "确认是当前应用资产后，可用 bind_workspace_app 或前端入口补绑定",
            ],
        }

    @mcp.tool()
    async def read_workspace_file(ws_id: str, file_path: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """读取 workspace 内某个文件。"""
        if not file_path:
            return {"ok": False, "error_code": "INVALID_FILE_PATH", "message": "file_path 不能为空"}
        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err
        from app.coding.tools import _read_file

        text = await _read_file({"file_path": file_path}, ws_path)
        if isinstance(text, str) and text.startswith("Error:"):
            return {"ok": False, "error_code": "FILE_READ_ERROR", "message": text}
        truncated = "(truncated," in (text or "")
        return {"ok": True, "ws_id": ws_id, "file_path": file_path, "content": text or "", "truncated": truncated}

    @mcp.tool()
    async def write_workspace_files(ws_id: str, files: list[dict], tenant_id: int = 0, user_id: int = 0) -> dict:
        """批量写入多个文件到 workspace。"""
        if not files:
            return {"ok": False, "error_code": "EMPTY_FILES", "message": "files 不能为空"}
        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err
        from app.coding.tools import _write_file

        results = []
        failed = 0
        for f in files:
            if not isinstance(f, dict):
                results.append({"file_path": str(f), "ok": False, "error": "not a dict"})
                failed += 1
                continue
            fp = f.get("file_path") or ""
            content = f.get("content", "")
            if not fp:
                results.append({"ok": False, "error": "file_path 缺失"})
                failed += 1
                continue
            text = await _write_file({"file_path": fp, "content": content}, ws_path)
            ok = not (isinstance(text, str) and text.startswith("Error:"))
            results.append({"file_path": fp, "ok": ok, "result": text if not ok else "written"})
            if not ok:
                failed += 1
        return {
            "ok": failed == 0,
            "ws_id": ws_id,
            "total": len(files),
            "succeeded": len(files) - failed,
            "failed": failed,
            "results": results,
        }

    @mcp.tool()
    async def edit_workspace_files(ws_id: str, edits: list[dict], tenant_id: int = 0, user_id: int = 0) -> dict:
        """批量对多个文件做精确字符串替换。"""
        if not edits:
            return {"ok": False, "error_code": "EMPTY_EDITS", "message": "edits 不能为空"}
        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err
        from app.coding.tools import _edit_file

        results = []
        failed = 0
        for e in edits:
            if not isinstance(e, dict):
                results.append({"ok": False, "error": "not a dict"})
                failed += 1
                continue
            text = await _edit_file(e, ws_path)
            ok = not (isinstance(text, str) and text.startswith("Error:"))
            results.append({"file_path": e.get("file_path"), "ok": ok, "result": text})
            if not ok:
                failed += 1
        return {
            "ok": failed == 0,
            "ws_id": ws_id,
            "total": len(edits),
            "succeeded": len(edits) - failed,
            "failed": failed,
            "results": results,
        }

    @mcp.tool()
    async def glob_workspace(ws_id: str, pattern: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """按 glob pattern 列工作区文件。"""
        if not pattern:
            return {"ok": False, "error_code": "INVALID_PATTERN", "message": "pattern 不能为空"}
        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err
        from app.coding.tools import _glob_files

        result = await _glob_files({"pattern": pattern}, ws_path)
        if isinstance(result, str) and result.startswith("Error:"):
            return {"ok": False, "error_code": "GLOB_FAILED", "message": result}
        return {"ok": True, "ws_id": ws_id, "pattern": pattern, "result": result}

    @mcp.tool()
    async def grep_workspace(
        ws_id: str,
        pattern: str,
        file_pattern: str = "",
        tenant_id: int = 0,
        user_id: int = 0,
    ) -> dict:
        """在工作区内 grep 正则搜索。"""
        if not pattern:
            return {"ok": False, "error_code": "INVALID_PATTERN", "message": "pattern 不能为空"}
        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err
        from app.coding.tools import _grep_search

        args = {"pattern": pattern}
        if file_pattern:
            args["file_pattern"] = file_pattern
        result = await _grep_search(args, ws_path)
        if isinstance(result, str) and result.startswith("Error:"):
            return {"ok": False, "error_code": "GREP_FAILED", "message": result}
        return {"ok": True, "ws_id": ws_id, "pattern": pattern, "result": result}

    @mcp.tool()
    async def run_workspace_command(ws_id: str, command: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """在 workspace 根目录跑 shell 命令。"""
        if not command:
            return {"ok": False, "error_code": "INVALID_COMMAND", "message": "command 不能为空"}
        tid, uid = resolve_identity(tenant_id, user_id)
        ws_path, err = resolve_workspace_path(ws_id, tid, uid)
        if err:
            return err
        from app.coding.tools import _run_command

        text = await _run_command({"command": command}, ws_path, None)
        if isinstance(text, str) and text.startswith("Error:"):
            return {"ok": False, "error_code": "COMMAND_FAILED", "message": text}
        return {"ok": True, "ws_id": ws_id, "command": command, "output": text}

    @mcp.tool()
    async def get_dev_workspace_status(ws_id: str, tenant_id: int = 0, user_id: int = 0) -> dict:
        """查询自开发 workspace 的当前状态。"""
        tid, uid = resolve_identity(tenant_id, user_id)
        res = await api_call("GET", f"/coding/workspace/{ws_id}", tenant_id=tid, user_id=uid)
        return res if isinstance(res, dict) else {"ok": False, "raw": res}

    tools = {
        "list_dev_workspaces": list_dev_workspaces,
        "read_workspace_file": read_workspace_file,
        "write_workspace_files": write_workspace_files,
        "edit_workspace_files": edit_workspace_files,
        "glob_workspace": glob_workspace,
        "grep_workspace": grep_workspace,
        "run_workspace_command": run_workspace_command,
        "get_dev_workspace_status": get_dev_workspace_status,
    }
    _registered_tools_by_mcp[marker] = tools
    return tools
