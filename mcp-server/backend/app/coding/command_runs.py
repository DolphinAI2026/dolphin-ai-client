"""持久化 run_workspace_command 后台执行状态。

背景
----
dolphin omnigate 转发 chat → MCP 时**死设 30s timeout**（实测 nginx 499 client closed
准点 30s）。npm install && npm run build 在中型项目下要跑 1-5 分钟，撞 timeout 后
mcp SDK streamable_http 写响应时遇到关闭的 stream 抛 ClosedResourceError，被 anyio
task group 聚合成 "unhandled errors in a TaskGroup (1 sub-exception)" 给 dolphin
omnigate，agent 拿到的就是这条无信息量的壳子（看不到 npm 实际输出）。

方案
----
照 deploy_application 已验证的 asyncio.shield + wait_for(20s) 异步早返套路：
- 20s 内能跑完 → 同步返完整 output（行为完全兼容旧版快命令 pwd/ls/cat）
- 20s 没跑完 → 立即返 {status:"in_progress", task_id, polling_hint}，后台 shield
  保护的 task 继续跑，结果写到 .workspace.json.last_command_run + 日志文件，agent
  通过 get_dev_workspace_status(ws_id) 轮询拿最终结果

设计取舍
--------
- 单 workspace 一次最多一个 last_command_run（npm install/build 顺序跑不并发，简化）
- 状态写 .workspace.json.last_command_run；详细输出流式写 <ws>/.command-logs/<task_id>.log
- pod 重启 + status=running 持续 >10min → 标 stale，让 agent 知道任务丢了重试

跟我们 deploy_application 状态写 applications 表不同：workspace 没有现成 DB 表，
.workspace.json 是 workspace 元数据 single source of truth（项目类型 / 关联应用 /
最近活动），写它最自然。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_META_FILE = ".workspace.json"
_LOG_DIR = ".command-logs"

# started_at 超过这个时长仍标 running → 视为 pod 挂了，标 stale
STALE_THRESHOLD_SECONDS = 10 * 60

# 日志文件保留 N 个最近 task；超出删旧的（避免无限增长）
_MAX_KEEP_LOGS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_meta(ws_path: Path) -> dict:
    f = ws_path / _META_FILE
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("command_runs: 读 .workspace.json 失败 ws_path=%s", ws_path, exc_info=True)
        return {}


def _write_meta(ws_path: Path, meta: dict) -> None:
    """原子写：先 .tmp 再 rename，避免并发读到半写状态"""
    f = ws_path / _META_FILE
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)


def make_task_id(ws_id: str) -> str:
    return f"cmd_{ws_id}_{int(time.time() * 1000)}"


def start_run(ws_path: Path, task_id: str, command: str) -> Path:
    """登记新命令运行，返回日志文件路径。

    返回的日志文件已 touch 创建，调用方拿到后用 append_log_callback 包成 progress_callback
    传给 _run_command。
    """
    log_dir = ws_path / _LOG_DIR
    log_dir.mkdir(exist_ok=True)
    _gc_old_logs(log_dir)
    log_file = log_dir / f"{task_id}.log"
    log_file.touch()

    meta = _read_meta(ws_path)
    meta["last_command_run"] = {
        "task_id": task_id,
        "command": command,
        "started_at": _now_iso(),
        "started_at_ts": time.time(),
        "status": "running",
        "log_file": f"{_LOG_DIR}/{task_id}.log",
        "exit_code": None,
        "finished_at": None,
    }
    _write_meta(ws_path, meta)
    return log_file


def finish_run(
    ws_path: Path,
    task_id: str,
    *,
    status: str,
    exit_code: Optional[int],
    output: str = "",
) -> None:
    """终态登记。status: completed | failed | cancelled

    防御性：如果当前 last_command_run.task_id 已被新 task 覆盖，不动它
    （旧 task finish 时新 task 已经在跑了）。
    """
    if status not in ("completed", "failed", "cancelled"):
        logger.warning("finish_run: 无效 status=%s, task_id=%s", status, task_id)
        return
    meta = _read_meta(ws_path)
    last = meta.get("last_command_run") or {}
    if last.get("task_id") != task_id:
        return
    last["status"] = status
    last["exit_code"] = exit_code
    last["finished_at"] = _now_iso()
    # 末尾 2000 字符存元数据里，agent 通过 get_dev_workspace_status 直接看到
    # 不用再开第二个工具读日志文件
    if output:
        tail = output if len(output) <= 2000 else "...(truncated)\n" + output[-2000:]
        last["output_tail"] = tail
    meta["last_command_run"] = last
    _write_meta(ws_path, meta)


def get_last_run(ws_path: Path) -> Optional[dict]:
    """读上次命令运行状态；status=running 且 started_at >10min ago → 自动改标 stale"""
    meta = _read_meta(ws_path)
    last = meta.get("last_command_run")
    if not last:
        return None
    if last.get("status") == "running":
        ts = last.get("started_at_ts") or 0
        if ts and (time.time() - ts) > STALE_THRESHOLD_SECONDS:
            stale = dict(last)
            stale["status"] = "stale"
            stale["stale_reason"] = (
                "started_at > 10min ago but still 'running' — backend pod likely restarted; "
                "re-run the command if needed."
            )
            return stale
    return last


def append_log_callback(log_file: Path) -> Callable[[str], None]:
    """生成 progress_callback：流式追加 chunk 到日志文件。

    chunk 单位是 _stream_process_output 里的 1KB 子片段 + npm 安装/构建器内
    手动 _emit_progress 的整行消息，不会高频到 IO 瓶颈。
    """
    def _cb(chunk: str) -> None:
        if not chunk:
            return
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(chunk)
        except Exception:
            # 日志写失败不影响主流程（agent 还能从 .workspace.json output_tail 看末段）
            logger.debug("append_log_callback: 写日志失败 log_file=%s", log_file, exc_info=True)
    return _cb


def read_log_tail(ws_path: Path, task_id: str, max_chars: int = 4000) -> str:
    """读上次命令的日志末段。get_dev_workspace_status 内部用，agent 不直接调"""
    if not task_id:
        return ""
    log_file = ws_path / _LOG_DIR / f"{task_id}.log"
    if not log_file.exists():
        return ""
    try:
        text = log_file.read_text(encoding="utf-8")
        if len(text) > max_chars:
            return f"...(truncated, showing last {max_chars} chars)\n" + text[-max_chars:]
        return text
    except Exception:
        return ""


def _gc_old_logs(log_dir: Path) -> None:
    """保留最新 _MAX_KEEP_LOGS 个 .log 文件，老的删除。失败不阻塞主流程。"""
    try:
        logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in logs[_MAX_KEEP_LOGS:]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:
        pass


__all__ = [
    "make_task_id",
    "start_run",
    "finish_run",
    "get_last_run",
    "append_log_callback",
    "read_log_tail",
    "STALE_THRESHOLD_SECONDS",
]
