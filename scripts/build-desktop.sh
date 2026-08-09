#!/usr/bin/env bash
# 一键构建桌面包: 前端 → PyInstaller sidecar → tauri build
set -euo pipefail

START_TS=$(date +%s)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIPLE="$(rustc --print host-tuple)"

echo "==> [build-desktop.sh] ROOT=$ROOT  TRIPLE=$TRIPLE"
echo ""

echo "==> 1/4 前端桌面构建 (base=/)"
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    (cd "$ROOT/frontend" && npm ci)
fi
cd "$ROOT/frontend" && npm run build:desktop

echo ""
echo "==> 2/4 PyInstaller 打 sidecar (onefile, 内嵌前端)"
cd "$ROOT/backend"
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt >/dev/null
# 全新 checkout 可能没装 pyinstaller — 缺则补装 (构建期依赖, 不入 requirements.txt 避免污染部署)
.venv/bin/python -m PyInstaller --version >/dev/null 2>&1 || .venv/bin/pip install "pyinstaller>=6.6"
# 预置 skill (backend/desktop/preset-skills) 经 ruijing-sidecar.spec 的 datas 收进包,
# 首启由 build_env._sync_preset_skills 覆盖式同步进 data_dir/skills/platform/。
.venv/bin/python -m PyInstaller ruijing-sidecar.spec --clean --noconfirm

echo ""
echo "==> 3/4 放置 sidecar 二进制 (triple=$TRIPLE)"
mkdir -p "$ROOT/src-tauri/binaries"
cp "$ROOT/backend/dist/ruijing-sidecar" "$ROOT/src-tauri/binaries/ruijing-sidecar-${TRIPLE}"
chmod +x "$ROOT/src-tauri/binaries/ruijing-sidecar-${TRIPLE}"
ls -lh "$ROOT/src-tauri/binaries/"

echo ""
if [[ "$(uname -s)" == "Darwin" ]]; then
    BUNDLES="app,dmg"
    FALLBACK_BUNDLES="app"
    BUNDLE_DIRS=("macos" "dmg")
else
    BUNDLES="appimage,deb"
    FALLBACK_BUNDLES="appimage"
    BUNDLE_DIRS=("appimage" "deb")
fi
echo "==> Tauri 出包 ($BUNDLES)"
if [[ ! -d "$ROOT/node_modules" ]]; then
    (cd "$ROOT" && npm ci)
fi
cd "$ROOT" && npx tauri build --bundles "$BUNDLES" || {
    echo ""
    echo "    WARNING: tauri bundle failed; falling back to --bundles $FALLBACK_BUNDLES"
    cd "$ROOT" && npx tauri build --bundles "$FALLBACK_BUNDLES"
}

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo ""
echo "==> 完成。耗时 ${ELAPSED}s。产物:"
for bundle_dir in "${BUNDLE_DIRS[@]}"; do
    ls -la "$ROOT/src-tauri/target/release/bundle/$bundle_dir/" 2>/dev/null || true
done
