"""Snapshot test for _render_design_doc_markdown.

复用 generator_v2 fixture 产出 markdown 设计文档，任何字节变化都会 FAIL。

更新：UPDATE_SNAPSHOTS=1 pytest tests/test_design_doc_renderer.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest

from app.routes.generation_steps import _render_design_doc_markdown


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "generator_v2"
CONFIG_PATH = FIXTURE_DIR / "sample_config.json"
EXPECTED_MD_PATH = Path(__file__).parent / "fixtures" / "design_doc_renderer" / "expected.md"


def test_design_doc_snapshot():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    data = cfg.get("data", cfg)
    rendered = _render_design_doc_markdown(
        data.get("appName", ""),
        "test_app_code",
        data,
    )

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        EXPECTED_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED_MD_PATH.write_text(rendered, encoding="utf-8")
        pytest.skip("snapshot updated")

    assert EXPECTED_MD_PATH.exists(), (
        f"snapshot missing: {EXPECTED_MD_PATH}. "
        f"run with UPDATE_SNAPSHOTS=1 to create baseline."
    )

    expected = EXPECTED_MD_PATH.read_text(encoding="utf-8")
    assert rendered == expected, "设计文档 markdown 与 snapshot 不一致"
