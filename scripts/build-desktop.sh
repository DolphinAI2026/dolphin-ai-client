#!/usr/bin/env bash
# 一键构建桌面包: 前端 → PyInstaller sidecar → tauri build
set -euo pipefail

START_TS=$(date +%s)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST_OS="$(uname -s)"
HOST_ARCH="$(uname -m)"
TRIPLE="$(rustc --print host-tuple)"
CONFIG="$ROOT/src-tauri/tauri.conf.json"
SOURCE_REVISION="$(git -C "$ROOT" rev-parse HEAD)"
DESKTOP_PYTHON="${DOLPHIN_DESKTOP_PYTHON:-python3.11}"
UPDATER_ARTIFACTS_ENABLED=1
TAURI_TARGET_DIR=""
TAURI_RELEASE_DIR=""

is_release_build() {
    [[ "${DOLPHIN_RELEASE_BUILD:-}" == "1" || "${GITHUB_REF_TYPE:-}" == "tag" || "${GITHUB_REF:-}" == refs/tags/* ]]
}

assert_macos_arm_host() {
    local host_os="$1" host_arch="$2" host_triple="$3"
    [[ "$host_os" != "Darwin" ]] && return 0
    if [[ "$host_arch" != "arm64" && "$host_arch" != "aarch64" ]] || [[ "$host_triple" != "aarch64-apple-darwin" ]]; then
        echo "ERROR: build-desktop.sh only produces macOS aarch64 packages on Apple Silicon. Use scripts/build-desktop-x86.sh for Intel macOS packages." >&2
        return 1
    fi
}

assert_macos_arm_host "$HOST_OS" "$HOST_ARCH" "$TRIPLE"

restore_tauri_config() {
    if [[ -n "${TAURI_CONFIG_BACKUP:-}" ]]; then
        cp "$TAURI_CONFIG_BACKUP" "$CONFIG"
        rm -f "$TAURI_CONFIG_BACKUP"
    fi
}

cleanup_build_target() {
    if [[ -n "${TAURI_TARGET_DIR:-}" && -d "$TAURI_TARGET_DIR" ]]; then
        rm -rf "$TAURI_TARGET_DIR"
    fi
}

cleanup() {
    restore_tauri_config
    cleanup_build_target
}

trap cleanup EXIT

if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]]; then
    if is_release_build; then
        echo "ERROR: TAURI_SIGNING_PRIVATE_KEY is required for a Release-tag desktop build." >&2
        exit 1
    fi
    mkdir -p /tmp/d-ai-code/build-desktop
    TAURI_CONFIG_BACKUP="$(mktemp /tmp/d-ai-code/build-desktop/tauri.conf.XXXXXX)"
    cp "$CONFIG" "$TAURI_CONFIG_BACKUP"
    node -e 'const fs = require("node:fs"); const file = process.argv[1]; const config = JSON.parse(fs.readFileSync(file, "utf8")); config.bundle.createUpdaterArtifacts = false; fs.writeFileSync(file, `${JSON.stringify(config, null, 2)}\n`);' "$CONFIG"
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

copy_linux_signatures() {
    local source_dir="$1" release_dir="$2" prefix="$3" source base suffix destination
    local signature_count=0
    while IFS= read -r -d '' source; do
        base="$(basename "$source")"
        suffix=""
        [[ "$base" == *.sig ]] && suffix=".sig" && base="${base%.sig}"
        case "$base" in
            *.AppImage) destination="$release_dir/${prefix}.AppImage${suffix}" ;;
            *.deb) destination="$release_dir/${prefix}.deb${suffix}" ;;
            *)
                echo "ERROR: unsupported Linux signature artifact: $source" >&2
                return 1
                ;;
        esac
        cp "$source" "$destination"
        [[ "$suffix" == ".sig" ]] && ((signature_count += 1))
    done < <(find "$source_dir" -maxdepth 1 -type f -name '*.sig' -print0)
    if (( UPDATER_ARTIFACTS_ENABLED )) && (( signature_count == 0 )); then
        echo "ERROR: Tauri updater artifacts were enabled but Linux signatures were not generated." >&2
        return 1
    fi
}

copy_macos_updater_artifacts() {
    local release_dir="$1" prefix="$2" source_dir source base suffix destination
    local signature_count=0
    shift 2
    for source_dir in "$@"; do
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
    if (( UPDATER_ARTIFACTS_ENABLED )) && (( signature_count == 0 )); then
        echo "ERROR: Tauri updater artifacts were enabled but macOS signatures were not generated." >&2
        return 1
    fi
}

publish_linux_release() {
    local version release_dir appimage_dir deb_dir prefix
    version="$(read_package_version)"
    release_dir="$ROOT/dist-desktop/release"
    appimage_dir="$TAURI_RELEASE_DIR/bundle/appimage"
    deb_dir="$TAURI_RELEASE_DIR/bundle/deb"
    prefix="dolphin-ai-${version}-linux-x86_64"
    mkdir -p "$release_dir"
    find "$release_dir" -maxdepth 1 -type f -name '*portable*.zip' -delete
    find "$release_dir" -maxdepth 1 -type f \( -iname '*ruijing-*' -o -iname '*dolphin code*' -o -iname '*ruijing-sidecar*' \) -delete
    copy_single_artifact "$appimage_dir" '*.AppImage' "$release_dir/${prefix}.AppImage"
    copy_single_artifact "$deb_dir" '*.deb' "$release_dir/${prefix}.deb"
    copy_linux_signatures "$appimage_dir" "$release_dir" "$prefix"
    copy_linux_signatures "$deb_dir" "$release_dir" "$prefix"
    local -a brand_args=(--root "$release_dir" --version "$version" --platform linux)
    (( UPDATER_ARTIFACTS_ENABLED )) && brand_args+=(--require-updater)
    node "$ROOT/scripts/verify-desktop-release-brand.mjs" "${brand_args[@]}"
}

publish_macos_arm_release() {
    local version release_dir dmg_dir app_dir prefix
    version="$(read_package_version)"
    release_dir="$ROOT/dist-desktop/release"
    dmg_dir="$TAURI_RELEASE_DIR/bundle/dmg"
    app_dir="$TAURI_RELEASE_DIR/bundle/macos"
    prefix="dolphin-ai-${version}-macos-aarch64"
    mkdir -p "$release_dir"
    find "$release_dir" -maxdepth 1 -type f -name '*portable*.zip' -delete
    find "$release_dir" -maxdepth 1 -type f \( -iname '*ruijing-*' -o -iname '*dolphin code*' -o -iname '*ruijing-sidecar*' \) -delete
    copy_single_artifact "$dmg_dir" '*.dmg' "$release_dir/${prefix}.dmg"
    copy_macos_updater_artifacts "$release_dir" "$prefix" "$app_dir" "$dmg_dir"
    local -a brand_args=(--root "$release_dir" --version "$version" --platform macos)
    (( UPDATER_ARTIFACTS_ENABLED )) && brand_args+=(--require-updater)
    node "$ROOT/scripts/verify-desktop-release-brand.mjs" "${brand_args[@]}"
}

repack_linux_appimage_with_pristine_codex() {
    local bundle_dir="$TAURI_RELEASE_DIR/bundle/appimage"
    local source_codex="$ROOT/src-tauri/resources/agent-runtime/codex/bin/codex"
    local source_builder_index="$ROOT/src-tauri/resources/agent-runtime/web/builder/dist/index.html"
    local appdir appdir_codex output_file output_name plugin arch
    local source_hash bundled_hash extracted_codex extracted_builder_index smoke_dir codex_version

    [[ -x "$source_codex" ]] || {
        echo "ERROR: Linux Runtime Codex 不存在或不可执行: $source_codex" >&2
        return 1
    }
    [[ -f "$source_builder_index" ]] || {
        echo "ERROR: Linux Runtime Builder 入口不存在: $source_builder_index" >&2
        return 1
    }
    grep -q 'id="root"' "$source_builder_index" && grep -q 'type="module"' "$source_builder_index" || {
        echo "ERROR: Linux Runtime Builder 入口不是可运行的前端构建产物: $source_builder_index" >&2
        return 1
    }

    appdir="$(find_exactly_one "期望恰好一个 AppDir: $bundle_dir" find "$bundle_dir" -maxdepth 1 -type d -name '*.AppDir' -print0)" || return 1

    appdir_codex="$(find_exactly_one "AppDir 中未找到唯一的 Runtime Codex" find "$appdir" -type f -path '*/resources/agent-runtime/codex/bin/codex' -print0)" || return 1

    output_file="$(find_exactly_one "期望恰好一个 AppImage: $bundle_dir" find "$bundle_dir" -maxdepth 1 -type f -name '*.AppImage' -print0)" || return 1
    output_name="$(basename "$output_file")"

    plugin="${LINUXDEPLOY_PLUGIN_APPIMAGE:-$HOME/.cache/tauri/linuxdeploy-plugin-appimage.AppImage}"
    [[ -x "$plugin" ]] || {
        echo "ERROR: 找不到 Tauri AppImage 封装插件: $plugin" >&2
        return 1
    }

    echo "==> 恢复 AppDir 中被 linuxdeploy 改写的 Runtime Codex"
    cp "$source_codex" "$appdir_codex"
    chmod +x "$appdir_codex"
    source_hash="$(sha256sum "$source_codex" | awk '{print $1}')"
    bundled_hash="$(sha256sum "$appdir_codex" | awk '{print $1}')"
    [[ "$source_hash" == "$bundled_hash" ]] || {
        echo "ERROR: AppDir Runtime Codex 哈希与源文件不一致" >&2
        return 1
    }

    case "$(uname -m)" in
        x86_64) arch="x86_64" ;;
        aarch64|arm64) arch="aarch64" ;;
        *)
            echo "ERROR: 不支持的 AppImage 架构: $(uname -m)" >&2
            return 1
            ;;
    esac

    find "$bundle_dir" -maxdepth 1 -type f -name '*.AppImage' -delete
    (
        cd "$bundle_dir"
        ARCH="$arch" LDAI_OUTPUT="$output_name" \
            "$plugin" --appimage-extract-and-run --appdir="$appdir"
    )
    [[ -x "$output_file" ]] || {
        echo "ERROR: AppImage 重新封装后未生成: $output_file" >&2
        return 1
    }
    if (( UPDATER_ARTIFACTS_ENABLED )); then
        echo "==> 为最终 AppImage 重新生成更新签名"
        rm -f "${output_file}.sig"
        npx tauri signer sign "$output_file"
        [[ -s "${output_file}.sig" ]] || {
            echo "ERROR: 最终 AppImage 未生成更新签名: ${output_file}.sig" >&2
            return 1
        }
    fi

    mkdir -p /tmp/d-ai-code/build-desktop
    smoke_dir="$(mktemp -d /tmp/d-ai-code/build-desktop/appimage-codex.XXXXXX)"
    (
        cd "$smoke_dir"
        "$output_file" --appimage-extract \
            'usr/lib/*/resources/agent-runtime/codex/bin/codex' >/dev/null
        "$output_file" --appimage-extract \
            'usr/lib/*/resources/agent-runtime/web/builder/dist/index.html' >/dev/null
    )
    extracted_codex="$(find_exactly_one "无法从最终 AppImage 提取唯一的 Runtime Codex" find "$smoke_dir/squashfs-root" -type f -path '*/resources/agent-runtime/codex/bin/codex' -print0)" || {
        find "$smoke_dir" -depth -delete
        return 1
    }
    bundled_hash="$(sha256sum "$extracted_codex" | awk '{print $1}')"
    [[ "$source_hash" == "$bundled_hash" ]] || {
        echo "ERROR: 最终 AppImage 再次改写了 Runtime Codex" >&2
        find "$smoke_dir" -depth -delete
        return 1
    }
    codex_version="$("$extracted_codex" --version)"
    extracted_builder_index="$(find_exactly_one "无法从最终 AppImage 提取唯一的 Builder 入口" find "$smoke_dir/squashfs-root" -type f -path '*/resources/agent-runtime/web/builder/dist/index.html' -print0)" || {
        find "$smoke_dir" -depth -delete
        return 1
    }
    grep -q 'id="root"' "$extracted_builder_index" && grep -q 'type="module"' "$extracted_builder_index" || {
        echo "ERROR: 最终 AppImage 内 Builder 入口缺少前端模块" >&2
        find "$smoke_dir" -depth -delete
        return 1
    }
    find "$smoke_dir" -depth -delete
    echo "==> AppImage Runtime 校验通过: $codex_version，Builder workbench 已包含"
}

echo "==> [build-desktop.sh] ROOT=$ROOT  TRIPLE=$TRIPLE REVISION=$SOURCE_REVISION"
echo ""

echo "==> 1/4 前端桌面构建 (base=/)"
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    (cd "$ROOT/frontend" && npm ci)
fi
if [[ "$HOST_OS" == "Darwin" ]]; then
    DOLPHIN_BUILD_TARGET="macos-aarch64"
else
    DOLPHIN_BUILD_TARGET="linux-x86_64"
fi
(
    cd "$ROOT/frontend"
    DOLPHIN_BUILD_REVISION="$SOURCE_REVISION" DOLPHIN_BUILD_TARGET="$DOLPHIN_BUILD_TARGET" npm run build:desktop
)

echo ""
echo "==> 2/4 PyInstaller 打 sidecar (onefile, 内嵌前端)"
cd "$ROOT/backend"
command -v "$DESKTOP_PYTHON" >/dev/null 2>&1 || {
    echo "ERROR: desktop sidecar build requires Python 3.11: $DESKTOP_PYTHON" >&2
    exit 1
}
if [[ ! -x .venv/bin/python ]]; then
    "$DESKTOP_PYTHON" -m venv .venv
fi
.venv/bin/python - <<'PY'
import sys

if sys.version_info[:2] != (3, 11):
    raise SystemExit(
        "desktop sidecar build requires Python 3.11; remove backend/.venv and retry"
    )
PY
.venv/bin/python -m pip install -r requirements.txt >/dev/null
# 全新 checkout 可能没装 pyinstaller — 缺则补装 (构建期依赖, 不入 requirements.txt 避免污染部署)
.venv/bin/python -m PyInstaller --version >/dev/null 2>&1 || .venv/bin/pip install "pyinstaller>=6.6"
# 预置 skill (backend/desktop/preset-skills) 经 dolphin-ai-sidecar.spec 的 datas 收进包,
# 首启由 build_env._sync_preset_skills 覆盖式同步进 data_dir/skills/platform/。
# 注入构建期 env 防 collect_submodules("app") 触发 Settings() 校验失败
export JWT_SECRET_KEY="pyinstaller-build-placeholder"
export ENCRYPTION_KEY="$(.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))")"
export DATABASE_URL="sqlite+aiosqlite:///:memory:"
export ALLOW_DEFAULT_ENCRYPTION_KEY="1"
.venv/bin/python -m PyInstaller dolphin-ai-sidecar.spec --clean --noconfirm
"$ROOT/backend/.venv/bin/python" "$ROOT/scripts/verify-desktop-sidecar.py" \
    --sidecar "$ROOT/backend/dist/dolphin-ai-sidecar" \
    --verify-import app.agents.profile \
    --timeout-seconds 60

echo ""
echo "==> 3/4 放置 sidecar 二进制 (triple=$TRIPLE)"
mkdir -p "$ROOT/src-tauri/binaries"
cp "$ROOT/backend/dist/dolphin-ai-sidecar" "$ROOT/src-tauri/binaries/dolphin-ai-sidecar-${TRIPLE}"
chmod +x "$ROOT/src-tauri/binaries/dolphin-ai-sidecar-${TRIPLE}"
ls -lh "$ROOT/src-tauri/binaries/"

echo ""
if [[ "$HOST_OS" == "Darwin" ]]; then
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
BUILDER_INDEX="$ROOT/src-tauri/resources/agent-runtime/web/builder/dist/index.html"
[[ -f "$BUILDER_INDEX" ]] || {
    echo "ERROR: Tauri 构建前缺少 Builder 入口: $BUILDER_INDEX" >&2
    exit 1
}
grep -q 'id="root"' "$BUILDER_INDEX" && grep -q 'type="module"' "$BUILDER_INDEX" || {
    echo "ERROR: Tauri 构建前 Builder 入口不是可运行的前端构建产物: $BUILDER_INDEX" >&2
    exit 1
}
mkdir -p /tmp/d-ai-code/build-desktop
TAURI_TARGET_DIR="$(mktemp -d /tmp/d-ai-code/build-desktop/tauri-target.XXXXXX)"
TAURI_RELEASE_DIR="$TAURI_TARGET_DIR/release"
echo "==> 使用隔离 Tauri 构建目录：$TAURI_TARGET_DIR"
for bundle_dir in "${BUNDLE_DIRS[@]}"; do
    generated_dir="$TAURI_RELEASE_DIR/bundle/$bundle_dir"
    if [[ -d "$generated_dir" ]]; then
        find "$generated_dir" -mindepth 1 -delete
    fi
done

run_tauri_build() {
    if [[ "${DOLPHIN_TAURI_VERBOSE:-}" == "1" ]]; then
        CARGO_TARGET_DIR="$TAURI_TARGET_DIR" npx tauri build --verbose --bundles "$1"
    else
        CARGO_TARGET_DIR="$TAURI_TARGET_DIR" npx tauri build --bundles "$1"
    fi
}

cd "$ROOT" && run_tauri_build "$BUNDLES" || {
    echo ""
    echo "    WARNING: tauri bundle failed; falling back to --bundles $FALLBACK_BUNDLES"
    cd "$ROOT" && run_tauri_build "$FALLBACK_BUNDLES"
}

if [[ "$HOST_OS" == "Linux" ]]; then
    repack_linux_appimage_with_pristine_codex
    publish_linux_release
else
    publish_macos_arm_release
fi

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo ""
echo "==> 完成。耗时 ${ELAPSED}s。产物:"
for bundle_dir in "${BUNDLE_DIRS[@]}"; do
    ls -la "$ROOT/src-tauri/target/release/bundle/$bundle_dir/" 2>/dev/null || true
done
