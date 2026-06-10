#!/usr/bin/env bash
# Roll out the prebuilt main/prod image.
#
# Safe for KubeSphere / web kubectl terminals: this script is self-contained and
# does not need the repository files to exist on the target machine. It refreshes
# the nginx ConfigMap, updates StatefulSet images, and waits for rollout. It does
# not delete databases, Secrets, PVCs, or workspace volumes, so data remains in place.

set -euo pipefail

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder}"
NGINX_CM="${NGINX_CM:-${APP_NAME}-nginx}"
IMAGE="${IMAGE:-hub.dfy.definesys.cn/ai-builder/apaas-builder:main-20260608-mcp-external-route-fix}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-apaas-builder}"
DIST_INIT_CONTAINER="${DIST_INIT_CONTAINER:-copy-frontend-dist}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
PUBLIC_URL="${PUBLIC_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/login}"
ADMIN_URL="${ADMIN_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/platform-admin}"
ADMIN_DIRECT_URL="${ADMIN_DIRECT_URL:-https://df-aigc.dfy.definesys.cn/ai-builder/admin}"
MCP_URL="${MCP_URL:-https://df-aigc.dfy.definesys.cn/api/mcp/mcp}"

log() { printf '[deploy-main-image] %s\n' "$*"; }
die() { printf '[deploy-main-image][fail] %s\n' "$*" >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || die 'missing command: kubectl'

apply_nginx_config() {
  log "apply nginx ConfigMap: ${NGINX_CM}"
  cat > /tmp/apaas-builder-nginx-default.conf <<'NGINX_CONF'
# WebSocket upgrade map（http{} context 生效，conf.d/*.conf 会被主 nginx.conf 的 include 放进 http{}）
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

map $http_x_forwarded_proto $proxy_x_forwarded_proto {
    default $http_x_forwarded_proto;
    ''      $scheme;
}

server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    client_max_body_size 100M;

    # Ingress 解包 TLS 后用 HTTP 转发到 sidecar，return 301 /foo/ 默认会生成
    # Location: http://host/foo/。absolute_redirect off 让 nginx 返回相对路径，
    # 浏览器保留原 scheme（https）。
    absolute_redirect off;

    # ============================================================
    # 路径前缀部署：/ai-builder/*
    # 前端 build 时 VITE_BASE_URL=/ai-builder/，资源都带这个前缀
    # nginx sidecar 把前缀去掉再转给后端（后端在根路径上）
    # ============================================================

    # 后端 API：/ai-builder/api/* → 后端 /api/*
    location /ai-builder/api/ {
        rewrite ^/ai-builder/api/(.*)$ /api/$1 break;
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;

        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
        proxy_set_header X-Forwarded-Prefix /ai-builder;

        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    # 保留根 /api 给少量同源兼容调用；主应用线上入口使用 /ai-builder/api/*。
    location /api/ {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;

        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;

        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    # 平台管理 admin-spa 由后端 StaticFiles 挂载在 /admin。
    # 主前端 /platform-admin iframe 会访问同源 /admin/*。
    location = /ai-builder/admin {
        return 302 /ai-builder/admin/;
    }

    location ^~ /ai-builder/admin/ {
        rewrite ^/ai-builder/admin/(.*)$ /admin/$1 break;
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
        proxy_set_header X-Forwarded-Prefix /ai-builder;
    }

    location ^~ /admin/ {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
    }

    location = /admin {
        return 302 /admin/;
    }

    location ^~ /platform-admin/ {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
    }

    location = /platform-admin {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
    }

    # 平台代理路由：与 backend/app/routes/platform_proxy.py 中声明的顶层路径保持一致。
    # 这些路径都是 aPaaS iframe 内部页面 / API / 运行态 / 插件资源，不能落到 SPA fallback。
    location ~ ^/ai-builder/(platform|backend|plugin|xdap-admin|xdap-plugin|xdap-app|xdap-open|common|smartbi|apaas|app|m)(/|$) {
        rewrite ^/ai-builder/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;

        proxy_buffering off;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;

        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    # aPaaS iframe 内部会跳转/加载根路径绝对地址（例如 /platform/...、/backend/...）。
    # dev 站点的 Ingress 同时把 "/" 转到本服务，所以这些根路径也必须交给后端平台代理；
    # 否则会落到 sidecar nginx 静态文件查找，页面显示 nginx/1.29.1 的 404。
    location ~ ^/(platform|backend|plugin|xdap-admin|xdap-plugin|xdap-app|xdap-open|common|smartbi|apaas|app|m)(/|$) {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;

        proxy_buffering off;
        proxy_set_header Connection "";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;

        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    # 平台插件资源：/{32位hex}/... —— 后端 middleware 识别
    # aPaaS iframe 在 /ai-builder 前缀下时，插件资源可能被浏览器解析成
    # /ai-builder/{32位hex}/...，需要先剥掉前缀再交给后端 middleware。
    location ~ "^/ai-builder/[0-9a-f]{32}/" {
        rewrite ^/ai-builder/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    # aPaaS iframe 里可能出现不带 /platform 前缀的静态资源绝对路径。
    # 排除前端自己的 /ai-builder/assets 后，其他资源型请求交给后端平台代理兜底。
    location ~ "^/ai-builder/(?!assets/).+\\.(js|css|map|json|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|eot)$" {
        rewrite ^/ai-builder/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
    }

    location ~ "^/[0-9a-f]{32}/" {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

    # 平台 HTML 还可能以根路径加载 env.tmpl.js / browser.js / 图片字体等资源。
    # 前端自己的构建产物都在 /ai-builder/assets/，所以根路径资源可以交给平台代理。
    location ~ "^/(env\\.tmpl\\.js|browser\\.js|favicon\\.ico|.+\\.(js|css|map|json|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|eot))$" {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
    }

    # 静态资源（带 hash 的 assets，Vite 构建产物）
    location ^~ /ai-builder/assets/ {
        alias /usr/share/nginx/html/assets/;
        access_log off;
        expires 7d;
        add_header Cache-Control "public, max-age=604800, immutable";
        try_files $uri =404;
    }

    # SPA 兜底：/ai-builder/ 下一切未命中路径都回 index.html
    location /ai-builder/ {
        rewrite ^/ai-builder/(.*)$ /$1 break;
        try_files $uri $uri/ /index.html;
    }

    # 根路径重定向到 /ai-builder/
    location = / {
        return 301 /ai-builder/;
    }

    # /ai-builder（无斜杠）也重定向到 /ai-builder/
    # 否则 nginx 会当成静态文件找 /usr/share/nginx/html/ai-builder 然后 404
    location = /ai-builder {
        return 301 /ai-builder/;
    }
}
NGINX_CONF
  kubectl -n "${NAMESPACE}" create configmap "${NGINX_CM}" \
    --from-file=default.conf=/tmp/apaas-builder-nginx-default.conf \
    --dry-run=client -o yaml | kubectl apply -f -
}

log "namespace: ${NAMESPACE}"
log "statefulset: ${APP_NAME}"
log "nginx configmap: ${NGINX_CM}"
log "image: ${IMAGE}"

kubectl get namespace "${NAMESPACE}" >/dev/null
kubectl -n "${NAMESPACE}" get "statefulset/${APP_NAME}" >/dev/null

apply_nginx_config

log "update backend container image"
kubectl -n "${NAMESPACE}" set image \
  "statefulset/${APP_NAME}" \
  "${BACKEND_CONTAINER}=${IMAGE}"

log "update frontend dist initContainer image and restart pod"
cat > /tmp/apaas-builder-statefulset-image-patch.yaml <<EOF
spec:
  template:
    metadata:
      annotations:
        deploy-image/restartedAt: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    spec:
      initContainers:
        - name: ${DIST_INIT_CONTAINER}
          image: ${IMAGE}
EOF
kubectl -n "${NAMESPACE}" patch "statefulset/${APP_NAME}" --type=strategic --patch-file /tmp/apaas-builder-statefulset-image-patch.yaml

log "wait for rollout"
kubectl -n "${NAMESPACE}" rollout status "statefulset/${APP_NAME}" --timeout="${ROLL_TIMEOUT}"

pod="$(kubectl -n "${NAMESPACE}" get pod -l "app=${APP_NAME}" -o jsonpath='{.items[0].metadata.name}')"
if [ -n "${pod}" ]; then
  log "current pod: ${pod}"
fi

if command -v curl >/dev/null 2>&1; then
  log "health check: ${PUBLIC_URL}"
  curl -k -L -sS -o /tmp/apaas-builder-main-login.html \
    -w 'LOGIN_HTTP %{http_code} SIZE %{size_download}\n' \
    "${PUBLIC_URL}" || true

  log "admin route check: ${ADMIN_URL}"
  curl -k -L -sS -o /tmp/apaas-builder-main-platform-admin.html \
    -w 'ADMIN_HTTP %{http_code} SIZE %{size_download}\n' \
    "${ADMIN_URL}" || true

  log "admin direct route check: ${ADMIN_DIRECT_URL}"
  curl -k -L -sS -o /tmp/apaas-builder-main-admin.html \
    -w 'ADMIN_DIRECT_HTTP %{http_code} SIZE %{size_download}\n' \
    "${ADMIN_DIRECT_URL}" || true

  log "MCP unauth route check: ${MCP_URL}"
  curl -k -sS -o /tmp/apaas-builder-main-mcp-unauth.json \
    -w 'MCP_UNAUTH_HTTP %{http_code} SIZE %{size_download}\n' \
    -X POST "${MCP_URL}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' || true
fi

log "done"
