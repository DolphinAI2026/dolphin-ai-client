"""
Vibe Coding API - full-code workspace control plane.

This module may import a Git repository into an isolated workspace directory,
but it intentionally does not install dependencies or execute repository code.
Those actions belong to the sandbox/agent execution stage.
"""

import asyncio
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.coding.workspace import WORKSPACE_ROOT
from app.database import get_db
from app.deps import AuthContext, get_auth_context
from app.routes.coding import (
    _align_local_code_server_base_url,
    _build_ide_proxy_api_base,
    _create_ide_access_token,
    _derive_harness_api_base,
    _get_default_coding_model_id,
    _verify_ide_access_token,
    _write_ruijing_extension_config,
)

router = APIRouter(prefix="/online-coding", tags=["online-coding"])

ONLINE_CODING_ROOT = Path(
    os.environ.get("APAAS_ONLINE_CODING_ROOT")
    or (WORKSPACE_ROOT / "_online_coding")
)


class OnlineCodingCreateRequest(BaseModel):
    repo_url: Optional[str] = Field(default=None, max_length=2000)
    task: Optional[str] = Field(default=None, max_length=8000)
    git_username: Optional[str] = Field(default=None, max_length=256)
    git_token: Optional[str] = Field(default=None, max_length=4096)


class OnlineCodingImportRequest(BaseModel):
    repo_url: Optional[str] = Field(default=None, max_length=2000)
    task: Optional[str] = Field(default=None, max_length=8000)
    git_username: Optional[str] = Field(default=None, max_length=256)
    git_token: Optional[str] = Field(default=None, max_length=4096)


class OnlineCodingWorkspace(BaseModel):
    id: str
    repo_url: Optional[str]
    task: str
    user_id: int
    status: str
    sandbox_status: str
    created_at: str
    updated_at: str
    next_steps: list[str]
    imported_at: Optional[str] = None
    branch: Optional[str] = None
    file_count: int = 0
    files: list[str] = []
    import_error: Optional[str] = None
    spec_draft: Optional[str] = None
    spec_confirmed: bool = False


class OnlineCodingSpecUpdateRequest(BaseModel):
    task: Optional[str] = Field(default=None, max_length=8000)
    spec_draft: Optional[str] = Field(default=None, max_length=120_000)
    spec_confirmed: Optional[bool] = None


class OnlineCodingFileContent(BaseModel):
    path: str
    content: str
    truncated: bool = False


EXCLUDED_REPO_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".next",
    ".nuxt",
    ".turbo",
}

MAX_FILE_PREVIEW = 80
MAX_FILE_READ_BYTES = 300_000
MAX_IDE_CONTEXT_FILES = 18
MAX_IDE_CONTEXT_FILE_CHARS = 5000
MAX_IDE_CONTEXT_TOTAL_CHARS = 52_000
MAX_IDE_CONTEXT_FILE_INDEX = 220
EMPTY_REPO_IMPORT_ERROR = (
    "仓库导入成功，但默认分支没有任何可读取文件。"
    "请确认仓库不是空仓库，或先推送代码到默认分支后重新导入。"
)
EMPTY_REPO_READY_MESSAGE = (
    "空仓库已接入，可以直接打开 IDE，从 0 到 1 初始化项目。"
)

SOURCE_FILE_RE = re.compile(
    r"\.(vue|js|jsx|ts|tsx|json|py|java|go|rs|xml|yml|yaml|toml|ini|properties|scss|css|less|html|md)$",
    re.IGNORECASE,
)
OVERVIEW_TASK_RE = re.compile(
    r"(完整代码|整体代码|全部代码|读代码|读取代码|看代码|分析代码|工程代码|项目代码|仓库代码|工作区.*代码|读一下.*代码|看一下.*代码|项目结构|仓库结构|代码结构|架构|梳理|overview|architecture|review)",
    re.IGNORECASE,
)
INSPECT_TASK_RE = re.compile(
    r"(检查|排查|看看|看一下|看一看|存不存在|缺失|缺少|不存在|有没有|是否存在|注册|入口|导入|导出|import|export|index\.js)",
    re.IGNORECASE,
)
MENTIONED_PATH_RE = re.compile(r"[A-Za-z0-9_.\-/]+\.[A-Za-z0-9]{1,8}")


async def _ensure_local_code_server_available(base_url: str) -> None:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip().lower()
    if host not in {"127.0.0.1", "localhost"}:
        return
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=0.8)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    except Exception:
        raise HTTPException(status_code=503, detail="Web IDE 服务不可用，请先启动 code-server")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace_slug(repo_url: Optional[str], task: str) -> str:
    source = (repo_url or task or "full-code-workspace").strip()
    source = source.rstrip("/").split("/")[-1]
    source = re.sub(r"\.git$", "", source, flags=re.IGNORECASE)
    source = re.sub(r"[^a-zA-Z0-9._-]+", "-", source).strip("-._")
    return (source or "full-code-workspace")[:48]


def _tenant_root(tenant_id: int) -> Path:
    """返回租户专属的 workspace 根目录。"""
    return ONLINE_CODING_ROOT / str(int(tenant_id))


def _workspace_dir(workspace_id: str, tenant_id: int, repo_url: Optional[str], task: str) -> Path:
    """新建 workspace 路径：始终走 {root}/{tenant_id}/{slug}__{ws_id}（租户隔离）。"""
    return _tenant_root(tenant_id) / f"{_workspace_slug(repo_url, task)}__{workspace_id}"


def _meta_path(ws_dir: Path) -> Path:
    return ws_dir / ".online-coding.json"


def _repo_path(ws_dir: Path) -> Path:
    return ws_dir / "repo"


def _iter_workspace_meta_dirs():
    """遍历所有合法的 workspace 目录。

    优先扫新路径 {root}/{tenant_id}/<ws_dir>（tenant_id 为纯数字目录名），
    回退兼容老路径 {root}/<ws_dir>（迁移脚本跑完后老路径应为空）。

    会跳过 `.preview-runtime` 等隐藏 / 非 workspace 目录。
    """
    if not ONLINE_CODING_ROOT.exists():
        return
    for entry in ONLINE_CODING_ROOT.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        # 新路径：tenant 子目录（数字）下的 ws
        if entry.name.isdigit():
            for ws_dir in entry.iterdir():
                if ws_dir.is_dir() and _meta_path(ws_dir).exists():
                    yield ws_dir
            continue
        # 老路径：直接挂在 root 下的 ws（待迁移）
        if _meta_path(entry).exists():
            yield entry


def _resolve_repo_file(repo_dir: Path, file_path: str) -> Path:
    clean_path = file_path.strip().replace("\\", "/")
    if not clean_path or clean_path.startswith("/") or "\x00" in clean_path:
        raise HTTPException(status_code=400, detail="文件路径不合法")
    if any(part in {"", ".", ".."} for part in clean_path.split("/")):
        raise HTTPException(status_code=400, detail="文件路径不合法")

    root = repo_dir.resolve()
    target = (repo_dir / clean_path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="文件路径越界")
    if ".git" in target.relative_to(root).parts:
        raise HTTPException(status_code=400, detail="不能读取 Git 内部文件")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return target


def _verify_online_ide_access(
    workspace_id: str,
    meta: dict,
    ide_token: Optional[str],
) -> dict:
    if not ide_token:
        raise HTTPException(status_code=401, detail="缺少 IDE 访问令牌，请重新从 Builder 打开 Web IDE")

    payload = _verify_ide_access_token(ide_token, workspace_id)
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="无效的 IDE 访问令牌")

    if int(meta.get("user_id") or 0) != user_id:
        raise HTTPException(status_code=403, detail="IDE 访问令牌与当前工作区用户不匹配")

    token_tenant = payload.get("tid")
    meta_tenant = meta.get("tenant_id")
    if token_tenant is not None and meta_tenant is not None and int(token_tenant) != int(meta_tenant):
        raise HTTPException(status_code=403, detail="IDE 访问令牌与当前租户不匹配")

    return payload


def _list_repo_files(repo_dir: Path, max_files: int = 800) -> list[str]:
    files: list[str] = []
    if not repo_dir.exists():
        return files

    for root, dirs, filenames in os.walk(repo_dir):
        dirs[:] = [
            dirname for dirname in dirs
            if dirname not in EXCLUDED_REPO_DIRS and not dirname.startswith(".git")
        ]
        root_path = Path(root)
        for filename in sorted(filenames):
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            rel_path = file_path.relative_to(repo_dir).as_posix()
            files.append(rel_path)
            if len(files) >= max_files:
                return files
    return files


def _extract_mentioned_paths(prompt: str) -> list[str]:
    result: list[str] = []
    for raw in MENTIONED_PATH_RE.findall(prompt or ""):
        normalized = raw.strip().replace("\\", "/").strip("./")
        if normalized and not normalized.startswith("http") and normalized not in result:
            result.append(normalized)
    return result[:12]


def _extract_search_terms(prompt: str) -> list[str]:
    terms: list[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", prompt or ""):
        lowered = raw.lower()
        if lowered in {"src", "file", "path", "code", "help", "this", "that"}:
            continue
        if lowered not in terms:
            terms.append(lowered)
    return terms[:10]


def _overview_files(files: list[str]) -> list[str]:
    priority = [
        "README.md",
        "ARCHITECTURE.md",
        "PROJECT_SUMMARY.md",
        "QUICKSTART.md",
        "package.json",
        "frontend/package.json",
        "backend/package.json",
        "pyproject.toml",
        "requirements.txt",
        "backend/requirements.txt",
        "vite.config.ts",
        "vite.config.js",
        "frontend/vite.config.ts",
        "frontend/vite.config.js",
        "frontend/src/main.ts",
        "frontend/src/main.tsx",
        "frontend/src/App.vue",
        "frontend/src/App.tsx",
        "frontend/src/router/index.ts",
        "backend/run.py",
        "backend/app/main.py",
        "src/main.ts",
        "src/main.tsx",
        "src/App.vue",
        "src/App.tsx",
        "main.py",
        "app.py",
    ]
    result: list[str] = []
    file_set = set(files)
    for rel in priority:
        if rel in file_set and rel not in result:
            result.append(rel)

    for rel in files:
        if len(result) >= MAX_IDE_CONTEXT_FILES:
            break
        if (
            SOURCE_FILE_RE.search(rel)
            and re.search(r"(^|/)(main|index|app|server|layout|page)\.", rel, re.IGNORECASE)
            and not re.search(r"(^|/)(dist|build|coverage|target|tmp|temp)/", rel)
            and rel not in result
        ):
            result.append(rel)

    return result[:MAX_IDE_CONTEXT_FILES]


def _score_repo_file(rel: str, terms: list[str]) -> int:
    lower = rel.lower()
    score = 0
    for term in terms:
        if lower == term:
            score += 220
        elif lower.endswith(f"/{term}"):
            score += 150
        elif term in lower:
            score += 80 if len(term) >= 8 else 40
    if lower.endswith(("package.json", "readme.md", "main.ts", "main.py", "app.vue", "app.py")):
        score += 30
    return score


def _choose_context_files(files: list[str], prompt: str) -> list[str]:
    selected: list[str] = []

    def add(rel: str) -> None:
        if rel and rel in files and rel not in selected:
            selected.append(rel)

    for mentioned in _extract_mentioned_paths(prompt):
        for rel in files:
            if rel == mentioned or rel.endswith(mentioned) or mentioned in rel:
                add(rel)
                if len(selected) >= MAX_IDE_CONTEXT_FILES:
                    return selected

    terms = _extract_search_terms(prompt)
    if terms:
        scored = [
            (rel, _score_repo_file(rel, terms))
            for rel in files
            if SOURCE_FILE_RE.search(rel)
        ]
        for rel, score in sorted(scored, key=lambda item: (-item[1], item[0])):
            if score <= 0:
                break
            add(rel)
            if len(selected) >= 10:
                break

    if OVERVIEW_TASK_RE.search(prompt or "") or INSPECT_TASK_RE.search(prompt or "") or not selected:
        for rel in _overview_files(files):
            add(rel)
            if len(selected) >= MAX_IDE_CONTEXT_FILES:
                break

    return selected[:MAX_IDE_CONTEXT_FILES]


def _build_ide_workspace_context(repo_dir: Path, prompt: str) -> dict:
    files = _list_repo_files(repo_dir)
    if not files:
        return {
            "context": "\n".join([
                "EMPTY_REPO: true",
                "当前 Git 仓库没有业务文件。请把它当作 0-1 新项目，先根据用户目标创建项目结构、README 和首版代码。",
                f"USER_GOAL: {prompt.strip() or '用户尚未补充具体开发目标'}",
            ]),
            "read_files": [],
            "file_count": 0,
        }
    selected = _choose_context_files(files, prompt)
    excerpts: list[str] = []
    read_files: list[str] = []
    total_len = 0

    for rel in selected:
        if total_len >= MAX_IDE_CONTEXT_TOTAL_CHARS:
            break
        try:
            target = _resolve_repo_file(repo_dir, rel)
            raw = target.read_bytes()
        except Exception:
            continue

        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        if len(content) > MAX_IDE_CONTEXT_FILE_CHARS:
            content = content[:MAX_IDE_CONTEXT_FILE_CHARS] + "\n/* ... truncated ... */"
        excerpts.append(f"### {rel}\n```\n{content}\n```")
        read_files.append(rel)
        total_len += len(content)

    search_terms = _extract_search_terms(prompt)
    file_index = "\n".join(files[:MAX_IDE_CONTEXT_FILE_INDEX])
    context_parts = [
        f"SEARCH_TERMS:\n{', '.join(search_terms)}\n" if search_terms else "",
        f"READ_FILES:\n{chr(10).join(read_files)}\n" if read_files else "",
        f"RELEVANT_FILE_CONTENTS:\n{chr(10).join(excerpts)}",
        f"WORKSPACE_FILE_INDEX({len(files)}):\n{file_index}",
    ]
    return {
        "context": "\n\n".join(part for part in context_parts if part),
        "read_files": read_files,
        "file_count": len(files),
    }


def _read_workspace(ws_dir: Path) -> dict:
    try:
        return json.loads(_meta_path(ws_dir).read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=404, detail="Vibe Coding 工作区不存在")


def _write_workspace(ws_dir: Path, meta: dict) -> None:
    ws_dir.mkdir(parents=True, exist_ok=True)
    _meta_path(ws_dir).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = ws_dir / "README.md"
    readme.write_text(
        "\n".join([
            "# Vibe Coding Workspace",
            "",
            f"- Workspace ID: `{meta['id']}`",
            f"- Repo URL: `{meta.get('repo_url') or '未填写'}`",
            f"- Status: `{meta['status']}`",
            f"- Sandbox: `{meta['sandbox_status']}`",
            f"- Imported files: `{meta.get('file_count') or 0}`",
            "",
            "## Task",
            "",
            meta.get("task") or "未填写开发任务",
            "",
            "## Next",
            "",
            "当前阶段只导入代码并登记控制面数据，不自动安装依赖或执行仓库代码。接入云沙箱后，这个工作区会继续完成依赖安装、预览、测试和 PR 生成。",
            "",
        ]),
        encoding="utf-8",
    )


def _validate_repo_url(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=400, detail="当前只支持 HTTPS Git 仓库地址")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="仓库地址不能包含用户名、密码或 token")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost"} or hostname.endswith(".local"):
        raise HTTPException(status_code=400, detail="不允许导入本机或内网仓库地址")
    if "." not in hostname:
        raise HTTPException(status_code=400, detail="Git 仓库地址域名不合法")
    if not parsed.path or parsed.path == "/":
        raise HTTPException(status_code=400, detail="Git 仓库地址缺少项目路径")
    return repo_url


def _summarize_repo(repo_dir: Path) -> tuple[int, list[str]]:
    file_count = 0
    preview: list[str] = []
    if not repo_dir.exists():
        return file_count, preview

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [
            dirname for dirname in dirs
            if dirname not in EXCLUDED_REPO_DIRS and not dirname.startswith(".git")
        ]
        root_path = Path(root)
        for filename in sorted(files):
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue
            rel_path = file_path.relative_to(repo_dir).as_posix()
            file_count += 1
            if len(preview) < MAX_FILE_PREVIEW:
                preview.append(rel_path)
    return file_count, preview


def _workspace_file_count(meta: dict) -> int:
    try:
        file_count = int(meta.get("file_count") or 0)
    except (TypeError, ValueError):
        file_count = 0
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    return max(file_count, len(files))


def _mark_empty_repo_import(meta: dict, *, branch: Optional[str] = None) -> dict:
    meta.update({
        "status": "repo_imported",
        "sandbox_status": "repo_ready",
        "branch": branch or meta.get("branch") or None,
        "file_count": 0,
        "files": [],
        "imported_at": meta.get("imported_at") or _now_iso(),
        "import_error": None,
        "updated_at": _now_iso(),
    })
    return meta


def _is_legacy_empty_repo_import(meta: dict) -> bool:
    return (
        meta.get("status") == "import_failed"
        and str(meta.get("import_error") or "").strip() == EMPTY_REPO_IMPORT_ERROR
    )


def _is_repo_imported(meta: dict) -> bool:
    return meta.get("status") == "repo_imported" or _is_legacy_empty_repo_import(meta)


def _friendly_git_error(error_text: str) -> str:
    normalized = error_text.strip()
    lower = normalized.lower()
    if (
        "could not read username" in lower
        or "authentication failed" in lower
        or "repository not found" in lower
        or "http basic: access denied" in lower
        or "authentication required" in lower
    ):
        return "仓库需要登录、地址不存在或当前账号无权限。公开 HTTPS 仓库可直接导入；私有仓库请使用 GitHub/GitLab Token 授权后重新导入。"
    if "terminal prompts disabled" in lower:
        return "仓库导入需要交互式认证。当前导入流程不会读取本机凭据；请使用公开仓库，或填写 Git Token 后重新导入。"
    if "could not resolve host" in lower or "failed to connect" in lower:
        return "无法连接 Git 服务，请检查网络和仓库域名。"
    return normalized or "Git 仓库导入失败"


def _git_auth_from_request(username: Optional[str], token: Optional[str]) -> Optional[dict[str, str]]:
    clean_token = (token or "").strip()
    if not clean_token:
        return None
    clean_username = (username or "").strip() or "x-access-token"
    return {"username": clean_username, "token": clean_token}


def _write_askpass_script(cwd: Path) -> Path:
    script = cwd / ".git-home" / "online-coding-askpass.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "\n".join([
            "#!/bin/sh",
            "case \"$1\" in",
            "  *Username*|*username*) printf '%s' \"${ONLINE_CODING_GIT_USERNAME:-x-access-token}\" ;;",
            "  *Password*|*password*) printf '%s' \"$ONLINE_CODING_GIT_TOKEN\" ;;",
            "  *) printf '%s' \"$ONLINE_CODING_GIT_TOKEN\" ;;",
            "esac",
            "",
        ]),
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script


async def _run_command(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 180,
    git_auth: Optional[dict[str, str]] = None,
) -> tuple[int, str, str]:
    env = os.environ.copy()
    git_home = cwd / ".git-home"
    git_home.mkdir(parents=True, exist_ok=True)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": str(git_home),
    })
    if git_auth:
        env["ONLINE_CODING_GIT_USERNAME"] = git_auth["username"]
        env["ONLINE_CODING_GIT_TOKEN"] = git_auth["token"]
        env["GIT_ASKPASS"] = str(_write_askpass_script(cwd))
    else:
        env["GIT_ASKPASS"] = "false"
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return 124, "", "Git 仓库导入超时"
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


async def _detect_repo_branch(git_bin: str, ws_dir: Path, repo_dir: Path) -> Optional[str]:
    branch_code, branch_stdout, _ = await _run_command(
        [git_bin, "-C", str(repo_dir), "branch", "--show-current"],
        cwd=ws_dir,
        timeout=15,
    )
    if branch_code == 0 and branch_stdout.strip():
        return branch_stdout.strip()
    return None


async def _detect_repo_origin(git_bin: str, ws_dir: Path, repo_dir: Path) -> Optional[str]:
    origin_code, origin_stdout, _ = await _run_command(
        [git_bin, "-C", str(repo_dir), "remote", "get-url", "origin"],
        cwd=ws_dir,
        timeout=15,
    )
    if origin_code == 0 and origin_stdout.strip():
        return origin_stdout.strip()
    return None


def _same_repo_url(left: Optional[str], right: Optional[str]) -> bool:
    def normalize(value: Optional[str]) -> str:
        normalized = (value or "").strip().rstrip("/")
        if normalized.endswith(".git"):
            normalized = normalized[:-4]
        return normalized

    return bool(normalize(left) and normalize(left) == normalize(right))


async def _import_repository(
    ws_dir: Path,
    meta: dict,
    *,
    git_auth: Optional[dict[str, str]] = None,
) -> dict:
    repo_url = _validate_repo_url(str(meta.get("repo_url") or "").strip())
    git_bin = shutil.which("git")
    if not git_bin:
        meta.update({
            "status": "import_failed",
            "sandbox_status": "not_configured",
            "import_error": "当前环境未安装 git，无法导入仓库",
            "updated_at": _now_iso(),
        })
        _write_workspace(ws_dir, meta)
        return meta

    repo_dir = _repo_path(ws_dir)
    meta.update({
        "status": "repo_importing",
        "sandbox_status": "importing",
        "import_error": None,
        "updated_at": _now_iso(),
    })
    _write_workspace(ws_dir, meta)

    if repo_dir.exists():
        if (repo_dir / ".git").exists():
            branch = await _detect_repo_branch(git_bin, ws_dir, repo_dir)
            origin = await _detect_repo_origin(git_bin, ws_dir, repo_dir)
            file_count, files = _summarize_repo(repo_dir)
            if _same_repo_url(origin, repo_url):
                if file_count <= 0:
                    _mark_empty_repo_import(meta, branch=branch)
                    _write_workspace(ws_dir, meta)
                    return meta
                meta.update({
                    "status": "repo_imported",
                    "sandbox_status": "repo_ready",
                    "branch": branch or meta.get("branch") or None,
                    "file_count": file_count,
                    "files": files,
                    "import_error": None,
                    "updated_at": _now_iso(),
                })
                _write_workspace(ws_dir, meta)
                return meta
        shutil.rmtree(repo_dir, ignore_errors=True)

    code, stdout, stderr = await _run_command(
        [
            git_bin,
            "-c", "credential.helper=",
            "-c", "core.hooksPath=/dev/null",
            "-c", "protocol.file.allow=never",
            "clone",
            "--depth", "1",
            "--no-tags",
            repo_url,
            str(repo_dir),
        ],
        cwd=ws_dir,
        git_auth=git_auth,
    )
    if code != 0:
        error_text = _friendly_git_error((stderr or stdout or "Git 仓库导入失败").strip()[-1200:])
        meta.update({
            "status": "import_failed",
            "sandbox_status": "not_configured",
            "import_error": error_text,
            "updated_at": _now_iso(),
        })
        _write_workspace(ws_dir, meta)
        return meta

    branch = await _detect_repo_branch(git_bin, ws_dir, repo_dir)
    file_count, files = _summarize_repo(repo_dir)
    if file_count <= 0:
        _mark_empty_repo_import(meta, branch=branch)
        _write_workspace(ws_dir, meta)
        return meta
    meta.update({
        "status": "repo_imported",
        "sandbox_status": "repo_ready",
        "branch": branch,
        "file_count": file_count,
        "files": files,
        "imported_at": _now_iso(),
        "updated_at": _now_iso(),
        "import_error": None,
    })
    _write_workspace(ws_dir, meta)
    return meta


def _find_workspace_dir(workspace_id: str) -> tuple[Path, dict]:
    ONLINE_CODING_ROOT.mkdir(parents=True, exist_ok=True)
    for ws_dir in _iter_workspace_meta_dirs():
        try:
            meta = _read_workspace(ws_dir)
        except HTTPException:
            continue
        if meta.get("id") == workspace_id:
            return ws_dir, meta
    raise HTTPException(status_code=404, detail="Vibe Coding 工作区不存在")


def _public_workspace(meta: dict) -> OnlineCodingWorkspace:
    status = meta.get("status") or "created"
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    file_count = _workspace_file_count(meta)
    import_error = meta.get("import_error") or None
    sandbox_status = meta.get("sandbox_status") or "not_configured"
    if _is_legacy_empty_repo_import(meta):
        status = "repo_imported"
        sandbox_status = "repo_ready"
        import_error = None
    if status == "repo_imported":
        if file_count <= 0:
            next_steps = [
                "打开 IDE 初始化首版工程",
                "让 AI 根据开发目标生成项目结构和代码",
                "生成首版后再提交并推送到默认分支",
            ]
        else:
            next_steps = [
                "打开 IDE 浏览仓库代码",
                "让 AI 分析仓库结构并生成开发计划",
                "确认后在沙箱里安装依赖、运行测试和生成 PR",
            ]
    elif status == "import_failed":
        next_steps = [
            "检查仓库地址和访问权限",
            "公开仓库可直接 HTTPS clone，私有仓库需要 Token 授权",
            "重新导入仓库",
        ]
    else:
        next_steps = [
            "导入 Git 仓库",
            "接入隔离云沙箱与资源限额",
            "接入 Agent 执行流、测试、预览和 PR",
        ]
    return OnlineCodingWorkspace(
        id=meta["id"],
        repo_url=meta.get("repo_url") or None,
        task=meta.get("task") or "",
        user_id=int(meta["user_id"]),
        status=status,
        sandbox_status=sandbox_status,
        created_at=meta.get("created_at") or "",
        updated_at=meta.get("updated_at") or "",
        next_steps=next_steps,
        imported_at=meta.get("imported_at") or None,
        branch=meta.get("branch") or None,
        file_count=file_count,
        files=files,
        import_error=import_error,
        spec_draft=meta.get("spec_draft") or None,
        spec_confirmed=bool(meta.get("spec_confirmed") or False),
    )


@router.post("/workspaces", response_model=OnlineCodingWorkspace)
async def create_online_coding_workspace(
    req: OnlineCodingCreateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    repo_url = (req.repo_url or "").strip() or None
    task = (req.task or "").strip()
    if not repo_url and not task:
        raise HTTPException(status_code=400, detail="请填写 Git 仓库地址或开发任务")
    if repo_url:
        repo_url = _validate_repo_url(repo_url)

    # 租户 workspace 数配额
    from app.tenant_quota import assert_tenant_quota
    await assert_tenant_quota(db, ctx.tenant_id, "workspaces")

    workspace_id = f"oc_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    ws_dir = _workspace_dir(workspace_id, ctx.tenant_id, repo_url, task or "无 Git 工作区")
    meta = {
        "id": workspace_id,
        "repo_url": repo_url,
        "task": task or "无 Git 工作区",
        "user_id": ctx.user.id,
        "tenant_id": ctx.tenant_id,
        "status": "created",
        "sandbox_status": "not_configured",
        "created_at": now,
        "updated_at": now,
    }
    _write_workspace(ws_dir, meta)
    if repo_url:
        meta = await _import_repository(
            ws_dir,
            meta,
            git_auth=_git_auth_from_request(req.git_username, req.git_token),
        )
    else:
        # 无 Git 模式：建空 repo/ 目录 + 标记 ready，让 Vibe Coding 对话直接接管
        _repo_path(ws_dir).mkdir(parents=True, exist_ok=True)
        meta = _mark_empty_repo_import(meta)
        _write_workspace(ws_dir, meta)
    return _public_workspace(meta)


@router.post("/workspaces/{workspace_id}/import", response_model=OnlineCodingWorkspace)
async def import_online_coding_workspace(
    workspace_id: str,
    req: OnlineCodingImportRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    ws_dir, meta = _find_workspace_dir(workspace_id)
    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该 Vibe Coding 工作区")

    repo_url = (req.repo_url or meta.get("repo_url") or "").strip()
    if not repo_url:
        raise HTTPException(status_code=400, detail="请先填写 Git 仓库地址")
    meta["repo_url"] = _validate_repo_url(repo_url)
    task = (req.task or "").strip()
    if task:
        meta["task"] = task
    meta = await _import_repository(
        ws_dir,
        meta,
        git_auth=_git_auth_from_request(req.git_username, req.git_token),
    )
    return _public_workspace(meta)


@router.get("/workspaces", response_model=list[OnlineCodingWorkspace])
async def list_online_coding_workspaces(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    ONLINE_CODING_ROOT.mkdir(parents=True, exist_ok=True)
    items: list[OnlineCodingWorkspace] = []
    for ws_dir in _iter_workspace_meta_dirs():
        try:
            meta = json.loads(_meta_path(ws_dir).read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("user_id") != ctx.user.id:
            continue
        items.append(_public_workspace(meta))
    return sorted(items, key=lambda item: item.updated_at, reverse=True)


@router.get("/workspaces/{workspace_id}", response_model=OnlineCodingWorkspace)
async def get_online_coding_workspace(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    _, meta = _find_workspace_dir(workspace_id)
    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该 Vibe Coding 工作区")
    return _public_workspace(meta)


@router.delete("/workspaces/{workspace_id}")
async def delete_online_coding_workspace(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    ws_dir, meta = _find_workspace_dir(workspace_id)
    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该 Vibe Coding 工作区")

    # 先清掉 Vibe Coding 沙箱容器（如果有）— 否则删了挂载点容器变孤儿
    try:
        from app.vibe_coding.docker_runtime import get_runtime as _get_rt
        rt = _get_rt()
        if await rt.is_available():
            await rt.remove(workspace_id, force=True)
    except Exception as exc:  # 容器层失败不应该挡住目录删除
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Failed to remove vibe sandbox container for %s: %s", workspace_id, exc
        )

    shutil.rmtree(ws_dir, ignore_errors=True)
    return {"ok": True}


@router.put("/workspaces/{workspace_id}/spec", response_model=OnlineCodingWorkspace)
async def update_online_coding_workspace_spec(
    workspace_id: str,
    req: OnlineCodingSpecUpdateRequest,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
):
    ws_dir, meta = _find_workspace_dir(workspace_id)
    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该 Vibe Coding 工作区")
    task = (req.task or "").strip()
    spec_draft = (req.spec_draft or "").strip()
    if task:
        meta["task"] = task
    if req.spec_draft is not None:
        meta["spec_draft"] = spec_draft
    if req.spec_confirmed is not None:
        meta["spec_confirmed"] = bool(req.spec_confirmed)
    meta["updated_at"] = _now_iso()
    _write_workspace(ws_dir, meta)
    return _public_workspace(meta)


@router.get("/workspaces/{workspace_id}/file", response_model=OnlineCodingFileContent)
async def read_online_coding_workspace_file(
    workspace_id: str,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    file_path: str = Query(..., min_length=1, max_length=2000),
):
    ws_dir, meta = _find_workspace_dir(workspace_id)
    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该 Vibe Coding 工作区")
    if not _is_repo_imported(meta):
        raise HTTPException(status_code=400, detail="仓库导入成功后才能读取文件")
    if _workspace_file_count(meta) <= 0:
        raise HTTPException(status_code=400, detail="空仓库还没有可读取文件，请先在 IDE 中创建项目文件")

    repo_dir = _repo_path(ws_dir)
    target = _resolve_repo_file(repo_dir, file_path)
    raw = target.read_bytes()
    truncated = len(raw) > MAX_FILE_READ_BYTES
    if truncated:
        raw = raw[:MAX_FILE_READ_BYTES]
    return OnlineCodingFileContent(
        path=file_path,
        content=raw.decode("utf-8", errors="replace"),
        truncated=truncated,
    )


@router.get("/workspaces/{workspace_id}/ide/context")
async def get_online_coding_workspace_ide_context(
    workspace_id: str,
    prompt: str = Query(default="", max_length=4000, description="用户当前问题，用于选择关键文件"),
    x_vibe_ide_token: Annotated[Optional[str], Header(alias="X-Vibe-IDE-Token")] = None,
    token: Optional[str] = Query(default=None),
):
    """给 Web IDE 内置 AI 提供在线仓库代码上下文。

    这个接口只接受短时 IDE token，不依赖浏览器登录态。用于 code-server
    扩展在本地 workspace 扫描失败或刚加载时，仍然能拿到当前在线仓库的
    文件索引和关键源码片段。
    """
    ws_dir, meta = _find_workspace_dir(workspace_id)
    _verify_online_ide_access(workspace_id, meta, x_vibe_ide_token or token)
    if not _is_repo_imported(meta):
        raise HTTPException(status_code=400, detail="仓库导入成功后才能读取代码上下文")

    repo_dir = _repo_path(ws_dir)
    if not repo_dir.exists():
        raise HTTPException(status_code=404, detail="仓库目录不存在")

    payload = _build_ide_workspace_context(repo_dir, prompt)
    return {
        "workspace_id": workspace_id,
        **payload,
    }


@router.get("/workspaces/{workspace_id}/ide-url")
async def get_online_coding_workspace_ide_url(
    workspace_id: str,
    request: Request,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    theme: Optional[str] = Query(default=None, description="light/dark，用于同步界面主题"),
    selected_model: Optional[str] = Query(default=None, max_length=256, description="Vibe Coding Agent 使用的模型标识"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    ws_dir, meta = _find_workspace_dir(workspace_id)
    if meta.get("user_id") != ctx.user.id:
        raise HTTPException(status_code=403, detail="无权访问该 Vibe Coding 工作区")
    if not _is_repo_imported(meta):
        raise HTTPException(status_code=400, detail="仓库导入成功后才能进入 IDE")

    base_url = _align_local_code_server_base_url(request, settings.code_server_base_url)
    if not base_url:
        raise HTTPException(status_code=501, detail="Web IDE 未配置，请在 .env 中设置 CODE_SERVER_BASE_URL")
    await _ensure_local_code_server_available(base_url)

    repo_dir = _repo_path(ws_dir)
    if not repo_dir.exists():
        raise HTTPException(status_code=404, detail="仓库目录不存在")

    ide_token = _create_ide_access_token(ctx, workspace_id)
    api_base = _build_ide_proxy_api_base(request, workspace_id)
    extension_model = (
        selected_model.strip()
        if selected_model and selected_model.strip()
        else await _get_default_coding_model_id(db, ctx.tenant_id)
    )
    _write_ruijing_extension_config(repo_dir, workspace_id, ide_token, api_base, extension_model)
    config_file = repo_dir / ".vscode" / "ruijing-ai.json"
    try:
        config_payload = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        config_payload = {}
    config_payload.update({
        "onlineMode": True,
        "runtimeMode": "online-coding",
        "onlineWorkspaceId": workspace_id,
    })
    config_file.write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    query_params = {
        "folder": str(repo_dir.resolve()),
        # code-server 内的睿鲸补丁和模型选择器识别的是这组标准 Vibe IDE 参数。
        "vibe_workspace_id": workspace_id,
        "vibe_online_workspace_id": workspace_id,
        "vibe_runtime_mode": "online-coding",
        "vibe_api_base": api_base,
        "vibe_harness_api_base": _derive_harness_api_base(api_base),
        "vibe_ide_token": ide_token,
    }
    if theme in {"light", "dark"}:
        query_params["vibe_ui_theme"] = theme
        query_params["vscode_theme"] = "Default Dark Modern" if theme == "dark" else "Default Light Modern"
    if selected_model and selected_model.strip():
        query_params["vibe_model"] = selected_model.strip()
    return {"ide_url": f"{base_url}/?{urlencode(query_params)}"}
