#!/usr/bin/env bash
# 在 Apple Silicon 机器上交叉构建 Intel (x86_64) 桌面包。
# 前提: 已装 rust target x86_64-apple-darwin + backend/.venv-x86 (uv 建的 x86_64 venv)。
# sidecar 用 Rosetta 跑 x86_64 Python + PyInstaller (PyInstaller 不能交叉编译, 故走 Rosetta)。
set -euo pipefail

START_TS=$(date +%s)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="x86_64-apple-darwin"
PYX86VENV="$ROOT/backend/.venv-x86/bin/python"
CONFIG="$ROOT/src-tauri/tauri.conf.json"
SOURCE_REVISION="$(git -C "$ROOT" rev-parse HEAD)"
UPDATER_ARTIFACTS_ENABLED=1

is_release_build() {
    [[ "${DOLPHIN_RELEASE_BUILD:-}" == "1" || "${GITHUB_REF_TYPE:-}" == "tag" || "${GITHUB_REF:-}" == refs/tags/* ]]
}

restore_tauri_config() {
    if [[ -n "${TAURI_CONFIG_BACKUP:-}" ]]; then
        cp "$TAURI_CONFIG_BACKUP" "$CONFIG"
        rm -f "$TAURI_CONFIG_BACKUP"
    fi
}

if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    if is_release_build; then
        echo "ERROR: TAURI_SIGNING_PRIVATE_KEY is required for a Release-tag desktop build." >&2
        exit 1
    fi
    mkdir -p /tmp/d-ai-code/build-desktop
    TAURI_CONFIG_BACKUP="$(mktemp /tmp/d-ai-code/build-desktop/tauri.conf.XXXXXX)"
    cp "$CONFIG" "$TAURI_CONFIG_BACKUP"
    node -e 'const fs = require("node:fs"); const file = process.argv[1]; const config = JSON.parse(fs.readFileSync(file, "utf8")); config.bundle.createUpdaterArtifacts = false; fs.writeFileSync(file, `${JSON.stringify(config, null, 2)}\n`);' "$CONFIG"
    trap restore_tauri_config EXIT
    UPDATER_ARTIFACTS_ENABLED=0
    echo "==> TAURI_SIGNING_PRIVATE_KEY is not set; updater artifacts are temporarily disabled for this non-Release desktop build."
fi

read_package_version() {
    node -e 'const fs = require("node:fs"); console.log(JSON.parse(fs.readFileSync(process.argv[1], "utf8")).version);' "$CONFIG"
}

find_exactly_one() {
    local description="$1" candidate match="" count=0
    shift
    while IFS= read -r -d '' candidate; do
        match="$candidate"
        count=$((count + 1))
    done < <("$@")
    [[ "$count" -eq 1 ]] || {
        echo "ERROR: $description, found $count" >&2
        return 1
    }
    printf '%s\n' "$match"
}

copy_single_artifact() {
    local source_dir="$1" pattern="$2" destination="$3" source
    source="$(find_exactly_one "expected one $pattern artifact under $source_dir" find "$source_dir" -maxdepth 1 -type f -name "$pattern" -print0)" || return 1
    cp "$source" "$destination"
}

publish_macos_x86_release() {
    local version release_dir dmg_dir app_dir prefix signature_count=0 source base suffix destination source_dir
    version="$(read_package_version)"
    release_dir="$ROOT/dist-desktop/release"
    dmg_dir="$ROOT/src-tauri/target/$TARGET/release/bundle/dmg"
    app_dir="$ROOT/src-tauri/target/$TARGET/release/bundle/macos"
    prefix="dolphin-ai-${version}-macos-x86_64"
    mkdir -p "$release_dir"
    find "$release_dir" -maxdepth 1 -type f -name '*portable*.zip' -delete
    find "$release_dir" -maxdepth 1 -type f \( -iname '*ruijing-*' -o -iname '*dolphin code*' -o -iname '*ruijing-sidecar*' \) -delete
    copy_single_artifact "$dmg_dir" '*.dmg' "$release_dir/${prefix}.dmg"
    for source_dir in "$app_dir" "$dmg_dir"; do
        while IFS= read -r -d '' source; do
            base="$(basename "$source")"
            suffix=""
            [[ "$base" == *.sig ]] && suffix=".sig" && base="${base%.sig}"
            case "$base" in
                *.app.tar.gz) destination="$release_dir/${prefix}-updater.app.tar.gz${suffix}" ;;
                *.dmg) destination="$release_dir/${prefix}.dmg${suffix}" ;;
                *)
                    echo "ERROR: unsupported macOS updater artifact: $source" >&2
                    return 1
                    ;;
            esac
            cp "$source" "$destination"
            [[ "$suffix" == ".sig" ]] && ((signature_count += 1))
        done < <(find "$source_dir" -maxdepth 1 -type f \( -name '*.sig' -o -name '*.app.tar.gz' \) -print0)
    done
    if (( UPDATER_ARTIFACTS_ENABLED && signature_count == 0 )); then
        echo "ERROR: Tauri updater artifacts were enabled but macOS signatures were not generated." >&2
        return 1
    fi
    local -a brand_args=(--root "$release_dir" --version "$version" --platform macos-x86_64)
    (( UPDATER_ARTIFACTS_ENABLED )) && brand_args+=(--require-updater)
    node "$ROOT/scripts/verify-desktop-release-brand.mjs" "${brand_args[@]}"
}

echo "==> [build-desktop-x86.sh] ROOT=$ROOT  TARGET=$TARGET REVISION=$SOURCE_REVISION"
[ -x "$PYX86VENV" ] || { echo "ERROR: 缺 x86 venv ($PYX86VENV)"; exit 1; }

echo ""
echo "==> 1/4 前端桌面构建 (base=/)"
(
    cd "$ROOT/frontend"
    DOLPHIN_BUILD_REVISION="$SOURCE_REVISION" DOLPHIN_BUILD_TARGET="macos-x86_64" npm run build:desktop
)

echo ""
echo "==> 2/4 PyInstaller x86_64 sidecar (Rosetta)"
cd "$ROOT/backend"
arch -x86_64 "$PYX86VENV" -m PyInstaller dolphin-ai-sidecar.spec --clean --noconfirm \
    --distpath dist-x86 --workpath build-x86
arch -x86_64 "$PYX86VENV" "$ROOT/scripts/verify-desktop-sidecar.py" \
    --sidecar "$ROOT/backend/dist-x86/dolphin-ai-sidecar"

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
publish_macos_x86_release

END_TS=$(date +%s)
echo ""
echo "==> 完成。耗时 $((END_TS - START_TS))s。产物:"
ls -la "$ROOT/src-tauri/target/${TARGET}/release/bundle/macos/" 2>/dev/null || true
ls -la "$ROOT/src-tauri/target/${TARGET}/release/bundle/dmg/"   2>/dev/null || true
