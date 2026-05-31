# K8s MCP Server 迁移 Runbook

## 目标边界

- 线上先不直接改，先完成资源盘点、配置固化和切流步骤确认。
- 不再在 `apaas-builder` 里修 MCP；`apaas-builder` 后续只保留 AI Builder。
- MCP 统一迁到 `apaas-mcp-server` namespace。
- 第一阶段继续复用现有镜像：`hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:<tag>`。
- `apaas-mcp-server` 自己维护独立 Ingress：
  `https://agent.dfy.definesys.cn/mcp-server/*`。
- 新 MCP 地址只配置：
  `https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp`。
- MCP 管理台只配置：
  `https://agent.dfy.definesys.cn/mcp-server/admin/`。
- 旧地址只做临时兼容转发，验证稳定后下线；不再对外宣传。

## 当前资源盘点

### 旧位置：`apaas-builder`

仓库历史 manifests 已移到 `k8s/legacy-apaas-builder/`，只作参考：

- Deployment：`apaas-builder-mcp-server`
- Service：`apaas-builder-mcp-server`
- Ingress：`apaas-builder-mcp-server`
- Secret 依赖：
  - `mcp-server-config`
  - `apaas-backend-env`
- 旧 Ingress host：
  - `df-aigc.dfy.definesys.cn/mcp-server/*`
  - `agent.dfy.definesys.cn/mcp-server/*`

处理原则：只迁出和清理，不在这里继续增强 MCP。

### 新位置：`apaas-mcp-server`

默认 manifests：

- `k8s/00-namespace.yaml`
- `k8s/10-mysql.yaml`
- `k8s/20-mcp-server.yaml`
- `k8s/30-ingress.yaml`
- `k8s/kustomization.yaml`
- `k8s/templates/apaas-mcp-server-env.secret.example.yaml`（示例，不直接 apply）
- `k8s/templates/mysql-credentials.secret.example.yaml`（示例，不直接 apply）
- `k8s/cutover/ingress-agent-mcp-server-to-v2.yaml`（切流专用，不在默认 kustomize）

目标资源：

- Namespace：`apaas-mcp-server`
- Secret：`apaas-mcp-server-env`
- Deployment：`apaas-mcp-server`
- Service：`apaas-mcp-server`
- Ingress：`apaas-mcp-server`
- PVC：`workspaces`
- MySQL Secret/StatefulSet：`mysql-credentials` / `mysql`

### 2026-05-17 线上只读盘点

`apaas-builder` 仍占用正式 MCP 路径：

- Deployment：`apaas-builder-mcp-server`，Ready `1/1`，Age `4d5h`
- Service：`apaas-builder-mcp-server`，`8004/TCP`
- Ingress：`apaas-builder-mcp-server`
  - Hosts：`df-aigc.dfy.definesys.cn,agent.dfy.definesys.cn`
  - Path：`/mcp-server(/|$)(.*)`
- Secret：`apaas-backend-env`、`mcp-server-config`

`apaas-mcp-server` 已存在候选 v2：

- Deployment：`apaas-mcp-server-v2`，Ready `1/1`，Age `2d21h`
- Service：`apaas-mcp-server-v2`，`80/TCP`
- Ingress：`apaas-mcp-server-v2`
  - Host：`agent.dfy.definesys.cn`
  - Path：`/mcp-server-v2(/|$)(.*)`
  - Backend：`apaas-mcp-server-v2:80`
- Image：`hub-snapshots.dfy.definesys.cn/mars/apaas-builder-mcp-server:20260515-user-token`
- ImagePullSecret：`hub-dfy-pull`
- Env Secret：`apaas-mcp-server-env`
- PVC：`workspaces-v2`

公网健康检查：

- `https://agent.dfy.definesys.cn/mcp-server/api/health`：200，当前仍来自旧 `apaas-builder`
- `https://agent.dfy.definesys.cn/mcp-server-v2/api/health`：200，来自新 `apaas-mcp-server-v2`

### 2026-05-17 切流结果

已完成正式入口切流：

- 删除旧 Ingress：`apaas-builder/apaas-builder-mcp-server`
- 保留旧兼容入口：
  - Ingress：`apaas-builder/apaas-builder-mcp-server-legacy-df-aigc`
  - Host：`df-aigc.dfy.definesys.cn`
  - Backend：`apaas-builder-mcp-server:8004`
- 新增正式入口：
  - Ingress：`apaas-mcp-server/apaas-mcp-server-final`
  - Host：`agent.dfy.definesys.cn`
  - Path：`/mcp-server(/|$)(.*)`
  - Backend：`apaas-mcp-server-v2:80`

健康检查：

- `https://agent.dfy.definesys.cn/mcp-server/api/health`：200
- `https://agent.dfy.definesys.cn/mcp-server-v2/api/health`：200
- `https://df-aigc.dfy.definesys.cn/mcp-server/api/health`：200

Dolphin MCP 代理服务 `apaas-builder-ai-mcp` 已更新并保存：

- 请求地址：`https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp`
- 连接测试成功，返回 77 个工具，包含 `list_apaas_apps`

## Secret 迁移

先从现有可用配置迁移，再固化成 `apaas-mcp-server` 自己的 Secret。

必须确认的键：

- `MCP_API_KEY`
- `MCP_API_KEYS`
- `MCP_ALLOWED_HOSTS=agent.dfy.definesys.cn`
- `APAAS_BASE_URL`
- `APAAS_TENANT_ID`
- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `LLM_API_KEY`
- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_API_KEY`
- `DOLPHIN_SERVER_URL`
- `DOLPHIN_AGENT_CODE`
- `DOLPHIN_COPILOT_AGENT_CODE`
- `DOLPHIN_CODING_AGENT_CODE`
- `DOLPHIN_USE_USER_TOKEN`
- `AI_BUILDER_CHAT_DEEPLINK_BASE=https://agent.dfy.definesys.cn`
- `MCP_INTERNAL_BASE=http://127.0.0.1:8004/api`

注意：真实密钥不要写入 git。Secret 键名和占位值只放在
`k8s/templates/apaas-mcp-server-env.secret.example.yaml`，默认部署资源不会 apply
这个模板。

## 执行步骤

注意：不要执行 `kubectl apply -f k8s/`。该目录包含 `kustomization.yaml`、
模板和 legacy 参考文件。Secret 用真实值单独创建后，再执行
`kubectl apply -k k8s/`。

1. 冻结旧位置

   确认 `apaas-builder` 后续不再部署 MCP 新版本，只保留当前可回滚状态。

2. 准备新命名空间和数据库 Secret

   ```bash
   kubectl apply -f k8s/00-namespace.yaml

   kubectl -n apaas-mcp-server create secret generic mysql-credentials \
     --from-literal="MYSQL_ROOT_PASSWORD=<strong-root-password>" \
     --from-literal="MYSQL_USER=apaas_builder" \
     --from-literal="MYSQL_PASSWORD=<strong-app-password>" \
     --from-literal="MYSQL_DATABASE=apaas_builder" \
     --dry-run=client -o yaml | kubectl apply -f -

   kubectl apply -f k8s/10-mysql.yaml
   ```

3. 创建或更新独立 Secret

   ```bash
   kubectl -n apaas-mcp-server create secret generic apaas-mcp-server-env \
     --from-literal="MCP_API_KEY=<current-or-new-key>" \
     --from-literal="MCP_API_KEYS=<current-or-new-key>" \
     --from-literal="MCP_ALLOWED_HOSTS=agent.dfy.definesys.cn" \
     --from-literal="APAAS_BASE_URL=<current-value>" \
     --from-literal="APAAS_TENANT_ID=<current-value>" \
     --from-literal="DATABASE_URL=<current-or-new-db-url>" \
     --from-literal="JWT_SECRET_KEY=<current-or-new-secret>" \
     --from-literal="LLM_API_KEY=<current-value>" \
     --from-literal="ANTHROPIC_API_KEY=<current-value>" \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

4. 部署 MCP Server 和独立 Ingress

   ```bash
   kubectl apply -k k8s/
   kubectl -n apaas-mcp-server rollout status deployment/apaas-mcp-server --timeout=180s
   ```

5. 验证新入口

   ```bash
   # 候选新服务，切流前验证
   curl -s https://agent.dfy.definesys.cn/mcp-server-v2/api/health

   curl -s https://agent.dfy.definesys.cn/mcp-server/api/health

   curl -X POST https://agent.dfy.definesys.cn/mcp-server-v2/api/mcp/mcp \
     -H "Authorization: Bearer <MCP_API_KEY>" \
     -H "Accept: application/json, text/event-stream" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
   ```

6. 切 Dolphin MCP 配置

   所有新配置只填：

   ```text
   https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp
   ```

7. 切正式路径到新 namespace

   当前正式 `/mcp-server/*` 仍被 `apaas-builder` 的旧 Ingress 占用。
   切流时先删旧 Ingress，再创建新 namespace 的正式路径 Ingress。

   ```bash
   kubectl -n apaas-builder delete ingress apaas-builder-mcp-server
   kubectl apply -f k8s/cutover/ingress-agent-mcp-server-to-v2.yaml
   ```

   切完后验证正式地址：

   ```bash
   curl -s https://agent.dfy.definesys.cn/mcp-server/api/health

   curl -X POST https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp \
     -H "Authorization: Bearer <MCP_API_KEY>" \
     -H "Accept: application/json, text/event-stream" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
   ```

8. 稳定后清理旧位置

   在验证期结束后，从 `apaas-builder` 删除 MCP Deployment / Service，
   旧地址转发也一起下线。

   ```bash
   kubectl -n apaas-builder delete service apaas-builder-mcp-server
   kubectl -n apaas-builder delete deployment apaas-builder-mcp-server
   ```

## 验证清单

- `kubectl -n apaas-mcp-server get pods`：MCP pod Ready。
- `kubectl -n apaas-mcp-server logs deploy/apaas-mcp-server`：启动无缺少 env 报错。
- `/mcp-server/api/health` 返回 200。
- `/mcp-server/admin/` 能打开并登录。
- `tools/list` 返回预期工具列表。
- `list_apaas_apps` 能访问 aPaaS 平台 API。
- Dolphin 测试连接通过。
- 调用日志能写入并在管理台查看。
- `agent.dfy.definesys.cn/ai-builder/` 不受影响。
- `df-aigc.dfy.definesys.cn/ai-builder/` 不受影响。

## 回滚

- Dolphin 侧把 MCP URL 改回切流前地址。
- 保留旧 `apaas-builder` MCP 资源到验证完成前，作为短期回滚点。
- 如新命名空间异常：

  ```bash
  kubectl -n apaas-mcp-server scale deployment/apaas-mcp-server --replicas=0
  ```

回滚后继续排查 `apaas-mcp-server`，不要回到 `apaas-builder` 里做新增修复。
