# 03 · dolphin admin MCP URL 切换 runbook

> Phase 6 执行。新 mcp server 部署完毕 + 49+9=58 工具就绪后，dolphin agent 切流量。

## 背景

dolphin omnigate 当前指向 **旧 ai-builder MCP endpoint**：

```
https://agent.dfy.definesys.cn/ai-builder/api/mcp/mcp
```

切流量目标 **新 mcp server**（Phase 5 实际部署）：

```
https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp
```

**决策更新（2026-05-11 Phase 5）**：原计划用独立子域 `mcp.dfy.definesys.cn`，实际复用了
`agent.dfy.definesys.cn` 域 + `/mcp-server/` 前缀 — 与 ai-builder `/ai-builder/` 并存，零
SSL 证书运维，nginx config 仅加一个 include 文件即可（详见 phase-5-deploy.md）。

## 已知坑（memory 记录）

之前 `handoff_2026_05_09.md` 记的两个坑必须避开：

1. **dolphin admin 编辑现有 MCP 服务弹窗没"刷新"按钮**：改 URL 后**工具列表不会自动重新拉取**，dolphin omnigate 仍调老 URL
2. **dolphin admin 编辑 MCP 服务**只能改"工具列表 + Body 字段 + Header"，**不能改 endpoint URL**（URL 是创建时固化的）

**唯一解**：**删除现有 MCP 服务关联 + 重新添加**指向新 URL。

## 切换前检查清单

新 mcp server 必须先就绪：

- [ ] 新 mcp server 部署在 `agent.dfy.definesys.cn:443（nginx 反代 → 内部 :8004）`（或 `:443` via nginx）
- [ ] `curl https://agent.dfy.definesys.cn/mcp-server/api/health` 返 `{"status":"ok"}`
- [ ] `curl -H "Authorization: Bearer $TOKEN" -X POST https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp -H "Accept: application/json,text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'` 返 58 工具
- [ ] 新 mcp server 连同一个 mysql `apaas_builder` DB（数据完整）
- [ ] 新 mcp server 启动 health check 4 个 tenant 输出（default OK / pg_trial OK / bkbs WARN / deckers WARN）
- [ ] admin 在新 admin SPA `https://agent.dfy.definesys.cn/mcp-server/admin/` 能登录 + 看到 4 个租户（Phase 5.2 部署，当前 Phase 5 只暴露 backend API）

## 切换步骤（每个 agent 都要做 1 遍，共 4 个）

需要切的 4 个 agent：

| 租户 | Builder | Coding |
|------|---------|--------|
| default（体验） | `23c93f30d8` | `f765238af4` |
| pg_trial（宝洁） | `76b2b8cecc` | `41fe6f2479` |

### 单个 agent 切换流程（5 分钟/agent）

1. 登 dolphin admin（pg / superadmin，看 agent 归属）
2. 进 **智能体管理** → 选目标 agent → **配置**
3. 滚到 **工具** 区域 → **MCP 服务** → 找到 `aPaaS Builder AI 工具集` 那一行
4. ⚠️ **点 × 删除现有关联**（不是编辑，是删除）
5. 点 **+ 添加** → 选 `+ 添加 MCP 服务市场未列入的服务`（或类似"自定义 MCP 服务"按钮）
6. 填入：
   ```
   服务名: apaas-builder-mcp (或保持 aPaaS Builder AI 工具集)
   URL: https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp
   传输方式: SSE / Streamable HTTP（按 dolphin 版本支持选）
   ```
7. 点 **测试连接** → 等几秒 → 出现 **58 个工具列表**
8. **全勾选 58 个工具**
9. 把 `X-AI-GW-KEY` 自定义请求头加上（值跟之前一样）
10. 点 **保存**
11. 切到 agent 主页 → 点 **发布** → 等"已发布"标识
12. **新开一个对话**测：让 pg 在新对话里说"list 一下宝洁租户应用" → agent 调 `list_apaas_apps(env="baogong")` → 返应用列表 → 切换成功

### 4 个 agent 都做完后

总耗时 ~ 20 分钟。

### 验证清单

切完 4 个 agent 后跑这 4 个测试：

1. **pg 用户进宝洁 Builder agent**：说"做一个员工通讯录应用" → agent 应该走 req-design → app-create 流程，能创建出宝洁 tenant 下的应用
2. **pg 用户进宝洁 Coding agent**：说"在 #244 应用上加一个产品分类组件" → agent 应该走 create_dev_workspace 流程
3. **pg 用户进宝洁 Coding agent**：传一个 zip base64 + 说"改一下这个组件的颜色" → agent 应该走 `import_zip_to_workspace` 新工具
4. **admin 进 default Builder agent**：说"list 我所有应用" → agent 调 `list_my_applications` 返回 admin 自己的应用

## 回滚

如果 5 分钟内发现切换坏了某个 agent：

1. 该 agent → MCP 服务 → 删除新关联
2. **重新添加** → URL 填回旧地址 `https://agent.dfy.definesys.cn/ai-builder/api/mcp/mcp`
3. 测试连接 → 49 工具（旧没 import_zip）→ 全选 → 保存 + 发布

回滚时间 ~ 5 分钟 per agent。

## 老 ai-builder 何时下线

**保留 1-2 个月**作热备：

- 新 mcp server 切流量后 1 个月 = 2026-06-12 前：完全不动老 ai-builder
- 1 个月后：检查 backend.log 有没有新 MCP 调用（即检查有没有 agent 还忘记切了）
- 2 个月 = 2026-07-12：可以正式关 ai-builder backend（端口 8003 free）
- frontend `agent.dfy.definesys.cn/ai-builder/*` 路径可以 redirect 到 `mcp.dfy.definesys.cn/admin/`（如果有老链接）

## DB 共享期的并发写风险

新老两边代码都连同一个 `mysql apaas_builder` DB：

- **applications** 表：双写没问题（每行 tenant_id + 应用名隔离）
- **tenants** 表：admin SPA 改 tenant 配置时，老 ai-builder 后端 cache 会过期 → 用户在老 ai-builder 域用浮窗时可能拿到旧配置。**建议切流量后立刻让用户停用老 ai-builder 域**
- **users** 表：双方都不允许 user 注册 / 改密码 / 改 apaas_user_id，只允许 read。安全

## 切换日志记录

切完后在新 admin SPA 看：

- `https://agent.dfy.definesys.cn/mcp-server/admin/status` → 系统状态页 → 看 backend.log 最近 100 行（Phase 5.2 部署后可用）
- 应该看到大量 `_resolve_alias_tid_for_env` / `_resolve_alias_tid_for_app` 命中（说明 alias 模式 tid 反查正常）
- 没有 `403 无权访问该平台环境` / `MultipleResultsFound` 异常

---

## 给 dolphin 团队的 ticket（如果碰到问题）

如果**第 6 步「测试连接」拿不到 58 工具**：

```
环境：dolphin-trial.definesys.cn admin
操作：MCP 管理 → 添加 MCP 服务 → URL: https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp → 测试连接
现象：拉工具列表失败 / 超时 / 拉到 0 工具

排查：
1. 在 mcp server ECS 上 curl 本机：
   curl -X POST http://localhost:8004/api/mcp/mcp \
     -H "Accept: application/json,text/event-stream" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
   应该返 58 工具
2. 检查 nginx 反代：
   curl -X POST https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp ...
   也应该返 58 工具
3. 如果 1 通 2 不通：nginx 配置 proxy_buffering off + read_timeout 600s 是否生效
4. 如果 1 不通：检查 ai-builder backend 是否真的有 import_zip_to_workspace（grep 工具数）

如以上都通但 dolphin 那边仍拉不到，请 dolphin 团队看 omnigate 这边的连接日志（trace_id 在浏览器 console 看得到）。
```
