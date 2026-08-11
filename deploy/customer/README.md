# deploy/customer — 客户单机部署包

面向**客户单机 Docker Compose 交付**的加固部署包。复用 `deploy/docker/` 团队已验证的编排，
在其之上补齐客户部署真正缺的环节：单一配置文件、随机密钥生成、必填项校验、健康检查、首个管理员 seed。

## 文件

| 文件 | 作用 |
|---|---|
| `deploy.sh` | 一键部署脚本（前置校验 → 生成密钥 → 拉起容器 → 健康检查 → seed 管理员） |
| `backend.env.template` | 唯一客户配置模板（镜像/端口/workspace/JDK/PostgreSQL/认证/密钥都在这里） |
| （依赖）`../docker/docker-compose.yml` | 复用的容器编排 |
| （依赖）`../../backend/scripts/create_admin.py` | 创建/重置平台管理员（解「无 aPaaS 无管理员」阻塞） |

客户只需要维护一份文件：`/data/apaas/backend.env`。部署脚本会从它派生 `/data/apaas/compose.env` 给 Docker Compose 插值使用；`compose.env` 是脚本内部产物，不需要客户手工编辑。

## 快速开始

```bash
# 首次：生成唯一配置 backend.env（含随机密钥），按提示填 PostgreSQL/Control Plane
IMAGE_TAR=/path/apaas-builder.tar ./deploy.sh
vi /data/apaas/backend.env          # 只改这一份配置文件，填好所有 __SET_ME__

# 再次：校验通过 → 部署 → 健康检查 → seed 管理员（末尾打印账号口令）
IMAGE_TAR=/path/apaas-builder.tar ./deploy.sh
```

常用配置项都写在 `/data/apaas/backend.env`：`IMAGE_TAG`、`IMAGE_TAR`、`PORT`、`VITE_BASE_URL`、`WORKSPACES_DIR`、`APAAS_BACKEND_JDK_VERSION` 等。

默认认证模式为 `control_plane`。Builder 通过
`DOLPHIN_WORKSPACE_BASE_URL=https://dolphin.dfy.definesys.cn` 登录并保存用户 Token，
再以 `Authorization: Bearer <Dolphin Token>` 调用 `DOLPHIN_CODE_CONTROL_PLANE_URL`。
Control Plane 运行环境必须同时配置
`CONTROL_PLANE_AUTH_FULL_WORKSPACE_BASE_URL=https://dolphin.dfy.definesys.cn`。

少数脚本级覆盖仍可用：`APAAS_BUILDER_DATA_DIR`（决定首次生成配置的位置，默认 `/data/apaas`）、`ADMIN_USERNAME`、`ADMIN_PASSWORD`。

## Code 工作台连接

客户以 Kubernetes 方式同时部署 Control Plane、ai-builder 和 Agent Runtime 时，
`workspace/open` 会返回两类地址：`specReviewUrl` 供浏览器通过公网 ai-builder 打开工作台，
`runtimeBaseUrl` 供 ai-builder 后端通过集群内 Service 访问 Runtime。ai-builder 不会把
`runtimeBaseUrl`、Runtime Cookie 或启动 Token 返回浏览器。

现场发布顺序固定为：

1. 先发布 Control Plane，确认 `workspace/open` 同时返回公网 `specReviewUrl` 和形如
   `http://<service>.<namespace>.svc.cluster.local:8080` 的 `runtimeBaseUrl`。
2. 再发布 ai-builder。老版本 Control Plane 没有 `runtimeBaseUrl` 时仍能运行，但会继续走公网 Runtime fallback。
3. 公网 L7 会缓冲小 SSE 首包时，在 `backend.env` 配置
   `BUILDER_SSE_PADDING_BYTES=16384`；无该问题的环境保持默认 `0`。
4. 新建工作区验证首次连接，再等待一次 Runtime 凭证续期，确认页面不中断且 ai-builder 日志不再访问公网 Runtime 域名。
5. 验证 Builder JS/CSS 无 gzip 解码错误。

该方案不需要修改公网网关、负载均衡或 Ingress。前提是 ai-builder Pod 能解析并访问
Control Plane 返回的集群内 Service DNS；单机 Docker Compose 不具备该网络条件时会自动使用现有公网地址 fallback。

## ⚠️ 重要

- 本脚本能做**配置层加固**（随机密钥、最小化 backend.env），但**改不了代码/编排层的红线**。
  上生产前务必完成 [`docs/deploy-readiness-2026-05-30/部署前置要求.md`](../../docs/deploy-readiness-2026-05-30/部署前置要求.md) §7 的人工加固
  （平台代理鉴权、轮换泄漏密钥、删 docker.sock、容器非 root、nginx 安全头）。
- 完整前置与盘点见 `docs/deploy-readiness-2026-05-30/`（部署前置要求 / 05-部署盘点 / 04-安全报告）。
- `backend.env` 含明文凭据，权限 600，**勿提交、勿打入镜像**（已被 `.gitignore`/`.dockerignore` 排除）。
