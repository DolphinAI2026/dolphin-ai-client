# Rancher 单节点 Kubernetes 交付

这个目录用于客户现场的 Rancher/RKE2 单机部署。交付时不要求客户有源码，也不在 Rancher 里构建镜像；镜像由我们提前构建好，客户只需要让节点能拿到镜像，然后在 Rancher 的 `kubectl` 终端执行 `deploy.sh`。

## 交付物

- `deploy.sh`：可直接在 Rancher / kubectl 终端执行的交互式部署脚本。
- `apaas-builder-rancher-images-<tag>.tar`：建议包含 `apaas-builder:<tag>` 和 `nginx:alpine` 两个镜像。

## 我们这边制作镜像包

```bash
cd /Users/admin/Desktop/AI/ai-builder-new/apaas-builder-ai

TAG=customer-$(date +%Y%m%d)
BUILD_SHA=$(git rev-parse HEAD)
docker build --platform linux/amd64 \
  -f deploy/docker/Dockerfile \
  --build-arg VITE_BASE_URL=/ai-builder/ \
  --build-arg VITE_BUILD_SHA=${BUILD_SHA} \
  -t apaas-builder:$TAG \
  .

docker pull --platform linux/amd64 nginx:alpine
docker save apaas-builder:$TAG nginx:alpine \
  -o apaas-builder-rancher-images-$TAG.tar
```

把 `apaas-builder-rancher-images-$TAG.tar` 和 `deploy/rancher-single-node/deploy.sh` 放到客户可下载的链接即可。

## 客户现场导入镜像

在 Rancher 管理的那台单节点机器上导入镜像。RKE2 常见命令如下：

```bash
sudo /var/lib/rancher/rke2/bin/ctr \
  --address /run/k3s/containerd/containerd.sock \
  -n k8s.io images import apaas-builder-rancher-images-<tag>.tar
```

如果是 K3s，通常也可以用：

```bash
sudo k3s ctr -n k8s.io images import apaas-builder-rancher-images-<tag>.tar
```

导入后镜像名必须和部署脚本里填写的 `IMAGE` 完全一致，例如：

```text
apaas-builder:customer-20260602
```

如果客户有自己的内网镜像仓库，也可以把镜像推到仓库，脚本里填写仓库地址，例如：

```text
registry.example.com/ai-builder/apaas-builder:customer-20260602
```

## Rancher 里执行

进入 Rancher 的集群 `kubectl` 终端，执行：

```bash
sh deploy.sh
```

脚本会交互式询问：

- `DATABASE_URL`：PostgreSQL async URL
- `DOLPHIN_CODE_CONTROL_PLANE_URL`：Control Plane API 地址

默认使用 Dolphin/Control Plane 认证。`APAAS_TENANT_ID` 和 LLM 配置仍由客户部署完成后进入平台配置。

其他部署参数不在交互里打扰客户，默认值如下：

- `IMAGE=apaas-builder:latest`
- `NGINX_IMAGE=nginx:alpine`
- `NAMESPACE=apaas-builder`
- `APP_NAME=apaas-builder`
- `STORAGE_CLASS=local-path`
- `AUTH_PROVIDER=control_plane`
- `DOLPHIN_WORKSPACE_BASE_URL=https://dolphin.dfy.definesys.cn`
- `DATABASE_URL=postgresql+asyncpg://apaas:<password>@postgres:5432/apaas_builder`
- `INGRESS_CLASS=nginx`
- `BUILDER_HOST` 默认为空，Ingress 使用不限定域名的规则

需要时由交付人员用环境变量覆盖：

```bash
NAMESPACE=apaas-builder \
APP_NAME=apaas-builder \
IMAGE=apaas-builder:customer-20260602 \
NGINX_IMAGE=nginx:alpine \
STORAGE_CLASS=local-path \
WORKSPACES_SIZE=50Gi \
INGRESS_CLASS=nginx \
sh deploy.sh
```

部署完成后访问：

```text
http(s)://<客户 Rancher/Ingress 入口>/ai-builder/login
```

## 验证命令

```bash
kubectl -n apaas-builder get pods,svc,ingress,pvc
kubectl -n apaas-builder logs statefulset/apaas-builder -c apaas-builder --tail=80
```

如果现场没有 DNS，先把 `BUILDER_HOST` 解析到 Rancher 单节点的 ingress IP。
