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


def _has_direct_builder_dockerfile_build(text: str) -> bool:
    normalized = re.sub(r"\\\s*\n\s*", " ", text)
    cli = r"(?:docker|podman|[\"']?\$\{?CONTAINER_CLI\}?[\"']?)"
    file_option = r"(?:-f\s+|--file(?:=|\s+))"
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9_]){cli}\s+(?:buildx\s+)?build\b[^\n]*"
            rf"{file_option}[^\n]*deploy/docker/Dockerfile",
            normalized,
        )
    )


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
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    direct_callers: set[str] = set()
    for raw_relative_path in tracked:
        if not raw_relative_path:
            continue
        relative_path = raw_relative_path.decode()
        if relative_path == "backend/tests/test_tenant_url_build_contract.py":
            continue
        path = repo_root / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "filename=deploy/docker/Dockerfile" in text:
            direct_callers.add(relative_path)
        if _has_direct_builder_dockerfile_build(text):
            direct_callers.add(relative_path)
        if (
            relative_path == "scripts/build_builder_image.sh"
            and "deploy/docker/Dockerfile" in text
        ):
            direct_callers.add(relative_path)

    assert direct_callers == {
        ".gitlab-ci.yml",
        "scripts/build_builder_image.sh",
    }
    ci = (repo_root / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert "build-arg:VITE_BUILD_SHA=${CI_COMMIT_SHA}" in ci


@pytest.mark.parametrize(
    "command",
    [
        "docker build -f deploy/docker/Dockerfile .",
        "docker build --file deploy/docker/Dockerfile .",
        "docker build --file=deploy/docker/Dockerfile .",
        "docker buildx build --file deploy/docker/Dockerfile .",
        "podman build --file=deploy/docker/Dockerfile .",
        '${CONTAINER_CLI} build -f "$ROOT/deploy/docker/Dockerfile" .',
    ],
)
def test_direct_caller_scanner_covers_dockerfile_option_forms(command: str):
    assert _has_direct_builder_dockerfile_build(command)


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


def test_shared_wrapper_builds_from_head_archive_snapshot(repo_root: Path):
    text = (repo_root / "scripts" / "build_builder_image.sh").read_text(
        encoding="utf-8"
    )

    assert "eval" not in text
    assert 'CONTAINER_CLI="${CONTAINER_CLI:-docker}"' in text
    assert 'IMAGE="${IMAGE:-apaas-builder:${IMAGE_TAG:-latest}}"' in text
    assert 'REPO_ROOT="${REPO_ROOT:-' in text
    assert "git -C \"$REPO_ROOT\" rev-parse HEAD" in text
    assert r"^[0-9a-f]{40}$" in text
    assert 'SNAPSHOT_DIR="$(mktemp -d' in text
    assert 'trap cleanup EXIT' in text
    assert 'archive --format=tar "$BUILD_SHA"' in text
    assert 'tar -xf - -C "$SNAPSHOT_DIR"' in text
    assert '[ -f "$SNAPSHOT_DIR/deploy/docker/Dockerfile" ]' in text
    assert '"$SNAPSHOT_DIR"' in text
    assert text.index("rev-parse HEAD") < text.index("archive --format=tar")
    assert text.index("archive --format=tar") < text.index(
        '"$SNAPSHOT_DIR/deploy/docker/Dockerfile"'
    )


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
        ".gitignore",
    ):
        (temp_repo / relative_path).write_text(
            f"tracked fixture: {relative_path}\n",
            encoding="utf-8",
        )
    (temp_repo / ".gitignore").write_text(
        "backend/.pytest_cache/\n",
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
        "if [ \"${1:-}\" = buildx ] && [ \"${2:-}\" = version ]; then\n"
        "  [ \"${FAKE_BUILDX_AVAILABLE:-0}\" = 1 ]\n"
        "  exit\n"
        "fi\n"
        "{ printf '%s\\n' '==='; printf '%s\\n' \"$@\"; } "
        ">> \"$FAKE_CONTAINER_LOG\"\n"
        "if { [ \"${1:-}\" = build ] || "
        "{ [ \"${1:-}\" = buildx ] && [ \"${2:-}\" = build ]; }; }; then\n"
        "  context=\"${!#}\"\n"
        "  printf '%s\\n' \"$context\" > \"$FAKE_CONTEXT_PATH\"\n"
        "  rm -rf \"$FAKE_CONTEXT_COPY\"\n"
        "  mkdir -p \"$FAKE_CONTEXT_COPY\"\n"
        "  cp -a \"$context/.\" \"$FAKE_CONTEXT_COPY/\"\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    return temp_repo, wrapper, fake_cli


def _wrapper_env(
    temp_repo: Path,
    fake_cli: Path,
    tmp_path: Path,
) -> dict[str, str]:
    return {
        **os.environ,
        "REPO_ROOT": str(temp_repo),
        "CONTAINER_CLI": str(fake_cli),
        "FAKE_CONTAINER_LOG": str(tmp_path / "container-cli.log"),
        "FAKE_CONTEXT_PATH": str(tmp_path / "context-path.log"),
        "FAKE_CONTEXT_COPY": str(tmp_path / "context-copy"),
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


def _fake_invocations(path: Path) -> list[list[str]]:
    return [
        block.splitlines()
        for block in path.read_text(encoding="utf-8").split("===\n")
        if block.strip()
    ]


def test_shared_wrapper_excludes_live_dirty_and_ignored_files_from_context(
    repo_root: Path,
    tmp_path: Path,
):
    temp_repo, wrapper, fake_cli = _init_wrapper_repo(repo_root, tmp_path)
    (temp_repo / "frontend/source.txt").write_text(
        "staged live content\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "add", "frontend/source.txt"], cwd=temp_repo, check=True
    )
    (temp_repo / "backend/source.txt").write_text(
        "unstaged live content\n", encoding="utf-8"
    )
    (temp_repo / "deploy/docker/untracked.txt").write_text(
        "untracked live content\n", encoding="utf-8"
    )
    ignored = temp_repo / "backend/.pytest_cache/sentinel.txt"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("ignored but Docker-included\n", encoding="utf-8")

    env = _wrapper_env(temp_repo, fake_cli, tmp_path)
    result = subprocess.run(
        [str(wrapper)],
        cwd=temp_repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    context_copy = Path(env["FAKE_CONTEXT_COPY"])
    assert (context_copy / "frontend/source.txt").read_text(
        encoding="utf-8"
    ) == "tracked fixture: frontend/source.txt\n"
    assert (context_copy / "backend/source.txt").read_text(
        encoding="utf-8"
    ) == "tracked fixture: backend/source.txt\n"
    assert (context_copy / "deploy/docker/Dockerfile").is_file()
    assert not (context_copy / "deploy/docker/untracked.txt").exists()
    assert not (context_copy / "backend/.pytest_cache/sentinel.txt").exists()

    snapshot_context = Path(
        Path(env["FAKE_CONTEXT_PATH"]).read_text(encoding="utf-8").strip()
    )
    assert temp_repo not in snapshot_context.parents
    assert not snapshot_context.exists()


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
    env = _wrapper_env(temp_repo, fake_cli, tmp_path)

    result = subprocess.run(
        [str(wrapper)],
        cwd=temp_repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    snapshot_context = Path(
        Path(env["FAKE_CONTEXT_PATH"]).read_text(encoding="utf-8").strip()
    )
    assert _fake_invocations(call_log) == [[
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
        str(snapshot_context / "deploy/docker/Dockerfile"),
        "-t",
        "registry.example.invalid/builder:contract",
        str(snapshot_context),
    ]]
    assert not snapshot_context.exists()


@pytest.mark.parametrize(
    ("buildx_available", "expected_prefixes"),
    [
        (True, [("buildx", "build")]),
        (False, [("build",), ("push",)]),
    ],
)
def test_shared_wrapper_push_modes(
    repo_root: Path,
    tmp_path: Path,
    buildx_available: bool,
    expected_prefixes: list[tuple[str, ...]],
):
    temp_repo, wrapper, fake_cli = _init_wrapper_repo(repo_root, tmp_path)
    env = _wrapper_env(temp_repo, fake_cli, tmp_path)
    env["PUSH"] = "1"
    env["FAKE_BUILDX_AVAILABLE"] = "1" if buildx_available else "0"

    result = subprocess.run(
        [str(wrapper)],
        cwd=temp_repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    invocations = _fake_invocations(Path(env["FAKE_CONTAINER_LOG"]))
    assert [tuple(call[: len(prefix)]) for call, prefix in zip(
        invocations, expected_prefixes, strict=True
    )] == expected_prefixes
    if buildx_available:
        assert "--push" in invocations[0]
    else:
        assert invocations[1] == [
            "push",
            "registry.example.invalid/builder:contract",
        ]


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/deploy_k8s_dev.sh",
        "scripts/deploy_k8s_dev_web_terminal.sh",
        "scripts/deploy_login_sync_hotfix.sh",
        "scripts/deploy_platform_proxy_hotfix.sh",
        "scripts/rebuild_images_dev_main.sh",
    ],
)
def test_git_docker_callers_delegate_to_snapshot_wrapper(
    repo_root: Path,
    relative_path: str,
):
    text = (repo_root / relative_path).read_text(encoding="utf-8")

    assert "build_builder_image.sh" in text
    assert "PUSH=1" in text
    assert "assert_clean_build_inputs" not in text
    assert "deploy/docker/Dockerfile" not in text
    assert not _has_direct_builder_dockerfile_build(text)
    if relative_path == "scripts/deploy_online_latest_kubesphere.sh":
        assert 'REPO_ROOT="$WORKDIR"' in text
        assert '"$WORKDIR/scripts/build_builder_image.sh"' in text
    else:
        assert 'REPO_ROOT="$REPO_ROOT"' in text
        assert '"$REPO_ROOT/scripts/build_builder_image.sh"' in text


def test_online_git_caller_uses_immutable_cli_branches(repo_root: Path):
    text = (
        repo_root / "scripts" / "deploy_online_latest_kubesphere.sh"
    ).read_text(encoding="utf-8")

    assert 'REPO_ROOT="$WORKDIR"' in text
    assert '"$WORKDIR/scripts/build_builder_image.sh"' in text
    assert 'podman) build_push=0 ;;' in text
    assert re.search(
        r"docker\)\s+verify_docker_digest_capability\s+build_push=1\s+;;",
        text,
    )
    assert 'PUSH="$build_push"' in text
    assert 'push --digestfile "$digest_file" "$image_tag_ref"' in text
    assert "verify_source_provenance" in text
    assert "verify_docker_digest_capability" in text
    assert text.index("verify_source_provenance") < text.index("build_and_push_image")
    assert text.index("verify_docker_digest_capability") < text.index(
        '"$WORKDIR/scripts/build_builder_image.sh"'
    )
    assert "git clone --depth" not in text


def test_online_release_is_existing_workload_image_only(repo_root: Path):
    text = (
        repo_root / "scripts" / "deploy_online_latest_kubesphere.sh"
    ).read_text(encoding="utf-8")

    assert "first installation requires bootstrap" in text
    assert "run_release_builder_prebuild_preflight" in text
    assert "acquire_release_lock" in text
    assert "recover_failed_release" in text
    assert "rollback CAS rejected" in text
    assert "kubectl set image" not in text
    assert "patch_statefulset_images_cas" in text
    assert "fence_statefulset_for_generation" in text
    assert "/metadata/annotations/builder.ai~1release-generation" in text
    assert "/spec/template/spec/containers/%s/name" in text
    assert "/spec/template/spec/containers/%s/image" in text
    assert "/spec/template/spec/initContainers/%s/name" in text
    assert "/spec/template/spec/initContainers/%s/image" in text
    main_text = text[text.index("main() {") :]
    assert main_text.index("run_release_builder_prebuild_preflight") < main_text.index(
        "docker_login_if_requested"
    )
    assert main_text.index("acquire_release_lock") < main_text.index(
        'set_release_images "$PREVIOUS_BACKEND_IMAGE"'
    )
    for forbidden in (
        "kubectl apply",
        "create namespace",
        "apply_namespace",
        "apply_nginx_config",
        "ensure_dev_secret",
        "apply_workloads",
        "cleanup_fresh_workload",
        "delete ingress",
        "delete service",
    ):
        assert forbidden not in text


def test_rebuild_script_invokes_wrapper_for_dev_and_main(repo_root: Path):
    text = (repo_root / "scripts" / "rebuild_images_dev_main.sh").read_text(
        encoding="utf-8"
    )

    assert 'build_image "$DEV_TAG" "$DEV_MCP_PUBLIC_BASE"' in text
    assert 'build_image "$MAIN_TAG" "$MAIN_MCP_PUBLIC_BASE"' in text


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
