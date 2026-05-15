# Vibe Coding K8s Pod-per-Workspace 迁移设计

> 2026-05-15 凌晨立项。背景：老阿里云 ECS 101.132.123.203 已销毁，vibe-coding 沙箱（docker container）跟着没了。决策不修补旧方案，直接重写为 K8s 原生 pod-per-workspace 架构。
>
> 上下文：[[arch_decision_mcp_provider_2026_05_14]] 锁定 ai-builder = MCP 工具供应商；[[b_plan_landed_2026_05_15]] 已落地 ai-builder backend 上 k8s。本文件是 vibe-coding 子系统在 k8s 上的落地设计。

## 目标

每个 vibe workspace = 一个独立 K8s Pod，通过 K8s API 创建/管理。preview 通过 `{workspace_id}.vibe-first.cn` 通配子域路由到对应 Pod 的 vite dev server 端口。

非目标：
- ❌ 多租户共享 Pod（性能 / 隔离不可接受）
- ❌ 用 DinD / docker.sock hostPath（特权 + 安全风险）
- ❌ 自建 nginx 反代层（用 K8s Ingress 原生能力）

## 架构

```
浏览器
  ↓ https://{workspace_id}.vibe-first.cn
DNS A → 阿里云 ECS 39.103.201.110 (公网入口)
  ↓ Host: {ws_id}.vibe-first.cn 透传
ECS nginx → 反代 k8s nginx-ingress (跟 agent.dfy 同套路)
  ↓
k8s Ingress (host=*.vibe-first.cn 通配)
  ↓ 按 Host header 匹配 Service
Service vibe-sandbox-{ws_id} (ClusterIP)
  ↓
Pod vibe-sandbox-{ws_id} (vite :6173 暴露)
  ├─ image: vibe-sandbox:latest (node 20 + npm + vibe tools)
  ├─ command: ["sleep", "infinity"]  ← 等 vibe_run_command exec 触发
  └─ volume: PVC apaas-workspaces-ming subPath=tenant_{tid}/{ws_id} → /workspace
```

## 核心抽象：KubernetesRuntime

对齐现有 `DockerRuntime` 接口（`backend/app/vibe_coding/docker_runtime.py:398 LOC`），新写 `KubernetesRuntime`（`k8s_runtime.py`），保留 method 签名让 `tools.py` 不需要大改：

```python
class KubernetesRuntime:
    async def is_available(self) -> bool:
        """check K8s API 通 + 有权限 create pod"""
    
    async def ensure_container(self, ws_id, *, image, workspace_dir, env=None) -> str:
        """idempotent — 已有 Pod 就 return，没有就 create"""
    
    async def exec(self, ws_id, cmd, *, timeout=30) -> ExecResult:
        """通过 K8s exec API (类似 kubectl exec)"""
    
    async def exec_background(self, ws_id, cmd, log_path) -> int:
        """nohup ... > log 2>&1 & 然后 exec"""
    
    async def stop(self, ws_id) -> None:
        """delete pod (Service/Ingress 保留以便 resume)"""
    
    async def remove(self, ws_id) -> None:
        """delete pod + svc + ingress + (可选) subPath data"""
    
    async def host_port(self, ws_id, container_port) -> int:
        """K8s 不需要 host port mapping — 都通过 Ingress 路由。返 container_port 即可"""
    
    async def all_host_ports(self, ws_id) -> dict[int, int]:
        """同上"""
```

## Pod 模板

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: vibe-sandbox-{ws_id}
  namespace: apaas-builder
  labels:
    app: vibe-sandbox
    workspace-id: "{ws_id}"
    tenant-id: "{tenant_id}"
spec:
  containers:
    - name: sandbox
      image: hub.dfy.definesys.cn/ai-builder/vibe-sandbox:20260515
      imagePullPolicy: IfNotPresent
      command: ["sleep", "infinity"]
      ports:
        - { name: vite, containerPort: 6173 }
        - { name: alt1, containerPort: 6300 }
        - { name: alt2, containerPort: 6400 }
        - { name: alt3, containerPort: 6500 }
      volumeMounts:
        - name: workspace
          mountPath: /workspace
          subPath: "tenant_{tenant_id}/{ws_id}"
      resources:
        requests: { cpu: "10m", memory: "256Mi" }
        limits:   { cpu: "2",   memory: "2Gi" }
  volumes:
    - name: workspace
      persistentVolumeClaim:
        claimName: apaas-workspaces-ming  # 复用现有 50Gi PVC
  imagePullSecrets:
    - name: regcred-hub-dfy
```

## Service 模板

```yaml
apiVersion: v1
kind: Service
metadata:
  name: vibe-sandbox-{ws_id}
  namespace: apaas-builder
spec:
  selector:
    workspace-id: "{ws_id}"
  ports:
    - name: vite
      port: 6173
      targetPort: vite
```

## Ingress（方案 A：通配 + 静态 backend，让 nginx-ingress 按 Host header 路由）

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: vibe-sandboxes
  namespace: apaas-builder
  annotations:
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
    # configurationSnippet 用 server name 正则提取 ws_id 再 proxy_pass
    nginx.ingress.kubernetes.io/server-snippet: |
      set $ws_id "";
      if ($host ~ "^([a-z0-9_-]+)\.vibe-first\.cn$") {
        set $ws_id $1;
      }
      location / {
        proxy_pass http://vibe-sandbox-$ws_id.apaas-builder.svc.cluster.local:6173;
      }
spec:
  ingressClassName: nginx
  rules:
    - host: "*.vibe-first.cn"
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: vibe-sandbox-default  # placeholder，实际由 snippet 路由
                port: { number: 6173 }
```

**或方案 B（更稳但运维成本高）**：backend 每次 create workspace 时**动态创建** 1 个 Ingress object（host=`{ws_id}.vibe-first.cn`），删除时清理。少踩 nginx-ingress configurationSnippet 兼容性问题，但 ingress object 数量随 workspace 线性增长。

**推荐**：先做 A，撞兼容性问题再切 B。

## RBAC

ming pod 需要 K8s API 权限。新建 ServiceAccount + Role + RoleBinding：

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vibe-sandbox-manager
  namespace: apaas-builder
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: vibe-sandbox-manager
  namespace: apaas-builder
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/exec", "pods/log", "services"]
    verbs: ["get", "list", "create", "delete", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "create", "delete", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: vibe-sandbox-manager
  namespace: apaas-builder
subjects:
  - kind: ServiceAccount
    name: vibe-sandbox-manager
    namespace: apaas-builder
roleRef:
  kind: Role
  name: vibe-sandbox-manager
  apiGroup: rbac.authorization.k8s.io
```

`apaas-builder-ming` Deployment spec.template.spec 加 `serviceAccountName: vibe-sandbox-manager`。

## 持久化：subPath 共享 PVC

复用现有 `apaas-workspaces-ming` 50Gi PVC，每个 workspace 通过 `subPath=tenant_{tid}/{ws_id}` 隔离子目录。

**优点**：
- 不为每个 workspace 创 PVC（K8s storage class quota 限制）
- 现有 8 个 workspace 数据迁移 = 目录 mv 即可（无 PV 迁移）

**风险**：
- ming pod 跟 sandbox Pod 同时挂同一 PVC → RWO mode 下不能并发挂同一 node 之外的两个 pod
- 当前 PVC 是 `local-path` RWO，所以 ming + sandbox Pod 必须同 node
- 用 nodeAffinity 强制 sandbox Pod 调度到 ming 同节点（apaas.definesys.com/app-tier=true）

## Idle reaping

当前 docker_runtime.py `_activity` dict 跟踪 idle 时间，闲置 30 分钟 stop container。K8s 版本：
- 在 ming pod 内跑 background asyncio task
- 每 5 分钟扫 `kubectl get pods -l app=vibe-sandbox`，查每个 pod 的 `.online-coding.json` last_active
- 闲置超 30 分钟 → `stop()` 删 Pod（保留 Service+PVC subPath data）
- 用户下次 vibe_run_command → `ensure_container()` 重新 create Pod，挂回原 subPath，数据无损

## 设计决策追溯

| 决策 | 选 | 备选 | 理由 |
|---|---|---|---|
| Pod-per-ws vs 多 ws/Pod | Pod-per-ws | namespace 隔离多 ws 共 1 Pod | npm 版本冲突 / dev server 端口冲突 |
| 文件持久化 | 共享 PVC + subPath | 每 ws 独立 PVC | storage class quota / 8 个现有 ws 迁移成本 |
| 调度 | nodeAffinity 同 ming | 跨 node | local-path PVC RWO 限制 |
| Ingress 路由 | 通配 + server-snippet | 动态 create Ingress | 减少 ingress object 数；撞兼容性回退 B |
| K8s SDK | kubernetes-asyncio | kr8s / lightkube | mcp-server v2 已用，依赖少 |
| Pod 入口 | sleep infinity + exec | dev server 作 ENTRYPOINT | 灵活：什么命令什么时候跑 vibe_run_command 说了算 |
| Idle reaping | Pod stop 保留 Service | TTL 自动删 | 数据持久化 + 快速 resume |

## 风险 / 留尾

1. **`kubernetes-asyncio` 在 ai-builder backend 加 deps** — 依赖大约 5-10 MB，verify pip resolve 无冲突
2. **Pod 启动延迟** — 首次 ensure_container() 拉 image + Pod schedule + container start，预期 5-15s。需要 vibe_create_workspace 异步早返 + 后台等 ready
3. **K8s API 调用限流** — 大量 workspace 同时 create 时撞 API quota，需要 backend client 端 throttle
4. **Pod 安全策略** — 默认 SecurityContext 跑非 root；vite 默认绑 0.0.0.0 OK；npm install 需要写 node_modules → 走 emptyDir 不污染 PVC
5. **PVC `local-path` RWO 同 node 限制** — 如果 ming pod 撤离 app-tier 节点，sandbox Pod 也跟着挂；考虑改 RWX storage class（NFS / cephfs）
6. **vibe-sandbox image 制作 + 推 hub.dfy** — 是个独立 Dockerfile，需要立项

## 下次接手第一步

1. 看本设计文档确认架构
2. 进 Task #9 准备：写 `deploy/k8s/vibe-rbac.yaml` + `deploy/docker/vibe-sandbox/Dockerfile` + `deploy/k8s/vibe-ingress.yaml`
3. 然后 Task #10 写 `backend/app/vibe_coding/k8s_runtime.py`
4. Task #11-12 Service+Ingress 动态 + `_resolve_runtime` 加 k8s mode
5. Task #13-14 DNS + 阿里云 nginx + rebuild image
6. Task #15 端到端
