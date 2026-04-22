# 部署清单

线上地址：https://agent.dfy.definesys.cn/ai-builder/
服务器：101.132.123.203（root / Mars888521）
部署目录：/root/apaas-builder/
后端端口：8003

---

## 快速部署（标准流程）

### 第一步：提交代码

```bash
cd /Users/mars/Desktop/apaas-build/apaas-builder-ai

# 查看改动
git diff --stat

# 暂存需要提交的文件（按实际修改选择）
git add backend/app/... frontend/src/...

# 提交
git commit -m "描述本次改动"

# 推送
git push origin main
```

---

### 第二步：构建前端

```bash
cd /Users/mars/Desktop/apaas-build/apaas-builder-ai/frontend

VITE_BASE_URL=/ai-builder/ /usr/local/bin/node node_modules/.bin/vite build
```

构建产物输出到 `frontend/dist/`。

---

### 第三步：运行部署脚本

```bash
/usr/local/bin/python3 /tmp/deploy.py
```

> 如果 `/tmp/deploy.py` 不存在（重启电脑后临时文件会消失），见下方「重建部署脚本」。

脚本会自动：
1. 打包上传后端代码（排除 `.env` / `venv` / `__pycache__` / `*.db`）
2. 打包上传前端 `dist/`
3. 安装新增 Python 依赖（`pip install -r requirements.txt`）
4. 重启后端 uvicorn 进程

---

### 第四步：验证

```bash
# 后端健康检查
curl -s -o /dev/null -w "%{http_code}" https://agent.dfy.definesys.cn/ai-builder/api/health
# 期望返回：200

# 浏览器访问前端
open https://agent.dfy.definesys.cn/ai-builder/
```

---

## 重建部署脚本

如果 `/tmp/deploy.py` 丢失，执行以下命令重新创建：

```bash
cat > /tmp/deploy.py << 'PYEOF'
#!/usr/bin/env python3
import os, sys, tarfile, io, time
import paramiko
from pathlib import Path

HOST = "101.132.123.203"
PORT = 22
USER = "root"
PASS = "Mars888521"

LOCAL_BACKEND      = "/Users/mars/Desktop/apaas-build/apaas-builder-ai/backend"
LOCAL_FRONTEND_DIST= "/Users/mars/Desktop/apaas-build/apaas-builder-ai/frontend/dist"
REMOTE_BASE        = "/root/apaas-builder"

BACKEND_EXCLUDES = {".env","venv",".venv","__pycache__",".db","uvicorn.log","apaas_builder.db"}

def should_exclude(path_str):
    for part in Path(path_str).parts:
        if part in BACKEND_EXCLUDES: return True
        if part.endswith((".pyc",".log",".db")): return True
        if part.startswith("._") or part == ".DS_Store": return True  # macOS 元数据
    return False

def make_tar(local_dir):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        base = Path(local_dir)
        for path in base.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(base))
                if not should_exclude(rel):
                    tar.add(str(path), arcname=rel)
    buf.seek(0)
    return buf

print("Connecting...")
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, port=PORT, username=USER, password=PASS, timeout=30)
sftp = client.open_sftp()

def run(cmd):
    _, stdout, stderr = client.exec_command(cmd)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(f"  > {out}")
    if err: print(f"  ! {err}")
    return out

# 1. 上传后端
print("\n=== 上传后端...")
data = make_tar(LOCAL_BACKEND).read()
print(f"  {len(data)//1024} KB")
with sftp.open("/tmp/backend_deploy.tar.gz","wb") as f: f.write(data)
run("tar -xzf /tmp/backend_deploy.tar.gz -C /root/apaas-builder/backend/")
run("rm -f /tmp/backend_deploy.tar.gz")

# 2. 上传前端
print("\n=== 上传前端 dist...")
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w:gz") as tar:
    base = Path(LOCAL_FRONTEND_DIST)
    for path in base.rglob("*"):
        if path.is_file():
            tar.add(str(path), arcname=str(path.relative_to(base)))
buf.seek(0); data = buf.read()
print(f"  {len(data)//1024} KB")
with sftp.open("/tmp/frontend_deploy.tar.gz","wb") as f: f.write(data)
run("rm -rf /root/apaas-builder/frontend/dist && mkdir -p /root/apaas-builder/frontend/dist")
run("tar -xzf /tmp/frontend_deploy.tar.gz -C /root/apaas-builder/frontend/dist/")
run("rm -f /tmp/frontend_deploy.tar.gz")

# 3. 安装依赖
print("\n=== 安装依赖...")
run("cd /root/apaas-builder/backend && .venv/bin/pip install -q -r requirements.txt")

# 4. 重启后端
print("\n=== 重启后端...")
# 匹配新旧两种命令（uvicorn app.main:app 和老的 uvicorn main:app），否则老进程会继续占 8003 掩盖新进程 crash
run("pkill -9 -f 'uvicorn.*:app.*8003' || true")
time.sleep(3)
# cwd 必须是 backend/，否则 `app.main:app` 会 ModuleNotFoundError: No module named 'app'
# --workers 1：platform_proxy._proxy_state 是模块级全局 dict，多 worker 下 iframe 后续请求会打到空状态的 worker
run("cd /root/apaas-builder/backend && nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8003 --workers 1 >> ../backend.log 2>&1 &")
time.sleep(4)
code = run("curl -s -o /dev/null -w '%{http_code}' http://localhost:8003/api/health")
print(f"  健康检查: {code}")
# 真实路由探测：老代码没有 harness 路由，能骗过 /api/health
hit = run("curl -s http://localhost:8003/openapi.json | grep -c '/harness/coding/pipeline' || true")
print(f"  harness 路由命中: {hit}")

sftp.close(); client.close()
print("\n✅ 部署完成！")
print("访问：https://agent.dfy.definesys.cn/ai-builder/")
PYEOF
```

---

## 注意事项

| 事项 | 说明 |
|------|------|
| `.env` | 脚本已排除，永远不会覆盖线上配置 |
| 数据库 `.db` | 已排除，线上数据不受影响 |
| `venv` / `.venv` | 已排除，使用线上已有的虚拟环境 |
| 仅部署后端 | 跳过第二步（构建前端），第三步脚本仍会上传后端并重启 |
| 仅部署前端 | 只执行第二步构建 + 第三步脚本（脚本会同时上传前端并跳过后端重启如无需要） |
| 依赖有变化 | 脚本会自动执行 `pip install -r requirements.txt`，无需手动操作 |
| 工作区模板改动 | 改动 `backend/templates/` 或 `workspace.py` 后，已存在的旧工作区不会自动更新；需要重新创建工作区才能生效 |
| deploy.py 卡在"重启后端" | paramiko 执行 `nohup ... &` 时 SSH 通道不会自动关闭，属正常现象。观察到"=== 安装依赖..."已完成即可手动 kill deploy.py 进程，然后执行健康检查确认服务正常 |
| 部署后 action 绿灯但新路由 404 | 历史 bug：老 `pkill` 只匹配 `app.main:app`，匹配不到老进程的 `main:app`（跑在 `venv/` 而非 `.venv/`）。老进程占着 8003 让 `/api/health` 返回 200 骗过健康检查，新进程实际 crash。修复已加真实路由探测（`openapi.json` 要包含 `/harness/coding/pipeline`）兜底 |
| dev server HTTPS 已移除 | workspace 模板的 `vue.config.js` 不再配置 HTTPS，dev server 跑纯 HTTP，通过 code-server `/proxy/{port}/` 访问。旧工作区若仍有 `https: {...}` 配置需手动删除 |
| 公网预览地址 | 在 code-server 终端执行 `npm run serve` 后，终端会自动打印公网访问地址：`https://agent.dfy.definesys.cn/ai-builder/ide/proxy/{port}/` |

---

## 容器化部署注意事项（未来规划）

> 当前线上为**主机部署**（进程直接跑在云主机上），以下为未来容器化时需要关注的差异点。

### 差异对比

| 项目 | 主机部署（当前） | 容器部署 |
|---|---|---|
| 工作区数据 | 本地磁盘 `/root/apaas-builder/workspaces/` | 必须挂载持久化 volume，否则重启丢失 |
| code-server 路径 | 与后端共享本地文件系统 | 需通过共享 volume 挂载到两个容器 |
| Node.js 环境 | 主机已安装 | 镜像内需预装 Node.js |
| dev server 端口 | 直接可被 nginx 访问 | 需用 `--network=host` 或显式 expose 端口 |
| nginx 转发 | `proxy_pass http://127.0.0.1:8003` | 改为容器服务名，如 `proxy_pass http://apaas-backend:8003` |
| 配置文件 | `.env` 文件放在服务器上 | 改用 Docker secrets 或 `env_file` 挂载，不打入镜像 |

### 关键注意点

**1. 工作区 volume 挂载**
```yaml
volumes:
  - /data/workspaces:/root/apaas-builder/workspaces
```

**2. code-server 与后端共享工作区**

code-server 和后端需挂载同一个 volume，且路径必须一致，因为后端传给 code-server 的 `folder=` 参数是绝对路径。

**3. dev server 端口访问**

最小改动方案：后端容器使用 `--network=host`，nginx 仍可用 `127.0.0.1:{port}` 访问 dev server，行为与主机部署一致。

**4. 最小迁移路径**

先用单容器 + `--network=host` 模式，把后端和 code-server 打进同一镜像，改动最小，验证稳定后再拆分。

---

## 线上目录结构

```
/root/apaas-builder/
├── backend/
│   ├── .env          ← 线上配置，部署时不覆盖
│   ├── .venv/        ← 虚拟环境，部署时不覆盖
│   ├── app/          ← 后端代码（部署更新）
│   ├── requirements.txt
│   └── run.py
├── frontend/
│   └── dist/         ← 前端构建产物（部署更新）
├── workspaces/       ← 用户工作区数据，不涉及部署
└── backend.log
```

---

## 快速排查

```bash
# SSH 登录服务器
ssh root@101.132.123.203
# 密码：Mars888521

# 查看后端进程
ps aux | grep uvicorn

# 查看后端日志
tail -50 /root/apaas-builder/backend.log

# 手动重启后端
# 注意：kill 模式要匹配两种启动命令（新的 app.main:app 和老的 main:app），否则老进程会一直占端口
pkill -9 -f 'uvicorn.*:app.*8003'
# cwd 必须是 backend/，否则 `app.main:app` 会 ModuleNotFoundError
cd /root/apaas-builder/backend
# --workers 1：platform_proxy 代理状态跨 worker 不共享，多 worker 会导致 iframe "智能体不存在"
nohup .venv/bin/python -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8003 --workers 1 >> ../backend.log 2>&1 &

# 重载 nginx（改了 nginx 配置后）
nginx -t && nginx -s reload
```
