#!/usr/bin/env bash
# Deploy ai-builder to the shared orcamatrix-demo namespace.
#
# Required:
#   IMAGE=om-harbor.dfy.definesys.cn/om-demo/ai-builder:<tag>
#   BACKEND_ENV_FILE=/path/to/backend/.env
#
# Optional:
#   KUBECTL_BIN=kubectl
#   KUBE_NAMESPACE=orcamatrix-demo
#   KUBE_CONTEXT=<context>
#   CONTROL_PLANE_URL=https://om-demo.dfy.definesys.cn/control-plane
#   CONTROL_PLANE_DEPLOYMENT=control-plane-fw-auth-preview
#   DOLPHIN_WORKSPACE_BASE_URL=https://om-demo.dfy.definesys.cn
#   CONTROL_PLANE_CAPTCHA_ENABLED=true
#   CONTROL_PLANE_BINDING_ENABLED=false
#   MODEL_PROVIDER_SECRET=sandbox-runtime-model-provider-real
#
# CONTROL_PLANE_BINDING_ENABLED is optional. Keep it false unless platform
# administrators require explicit Dolphin account and aPaaS environment binding.
# MODEL_PROVIDER_SECRET is optional. Set it to an empty value to skip reusing
# the shared Agent Runtime model provider as Builder's default model.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
KUBE_NAMESPACE="${KUBE_NAMESPACE:-orcamatrix-demo}"
KUBE_CONTEXT="${KUBE_CONTEXT:-}"
IMAGE="${IMAGE:-}"
BACKEND_ENV_FILE="${BACKEND_ENV_FILE:-}"
CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-https://om-demo.dfy.definesys.cn/control-plane}"
CONTROL_PLANE_DEPLOYMENT="${CONTROL_PLANE_DEPLOYMENT:-control-plane-fw-auth-preview}"
DOLPHIN_WORKSPACE_BASE_URL="${DOLPHIN_WORKSPACE_BASE_URL:-https://om-demo.dfy.definesys.cn}"
CONTROL_PLANE_CAPTCHA_ENABLED="${CONTROL_PLANE_CAPTCHA_ENABLED:-true}"
CONTROL_PLANE_BINDING_ENABLED="${CONTROL_PLANE_BINDING_ENABLED:-false}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://om-demo.dfy.definesys.cn/ai-builder}"
DATABASE_SECRET="${DATABASE_SECRET:-control-plane-db-secret}"
IMAGE_PULL_SECRET="${IMAGE_PULL_SECRET:-om-demo-harbor-pull-secret}"
DELEGATION_SECRET="${DELEGATION_SECRET:-ai-builder-control-plane-delegation}"
MODEL_PROVIDER_SECRET="${MODEL_PROVIDER_SECRET-sandbox-runtime-model-provider-real}"
MODEL_PROVIDER_SECRET_KEY="${MODEL_PROVIDER_SECRET_KEY:-model-provider.json}"
NGINX_IMAGE="${NGINX_IMAGE:-hub-mirror.dfy.definesys.cn/library/nginx:1.27-alpine}"
STORAGE_CLASS="${STORAGE_CLASS:-local-path}"
STORAGE_SIZE="${STORAGE_SIZE:-50Gi}"

if [[ -z "$IMAGE" ]]; then
  echo "IMAGE is required" >&2
  exit 2
fi
if [[ -z "$BACKEND_ENV_FILE" || ! -f "$BACKEND_ENV_FILE" ]]; then
  echo "BACKEND_ENV_FILE must point to an existing file" >&2
  exit 2
fi

kubectl_args=()
if [[ -n "$KUBE_CONTEXT" ]]; then
  kubectl_args+=(--context "$KUBE_CONTEXT")
fi
kube() {
  "$KUBECTL_BIN" "${kubectl_args[@]}" "$@"
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
chmod 700 "$tmp_dir"

decode_secret_key() {
  local key="$1"
  kube -n "$KUBE_NAMESPACE" get secret "$DATABASE_SECRET" \
    -o "jsonpath={.data.${key}}" | base64 --decode
}

jdbc_url="$(decode_secret_key jdbc-url)"
database_username="$(decode_secret_key username)"
database_password="$(decode_secret_key password)"

database_url="$(
  JDBC_URL="$jdbc_url" DB_USERNAME="$database_username" DB_PASSWORD="$database_password" \
    python3 - <<'PY'
import os
import re
from urllib.parse import quote

jdbc_url = os.environ["JDBC_URL"]
match = re.fullmatch(
    r"jdbc:postgresql://(?P<host>[^/:?#]+)(?::(?P<port>\d+))?/(?P<database>[^?]+)(?:\?.*)?",
    jdbc_url,
)
if not match:
    raise SystemExit("unsupported PostgreSQL JDBC URL in database secret")

host = match.group("host")
port = match.group("port") or "5432"
database = quote(match.group("database"), safe="")
username = quote(os.environ["DB_USERNAME"], safe="")
password = quote(os.environ["DB_PASSWORD"], safe="")
print(f"postgresql+asyncpg://{username}:{password}@{host}:{port}/{database}")
PY
)"

if [[ -n "$MODEL_PROVIDER_SECRET" ]] \
  && kube -n "$KUBE_NAMESPACE" get secret "$MODEL_PROVIDER_SECRET" >/dev/null 2>&1; then
  kube -n "$KUBE_NAMESPACE" get secret "$MODEL_PROVIDER_SECRET" -o json \
    | MODEL_PROVIDER_SECRET_KEY="$MODEL_PROVIDER_SECRET_KEY" \
      MODEL_PROVIDER_ENV_FILE="$tmp_dir/model-provider.env" \
      python3 -c '
import base64
import json
import os
import sys
from pathlib import Path

secret = json.load(sys.stdin)
encoded = (secret.get("data") or {}).get(os.environ["MODEL_PROVIDER_SECRET_KEY"], "")
if not encoded:
    raise SystemExit("shared model provider secret key is missing")
payload = json.loads(base64.b64decode(encoded))
provider_id = str(payload.get("defaultProviderId") or "").strip()
providers = payload.get("providers") or []
provider = next(
    (item for item in providers if str(item.get("providerId") or "").strip() == provider_id),
    providers[0] if providers else {},
)
base_url = str(provider.get("apiBaseUrl") or "").strip()
api_key = str(provider.get("token") or "").strip()
model = str(provider.get("defaultModel") or "").strip()
if not base_url or not api_key or not model:
    raise SystemExit("shared model provider is incomplete")
if any("\n" in value or "\r" in value for value in (base_url, api_key, model)):
    raise SystemExit("shared model provider contains unsupported line breaks")
Path(os.environ["MODEL_PROVIDER_ENV_FILE"]).write_text(
    f"DOLPHIN_BASE_URL={base_url}\n"
    f"DOLPHIN_API_KEY={api_key}\n"
    f"DOLPHIN_MODEL={model}\n",
    encoding="utf-8",
)
'
fi

awk '
  !/^(DATABASE_URL|AUTH_PROVIDER|CONTROL_PLANE_BINDING_ENABLED|CONTROL_PLANE_CAPTCHA_ENABLED|DOLPHIN_WORKSPACE_BASE_URL|DOLPHIN_CODE_CONTROL_PLANE_URL|DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET|DOLPHIN_CODE_BUILDER_URL|AI_BUILDER_CHAT_DEEPLINK_BASE|HOST|PORT)=/
' "$BACKEND_ENV_FILE" > "$tmp_dir/backend.env"
cat >> "$tmp_dir/backend.env" <<EOF

# orcamatrix-demo deployment overrides
DATABASE_URL=${database_url}
AUTH_PROVIDER=control_plane
# Optional: set true only when administrators require explicit account/environment binding.
CONTROL_PLANE_BINDING_ENABLED=${CONTROL_PLANE_BINDING_ENABLED}
# Optional: set true only when the configured Control Plane login requires captcha.
CONTROL_PLANE_CAPTCHA_ENABLED=${CONTROL_PLANE_CAPTCHA_ENABLED}
DOLPHIN_WORKSPACE_BASE_URL=${DOLPHIN_WORKSPACE_BASE_URL}
DOLPHIN_CODE_CONTROL_PLANE_URL=${CONTROL_PLANE_URL}
AI_BUILDER_CHAT_DEEPLINK_BASE=${PUBLIC_BASE_URL}
HOST=0.0.0.0
PORT=8003
EOF
if [[ -s "$tmp_dir/model-provider.env" ]]; then
  cat >> "$tmp_dir/backend.env" <<EOF

# Optional shared Agent Runtime model provider used as Builder's default model.
EOF
  cat "$tmp_dir/model-provider.env" >> "$tmp_dir/backend.env"
fi
chmod 600 "$tmp_dir/backend.env"
backend_env_checksum="$(sha256sum "$tmp_dir/backend.env" | awk '{print $1}')"

if ! kube -n "$KUBE_NAMESPACE" get secret "$DELEGATION_SECRET" >/dev/null 2>&1; then
  delegation_value="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  kube -n "$KUBE_NAMESPACE" create secret generic "$DELEGATION_SECRET" \
    --from-literal=CONTROL_PLANE_WORKSPACE_DELEGATION_SECRET="$delegation_value" >/dev/null
fi

kube -n "$KUBE_NAMESPACE" set env "deployment/${CONTROL_PLANE_DEPLOYMENT}" \
  CONTROL_PLANE_AUTH_FULL_WORKSPACE_BASE_URL="$DOLPHIN_WORKSPACE_BASE_URL" >/dev/null
kube -n "$KUBE_NAMESPACE" set env "deployment/${CONTROL_PLANE_DEPLOYMENT}" \
  --from="secret/${DELEGATION_SECRET}" >/dev/null
control_plane_ready=false
for _ in $(seq 1 150); do
  read -r generation observed desired updated available < <(
    kube -n "$KUBE_NAMESPACE" get "deployment/${CONTROL_PLANE_DEPLOYMENT}" \
      -o jsonpath='{.metadata.generation}{" "}{.status.observedGeneration}{" "}{.spec.replicas}{" "}{.status.updatedReplicas}{" "}{.status.availableReplicas}{"\n"}'
  )
  if [[ "$generation" == "$observed" && "$desired" == "$updated" && "$desired" == "$available" ]]; then
    control_plane_ready=true
    break
  fi
  sleep 2
done
if [[ "$control_plane_ready" != "true" ]]; then
  echo "Control Plane deployment did not become ready within 300 seconds" >&2
  exit 1
fi

awk '
  /^  default.conf: \|$/ { capture=1; next }
  capture { sub(/^    /, ""); print }
' "$ROOT_DIR/deploy/k8s/15-configmap-nginx.yaml" > "$tmp_dir/default.conf"

kube -n "$KUBE_NAMESPACE" create secret generic ai-builder-backend-env \
  --from-file=backend.env="$tmp_dir/backend.env" \
  --from-literal=DATABASE_URL="$database_url" \
  --dry-run=client -o yaml | kube apply -f -

kube -n "$KUBE_NAMESPACE" create configmap ai-builder-nginx \
  --from-file=default.conf="$tmp_dir/default.conf" \
  --dry-run=client -o yaml | kube apply -f -

cat <<EOF | kube apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ai-builder-workspaces
  namespace: ${KUBE_NAMESPACE}
  labels:
    app.kubernetes.io/name: ai-builder
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ${STORAGE_CLASS}
  resources:
    requests:
      storage: ${STORAGE_SIZE}
---
apiVersion: v1
kind: Service
metadata:
  name: ai-builder
  namespace: ${KUBE_NAMESPACE}
  labels:
    app.kubernetes.io/name: ai-builder
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: ai-builder
  ports:
    - name: http
      port: 80
      targetPort: http
---
apiVersion: v1
kind: Service
metadata:
  name: ai-builder-headless
  namespace: ${KUBE_NAMESPACE}
  labels:
    app.kubernetes.io/name: ai-builder
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: ai-builder
  ports:
    - name: http
      port: 80
      targetPort: http
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: ai-builder
  namespace: ${KUBE_NAMESPACE}
  labels:
    app.kubernetes.io/name: ai-builder
    app.kubernetes.io/part-of: orcamatrix
spec:
  serviceName: ai-builder-headless
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ai-builder
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ai-builder
        app.kubernetes.io/part-of: orcamatrix
      annotations:
        checksum/backend-env: ${backend_env_checksum}
    spec:
      imagePullSecrets:
        - name: ${IMAGE_PULL_SECRET}
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
          volumeMounts:
            - name: frontend-dist
              mountPath: /share/dist
      containers:
        - name: ai-builder
          image: ${IMAGE}
          imagePullPolicy: Always
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: ai-builder-backend-env
                  key: DATABASE_URL
            - name: WAIT_FOR_DATABASE
              value: "1"
            - name: DOLPHIN_CODE_CONTROL_PLANE_DELEGATION_SECRET
              valueFrom:
                secretKeyRef:
                  name: ${DELEGATION_SECRET}
                  key: CONTROL_PLANE_WORKSPACE_DELEGATION_SECRET
            - name: APAAS_WORKSPACE_ROOT
              value: /root/apaas-builder/workspaces
            - name: APAAS_NPM_CACHE_DIR
              value: /root/apaas-builder/workspaces/.npm-cache
            - name: APAAS_PRIVATE_NPM_REGISTRY
              value: https://registry.dfy.definesys.cn/repository/apaas-npm-group/
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
            initialDelaySeconds: 20
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 12
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
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: "2"
              memory: 4Gi
        - name: web
          image: ${NGINX_IMAGE}
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
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 500m
              memory: 256Mi
      volumes:
        - name: workspaces
          persistentVolumeClaim:
            claimName: ai-builder-workspaces
        - name: backend-env
          secret:
            secretName: ai-builder-backend-env
        - name: frontend-dist
          emptyDir: {}
        - name: nginx-conf
          configMap:
            name: ai-builder-nginx
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ai-builder
  namespace: ${KUBE_NAMESPACE}
  labels:
    app.kubernetes.io/name: ai-builder
    app.kubernetes.io/part-of: orcamatrix
  annotations:
    nginx.ingress.kubernetes.io/proxy-buffering: "off"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
spec:
  ingressClassName: nginx
  rules:
    - host: om-demo.dfy.definesys.cn
      http:
        paths:
          - path: /ai-builder
            pathType: Prefix
            backend:
              service:
                name: ai-builder
                port:
                  name: http
EOF

kube -n "$KUBE_NAMESPACE" rollout status statefulset/ai-builder --timeout=600s
echo "ai-builder deployed: ${PUBLIC_BASE_URL}/"
