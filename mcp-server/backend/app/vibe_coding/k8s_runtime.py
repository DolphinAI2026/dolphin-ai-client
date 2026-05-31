"""
KubernetesRuntime — vibe-coding 沙箱在 K8s 上的运行时实现。

设计文档: docs/vibe-k8s-migration/00-design.md

接口跟 DockerRuntime 对齐（tools.py 的 _run_command_docker 等 helper 不用改写），
关键差异：
- container_name → pod_name（命名前缀 vibe-sandbox- 而不是 vibe-）
- host_port → K8s 没有 host port 概念，preview 走 Ingress 路由，本方法返 container_port
- exec → K8s websocket 协议（kubernetes_asyncio.stream.WsApiClient），比 docker exec 复杂
- 沙箱 image 通过 settings 配置，PVC 共享 apaas-workspaces-ming（subPath 隔离 per-workspace）

ServiceAccount 鉴权：ming pod 需要 spec.serviceAccountName=vibe-sandbox-manager
（deploy/k8s/60-vibe-rbac.yaml 已建）。本地 dev 走 ~/.kube/config。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────── 常量 ───────────────────────────

IMAGE = os.getenv(
    "VIBE_SANDBOX_IMAGE",
    # fallback: 复用 ai-builder/apaas-builder repo + vibe-sandbox-{date} tag。
    # 真因：hub.dfy.definesys.cn/ai-builder/vibe-sandbox 这个新 repo 后台没建过，
    # POST /v2/token 不签 token → buildkit/crane 撞 EOF。apaas-builder repo 已存在
    # 能 push（GET token endpoint 通），用同 repo + 不同 tag 区分 image。
    # 下次让 hub.dfy admin 建 ai-builder/vibe-sandbox 后改回 latest。
    # 2026-05-18 上线："vibe-sandbox-20260515" tag 实际从未 push 到 registry
    # （pod ImagePullBackOff），新 build vibe-sandbox-20260518 含 node20+python3+pnpm+uv。
    "hub.dfy.definesys.cn/ai-builder/apaas-builder:vibe-sandbox-20260518",
)
POD_PREFIX = "vibe-sandbox-"
SVC_PREFIX = "vibe-svc-"
NAMESPACE = os.getenv("VIBE_SANDBOX_NAMESPACE", "apaas-builder")
PVC_NAME = os.getenv("VIBE_SANDBOX_PVC", "apaas-workspaces-ming")
IMAGE_PULL_SECRET = os.getenv("VIBE_SANDBOX_IMAGE_PULL_SECRET", "regcred-hub-dfy")
DEFAULT_IDLE_THRESHOLD_SEC = 30 * 60  # 30 分钟无活跃 stop

# Pod 暴露的端口段（agent prompt 约束只用这段）
PORT_RANGE_START = 6100
PORT_RANGE_END = 6999
# 默认显式暴露的端口（其他端口用户用了也能 listen，但 Service 不路由）
DEFAULT_EXPOSED_PORTS = [6173, 6300, 6400, 6500]
# preview Service 主端口（vite 默认）
PRIMARY_PREVIEW_PORT = 6173

# Pod 启动后等 Running 的最大时间（拉 image + schedule）
POD_READY_TIMEOUT_SEC = 60

# nodeAffinity：把沙箱 Pod 调度到 ming pod 同节点（local-path PVC RWO 要求同 node）
NODE_AFFINITY_KEY = "apaas.definesys.com/app-tier"


@dataclass
class ExecResult:
    """跟 docker_runtime.ExecResult 同结构，让 tools.py 不需要改判断逻辑。"""
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class _ActivityRecord:
    last_active: float = field(default_factory=time.time)


# ─────────────────────────── K8s 客户端单例 ───────────────────────────


_k8s_loaded = False


async def _load_k8s_config() -> None:
    """优先 in-cluster（ming pod 内），fallback 本地 ~/.kube/config。"""
    global _k8s_loaded
    if _k8s_loaded:
        return
    # 延迟 import：让 backend 不带 kubernetes-asyncio 也能 import 本模块
    # （vibe-coding 没启用时不应该让 backend 启动崩）
    from kubernetes_asyncio import config as k8s_config

    try:
        k8s_config.load_incluster_config()
        logger.info("kubernetes-asyncio loaded in-cluster config")
    except k8s_config.ConfigException:
        # 本地 dev 走 kube/config
        await k8s_config.load_kube_config()
        logger.info("kubernetes-asyncio loaded kube/config")
    _k8s_loaded = True


class KubernetesRuntime:
    """单例。跟 DockerRuntime 接口对齐。"""

    def __init__(self, *, idle_threshold: int = DEFAULT_IDLE_THRESHOLD_SEC):
        self._activity: dict[str, _ActivityRecord] = {}
        self.idle_threshold = idle_threshold

    # ─────────────────────────── 可用性探测 ───────────────────────────

    async def is_available(self) -> bool:
        """K8s API 通 + 沙箱 image 可拉 + 当前 ServiceAccount 有权限。
        任意失败返回 False，调用方 fallback 到 host 模式。
        """
        try:
            await _load_k8s_config()
        except Exception as e:
            logger.warning("k8s config load failed: %s", e)
            return False

        from kubernetes_asyncio import client as k8s_client
        try:
            async with k8s_client.ApiClient() as api:
                core = k8s_client.CoreV1Api(api)
                # 列一下 ns 内 pod（验证 K8s API 通 + RBAC 有 list 权限）
                await core.list_namespaced_pod(namespace=NAMESPACE, limit=1)
            return True
        except Exception as e:
            logger.warning("k8s API probe failed: %s", e)
            return False

    # ─────────────────────────── Pod 生命周期 ───────────────────────────

    def pod_name(self, workspace_id: str) -> str:
        """workspace_id 用户提供（应该 alphanumeric + underscore + dash），不 sanitize 输入。
        K8s name 长度 ≤ 63 chars，前缀 14 chars，留 49 chars 给 ws_id。
        """
        return f"{POD_PREFIX}{workspace_id}".lower().replace("_", "-")[:63]

    # 向后兼容（让 tools.py 现有用法不报错）
    def container_name(self, workspace_id: str) -> str:
        return self.pod_name(workspace_id)

    def svc_name(self, workspace_id: str) -> str:
        return f"{SVC_PREFIX}{workspace_id}".lower().replace("_", "-")[:63]

    def ingress_name(self, workspace_id: str) -> str:
        return f"vibe-ws-{workspace_id}".lower().replace("_", "-")[:63]

    def ingress_host(self, workspace_id: str) -> str:
        """公网预览域名 — 阿里云 *.vibe-first.cn 通配指 39.103.201.110 反代到 ingress-nginx。
        DNS 也要保证子域名只包含 a-z0-9- 且首尾非 -（K8s svc 命名规范一致）。
        """
        sub = workspace_id.lower().replace("_", "-").strip("-")
        return f"{sub}.vibe-first.cn"

    async def container_status(self, workspace_id: str) -> Optional[str]:
        """返回 Pod phase，跟 DockerRuntime 的 container_status 对齐：
        Running → "running"，Pending → "created"，Succeeded/Failed → "exited"，None → 不存在
        """
        from kubernetes_asyncio import client as k8s_client
        from kubernetes_asyncio.client.rest import ApiException

        try:
            await _load_k8s_config()
            async with k8s_client.ApiClient() as api:
                core = k8s_client.CoreV1Api(api)
                pod = await core.read_namespaced_pod(
                    name=self.pod_name(workspace_id), namespace=NAMESPACE
                )
        except ApiException as e:
            if e.status == 404:
                return None
            logger.warning("pod_status %s ApiException: %s", workspace_id, e)
            return None
        except Exception as e:
            logger.warning("pod_status %s error: %s", workspace_id, e)
            return None

        phase = (pod.status.phase or "").lower()
        mapping = {
            "running": "running",
            "pending": "created",
            "succeeded": "exited",
            "failed": "exited",
            "unknown": None,
        }
        return mapping.get(phase)

    async def ensure_container(
        self,
        workspace_id: str,
        host_workspace_dir: Path,
        *,
        ports: Optional[list[int]] = None,
        tenant_id: int = 1,
    ) -> str:
        """保证 Pod 处于 Running，返回 Pod 名。

        - 不存在 → 创建 Pod（subPath 挂 PVC + 暴露端口 + nodeAffinity 同 ming 节点）
        - exited / Pending stuck → 删 + 重建
        - Running → 直接返回，更新 activity

        注：host_workspace_dir 在 K8s 里不直接用（PVC subPath 路径由 ws_id 决定），
            参数保留以对齐 DockerRuntime 签名让 tools.py 不改。
        """
        from kubernetes_asyncio import client as k8s_client
        from kubernetes_asyncio.client.rest import ApiException

        await _load_k8s_config()
        name = self.pod_name(workspace_id)

        status = await self.container_status(workspace_id)
        if status == "running":
            self._touch(workspace_id)
            # 顺手确保 svc + ingress 还在（Pod 重建后可能也没）
            await self._ensure_service(workspace_id)
            await self._ensure_ingress(workspace_id)
            return name

        # exited 或 unknown 状态：删了重建
        if status == "exited":
            logger.info("Pod %s in exited state, recreating", name)
            await self._delete_pod(workspace_id)
            status = None

        # Pending stuck（>2 分钟还没起来）也要 reset
        # 简化：不存在就 create
        if status is None:
            spec = _pod_spec(
                workspace_id=workspace_id,
                tenant_id=tenant_id,
                image=IMAGE,
                ports=ports,
            )
            async with k8s_client.ApiClient() as api:
                core = k8s_client.CoreV1Api(api)
                try:
                    await core.create_namespaced_pod(namespace=NAMESPACE, body=spec)
                    logger.info("created Pod %s", name)
                except ApiException as e:
                    if e.status == 409:
                        # 并发 race：另一个调用已经创建，忽略
                        logger.info("Pod %s already exists (race), continuing", name)
                    else:
                        raise

        # 确保 Service + Ingress 也在
        await self._ensure_service(workspace_id)
        await self._ensure_ingress(workspace_id)

        # 等 Pod 进 Running（最多 POD_READY_TIMEOUT_SEC）
        ready = await self._wait_pod_running(workspace_id, timeout=POD_READY_TIMEOUT_SEC)
        if not ready:
            logger.warning(
                "Pod %s 等 Running 超时 (%ds)，继续 — exec/preview 可能失败",
                name, POD_READY_TIMEOUT_SEC,
            )

        self._touch(workspace_id)
        return name

    async def _wait_pod_running(self, workspace_id: str, *, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = await self.container_status(workspace_id)
            if status == "running":
                return True
            await asyncio.sleep(1.5)
        return False

    async def _ensure_service(self, workspace_id: str) -> None:
        """每个 Pod 对应一个 ClusterIP Service，让 Ingress 能按 Host header 路由到。
        idempotent — 已有就跳过。
        """
        from kubernetes_asyncio import client as k8s_client
        from kubernetes_asyncio.client.rest import ApiException

        svc_name = self.svc_name(workspace_id)
        async with k8s_client.ApiClient() as api:
            core = k8s_client.CoreV1Api(api)
            try:
                await core.read_namespaced_service(name=svc_name, namespace=NAMESPACE)
                return  # 已存在
            except ApiException as e:
                if e.status != 404:
                    raise

            svc_spec = _service_spec(workspace_id=workspace_id)
            try:
                await core.create_namespaced_service(namespace=NAMESPACE, body=svc_spec)
                logger.info("created Service %s", svc_name)
            except ApiException as e:
                if e.status != 409:
                    raise


    async def _ensure_ingress(self, workspace_id: str) -> None:
        """方案 B per-workspace Ingress（2026-05-18 实装）。

        host=<ws>.vibe-first.cn → service vibe-svc-<ws>:6173 (PRIMARY_PREVIEW_PORT)。
        HTTP only — TLS 等 wildcard cert secret 接入再加 spec.tls。
        idempotent — 已存在直接返回 (409)。
        """
        from kubernetes_asyncio import client as k8s_client
        from kubernetes_asyncio.client.rest import ApiException

        host = self.ingress_host(workspace_id)
        name = self.ingress_name(workspace_id)
        svc = self.svc_name(workspace_id)

        annotations = {
            # dev server WebSocket（vite HMR / next-router）会用 long-lived 连接 + chunked
            # 必须关 buffering + 拉长 read/send timeout，否则 hot reload 卡顿
            "nginx.ingress.kubernetes.io/proxy-buffering": "off",
            "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
            "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
            # vite / webpack-dev-server 头部包含 X-Forwarded-Host 等，必须透传
            "nginx.ingress.kubernetes.io/configuration-snippet": (
                "proxy_set_header X-Forwarded-Proto $scheme;\n"
                "proxy_set_header X-Forwarded-Host $host;\n"
            ),
        }
        # TLS：vibe-first.cn wildcard cert secret 接入后会自动 enable
        tls_secret = os.getenv("VIBE_INGRESS_TLS_SECRET", "").strip()

        ingress_spec = k8s_client.V1Ingress(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                namespace=NAMESPACE,
                labels={"app": "vibe-sandbox", "workspace-id": workspace_id},
                annotations=annotations,
            ),
            spec=k8s_client.V1IngressSpec(
                ingress_class_name="nginx",
                rules=[k8s_client.V1IngressRule(
                    host=host,
                    http=k8s_client.V1HTTPIngressRuleValue(paths=[
                        k8s_client.V1HTTPIngressPath(
                            path="/",
                            path_type="Prefix",
                            backend=k8s_client.V1IngressBackend(
                                service=k8s_client.V1IngressServiceBackend(
                                    name=svc,
                                    port=k8s_client.V1ServiceBackendPort(number=PRIMARY_PREVIEW_PORT),
                                ),
                            ),
                        ),
                    ]),
                )],
                tls=([k8s_client.V1IngressTLS(hosts=[host], secret_name=tls_secret)]
                     if tls_secret else None),
            ),
        )

        async with k8s_client.ApiClient() as api:
            net = k8s_client.NetworkingV1Api(api)
            try:
                await net.create_namespaced_ingress(namespace=NAMESPACE, body=ingress_spec)
                logger.info("created Ingress %s for host %s → svc %s", name, host, svc)
            except ApiException as e:
                if e.status == 409:
                    # 已存在 — patch 更新（svc 改名了的话能跟上）
                    try:
                        await net.patch_namespaced_ingress(
                            name=name, namespace=NAMESPACE, body=ingress_spec
                        )
                    except ApiException as patch_e:
                        if patch_e.status != 404:
                            logger.warning("patch_ingress %s failed: %s", name, patch_e)
                else:
                    raise

    async def _delete_ingress(self, workspace_id: str) -> bool:
        from kubernetes_asyncio import client as k8s_client
        from kubernetes_asyncio.client.rest import ApiException

        async with k8s_client.ApiClient() as api:
            net = k8s_client.NetworkingV1Api(api)
            try:
                await net.delete_namespaced_ingress(
                    name=self.ingress_name(workspace_id), namespace=NAMESPACE
                )
                return True
            except ApiException as e:
                if e.status == 404:
                    return False
                logger.warning("delete_ingress %s failed: %s", workspace_id, e)
                return False

    async def _delete_pod(self, workspace_id: str) -> bool:
        """删 Pod（保留 Service 以便 resume 时复用）。"""
        from kubernetes_asyncio import client as k8s_client
        from kubernetes_asyncio.client.rest import ApiException

        async with k8s_client.ApiClient() as api:
            core = k8s_client.CoreV1Api(api)
            try:
                await core.delete_namespaced_pod(
                    name=self.pod_name(workspace_id),
                    namespace=NAMESPACE,
                    grace_period_seconds=10,
                )
                return True
            except ApiException as e:
                if e.status == 404:
                    return False
                logger.warning("delete_pod %s failed: %s", workspace_id, e)
                return False

    async def stop(self, workspace_id: str, *, timeout: int = 10) -> bool:
        """删 Pod，保留 Service + PVC subPath data（复用 resume）。"""
        ok = await self._delete_pod(workspace_id)
        self._activity.pop(workspace_id, None)
        return ok

    async def remove(self, workspace_id: str, *, force: bool = True) -> bool:
        """删 Pod + Service + Ingress（不删 PVC subPath 数据 — 用户数据用文件级 API 单独清理）。"""
        from kubernetes_asyncio import client as k8s_client
        from kubernetes_asyncio.client.rest import ApiException

        await self._delete_pod(workspace_id)
        await self._delete_ingress(workspace_id)
        async with k8s_client.ApiClient() as api:
            core = k8s_client.CoreV1Api(api)
            try:
                await core.delete_namespaced_service(
                    name=self.svc_name(workspace_id), namespace=NAMESPACE
                )
            except ApiException as e:
                if e.status != 404:
                    logger.warning("delete_svc %s failed: %s", workspace_id, e)
        self._activity.pop(workspace_id, None)
        return True

    # ─────────────────────────── Exec ───────────────────────────

    async def exec(
        self,
        workspace_id: str,
        cmd: list[str],
        *,
        timeout: int = 30,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> ExecResult:
        """K8s exec：用 kubernetes_asyncio.stream.WsApiClient websocket。

        env 注入：K8s exec API 不直接支持，用 `env KEY=VAL ... cmd...` 包一层 sh -c。
        cwd 同理用 `cd /workspace/... && ...`。
        """
        from kubernetes_asyncio import client as k8s_client
        from kubernetes_asyncio.stream import WsApiClient

        await _load_k8s_config()
        self._touch(workspace_id)

        full_cmd = _wrap_cmd(cmd, cwd=cwd, env=env)
        ws_config = await _ws_api_client_config()

        # 用 stream() helper 跑同步 exec — 比 ws raw 简单
        async with WsApiClient(configuration=ws_config) as api:
            core = k8s_client.CoreV1Api(api)
            try:
                ws = await asyncio.wait_for(
                    core.connect_get_namespaced_pod_exec(
                        name=self.pod_name(workspace_id),
                        namespace=NAMESPACE,
                        command=full_cmd,
                        stderr=True,
                        stdin=False,
                        stdout=True,
                        tty=False,
                        _preload_content=False,
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return ExecResult(returncode=-1, stdout="", stderr="", timed_out=True)
            except Exception as e:
                return ExecResult(returncode=-1, stdout="", stderr=f"exec error: {e}")

            stdout_buf, stderr_buf = [], []
            try:
                async for msg in ws:
                    # k8s ws 协议：每条消息第 1 字节是 channel (1=stdout, 2=stderr, 3=err)
                    if not msg.data:
                        continue
                    data = msg.data if isinstance(msg.data, bytes) else msg.data.encode("utf-8", "replace")
                    if len(data) < 1:
                        continue
                    channel = data[0]
                    payload = data[1:].decode("utf-8", "replace")
                    if channel == 1:
                        stdout_buf.append(payload)
                    elif channel == 2:
                        stderr_buf.append(payload)
            except Exception as e:
                stderr_buf.append(f"\n[stream error: {e}]")

            # K8s exec 不直接给 exit code，只能从 stderr/特殊 channel 推断
            # 简化：stderr 含 "command terminated" / "exit code N" 解析；否则默认 0
            stderr_text = "".join(stderr_buf)
            stdout_text = "".join(stdout_buf)
            returncode = _parse_exit_code(stderr_text, stdout_text)
            return ExecResult(
                returncode=returncode,
                stdout=stdout_text,
                stderr=stderr_text,
                timed_out=False,
            )

    async def exec_background(
        self,
        workspace_id: str,
        cmd: list[str],
        log_path: str,
        *,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> int:
        """后台跑命令，stdout/stderr 写 log_path。返回进程 PID（pod 内 PID）。

        实现：在 Pod 内 sh -c "nohup CMD > LOG 2>&1 & echo $!"，解析 echo 出的 PID。
        """
        # 构造 background 命令
        log_dir = Path(log_path).parent.as_posix()
        ws_root = cwd or "/workspace"
        joined_cmd = " ".join(shlex.quote(x) for x in cmd)
        env_prefix = ""
        if env:
            env_prefix = " ".join(
                f"{k}={shlex.quote(str(v))}" for k, v in env.items()
            ) + " "
        bg_script = (
            f"mkdir -p {shlex.quote(log_dir)} && "
            f"cd {shlex.quote(ws_root)} && "
            f"nohup {env_prefix}{joined_cmd} > {shlex.quote(log_path)} 2>&1 & "
            f"echo $!"
        )
        result = await self.exec(
            workspace_id, ["sh", "-c", bg_script], timeout=10, cwd=None, env=None
        )
        try:
            return int(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return -1

    # ─────────────────────────── 端口 ───────────────────────────

    async def host_port(self, workspace_id: str, container_port: int) -> Optional[int]:
        """K8s 模式没 host port 映射 — 所有 preview 走 Ingress。
        返 container_port 自身让上游路由用相同值（语义：'对外暴露的端口 = 容器端口'）。
        """
        status = await self.container_status(workspace_id)
        if status != "running":
            return None
        return container_port

    async def all_host_ports(self, workspace_id: str) -> dict[int, int]:
        """返默认暴露端口段（K8s 模式下 host==container）。"""
        status = await self.container_status(workspace_id)
        if status != "running":
            return {}
        return {p: p for p in DEFAULT_EXPOSED_PORTS}

    async def listening_ports(self, workspace_id: str) -> set[int]:
        """exec 进 Pod 跑 ss -lnt 看实际监听端口（识别用户 npm run dev 起的）。"""
        result = await self.exec(
            workspace_id,
            ["sh", "-c", "ss -lnt 2>/dev/null | awk 'NR>1 {print $4}' | awk -F: '{print $NF}' | sort -u"],
            timeout=5,
        )
        ports: set[int] = set()
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            p = int(line)
            if PORT_RANGE_START <= p <= PORT_RANGE_END:
                ports.add(p)
        return ports

    # ─────────────────────────── Idle reaping ───────────────────────────

    def _touch(self, workspace_id: str) -> None:
        self._activity[workspace_id] = _ActivityRecord()

    async def reap_idle(self) -> list[str]:
        """扫 _activity，闲置超 idle_threshold 的 Pod stop 掉。返回被 stop 的 ws_id 列表。"""
        now = time.time()
        stale = [
            ws for ws, rec in self._activity.items()
            if now - rec.last_active > self.idle_threshold
        ]
        stopped = []
        for ws in stale:
            if await self.stop(ws):
                stopped.append(ws)
        return stopped


# ─────────────────────────── Pod / Service spec 模板 ───────────────────────────


def _pod_spec(
    *,
    workspace_id: str,
    tenant_id: int,
    image: str,
    ports: Optional[list[int]] = None,
) -> dict:
    """生成 Pod yaml dict。"""
    port_list = ports or DEFAULT_EXPOSED_PORTS
    container_ports = [
        {"name": f"port-{i}", "containerPort": p}
        for i, p in enumerate(port_list)
    ]
    safe_id = workspace_id.lower().replace("_", "-")
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": f"{POD_PREFIX}{safe_id}"[:63],
            "namespace": NAMESPACE,
            "labels": {
                "app": "vibe-sandbox",
                "workspace-id": safe_id[:63],
                "tenant-id": str(tenant_id),
            },
        },
        "spec": {
            "restartPolicy": "OnFailure",
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {"key": NODE_AFFINITY_KEY, "operator": "Exists"}
                                ]
                            }
                        ]
                    }
                }
            },
            "containers": [
                {
                    "name": "sandbox",
                    "image": image,
                    "imagePullPolicy": "IfNotPresent",
                    "ports": container_ports,
                    "volumeMounts": [
                        {
                            "name": "workspace",
                            "mountPath": "/workspace",
                            "subPath": f"tenant_{tenant_id}/{workspace_id}",
                        }
                    ],
                    "resources": {
                        "requests": {"cpu": "10m", "memory": "256Mi"},
                        "limits": {"cpu": "2", "memory": "2Gi"},
                    },
                }
            ],
            "volumes": [
                {
                    "name": "workspace",
                    "persistentVolumeClaim": {"claimName": PVC_NAME},
                }
            ],
            "imagePullSecrets": [{"name": IMAGE_PULL_SECRET}],
        },
    }


def _service_spec(*, workspace_id: str) -> dict:
    safe_id = workspace_id.lower().replace("_", "-")
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"{SVC_PREFIX}{safe_id}"[:63],
            "namespace": NAMESPACE,
            "labels": {"app": "vibe-sandbox", "workspace-id": safe_id[:63]},
        },
        "spec": {
            "type": "ClusterIP",
            "selector": {"workspace-id": safe_id[:63]},
            "ports": [
                {
                    "name": f"port-{p}",
                    "port": p,
                    "targetPort": p,
                    "protocol": "TCP",
                }
                for p in DEFAULT_EXPOSED_PORTS
            ],
        },
    }


# ─────────────────────────── 辅助 ───────────────────────────


async def _ws_api_client_config():
    """生成给 WsApiClient 用的 Configuration（跟 ApiClient 配置一致）。"""
    from kubernetes_asyncio import client as k8s_client
    cfg = k8s_client.Configuration.get_default_copy()
    return cfg


def _wrap_cmd(
    cmd: list[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> list[str]:
    """把命令包成 sh -c，注入 cwd / env。"""
    if not (cwd or env):
        return list(cmd)
    parts = []
    if cwd:
        parts.append(f"cd {shlex.quote(cwd)} &&")
    if env:
        for k, v in env.items():
            parts.append(f"{k}={shlex.quote(str(v))}")
    parts.append(" ".join(shlex.quote(x) for x in cmd))
    return ["sh", "-c", " ".join(parts)]


def _parse_exit_code(stderr: str, stdout: str = "") -> int:
    """K8s exec 不直接给 exit code — 从 stderr 解析。
    典型格式：'command terminated with exit code 1'。没解析到默认 0（即"成功"）。

    2026-05-18: 加 evicted/NotFound 关键字识别。注意不能用"stderr+stdout 全空"
    判失败 — 成功的 `touch foo` / `mkdir -p` 之类本来就 silent。pod 是否真 Running
    应在调用方 _run_command_k8s 用 container_status pre-flight 校验。
    """
    import re
    s = stderr or ""
    m = re.search(r"exit code (\d+)", s)
    if m:
        return int(m.group(1))
    low = s.lower()
    if "command terminated" in low:
        return 1
    if "container not found" in low or "is not running" in low or "container not in" in low:
        return -1
    return 0


# ─────────────────────────── 单例 ───────────────────────────


_k8s_runtime: Optional[KubernetesRuntime] = None


def get_k8s_runtime() -> KubernetesRuntime:
    global _k8s_runtime
    if _k8s_runtime is None:
        _k8s_runtime = KubernetesRuntime()
    return _k8s_runtime
