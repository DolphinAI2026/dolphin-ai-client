#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PARENT_CI_PATH="${ROOT_DIR}/.gitlab-ci.yml"
CHILD_CI_PATH="${ROOT_DIR}/.gitlab/ci/release-builder-child.yml"
HELPER_PATH="${ROOT_DIR}/scripts/prepare_release_kubectl.sh"
TMP_DIR="$(mktemp -d -t builder-kubectl-artifact.XXXXXX)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

test -x "$HELPER_PATH"

ruby -ryaml - "$PARENT_CI_PATH" "$CHILD_CI_PATH" <<'RUBY'
parent = YAML.load_file(ARGV.fetch(0))
child = YAML.load_file(ARGV.fetch(1))
image = "hub-mirror.dfy.definesys.cn/bitnami/kubectl:1.30.7"
artifact = "build/tools/kubectl"
helper = "bash scripts/prepare_release_kubectl.sh"

prepare = parent.fetch("prepare_release_kubectl")
preflight = parent.fetch("release_builder_preflight")
update = child.fetch("release_and_update_server")
smoke = child.fetch("release_builder_browser_smoke")

abort "prepare job must use the internal kubectl image" unless prepare.dig("image", "name") == image
abort "prepare job must export kubectl" unless prepare.fetch("script").include?("#{helper} export")
abort "prepare job must publish kubectl" unless Array(prepare.dig("artifacts", "paths")).include?(artifact)
abort "preflight must consume kubectl artifact" unless preflight.fetch("needs").any? do |need|
  need["job"] == "prepare_release_kubectl" && need["artifacts"]
end
abort "preflight must install kubectl artifact" unless preflight.fetch("before_script").include?("#{helper} install")
abort "preflight must not download kubectl" if preflight.fetch("before_script").join("\n").include?("dl.k8s.io")
abort "update job must use the internal kubectl image" unless update.dig("image", "name") == image
abort "update job must export kubectl" unless update.fetch("script").include?("#{helper} export")
abort "update job must publish kubectl" unless Array(update.dig("artifacts", "paths")).include?(artifact)
abort "browser smoke must install kubectl artifact" unless smoke.fetch("before_script").include?("#{helper} install")
abort "browser smoke must not download kubectl" if smoke.fetch("before_script").join("\n").include?("dl.k8s.io")
RUBY

source_kubectl="${TMP_DIR}/source-kubectl"
artifact_kubectl="${TMP_DIR}/artifact/kubectl"
installed_kubectl="${TMP_DIR}/installed/kubectl"
printf '#!/usr/bin/env bash\nprintf "test-kubectl\\n"\n' >"$source_kubectl"
chmod 755 "$source_kubectl"

KUBECTL_SOURCE="$source_kubectl" KUBECTL_ARTIFACT="$artifact_kubectl" \
  bash "$HELPER_PATH" export
cmp "$source_kubectl" "$artifact_kubectl"
test -x "$artifact_kubectl"

KUBECTL_ARTIFACT="$artifact_kubectl" KUBECTL_DESTINATION="$installed_kubectl" \
  bash "$HELPER_PATH" install
cmp "$artifact_kubectl" "$installed_kubectl"
test -x "$installed_kubectl"
test "$($installed_kubectl)" = "test-kubectl"

printf 'PASS: internal kubectl artifact contract\n'
