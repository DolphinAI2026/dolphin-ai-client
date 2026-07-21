from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _package(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_root_package_is_only_playwright_owner(repo_root: Path):
    root = _package(repo_root / "package.json")
    frontend = _package(repo_root / "frontend" / "package.json")

    assert root["devDependencies"]["playwright"] == "1.61.1"
    assert "playwright" not in frontend.get("dependencies", {})
    assert "playwright" not in frontend.get("devDependencies", {})


def test_package_locks_match_playwright_ownership(repo_root: Path):
    root_lock = _package(repo_root / "package-lock.json")
    frontend_lock = _package(repo_root / "frontend" / "package-lock.json")

    assert root_lock["packages"][""]["devDependencies"]["playwright"] == "1.61.1"
    assert root_lock["packages"]["node_modules/playwright"]["version"] == "1.61.1"
    assert "playwright" not in frontend_lock["packages"][""].get("dependencies", {})
    assert "playwright" not in frontend_lock["packages"][""].get("devDependencies", {})
    assert "node_modules/playwright" not in frontend_lock["packages"]
    assert "node_modules/playwright-core" not in frontend_lock["packages"]


def test_frontend_index_exposes_exact_build_sha_placeholder(repo_root: Path):
    text = (repo_root / "frontend" / "index.html").read_text(encoding="utf-8")

    assert text.count('name="builder-build-sha"') == 1
    assert '<meta name="builder-build-sha" content="%VITE_BUILD_SHA%">' in text


def test_dockerfile_requires_vite_build_sha(repo_root: Path):
    text = (repo_root / "deploy" / "docker" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "ARG VITE_BUILD_SHA" in text
    assert "ENV VITE_BUILD_SHA=${VITE_BUILD_SHA}" in text
    assert "^[0-9a-f]{40}$" in text
    assert 'node_modules/.bin/vite build' in text


def test_every_dockerfile_caller_passes_full_build_sha(repo_root: Path):
    expected_callers = {
        ".gitlab-ci.yml": "build-arg:VITE_BUILD_SHA=${CI_COMMIT_SHA}",
        "DEPLOY_CONTAINER.md": "--build-arg VITE_BUILD_SHA=${BUILD_SHA}",
        "deploy/customer/deploy.sh": "--build-arg VITE_BUILD_SHA=\\$BUILD_SHA",
        "deploy/docker/docker-compose.yml": "VITE_BUILD_SHA: ${VITE_BUILD_SHA:?",
        "deploy/k8s/README.md": "--build-arg VITE_BUILD_SHA=${BUILD_SHA}",
        "deploy/rancher-single-node/README.md": "--build-arg VITE_BUILD_SHA=${BUILD_SHA}",
        "scripts/deploy_k8s_dev.sh": '--build-arg "VITE_BUILD_SHA=${BUILD_SHA}"',
        "scripts/deploy_k8s_dev_web_terminal.sh": (
            '--build-arg "VITE_BUILD_SHA=${BUILD_SHA}"'
        ),
        "scripts/deploy_login_sync_hotfix.sh": (
            '--build-arg "VITE_BUILD_SHA=${BUILD_SHA}"'
        ),
        "scripts/deploy_online_latest_kubesphere.sh": (
            '--build-arg "VITE_BUILD_SHA=${GIT_FULL_SHA}"'
        ),
        "scripts/deploy_platform_proxy_hotfix.sh": (
            '--build-arg "VITE_BUILD_SHA=${BUILD_SHA}"'
        ),
        "scripts/rebuild_images_dev_main.sh": (
            '--build-arg "VITE_BUILD_SHA=${BUILD_SHA}"'
        ),
    }
    caller_patterns = (
        re.compile(r"-f\s+[^\n]*deploy/docker/Dockerfile"),
        re.compile(r"filename=deploy/docker/Dockerfile"),
        re.compile(r"dockerfile:\s*deploy/docker/Dockerfile"),
    )
    discovered: set[str] = set()
    search_roots = [
        repo_root / ".gitlab-ci.yml",
        repo_root / "DEPLOY_CONTAINER.md",
        repo_root / "deploy",
        repo_root / "scripts",
    ]
    candidates = []
    for root in search_roots:
        candidates.extend([root] if root.is_file() else root.rglob("*"))
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in caller_patterns):
            discovered.add(path.relative_to(repo_root).as_posix())

    assert discovered == set(expected_callers)
    for relative_path, required_text in expected_callers.items():
        text = (repo_root / relative_path).read_text(encoding="utf-8")
        assert required_text in text, relative_path

    compose_env = (
        repo_root / "deploy" / "docker" / "compose.env.example"
    ).read_text(encoding="utf-8")
    assert "VITE_BUILD_SHA=" in compose_env
    assert "40" in compose_env


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/deploy_k8s_dev.sh",
        "scripts/deploy_k8s_dev_web_terminal.sh",
        "scripts/deploy_login_sync_hotfix.sh",
        "scripts/deploy_online_latest_kubesphere.sh",
        "scripts/deploy_platform_proxy_hotfix.sh",
        "scripts/rebuild_images_dev_main.sh",
    ],
)
def test_git_docker_callers_require_clean_build_inputs(
    repo_root: Path,
    relative_path: str,
):
    text = (repo_root / relative_path).read_text(encoding="utf-8")

    assert "assert_clean_build_inputs" in text
    assert "git diff --quiet --cached" in text
    assert "git diff --quiet --" in text
    assert "git ls-files --others --exclude-standard" in text
    assert "rev-parse HEAD" in text


def test_fixture_fails_closed_on_dirty_build_inputs(repo_root: Path):
    text = (
        repo_root / "tests" / "e2e" / "builder-tenant-url-public-uuid-fixture.sh"
    ).read_text(encoding="utf-8")

    assert "assert_clean_build_inputs" in text
    assert "git diff --quiet --cached" in text
    assert "git diff --quiet --" in text
    assert "git ls-files --others --exclude-standard" in text
    for build_input in (
        "frontend",
        "backend",
        "tests/e2e",
        "deploy/docker/Dockerfile",
        "package.json",
        "package-lock.json",
    ):
        assert build_input in text


def test_windows_node_uses_fresh_wslenv_allowlist(repo_root: Path):
    text = (
        repo_root / "tests" / "e2e" / "builder-tenant-url-public-uuid-fixture.sh"
    ).read_text(encoding="utf-8")

    assert 'e2e_wslenv="${WSLENV:-}"' not in text
    assert "${e2e_wslenv:+" not in text
    assert "TASK6_WSLENV_SENTINEL" in text
    assert "TASK6_WSLENV_SENTINEL" not in re.search(
        r'e2e_wslenv="([^"]+)"', text
    ).group(1)
    assert 'WSLENV="" "${WINDOWS_NODE}"' in text


def test_e2e_records_rejected_requests_and_out_of_order_switches(repo_root: Path):
    fixture = (
        repo_root / "tests" / "e2e" / "builder-tenant-url-public-uuid-fixture.sh"
    ).read_text(encoding="utf-8")
    spec = (
        repo_root / "tests" / "e2e" / "builder-tenant-url-public-uuid.spec.mjs"
    ).read_text(encoding="utf-8")

    assert "BUILDER_TARGET_C_TENANT_UUID" in fixture
    assert "DELAY_TENANT_ID" in fixture
    assert '"target_c_tenant_uuid"' in fixture
    assert "page.addInitScript" in spec
    assert "XMLHttpRequest.prototype.open" in spec
    assert "MutationObserver" in spec
    assert "/ai-builder/api/apaas/status" not in spec
    assert "required.targetCTenantId" in spec
    assert "isCandidateTenantMeRequest" in spec
    assert "activationResponses" in spec
    assert "response.status(), 200" in spec
    assert '"${SEED_LOG}"' in fixture
