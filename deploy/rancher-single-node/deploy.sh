#!/usr/bin/env sh
# apaas-builder Rancher single-node Kubernetes installer.
#
# Designed for customer-side Rancher/Kubernetes terminals where the image has
# already been imported into the node runtime or pushed to a reachable registry.

set -eu
(set -o pipefail) 2>/dev/null && set -o pipefail || true

c_red="$(printf '\033[31m')"
c_grn="$(printf '\033[32m')"
c_yel="$(printf '\033[33m')"
c_blu="$(printf '\033[36m')"
c_rst="$(printf '\033[0m')"

log() { printf '%s[deploy-rancher]%s %s\n' "$c_blu" "$c_rst" "$*"; }
ok() { printf '%s[ ok ]%s %s\n' "$c_grn" "$c_rst" "$*"; }
warn() { printf '%s[warn]%s %s\n' "$c_yel" "$c_rst" "$*" >&2; }
die() { printf '%s[fail]%s %s\n' "$c_red" "$c_rst" "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

default_scheme() {
  case "${BUILDER_HOST:-}" in
    "") printf '%s' "" ;;
    http://*|https://*) printf '%s' "" ;;
    *) printf '%s' "https://" ;;
  esac
}

external_base_url() {
  case "$BUILDER_HOST" in
    "") printf '%s' "" ;;
    http://*|https://*) printf '%s' "${BUILDER_HOST%/}" ;;
    *) printf '%s%s' "$(default_scheme)" "${BUILDER_HOST%/}" ;;
  esac
}

external_host_name() {
  host="$BUILDER_HOST"
  host="${host#http://}"
  host="${host#https://}"
  host="${host%%/*}"
  printf '%s' "$host"
}

prompt() {
  var_name="$1"
  label="$2"
  default_value="${3:-}"
  secret="${4:-0}"
  current_value="$(eval "printf '%s' \"\${$var_name:-}\"")"
  if [ -n "$current_value" ]; then
    return
  fi

  while :; do
    if [ -n "$default_value" ]; then
      printf '%s [%s]: ' "$label" "$default_value" >&2
    else
      printf '%s: ' "$label" >&2
    fi
    if [ "$secret" = "1" ]; then
      stty -echo 2>/dev/null || true
      IFS= read -r value || value=""
      stty echo 2>/dev/null || true
      printf '\n' >&2
    else
      IFS= read -r value || value=""
    fi
    if [ -z "$value" ]; then
      value="$default_value"
    fi
    if [ -n "$value" ]; then
      eval "$var_name=\$value"
      export "$var_name"
      return
    fi
    warn "$label is required"
  done
}

prompt_optional() {
  var_name="$1"
  label="$2"
  default_value="${3:-}"
  current_value="$(eval "printf '%s' \"\${$var_name:-}\"")"
  if [ -n "$current_value" ]; then
    return
  fi
  if [ -n "$default_value" ]; then
    printf '%s [%s]: ' "$label" "$default_value" >&2
  else
    printf '%s: ' "$label" >&2
  fi
  IFS= read -r value || value=""
  if [ -z "$value" ]; then
    value="$default_value"
  fi
  eval "$var_name=\$value"
  export "$var_name"
}

rand_b64() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr -d '\n'
  else
    head -c 32 /dev/urandom | base64 | tr -d '\n'
  fi
}

rand_fernet() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
  else
    head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'
  fi
}

append_env() {
  key="$1"
  value="$2"
  printf '%s=%s\n' "$key" "$value" >> "$BACKEND_ENV_TMP"
}

preflight() {
  need kubectl
  kubectl version --client >/dev/null 2>&1 || die "kubectl is not available"
  kubectl cluster-info >/dev/null 2>&1 || die "kubectl cannot reach the cluster"
  ok "kubectl connected"
}

collect_inputs() {
  NAMESPACE="${NAMESPACE:-apaas-builder}"
  APP_NAME="${APP_NAME:-apaas-builder}"
  IMAGE="${IMAGE:-docker.io/library/apaas-builder:latest}"
  NGINX_IMAGE="${NGINX_IMAGE:-docker.io/library/nginx:alpine}"
  IMAGE_PULL_POLICY="${IMAGE_PULL_POLICY:-Never}"
  IMAGE_PULL_SECRET="${IMAGE_PULL_SECRET:-}"
  STORAGE_CLASS="${STORAGE_CLASS:-local-path}"
  WORKSPACES_SIZE="${WORKSPACES_SIZE:-50Gi}"
  INGRESS_CLASS="${INGRESS_CLASS:-nginx}"
  BUILDER_HOST="${BUILDER_HOST:-}"
  DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:////root/apaas-builder/workspaces/apaas_builder.db}"

  if [ -n "$BUILDER_HOST" ]; then
    default_code_server_url="$(external_base_url)/ai-builder/ide/"
    default_public_url="$(external_base_url)/ai-builder/login"
  else
    default_code_server_url=""
    default_public_url=""
  fi

  printf '\n%s\n' "Please enter aPaaS connection setting."
  prompt APAAS_BASE_URL "aPaaS backend URL, for example https://apaas.example.com/backend" "${APAAS_BASE_URL:-}"
  BUILDER_HOST_NAME="$(external_host_name)"
  export BUILDER_HOST_NAME

  APAAS_TENANT_ID="${APAAS_TENANT_ID:-}"
  JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(rand_b64)}"
  ENCRYPTION_KEY="${ENCRYPTION_KEY:-$(rand_b64)}"
  BUILDER_FERNET_KEY="${BUILDER_FERNET_KEY:-$(rand_fernet)}"
}

create_backend_secret() {
  BACKEND_SECRET="${BACKEND_SECRET:-${APP_NAME}-backend-env}"
  BACKEND_ENV_TMP="$(mktemp)"
  : > "$BACKEND_ENV_TMP"

  append_env DATABASE_URL "$DATABASE_URL"
  append_env APAAS_BASE_URL "$APAAS_BASE_URL"
  append_env APAAS_TENANT_ID "$APAAS_TENANT_ID"
  append_env JWT_SECRET_KEY "$JWT_SECRET_KEY"
  append_env JWT_ALGORITHM "HS256"
  append_env JWT_EXPIRE_MINUTES "1440"
  append_env ENCRYPTION_KEY "$ENCRYPTION_KEY"
  append_env BUILDER_FERNET_KEY "$BUILDER_FERNET_KEY"
  append_env HOST "0.0.0.0"
  append_env PORT "8003"
  append_env APAAS_WORKSPACE_ROOT "/root/apaas-builder/workspaces"
  append_env APAAS_NPM_CACHE_DIR "/root/apaas-builder/workspaces/.npm-cache"

  log "applying backend Secret: $BACKEND_SECRET"
  kubectl -n "$NAMESPACE" create secret generic "$BACKEND_SECRET" \
    --from-file=backend.env="$BACKEND_ENV_TMP" \
    --dry-run=client -o yaml | kubectl apply -f -
  rm -f "$BACKEND_ENV_TMP"
}

create_nginx_config() {
  NGINX_CM="${NGINX_CM:-${APP_NAME}-nginx}"
  NGINX_TMP="$(mktemp)"
  cat > "$NGINX_TMP" <<'NGINX_CONF'
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
    absolute_redirect off;

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

    location ~ "^/ai-builder/[0-9a-f]{32}/" {
        rewrite ^/ai-builder/(.*)$ /$1 break;
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }

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

    location ~ "^/(env\\.tmpl\\.js|browser\\.js|favicon\\.ico|.+\\.(js|css|map|json|png|jpe?g|gif|svg|ico|webp|woff2?|ttf|eot))$" {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $proxy_x_forwarded_proto;
    }

    location ^~ /ai-builder/assets/ {
        alias /usr/share/nginx/html/assets/;
        access_log off;
        expires 7d;
        add_header Cache-Control "public, max-age=604800, immutable";
        try_files $uri =404;
    }

    location /ai-builder/ {
        rewrite ^/ai-builder/(.*)$ /$1 break;
        try_files $uri $uri/ /index.html;
    }

    location = / {
        return 301 /ai-builder/;
    }

    location = /ai-builder {
        return 301 /ai-builder/;
    }
}
NGINX_CONF

  log "applying nginx ConfigMap: $NGINX_CM"
  kubectl -n "$NAMESPACE" create configmap "$NGINX_CM" \
    --from-file=default.conf="$NGINX_TMP" \
    --dry-run=client -o yaml | kubectl apply -f -
  rm -f "$NGINX_TMP"
}

apply_workloads() {
  WORKSPACES_PVC="${WORKSPACES_PVC:-${APP_NAME}-workspaces}"
  IMAGE_PULL_SECRETS_BLOCK=""
  if [ -n "${IMAGE_PULL_SECRET:-}" ]; then
    IMAGE_PULL_SECRETS_BLOCK="      imagePullSecrets:
        - name: ${IMAGE_PULL_SECRET}"
  fi
  INGRESS_RULE_PREFIX="    - http:"
  if [ -n "${BUILDER_HOST_NAME:-}" ]; then
    INGRESS_RULE_PREFIX="    - host: ${BUILDER_HOST_NAME}
      http:"
  fi

  log "applying Kubernetes workloads"
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
${IMAGE_PULL_SECRETS_BLOCK}
      initContainers:
        - name: copy-frontend-dist
          image: ${IMAGE}
          imagePullPolicy: ${IMAGE_PULL_POLICY}
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
          imagePullPolicy: ${IMAGE_PULL_POLICY}
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
          image: ${NGINX_IMAGE}
          imagePullPolicy: ${IMAGE_PULL_POLICY}
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
  ingressClassName: ${INGRESS_CLASS}
  rules:
${INGRESS_RULE_PREFIX}
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
}

wait_rollout() {
  ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
  log "waiting for rollout"
  kubectl -n "$NAMESPACE" rollout status "statefulset/$APP_NAME" --timeout="$ROLL_TIMEOUT"
}

verify() {
  log "current resources"
  kubectl -n "$NAMESPACE" get pods,sts,svc,ingress,pvc | grep -E "NAME|${APP_NAME}" || true
  pod="$(kubectl -n "$NAMESPACE" get pod -l app="$APP_NAME" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [ -n "$pod" ]; then
    log "pod logs tail: $pod"
    kubectl -n "$NAMESPACE" logs "$pod" -c apaas-builder --tail=60 || true
  fi
  printf '\n%s\n' "Done: $(external_base_url)/ai-builder/login"
}

main() {
  preflight
  collect_inputs
  log "creating namespace: $NAMESPACE"
  kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
  create_backend_secret
  create_nginx_config
  apply_workloads
  wait_rollout
  verify
}

main "$@"
