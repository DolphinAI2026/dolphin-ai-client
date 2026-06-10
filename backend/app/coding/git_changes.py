"""工作区改动跟踪 —— 把 git 当"改动数据库"用。

工作区目录历史上不是 git 仓库。为了让代码工作区能展示"这一轮 agent 改了什么"，
这里给工作区引入一个对用户完全透明的 git 基线机制：

- ensure_baseline: 懒初始化。git init + 忽略规则写 .git/info/exclude（不碰用户文件）
  + 全量基线提交。老工作区第一次查改动时自动补建，基线 = 当时的现状。
- checkpoint: agent 跑代码前调用，把上一轮的改动收进基线。
  于是「改动」语义始终 = 最近一轮 agent 跑完后相对基线的差异。
- collect_changes: 文件状态(A/M/D) + 逐文件增删行数 + 汇总，喂文件树徽标和改动分组。
- file_diff: 单文件 unified diff 文本，喂查看器红绿对比。

git 不可用 / 任何子进程失败时一律安静降级（enabled=False / 返回 False），
绝不影响工作区原有功能。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 60  # 基线提交可能要加几千个文件，给足余量
_MAX_TEXT_PROBE = 1024 * 1024  # 未跟踪文件数行数的读取上限

# 写进 .git/info/exclude 的忽略规则（不污染工作区本身的 .gitignore）
_EXCLUDE_MARKER = "# ai-builder workspace changes (managed)"
_EXCLUDE_RULES = [
    "node_modules/",
    "dist/",
    "build/",
    "target/",
    ".cache/",
    ".venv/",
    "__pycache__/",
    "*.log",
    ".DS_Store",
]

_COMMIT_IDENTITY = [
    "-c", "user.name=ruijing-ai",
    "-c", "user.email=ai@ruijing.local",
]


@lru_cache(maxsize=1)
def git_available() -> bool:
    return shutil.which("git") is not None


def _git(ws_path: Path, *args: str, identity: bool = False) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(ws_path), "-c", "core.quotepath=false"]
    if identity:
        cmd += _COMMIT_IDENTITY
    cmd += list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        # 防止外层环境变量(GIT_DIR / GIT_INDEX_FILE 等)串进来
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home())},
    )


def _write_excludes(ws_path: Path) -> None:
    exclude = ws_path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if _EXCLUDE_MARKER in existing:
        return
    block = "\n".join([_EXCLUDE_MARKER, *_EXCLUDE_RULES]) + "\n"
    exclude.write_text(existing.rstrip("\n") + ("\n" if existing.strip() else "") + block, encoding="utf-8")


def _head_exists(ws_path: Path) -> bool:
    return _git(ws_path, "rev-parse", "--verify", "-q", "HEAD").returncode == 0


def ensure_baseline(ws_path: Path) -> bool:
    """确保工作区有 git 仓库 + 基线提交。返回是否就绪。"""
    if not git_available():
        return False
    try:
        if not (ws_path / ".git").exists():
            if _git(ws_path, "init", "-q").returncode != 0:
                return False
        _write_excludes(ws_path)
        if not _head_exists(ws_path):
            _git(ws_path, "add", "-A")
            r = _git(ws_path, "commit", "-q", "--allow-empty", "--no-verify",
                     "-m", "baseline: workspace snapshot", identity=True)
            if r.returncode != 0:
                logger.warning("workspace git 基线提交失败: %s", r.stderr.strip()[:300])
                return False
        return True
    except Exception:
        logger.warning("workspace git 基线初始化失败(忽略): %s", ws_path, exc_info=True)
        return False


def checkpoint(ws_path: Path, message: str = "checkpoint: before agent run") -> bool:
    """把当前未收基线的改动收进基线（agent 跑代码前调用）。返回是否产生了新提交。"""
    if not ensure_baseline(ws_path):
        return False
    try:
        status = _git(ws_path, "status", "--porcelain", "-uall", "--no-renames")
        if status.returncode != 0 or not status.stdout.strip():
            return False
        _git(ws_path, "add", "-A")
        r = _git(ws_path, "commit", "-q", "--no-verify", "-m", message, identity=True)
        return r.returncode == 0
    except Exception:
        logger.warning("workspace git checkpoint 失败(忽略): %s", ws_path, exc_info=True)
        return False


def _normalize_status(xy: str) -> str:
    if xy == "??":
        return "A"
    if "D" in xy:
        return "D"
    if "A" in xy:
        return "A"
    return "M"


def _count_text_lines(path: Path) -> tuple[int, bool]:
    """统计未跟踪文件行数。返回 (行数, 是否二进制)。"""
    try:
        if path.stat().st_size > _MAX_TEXT_PROBE:
            return 0, True
        raw = path.read_bytes()
        if b"\0" in raw[:8000]:
            return 0, True
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return 0, True
    if not text:
        return 0, False
    return text.count("\n") + (0 if text.endswith("\n") else 1), False


_DISABLED = {"enabled": False, "files": [], "total": {"files": 0, "additions": 0, "deletions": 0}}


def collect_changes(ws_path: Path) -> dict:
    """收集相对基线的改动清单。任何失败都降级为 enabled=False。"""
    if not ensure_baseline(ws_path):
        return dict(_DISABLED)
    try:
        status = _git(ws_path, "status", "--porcelain", "-uall", "--no-renames", "-z")
        if status.returncode != 0:
            return dict(_DISABLED)

        entries: dict[str, str] = {}
        for item in status.stdout.split("\0"):
            if len(item) < 4:
                continue
            xy, rel = item[:2], item[3:]
            entries[rel] = _normalize_status(xy)

        # 已跟踪文件的增删行数（含被删文件）；二进制 numstat 给 "-"
        numstat: dict[str, tuple[int, int, bool]] = {}
        ns = _git(ws_path, "diff", "HEAD", "--numstat", "--no-renames", "-z")
        if ns.returncode == 0:
            for item in ns.stdout.split("\0"):
                parts = item.split("\t")
                if len(parts) != 3:
                    continue
                a, d, rel = parts
                binary = a == "-" or d == "-"
                numstat[rel] = (0 if binary else int(a), 0 if binary else int(d), binary)

        files = []
        for rel in sorted(entries):
            st = entries[rel]
            if rel in numstat:
                additions, deletions, binary = numstat[rel]
            elif st == "A":
                additions, binary = _count_text_lines(ws_path / rel)
                deletions = 0
            else:
                additions = deletions = 0
                binary = False
            files.append({
                "path": rel, "status": st,
                "additions": additions, "deletions": deletions, "binary": binary,
            })

        return {
            "enabled": True,
            "files": files,
            "total": {
                "files": len(files),
                "additions": sum(f["additions"] for f in files),
                "deletions": sum(f["deletions"] for f in files),
            },
        }
    except Exception:
        logger.warning("workspace git 改动收集失败(忽略): %s", ws_path, exc_info=True)
        return dict(_DISABLED)


def file_diff(ws_path: Path, rel_path: str) -> dict:
    """单文件相对基线的 unified diff。"""
    disabled = {"enabled": False, "path": rel_path, "status": None, "diff": "", "binary": False}
    if not ensure_baseline(ws_path):
        return disabled
    try:
        status = _git(ws_path, "status", "--porcelain", "-uall", "--no-renames", "--", rel_path)
        if status.returncode != 0:
            return disabled
        line = status.stdout.rstrip("\n")
        st = _normalize_status(line[:2]) if line else None

        if line and line[:2] == "??":
            # 未跟踪的新文件：diff --no-index 对 /dev/null（有差异时退出码=1，非错误）
            r = _git(ws_path, "diff", "--no-color", "--no-index", "--", "/dev/null", rel_path)
        else:
            r = _git(ws_path, "diff", "--no-color", "--no-renames", "HEAD", "--", rel_path)
        out = r.stdout or ""
        binary = "Binary files" in out or "GIT binary patch" in out
        return {
            "enabled": True,
            "path": rel_path,
            "status": st,
            "diff": "" if binary else out,
            "binary": binary,
        }
    except Exception:
        logger.warning("workspace git 单文件 diff 失败(忽略): %s %s", ws_path, rel_path, exc_info=True)
        return disabled
