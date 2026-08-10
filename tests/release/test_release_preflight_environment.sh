#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

ruby -ryaml - "${ROOT_DIR}/.gitlab-ci.yml" "${ROOT_DIR}/.gitlab/ci/release-builder-child.yml" <<'RUBY'
parent = YAML.load_file(ARGV.fetch(0))
child = YAML.load_file(ARGV.fetch(1))
expected = "$BUILDER_K8S_EXPECTED_ORIGIN"

preflight = parent.fetch("release_builder_preflight")
smoke = child.fetch("release_builder_browser_smoke")

abort "preflight must map Builder origin" unless preflight.dig("variables", "BUILDER_ORIGIN") == expected
abort "browser smoke must map Builder origin" unless smoke.dig("variables", "BUILDER_ORIGIN") == expected
RUBY

printf 'PASS: release preflight environment contract\n'
