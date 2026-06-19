"""共享 Python 执行器 —— ai_chat 与 coding 两条链路的单一真相源。

冻结态(桌面打包)用 sidecar 二进制 `--run-script <file>` 跑;非冻结(开发/云端)用解释器 `-c code`。
不依赖 ai_chat / coding,避免循环 import。
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

from app import runtime


def build_python_argv(code: str, tmp_path: str, exe: str | None = None) -> list[str]:
    """桌面冻结态用 sidecar 二进制 --run-script <file>;否则用解释器 -c code。"""
    exe = exe or sys.executable
    if runtime.is_frozen():
        return [exe, "--run-script", tmp_path]
    return [exe, "-c", code]


async def run_python_in_dir(
    code: str,
    workspace: str | Path,
    *,
    timeout: int = 30,
    max_chars: int = 8000,
) -> tuple[bool, str]:
    """在 workspace 目录(cwd)执行 Python 代码,返回 (是否成功, 格式化的 stdout/stderr 文本)。

    冻结态把 code 落临时文件经 sidecar --run-script 跑,完后删除;超时 kill;超长截断。
    """
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    tmp_path = ""
    if runtime.is_frozen():
        tmp_path = str(ws / f".run_{uuid.uuid4().hex}.py")
        Path(tmp_path).write_text(code, encoding="utf-8")
    argv = build_python_argv(code, tmp_path)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(ws),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return False, f"错误：执行超时（{timeout} 秒）"
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        parts = []
        if out:
            parts.append(f"[stdout]\n{out.rstrip()}")
        if err:
            parts.append(f"[stderr]\n{err.rstrip()}")
        if proc.returncode != 0:
            parts.append(f"[exit code: {proc.returncode}]")
        result = "\n\n".join(parts) if parts else "[无输出]"
        if len(result) > max_chars:
            result = result[:max_chars] + f"\n\n[输出已截断，原始 {len(result)} 字符]"
        return proc.returncode == 0, result
    except Exception as e:  # noqa: BLE001
        return False, f"错误：执行失败 - {e}"
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
