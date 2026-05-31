#!/bin/bash
# 02 · 新 repo 初始化脚本
#
# 用法：从 ai-builder repo 根目录执行
#   bash docs/refactor-mcp-server/02-init-new-repo.sh /path/to/new-repo-parent
#
# 例：
#   cd "/Users/mars/Vibe Coding/apaas-builder-ai"
#   bash docs/refactor-mcp-server/02-init-new-repo.sh "/Users/mars/Vibe Coding"
#
# 完成后产物：
#   /Users/mars/Vibe Coding/apaas-builder-mcp-server/
#
# 注意：此脚本只做"复制 + 初始化"，不做"砍 routes"（那是 Phase 2 手工 review）

set -e

# ────────────── 参数 ──────────────
NEW_REPO_PARENT="${1:-$HOME/Vibe Coding}"
NEW_REPO_NAME="apaas-builder-mcp-server"
NEW_REPO="$NEW_REPO_PARENT/$NEW_REPO_NAME"
SOURCE_REPO="$(pwd)"

if [ ! -f "$SOURCE_REPO/backend/app/mcp_server.py" ]; then
  echo "❌ 当前目录不像 apaas-builder-ai repo 根目录（找不到 backend/app/mcp_server.py）"
  echo "   请先 cd 进 apaas-builder-ai repo 再执行此脚本"
  exit 1
fi

if [ -e "$NEW_REPO" ]; then
  echo "❌ 目标目录已存在: $NEW_REPO"
  echo "   先删除或换个名字"
  exit 1
fi

echo "==> 源 repo: $SOURCE_REPO"
echo "==> 新 repo: $NEW_REPO"
echo ""

# ────────────── 1. 建目录结构 ──────────────
echo "==> [1/7] 建目录结构..."
mkdir -p "$NEW_REPO"/{backend/app,admin-spa/src,docs}
cd "$NEW_REPO"

# ────────────── 2. 复制 backend 核心代码 ──────────────
echo "==> [2/7] 复制 backend 核心代码..."

# rsync 选择性复制（排除 __pycache__ / *.pyc）
rsync -a --exclude='__pycache__/' --exclude='*.pyc' --exclude='.venv/' \
  "$SOURCE_REPO/backend/app/" "$NEW_REPO/backend/app/"

# 配置 + migrations + requirements
cp -r "$SOURCE_REPO/backend/config" "$NEW_REPO/backend/config" 2>/dev/null || mkdir -p "$NEW_REPO/backend/config"
cp -r "$SOURCE_REPO/backend/migrations" "$NEW_REPO/backend/migrations" 2>/dev/null || mkdir -p "$NEW_REPO/backend/migrations"
cp "$SOURCE_REPO/backend/requirements.txt" "$NEW_REPO/backend/" 2>/dev/null || true
cp "$SOURCE_REPO/backend/.env.example" "$NEW_REPO/backend/" 2>/dev/null || true

# .env 不复制（含密钥），手工迁移
echo "   ⚠️  .env 没复制，手工从 ai-builder 拷贝一份到新 repo"

# ────────────── 3. 砍掉前端 frontend/ ──────────────
echo "==> [3/7] 跳过 frontend/（不复制，admin SPA 是全新的）"

# ────────────── 4. admin SPA 骨架 ──────────────
echo "==> [4/7] 建 admin SPA 骨架..."

cat > "$NEW_REPO/admin-spa/package.json" << 'EOF'
{
  "name": "apaas-builder-mcp-admin",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.0",
    "element-plus": "^2.7.0",
    "@element-plus/icons-vue": "^2.3.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "@vue/tsconfig": "^0.5.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "vue-tsc": "^2.0.0"
  }
}
EOF

cat > "$NEW_REPO/admin-spa/vite.config.ts" << 'EOF'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:8003'
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false
  }
})
EOF

mkdir -p "$NEW_REPO/admin-spa/src/"{views,components,router,api,stores,utils}

cat > "$NEW_REPO/admin-spa/src/main.ts" << 'EOF'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
EOF

cat > "$NEW_REPO/admin-spa/src/App.vue" << 'EOF'
<template>
  <router-view />
</template>
EOF

cat > "$NEW_REPO/admin-spa/src/router/index.ts" << 'EOF'
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/login', component: () => import('@/views/LoginPage.vue') },
    { path: '/', redirect: '/tenants' },
    { path: '/tenants',   component: () => import('@/views/PlatformTenants.vue'),  meta: { requiresAdmin: true } },
    { path: '/envs',      component: () => import('@/views/PlatformEnvs.vue'),     meta: { requiresAdmin: true } },
    { path: '/llms',      component: () => import('@/views/LlmConfigs.vue'),       meta: { requiresAdmin: true } },
    { path: '/users',     component: () => import('@/views/PlatformUsers.vue'),    meta: { requiresAdmin: true } },
    { path: '/sandboxes', component: () => import('@/views/SandboxMonitor.vue'),   meta: { requiresAdmin: true } },
    { path: '/status',    component: () => import('@/views/SystemStatus.vue'),     meta: { requiresAdmin: true } },
  ]
})

router.beforeEach((to, _from, next) => {
  if (!to.meta.requiresAdmin) return next()
  const token = localStorage.getItem('admin_token')
  if (!token) return next('/login')
  next()
})

export default router
EOF

# 从 ai-builder 复制 PlatformTenants / PlatformEnvs / TenantUsers 4 个核心 view 文件
echo "   📋 待手工复制 + 改造的核心 view 文件:"
echo "     - $SOURCE_REPO/frontend/src/views/PlatformTenants.vue → admin-spa/src/views/"
echo "     - $SOURCE_REPO/frontend/src/views/PlatformEnvs.vue    → admin-spa/src/views/"
echo "     - $SOURCE_REPO/frontend/src/views/TenantUsers.vue     → admin-spa/src/views/ (改名 PlatformUsers.vue)"
echo "     - admin-spa/src/views/LoginPage.vue        (新建)"
echo "     - admin-spa/src/views/LlmConfigs.vue       (从 PlatformEnvs.vue Tab3 抽出)"
echo "     - admin-spa/src/views/SandboxMonitor.vue   (从 Sandboxes.vue 改)"
echo "     - admin-spa/src/views/SystemStatus.vue     (新建)"

# ────────────── 5. nginx 配置 ──────────────
echo "==> [5/7] 写 nginx.conf 示例..."

cat > "$NEW_REPO/nginx.conf.example" << 'EOF'
# apaas-builder-mcp-server nginx 配置示例
# 域名建议：mcp.dfy.definesys.cn （或复用 agent.dfy.definesys.cn 改路径）

server {
    listen 443 ssl http2;
    server_name mcp.dfy.definesys.cn;

    ssl_certificate     /etc/letsencrypt/live/mcp.dfy.definesys.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.dfy.definesys.cn/privkey.pem;

    # MCP streamable HTTP 入口（dolphin omnigate 调）
    location /api/mcp/ {
        proxy_pass http://127.0.0.1:8004/api/mcp/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # SSE 长连接
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
    }

    # admin SPA 用的 backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8004/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # admin SPA 静态文件
    location /admin/ {
        alias /root/apaas-builder-mcp-server/admin-spa/dist/;
        try_files $uri $uri/ /admin/index.html;
        add_header Cache-Control "no-cache, must-revalidate";
    }

    # 根路径重定向
    location = / {
        return 301 /admin/;
    }
}
EOF

# ────────────── 6. git init + .gitignore ──────────────
echo "==> [6/7] git init + .gitignore..."

cat > "$NEW_REPO/.gitignore" << 'EOF'
# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/
.pytest_cache/

# Node
node_modules/
dist/

# Env
.env
.env.local
backend/.env
backend/config/apaas_envs.yaml

# Logs
*.log
backend.log

# Coding workspaces (用户数据)
_online_coding/
.pending-dev-specs/

# IDE
.vscode/
.idea/
*.swp
.DS_Store
EOF

cd "$NEW_REPO"
git init -b main
git add -A
git commit -m "init: apaas-builder-mcp-server 从 apaas-builder-ai 抽出（Phase 1 仅复制框架）

接 2026-05-11 ai-builder 重构 + 用户决策 路径 B 抽独立 repo。

本次提交：
- backend/app/ 完整复制（含全部 49 MCP 工具 + 全部 routes 未砍）
- backend/config / migrations 复制
- admin-spa/ 骨架（package.json + vite + router 仅 8 个路由）
- nginx.conf.example
- .gitignore

下一步（Phase 2）：
- 砍 29 个 user-facing route 文件（见 docs/01-route-cull-plan.md）
- main.py 同步 trim 路由注册
- 5 个 TRIM 文件内部精简

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

echo ""
echo "==> [7/7] ✅ 完成！"
echo ""
echo "新 repo 位置: $NEW_REPO"
echo ""
echo "下一步："
echo "  1. cd $NEW_REPO"
echo "  2. 从 ai-builder 拷贝 backend/.env 进新 repo"
echo "  3. 按 docs/refactor-mcp-server/01-route-cull-plan.md 砍 29 个 route + 5 个 TRIM"
echo "  4. 同步改 main.py 的 include_router 列表"
echo "  5. cd backend && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
echo "  6. 起服务验证：uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload"
echo "  7. curl localhost:8004/api/health"
echo "  8. curl localhost:8004/api/mcp/mcp tools/list 验证 49 工具"
echo "  9. 进 Phase 3 写 Vibe Coding 9 个 MCP 工具（参见 04-vibe-coding-mcp-tools-spec.md）"
echo " 10. 进 Phase 4 写 admin SPA 6 个 view 文件"
echo ""
echo "GitHub remote add （手工）："
echo "  cd $NEW_REPO"
echo "  gh repo create apaas-builder-mcp-server --private --source=. --remote=origin"
echo "  git push -u origin main"
