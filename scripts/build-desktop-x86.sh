#!/usr/bin/env bash
# 在 Apple Silicon 机器上交叉构建 Intel (x86_64) 桌面包。
# 前提: 已装 rust target x86_64-apple-darwin + backend/.venv-x86 (uv 建的 x86_64 venv)。
# sidecar 用 Rosetta 跑 x86_64 Python + PyInstaller (PyInstaller 不能交叉编译, 故走 Rosetta)。
set -euo pipefail

START_TS=$(date +%s)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="x86_64-apple-darwin"
PYX86VENV="$ROOT/backend/.venv-x86/bin/python"

echo "==> [build-desktop-x86.sh] ROOT=$ROOT  TARGET=$TARGET"
[ -x "$PYX86VENV" ] || { echo "ERROR: 缺 x86 venv ($PYX86VENV)"; exit 1; }

echo ""
echo "==> 1/4 前端桌面构建 (base=/)"
cd "$ROOT/frontend" && npm run build:desktop

echo ""
echo "==> 2/4 PyInstaller x86_64 sidecar (Rosetta)"
cd "$ROOT/backend"
arch -x86_64 "$PYX86VENV" -m PyInstaller dolphin-ai-sidecar.spec --clean --noconfirm \
    --distpath dist-x86 --workpath build-x86

echo ""
echo "==> 3/4 放置 x86 sidecar 二进制 (triple=$TARGET)"
mkdir -p "$ROOT/src-tauri/binaries"
cp "$ROOT/backend/dist-x86/dolphin-ai-sidecar" "$ROOT/src-tauri/binaries/dolphin-ai-sidecar-${TARGET}"
chmod +x "$ROOT/src-tauri/binaries/dolphin-ai-sidecar-${TARGET}"
file "$ROOT/src-tauri/binaries/dolphin-ai-sidecar-${TARGET}"

echo ""
echo "==> 4/4 Tauri build --target $TARGET"
cd "$ROOT" && npx tauri build --target "$TARGET" --bundles app,dmg || {
    echo ""
    echo "    WARNING: tauri build 失败 (DMG 可能需完整 Xcode); 回退 --bundles app"
    cd "$ROOT" && npx tauri build --target "$TARGET" --bundles app
}

END_TS=$(date +%s)
echo ""
echo "==> 完成。耗时 $((END_TS - START_TS))s。产物:"
ls -la "$ROOT/src-tauri/target/${TARGET}/release/bundle/macos/" 2>/dev/null || true
ls -la "$ROOT/src-tauri/target/${TARGET}/release/bundle/dmg/"   2>/dev/null || true
