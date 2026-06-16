#!/usr/bin/env bash
# 一键构建桌面包: 前端 → PyInstaller sidecar → rename → tauri build
set -euo pipefail

START_TS=$(date +%s)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIPLE="$(rustc --print host-tuple)"

echo "==> [build-desktop.sh] ROOT=$ROOT  TRIPLE=$TRIPLE"
echo ""

echo "==> 1/4 前端桌面构建 (base=/)"
cd "$ROOT/frontend" && npm run build:desktop

echo ""
echo "==> 2/4 PyInstaller 打 sidecar (onefile, 内嵌前端)"
cd "$ROOT/backend" && .venv/bin/python -m PyInstaller ruijing-sidecar.spec --noconfirm

echo ""
echo "==> 3/4 放置 sidecar 二进制 (triple=$TRIPLE)"
mkdir -p "$ROOT/src-tauri/binaries"
cp "$ROOT/backend/dist/ruijing-sidecar" "$ROOT/src-tauri/binaries/ruijing-sidecar-${TRIPLE}"
chmod +x "$ROOT/src-tauri/binaries/ruijing-sidecar-${TRIPLE}"
ls -lh "$ROOT/src-tauri/binaries/"

echo ""
echo "==> 4/4 Tauri 出包"
cd "$ROOT" && npx tauri build || {
    echo ""
    echo "    WARNING: tauri build failed (possibly DMG needs full Xcode); falling back to --bundles app"
    cd "$ROOT" && npx tauri build --bundles app
}

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo ""
echo "==> 完成。耗时 ${ELAPSED}s。产物:"
ls -la "$ROOT/src-tauri/target/release/bundle/macos/" 2>/dev/null || true
ls -la "$ROOT/src-tauri/target/release/bundle/dmg/"   2>/dev/null || true
