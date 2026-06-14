# aPaaS Builder AI — 阿里云部署指南

## 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| 操作系统 | CentOS 7+ / Alibaba Cloud Linux 3 | 推荐 Alibaba Cloud Linux 3 |
| Python | 3.10+ | 推荐 3.13，需支持 `str \| None` 语法 |
| Node.js | 18+ | 推荐 20+，用于构建前端 |
| MySQL | 8.0+ | 异步驱动 aiomysql |
| Nginx | 1.18+ | 反向代理 + 静态资源 |

## 1. 服务器准备

### 1.1 安装 Python 3.13（如未安装）

```bash
# 编译安装
yum install -y gcc openssl-devel bzip2-devel libffi-devel zlib-devel
cd /tmp
wget https://www.python.org/ftp/python/3.13.1/Python-3.13.1.tgz
tar xzf Python-3.13.1.tgz
cd Python-3.13.1
./configure --enable-optimizations --prefix=/usr/local
make -j$(nproc) && make altinstall

# 验证
python3.13 --version
```

### 1.2 安装 Node.js 20（如未安装）

```bash
curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
yum install -y nodejs
node --version
```

### 1.3 安装 MySQL 8.0（如未安装）

```bash
yum install -y mysql-server
systemctl enable mysqld && systemctl start mysqld
```

### 1.4 创建数据库

```bash
mysql -u root -p <<'SQL'
CREATE DATABASE IF NOT EXISTS apaas_builder CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'apaas'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON apaas_builder.* TO 'apaas'@'localhost';
FLUSH PRIVILEGES;
SQL
```

## 2. 部署代码

### 2.1 克隆仓库

```bash
cd /root
git clone https://github.com/Mars-hub404/apaas-builder-ai.git apaas-builder
cd apaas-builder
```

### 2.2 后端配置

```bash
cd /root/apaas-builder/backend

# 创建虚拟环境
python3.13 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
```

### 2.3 配置环境变量

```bash
cp .env.example .env
vim .env
```

`.env` 关键配置项：

```env
# 数据库（必须）
DATABASE_URL=mysql+aiomysql://apaas:your_password@localhost:3306/apaas_builder?charset=utf8mb4

# LLM 配置（必须）
LLM_API_BASE=https://api.minimax.chat
LLM_API_KEY=your_llm_api_key
LLM_MODEL=MiniMax-M2.7

# JWT 密钥（必须，请生成随机字符串）
JWT_SECRET_KEY=your_random_secret_key_here
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# 服务端口（与 Nginx 代理对应）
HOST=0.0.0.0
PORT=8003

# Claude Agent SDK（可选）
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_API_KEY=your_key
ANTHROPIC_MODEL=MiniMax-M2.7
```

> **注意**：`PORT` 需要与 Nginx 中 `proxy_pass` 的端口一致。

### 2.4 构建前端

```bash
cd /root/apaas-builder/frontend
npm install

# 带子路径构建（部署到 /ai-builder/ 下）
npx vite build --base=/ai-builder/

# 如果部署到根路径，直接：
# npm run build
```

构建产物在 `dist/` 目录。

## 3. Nginx 配置

### 3.1 创建配置文件

```bash
cat > /etc/nginx/apaas-builder.conf << 'NGINX'
# aPaaS Builder AI — 需包含在 server 块内

# 前端静态资源
location /ai-builder/ {
    alias /root/apaas-builder/frontend/dist/;
    try_files $uri $uri/ /ai-builder/index.html;
}

# 后端 API（含 SSE 流式接口：/applications/.../execute、/ai-builder/chat/stream 等）
# 关键：SSE 必须关 buffering，timeout 要覆盖最长 LLM 响应时间（大文档解析可能 >5 分钟）
location /ai-builder/api/ {
    rewrite ^/ai-builder/api/(.*) /api/$1 break;
    proxy_pass http://127.0.0.1:8003;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 1800s;
    proxy_send_timeout 1800s;

    # SSE 流式三件套：缺了就前端看不到增量 / 中途断连报 "network error"
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header X-Accel-Buffering no;
    chunked_transfer_encoding on;
    tcp_nodelay on;

    client_max_body_size 50m;
}

# 代理平台 API
location /ai-builder/platform/ {
    rewrite ^/ai-builder/(.*) /$1 break;
    proxy_pass http://127.0.0.1:8003;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 1800s;
}

location /ai-builder/backend/ {
    rewrite ^/ai-builder/(.*) /$1 break;
    proxy_pass http://127.0.0.1:8003;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 1800s;
}
NGINX
```

### 3.2 引入到 Nginx 主配置

在 `/etc/nginx/nginx.conf` 的 HTTPS server 块内添加：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    # SSL 证书配置
    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # ... 其他已有配置 ...

    # 引入 aPaaS Builder AI 配置
    include /etc/nginx/apaas-builder.conf;
}
```

### 3.3 测试并重载

```bash
nginx -t && nginx -s reload
```

## 4. 启动服务

### 方式一：nohup（简单）

```bash
cd /root/apaas-builder/backend
nohup .venv/bin/python -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8003 --workers 2 \
    > /root/apaas-builder/backend.log 2>&1 &
```

### 方式二：systemd（推荐生产环境）

```bash
cat > /etc/systemd/system/apaas-builder.service << 'EOF'
[Unit]
Description=aPaaS Builder AI Backend
After=network.target mysqld.service

[Service]
Type=simple
User=root
WorkingDirectory=/root/apaas-builder/backend
Environment=PATH=/root/apaas-builder/backend/.venv/bin:/usr/local/bin:/usr/bin
ExecStart=/root/apaas-builder/backend/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8003 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable apaas-builder
systemctl start apaas-builder
```

查看状态：

```bash
systemctl status apaas-builder
journalctl -u apaas-builder -f  # 实时日志
```

## 5. 验证部署

```bash
# 检查后端
curl -s http://localhost:8003/api/health
# 预期返回：{"status":"ok"}

# 检查前端
curl -sk https://your-domain.com/ai-builder/ -o /dev/null -w "%{http_code}"
# 预期返回：200

# 检查 API 代理
curl -sk https://your-domain.com/ai-builder/api/health -o /dev/null -w "%{http_code}"
# 预期返回：200
```

## 6. 首次使用

1. 访问 `https://your-domain.com/ai-builder/`
2. 注册账号并登录
3. 进入**环境管理**，添加得帆云平台连接信息：
   - 平台地址（如 `https://apaas.example.com/backend`）
   - 租户 ID
   - 账号密码
4. 点击"登录"验证连接
5. 设为默认环境
6. 回到首页，开始对话搭建应用

## 7. 更新部署

```bash
cd /root/apaas-builder

# 拉取最新代码
git pull origin main

# 更新后端依赖（如有变更）
cd backend && .venv/bin/pip install -r requirements.txt

# 重新构建前端
cd ../frontend && npx vite build --base=/ai-builder/

# 重启后端
systemctl restart apaas-builder
# 或：fuser -k 8003/tcp && cd /root/apaas-builder/backend && nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8003 --workers 2 > /root/apaas-builder/backend.log 2>&1 &
```

## 8. 常见问题

### 白屏（前端加载但页面空白）

前端路由 base path 未匹配。检查：
- `vite build --base=/ai-builder/` 是否带了正确的 base
- `router/index.ts` 中 `createWebHistory(import.meta.env.BASE_URL)` 是否正确

### 后端 502 Bad Gateway

```bash
# 检查后端是否在运行
ss -tlnp | grep 8003

# 查看日志
tail -50 /root/apaas-builder/backend.log
```

### 数据库连接失败

```bash
# 验证 MySQL 运行状态
systemctl status mysqld

# 验证连接
mysql -u apaas -p apaas_builder -e "SELECT 1"

# 检查 .env 中 DATABASE_URL 格式
```

### "未配置平台环境"

进入环境管理页面，添加平台连接信息并点击"登录"。确保环境状态为"已连接"。

## 9. 代码工作区配置

代码工作区已经内置在 AI Builder 前端和后端工具链中，不需要单独安装浏览器 IDE 服务。用户在 `/ai-builder/coding` 中查看文件树、源码、diff、命令输出和对话记录，后端负责读写工作区文件并执行受控命令。

### 9.1 配置工作区根目录

在 `/root/apaas-builder/backend/.env` 中确认：

```env
APAAS_WORKSPACE_ROOT=/root/apaas-builder/workspaces
APAAS_NPM_CACHE_DIR=/root/apaas-builder/workspaces/.npm-cache
```

创建目录并确保后端进程可读写：

```bash
mkdir -p /root/apaas-builder/workspaces/.npm-cache
chown -R root:root /root/apaas-builder/workspaces
```

### 9.2 配置命令执行前置

代码工作区会按场景运行 `npm`、`mvn`、打包和上传命令。确认宿主机具备：

```bash
node -v
npm -v
java -version
mvn -version
git --version
```

如果使用容器化 sandbox，请参考根目录 [DEPLOY_CONTAINER.md](../DEPLOY_CONTAINER.md) 构建 `vibe-sandbox:latest` 并挂载 Docker socket。

### 9.3 验证

1. 进入 AI Builder 自开发资产库。
2. 打开一个自开发资产或新建代码工作区。
3. 确认左侧文件树可加载，主区域能打开源码和 diff。
4. 让 AI 执行一次只读命令，例如读取 `src/apaas.json` 或运行构建检查。
5. 需要发布时，通过代码工作区工具链重新打包、上传并发布应用。

## 目录结构

```
/root/apaas-builder/
├── backend/
│   ├── .env              # 环境变量（不提交到 git）
│   ├── .venv/            # Python 虚拟环境
│   ├── app/              # 后端源码
│   ├── requirements.txt
│   └── run.py
├── frontend/
│   ├── dist/             # 构建产物（Nginx 指向此目录）
│   ├── src/              # 前端源码
│   └── package.json
├── workspaces/           # 代码工作区文件、构建产物和 npm 缓存
└── backend.log           # 后端日志（nohup 模式）
```
