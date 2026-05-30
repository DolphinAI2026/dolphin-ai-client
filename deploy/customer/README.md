# deploy/customer — 客户单机部署包

面向**客户单机 Docker Compose 交付**的加固部署包。复用 `deploy/docker/` 团队已验证的编排，
在其之上补齐客户部署真正缺的环节：随机密钥生成、必填项校验、健康检查、首个管理员 seed。

## 文件

| 文件 | 作用 |
|---|---|
| `deploy.sh` | 一键部署脚本（前置校验 → 生成密钥 → 拉起容器 → 健康检查 → seed 管理员） |
| `backend.env.template` | 后端业务环境变量模板（`__SET_ME__` 手填，`__GENERATE__` 脚本随机化） |
| （依赖）`../docker/docker-compose.yml` | 复用的容器编排 |
| （依赖）`../../backend/scripts/create_admin.py` | 创建/重置平台管理员（解「无 aPaaS 无管理员」阻塞） |

## 快速开始

```bash
# 首次：生成 backend.env（含随机密钥），按提示填 DB/aPaaS/LLM 必填项
IMAGE_TAR=/path/apaas-builder.tar ./deploy.sh
vi /data/apaas/backend.env          # 填好所有 __SET_ME__

# 再次：校验通过 → 部署 → 健康检查 → seed 管理员（末尾打印账号口令）
IMAGE_TAR=/path/apaas-builder.tar ./deploy.sh
```

常用覆盖变量：`APAAS_BUILDER_DATA_DIR`（默认 `/data/apaas`）、`IMAGE_TAG`、`IMAGE_TAR`、`PORT`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`。

## ⚠️ 重要

- 本脚本能做**配置层加固**（随机密钥、关 Web IDE、`VIBE_CODING_RUNTIME=host`），但**改不了代码/编排层的红线**。
  上生产前务必完成 [`docs/deploy-readiness-2026-05-30/部署前置要求.md`](../../docs/deploy-readiness-2026-05-30/部署前置要求.md) §7 的人工加固
  （平台代理鉴权、轮换泄漏密钥、删 docker.sock、容器非 root、nginx 安全头）。
- 完整前置与盘点见 `docs/deploy-readiness-2026-05-30/`（部署前置要求 / 05-部署盘点 / 04-安全报告）。
- `backend.env` 含明文凭据，权限 600，**勿提交、勿打入镜像**（已被 `.gitignore`/`.dockerignore` 排除）。
