#!/usr/bin/env bash
# Build and deploy apaas-builder from the latest online Git repository code.
#
# Designed for KubeSphere / Kubernetes node terminals:
#   bash deploy_online_latest_kubesphere.sh
#
# Optional overrides:
#   GIT_BRANCH=main DEPLOY_TARGET=main bash deploy_online_latest_kubesphere.sh
#   IMAGE_TAG=dev-manual-001 bash deploy_online_latest_kubesphere.sh
#   DOCKER_USERNAME=xxx DOCKER_PASSWORD=xxx bash deploy_online_latest_kubesphere.sh

set -euo pipefail

GIT_REPO="${GIT_REPO:-https://github.com/Mars-hub404/apaas-builder-ai.git}"
GIT_BRANCH="${GIT_BRANCH:-}"
DEPLOY_TARGET="${DEPLOY_TARGET:-dev}"

NAMESPACE="${NAMESPACE:-apaas-builder}"
IMAGE_REPO="${IMAGE_REPO:-hub.dfy.definesys.cn/ai-builder/apaas-builder}"
PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE_TAG="${IMAGE_TAG:-}"
IMAGE_PULL_SECRET="${IMAGE_PULL_SECRET:-regcred-hub-dfy}"
ROLL_TIMEOUT="${ROLL_TIMEOUT:-300s}"

VITE_BASE_URL="${VITE_BASE_URL:-/ai-builder/}"
VITE_ADMIN_BASE="${VITE_ADMIN_BASE:-/admin/}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-/ai-builder/api}"
VITE_MCP_PUBLIC_BASE="${VITE_MCP_PUBLIC_BASE:-}"

STORAGE_CLASS="${STORAGE_CLASS:-local-path}"
WORKSPACES_SIZE="${WORKSPACES_SIZE:-50Gi}"
NODE_AFFINITY_KEY="${NODE_AFFINITY_KEY:-apaas.definesys.com/app-tier}"

DEV_HOST="${DEV_HOST:-agent.dfy.definesys.cn}"
PROD_HOST="${PROD_HOST:-df-aigc.dfy.definesys.cn}"
DEV_DATABASE_NAME="${DEV_DATABASE_NAME:-apaas_builder_dev}"
DEV_MCP_API_KEYS="${DEV_MCP_API_KEYS:-dev-mcp-api-key-local}"
APAAS_BASE_URL="${APAAS_BASE_URL:-https://apaas-trial.definesys.cn/backend}"

if [ "$DEPLOY_TARGET" = "main" ] || [ "$DEPLOY_TARGET" = "prod" ]; then
  GIT_BRANCH="${GIT_BRANCH:-main}"
  APP_NAME="${APP_NAME:-apaas-builder}"
  HOST="${HOST:-$PROD_HOST}"
  NGINX_CM="${NGINX_CM:-${APP_NAME}-nginx}"
  BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env}"
  WORKSPACES_PVC="${WORKSPACES_PVC:-apaas-workspaces}"
  PUBLIC_URL="${PUBLIC_URL:-https://${HOST}/ai-builder/login}"
  IMAGE_TAG_PREFIX="${IMAGE_TAG_PREFIX:-main}"
else
  GIT_BRANCH="${GIT_BRANCH:-dev}"
  APP_NAME="${APP_NAME:-apaas-builder-dev}"
  HOST="${HOST:-$DEV_HOST}"
  NGINX_CM="${NGINX_CM:-${APP_NAME}-nginx}"
  BACKEND_SECRET="${BACKEND_SECRET:-apaas-backend-env-dev}"
  SOURCE_BACKEND_SECRET="${SOURCE_BACKEND_SECRET:-apaas-backend-env}"
  WORKSPACES_PVC="${WORKSPACES_PVC:-apaas-workspaces-dev}"
  PUBLIC_URL="${PUBLIC_URL:-https://${HOST}/ai-builder/login}"
  IMAGE_TAG_PREFIX="${IMAGE_TAG_PREFIX:-dev}"
fi

TMP_PARENT="${TMP_PARENT:-/tmp}"
WORKDIR="${WORKDIR:-${TMP_PARENT}/apaas-builder-online-${DEPLOY_TARGET}-${GIT_BRANCH}}"

log() { printf '[online-deploy] %s\n' "$*"; }
ok() { printf '[online-deploy][ok] %s\n' "$*"; }
warn() { printf '[online-deploy][warn] %s\n' "$*" >&2; }
die() { printf '[online-deploy][fail] %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

base64_decode() {
  if base64 --help 2>&1 | grep -q -- '-d'; then
    base64 -d
  else
    base64 -D
  fi
}

setup_kubeconfig() {
  if [ -n "${KUBE_CONTEXT:-}" ]; then
    kubectl config use-context "$KUBE_CONTEXT" >/dev/null
  fi
  kubectl cluster-info >/dev/null
  ok "kubectl connected: $(kubectl config current-context 2>/dev/null || printf default)"
}

clone_latest_code() {
  log "clone latest online code: ${GIT_REPO} branch=${GIT_BRANCH}"
  [ -n "$WORKDIR" ] && [ "$WORKDIR" != "/" ] || die "unsafe WORKDIR: ${WORKDIR}"
  rm -rf "$WORKDIR"
  git clone --depth 1 --branch "$GIT_BRANCH" "$GIT_REPO" "$WORKDIR"
  cd "$WORKDIR"
  GIT_SHA="$(git rev-parse --short HEAD)"
  GIT_FULL_SHA="$(git rev-parse HEAD)"
  ok "checked out ${GIT_BRANCH}@${GIT_FULL_SHA}"
}

docker_login_if_requested() {
  if [ -n "${DOCKER_USERNAME:-}" ] && [ -n "${DOCKER_PASSWORD:-}" ]; then
    local registry
    registry="${IMAGE_REPO%%/*}"
    log "docker login: ${registry}"
    printf '%s' "$DOCKER_PASSWORD" | docker login "$registry" -u "$DOCKER_USERNAME" --password-stdin
  else
    warn "DOCKER_USERNAME/DOCKER_PASSWORD not set; assuming docker is already logged in"
  fi
}

build_and_push_image() {
  if [ -z "$IMAGE_TAG" ]; then
    IMAGE_TAG="${IMAGE_TAG_PREFIX}-$(date +%Y%m%d-%H%M%S)-${GIT_SHA}"
  fi
  IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"

  log "build and push image: ${IMAGE}"
  if docker buildx version >/dev/null 2>&1; then
    docker buildx build \
      --platform "$PLATFORM" \
      --build-arg "VITE_BASE_URL=${VITE_BASE_URL}" \
      --build-arg "VITE_ADMIN_BASE=${VITE_ADMIN_BASE}" \
      --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL}" \
      --build-arg "VITE_MCP_PUBLIC_BASE=${VITE_MCP_PUBLIC_BASE:-https://${HOST}}" \
      -f "$WORKDIR/deploy/docker/Dockerfile" \
      -t "$IMAGE" \
      --push \
      "$WORKDIR"
  else
    docker build \
      --build-arg "VITE_BASE_URL=${VITE_BASE_URL}" \
      --build-arg "VITE_ADMIN_BASE=${VITE_ADMIN_BASE}" \
      --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL}" \
      --build-arg "VITE_MCP_PUBLIC_BASE=${VITE_MCP_PUBLIC_BASE:-https://${HOST}}" \
      -f "$WORKDIR/deploy/docker/Dockerfile" \
      -t "$IMAGE" \
      "$WORKDIR"
    docker push "$IMAGE"
  fi
  ok "image pushed: ${IMAGE}"
}

apply_namespace() {
  kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || kubectl create namespace "$NAMESPACE"
}

apply_nginx_config() {
  log "apply nginx ConfigMap: ${NGINX_CM}"
  awk '
    /default\.conf: \|/ { capture = 1; next }
    capture {
      sub(/^    /, "")
      print
    }
  ' "$WORKDIR/deploy/k8s/15-configmap-nginx.yaml" > /tmp/apaas-builder-nginx-default.conf

  [ -s /tmp/apaas-builder-nginx-default.conf ] || die "failed to extract nginx default.conf"

  kubectl -n "$NAMESPACE" create configmap "$NGINX_CM" \
    --from-file=default.conf=/tmp/apaas-builder-nginx-default.conf \
    --dry-run=client -o yaml | kubectl apply -f -
}

ensure_dev_secret() {
  [ "$DEPLOY_TARGET" != "main" ] && [ "$DEPLOY_TARGET" != "prod" ] || return 0

  if kubectl -n "$NAMESPACE" get secret "$BACKEND_SECRET" >/dev/null 2>&1; then
    log "patch existing dev Secret: ${BACKEND_SECRET}"
    kubectl -n "$NAMESPACE" get secret "$BACKEND_SECRET" -o jsonpath='{.data.backend\.env}' \
      | base64_decode > /tmp/apaas-builder-backend.env
  else
    log "create dev Secret from ${SOURCE_BACKEND_SECRET}: ${BACKEND_SECRET}"
    kubectl -n "$NAMESPACE" get secret "$SOURCE_BACKEND_SECRET" -o jsonpath='{.data.backend\.env}' \
      | base64_decode > /tmp/apaas-builder-backend.env
  fi

  if grep -q '^APAAS_BASE_URL=' /tmp/apaas-builder-backend.env; then
    sed -i.bak "s#^APAAS_BASE_URL=.*#APAAS_BASE_URL=${APAAS_BASE_URL}#" /tmp/apaas-builder-backend.env
  else
    printf 'APAAS_BASE_URL=%s\n' "$APAAS_BASE_URL" >> /tmp/apaas-builder-backend.env
  fi

  if grep -q '^DATABASE_URL=' /tmp/apaas-builder-backend.env; then
    sed -i.bak -E "s#^(DATABASE_URL=[a-zA-Z0-9+.-]+://[^/]+/)[^?[:space:]]+#\\1${DEV_DATABASE_NAME}#" /tmp/apaas-builder-backend.env
  fi

  sed -i.bak "s#${PROD_HOST}#${DEV_HOST}#g" /tmp/apaas-builder-backend.env

  if grep -q '^MCP_API_KEYS=' /tmp/apaas-builder-backend.env; then
    sed -i.bak "s#^MCP_API_KEYS=.*#MCP_API_KEYS=${DEV_MCP_API_KEYS}#" /tmp/apaas-builder-backend.env
  else
    printf 'MCP_API_KEYS=%s\n' "$DEV_MCP_API_KEYS" >> /tmp/apaas-builder-backend.env
  fi

  kubectl -n "$NAMESPACE" create secret generic "$BACKEND_SECRET" \
    --from-file=backend.env=/tmp/apaas-builder-backend.env \
    --dry-run=client -o yaml | kubectl apply -f -
}

apply_workloads() {
  log "apply Kubernetes workloads: ${APP_NAME}"
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
            - name: CODE_SERVER_BIND_HOST
              value: "127.0.0.1"
            - name: WAIT_FOR_MYSQL
              value: "1"
            - name: APAAS_WORKSPACE_ROOT
              value: "/root/apaas-builder/workspaces"
            - name: APAAS_NPM_CACHE_DIR
              value: "/root/apaas-builder/workspaces/.npm-cache"
            - name: APAAS_PRIVATE_NPM_REGISTRY
              value: "https://registry.dfy.definesys.cn/repository/apaas-npm-group/"
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
    - host: ${HOST}
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

rollout_and_verify() {
  log "wait for rollout: statefulset/${APP_NAME}"
  kubectl -n "$NAMESPACE" rollout status "statefulset/${APP_NAME}" --timeout="$ROLL_TIMEOUT"
  kubectl -n "$NAMESPACE" get pods,sts,svc,ingress,pvc | grep -E "NAME|${APP_NAME}|${WORKSPACES_PVC}" || true

  if command -v curl >/dev/null 2>&1; then
    log "verify public URL: ${PUBLIC_URL}"
    curl -k -L -sS -o /tmp/apaas-builder-online-login.html \
      -w "HTTP %{http_code}\nURL %{url_effective}\nTYPE %{content_type}\nSIZE %{size_download}\n" \
      "$PUBLIC_URL" || warn "public URL check failed; inspect ingress and pod logs"
  fi
}

main() {
  need git
  need docker
  need kubectl
  need awk
  need sed
  need base64

  setup_kubeconfig
  clone_latest_code
  docker_login_if_requested
  build_and_push_image
  apply_namespace
  apply_nginx_config
  ensure_dev_secret
  apply_workloads
  rollout_and_verify

  ok "deployed ${APP_NAME}"
  ok "source ${GIT_BRANCH}@${GIT_FULL_SHA}"
  ok "image ${IMAGE}"
  ok "url ${PUBLIC_URL}"
}

main "$@"
