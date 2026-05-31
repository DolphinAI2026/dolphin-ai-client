# K8s 部署清单

单节点 StatefulSet 方案：一个 Pod 里跑
- **主容器**：supervisord → uvicorn (8003) + code-server (8080)
- **sidecar nginx**：serve 前端 dist（由 initContainer 从镜像内拷到共享卷），并反代 /ai-builder/api → 主容器 8003、/ai-builder/ide → 8080

集群入口：Ingress（nginx class）→ Service:80 → Pod 里 nginx sidecar。

**URL 方案**：路径前缀 `https://df-aigc.dfy.definesys.cn/ai-builder/`。前端镜像用 `--build-arg VITE_BASE_URL=/ai-builder/` 构建。

## Dev 一键部署

内测环境可以直接走脚本，不再通过 KubeSphere 浏览器终端手敲：

```bash
KUBECONFIG=~/.kube/dfy-host.yaml scripts/deploy_k8s_dev.sh
```

脚本会把当前 `HEAD` 推到 `origin/dev`，构建并推送 `hub.dfy.definesys.cn/ai-builder/apaas-builder:dev-<日期>-<sha>`，然后更新 `apaas-builder-dev` 的 StatefulSet / Service / Ingress / ConfigMap / Secret / PVC，并验证 `https://agent.dfy.definesys.cn/ai-builder/login`。

前置条件：
- 本机 `docker` 已登录 `hub.dfy.definesys.cn`
- 本机 `kubectl` 能用 kubeconfig 直连集群
- 工作区干净；如只想部署不推分支，可用 `PUSH_DEV=0 scripts/deploy_k8s_dev.sh`

## 架构

```
Ingress (host=df-aigc.dfy.definesys.cn)
    │
    ▼
Service apaas-builder:80
    │
    ▼
StatefulSet apaas-builder (replicas=1, nodeAffinity app-tier=true)
    ├─ initContainer  copy-frontend-dist: cp /app/frontend/dist → emptyDir
    ├─ container      apaas-builder:   uvicorn:8003 + code-server:8080
    └─ container      web (nginx):     serve emptyDir dist, proxy /api:8003 /ide:8080

  volumes:
   - workspaces  ← PVC (local-path, 50Gi, RWO, 固定节点)
   - backend-env ← Secret (手动 kubectl create)
```

## 前置

- **MySQL**：已部署在 `mysql` 命名空间（单节点，集群内 DNS `mysql.mysql.svc.cluster.local:3306`）。业务库/账号已创建：`apaas_builder` / `apaas:apaas2024`。详见 [../../主备部署mysql(1).md](../../../../../Downloads/单节点部署mysql.md) 的单节点修改版。
- **镜像**：当前部署使用 `hub.dfy.definesys.cn/ai-builder/apaas-builder:20260428-ruijing`。
- **节点标签**：`apaas.definesys.com/app-tier=true` 已在 `i8vbj7weas0dx1id3v9wa` 上（PV + 调度会绑到这台）。
- **IngressClass**：`nginx`（集群已有）。

## 一次性操作

### 1. 建 Secret（backend.env）

准备一份生产版 `backend.env`（和本地 `/tmp/apaas-local/backend.env` 对照修改）：

```dotenv
APAAS_BASE_URL=https://apaas-poc.definesys.cn/backend
APAAS_TENANT_ID=743906758237356033

LLM_API_BASE=https://api.minimaxi.com/anthropic
LLM_API_KEY=<生产 API KEY>
LLM_MODEL=MiniMax-M2.7
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_API_KEY=<同上>
ANTHROPIC_MODEL=MiniMax-M2.7

# 指向集群内 MySQL
DATABASE_URL=mysql+aiomysql://apaas:apaas2024@mysql.mysql.svc.cluster.local:3306/apaas_builder?charset=utf8mb4

JWT_SECRET_KEY=<换成随机长字符串>
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

HOST=0.0.0.0
PORT=8003
ENABLE_CODE_SUFFIX=false

# Web IDE 外部 URL（用户浏览器访问的入口，ingress host + /ai-builder/ide/）
CODE_SERVER_BASE_URL=https://df-aigc.dfy.definesys.cn/ai-builder/ide/

# npm-cache 跟 workspaces 在同一 PVC 下
APAAS_WORKSPACE_ROOT=/root/apaas-builder/workspaces
APAAS_NPM_CACHE_DIR=/root/apaas-builder/workspaces/.npm-cache
```

> 注意：`backend.env` 里的 `APAAS_WORKSPACE_ROOT` 只作为配置留档；后端工作区代码直接读取进程环境变量。`30-statefulset.yaml` 必须同步显式注入 `APAAS_WORKSPACE_ROOT=/root/apaas-builder/workspaces` 和 `APAAS_NPM_CACHE_DIR=/root/apaas-builder/workspaces/.npm-cache`，否则后端会回退到镜像内 `/app/workspaces`，与 code-server/PVC 路径不一致。

先建 namespace，再建 secret：

```bash
kubectl apply -f 00-namespace.yaml

kubectl -n apaas-builder create secret generic apaas-backend-env \
  --from-file=backend.env=/path/to/your/backend.env
```

### 2. (可选) 私库 pull secret

如果集群默认不能免凭据拉 `hub.dfy.definesys.cn`，建一个 docker-registry secret：

```bash
kubectl -n apaas-builder create secret docker-registry regcred-hub-dfy \
  --docker-server=hub.dfy.definesys.cn \
  --docker-username=<你的账号> \
  --docker-password=<你的密码>
```

然后取消 `30-statefulset.yaml` 里 `imagePullSecrets` 段的注释。

### 3. 改 Ingress 域名

编辑 [50-ingress.yaml](50-ingress.yaml)，把 `df-aigc.dfy.definesys.cn` 替换成你实际要用的域名，并把对应的 DNS A 记录指向集群 ingress IP（看 `kubectl get ingress -A` 现有那些 ingress 的 ADDRESS 列即可：`172.23.39.215,234,237,246`）。

如果要 HTTPS，取消 `tls:` 段并准备一个 secret 存证书：

```bash
kubectl -n apaas-builder create secret tls apaas-builder-tls \
  --cert=/path/to/fullchain.pem \
  --key=/path/to/privkey.pem
```

## 部署

按数字顺序 apply：

```bash
kubectl apply -f 00-namespace.yaml
# secret 手动建（见上）
kubectl apply -f 15-configmap-nginx.yaml
kubectl apply -f 20-pvc-workspaces.yaml
kubectl apply -f 30-statefulset.yaml
kubectl apply -f 40-service.yaml
kubectl apply -f 50-ingress.yaml
```

或一把梭（secret 单独处理）：

```bash
kubectl apply -f .
```

## 验证

```bash
# Pod Ready（首次启动会等 MySQL + init_db + seed_data，约 1-3 分钟）
kubectl -n apaas-builder get pods -w

# 日志
kubectl -n apaas-builder logs apaas-builder-0 -c apaas-builder --tail=50 -f
kubectl -n apaas-builder logs apaas-builder-0 -c web --tail=20
kubectl -n apaas-builder logs apaas-builder-0 -c copy-frontend-dist

# Service 通不通（集群内）
kubectl -n apaas-builder run curl-test --rm -i --tty --image=curlimages/curl -- \
  sh -c 'curl -sS http://apaas-builder/api/health && echo'

# Ingress
curl -s -o /dev/null -w "%{http_code}\n" -H 'Host: df-aigc.dfy.definesys.cn' http://<任意节点IP>/
# 期望 200（静态 index.html）

curl -s -H 'Host: df-aigc.dfy.definesys.cn' http://<节点IP>/api/health
# 期望 {"status":"ok"}
```

## 升级（推新镜像后）

```bash
# 1. 本地构建新镜像
docker build --platform linux/amd64 \
  -f deploy/docker/Dockerfile \
  --build-arg VITE_BASE_URL=/ai-builder/ \
  -t apaas-builder:local .

# 2. 推到私库（日期 tag）
TAG=$(date +%Y%m%d)
docker tag apaas-builder:local hub.dfy.definesys.cn/ai-builder/apaas-builder:$TAG
docker push hub.dfy.definesys.cn/ai-builder/apaas-builder:$TAG

# 3. 改 statefulset.yaml 里的 tag（两处：initContainer 和主容器，保持一致）
sed -i '' -E "s|apaas-builder:[^[:space:]]+|apaas-builder:$TAG|g" deploy/k8s/30-statefulset.yaml
kubectl apply -f deploy/k8s/30-statefulset.yaml

# 4. 或直接 set image（不改 yaml）
kubectl -n apaas-builder set image statefulset/apaas-builder \
  copy-frontend-dist=hub.dfy.definesys.cn/ai-builder/apaas-builder:$TAG \
  apaas-builder=hub.dfy.definesys.cn/ai-builder/apaas-builder:$TAG

# 然后等 pod 滚动
kubectl -n apaas-builder rollout status statefulset/apaas-builder
```

> 注意：StatefulSet 里 initContainer 和主容器**都**引用同一镜像（dist 来自镜像内）。如果只改主容器，initContainer 用的还是旧镜像，前端可能不更新。升级前端时直接 apply 整份 yaml 更稳。

## 关于 VITE_BASE_URL

当前路径前缀方案使用 `/ai-builder/`，镜像必须用 `--build-arg VITE_BASE_URL=/ai-builder/` 构建，和 nginx sidecar 的 `/ai-builder/*` location 保持一致。

如果要换成根路径或其他前缀部署，必须**重新构建镜像**：

```bash
docker build --platform linux/amd64 --build-arg VITE_BASE_URL=<prefix> ...
```

并同步修改 Ingress 的 path、nginx sidecar ConfigMap 里的 location 规则。

## code-server / 睿鲸 AI 扩展

容器镜像会在构建时完成两件事：

1. 从 `extensions/ruijing-ai` 构建并安装 `apaas-builder.ruijing-ai` VSIX。
2. 执行 `scripts/patch_all.js --code-server-path /opt/code-server`，把 code-server 原生 Chat 对 `GitHub.copilot-chat` 的检查切到 `apaas-builder.ruijing-ai`。

部署后可用以下命令确认：

```bash
kubectl -n apaas-builder exec apaas-builder-0 -c apaas-builder -- \
  sh -lc 'code-server --list-extensions --show-versions | grep ruijing'

kubectl -n apaas-builder exec apaas-builder-0 -c apaas-builder -- \
  sh -lc 'WB=/opt/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js; grep -q GitHub.copilot-chat "$WB" && echo "patch missing" || echo "patch ok"'
```

期望输出包含 `apaas-builder.ruijing-ai@0.1.0`，并显示 `patch ok`。

## 回滚

```bash
# 上一版本镜像的 tag 你应该还留着，直接切回去
kubectl -n apaas-builder set image statefulset/apaas-builder \
  copy-frontend-dist=hub.dfy.definesys.cn/ai-builder/apaas-builder:<旧 tag> \
  apaas-builder=hub.dfy.definesys.cn/ai-builder/apaas-builder:<旧 tag>
kubectl -n apaas-builder rollout status statefulset/apaas-builder
```

## 拆除

```bash
kubectl delete ns apaas-builder
# 注意：PVC 删除后 local-path PV 里的 workspaces 数据会**丢失**
# 保险起见先 kubectl -n apaas-builder get pvc 并 pv 级别备份或改 reclaim policy
```

## 故障排查

| 症状 | 可能原因 | 处理 |
|---|---|---|
| Pod ImagePullBackOff | 私库要凭据 | 建 regcred-hub-dfy secret，yaml 加 imagePullSecrets |
| Pod Pending（调度不上）| 没有 `app-tier=true` 标签节点，或 PVC 绑定失败 | `kubectl describe pod` 看 events；标签通过 `kubectl label node <x> apaas.definesys.com/app-tier=true` 加 |
| readinessProbe 失败 | 首次启动 init_db 慢（远程 MySQL 连慢） | 看 apaas-builder 容器日志里有没有 `Application startup complete`；改 probe initialDelay |
| nginx sidecar 404 / 无 index.html | initContainer cp 失败 | `kubectl logs apaas-builder-0 -c copy-frontend-dist`；检查镜像里是否真有 `/app/frontend/dist` |
| IDE 白屏 | CODE_SERVER_BASE_URL 和 ingress host 不一致 | backend.env 里 `CODE_SERVER_BASE_URL=https://<ingress host>/ide/` |
| SSE 请求被断 | ingress 漏配 proxy-buffering off | 已在 50-ingress.yaml annotations 里配，检查 nginx-ingress-controller 是否尊重 |
