set -euo pipefail

NAMESPACE='apaas-builder'
APP_NAME='apaas-builder-dev'
PROD_APP_NAME='apaas-builder'
IMAGE='hub.dfy.definesys.cn/ai-builder/apaas-builder:dev-20260606-c5c7184e'
DEV_HOST='agent.dfy.definesys.cn'
PROD_HOST='df-aigc.dfy.definesys.cn'
PUBLIC_URL='https://agent.dfy.definesys.cn/ai-builder/login'
APAAS_BASE_URL='https://apaas-trial.definesys.cn/backend'
APAAS_TENANT_ID='833831156406288385'
DEV_DATABASE_NAME='apaas_builder_dev'
SOURCE_NGINX_CM='apaas-builder-nginx'
NGINX_CM='apaas-builder-dev-nginx'
SOURCE_BACKEND_SECRET='apaas-backend-env'
BACKEND_SECRET='apaas-backend-env-dev'
WORKSPACES_PVC='apaas-workspaces-dev'
STORAGE_CLASS='local-path'
WORKSPACES_SIZE='50Gi'
IMAGE_PULL_SECRET='regcred-hub-dfy'
NODE_AFFINITY_KEY='apaas.definesys.com/app-tier'
ROLL_TIMEOUT='300s'

echo "[1/7] checking namespace"
kubectl get namespace "$NAMESPACE" >/dev/null

echo "[2/7] applying nginx ConfigMap from repo"
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
    # nginx sidecar 把前缀去掉再转给后端 / code-server（它们都在根路径上）
    # ============================================================

    # code-server (Web IDE + WebSocket) — 最优先匹配
    location ^~ /ai-builder/ide/ {
        rewrite ^/ai-builder/ide/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Prefix /ai-builder/ide;

        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

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

    # 平台管理 admin-spa：父应用 /platform-admin iframe 加载同源 /admin/*
    location /admin/ {
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

    # admin-spa 按 /api 调后端，和本地 vite proxy 保持一致。
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
kubectl -n "$NAMESPACE" create configmap "$NGINX_CM" \
  --from-file=default.conf=/tmp/apaas-builder-nginx-default.conf \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[3/7] syncing backend Secret"
echo "      using isolated dev database: $DEV_DATABASE_NAME"
kubectl -n "$NAMESPACE" get secret "$SOURCE_BACKEND_SECRET" -o jsonpath='{.data.backend\.env}' \
  | base64 -d \
  | sed "s#${PROD_HOST}#${DEV_HOST}#g" \
  > /tmp/apaas-builder-backend.env
if grep -q '^APAAS_BASE_URL=' /tmp/apaas-builder-backend.env; then
  sed -i "s#^APAAS_BASE_URL=.*#APAAS_BASE_URL=${APAAS_BASE_URL}#" /tmp/apaas-builder-backend.env
else
  printf 'APAAS_BASE_URL=%s\n' "$APAAS_BASE_URL" >> /tmp/apaas-builder-backend.env
fi
if grep -q '^APAAS_TENANT_ID=' /tmp/apaas-builder-backend.env; then
  sed -i "s#^APAAS_TENANT_ID=.*#APAAS_TENANT_ID=${APAAS_TENANT_ID}#" /tmp/apaas-builder-backend.env
else
  printf 'APAAS_TENANT_ID=%s\n' "$APAAS_TENANT_ID" >> /tmp/apaas-builder-backend.env
fi
if grep -q '^DATABASE_URL=mysql' /tmp/apaas-builder-backend.env; then
  sed -i -E "s#^(DATABASE_URL=[^:]+://[^/]+/)[^?]*(.*)#\1${DEV_DATABASE_NAME}\2#" /tmp/apaas-builder-backend.env
else
  echo "ERROR: DATABASE_URL is missing or not mysql; refusing to deploy dev against an unknown database" >&2
  exit 1
fi
kubectl -n "$NAMESPACE" create secret generic "$BACKEND_SECRET" \
  --from-file=backend.env=/tmp/apaas-builder-backend.env \
  --dry-run=client -o yaml \
  | kubectl apply -f -

echo "[4/7] deleting old StatefulSet/Pods so stale probes cannot survive"
kubectl -n "$NAMESPACE" delete statefulset "$APP_NAME" --ignore-not-found=true --wait=true
kubectl -n "$NAMESPACE" delete pod -l app="$APP_NAME" --ignore-not-found=true --wait=true || true

echo "[5/7] applying workloads"
kubectl apply -f - <<YAML
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${WORKSPACES_PVC}
  namespace: ${NAMESPACE}
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ${STORAGE_CLASS}
  resources:
    requests:
      storage: ${WORKSPACES_SIZE}
---
apiVersion: v1
kind: Service
metadata:
  name: ${APP_NAME}
  namespace: ${NAMESPACE}
  labels:
    app: ${APP_NAME}
spec:
  type: ClusterIP
  selector:
    app: ${APP_NAME}
  ports:
    - name: http
      port: 80
      targetPort: http
---
apiVersion: v1
kind: Service
metadata:
  name: ${APP_NAME}-headless
  namespace: ${NAMESPACE}
spec:
  clusterIP: None
  selector:
    app: ${APP_NAME}
  ports:
    - name: http
      port: 80
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: ${APP_NAME}
  namespace: ${NAMESPACE}
  labels:
    app: ${APP_NAME}
spec:
  serviceName: ${APP_NAME}-headless
  replicas: 1
  selector:
    matchLabels:
      app: ${APP_NAME}
  template:
    metadata:
      labels:
        app: ${APP_NAME}
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: ${NODE_AFFINITY_KEY}
                    operator: Exists
      initContainers:
        - name: copy-frontend-dist
          image: ${IMAGE}
          imagePullPolicy: Always
          command:
            - sh
            - -c
            - |
              set -eu
              rm -rf /share/dist/*
              cp -R /app/frontend/dist/. /share/dist/
              echo "dist files:" && ls /share/dist/ | head
          volumeMounts:
            - name: frontend-dist
              mountPath: /share/dist
      containers:
        - name: apaas-builder
          image: ${IMAGE}
          imagePullPolicy: Always
          env:
            - name: CODE_SERVER_BIND_HOST
              value: "127.0.0.1"
            - name: WAIT_FOR_MYSQL
              value: "1"
            - name: APAAS_WORKSPACE_ROOT
              value: "/root/apaas-builder/workspaces"
            - name: APAAS_NPM_CACHE_DIR
              value: "/root/apaas-builder/workspaces/.npm-cache"
          ports:
            - name: api
              containerPort: 8003
            - name: ide
              containerPort: 8080
          volumeMounts:
            - name: workspaces
              mountPath: /root/apaas-builder/workspaces
            - name: backend-env
              mountPath: /app/backend/.env
              subPath: backend.env
              readOnly: true
          readinessProbe:
            tcpSocket:
              port: api
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 6
          livenessProbe:
            tcpSocket:
              port: api
            initialDelaySeconds: 180
            periodSeconds: 30
            timeoutSeconds: 5
            failureThreshold: 3
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2"
              memory: "4Gi"
        - name: web
          image: nginx:alpine
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 80
          volumeMounts:
            - name: frontend-dist
              mountPath: /usr/share/nginx/html
              readOnly: true
            - name: nginx-conf
              mountPath: /etc/nginx/conf.d/default.conf
              subPath: default.conf
              readOnly: true
          readinessProbe:
            httpGet:
              path: /index.html
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              cpu: "50m"
              memory: "64Mi"
            limits:
              cpu: "500m"
              memory: "256Mi"
      volumes:
        - name: workspaces
          persistentVolumeClaim:
            claimName: ${WORKSPACES_PVC}
        - name: backend-env
          secret:
            secretName: ${BACKEND_SECRET}
        - name: frontend-dist
          emptyDir: {}
        - name: nginx-conf
          configMap:
            name: ${NGINX_CM}
      imagePullSecrets:
        - name: ${IMAGE_PULL_SECRET}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ${APP_NAME}
  namespace: ${NAMESPACE}
  annotations:
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
spec:
  ingressClassName: nginx
  rules:
    - host: ${DEV_HOST}
      http:
        paths:
          - path: /ai-builder
            pathType: Prefix
            backend:
              service:
                name: ${APP_NAME}
                port:
                  name: http
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ${APP_NAME}
                port:
                  name: http
YAML

echo "[6/7] checking host conflicts"
kubectl get ingress -A \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,HOSTS:.spec.rules[*].host' \
  --no-headers \
  | awk -v host="$DEV_HOST" -v ns="$NAMESPACE" -v app="$APP_NAME" '$0 ~ host && !($1 == ns && $2 == app) {print "WARNING host conflict:", $0}'

echo "probe config now in StatefulSet:"
kubectl -n "$NAMESPACE" get statefulset "$APP_NAME" -o yaml | sed -n '/readinessProbe:/,/resources:/p'

echo "[7/7] waiting for rollout"
kubectl -n "$NAMESPACE" rollout status "statefulset/$APP_NAME" --timeout="$ROLL_TIMEOUT"
kubectl -n "$NAMESPACE" get pods,sts,svc,ingress,pvc | grep -E "NAME|${PROD_APP_NAME}|${APP_NAME}|mcp|ming" || true
echo "statefulset images:"
kubectl -n "$NAMESPACE" get statefulset "$APP_NAME" -o jsonpath='{range .spec.template.spec.initContainers[*]}init/{.name}={.image}{"\n"}{end}{range .spec.template.spec.containers[*]}container/{.name}={.image}{"\n"}{end}'
POD="$(kubectl -n "$NAMESPACE" get pod -l app="$APP_NAME" -o jsonpath='{.items[0].metadata.name}')"
echo "running pod: $POD"
kubectl -n "$NAMESPACE" exec "$POD" -c apaas-builder -- python - <<'PY' || true
from pathlib import Path
from urllib.request import urlopen

main = Path("/app/backend/app/main.py").read_text()
try:
    print("health_before_routers=", main.index('@app.get("/api/health")') < main.index('app.include_router(auth.router, prefix="/api")'))
except ValueError as exc:
    print("health_order_check_failed=", exc)

try:
    with urlopen("http://127.0.0.1:8003/api/health", timeout=5) as resp:
        print("IN_POD_HEALTH_HTTP", resp.status)
        print(resp.read(200).decode("utf-8", "replace"))
except Exception as exc:
    print("IN_POD_HEALTH_FAILED", repr(exc))
PY

if command -v curl >/dev/null 2>&1; then
  curl -k -sS -o /tmp/apaas-builder-dev-login.html \
    -w "HTTP %{http_code}\nURL %{url_effective}\nTYPE %{content_type}\nSIZE %{size_download}\n" \
    "$PUBLIC_URL" || true
  MCP_API_KEY="$(awk -F= '/^MCP_API_KEYS=/{print $2; exit}' /tmp/apaas-builder-backend.env | cut -d, -f1)"
  if [ -n "$MCP_API_KEY" ]; then
    curl -k -sS -o /tmp/apaas-builder-dev-mcp-tools.json \
      -w "MCP_TOOLS_HTTP %{http_code}\n" \
      -X POST "https://${DEV_HOST}/api/mcp/mcp" \
      -H "Authorization: Bearer $MCP_API_KEY" \
      -H "Content-Type: application/json" \
      -H "Accept: application/json, text/event-stream" \
      --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' || true
    head -c 200 /tmp/apaas-builder-dev-mcp-tools.json || true
    echo
  else
    echo "MCP_TOOLS_HTTP skipped: MCP_API_KEYS missing in backend env"
  fi
fi

echo "done: $PUBLIC_URL"
