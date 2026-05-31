# aPaaS MCP Server 正式/内测双环境实施方案

## 目标

把未来主线收敛到一个仓库、一个服务类型、两个运行环境：

```text
主仓库：apaas-builder-mcp-server
主服务：apaas-mcp-server

prod    正式环境，部署 main 分支镜像
staging 内测环境，部署 develop 或 release 分支镜像
```

正式域名不换：

```text
https://df-aigc.dfy.definesys.cn/ai-builder/
```

当前旧服务 `apaas-builder` 先保留不动，作为回滚兜底。等新的 `apaas-mcp-server-prod` 验证通过后，只切 Ingress / 路由指向。

## 当前状态

```text
正式线上：
https://df-aigc.dfy.definesys.cn/ai-builder/
  -> apaas-builder
  -> 老线上服务，先不动

MCP 内测：
https://agent.dfy.definesys.cn/mcp-server/
  -> apaas-mcp-server 或 apaas-mcp-server-v2
  -> 新 MCP 能力测试中
```

现在看到多个工作负载是过渡状态。后续要整理成固定命名：

```text
apaas-mcp-server-prod
apaas-mcp-server-staging
```

## 目标架构

```text
Git 仓库
┌──────────────────────────────┐
│ apaas-builder-mcp-server      │
│                              │
│ main     -> 正式版本          │
│ develop  -> 内测版本          │
│ release/* -> 上线候选版本     │
└───────────────┬──────────────┘
                │
        ┌───────┴────────┐
        │                │
        ▼                ▼
┌────────────────┐  ┌────────────────┐
│ prod            │  │ staging         │
│ main 镜像        │  │ develop/release │
│ apaas-mcp-server│  │ apaas-mcp-server│
│ 正式域名 /ai-builder │ 内测入口 /mcp-server │
└────────────────┘  └────────────────┘
```

注意：这是两个服务实例，不是一个服务里跑两份代码。

```text
apaas-mcp-server-prod     跑 main 镜像
apaas-mcp-server-staging  跑 develop/release 镜像
```

## 服务边界

每个环境只需要一个常驻主服务：

```text
apaas-mcp-server-prod
  - MCP endpoint
  - 后端 API
  - Builder 前端 dist
  - Admin dist
  - 沙箱调度能力

apaas-mcp-server-staging
  - 同上，用于内测
```

前端不单独起服务。前端和 admin-spa 都作为 dist 打进镜像。

沙箱不是主服务。沙箱是运行时按需创建/调用的资源：

```text
主服务常驻：
apaas-mcp-server-prod
apaas-mcp-server-staging

沙箱按需：
vibe-sandbox-xxxx
workspace-xxxx
preview-xxxx
```

prod 和 staging 的沙箱、工作区、PVC、数据库配置要隔离，避免串数据。

## 实施阶段

### 1. 冻结旧正式服务

保留现有 `apaas-builder`：

```text
namespace/project: apaas-builder
workload: apaas-builder
入口: https://df-aigc.dfy.definesys.cn/ai-builder/
```

要求：

- 不删除。
- 不缩容。
- 不改配置。
- 只允许紧急 hotfix。
- 作为切换失败时的回滚目标。

### 2. 规范 MCP staging

在 `apaas-mcp-server` 项目下保留或新建内测工作负载：

```text
workload: apaas-mcp-server-staging
service: apaas-mcp-server-staging
image: hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:<staging-tag>
入口: https://agent.dfy.definesys.cn/mcp-server/
```

staging 用于继续验证：

- 登录
- 租户切换
- 租户绑定环境
- 应用列表
- 菜单解析数量
- 模型解析数量
- 字段解析数量
- 权限解析
- 设计文档生成
- Dolphin 调 MCP
- Admin 配置页
- 沙箱/预览/工作区

### 3. 准备 MCP prod

在同一个项目下新建正式工作负载：

```text
workload: apaas-mcp-server-prod
service: apaas-mcp-server-prod
image: hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:<prod-candidate-tag>
```

prod 先不要接正式域名。先用临时 Ingress 或 port-forward 验证。

prod 需要使用正式配置：

```text
BASE_PATH=/ai-builder
ROOT_PATH=/ai-builder
PUBLIC_BASE_URL=https://df-aigc.dfy.definesys.cn/ai-builder
MCP_ALLOWED_HOSTS=df-aigc.dfy.definesys.cn,agent.dfy.definesys.cn
```

如果代码里仍写死 `/mcp-server`，必须先改成配置项，否则正式路径 `/ai-builder/` 会出问题。

### 4. 数据和配置检查

切换前确认：

- prod 数据库连接是否指向正式库或正式库副本。
- staging 数据库不能误连正式库。
- MCP API Key / Service Token 已配置。
- LLM 配置完整。
- aPaaS 平台地址、租户、环境绑定正确。
- Dolphin 侧 MCP endpoint 可配置到新地址。
- 工作区 PVC 与沙箱目录隔离。

建议先用正式库副本演练一次。

### 5. 正式切换

切换时只改正式入口后端指向：

```text
切换前：
https://df-aigc.dfy.definesys.cn/ai-builder/
  -> service/apaas-builder

切换后：
https://df-aigc.dfy.definesys.cn/ai-builder/
  -> service/apaas-mcp-server-prod
```

不要换域名。不要让用户改地址。

Ingress 需要确保：

```text
host: df-aigc.dfy.definesys.cn
path: /ai-builder
backend service: apaas-mcp-server-prod
```

同时设置正确的前缀头：

```text
X-Forwarded-Prefix: /ai-builder
X-Forwarded-Host: df-aigc.dfy.definesys.cn
```

### 6. 切后验证

切换后立即验证：

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  https://df-aigc.dfy.definesys.cn/ai-builder/api/health
```

业务验证清单：

- 正式入口能打开。
- 登录正常。
- 当前租户显示正确。
- 切换租户后能查到应用。
- 不需要手动找环境，租户绑定环境能自动使用。
- 应用解析数量正确。
- 菜单、模型、字段、权限数量正确。
- 设计文档能完整生成。
- MCP endpoint 鉴权正常。
- Dolphin 调用 MCP 正常。
- 沙箱能创建、预览、释放。
- Admin 页能打开并保存配置。

### 7. 回滚方案

如果切换后出现严重问题，不改代码，直接把 Ingress 指回旧服务：

```text
https://df-aigc.dfy.definesys.cn/ai-builder/
  -> service/apaas-builder
```

旧 `apaas-builder` 在观察期内必须保持运行。

观察期建议：

```text
至少 1-3 天
```

稳定后再考虑：

- `apaas-builder` 缩容到 0。
- 保留镜像和配置作为回滚参考。
- 再过一段时间后归档旧仓库 `apaas-builder-ai`。

## 日常更新、合并、部署流程

### 1. 拉取同事改动

如果同事仍然把改动推到旧仓库 `apaas-builder-ai` 的测试分支，先只做同步和盘点，不直接部署到正式环境。

```bash
cd /Users/admin/Desktop/AI/apaas-buider-mcp/apaas-builder-ai
git fetch origin --prune
git status -sb
git log --oneline HEAD..origin/local/ui-redesign-2026-05-20
```

如果当前分支只落后远端，并且本地有未提交改动，用 autostash 快进：

```bash
git pull --ff-only --autostash
```

拉完后记录新增提交、变更文件和是否需要迁移到 MCP 主线。

本次已拉取的同事提交：

```text
87b6f17 feat(browser-control): Phase 3d MVP — Browser viewport mini preview MJPEG 嵌入
6cb7ce0 fix(apaas-platform): env.token 空时自动 login 拿 token (首次自愈)
```

### 2. 判断是否合入 MCP 主线

后续主线是 `apaas-builder-mcp-server`，所以旧仓库里的改动要分三类处理：

```text
必须迁移：
- MCP 工具能力
- 租户 / 环境 / 应用解析
- 菜单 / 模型 / 字段 / 权限读取
- 设计文档生成
- Dolphin 调用链路
- 沙箱 / 工作区能力

可以迁移：
- 调试 UI
- Admin 配置入口
- 浏览器控制辅助能力

可以不迁移：
- 旧 AI Builder 专属页面
- 过渡期 UI 调整
- 已经被 MCP 主线替代的实现
```

不要把旧仓库整个 merge 到 MCP 仓库。优先按功能点 cherry-pick 或手动迁移，避免把旧 UI 和历史部署配置一起带进去。

### 3. 合并分支规则

未来固定使用一个主仓库：

```text
apaas-builder-mcp-server
```

分支含义：

```text
main       正式稳定版本，只部署 prod
develop    内部测试版本，只部署 staging
release/*  上线候选版本，用于从 staging 推向 prod
hotfix/*   正式紧急修复
```

推荐流程：

```text
功能开发 -> feature/*
合入内测 -> develop
内测通过 -> release/*
上线准备 -> 合入 main
正式部署 -> apaas-mcp-server-prod
```

### 4. staging 部署流程

staging 用于验证新能力，入口保持：

```text
https://agent.dfy.definesys.cn/mcp-server/
```

构建并推送 staging 镜像：

```bash
cd /Users/admin/Desktop/AI/apaas-buider-mcp/apaas-builder-mcp-server
TAG=staging-$(date +%Y%m%d-%H%M)
docker build -t hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG .
docker push hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG
```

更新 staging 工作负载：

```bash
kubectl -n apaas-mcp-server set image deployment/apaas-mcp-server-staging \
  apaas-mcp-server=hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG

kubectl -n apaas-mcp-server rollout status deployment/apaas-mcp-server-staging --timeout=180s
```

验证：

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  https://agent.dfy.definesys.cn/mcp-server/api/health
```

### 5. prod 准备流程

prod 不直接从开发分支部署。先从已通过 staging 的版本创建 release 或确认 main 合并点。

构建 prod 候选镜像：

```bash
TAG=prod-candidate-$(date +%Y%m%d-%H%M)
docker build -t hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG .
docker push hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG
```

先更新 `apaas-mcp-server-prod`，但不要立刻切正式入口：

```bash
kubectl -n apaas-mcp-server set image deployment/apaas-mcp-server-prod \
  apaas-mcp-server=hub.dfy.definesys.cn/ai-builder/apaas-builder-mcp-server:$TAG

kubectl -n apaas-mcp-server rollout status deployment/apaas-mcp-server-prod --timeout=180s
```

用临时入口、port-forward 或内部检查确认 prod 配置可用。

### 6. 正式入口切换

正式入口只认：

```text
https://df-aigc.dfy.definesys.cn/ai-builder/
```

切换时只改 Ingress 后端：

```text
切换前：
/ai-builder -> service/apaas-builder

切换后：
/ai-builder -> service/apaas-mcp-server-prod
```

切完立即验证：

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  https://df-aigc.dfy.definesys.cn/ai-builder/api/health
```

### 7. 合并部署记录模板

每次更新后在任务记录里写清楚：

```text
来源分支：
合入目标：
新增提交：
影响模块：
是否迁移到 MCP 主线：
staging 镜像：
staging 验证结果：
prod 镜像：
正式入口是否已切换：
回滚点：
```

## 最终状态

```text
正式：
https://df-aigc.dfy.definesys.cn/ai-builder/
  -> apaas-mcp-server-prod
  -> main 分支镜像

内测：
https://agent.dfy.definesys.cn/mcp-server/
  -> apaas-mcp-server-staging
  -> develop/release 分支镜像

旧服务：
apaas-builder
  -> 先保留
  -> 稳定后缩容
  -> 最后归档
```

## 给执行会话的任务描述

```text
请按 docs/operations/prod-staging-cutover-plan.md 执行 MCP Server 双环境整理。

要求：
1. 不改、不删、不缩容现有 apaas-builder，旧正式服务先保留作为回滚。
2. 在 apaas-builder-mcp-server 主线内准备两个部署实例：
   - apaas-mcp-server-prod
   - apaas-mcp-server-staging
3. staging 继续服务 https://agent.dfy.definesys.cn/mcp-server/。
4. prod 需要兼容正式入口 https://df-aigc.dfy.definesys.cn/ai-builder/。
5. 前端和 admin-spa 不单独起服务，作为 dist 打入 apaas-mcp-server 镜像。
6. 沙箱作为按需资源，prod/staging 必须隔离工作区、PVC、数据库和配置。
7. 切换正式入口时只改 Ingress 后端，从 apaas-builder 指到 apaas-mcp-server-prod。
8. 切换失败时立即把 Ingress 指回 apaas-builder。
```
