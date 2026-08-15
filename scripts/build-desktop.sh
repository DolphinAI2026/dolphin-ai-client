#!/usr/bin/env bash
# 一键构建桌面包: 前端 → PyInstaller sidecar → tauri build
set -euo pipefail

START_TS=$(date +%s)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRIPLE="$(rustc --print host-tuple)"

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
fi

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo ""
echo "==> 完成。耗时 ${ELAPSED}s。产物:"
for bundle_dir in "${BUNDLE_DIRS[@]}"; do
    ls -la "$ROOT/src-tauri/target/release/bundle/$bundle_dir/" 2>/dev/null || true
done
