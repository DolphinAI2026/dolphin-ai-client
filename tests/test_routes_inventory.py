"""Snapshot of all FastAPI routes.

用于大文件拆分（如 applications.py 切 4 个 submodule）的保障测试。
任何路由丢失、方法变化、path 变化都会 FAIL。

更新：UPDATE_SNAPSHOTS=1 pytest tests/test_routes_inventory.py
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

from app.main import app


EXPECTED_PATH = Path(__file__).parent / "fixtures" / "routes_inventory.json"


def _collect_routes() -> list[dict]:
    out = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if methods is None:
            continue
        out.append({
            "path": route.path,
            "methods": sorted(methods),
            "name": route.name,
        })
    # 路径 + 方法 稳定排序
    out.sort(key=lambda r: (r["path"], ",".join(r["methods"]), r["name"]))
    return out


def test_routes_inventory_snapshot():
    actual = _collect_routes()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        EXPECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED_PATH.write_text(
            json.dumps(actual, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        pytest.skip("snapshot updated")

    assert EXPECTED_PATH.exists(), (
        f"snapshot missing: {EXPECTED_PATH}. "
        f"run with UPDATE_SNAPSHOTS=1 to create baseline."
    )
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    assert actual == expected, "FastAPI 路由清单与 snapshot 不一致"
