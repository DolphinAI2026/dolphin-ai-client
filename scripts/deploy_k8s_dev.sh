#!/usr/bin/env bash
# Deploy the current checkout to the dev Kubernetes environment.
#
# Requirements:
#   - docker logged in to hub.dfy.definesys.cn
#   - kubectl can reach the cluster directly
#   - KUBECONFIG is set, or ~/.kube/dfy-host.yaml exists, or kubectl has a current context
#
# Typical use:
#   scripts/deploy_k8s_dev.sh
#
# Useful overrides:
#   KUBECONFIG=~/.kube/dfy-host.yaml scripts/deploy_k8s_dev.sh
#   PUSH_DEV=0 scripts/deploy_k8s_dev.sh
#   IMAGE_TAG=dev-manual-001 scripts/deploy_k8s_dev.sh

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
CONTAINER_CLI="${CONTAINER_CLI:-docker}"
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
BUILDER_SSE_PADDING_BYTES="${BUILDER_SSE_PADDING_BYTES:-0}"
SYSTEM_GIT_DEFAULT_PROVIDER="${SYSTEM_GIT_DEFAULT_PROVIDER:-}"
SYSTEM_GIT_DEFAULT_HOST="${SYSTEM_GIT_DEFAULT_HOST:-}"
SYSTEM_GIT_DEFAULT_ACCESS_TOKEN="${SYSTEM_GIT_DEFAULT_ACCESS_TOKEN:-}"
SYSTEM_GIT_DEFAULT_GROUP_OR_ORG="${SYSTEM_GIT_DEFAULT_GROUP_OR_ORG:-}"

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

c_red=$'\033[31m'
c_grn=$'\033[32m'
c_yel=$'\033[33m'
c_blu=$'\033[36m'
c_rst=$'\033[0m'

log() { printf "%s[deploy-dev]%s %s\n" "$c_blu" "$c_rst" "$*"; }
ok() { printf "%s[ ok ]%s %s\n" "$c_grn" "$c_rst" "$*"; }
warn() { printf "%s[warn]%s %s\n" "$c_yel" "$c_rst" "$*" >&2; }
die() { printf "%s[fail]%s %s\n" "$c_red" "$c_rst" "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

setup_kubeconfig() {
  if [ -n "${KUBECONFIG:-}" ]; then
    export KUBECONFIG
  elif [ -f "$HOME/.kube/dfy-host.yaml" ]; then
    export KUBECONFIG="$HOME/.kube/dfy-host.yaml"
  elif kubectl config current-context >/dev/null 2>&1; then
    :
  else
    die "kubectl has no context. Export KUBECONFIG or save the cluster kubeconfig to ~/.kube/dfy-host.yaml"
  fi

  if [ -n "${KUBE_CONTEXT:-}" ]; then
    kubectl config use-context "$KUBE_CONTEXT" >/dev/null
  fi
  kubectl cluster-info >/dev/null
  ok "kubectl connected: $(kubectl config current-context 2>/dev/null || printf default)"
}

ensure_clean_git() {
  if [ "$ALLOW_DIRTY" = "1" ]; then
    warn "ALLOW_DIRTY=1, deploying with local uncommitted changes"
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
  local sha
  sha="$(git -C "$REPO_ROOT" rev-parse --short=7 HEAD)"
  if [ -z "$IMAGE_TAG" ]; then
    IMAGE_TAG="dev-$(date +%Y%m%d)-${sha}"
  fi
  IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"

  log "build and push image: ${IMAGE}"
  REPO_ROOT="$REPO_ROOT" \
  CONTAINER_CLI="$CONTAINER_CLI" \
  IMAGE="$IMAGE" \
  PLATFORM="$PLATFORM" \
  VITE_BASE_URL="$VITE_BASE_URL" \
  VITE_ADMIN_BASE="$VITE_ADMIN_BASE" \
  VITE_API_BASE_URL="$VITE_API_BASE_URL" \
  VITE_MCP_PUBLIC_BASE="$VITE_MCP_PUBLIC_BASE" \
  PUSH=1 \
    "$REPO_ROOT/scripts/build_builder_image.sh"
  ok "image pushed: ${IMAGE}"
}

clone_nginx_config() {
  log "apply nginx ConfigMap from repo -> ${NGINX_CM}"
  sed '1,/default.conf: |/d; s/^    //' "$REPO_ROOT/deploy/k8s/15-configmap-nginx.yaml" \
    > /tmp/apaas-builder-nginx-default.conf
  kubectl -n "$NAMESPACE" create configmap "$NGINX_CM" \
    --from-file=default.conf=/tmp/apaas-builder-nginx-default.conf \
    --dry-run=client -o yaml | kubectl apply -f -
}

clone_backend_secret() {
  [ -n "$APAAS_BASE_URL" ] || die "APAAS_BASE_URL is empty. Set it in ${DEPLOY_ENV_FILE}"
  [ -n "$DEV_DATABASE_NAME" ] || die "DEV_DATABASE_NAME is empty. Set it in ${DEPLOY_ENV_FILE}"
  log "sync backend Secret ${SOURCE_BACKEND_SECRET} -> ${BACKEND_SECRET}"
  kubectl -n "$NAMESPACE" get secret "$SOURCE_BACKEND_SECRET" -o jsonpath='{.data.backend\.env}' \
    | python3 -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))' \
    > /tmp/apaas-builder-backend.env
  python3 - "$APAAS_BASE_URL" "$DEV_DATABASE_NAME" "$BUILDER_SSE_PADDING_BYTES" "$SYSTEM_GIT_DEFAULT_PROVIDER" "$SYSTEM_GIT_DEFAULT_HOST" "$SYSTEM_GIT_DEFAULT_ACCESS_TOKEN" "$SYSTEM_GIT_DEFAULT_GROUP_OR_ORG" /tmp/apaas-builder-backend.env <<'PY'
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit

base_url, dev_db, sse_padding_bytes, git_provider, git_host, git_token, git_group, path = sys.argv[1:9]
env_path = Path(path)
values = {
    "APAAS_BASE_URL": base_url,
    "BUILDER_SSE_PADDING_BYTES": sse_padding_bytes,
}
for key, value in {
    "SYSTEM_GIT_DEFAULT_PROVIDER": git_provider,
    "SYSTEM_GIT_DEFAULT_HOST": git_host,
    "SYSTEM_GIT_DEFAULT_ACCESS_TOKEN": git_token,
    "SYSTEM_GIT_DEFAULT_GROUP_OR_ORG": git_group,
}.items():
    if value:
        values[key] = value
seen = set()
lines = []
for line in env_path.read_text().splitlines():
    key = line.split("=", 1)[0] if "=" in line else ""
    if key == "APAAS_TENANT_ID":
        continue
    if key in values:
        lines.append(f"{key}={values[key]}")
        seen.add(key)
    elif key == "DATABASE_URL":
        value = line.split("=", 1)[1]
        parsed = urlsplit(value)
        if parsed.scheme.startswith(("postgresql", "postgres", "mysql")):
            lines.append(f"DATABASE_URL={urlunsplit((parsed.scheme, parsed.netloc, '/' + dev_db, parsed.query, parsed.fragment))}")
        else:
            raise SystemExit(f"unsupported DATABASE_URL for dev split: {parsed.scheme}")
    else:
        lines.append(line)
for key, value in values.items():
    if key not in seen:
        lines.append(f"{key}={value}")
env_path.write_text("\n".join(lines) + "\n")
PY
  sed -i.bak "s#${PROD_HOST}#${DEV_HOST}#g" /tmp/apaas-builder-backend.env
  if grep -q '^MCP_API_KEYS=' /tmp/apaas-builder-backend.env; then
    sed -i.bak "s#^MCP_API_KEYS=.*#MCP_API_KEYS=${DEV_MCP_API_KEYS}#" /tmp/apaas-builder-backend.env
  else
    printf 'MCP_API_KEYS=%s\n' "${DEV_MCP_API_KEYS}" >> /tmp/apaas-builder-backend.env
  fi
  kubectl -n "$NAMESPACE" create secret generic "$BACKEND_SECRET" \
    --from-file=backend.env=/tmp/apaas-builder-backend.env \
    --dry-run=client -o yaml \
    | kubectl apply -f -
}

apply_workloads() {
  log "apply Kubernetes resources for ${APP_NAME}"
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
          imagePullPolicy: IfNotPresent
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
          imagePullPolicy: IfNotPresent
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
            httpGet:
              path: /api/health
              port: api
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 6
          livenessProbe:
            httpGet:
              path: /api/health
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
}

verify_no_host_conflict() {
  local conflicts
  conflicts="$(
    kubectl get ingress -A \
      -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,HOSTS:.spec.rules[*].host' \
      --no-headers \
      | awk -v host="$DEV_HOST" -v ns="$NAMESPACE" -v app="$APP_NAME" '$0 ~ host && !($1 == ns && $2 == app) {print}'
  )"
  if [ -n "$conflicts" ]; then
    warn "host ${DEV_HOST} is also used by another ingress:"
    printf "%s\n" "$conflicts" >&2
    warn "If this is the old prod ingress, patch it first so prod only uses ${PROD_HOST}."
  fi
}

rollout_and_verify() {
  log "wait for rollout"
  kubectl -n "$NAMESPACE" rollout status "statefulset/${APP_NAME}" --timeout="$ROLL_TIMEOUT"
  kubectl -n "$NAMESPACE" get pods,sts,svc,ingress,pvc | grep -E "NAME|${PROD_APP_NAME}|${APP_NAME}|mcp|ming" || true

  log "verify public URL: ${PUBLIC_URL}"
  curl -k -sS -o /tmp/apaas-builder-dev-login.html \
    -w "HTTP %{http_code}\nURL %{url_effective}\nTYPE %{content_type}\nSIZE %{size_download}\n" \
    "$PUBLIC_URL"
  log "verify admin route"
  curl -k -L -sS -o /tmp/apaas-builder-dev-admin.html \
    -w "ADMIN_HTTP %{http_code}\n" \
    "https://${DEV_HOST}/ai-builder/admin" || true
  log "verify MCP tools/list with X-API-Key"
  curl -k -sS -o /tmp/apaas-builder-dev-mcp-tools.json \
    -w "MCP_TOOLS_HTTP %{http_code}\n" \
    -X POST "https://${DEV_HOST}/api/mcp/mcp" \
    -H "X-API-Key: ${DEV_MCP_API_KEYS%%,*}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
  head -c 200 /tmp/apaas-builder-dev-mcp-tools.json || true
  echo
}

main() {
  cd "$REPO_ROOT"
  need git
  need "$CONTAINER_CLI"
  need kubectl
  need python3
  need curl

  ensure_clean_git
  setup_kubeconfig
  push_dev_branch
  build_and_push_image
  kubectl get namespace "$NAMESPACE" >/dev/null
  clone_nginx_config
  clone_backend_secret
  apply_workloads
  verify_no_host_conflict
  rollout_and_verify
  ok "dev deployed: ${PUBLIC_URL}"
}

main "$@"
