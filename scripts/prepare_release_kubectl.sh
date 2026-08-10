#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
artifact="${KUBECTL_ARTIFACT:-build/tools/kubectl}"

case "$mode" in
  export)
    source_path="${KUBECTL_SOURCE:-$(command -v kubectl)}"
    test -n "$source_path"
    test -x "$source_path"
    mkdir -p "$(dirname "$artifact")"
    cp "$source_path" "$artifact"
    chmod 755 "$artifact"
    ;;
  install)
    destination="${KUBECTL_DESTINATION:-/usr/local/bin/kubectl}"
    test -s "$artifact"
    mkdir -p "$(dirname "$destination")"
    cp "$artifact" "$destination"
    chmod 755 "$destination"
    ;;
  *)
    printf 'usage: %s {export|install}\n' "$0" >&2
    exit 64
    ;;
esac
