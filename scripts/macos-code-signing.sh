#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 sign-resources <directory> | verify-app <path.app>" >&2
    exit 2
}

[[ $# -eq 2 ]] || usage
MODE="$1"
TARGET="$2"

command -v codesign >/dev/null 2>&1 || {
    echo "ERROR: codesign is required for macOS packaging." >&2
    exit 1
}

case "$MODE" in
    sign-resources)
        [[ -d "$TARGET" ]] || {
            echo "ERROR: macOS Runtime resource directory does not exist: $TARGET" >&2
            exit 1
        }
        command -v file >/dev/null 2>&1 || {
            echo "ERROR: file is required to identify Mach-O resources." >&2
            exit 1
        }

        signed_count=0
        while IFS= read -r -d '' candidate; do
            if [[ "$(file -b "$candidate")" == Mach-O* ]]; then
                codesign --force --sign - --timestamp=none "$candidate"
                signed_count=$((signed_count + 1))
            fi
        done < <(find "$TARGET" -type f -print0)

        nested_bundles=()
        while IFS= read -r -d '' candidate; do
            nested_bundles+=("$candidate")
        done < <(find "$TARGET" -type d \( -name '*.framework' -o -name '*.xpc' -o -name '*.appex' -o -name '*.app' \) -print0)
        for ((index=${#nested_bundles[@]} - 1; index >= 0; index--)); do
            codesign --force --sign - --timestamp=none "${nested_bundles[$index]}"
            signed_count=$((signed_count + 1))
        done

        (( signed_count > 0 )) || {
            echo "ERROR: no Mach-O files were found under macOS Runtime resources: $TARGET" >&2
            exit 1
        }
        echo "==> macOS Runtime ad-hoc signing complete: $signed_count code objects"
        ;;
    verify-app)
        [[ -d "$TARGET" && "$TARGET" == *.app ]] || {
            echo "ERROR: expected a macOS .app bundle: $TARGET" >&2
            exit 1
        }
        codesign --verify --deep --strict --verbose=4 "$TARGET"
        echo "==> macOS app signature verification passed: $TARGET"
        ;;
    *)
        usage
        ;;
esac
