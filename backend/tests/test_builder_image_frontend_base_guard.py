import os
import subprocess
from pathlib import Path


REVISION = "2aa07a75c2800d99963c97032bbc110b65dfcdcc"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_guard(tmp_path: Path, html: str) -> subprocess.CompletedProcess[str]:
    html_path = tmp_path / "index.html"
    html_path.write_text(html, encoding="utf-8")

    fake_cli = tmp_path / "container-cli"
    fake_cli.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  pull) exit 0 ;;
  run) cat "$FAKE_INDEX_HTML" ;;
  *) exit 64 ;;
esac
""",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "BUILDER_IMAGE": "registry.example/ai-builder@sha256:" + "a" * 64,
            "CONTAINER_CLI": str(fake_cli),
            "EXPECTED_BASE_URL": "/ai-builder/",
            "EXPECTED_BUILD_SHA": REVISION,
            "FAKE_INDEX_HTML": str(html_path),
        }
    )
    return subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/verify_builder_image_frontend_base.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _index_html(base_url: str, revision: str = REVISION) -> str:
    return f"""<!doctype html>
<html><head>
<meta name="builder-build-sha" content="{revision}">
<script type="module" src="{base_url}assets/index.js"></script>
<link rel="stylesheet" href="{base_url}assets/index.css">
</head></html>
"""


def test_accepts_matching_frontend_base_and_revision(tmp_path: Path):
    result = _run_guard(tmp_path, _index_html("/ai-builder/"))

    assert result.returncode == 0, result.stderr
    assert "[builder-image-contract][ok]" in result.stdout


def test_rejects_standalone_image_for_full_workspace(tmp_path: Path):
    result = _run_guard(tmp_path, _index_html("/builder-standalone/"))

    assert result.returncode != 0
    assert "does not use /ai-builder/assets/" in result.stderr


def test_rejects_image_built_from_another_revision(tmp_path: Path):
    result = _run_guard(tmp_path, _index_html("/ai-builder/", "b" * 40))

    assert result.returncode != 0
    assert "frontend build SHA does not match" in result.stderr
