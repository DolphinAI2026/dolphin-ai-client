# k8s 部署清单

apaas MCP Server 在 k8s（KubeSphere 集群）上的独立部署描述。

> 当前目录默认部署 `apaas-mcp-server-staging` 和 `apaas-mcp-server-prod` 两个工作负载。
> 默认 Ingress 只接 staging；正式入口切换文件放在 `cutover/`。旧的 `apaas-builder` 内 MCP
> manifests 已移到 `legacy-apaas-builder/`，只作为回滚和盘点参考，不再作为
> MCP 新增能力的修改位置。

## 环境信息

- 集群：`kubesphere.dfy.definesys.cn:6443`（KubeSphere v1.25.3 自建）
- 命名空间：`apaas-mcp-server`
- Registry：第一阶段复用 `hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:<tag>`
- staging Builder 前端：`https://agent.dfy.definesys.cn/mcp-server/`
- staging MCP endpoint：`https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp`
- staging Admin SPA：`https://agent.dfy.definesys.cn/mcp-server/admin/`
- prod 目标入口：`https://df-aigc.dfy.definesys.cn/ai-builder/`
- 旧正式入口当前仍指向 `apaas-builder`，切换前不要修改。

## 部署顺序

不要执行 `kubectl apply -f k8s/`：这个目录里有 `kustomization.yaml`、模板和
legacy 参考文件。请按下面顺序创建 Secret 后，再执行 `kubectl apply -k k8s/`。

```bash
# 0. 先准备 namespace
kubectl apply -f k8s/00-namespace.yaml

# 1. 准备 MySQL Secret（如改用公司 RDS，可跳过 10-mysql.yaml，直接在
#    staging/prod Secret 的 DATABASE_URL 填 RDS 地址）
kubectl -n apaas-mcp-server create secret generic mysql-credentials \
  --from-literal="MYSQL_ROOT_PASSWORD=<strong-root-password>" \
  --from-literal="MYSQL_USER=apaas_builder" \
  --from-literal="MYSQL_PASSWORD=<strong-app-password>" \
  --from-literal="MYSQL_DATABASE=apaas_builder" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f k8s/10-mysql.yaml

# 2. 准备独立 MCP Secret：
#    从 apaas-builder 现有 apaas-backend-env / mcp-server-config 迁移真实值，
#    再分别补齐 staging/prod 两套 Secret。prod/staging 数据库、PVC、Token
#    和工作区配置必须隔离。
MCP_API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
kubectl -n apaas-mcp-server create secret generic apaas-mcp-server-staging-env \
  --from-literal="MCP_API_KEY=$MCP_API_KEY" \
  --from-literal="MCP_API_KEYS=$MCP_API_KEY" \
  --from-literal="MCP_ALLOWED_HOSTS=agent.dfy.definesys.cn" \
  --from-literal="BASE_PATH=/mcp-server" \
  --from-literal="ROOT_PATH=/mcp-server" \
  --from-literal="PUBLIC_BASE_URL=https://agent.dfy.definesys.cn/mcp-server" \
  --from-literal="APAAS_BASE_URL=https://apaas-trial.definesys.cn/backend" \
  --from-literal="APAAS_TENANT_ID=<from-current-env>" \
  --from-literal="DATABASE_URL=mysql+aiomysql://apaas_builder:<password>@mysql:3306/apaas_builder" \
  --from-literal="JWT_SECRET_KEY=<generated-or-current>" \
  --from-literal="LLM_API_KEY=<from-current-env>" \
  --from-literal="ANTHROPIC_API_KEY=<from-current-env>" \
  --dry-run=client -o yaml | kubectl apply -f -

PROD_MCP_API_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
kubectl -n apaas-mcp-server create secret generic apaas-mcp-server-prod-env \
  --from-literal="MCP_API_KEY=$PROD_MCP_API_KEY" \
  --from-literal="MCP_API_KEYS=$PROD_MCP_API_KEY" \
  --from-literal="MCP_ALLOWED_HOSTS=df-aigc.dfy.definesys.cn,agent.dfy.definesys.cn" \
  --from-literal="BASE_PATH=/ai-builder" \
  --from-literal="ROOT_PATH=/ai-builder" \
  --from-literal="PUBLIC_BASE_URL=https://df-aigc.dfy.definesys.cn/ai-builder" \
  --from-literal="APAAS_BASE_URL=<prod-apaas-base-url>" \
  --from-literal="APAAS_TENANT_ID=<prod-tenant-id>" \
  --from-literal="DATABASE_URL=<prod-database-url-or-prod-replica-url>" \
  --from-literal="JWT_SECRET_KEY=<generated-or-current>" \
  --from-literal="LLM_API_KEY=<from-current-env>" \
  --from-literal="ANTHROPIC_API_KEY=<from-current-env>" \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. 部署 deployment / service / ingress
kubectl apply -k k8s/

# 4. 等 pod ready
kubectl -n apaas-mcp-server rollout status deployment/apaas-mcp-server-staging --timeout=180s
kubectl -n apaas-mcp-server rollout status deployment/apaas-mcp-server-prod --timeout=180s

# 5. 端到端验证
kubectl -n apaas-mcp-server port-forward svc/apaas-mcp-server-staging 8004:80 &
curl -s http://127.0.0.1:8004/api/health
curl -s http://127.0.0.1:8004/login | head
curl -s http://127.0.0.1:8004/admin/login | head
```

## 资源关系

```
agent.dfy.definesys.cn
        │
        │ /mcp-server(/|$)(.*) → rewrite /$2
        ▼
Ingress apaas-mcp-server-staging
        ▼
Service apaas-mcp-server-staging :80 → targetPort 8004
        ▼
Deployment apaas-mcp-server-staging
        - namespace: apaas-mcp-server
        - envFrom: Secret apaas-mcp-server-staging-env
        - image: apaas-builder-mcp-server:<tag>（第一阶段复用）
        - pvc: workspaces-staging
```

## 配置归属

- `apaas-builder`：只保留 AI Builder 自己的资源；MCP 相关资源后续清理迁出。
- `apaas-mcp-server`：承接 MCP Deployment / Service / Ingress / Secret / PVC。
- `apaas-mcp-server-staging`：内测入口 `/mcp-server`，使用 staging Secret 和 PVC。
- `apaas-mcp-server-prod`：正式候选入口 `/ai-builder`，切正式入口前只做预验证。
- Secret 先迁移现有可用配置，稳定后固化成独立键值，至少包含：
  `MCP_API_KEY(S)`、`MCP_ALLOWED_HOSTS`、`APAAS_BASE_URL`、`APAAS_TENANT_ID`、
  `DATABASE_URL`、`JWT_SECRET_KEY`、`LLM_API_KEY`、`ANTHROPIC_API_KEY`。
- Secret 示例见 `k8s/templates/apaas-mcp-server-env.secret.example.yaml`，不要直接 apply 占位值。
- MySQL Secret 示例见 `k8s/templates/mysql-credentials.secret.example.yaml`，不要直接 apply 占位值。

## 线上 v2 切流

2026-05-17 盘点发现线上已有 `apaas-mcp-server-v2`，当时通过
`https://agent.dfy.definesys.cn/mcp-server-v2/*` 验证；正式
`/mcp-server/*` 仍由 `apaas-builder` namespace 的旧 Ingress 占用。

2026-05-17 已完成切流。执行过的动作是先删除旧 Ingress，再使用切流专用文件把
`/mcp-server/*` 指到 v2 Service：

```bash
kubectl -n apaas-builder delete ingress apaas-builder-mcp-server
kubectl apply -f k8s/cutover/ingress-agent-mcp-server-to-v2.yaml
```

后续修正：
- `PREVIEW_BASE_URL` 已改为 `https://agent.dfy.definesys.cn/mcp-server/api`，新草稿预览不再生成 `/mcp-server-v2/*`。
- 当前线上镜像为 `hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:20260518-0412-clear-app-id-contract-amd64`，修复了 MCP Header 身份在内部 generate / force regenerate 阶段丢失的问题，避免子表回指主表的隐藏关联阻断数据选择器回写，从正式 MCP 注册工具的 schema 与函数签名中移除 `tenant_id` / `user_id` 旧身份参数，让 DB 回填的“线上已有”aPaaS 平台管理员账号可编辑、登录和持久化，并在刷新 aPaaS 租户时同步本地 `tenants` + 默认 `platform_envs`，供后续应用/工作区绑定使用；同步时会复用已有同编码本地租户并补齐 `apaas_tenant_id_str`，避免旧数据唯一键冲突。aPaaS 租户页默认读取本地缓存，只有点击“刷新租户”才请求 aPaaS 并同步；admin SPA 构建 base 固定为 `/mcp-server/admin/`。设计文档模板现在明确“原文编码优先保留”：合法的连续英文编码不再被主动拆成下划线形式，只有非法/重复/保留字/超长时才最小化改名并说明映射。后端同时保留 `/api/mcp-platform/login` 兼容入口，admin SPA 构建期固定 `VITE_API_BASE_URL=/mcp-server/api`，并为 `/mcp-server/admin/*` history 路由提供 index fallback，避免登录页刷新或旧缓存导致 404。`promote_draft_to_app` 返回中明确区分 `local_app_id/app_id` 与 `apaas_app_id`，并在 summary/id_guide/next_actions 中提示发布、自开发和 aPaaS 工具必须使用 `apaas_app_id`。

切完再验证：

```bash
curl -s https://agent.dfy.definesys.cn/mcp-server/api/health
```

Dolphin MCP 代理服务 `apaas-builder-ai-mcp` 也已保存为正式新地址：

```text
https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp
```

## 升级

```bash
# build + push 新 image
TAG=staging-$(date +%Y%m%d-%H%M)
docker build \
  --build-arg BUILDER_BASE_PATH=/mcp-server/ \
  --build-arg ADMIN_BASE_PATH=/mcp-server/admin/ \
  --build-arg ADMIN_API_BASE_URL=/mcp-server/api \
  -t hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG .
docker push hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG

# 更新独立 MCP deployment
kubectl -n apaas-mcp-server set image deployment/apaas-mcp-server-staging \
  apaas-mcp-server=hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG
```

prod 候选镜像需要用 `/ai-builder` 构建：

```bash
TAG=prod-candidate-$(date +%Y%m%d-%H%M)
docker build \
  --build-arg BUILDER_BASE_PATH=/ai-builder/ \
  --build-arg ADMIN_BASE_PATH=/ai-builder/admin/ \
  --build-arg ADMIN_API_BASE_URL=/ai-builder/api \
  -t hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG .
docker push hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG

kubectl -n apaas-mcp-server set image deployment/apaas-mcp-server-prod \
  apaas-mcp-server=hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG
```
