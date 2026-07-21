from __future__ import annotations

import json
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
    assert 'RUN test -n "${VITE_BUILD_SHA}" && node_modules/.bin/vite build' in text
