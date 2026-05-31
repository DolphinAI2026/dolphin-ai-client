# apaas-builder-mcp-server 重构总览

> 2026-05-11 立项 · 接 2026-05-11 一日 17+ commits 的 ai-builder 重构之后
> 用户决策：从 ai-builder 完整 SPA + backend 抽出一个**纯 MCP server**，dolphin 是唯一入口，无 iframe 嵌套

## 目标架构

```
┌─────────────────────────────────────────────────┐
│              dolphin 平台（唯一入口）             │
│  AI-Builder agent / AI-Coding agent              │
└─────────┬───────────────────────────────────────┘
          │ dolphin omnigate → HTTPS POST
          │ /api/mcp/mcp (streamable HTTP)
          ↓
┌─────────────────────────────────────────────────┐
│         apaas-builder-mcp-server (新 repo)       │
│                                                  │
│   ┌──────────────────────────────────────────┐  │
│   │ FastMCP + 58 MCP 工具                     │  │
│   │  - 49 个现有（Builder + Coding 主线）     │  │
│   │  - 9 个新 Vibe Coding 工具（沙箱开发）    │  │
│   └────────────┬─────────────────────────────┘  │
│                │                                 │
│   ┌────────────┴───┐  ┌────────────────────┐    │
│   │ apaas client   │  │ dolphin embed_auth │    │
│   └────────┬───────┘  └────────────────────┘    │
│            │                                     │
│   ┌────────┴──────────────────────────────┐    │
│   │  MySQL apaas_builder（复用同一个 DB）  │    │
│   └────────────────────────────────────────┘    │
│            │                                     │
│            ↓ 同 IP 不同端口（或独立 ECS）        │
│   ┌────────┴──────────────────────────────┐    │
│   │  podman 沙箱集群（Vibe Coding 运行时） │    │
│   └────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
            ↓ /api/admin/* （admin SPA 用）
┌──────────────────────────────────────────────────┐
│  admin SPA (轻量 Vue 3 SPA，仅 platform_admin 进)│
│  - /admin/tenants  租户管理                       │
│  - /admin/envs     平台环境 + dolphin agent 配置  │
│  - /admin/llms     LLM 配置                       │
│  - /admin/users    平台用户管理                   │
│  - /admin/sandboxes Vibe Coding 沙箱监控           │
│  - /admin/status   系统状态                       │
└──────────────────────────────────────────────────┘
```

## 用户决策（已拍板）

| 决策 | 选择 |
|------|------|
| 拆解路径 | **路径 B**：彻底抽独立 repo（不是渐进式 A） |
| 管理后台 | **保留轻量 admin SPA**，只给 platform_admin |
| Vibe Coding 沙箱 | **升级为 MCP 工具**给 dolphin agent 调（9 个新工具） |

## 6 个 Phase 路线图

| Phase | 内容 | 估时 | 累计 |
|-------|------|------|------|
| 1 | 建新 repo 框架 + 复制核心代码 | 0.5 天 | 0.5 |
| 2 | 砍 user-facing routes（~22 个文件） | 1-2 天 | 2.5 |
| 3 | Vibe Coding 9 个 MCP 工具开发 | 2-3 天 | 5.5 |
| 4 | 轻量 admin SPA（4-6 页面） | 2-3 天 | 8.5 |
| 5 | 部署（nginx + DB 复用） | 1 天 | 9.5 |
| 6 | dolphin admin 切 MCP URL + 验证 | 1-2 天 | 11.5 |

**整体 1.5-2 周**，工作日 8-12 个。

## 配套文档

- [01-route-cull-plan.md](01-route-cull-plan.md) — 41 个 route 文件逐个标记 保留/砍/降级
- [02-init-new-repo.sh](02-init-new-repo.sh) — 新 repo 初始化脚本（git init + 目录 + 复制）
- [03-dolphin-admin-mcp-switchover.md](03-dolphin-admin-mcp-switchover.md) — dolphin admin 切换 runbook（含回滚）
- [04-vibe-coding-mcp-tools-spec.md](04-vibe-coding-mcp-tools-spec.md) — Vibe Coding 9 个 MCP 工具签名 + 实现规范

## 关键风险 + 缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| dolphin admin MCP URL 切换缓存不刷新 | 切流量后 dolphin 仍调旧 URL | 删 + 重添加 MCP 服务（参考 03 runbook 含完整步骤）|
| 砍 route 时漏掉某个 MCP 工具依赖 | 部分 MCP 工具运行时 404 | Phase 2 砍前用 `_api_call` grep 全扫，部署前 pg 实测 49 工具 |
| Vibe Coding podman 沙箱多用户隔离漏洞 | 跨 tenant 串沙箱 | 沿用现有 `_resolve_identity` + tenant 维度沙箱目录隔离 |
| admin SPA 砍 NavRail 后路由乱 | platform_admin 进不去 | 重写 router，使用全新 admin-sidebar（不复用 BuilderNavRail）|
| 数据迁移（DB 复用是否兼容） | 新代码连旧 DB 出错 | DB 不动，schema 完全保留；新代码只是连接同一个 mysql，零迁移 |

## 回滚方案

每个 Phase 都有独立回滚点：

- **Phase 1-2 失败**：新 repo 删除，ai-builder 不动
- **Phase 3-4 失败**：dolphin agent 继续连旧 ai-builder MCP，新 repo 暂停部署
- **Phase 5-6 失败**：dolphin admin MCP URL 切回旧地址（一键，~ 5 分钟）

老 ai-builder 部署在 ECS `101.132.123.203:8003`，**保留 1-2 个月**作热备。新 mcp server 部署不同端口（如 8004）或不同 ECS。

## 数据迁移 = 零

DB schema 完全保留，新 repo 的 backend 连同一个 mysql。

- `tenants` / `users` / `applications` / `document_versions` / `change_plans` / `specs` / `coding_workspaces` / `tenant_dolphin_agents` / `platform_envs` 全部不动
- 文件系统：`_online_coding/{tenant_id}/{ws_id}/` workspace 物理目录，新 backend 用同一路径
- `backend/config/apaas_envs.yaml` 复制过去

## 不在本次 refactor 范围

- aPaaS 平台（得帆）侧改动 — 没有
- dolphin trial 服务器 CORS 修复 — 仍挂得帆侧
- 数据 schema 变更 — 没有
- 跨 tenant 业务逻辑变更 — 没有，全部沿用现有 1:1:1 强绑模型

## 启动时机

明天（2026-05-12）开 Phase 1。今天写完 5 份准备文档放在 `docs/refactor-mcp-server/` 目录。
