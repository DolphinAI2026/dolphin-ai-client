"""Docker Runtime — Vibe Coding 沙箱抽象层。

跟 docker daemon 通信走 docker CLI（subprocess 调），不引入 `docker-py` 依赖。
单 worker 部署够用，要扩到多 worker 时再考虑共享状态。

容器规约：
  - 名字: `vibe-{workspace_id}`（如 `vibe-oc_2caa734d4fa5`）
  - 镜像: `vibe-sandbox:latest`
  - 工作区挂载: host `online_coding/.../{ws}/repo` → container `/workspace`
  - 端口段: 6100-6999（容器内），host 用 -p 动态映射避免多 workspace 撞车
  - 长驻: `tail -f /dev/null` PID 1，agent 通过 `docker exec` 进容器跑命令

生命周期：
  - 创建 workspace 时不起容器（按需 lazy 启）
  - 第一次 run_command 时调 `ensure_container` 起或复用
  - 30 分钟无活跃 → `reap_idle()` stop（保留容器，下次 start 复用，不丢 node_modules）
  - 删 workspace → `remove(force=True)`

Dev fallback：
  - `is_available()` False 时，调用方应当 fallback 回 host subprocess（保留 dev 体验）
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


IMAGE = "vibe-sandbox:latest"
CONTAINER_PREFIX = "vibe-"
DEFAULT_IDLE_THRESHOLD_SEC = 30 * 60  # 30 分钟无活跃就停
# 容器内端口段 — agent 在 prompt 里被约束只用这段
PORT_RANGE_START = 6100
PORT_RANGE_END = 6999


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class _ActivityRecord:
    last_active: float = field(default_factory=time.time)


class DockerRuntime:
    """单例。维护活跃时间表，对 docker 的所有调用走 subprocess CLI。"""

    def __init__(self, *, idle_threshold: int = DEFAULT_IDLE_THRESHOLD_SEC):
        self._activity: dict[str, _ActivityRecord] = {}
        self.idle_threshold = idle_threshold

    # ─────────────────────────── 可用性探测 ───────────────────────────

    async def is_available(self) -> bool:
        """检查 docker（或兼容的 podman shim） + 镜像。任意一项失败就返回 False，调用方 fallback 到 host。

        兼容性：
        - Docker Engine：`docker info` 输出含 ServerVersion 字段
        - Podman shim（阿里云 Linux 等默认）：`docker info` 输出格式不同，没有 ServerVersion 字段
          → 改用 `docker version --format {{.Server.Version}}` 双方都支持的字段
        - 极端 fallback：直接 `docker info`（不带 --format）只看退出码
        """
        # version --format 在 docker / podman 都能拿到 server 版本（docker.Server.Version, podman 也填这字段）
        ok, out, _ = await self._run(
            ["docker", "version", "--format", "{{.Server.Version}}"], timeout=5
        )
        if not ok or not out.strip():
            # 兜底：只要 `docker info` 能跑通就认；过滤 podman 的 stderr 提示
            ok, _, _ = await self._run(["docker", "info"], timeout=5)
            if not ok:
                return False
        ok, out, _ = await self._run(
            ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], timeout=5
        )
        return ok and bool(out.strip())

    # ─────────────────────────── 容器生命周期 ───────────────────────────

    def container_name(self, workspace_id: str) -> str:
        return f"{CONTAINER_PREFIX}{workspace_id}"

    async def container_status(self, workspace_id: str) -> Optional[str]:
        """返回容器当前 docker state（running / exited / created / None=不存在）。"""
        name = self.container_name(workspace_id)
        ok, out, _ = await self._run(
            ["docker", "inspect", "--format", "{{.State.Status}}", name], timeout=5
        )
        if not ok:
            return None
        return out.strip() or None

    async def ensure_container(
        self,
        workspace_id: str,
        host_workspace_dir: Path,
        *,
        ports: Optional[list[int]] = None,
    ) -> str:
        """保证该 workspace 的容器在 running 状态，返回容器名。

        - 不存在 → docker run -d 起
        - exited → docker start 复用（node_modules 等已装的依赖还在）
        - running → 直接返回
        """
        name = self.container_name(workspace_id)
        host_workspace_dir = host_workspace_dir.resolve()
        host_workspace_dir.mkdir(parents=True, exist_ok=True)

        status = await self.container_status(workspace_id)
        if status == "running":
            self._touch(workspace_id)
            return name

        if status in ("exited", "created", "paused"):
            ok, _, err = await self._run(["docker", "start", name], timeout=15)
            if not ok:
                logger.warning("docker start %s failed: %s — falling back to recreate", name, err)
                await self._run(["docker", "rm", "-f", name], timeout=10)
                status = None
            else:
                self._touch(workspace_id)
                return name

        # 全新创建
        cmd = [
            "docker", "run", "-d",
            "--name", name,
            "--label", "vibe-coding=1",
            "--label", f"vibe-workspace={workspace_id}",
            "--workdir", "/workspace",
            "-v", f"{host_workspace_dir}:/workspace",
            # 资源限制（防 agent 误写死循环拖死 host）
            "--memory", "2g",
            "--cpus", "2",
            # 端口映射 —— host 端 0 让 docker 自动分配避免冲突
            *self._port_args(ports),
            IMAGE,
        ]
        ok, out, err = await self._run(cmd, timeout=30)
        if not ok:
            raise RuntimeError(f"docker run 失败: {err}")
        self._touch(workspace_id)
        logger.info("Started vibe sandbox container %s for ws %s", name, workspace_id)
        return name

    def _port_args(self, ports: Optional[list[int]]) -> list[str]:
        """把端口段映射到 host 上 — host 端写 0 让 docker 自动分配。

        默认映射 vibe 专用段中常用的几个（6173/6300/6400），
        agent 用其他端口时可以扩展（v1 暂时这几个够用）。
        """
        default_ports = ports or [6173, 6300, 6400, 6500]
        args: list[str] = []
        for p in default_ports:
            args.extend(["-p", f"0:{p}"])
        return args

    async def stop(self, workspace_id: str, *, timeout: int = 10) -> bool:
        name = self.container_name(workspace_id)
        ok, _, _ = await self._run(["docker", "stop", "-t", str(timeout), name], timeout=timeout + 5)
        return ok

    async def remove(self, workspace_id: str, *, force: bool = True) -> bool:
        name = self.container_name(workspace_id)
        cmd = ["docker", "rm"] + (["-f"] if force else []) + [name]
        ok, _, _ = await self._run(cmd, timeout=15)
        self._activity.pop(workspace_id, None)
        return ok

    # ─────────────────────────── 命令执行 ───────────────────────────

    async def exec(
        self,
        workspace_id: str,
        command: str,
        *,
        timeout: int = 120,
        env: Optional[dict[str, str]] = None,
        cwd: str = "/workspace",
    ) -> ExecResult:
        """前台执行命令，返回 stdout/stderr/returncode。container 必须先 ensure_container。"""
        name = self.container_name(workspace_id)
        self._touch(workspace_id)

        env_args: list[str] = []
        if env:
            for k, v in env.items():
                env_args.extend(["-e", f"{k}={v}"])

        # docker exec 不支持 cwd 参数，改用 sh -c "cd ... && cmd"
        wrapped = f"cd {shlex.quote(cwd)} && {command}"
        cmd = ["docker", "exec", *env_args, name, "sh", "-c", wrapped]
        ok, stdout, stderr = await self._run(cmd, timeout=timeout, capture_returncode=True)
        # _run 把 returncode 编进 stderr 末尾或返回，这里改用底层的 _run_full
        return await self._exec_full(cmd, timeout=timeout)

    async def exec_background(
        self,
        workspace_id: str,
        command: str,
        *,
        log_path: str,
        cwd: str = "/workspace",
    ) -> str:
        """后台执行命令，stdout/stderr 重定向到容器内的 log_path。返回容器内 pid。

        log_path 是相对 /workspace 的路径（如 `.vibe-logs/dev.log`），通过挂载共享给 host。

        关键：用 setsid 创建新会话彻底脱离 controlling terminal + stdin 重定向到 /dev/null，
        否则 docker exec 退出时 dev server（vite/tsx watch 等）可能因 stdin EOF / SIGHUP 自杀。
        """
        name = self.container_name(workspace_id)
        self._touch(workspace_id)
        log_dir = log_path.rsplit("/", 1)[0] if "/" in log_path else "."
        wrapped = (
            f"cd {shlex.quote(cwd)} && "
            f"mkdir -p {shlex.quote(log_dir)} && "
            f"setsid sh -c {shlex.quote(command)} "
            f"> {shlex.quote(log_path)} 2>&1 < /dev/null & "
            f"echo $!"
        )
        # -d 让 docker exec 自己 detach，不会因为 client 断开影响子进程
        cmd = ["docker", "exec", "-d", name, "sh", "-c", wrapped]
        # -d 模式 docker exec 不返回 stdout（pid 不会回来），所以单独再查一次
        result = await self._exec_full(cmd, timeout=10)
        if result.returncode != 0:
            raise RuntimeError(f"后台启动失败: {result.stderr}")
        # detach 模式拿不到 pid；查 log_path 文件 + ps 来兜底确认（agent 用 tail 看日志即可）
        return "(detached, see log)"

    # ─────────────────────────── 端口查询 ───────────────────────────

    async def host_port(self, workspace_id: str, container_port: int) -> Optional[int]:
        """查容器某个端口被 docker 映射到 host 的哪个端口。"""
        name = self.container_name(workspace_id)
        ok, out, _ = await self._run(
            ["docker", "port", name, str(container_port)], timeout=5
        )
        if not ok or not out.strip():
            return None
        # 输出形如 `0.0.0.0:55321\n[::]:55321`
        first_line = out.strip().split("\n")[0]
        if ":" in first_line:
            try:
                return int(first_line.rsplit(":", 1)[-1])
            except ValueError:
                return None
        return None

    async def all_host_ports(self, workspace_id: str) -> dict[int, int]:
        """返回 {container_port: host_port} — 给前端 preview iframe 拼 URL 用。"""
        name = self.container_name(workspace_id)
        ok, out, _ = await self._run(
            ["docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", name],
            timeout=5,
        )
        if not ok or not out.strip():
            return {}
        import json as _json
        try:
            data = _json.loads(out)
        except Exception:
            return {}
        result: dict[int, int] = {}
        for k, v in (data or {}).items():
            # k 形如 "6173/tcp"
            try:
                container_port = int(k.split("/")[0])
            except (ValueError, IndexError):
                continue
            if isinstance(v, list) and v:
                try:
                    result[container_port] = int(v[0].get("HostPort"))
                except (ValueError, KeyError, AttributeError):
                    continue
        return result

    async def listening_ports(self, workspace_id: str) -> set[int]:
        """容器内**真正在 LISTEN** 的 TCP 端口集合（IPv4 + IPv6）。

        通过读 /proc/net/tcp{,6}（最 portable，镜像不需要 ss/netstat）解析：
        每行 parts[1] 是 `local_addr:port`（hex），parts[3] 是 state（0A = TCP_LISTEN）。
        给 /sandbox/ports 用：跟 all_host_ports 取交集 → 过滤死端口。
        """
        name = self.container_name(workspace_id)
        ok, out, _ = await self._run(
            ["docker", "exec", name, "sh", "-c", "cat /proc/net/tcp /proc/net/tcp6 2>/dev/null"],
            timeout=5,
        )
        if not ok:
            return set()
        ports: set[int] = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[3] != "0A":
                continue
            local = parts[1]
            if ":" not in local:
                continue
            try:
                port = int(local.rsplit(":", 1)[-1], 16)
            except ValueError:
                continue
            if port > 0:
                ports.add(port)
        return ports

    # ─────────────────────────── Idle reaping ───────────────────────────

    def _touch(self, workspace_id: str) -> None:
        rec = self._activity.get(workspace_id)
        if rec:
            rec.last_active = time.time()
        else:
            self._activity[workspace_id] = _ActivityRecord()

    async def reap_idle(self) -> list[str]:
        """停 idle 超过阈值的容器（保留容器本体，下次 start 复用）。返回被停的 ws_id 列表。"""
        now = time.time()
        stopped: list[str] = []
        for ws_id, rec in list(self._activity.items()):
            if now - rec.last_active < self.idle_threshold:
                continue
            status = await self.container_status(ws_id)
            if status == "running":
                if await self.stop(ws_id):
                    stopped.append(ws_id)
                    logger.info("Reaped idle container %s (idle %.0fs)", ws_id, now - rec.last_active)
            self._activity.pop(ws_id, None)
        return stopped

    # ─────────────────────────── 内部 helper ───────────────────────────

    async def _run(
        self,
        cmd: list[str],
        *,
        timeout: int = 30,
        capture_returncode: bool = False,
    ) -> tuple[bool, str, str]:
        """跑 docker CLI 子进程，返回 (success, stdout, stderr)。"""
        result = await self._exec_full(cmd, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr

    async def _exec_full(self, cmd: list[str], *, timeout: int) -> ExecResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            return ExecResult(returncode=127, stdout="", stderr="docker CLI not installed")
        except Exception as exc:
            return ExecResult(returncode=1, stdout="", stderr=str(exc))
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return ExecResult(returncode=124, stdout="", stderr="timeout", timed_out=True)
        return ExecResult(
            returncode=proc.returncode or 0,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )


# 单例
_runtime: Optional[DockerRuntime] = None


def get_runtime() -> DockerRuntime:
    global _runtime
    if _runtime is None:
        _runtime = DockerRuntime()
    return _runtime
