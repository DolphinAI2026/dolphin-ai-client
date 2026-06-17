#!/usr/bin/env bash
# 一键发版桌面更新: build(arm+x64,签名+updater产物) → 拼 latest.json → 上传 account-service。
#
# 用法:
#   VERSION=0.2.0 NOTES="修复xx" ADMIN_USER=xxx ADMIN_PASS=xxx \
#     bash scripts/release-desktop.sh
#
# 私钥无密码(keys/ruijing-updater.key)。若日后改成带密码, 额外设
#   TAURI_SIGNING_PRIVATE_KEY_PASSWORD=...
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${VERSION:?需要 VERSION (如 VERSION=0.2.0)}"
NOTES="${NOTES:-}"
BASE="https://agent.dfy.definesys.cn/account-api"
# 凭据兜底: 若环境没传 ADMIN_USER/ADMIN_PASS, 自动从 keys/release.env 读。
# 用 set -a 让 source 进来的变量自动导出 —— 否则 release.env 里 `ADMIN_USER=...`
# (无 export) 经 `source` 只是非导出 shell 变量, 子进程/后续命令继承不到,
# 走到登录步的 `${ADMIN_USER:?}` 会中断 (2026-06-18 踩过: 白构建一整轮)。
if [ -z "${ADMIN_USER:-}" ] || [ -z "${ADMIN_PASS:-}" ]; then
  if [ -f "$ROOT/keys/release.env" ]; then
    set -a; . "$ROOT/keys/release.env"; set +a
  fi
fi
KEY="$ROOT/keys/ruijing-updater.key"
[ -f "$KEY" ] || { echo "缺签名私钥 $KEY"; exit 1; }
export TAURI_SIGNING_PRIVATE_KEY="$(cat "$KEY")"
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}"

echo "==> 同步 tauri.conf.json version=$VERSION"
sed -i '' "s/\"version\": \"[^\"]*\"/\"version\": \"$VERSION\"/" "$ROOT/src-tauri/tauri.conf.json"

echo "==> build arm (含签名 updater 产物)"
bash "$ROOT/scripts/build-desktop.sh"
echo "==> build x64 (含签名 updater 产物)"
bash "$ROOT/scripts/build-desktop-x86.sh"

ARM_DIR="$ROOT/src-tauri/target/release/bundle/macos"
X64_DIR="$ROOT/src-tauri/target/x86_64-apple-darwin/release/bundle/macos"
ARM_TGZ="$(ls "$ARM_DIR"/*.app.tar.gz | head -1)"
X64_TGZ="$(ls "$X64_DIR"/*.app.tar.gz | head -1)"
[ -f "$ARM_TGZ" ] && [ -f "$X64_TGZ" ] || { echo "缺 updater 产物 (.app.tar.gz)"; exit 1; }
[ -f "${ARM_TGZ}.sig" ] && [ -f "${X64_TGZ}.sig" ] || { echo "缺签名 .sig (TAURI_SIGNING_PRIVATE_KEY 没生效?)"; exit 1; }

ARM_NAME="ruijing-${VERSION}-aarch64.app.tar.gz"
X64_NAME="ruijing-${VERSION}-x86_64.app.tar.gz"
cp "$ARM_TGZ" "/tmp/$ARM_NAME"
cp "$X64_TGZ" "/tmp/$X64_NAME"
ARM_SIG="$(cat "${ARM_TGZ}.sig")"
X64_SIG="$(cat "${X64_TGZ}.sig")"
PUB_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 用 python3 安全生成 JSON(signature/notes 里有换行与特殊字符, 必须转义)
ARM_SIG="$ARM_SIG" X64_SIG="$X64_SIG" NOTES="$NOTES" VERSION="$VERSION" \
PUB_DATE="$PUB_DATE" ARM_URL="$BASE/desktop-updates/$ARM_NAME" \
X64_URL="$BASE/desktop-updates/$X64_NAME" python3 - > /tmp/latest.json <<'PY'
import json, os
m = {
    "version": os.environ["VERSION"],
    "notes": os.environ.get("NOTES", ""),
    "pub_date": os.environ["PUB_DATE"],
    "platforms": {
        "darwin-aarch64": {"signature": os.environ["ARM_SIG"], "url": os.environ["ARM_URL"]},
        "darwin-x86_64":  {"signature": os.environ["X64_SIG"], "url": os.environ["X64_URL"]},
    },
}
print(json.dumps(m, ensure_ascii=False, indent=2))
PY

echo "==> 平台管理员登录"
TOKEN="$(curl -s -X POST "$BASE/api/desktop-auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"${ADMIN_USER:?需要 ADMIN_USER}\",\"password\":\"${ADMIN_PASS:?需要 ADMIN_PASS}\"}" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')"
[ -n "$TOKEN" ] || { echo "登录失败, 拿不到 token"; exit 1; }

echo "==> 上传 manifest + 包"
curl -s -X POST "$BASE/desktop-updates/admin/publish" \
  -H "Authorization: Bearer $TOKEN" \
  -F "manifest=</tmp/latest.json" \
  -F "packages=@/tmp/$ARM_NAME" \
  -F "packages=@/tmp/$X64_NAME"
echo

echo "==> 校验线上 manifest"
curl -s "$BASE/desktop-updates/latest.json" | python3 -m json.tool | head -6
echo "==> 完成 v$VERSION"
