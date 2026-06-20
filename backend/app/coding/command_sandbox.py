"""run_command 的桌面态 OS 级沙箱(macOS sandbox-exec / Seatbelt)。

桌面端把 AI 生成的命令跑在客户机上,通用 shell 命令不受约束 = 真实风险(写出工作区、
rm 掉别的项目)。这里用 sandbox-exec 把**文件写入限制在工作区 + 临时/缓存目录**,
读与网络放行(不破坏 git fetch / 读系统文件 / >/dev/null 重定向)。

设计取舍:
- 只在桌面态(客户机)+ macOS + sandbox-exec 可用时启用;dev/服务端行为完全不变。
- 网络默认放行(默认 deny 会静默搞坏 git/curl;留作后续硬化开关)。
- npm install/build 已在 _run_command 被特判走 WorkspaceManager,不进沙箱这条。
SBPL 语义:last-match-wins,故 (allow default) → (deny file-write*) → (allow file-write* 白名单)。
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def is_macos() -> bool:
    return platform.system() == "Darwin"


def sandbox_exec_available() -> bool:
    return is_macos() and Path(SANDBOX_EXEC).exists()


def should_sandbox() -> bool:
    """仅桌面态(客户机)+ sandbox-exec 可用时启用;否则按原样裸跑(dev/服务端不变)。"""
    if not sandbox_exec_available():
        return False
    try:
        from app.runtime import is_desktop

        return bool(is_desktop())
    except Exception:  # noqa: BLE001 — 判定失败一律不沙箱(不阻断命令)
        return False


def _sbpl_quote(path: str) -> str:
    """SBPL 字符串字面量转义(路径含空格无碍;防御性转义反斜杠/引号)。"""
    return path.replace("\\", "\\\\").replace('"', '\\"')


def _allowed_write_subpaths(workspace_path: Path) -> list[str]:
    ws = str(Path(workspace_path).resolve())
    tmpd = os.environ.get("TMPDIR", "/tmp").rstrip("/") or "/tmp"
    candidates = [
        ws,
        "/private/tmp",
        "/tmp",
        tmpd,
        "/private/var/folders",  # macOS 进程级临时(mktemp/node 用)
        str(Path.home() / ".apaas-builder"),  # npm 缓存等
    ]
    seen: set[str] = set()
    out: list[str] = []
    for p in candidates:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def build_profile(workspace_path: Path) -> str:
    """生成 SBPL profile:默认放行,deny 所有写,再 re-allow 工作区+临时+/dev 写。"""
    subpaths = "\n".join(
        f'    (subpath "{_sbpl_quote(p)}")' for p in _allowed_write_subpaths(workspace_path)
    )
    return (
        "(version 1)\n"
        "(allow default)\n"
        "(deny file-write*)\n"
        "(allow file-write*\n"
        f"{subpaths}\n"
        '    (regex #"^/dev/"))\n'
    )


def wrap_command(command: str, workspace_path: Path) -> list[str]:
    """把 shell 命令包进 sandbox-exec argv(profile 经 -p 内联)。"""
    return [SANDBOX_EXEC, "-p", build_profile(workspace_path), "/bin/bash", "-c", command]
