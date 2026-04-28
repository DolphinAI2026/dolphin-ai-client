# 部署清单

线上地址：https://agent.dfy.definesys.cn/ai-builder/

部署目录：`/root/apaas-builder/`

后端端口：`8003`

> 不要把服务器口令写进仓库。部署脚本会从环境变量读取口令，或在本机交互式输入。

## 标准部署

在当前仓库根目录执行：

```bash
cd "/Users/mars/Vibe Coding/apaas-builder-ai"

python3 -m pip install paramiko

export APAAS_DEPLOY_HOST="101.132.123.203"
export APAAS_DEPLOY_USER="root"
export APAAS_DEPLOY_PASSWORD="你的 SSH 口令"

python3 scripts/deploy_cloud.py
```

脚本会完成：

1. 执行 `frontend` 的 `npm run build:nocheck`，生成 `/ai-builder/` 基路径产物。
2. 打包上传 `backend/`，自动排除 `.env`、虚拟环境、缓存、日志和数据库文件。
3. 打包上传 `frontend/dist/`。
4. 安装后端依赖。
5. 杀掉旧的 `uvicorn` 进程，重新启动 `app.main:app`。
6. 检查远端 `/api/health`、关键 OpenAPI 路由和公网健康状态。

常用参数：

```bash
# 前端已经构建过，只部署现有 dist
python3 scripts/deploy_cloud.py --skip-build

# 只部署后端并重启
python3 scripts/deploy_cloud.py --backend-only

# 只部署前端 dist
python3 scripts/deploy_cloud.py --frontend-only

# 跳过公网健康检查
python3 scripts/deploy_cloud.py --no-public-check
```

## 本地验证

部署前建议至少跑：

```bash
backend/venv/bin/python -m pytest backend/tests/test_doc_upload_spec_backfill.py -q

cd frontend
npm run build:nocheck
```

如果本机没有 `backend/venv`，先按项目 README 创建虚拟环境并安装依赖。

## 线上验证

```bash
curl -s -o /dev/null -w "%{http_code}" \
  https://agent.dfy.definesys.cn/ai-builder/api/health
```

期望返回 `200`。

建议再走一遍关键路径：

1. 登录线上。
2. 新建 AI-Builder 会话。
3. 上传标准设计文档。
4. 确认右侧 SPEC 在上传解析完成后自动出现，不需要再发一条消息。
5. 继续在对话框里提出修改，确认右侧 SPEC 能跟随更新。
6. 点击「开始构建」，检查低代码应用创建流程。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| `Missing dependency: pip install paramiko` | 执行 `python3 -m pip install paramiko` |
| `frontend/dist is missing` | 去掉 `--skip-build`，或先在 `frontend/` 下执行 `npm run build:nocheck` |
| 远端健康检查不是 `200` | 查看 `/root/apaas-builder/backend.log` |
| 新接口 404 但 `/api/health` 正常 | 脚本会检查 OpenAPI 关键路由；如果失败，通常是旧进程没杀干净或新进程启动失败 |
| `uvicorn` 启动后平台代理状态丢失 | 线上目前固定 `--workers 1`；多 worker 需要先把代理状态下沉到 DB 或 cookie |

## 手动重启后端

只有脚本失败且需要人工处理时再执行：

```bash
ssh root@101.132.123.203
cd /root/apaas-builder/backend

pkill -9 -f 'uvicorn.*:app.*8003' || true
fuser -k 8003/tcp || true

nohup .venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8003 --workers 1 \
  >> ../backend.log 2>&1 < /dev/null &

curl -s -o /dev/null -w "%{http_code}" http://localhost:8003/api/health
```
