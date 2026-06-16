# account-service 部署 + 桌面接线

account-service 是桌面账号的独立公网权威（设计见 `docs/superpowers/specs/2026-06-16-account-service-design.md`）。本文是部署 + 桌面端接线说明。第一版（Plan A）只含认证 + 开号；管账号 API / revocation / 管理后台见 Plan B/C。

## 部署 account-service（公网，如 agent.dfy 旁）

启动入口：`python -m services.account_service`（在 `backend/` 目录下跑，`services` 在 `backend/services/`）。

环境变量：

| env | 说明 |
|---|---|
| `ACCOUNT_SERVICE_DATABASE_URL` | 独立账号库（与 ai-builder 业务库分开） |
| `ACCOUNT_SERVICE_JWT_SECRET` | account-service 自己的 JWT 密钥，**必须与任何桌面 sidecar 不同**（信任边界，见 spec §4.1） |
| `ACCOUNT_SERVICE_PORT` | 监听端口（默认 8100） |

约束：
- 内部强制 `PUBLIC_ACCOUNT_BASE_URL=""`（authority 模式，本地校验账密）——entry 已写死，无需手动设。
- **生产必须 HTTPS**：federation 转发的是明文账密。

示例：
```bash
cd backend && \
ACCOUNT_SERVICE_DATABASE_URL="sqlite+aiosqlite:////data/account.db" \
ACCOUNT_SERVICE_JWT_SECRET="<account-service 专属密钥>" \
ACCOUNT_SERVICE_PORT=8100 \
.venv/bin/python -m services.account_service
```

## 开号

- HTTP：`POST /api/desktop-auth/admin/accounts`（需平台管理员 token），body `{username, password}`。
- 脚本：`python scripts/seed_desktop_account.py --username X --password Y`，把 `--data-dir` / `DATABASE_URL` 指向 account-service 的库。

开出来的桌面账号 `account_source='desktop'`，自带私有租户 + tenant_admin。

## 桌面端接线（federation）

桌面 sidecar（`backend/desktop_sidecar.py`）的 `PUBLIC_ACCOUNT_BASE_URL` 指向 account-service 的公网地址即可切 federation：

- 指向后：桌面登录走 federation——sidecar 把账密转发到 account-service 认证，认证过了本地镜像 user/tenant + 本地签 JWT。**新机器无需复制 app.db**。
- 留空：本地 authority 兜底（离线/无网时桌面用本机库自校验）。

注入点：`desktop_sidecar.py` 的 `build_env` 里 `PUBLIC_ACCOUNT_BASE_URL`，或由 Tauri 在拉起 sidecar 时传 env。

## 信任边界（重要）

- account-service **不签对外业务 token**：业务 JWT 由桌面 sidecar 用自己的密钥本地签。account-service 只回答"账密对不对、username 是谁"。
- 本地签的 token **只被该桌面实例信任**，account-service 和任何共享后端都不接受 sidecar 签的票。
- `is_platform_admin` 是 local-authority-only 概念，**不经 federation 流到桌面端**（federation 镜像出的用户恒为非平台管理员）。

详见 spec §4。
