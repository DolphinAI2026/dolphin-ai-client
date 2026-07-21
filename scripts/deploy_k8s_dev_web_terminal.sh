#!/usr/bin/env bash
# Prepare a dev deployment for the KubeSphere web kubectl terminal.
#
# This script runs the local-only steps:
#   1. verify git is clean
#   2. push current HEAD to origin/dev
#   3. build and push the dev image
#   4. generate a kubectl shell payload to paste into KubeSphere's terminal
#
# It does not require a local kubeconfig.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-$REPO_ROOT/deploy/k8s/dev.env}"

if [ -f "$DEPLOY_ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$DEPLOY_ENV_FILE"
  set +a
fi

NAMESPACE="${NAMESPACE:-apaas-builder}"
APP_NAME="${APP_NAME:-apaas-builder-dev}"
PROD_APP_NAME="${PROD_APP_NAME:-apaas-builder}"

DEV_BRANCH="${DEV_BRANCH:-dev}"
PUSH_DEV="${PUSH_DEV:-1}"
ALLOW_DIRTY="${ALLOW_DIRTY:-0}"

IMAGE_REPO="${IMAGE_REPO:-hub.dfy.definesys.cn/ai-builder/apaas-builder}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMAGE="${IMAGE:-}"
SKIP_IMAGE_BUILD="${SKIP_IMAGE_BUILD:-0}"
PLATFORM="${PLATFORM:-linux/amd64}"
VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
VITE_ADMIN_BASE="${VITE_ADMIN_BASE:-/ai-builder/admin/}"

DEV_HOST="${DEV_HOST:-agent.dfy.definesys.cn}"
PROD_HOST="${PROD_HOST:-df-aigc.dfy.definesys.cn}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-/ai-builder/api}"
VITE_MCP_PUBLIC_BASE="${VITE_MCP_PUBLIC_BASE:-https://${DEV_HOST}/ai-builder}"
PUBLIC_URL="${PUBLIC_URL:-https://${DEV_HOST}/ai-builder/login}"
APAAS_BASE_URL="${APAAS_BASE_URL:-}"
DEV_DATABASE_NAME="${DEV_DATABASE_NAME:-apaas_builder_dev}"
DEV_MCP_API_KEYS="${DEV_MCP_API_KEYS:-dev-mcp-api-key-local}"

SOURCE_NGINX_CM="${SOURCE_NGINX_CM:-${PROD_APP_NAME}-nginx}"
NGINX_CM="${NGINX_CM:-${APP_NAME}-nginx}"
SOURCE_BACKEND_SECRET="${SOURCE_BACKEND_SECRET:-apaas-backend-env}"
BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env-dev}"
WORKSPACES_PVC="${WORKSPACES_PVC:-apaas-workspaces-dev}"
STORAGE_CLASS="${STORAGE_CLASS:-local-path}"
WORKSPACES_SIZE="${WORKSPACES_SIZE:-50Gi}"
IMAGE_PULL_SECRET="${IMAGE_PULL_SECRET:-regcred-hub-dfy}"
NODE_AFFINITY_KEY="${NODE_AFFINITY_KEY:-apaas.definesys.com/app-tier}"

ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"
OUTPUT_FILE="${OUTPUT_FILE:-$REPO_ROOT/.run/deploy-dev-kubesphere-terminal.sh}"

c_red=$'\033[31m'
c_grn=$'\033[32m'
c_yel=$'\033[33m'
c_blu=$'\033[36m'
c_rst=$'\033[0m'

log() { printf "%s[prepare-web-deploy]%s %s\n" "$c_blu" "$c_rst" "$*"; }
ok() { printf "%s[ ok ]%s %s\n" "$c_grn" "$c_rst" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$c_yel" "$c_rst" "$*" >&2; }
die() { printf "%s[fail]%s %s\n" "$c_red" "$c_rst" "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

assert_clean_build_inputs() {
  (
    cd "$REPO_ROOT"
    build_inputs=(frontend backend admin-spa deploy/docker)
    git diff --quiet --cached -- "${build_inputs[@]}"
    git diff --quiet -- "${build_inputs[@]}"
    [ -z "$(git ls-files --others --exclude-standard -- "${build_inputs[@]}")" ]
  ) || die "Docker build inputs are dirty; commit them before building"
}

ensure_clean_git() {
  if [ "$ALLOW_DIRTY" = "1" ]; then
    warn "ALLOW_DIRTY=1, preparing deployment with local uncommitted changes"
    return
  fi
  if [ -n "$(git status --porcelain)" ]; then
    git status --short
    die "worktree is dirty. Commit first, or run with ALLOW_DIRTY=1"
  fi
}

push_dev_branch() {
  if [ "$PUSH_DEV" != "1" ]; then
    warn "PUSH_DEV=0, skip pushing HEAD to origin/${DEV_BRANCH}"
    return
  fi
  log "push current HEAD to origin/${DEV_BRANCH}"
  git push --force-with-lease origin HEAD:"$DEV_BRANCH"
}

build_and_push_image() {
  if [ "$SKIP_IMAGE_BUILD" = "1" ]; then
    [ -n "$IMAGE" ] || die "SKIP_IMAGE_BUILD=1 requires IMAGE=<repo:tag>"
    warn "SKIP_IMAGE_BUILD=1, reuse image: ${IMAGE}"
    return
  fi

  assert_clean_build_inputs
  local BUILD_SHA sha
  BUILD_SHA="$(git rev-parse HEAD)"
  [[ "$BUILD_SHA" =~ ^[0-9a-f]{40}$ ]] || die "HEAD is not a full lowercase Git SHA"
  sha="${BUILD_SHA:0:7}"
  if [ -z "$IMAGE_TAG" ]; then
    IMAGE_TAG="dev-$(date +%Y%m%d)-${sha}"
  fi
  IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"

  log "build and push image: ${IMAGE}"
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build \
      --platform "$PLATFORM" \
      --build-arg "VITE_BASE_URL=${VITE_BASE_URL}" \
      --build-arg "VITE_BUILD_SHA=${BUILD_SHA}" \
      --build-arg "VITE_ADMIN_BASE=${VITE_ADMIN_BASE}" \
      --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL}" \
      --build-arg "VITE_MCP_PUBLIC_BASE=${VITE_MCP_PUBLIC_BASE}" \
      -f "$REPO_ROOT/deploy/docker/Dockerfile" \
      -t "$IMAGE" \
      --push \
      "$REPO_ROOT"
  else
    docker build \
      --build-arg "VITE_BASE_URL=${VITE_BASE_URL}" \
      --build-arg "VITE_BUILD_SHA=${BUILD_SHA}" \
      --build-arg "VITE_ADMIN_BASE=${VITE_ADMIN_BASE}" \
      --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL}" \
      --build-arg "VITE_MCP_PUBLIC_BASE=${VITE_MCP_PUBLIC_BASE}" \
      -f "$REPO_ROOT/deploy/docker/Dockerfile" \
      -t "$IMAGE" \
      "$REPO_ROOT"
    docker push "$IMAGE"
  fi
  ok "image pushed: ${IMAGE}"
}

generate_terminal_payload() {
  [ -n "$APAAS_BASE_URL" ] || die "APAAS_BASE_URL is empty. Set it in ${DEPLOY_ENV_FILE}"
  [ -n "$DEV_DATABASE_NAME" ] || die "DEV_DATABASE_NAME is empty. Set it in ${DEPLOY_ENV_FILE}"
  mkdir -p "$(dirname "$OUTPUT_FILE")"
  local nginx_conf
  nginx_conf="$(sed '1,/default.conf: |/d; s/^    //' "$REPO_ROOT/deploy/k8s/15-configmap-nginx.yaml")"
  cat > "$OUTPUT_FILE" <<EOF
set -euo pipefail

NAMESPACE='${NAMESPACE}'
APP_NAME='${APP_NAME}'
PROD_APP_NAME='${PROD_APP_NAME}'
IMAGE='${IMAGE}'
DEV_HOST='${DEV_HOST}'
PROD_HOST='${PROD_HOST}'
PUBLIC_URL='${PUBLIC_URL}'
APAAS_BASE_URL='${APAAS_BASE_URL}'
DEV_DATABASE_NAME='${DEV_DATABASE_NAME}'
DEV_MCP_API_KEYS='${DEV_MCP_API_KEYS:-dev-mcp-api-key-local}'
SOURCE_NGINX_CM='${SOURCE_NGINX_CM}'
NGINX_CM='${NGINX_CM}'
SOURCE_BACKEND_SECRET='${SOURCE_BACKEND_SECRET}'
BACKEND_SECRET='${BACKEND_SECRET}'
WORKSPACES_PVC='${WORKSPACES_PVC}'
STORAGE_CLASS='${STORAGE_CLASS}'
WORKSPACES_SIZE='${WORKSPACES_SIZE}'
IMAGE_PULL_SECRET='${IMAGE_PULL_SECRET}'
NODE_AFFINITY_KEY='${NODE_AFFINITY_KEY}'
ROLL_TIMEOUT='${ROLL_TIMEOUT}'

echo "[1/7] checking namespace"
kubectl get namespace "\$NAMESPACE" >/dev/null

echo "[2/7] applying nginx ConfigMap from repo"
cat > /tmp/apaas-builder-nginx-default.conf <<'NGINX_CONF'
${nginx_conf}
NGINX_CONF
kubectl -n "\$NAMESPACE" create configmap "\$NGINX_CM" \\
  --from-file=default.conf=/tmp/apaas-builder-nginx-default.conf \\
  --dry-run=client -o yaml | kubectl apply -f -

echo "[3/7] syncing backend Secret"
echo "      using isolated dev database: \$DEV_DATABASE_NAME"
kubectl -n "\$NAMESPACE" get secret "\$SOURCE_BACKEND_SECRET" -o jsonpath='{.data.backend\\.env}' \\
  | base64 -d \\
  | sed "s#\${PROD_HOST}#\${DEV_HOST}#g" \\
  > /tmp/apaas-builder-backend.env
if grep -q '^APAAS_BASE_URL=' /tmp/apaas-builder-backend.env; then
  sed -i "s#^APAAS_BASE_URL=.*#APAAS_BASE_URL=\${APAAS_BASE_URL}#" /tmp/apaas-builder-backend.env
else
  printf 'APAAS_BASE_URL=%s\\n' "\$APAAS_BASE_URL" >> /tmp/apaas-builder-backend.env
fi
sed -i '/^APAAS_TENANT_ID=/d' /tmp/apaas-builder-backend.env
if grep -Eq '^DATABASE_URL=(postgresql|postgres|mysql)' /tmp/apaas-builder-backend.env; then
  sed -i -E "s#^(DATABASE_URL=[^:]+://[^/]+/)[^?]*(.*)#\\1\${DEV_DATABASE_NAME}\\2#" /tmp/apaas-builder-backend.env
else
  echo "ERROR: DATABASE_URL is missing or unsupported; refusing to deploy dev against an unknown database" >&2
  exit 1
fi
if grep -q '^MCP_API_KEYS=' /tmp/apaas-builder-backend.env; then
  sed -i "s#^MCP_API_KEYS=.*#MCP_API_KEYS=\${DEV_MCP_API_KEYS}#" /tmp/apaas-builder-backend.env
else
  printf 'MCP_API_KEYS=%s\\n' "\$DEV_MCP_API_KEYS" >> /tmp/apaas-builder-backend.env
fi
kubectl -n "\$NAMESPACE" create secret generic "\$BACKEND_SECRET" \\
  --from-file=backend.env=/tmp/apaas-builder-backend.env \\
  --dry-run=client -o yaml \\
  | kubectl apply -f -

echo "[4/7] deleting old StatefulSet/Pods so stale probes cannot survive"
kubectl -n "\$NAMESPACE" delete statefulset "\$APP_NAME" --ignore-not-found=true --wait=true
kubectl -n "\$NAMESPACE" delete pod -l app="\$APP_NAME" --ignore-not-found=true --wait=true || true

echo "[5/7] applying workloads"
kubectl apply -f - <<YAML
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: \${WORKSPACES_PVC}
  namespace: \${NAMESPACE}
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: \${STORAGE_CLASS}
  resources:
    requests:
      storage: \${WORKSPACES_SIZE}
---
apiVersion: v1
kind: Service
metadata:
  name: \${APP_NAME}
  namespace: \${NAMESPACE}
  labels:
    app: \${APP_NAME}
spec:
  type: ClusterIP
  selector:
    app: \${APP_NAME}
  ports:
    - name: http
      port: 80
      targetPort: http
---
apiVersion: v1
kind: Service
metadata:
  name: \${APP_NAME}-headless
  namespace: \${NAMESPACE}
spec:
  clusterIP: None
  selector:
    app: \${APP_NAME}
  ports:
    - name: http
      port: 80
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: \${APP_NAME}
  namespace: \${NAMESPACE}
  labels:
    app: \${APP_NAME}
spec:
  serviceName: \${APP_NAME}-headless
  replicas: 1
  selector:
    matchLabels:
      app: \${APP_NAME}
  template:
    metadata:
      labels:
        app: \${APP_NAME}
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: \${NODE_AFFINITY_KEY}
                    operator: Exists
      initContainers:
        - name: copy-frontend-dist
          image: \${IMAGE}
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
          image: \${IMAGE}
          imagePullPolicy: Always
          env:
            - name: WAIT_FOR_DATABASE
              value: "1"
            - name: APAAS_WORKSPACE_ROOT
              value: "/root/apaas-builder/workspaces"
            - name: APAAS_NPM_CACHE_DIR
              value: "/root/apaas-builder/workspaces/.npm-cache"
          ports:
            - name: api
              containerPort: 8003
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
            claimName: \${WORKSPACES_PVC}
        - name: backend-env
          secret:
            secretName: \${BACKEND_SECRET}
        - name: frontend-dist
          emptyDir: {}
        - name: nginx-conf
          configMap:
            name: \${NGINX_CM}
      imagePullSecrets:
        - name: \${IMAGE_PULL_SECRET}
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: \${APP_NAME}
  namespace: \${NAMESPACE}
  annotations:
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
spec:
  ingressClassName: nginx
  rules:
    - host: \${DEV_HOST}
      http:
        paths:
          - path: /ai-builder
            pathType: Prefix
            backend:
              service:
                name: \${APP_NAME}
                port:
                  name: http
          - path: /
            pathType: Prefix
            backend:
              service:
                name: \${APP_NAME}
                port:
                  name: http
YAML

echo "[6/7] checking host conflicts"
kubectl get ingress -A \\
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,HOSTS:.spec.rules[*].host' \\
  --no-headers \\
  | awk -v host="\$DEV_HOST" -v ns="\$NAMESPACE" -v app="\$APP_NAME" '\$0 ~ host && !(\$1 == ns && \$2 == app) {print "WARNING host conflict:", \$0}'

echo "probe config now in StatefulSet:"
kubectl -n "\$NAMESPACE" get statefulset "\$APP_NAME" -o yaml | sed -n '/readinessProbe:/,/resources:/p'

echo "[7/7] waiting for rollout"
kubectl -n "\$NAMESPACE" rollout status "statefulset/\$APP_NAME" --timeout="\$ROLL_TIMEOUT"
kubectl -n "\$NAMESPACE" get pods,sts,svc,ingress,pvc | grep -E "NAME|\${PROD_APP_NAME}|\${APP_NAME}|mcp|ming" || true
echo "statefulset images:"
kubectl -n "\$NAMESPACE" get statefulset "\$APP_NAME" -o jsonpath='{range .spec.template.spec.initContainers[*]}init/{.name}={.image}{"\n"}{end}{range .spec.template.spec.containers[*]}container/{.name}={.image}{"\n"}{end}'
POD="\$(kubectl -n "\$NAMESPACE" get pod -l app="\$APP_NAME" -o jsonpath='{.items[0].metadata.name}')"
echo "running pod: \$POD"
kubectl -n "\$NAMESPACE" exec "\$POD" -c apaas-builder -- python - <<'PY' || true
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
  curl -k -sS -o /tmp/apaas-builder-dev-login.html \\
    -w "HTTP %{http_code}\\nURL %{url_effective}\\nTYPE %{content_type}\\nSIZE %{size_download}\\n" \\
    "\$PUBLIC_URL" || true
  MCP_API_KEY="\$(awk -F= '/^MCP_API_KEYS=/{print \$2; exit}' /tmp/apaas-builder-backend.env | cut -d, -f1)"
  if [ -n "\$MCP_API_KEY" ]; then
    curl -k -sS -o /tmp/apaas-builder-dev-mcp-tools.json \\
      -w "MCP_TOOLS_HTTP %{http_code}\\n" \\
      -X POST "https://\${DEV_HOST}/api/mcp/mcp" \\
      -H "X-API-Key: \$MCP_API_KEY" \\
      -H "Content-Type: application/json" \\
      -H "Accept: application/json, text/event-stream" \\
      --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' || true
    head -c 200 /tmp/apaas-builder-dev-mcp-tools.json || true
    echo
  else
    echo "MCP_TOOLS_HTTP skipped: MCP_API_KEYS missing in backend env"
  fi
fi

echo "done: \$PUBLIC_URL"
EOF

  chmod +x "$OUTPUT_FILE"
  ok "generated KubeSphere terminal payload: ${OUTPUT_FILE}"

  if command -v pbcopy >/dev/null 2>&1; then
    pbcopy < "$OUTPUT_FILE"
    ok "payload copied to macOS clipboard"
  else
    warn "pbcopy not found; open and copy ${OUTPUT_FILE} manually"
  fi
}

main() {
  cd "$REPO_ROOT"
  need git
  need docker

  ensure_clean_git
  push_dev_branch
  build_and_push_image
  generate_terminal_payload

  cat <<EOF

Next step:
  Paste the generated payload into KubeSphere's kubectl terminal and press Enter.

Payload:
  ${OUTPUT_FILE}

Image:
  ${IMAGE}

Target:
  ${PUBLIC_URL}
EOF
}

main "$@"
