#!/usr/bin/env bash
# 一键构建桌面包: 前端 → PyInstaller sidecar → tauri build
set -euo pipefail

START_TS=$(date +%s)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIPLE="$(rustc --print host-tuple)"
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

copy_single_artifact() {
    local source_dir="$1" pattern="$2" destination="$3"
    local -a matches
    mapfile -d '' matches < <(find "$source_dir" -maxdepth 1 -type f -name "$pattern" -print0)
    [[ ${#matches[@]} -eq 1 ]] || {
        echo "ERROR: expected one $pattern artifact under $source_dir, found ${#matches[@]}" >&2
        return 1
    }
    cp "${matches[0]}" "$destination"
}

copy_linux_updater_artifacts() {
    local source_dir="$1" release_dir="$2" prefix="$3" source base suffix destination
    local signature_count=0
    while IFS= read -r -d '' source; do
        base="$(basename "$source")"
        suffix=""
        [[ "$base" == *.sig ]] && suffix=".sig" && base="${base%.sig}"
        case "$base" in
            *.AppImage.tar.gz) destination="$release_dir/${prefix}-updater.AppImage.tar.gz${suffix}" ;;
            *.AppImage) destination="$release_dir/${prefix}.AppImage${suffix}" ;;
            *.deb) destination="$release_dir/${prefix}.deb${suffix}" ;;
            *)
                echo "ERROR: unsupported Linux updater artifact: $source" >&2
                return 1
                ;;
        esac
        cp "$source" "$destination"
        [[ "$suffix" == ".sig" ]] && ((signature_count += 1))
    done < <(find "$source_dir" -maxdepth 1 -type f \( -name '*.sig' -o -name '*.AppImage.tar.gz' \) -print0)
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
    appimage_dir="$ROOT/src-tauri/target/release/bundle/appimage"
    deb_dir="$ROOT/src-tauri/target/release/bundle/deb"
    prefix="dolphin-ai-${version}-linux-x86_64"
    mkdir -p "$release_dir"
    find "$release_dir" -maxdepth 1 -type f -name '*portable*.zip' -delete
    find "$release_dir" -maxdepth 1 -type f \( -iname '*ruijing-*' -o -iname '*dolphin code*' -o -iname '*ruijing-sidecar*' \) -delete
    copy_single_artifact "$appimage_dir" '*.AppImage' "$release_dir/${prefix}.AppImage"
    copy_single_artifact "$deb_dir" '*.deb' "$release_dir/${prefix}.deb"
    copy_linux_updater_artifacts "$appimage_dir" "$release_dir" "$prefix"
    copy_linux_updater_artifacts "$deb_dir" "$release_dir" "$prefix"
    local -a brand_args=(--root "$release_dir" --version "$version" --platform linux)
    (( UPDATER_ARTIFACTS_ENABLED )) && brand_args+=(--require-updater)
    node "$ROOT/scripts/verify-desktop-release-brand.mjs" "${brand_args[@]}"
}

publish_macos_arm_release() {
    local version release_dir dmg_dir app_dir prefix
    version="$(read_package_version)"
    release_dir="$ROOT/dist-desktop/release"
    dmg_dir="$ROOT/src-tauri/target/release/bundle/dmg"
    app_dir="$ROOT/src-tauri/target/release/bundle/macos"
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
    local bundle_dir="$ROOT/src-tauri/target/release/bundle/appimage"
    local source_codex="$ROOT/src-tauri/resources/agent-runtime/codex/bin/codex"
    local source_builder_index="$ROOT/src-tauri/resources/agent-runtime/web/builder/dist/index.html"
    local appdir appdir_codex output_file output_name plugin arch
    local source_hash bundled_hash extracted_codex extracted_builder_index smoke_dir codex_version
    local -a matches

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

    mapfile -d '' matches < <(find "$bundle_dir" -maxdepth 1 -type d -name '*.AppDir' -print0)
    [[ ${#matches[@]} -eq 1 ]] || {
        echo "ERROR: 期望恰好一个 AppDir，实际 ${#matches[@]} 个: $bundle_dir" >&2
        return 1
    }
    appdir="${matches[0]}"

    mapfile -d '' matches < <(
        find "$appdir" -type f -path '*/resources/agent-runtime/codex/bin/codex' -print0
    )
    [[ ${#matches[@]} -eq 1 ]] || {
        echo "ERROR: AppDir 中未找到唯一的 Runtime Codex，实际 ${#matches[@]} 个" >&2
        return 1
    }
    appdir_codex="${matches[0]}"

    mapfile -d '' matches < <(find "$bundle_dir" -maxdepth 1 -type f -name '*.AppImage' -print0)
    [[ ${#matches[@]} -eq 1 ]] || {
        echo "ERROR: 期望恰好一个 AppImage，实际 ${#matches[@]} 个: $bundle_dir" >&2
        return 1
    }
    output_file="${matches[0]}"
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

    mkdir -p /tmp/d-ai-code/build-desktop
    smoke_dir="$(mktemp -d /tmp/d-ai-code/build-desktop/appimage-codex.XXXXXX)"
    (
        cd "$smoke_dir"
        "$output_file" --appimage-extract \
            'usr/lib/*/resources/agent-runtime/codex/bin/codex' >/dev/null
        "$output_file" --appimage-extract \
            'usr/lib/*/resources/agent-runtime/web/builder/dist/index.html' >/dev/null
    )
    mapfile -d '' matches < <(
        find "$smoke_dir/squashfs-root" -type f \
            -path '*/resources/agent-runtime/codex/bin/codex' -print0
    )
    [[ ${#matches[@]} -eq 1 ]] || {
        echo "ERROR: 无法从最终 AppImage 提取唯一的 Runtime Codex" >&2
        find "$smoke_dir" -depth -delete
        return 1
    }
    extracted_codex="${matches[0]}"
    bundled_hash="$(sha256sum "$extracted_codex" | awk '{print $1}')"
    [[ "$source_hash" == "$bundled_hash" ]] || {
        echo "ERROR: 最终 AppImage 再次改写了 Runtime Codex" >&2
        find "$smoke_dir" -depth -delete
        return 1
    }
    codex_version="$("$extracted_codex" --version)"
    mapfile -d '' matches < <(
        find "$smoke_dir/squashfs-root" -type f \
            -path '*/resources/agent-runtime/web/builder/dist/index.html' -print0
    )
    [[ ${#matches[@]} -eq 1 ]] || {
        echo "ERROR: 无法从最终 AppImage 提取唯一的 Builder 入口" >&2
        find "$smoke_dir" -depth -delete
        return 1
    }
    extracted_builder_index="${matches[0]}"
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
if [[ "$(uname -s)" == "Darwin" ]]; then
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
if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt >/dev/null
# 全新 checkout 可能没装 pyinstaller — 缺则补装 (构建期依赖, 不入 requirements.txt 避免污染部署)
.venv/bin/python -m PyInstaller --version >/dev/null 2>&1 || .venv/bin/pip install "pyinstaller>=6.6"
# 预置 skill (backend/desktop/preset-skills) 经 dolphin-ai-sidecar.spec 的 datas 收进包,
# 首启由 build_env._sync_preset_skills 覆盖式同步进 data_dir/skills/platform/。
.venv/bin/python -m PyInstaller dolphin-ai-sidecar.spec --clean --noconfirm

echo ""
echo "==> 3/4 放置 sidecar 二进制 (triple=$TRIPLE)"
mkdir -p "$ROOT/src-tauri/binaries"
cp "$ROOT/backend/dist/dolphin-ai-sidecar" "$ROOT/src-tauri/binaries/dolphin-ai-sidecar-${TRIPLE}"
chmod +x "$ROOT/src-tauri/binaries/dolphin-ai-sidecar-${TRIPLE}"
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
BUILDER_INDEX="$ROOT/src-tauri/resources/agent-runtime/web/builder/dist/index.html"
[[ -f "$BUILDER_INDEX" ]] || {
    echo "ERROR: Tauri 构建前缺少 Builder 入口: $BUILDER_INDEX" >&2
    exit 1
}
grep -q 'id="root"' "$BUILDER_INDEX" && grep -q 'type="module"' "$BUILDER_INDEX" || {
    echo "ERROR: Tauri 构建前 Builder 入口不是可运行的前端构建产物: $BUILDER_INDEX" >&2
    exit 1
}
for bundle_dir in "${BUNDLE_DIRS[@]}"; do
    generated_dir="$ROOT/src-tauri/target/release/bundle/$bundle_dir"
    if [[ -d "$generated_dir" ]]; then
        find "$generated_dir" -mindepth 1 -delete
    fi
done
cd "$ROOT" && npx tauri build --bundles "$BUNDLES" || {
    echo ""
    echo "    WARNING: tauri bundle failed; falling back to --bundles $FALLBACK_BUNDLES"
    cd "$ROOT" && npx tauri build --bundles "$FALLBACK_BUNDLES"
}

if [[ "$(uname -s)" == "Linux" ]]; then
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
