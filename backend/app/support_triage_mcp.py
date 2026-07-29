"""Dedicated standard MCP service for external support triage agents."""
from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app import runtime
from app.support_triage_records import write_support_triage_record


_allowed_hosts = [h.strip() for h in (os.getenv("MCP_ALLOWED_HOSTS") or "").split(",") if h.strip()]
if _allowed_hosts:
    _security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
    )
else:
    _security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP(
    "support-triage",
    instructions=(
        "问题分诊记录 MCP。外部问题助手先判断用户问题属于操作问题、Bug、需求或待确认，"
        "再调用 record_support_triage 记录分类、原因、优先级和准备回复给用户的话。"
        "需要处理代码材料时，可使用代码仓库工具拉取、列目录、读写文件、提交并推送。"
    ),
    transport_security=_security,
    stateless_http=True,
    json_response=True,
)


_DEFAULT_REPO_BASE = Path(__file__).resolve().parents[2]
_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
}


def _repo_base_dirs() -> list[Path]:
    raw = os.getenv("MCP_CODE_REPO_BASE_DIRS") or os.getenv("MCP_CODE_REPO_BASE_DIR") or ""
    dirs = [p.strip() for p in raw.split(",") if p.strip()]
    if not dirs:
        dirs = [str(_DEFAULT_REPO_BASE)]
    return [Path(p).expanduser().resolve() for p in dirs]


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _resolve_allowed_path(path: str, *, must_be_repo: bool = False) -> Path:
    if not path or not str(path).strip():
        raise ValueError("repo_path 不能为空")
    raw = Path(str(path).strip()).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (_repo_base_dirs()[0] / raw).resolve()
    if not any(_is_relative_to(candidate, base) for base in _repo_base_dirs()):
        bases = ", ".join(str(p) for p in _repo_base_dirs())
        raise ValueError(f"路径不在允许的代码仓库目录内: {candidate}; allowed={bases}")
    if must_be_repo and not (candidate / ".git").exists():
        raise ValueError(f"不是 Git 仓库目录: {candidate}")
    return candidate


def _resolve_repo_file(repo: Path, file_path: str) -> Path:
    if not file_path or not str(file_path).strip():
        raise ValueError("path 不能为空")
    rel = Path(str(file_path).strip())
    if rel.is_absolute():
        raise ValueError("path 必须是相对仓库根目录的路径")
    target = (repo / rel).resolve()
    if not _is_relative_to(target, repo):
        raise ValueError(f"path 越界: {file_path}")
    if ".git" in target.relative_to(repo).parts:
        raise ValueError("不允许读写 .git 目录")
    return target


async def _run_git(repo: Path, args: list[str], *, timeout: float = 120.0) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **runtime.subprocess_window_kwargs(),
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "ok": False,
            "error_code": "GIT_TIMEOUT",
            "message": f"git {' '.join(args)} 超时",
        }
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "command": ["git", "-C", str(repo), *args],
    }


async def _current_branch(repo: Path) -> str:
    result = await _run_git(repo, ["branch", "--show-current"], timeout=30.0)
    return (result.get("stdout") or "").strip()


def _tree_items(root: Path, start: Path, *, max_depth: int, include_hidden: bool, limit: int) -> list[dict]:
    items: list[dict] = []
    for current, dirs, files in os.walk(start):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root)
        depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
        dirs[:] = sorted(
            d for d in dirs
            if (include_hidden or not d.startswith("."))
            and d not in _IGNORED_DIRS
            and depth < max_depth
        )
        names = [(d, "dir") for d in dirs] + [(f, "file") for f in sorted(files)]
        for name, kind in names:
            if not include_hidden and name.startswith("."):
                continue
            path = current_path / name
            rel = path.relative_to(root).as_posix()
            items.append({
                "path": rel,
                "type": kind,
                "size": path.stat().st_size if kind == "file" else None,
            })
            if len(items) >= limit:
                return items
    return items


def _search_files(root: Path, *, query: str, glob: str, limit: int) -> list[dict]:
    query_lower = (query or "").lower()
    results: list[dict] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORED_DIRS and not d.startswith("."))
        for name in sorted(files):
            path = Path(current) / name
            rel = path.relative_to(root).as_posix()
            if glob and not fnmatch.fnmatch(rel, glob):
                continue
            if query_lower and query_lower not in rel.lower():
                continue
            results.append({"path": rel, "size": path.stat().st_size})
            if len(results) >= limit:
                return results
    return results


@mcp.tool()
async def record_support_triage(
    user_question: str,
    category: str,
    summary: str,
    reason: str,
    user_reply: str,
    confidence: str = "中",
    missing_info: str = "",
    priority: str = "P2",
    status: str = "新建",
    source: str = "external_agent",
    tenant_id: int = 0,
    user_id: int = 0,
) -> dict:
    """记录用户问题分诊结果。

    category 取值：操作问题 / Bug / 需求 / 待确认。
    本工具只记录分类、判断原因和给用户的回复，不会创建工单、改代码或部署。
    """
    return write_support_triage_record(
        user_question=user_question,
        category=category,
        summary=summary,
        reason=reason,
        user_reply=user_reply,
        confidence=confidence,
        missing_info=missing_info,
        priority=priority,
        status=status,
        source=source,
        tenant_id=tenant_id,
        user_id=user_id,
    )


@mcp.tool()
async def pull_repository(
    repo_path: str,
    remote: str = "origin",
    branch: str = "",
    ff_only: bool = True,
) -> dict:
    """拉取本地 Git 仓库更新。

    不接收 token；认证由仓库 remote、SSH key、Git credential helper 或运行环境负责。
    """
    try:
        repo = _resolve_allowed_path(repo_path, must_be_repo=True)
        args = ["pull"]
        if ff_only:
            args.append("--ff-only")
        if remote:
            args.append(remote)
        if branch:
            args.append(branch)
        result = await _run_git(repo, args, timeout=180.0)
        return {"ok": bool(result.get("ok")), "repo_path": str(repo), **result}
    except Exception as exc:
        return {"ok": False, "error_code": "PULL_REPOSITORY_FAILED", "message": str(exc)}


@mcp.tool()
async def list_repository_tree(
    repo_path: str,
    path: str = "",
    max_depth: int = 2,
    include_hidden: bool = False,
    limit: int = 500,
) -> dict:
    """列出仓库目录树，用于识别材料文件和页面文件。"""
    try:
        repo = _resolve_allowed_path(repo_path, must_be_repo=True)
        start = _resolve_repo_file(repo, path) if path else repo
        if not start.exists():
            return {"ok": False, "error_code": "PATH_NOT_FOUND", "message": f"路径不存在: {path}"}
        if not start.is_dir():
            return {"ok": False, "error_code": "PATH_NOT_DIRECTORY", "message": f"不是目录: {path}"}
        depth = max(0, min(int(max_depth), 10))
        capped_limit = max(1, min(int(limit), 5000))
        return {
            "ok": True,
            "repo_path": str(repo),
            "path": path or ".",
            "items": _tree_items(repo, start, max_depth=depth, include_hidden=include_hidden, limit=capped_limit),
        }
    except Exception as exc:
        return {"ok": False, "error_code": "LIST_REPOSITORY_TREE_FAILED", "message": str(exc)}


@mcp.tool()
async def search_repository_files(
    repo_path: str,
    query: str = "",
    glob: str = "",
    limit: int = 200,
) -> dict:
    """按文件名路径搜索仓库文件。query 做路径子串匹配，glob 支持如 **/*.html。"""
    try:
        repo = _resolve_allowed_path(repo_path, must_be_repo=True)
        capped_limit = max(1, min(int(limit), 2000))
        return {
            "ok": True,
            "repo_path": str(repo),
            "query": query,
            "glob": glob,
            "files": _search_files(repo, query=query, glob=glob, limit=capped_limit),
        }
    except Exception as exc:
        return {"ok": False, "error_code": "SEARCH_REPOSITORY_FILES_FAILED", "message": str(exc)}


@mcp.tool()
async def get_file(
    repo_path: str,
    path: str,
    ref: str = "",
    max_bytes: int = 200000,
) -> dict:
    """读取仓库文件内容。ref 为空读工作区文件；ref 非空时读指定 branch/tag/commit。"""
    try:
        repo = _resolve_allowed_path(repo_path, must_be_repo=True)
        capped = max(1, min(int(max_bytes), 1000000))
        if ref:
            result = await _run_git(repo, ["show", f"{ref}:{path}"], timeout=60.0)
            if not result.get("ok"):
                return {"ok": False, "error_code": "GIT_SHOW_FAILED", "repo_path": str(repo), **result}
            content = (result.get("stdout") or "")[:capped]
            return {"ok": True, "repo_path": str(repo), "path": path, "ref": ref, "content": content}
        target = _resolve_repo_file(repo, path)
        if not target.exists() or not target.is_file():
            return {"ok": False, "error_code": "FILE_NOT_FOUND", "message": f"文件不存在: {path}"}
        data = target.read_bytes()
        truncated = len(data) > capped
        content = data[:capped].decode("utf-8", errors="replace")
        return {
            "ok": True,
            "repo_path": str(repo),
            "path": path,
            "content": content,
            "truncated": truncated,
            "bytes": len(data),
        }
    except Exception as exc:
        return {"ok": False, "error_code": "GET_FILE_FAILED", "message": str(exc)}


@mcp.tool()
async def create_or_update_file(
    repo_path: str,
    path: str,
    content: str,
) -> dict:
    """新增或覆盖仓库文本文件，例如 materials.html 或 index.html。"""
    try:
        repo = _resolve_allowed_path(repo_path, must_be_repo=True)
        target = _resolve_repo_file(repo, path)
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "repo_path": str(repo),
            "path": path,
            "created": not existed,
            "bytes": len(content.encode("utf-8")),
        }
    except Exception as exc:
        return {"ok": False, "error_code": "CREATE_OR_UPDATE_FILE_FAILED", "message": str(exc)}


@mcp.tool()
async def commit(
    repo_path: str,
    message: str,
    paths: list[str] | None = None,
) -> dict:
    """提交仓库变更。paths 为空时提交全部已修改/新增文件。"""
    try:
        repo = _resolve_allowed_path(repo_path, must_be_repo=True)
        if not message.strip():
            return {"ok": False, "error_code": "EMPTY_COMMIT_MESSAGE", "message": "commit message 不能为空"}
        add_args = ["add"]
        if paths:
            for item in paths:
                _resolve_repo_file(repo, item)
            add_args.extend(["--", *paths])
        else:
            add_args.append("-A")
        add_result = await _run_git(repo, add_args, timeout=60.0)
        if not add_result.get("ok"):
            return {"ok": False, "error_code": "GIT_ADD_FAILED", "repo_path": str(repo), **add_result}
        diff_result = await _run_git(repo, ["diff", "--cached", "--quiet"], timeout=30.0)
        if diff_result.get("returncode") == 0:
            return {"ok": False, "error_code": "NO_STAGED_CHANGES", "message": "没有可提交的变更", "repo_path": str(repo)}
        result = await _run_git(repo, ["commit", "-m", message], timeout=120.0)
        branch = await _current_branch(repo)
        return {"ok": bool(result.get("ok")), "repo_path": str(repo), "branch": branch, **result}
    except Exception as exc:
        return {"ok": False, "error_code": "COMMIT_FAILED", "message": str(exc)}


@mcp.tool()
async def push(
    repo_path: str,
    remote: str = "origin",
    branch: str = "",
    set_upstream: bool = False,
) -> dict:
    """推送当前仓库分支。认证由本地 Git 凭据负责，不在工具参数里传 token。"""
    try:
        repo = _resolve_allowed_path(repo_path, must_be_repo=True)
        target_branch = branch.strip() or await _current_branch(repo)
        args = ["push"]
        if set_upstream:
            args.append("-u")
        args.append(remote or "origin")
        if target_branch:
            args.append(target_branch)
        result = await _run_git(repo, args, timeout=180.0)
        return {"ok": bool(result.get("ok")), "repo_path": str(repo), "branch": target_branch, **result}
    except Exception as exc:
        return {"ok": False, "error_code": "PUSH_FAILED", "message": str(exc)}
