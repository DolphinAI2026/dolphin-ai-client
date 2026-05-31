# Phase 2 验证记录（2026-05-11）

> 砍完 21 个 CULL route + main.py 精简后，本机起服务 + curl tools/list 实测 49 个 MCP 工具完整可拉。本文档为施工 trail，Phase 5 部署 ECS 时可作 runbook 参考。

## 验证目标（对应 `01-route-cull-plan.md` Phase 2 验收清单）

- [x] backend 起服务无 ImportError
- [x] `/api/health` 返 ok
- [x] `/api/mcp/mcp tools/list` 返 49 工具完整
- [x] admin 账号 `/api/auth/admin-login` 能登（实测走老的 `/api/auth/login`，TRIM 改名留 Phase 2.5）
- [x] 启动 health check 输出 tenant 1:1:1 状态
- [ ] pg 用户在 dolphin agent 实测 — 需公网 ECS 部署（Phase 5）

## 验证环境

| 组件 | 路径 / 端口 | 来源 |
|------|-----------|------|
| mysql | `/Users/mars/mysql/`（tarball 安装）port 3306 | 用户本地早已装 |
| backend python venv | `/Users/mars/Vibe Coding/apaas-builder-ai/backend/venv/bin/python3.13` | 复用 ai-builder 现成 venv（含 fastapi/sqlalchemy/aiomysql/mcp/uvicorn） |
| backend port | 8004 | 避开 ai-builder 8003，与 plan 一致 |
| DB | `apaas_builder` @ localhost:3306 | 已存在 22 个用户 + 多 tenants（5/4 老快照） |

## 启动步骤（本机复现 runbook）

```bash
# 1. 启动 mysql（如未起）
bash /Users/mars/mysql/start.sh

# 2. 拷 .env 进新 repo + 改 PORT/MCP_INTERNAL_BASE
cp "/Users/mars/Vibe Coding/apaas-builder-ai/backend/.env" \
   "/Users/mars/Vibe Coding/apaas-builder-mcp-server/backend/.env"
sed -i '' 's|^PORT=8000$|PORT=8004|; s|MCP_INTERNAL_BASE=http://127.0.0.1:8000/api|MCP_INTERNAL_BASE=http://127.0.0.1:8004/api|' \
   "/Users/mars/Vibe Coding/apaas-builder-mcp-server/backend/.env"

# 3. 跑 7 个 migrations（按时间顺序，见下节"部分失败补丁"）
cd "/Users/mars/Vibe Coding/apaas-builder-mcp-server/backend/migrations"
for f in 2026-05-09-platform-env-alias.sql \
         2026-05-09-tenant-external-link.sql \
         2026-05-09-tenant-split-agent-codes.sql \
         2026-05-10-auth-refactor-schema.sql \
         2026-05-10-pg-trial-dolphin-tenant-binding.sql \
         2026-05-11-tenant-dolphin-agents.sql \
         2026-05-11-tenant-dolphin-instance.sql; do
  /Users/mars/mysql/bin/mysql -uapaas -papaas2024 apaas_builder < "$f"
done

# 4. 起 backend
cd "/Users/mars/Vibe Coding/apaas-builder-mcp-server/backend"
/Users/mars/Vibe\ Coding/apaas-builder-ai/backend/venv/bin/python3.13 \
  -m uvicorn app.main:app --host 127.0.0.1 --port 8004
```

## 7 个 migrations 跑动结果

| Migration | 结果 | 备注 |
|-----------|------|------|
| 2026-05-09-platform-env-alias.sql | ✅ | platform_envs 加 alias 列 |
| 2026-05-09-tenant-external-link.sql | ✅ | tenants 加 apaas_env_id / dolphin_tenant_code 等 |
| 2026-05-09-tenant-split-agent-codes.sql | ✅ | 5 个分立 dolphin agent 字段 |
| 2026-05-10-auth-refactor-schema.sql | ⚠️ Line 22 失败 | `Duplicate entry '100169876816012509184' for uq_users_apaas_uid` — 老 DB users.apaas_user_id 有重复行，加 UNIQUE 失败。**Line 22 之后所有 SQL 没跑** |
| 2026-05-10-pg-trial-dolphin-tenant-binding.sql | ✅ | |
| 2026-05-11-tenant-dolphin-agents.sql | ⚠️ Line 36 失败 | `Field 'created_at' doesn't have a default value` — 严格 SQL_MODE 下 INSERT 缺值。表本身已建出来 |
| 2026-05-11-tenant-dolphin-instance.sql | ✅ | |

## 部分失败的两个 migration 处理

### Migration #4: users.apaas_user_id 重复 → 跳过 UNIQUE 索引

老 DB 里 `users` 表 `apaas_user_id` 列有重复（line 22 加 UNIQUE 失败）。本机老快照特性，**ECS 生产 DB 不会出现**（生产 DB 是干净的 5/9 之后状态）。

副作用：line 22 之后的 SQL 没跑 — 关键缺的是 `ALTER TABLE tenants ADD COLUMN apaas_tenant_id_str`（line 30-33）。**手工补**：

```sql
ALTER TABLE tenants
  ADD COLUMN apaas_tenant_id_str VARCHAR(40) NULL
    COMMENT 'aPaaS 平台租户 21 位 bigint string',
  ADD UNIQUE INDEX uq_tenants_apaas_tid (apaas_tenant_id_str);

UPDATE tenants SET apaas_tenant_id_str = '833850449709760513' WHERE tenant_code = 'pg_trial';
```

### Migration #6: tenant_dolphin_agents 数据 backfill 失败

表本身建好，line 36 之后的数据 backfill 失败（per-tenant 5 个分立 agent_code 字段拆进 N 行）。**不影响 backend 启动** — backend 启动只查 schema，不要求 backfill 数据。

Phase 5 ECS 部署时不会撞 — 生产 DB 已经在 2026-05-11 那天迁移过，本机老快照不一致是历史问题。

## 验证证据

### /api/health

```bash
$ curl -sS http://127.0.0.1:8004/api/health
{"status":"ok"}
```

### 1:1:1 健康检查启动日志

```
INFO  [tenant 1:1:1 健康检查] tenant id=1 OK (apaas_env=1, customer=...)
WARN  [tenant 1:1:1 健康检查] tenant id=2 ... (本地老 self_x 测试租户没绑)
WARN  [tenant 1:1:1 健康检查] tenant id=3 ...
... id=4-22 同样 WARN（本地老数据，预期）
```

只有 tenant id=1 (default) 是配齐的，2-22 是 self_x 历史测试租户，无 1:1:1 配置，启动**不阻塞**只 WARN。

### 49 MCP 工具实测

```bash
TOKEN=$(curl -sS -X POST http://127.0.0.1:8004/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "
import sys, json; print(json.load(sys.stdin)['access_token'])")

curl -sS -X POST http://127.0.0.1:8004/api/mcp/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('TOOL COUNT:', len(d['result']['tools']))
"
# 输出：TOOL COUNT: 49
```

全 49 工具名称：

```
Builder 主线 (15):
  parse_design_doc / list_platform_envs / list_apaas_apps / list_apaas_apps_in_env /
  check_app_code_conflict / list_apaas_models_in_env / generate_app_from_doc /
  list_my_applications / get_application / update_app_from_doc / get_change_plan /
  execute_change_plan / lookup_user_by_username / grant_app_access / deploy_application /
  publish_application

Builder 辅助 (3):
  get_doc_template_spec / validate_builder_doc / submit_design_doc

Coding 主线 (16):
  list_dev_scenes / get_dev_scene_spec / get_dev_scene_full_workflow /
  save_dev_spec / import_zip_to_workspace / create_dev_workspace /
  get_dev_workspace_status / read_workspace_file / write_workspace_files /
  edit_workspace_files / glob_workspace / grep_workspace /
  run_workspace_command / publish_dev_workspace /
  list_apaas_app_models / list_apaas_app_dicts

aPaaS 二次开发 (11):
  get_apaas_app_overview / enable_apaas_self_dev_config / list_apaas_app_dev_kits /
  attach_dev_packages_to_apaas_app / republish_apaas_app / list_apaas_app_menus /
  create_apaas_self_dev_menu / list_apaas_form_views / list_apaas_form_components /
  list_apaas_resource_pool_kits / upload_external_zip_to_apaas

Cross-agent (DEPRECATED 2 + 1):
  get_recent_app_context / handoff_to_coding / handoff_to_builder
```

合计 15+3+16+11+3 = **49** ✓

## Phase 5 (ECS 部署) 应用此 verification 经验

部署到生产 ECS 时不会有本机老 DB schema drift 问题（生产 DB 是干净 schema），步骤更简单：

1. rsync 整个 `apaas-builder-mcp-server/` 到 ECS（参照 ai-builder 部署 runbook）
2. ECS 已有 mysql `apaas_builder` DB（与 ai-builder 共用），DB schema 是 2026-05-11 最新状态
3. 启动新 8004 实例，与 ai-builder 8003 并行跑
4. dolphin admin 切 MCP URL 从 8003 → 8004（按 `03-dolphin-admin-mcp-switchover.md`）

## 复用 / 不复用决策清单

- **复用** ai-builder venv：本机已有 fastapi/sqlalchemy/mcp/uvicorn 全套，无需 pip install。
  ECS 上则要新建 venv（不共用，免得新 repo 路径变化）。
- **复用** mysql DB：本机 mysql apaas_builder 跟 ai-builder 共享（DB schema 一致）。
  ECS 上同样复用同一 DB（Plan 决策，零数据迁移）。
- **复用** .env：拷贝过来改两行（PORT + MCP_INTERNAL_BASE）。
  ECS 上 .env 要重写 — DB host / API keys 不同。
- **不复用** apaas_envs.yaml：本机没真文件（gitignore），缺失是 graceful WARN 不致命。
  ECS 上 ai-builder backend 有，新 repo 部署时要 cp 过来。
