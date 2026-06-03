# Dev KubeSphere 终端部署留档

适用场景：本机负责构建并推送镜像，KubeSphere 的 `kubectl` Web 终端只负责执行生成好的部署脚本。

## 当前可用脚本

本地保留的可执行 payload：

```bash
.run/deploy-dev-kubesphere-terminal.sh
```

当前已验证镜像：

```bash
hub.dfy.definesys.cn/ai-builder/apaas-builder:dev-20260601-mcp-origin-001
```

执行方式：复制 `.run/deploy-dev-kubesphere-terminal.sh` 全文，粘贴到 KubeSphere 的 `kubectl` 终端执行。

## 重新生成

以后需要重新部署 dev 时，在本机执行：

```bash
ALLOW_DIRTY=1 PUSH_DEV=0 IMAGE_TAG=dev-YYYYMMDD-<change-name>-001 scripts/deploy_k8s_dev_web_terminal.sh
```

脚本会：

- 构建并推送 `hub.dfy.definesys.cn/ai-builder/apaas-builder:${IMAGE_TAG}`
- 生成 `.run/deploy-dev-kubesphere-terminal.sh`
- 自动复制 payload 到 macOS 剪贴板

然后去 KubeSphere 终端粘贴执行。

## 成功标准

终端末尾必须看到：

```text
HTTP 200
MCP_TOOLS_HTTP 200
done: https://agent.dfy.definesys.cn/ai-builder/login
```

`MCP_TOOLS_HTTP 200` 是硬性标准；不是 200 就不要认为部署完成。

## MCP 链路要求

这次 MCP 接入页线上可用依赖以下四点，后续改部署时不要漏：

- `scripts/deploy_k8s_dev*.sh` 传入 `VITE_MCP_PUBLIC_BASE=https://${DEV_HOST}`
- `deploy/docker/Dockerfile` 在 admin-spa 构建阶段接收并导出 `VITE_MCP_PUBLIC_BASE`
- `backend/app/main.py` 挂载真实 `/api/mcp/mcp`，并在主 FastAPI lifespan 中启动 FastMCP `session_manager`
- `backend/app/mcp_server.py` 配置了 `MCP_ALLOWED_HOSTS` 时，也要允许对应 `Origin`，否则浏览器请求会被 SDK 拦成 `403 Invalid Origin header`

## 已清理

`.run` 里只保留当前 payload：

```text
.run/deploy-dev-kubesphere-terminal.sh
```

旧的临时排障脚本、日志和 pid 文件已删除，避免以后误执行。
