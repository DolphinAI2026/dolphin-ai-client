# Phase 5 部署 ECS 记录（2026-05-11）

> 把新 apaas-builder-mcp-server 部署到生产 ECS `101.132.123.203`，
> 复用同一 mysql + 同一 nginx + 同一域名 + 不同端口（8004），与
> ai-builder 8003 并存。Phase 6 dolphin admin 切 MCP URL 才会让流量正式转过去。

## 部署目标

| 项 | 路径 / 值 |
|----|----------|
| ECS | `101.132.123.203` (`iZuf617j3v6yndjigwrxi5Z`) |
| 源码 | `/root/apaas-builder-mcp-server/` |
| Backend | uvicorn `app.main:app` 跑在 `0.0.0.0:8004` `--root-path /mcp-server` |
| Python | 3.13（venv 复用 ai-builder `.venv` cp + 路径 rewrite） |
| DB | mysql 3306 本地，DB=`apaas_builder` 跟 ai-builder 共享 |
| nginx | `/etc/nginx/apaas-mcp-server.conf` include 到 `marsagent.conf` 主 https server |
| 域名/路径 | `https://agent.dfy.definesys.cn/mcp-server/api/*` |
| 端口共存 | 8001 (?) / 8002 (MarsAgent) / 8003 (ai-builder) / **8004 (new)** |

## 部署步骤实测（10 分钟跑完）

### 1. rsync 源到 ECS

```bash
# 本机：apaas-builder-mcp-server repo 根目录
rsync -avz \
  -e "ssh -i ~/.ssh/apaas_deploy_rsa" \
  --exclude='node_modules/' \
  --exclude='.git/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.venv/' \
  --exclude='venv/' \
  --exclude='dist/' \
  --exclude='backend/.env' \
  --exclude='backend/backend.log' \
  --exclude='backend/_online_coding/' \
  --exclude='*.tsbuildinfo' \
  ./ root@101.132.123.203:/root/apaas-builder-mcp-server/
# → 269 files / 1.15 MB
```

### 2. 复用 ai-builder venv（避免 pip install 几分钟）

```bash
cp -r /root/apaas-builder/backend/.venv /root/apaas-builder-mcp-server/backend/.venv
# venv 内部 bin/ 的 shebang 硬编码了旧路径，用 sed rewrite
find /root/apaas-builder-mcp-server/backend/.venv/bin -type f \
  -exec sed -i "s|/root/apaas-builder/backend/.venv|/root/apaas-builder-mcp-server/backend/.venv|g" {} \;
```

### 3. .env 拷过来 + 改 PORT + MCP_INTERNAL_BASE

```bash
cp /root/apaas-builder/backend/.env /root/apaas-builder-mcp-server/backend/.env
sed -i 's|^PORT=.*|PORT=8004|' /root/apaas-builder-mcp-server/backend/.env
sed -i 's|MCP_INTERNAL_BASE=http://127.0.0.1:[0-9]*/api|MCP_INTERNAL_BASE=http://127.0.0.1:8004/api|' \
  /root/apaas-builder-mcp-server/backend/.env
# ai-builder 的 .env 里没有 MCP_INTERNAL_BASE，需要追加
grep -q MCP_INTERNAL_BASE /root/apaas-builder-mcp-server/backend/.env || \
  echo "MCP_INTERNAL_BASE=http://127.0.0.1:8004/api" >> /root/apaas-builder-mcp-server/backend/.env
```

### 4. 拷 apaas_envs.yaml + 清 __pycache__

```bash
cp /root/apaas-builder/backend/config/apaas_envs.yaml \
   /root/apaas-builder-mcp-server/backend/config/apaas_envs.yaml
# 28 行环境定义

find /root/apaas-builder-mcp-server/backend/app -type d -name __pycache__ -exec rm -rf {} +
# 必删 — memory 教训：python 3.13 hash-based pyc 缓存陷阱
```

### 5. 起 uvicorn（nohup 后台）

```bash
cd /root/apaas-builder-mcp-server/backend
mkdir -p logs
nohup ./.venv/bin/python3.13 -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8004 --workers 1 \
  --root-path /mcp-server \
  >> logs/uvicorn-8004.log 2>&1 &
```

实测启动日志：
```
INFO  Vibe Coding MCP tools loaded (+9 tools)
INFO  MCP server mounted: streamable=/api/mcp/mcp, legacy_sse=/api/mcp-legacy/sse
INFO  [tenant 1:1:1 健康检查] tenant id=1 OK (apaas_env=1, customer=...)
WARN  [tenant id=2 缺 apaas_env_id ...] / id=3 / id=4 ...
INFO  ✅ 已同步内置 LLM 配置到 llm_configs
INFO  Application startup complete.
INFO  Uvicorn running on http://0.0.0.0:8004
```

### 6. nginx 反代

新文件 `/etc/nginx/apaas-mcp-server.conf`：

```nginx
location /mcp-server/api/ {
    rewrite ^/mcp-server/api/(.*) /api/$1 break;
    proxy_pass http://127.0.0.1:8004;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /mcp-server;
    # MCP streamable HTTP 是 SSE 长连接
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 1800s;
    proxy_send_timeout 1800s;
    proxy_set_header X-Accel-Buffering no;
    chunked_transfer_encoding on;
    tcp_nodelay on;
}
```

include 加到 `/etc/nginx/conf.d/marsagent.conf` 的 https server block，
紧跟现有 `include /etc/nginx/apaas-builder.conf;` 行之后。

```bash
nginx -t && nginx -s reload
```

### 7. 公网 https 实测（5 项全 pass）

```bash
# 健康
curl https://agent.dfy.definesys.cn/mcp-server/api/health
# → {"status":"ok"}

# admin 登录
RESP=$(curl -X POST https://agent.dfy.definesys.cn/mcp-server/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}')
TOKEN=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 58 工具
curl -X POST https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
print('TOOLS:', len(d['result']['tools']))
"
# → TOOLS: 58
```

## 验收清单

- [x] 8004 listen 0.0.0.0
- [x] `curl http://127.0.0.1:8004/api/health` → `{"status":"ok"}`
- [x] `curl https://agent.dfy.definesys.cn/mcp-server/api/health` → 公网 200
- [x] admin 登录走公网 OK
- [x] 公网 tools/list 返 58 工具（49 Builder/Coding + 9 Vibe）
- [x] 启动日志含 1:1:1 健康检查（tenant id=1 OK / 2+ WARN 符合预期）
- [x] 与 ai-builder 8003 并存，互不影响
- [ ] Phase 6 dolphin admin 切 4 个 agent 的 MCP URL（用户手动）

## 关键工具检查

| 项 | 路径 / 版本 |
|----|----------|
| podman | `/usr/bin/podman` 4.9.4-rhel — Vibe Coding 沙箱 OK |
| docker（CLI shim） | `/usr/bin/docker` Emulate via podman |
| mysql | localhost:3306，apaas_builder DB schema 已最新（无需补 migrations） |
| code-server | 4.114.0 跑 127.0.0.1:8080（ai-builder 老 IDE 服务，与 mcp-server 无关） |

## 当前 ECS 8004 状态

- `pid` 跑 `python3.13 -m uvicorn app.main:app --host 0.0.0.0 --port 8004 --root-path /mcp-server`
- 日志：`/root/apaas-builder-mcp-server/backend/logs/uvicorn-8004.log`
- 当前是 `nohup &`，**未配 systemd**。重启 ECS 后服务不会自启 — 后续可配 systemd unit。

## systemd unit 推荐配置（Phase 5.1）

```ini
# /etc/systemd/system/apaas-mcp-server.service
[Unit]
Description=apaas-builder MCP Server
After=network.target mysql.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/apaas-builder-mcp-server/backend
ExecStart=/root/apaas-builder-mcp-server/backend/.venv/bin/python3.13 \
  -m uvicorn app.main:app --host 0.0.0.0 --port 8004 --workers 1 --root-path /mcp-server
Restart=on-failure
RestartSec=5
StandardOutput=append:/root/apaas-builder-mcp-server/backend/logs/uvicorn-8004.log
StandardError=append:/root/apaas-builder-mcp-server/backend/logs/uvicorn-8004.log

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable apaas-mcp-server
systemctl restart apaas-mcp-server
```

## 回滚（如果 dolphin agent 切 URL 后出问题）

```bash
# 1. 直接 kill 8004（dolphin 立刻 fallback 回老的，因为 dolphin omnigate 当前还连 8003）
ssh root@101.132.123.203 'pkill -f "uvicorn.*8004"'

# 2. 真要彻底回滚：
ssh root@101.132.123.203 'rm /etc/nginx/apaas-mcp-server.conf'
ssh root@101.132.123.203 'sed -i "/apaas-mcp-server.conf/d" /etc/nginx/conf.d/marsagent.conf'
ssh root@101.132.123.203 'nginx -t && nginx -s reload'
# 新 repo 文件保留在 /root/apaas-builder-mcp-server/，下次直接重启即可
```

## 注意事项

1. **DB 共享期的并发风险**：新老 backend 共用 mysql，admin SPA 改 tenant
   配置时老 ai-builder backend cache 会过期。Phase 6 切流量后老的不再被用，
   1-2 个月后下线 ai-builder。
2. **`_online_coding/` 目录**：新 mcp-server backend 也用 `_online_coding/`
   作为 sandbox workspace 物理路径。当前默认在 `/root/apaas-builder-mcp-server/_online_coding/`，
   跟 ai-builder 的 `/root/apaas-builder/_online_coding/` 物理分离。
   如要共享 workspace（用户在新老 backend 之间无缝迁移），可用 `APAAS_ONLINE_CODING_ROOT`
   env var 指向同一目录。
2.5. **`.pending-dev-specs/` 目录共享**（2026-05-11 晚踩坑修）：
   两个 backend 都用 `<WORKSPACE_ROOT>/../.pending-dev-specs/` 存 dolphin coding agent
   写的 spec md / mockup html。新 mcp-server 写到 `/root/apaas-builder-mcp-server/.pending-dev-specs/`，
   老 ai-builder backend 找 `/root/apaas-builder/.pending-dev-specs/` → 用户从 dolphin
   chat 拿到 preview URL（硬编 `/ai-builder/dev-spec-preview/{token}`）访问时撞 SPEC_NOT_FOUND 404。

   修法：symlink 让两个 backend 共享同目录：
   ```bash
   # 备份老 backend 现有 pending（11 个老 spec 不要丢）
   mv /root/apaas-builder/.pending-dev-specs /root/apaas-builder/.pending-dev-specs.bak-YYYYMMDD-HHMM

   # symlink 指向新 mcp-server 的目录
   ln -s /root/apaas-builder-mcp-server/.pending-dev-specs /root/apaas-builder/.pending-dev-specs

   # 把备份的老 spec 全部 cp -n 进新目录（不覆盖）
   cp -n /root/apaas-builder/.pending-dev-specs.bak-*/* /root/apaas-builder-mcp-server/.pending-dev-specs/
   ```

   也对应代码层 fix（commit 1ce84d9）：create_dev_workspace 不再 unlink spec 源文件，
   两层保险让 preview URL 永久可用。
3. **DOLPHIN_AGENT_CODE 等 .env**：当前与 ai-builder 共享同一 .env，
   dolphin agent code 等配置也共享。如新 mcp 要接入独立 dolphin agent
   不影响老 agent，要单独改 .env。
4. **不阻塞 ai-builder**：本部署没动 ai-builder 8003 任何文件 / 配置 /
   端口，老服务完整无影响。

## Phase 5 → Phase 6 衔接

Phase 5 完毕状态：
- 新 mcp-server 在 `https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp` 可访问
- 58 工具可拉
- ai-builder 8003 还在跑 `https://agent.dfy.definesys.cn/ai-builder/api/mcp/mcp`
- dolphin agent 仍连老 URL

Phase 6 用户操作（按 `03-dolphin-admin-mcp-switchover.md`）：
1. dolphin admin 进 4 个 agent 配置
2. 删除现有 `aPaaS Builder AI 工具集` MCP 服务关联
3. 重新添加，URL 填新地址 `https://agent.dfy.definesys.cn/mcp-server/api/mcp/mcp`
4. 测试连接 → 拉 58 工具 → 全勾选 → 保存 → 发布
5. 新对话实测

回滚 < 5 分钟：把 URL 改回 `https://agent.dfy.definesys.cn/ai-builder/api/mcp/mcp` 即可。
