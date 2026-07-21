from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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


def test_direct_dockerfile_callers_are_provenance_safe(repo_root: Path):
    expected_callers = {
        ".gitlab-ci.yml": "build-arg:VITE_BUILD_SHA=${CI_COMMIT_SHA}",
        "scripts/build_builder_image.sh": (
            '--build-arg "VITE_BUILD_SHA=${BUILD_SHA}"'
        ),
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


def test_manual_build_paths_use_shared_wrapper(repo_root: Path):
    wrapper_reference = "scripts/build_builder_image.sh"
    for relative_path in (
        "DEPLOY_CONTAINER.md",
        "deploy/k8s/README.md",
        "deploy/rancher-single-node/README.md",
        "deploy/customer/deploy.sh",
    ):
        text = (repo_root / relative_path).read_text(encoding="utf-8")
        assert wrapper_reference in text, relative_path
        assert "BUILD_SHA=$(git rev-parse HEAD)" not in text, relative_path
        assert "BUILD_SHA=\\$(git rev-parse HEAD)" not in text, relative_path
        assert "-f deploy/docker/Dockerfile" not in text, relative_path

    container_doc = (repo_root / "DEPLOY_CONTAINER.md").read_text(
        encoding="utf-8"
    )
    k8s_doc = (repo_root / "deploy" / "k8s" / "README.md").read_text(
        encoding="utf-8"
    )
    assert "docker compose build" not in container_doc
    assert "docker build --platform linux/amd64" not in container_doc
    assert "podman build --layers" not in container_doc
    assert "docker build --platform linux/amd64" not in k8s_doc


def test_compose_uses_prebuilt_image_only(repo_root: Path):
    compose = (
        repo_root / "deploy" / "docker" / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    compose_env = (
        repo_root / "deploy" / "docker" / "compose.env.example"
    ).read_text(encoding="utf-8")

    assert not re.search(r"(?m)^\s+build:\s*$", compose)
    assert "dockerfile:" not in compose
    assert "VITE_BUILD_SHA" not in compose
    assert "VITE_BUILD_SHA" not in compose_env


def test_shared_wrapper_gates_inputs_before_reading_head(repo_root: Path):
    text = (repo_root / "scripts" / "build_builder_image.sh").read_text(
        encoding="utf-8"
    )

    assert "eval" not in text
    assert 'CONTAINER_CLI="${CONTAINER_CLI:-docker}"' in text
    assert 'IMAGE="${IMAGE:-apaas-builder:${IMAGE_TAG:-latest}}"' in text
    for build_input in (
        "frontend",
        "backend",
        "admin-spa",
        "deploy/docker",
        ".dockerignore",
    ):
        assert build_input in text
    assert "git diff --quiet --cached" in text
    assert "git diff --quiet --" in text
    assert "git ls-files --others --exclude-standard" in text
    assert re.search(
        r"assert_clean_build_inputs\s*\n"
        r"\s*BUILD_SHA=.*git .*rev-parse HEAD",
        text,
    )
    assert r"^[0-9a-f]{40}$" in text


def _init_wrapper_repo(repo_root: Path, tmp_path: Path) -> tuple[Path, Path, Path]:
    temp_repo = tmp_path / "repo"
    temp_repo.mkdir()
    for directory in (
        "frontend",
        "backend",
        "admin-spa",
        "deploy/docker",
        "scripts",
    ):
        (temp_repo / directory).mkdir(parents=True, exist_ok=True)
    for relative_path in (
        "frontend/source.txt",
        "backend/source.txt",
        "admin-spa/source.txt",
        "deploy/docker/Dockerfile",
        "deploy/docker/runtime.txt",
        ".dockerignore",
    ):
        (temp_repo / relative_path).write_text(
            f"tracked fixture: {relative_path}\n",
            encoding="utf-8",
        )

    wrapper = temp_repo / "scripts" / "build_builder_image.sh"
    shutil.copy2(repo_root / "scripts" / "build_builder_image.sh", wrapper)
    wrapper.chmod(0o755)

    subprocess.run(["git", "init", "-q"], cwd=temp_repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "task6@example.invalid"],
        cwd=temp_repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Task 6 Contract"],
        cwd=temp_repo,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=temp_repo, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "fixture"], cwd=temp_repo, check=True
    )

    fake_cli = tmp_path / "fake-container"
    fake_cli.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$@\" > \"$FAKE_CONTAINER_LOG\"\n",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    return temp_repo, wrapper, fake_cli


@pytest.mark.parametrize(
    ("dirty_kind", "relative_path"),
    [
        ("staged", "frontend/source.txt"),
        ("unstaged", "backend/source.txt"),
        ("untracked", "deploy/docker/untracked.txt"),
    ],
)
def test_shared_wrapper_fails_closed_before_container_cli(
    repo_root: Path,
    tmp_path: Path,
    dirty_kind: str,
    relative_path: str,
):
    temp_repo, wrapper, fake_cli = _init_wrapper_repo(repo_root, tmp_path)
    dirty_path = temp_repo / relative_path
    if dirty_kind == "untracked":
        dirty_path.write_text("untracked Docker input\n", encoding="utf-8")
    else:
        dirty_path.write_text("dirty Docker input\n", encoding="utf-8")
        if dirty_kind == "staged":
            subprocess.run(
                ["git", "add", relative_path], cwd=temp_repo, check=True
            )

    call_log = tmp_path / "container-cli.log"
    result = subprocess.run(
        [str(wrapper)],
        cwd=temp_repo,
        env={
            **os.environ,
            "CONTAINER_CLI": str(fake_cli),
            "FAKE_CONTAINER_LOG": str(call_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Docker build inputs are dirty" in result.stderr
    assert not call_log.exists()


def test_shared_wrapper_clean_path_passes_full_sha_and_build_args(
    repo_root: Path,
    tmp_path: Path,
):
    temp_repo, wrapper, fake_cli = _init_wrapper_repo(repo_root, tmp_path)
    call_log = tmp_path / "container-cli.log"
    expected_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=temp_repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    env = {
        **os.environ,
        "CONTAINER_CLI": str(fake_cli),
        "FAKE_CONTAINER_LOG": str(call_log),
        "IMAGE": "registry.example.invalid/builder:contract",
        "PLATFORM": "linux/arm64",
        "VITE_BASE_URL": "/builder/",
        "VITE_ADMIN_BASE": "/builder/admin/",
        "VITE_API_BASE_URL": "/builder/api",
        "VITE_MCP_PUBLIC_BASE": "https://builder.example.invalid",
        "NODE_IMAGE": "registry.example.invalid/node:20",
        "JDK8_IMAGE": "registry.example.invalid/jdk:8",
        "JDK17_IMAGE": "registry.example.invalid/jdk:17",
        "MAVEN_IMAGE": "registry.example.invalid/maven:3",
        "PYTHON_IMAGE": "registry.example.invalid/python:3.12",
        "DOCKER_CLI_IMAGE": "registry.example.invalid/docker:24",
        "NPM_REGISTRY": "https://npm.example.invalid",
        "PIP_INDEX_URL": "https://pypi.example.invalid/simple",
    }

    result = subprocess.run(
        [str(wrapper)],
        cwd=temp_repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "build",
        "--platform",
        "linux/arm64",
        "--build-arg",
        "VITE_BASE_URL=/builder/",
        "--build-arg",
        f"VITE_BUILD_SHA={expected_sha}",
        "--build-arg",
        "VITE_ADMIN_BASE=/builder/admin/",
        "--build-arg",
        "VITE_API_BASE_URL=/builder/api",
        "--build-arg",
        "VITE_MCP_PUBLIC_BASE=https://builder.example.invalid",
        "--build-arg",
        "NODE_IMAGE=registry.example.invalid/node:20",
        "--build-arg",
        "JDK8_IMAGE=registry.example.invalid/jdk:8",
        "--build-arg",
        "JDK17_IMAGE=registry.example.invalid/jdk:17",
        "--build-arg",
        "MAVEN_IMAGE=registry.example.invalid/maven:3",
        "--build-arg",
        "PYTHON_IMAGE=registry.example.invalid/python:3.12",
        "--build-arg",
        "DOCKER_CLI_IMAGE=registry.example.invalid/docker:24",
        "--build-arg",
        "NPM_REGISTRY=https://npm.example.invalid",
        "--build-arg",
        "PIP_INDEX_URL=https://pypi.example.invalid/simple",
        "-f",
        str(temp_repo / "deploy/docker/Dockerfile"),
        "-t",
        "registry.example.invalid/builder:contract",
        str(temp_repo),
    ]


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
