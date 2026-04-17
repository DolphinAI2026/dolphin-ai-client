"""Baseline snapshot test for generator_v2.run_complete_generation.

目的：锁定 `run_complete_generation` 的两条对外契约——
  1. yielded SSE 事件序列
  2. 对 APaaSClient 的方法调用序列（含参数）

重构拆分时，任何 diff 都会让本测试 FAIL，以此保证"纯搬家、不动行为"。

更新 snapshot：UPDATE_SNAPSHOTS=1 pytest tests/test_generator_v2_events.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest

from app.generator_v2 import run_complete_generation


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "generator_v2"
CONFIG_PATH = FIXTURE_DIR / "sample_config.json"
EXPECTED_EVENTS_PATH = FIXTURE_DIR / "expected_events.json"
EXPECTED_CALLS_PATH = FIXTURE_DIR / "expected_calls.json"


class FakeAPaaSClient:
    """内存态假平台客户端：记录调用 + 返回确定性假数据。"""

    base_url = "https://fake.apaas.local"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._next_id = 1000
        self._roles: list[dict] = []
        self._dicts: list[dict] = []
        self._models: list[dict] = []
        self._forms: list[dict] = []
        self._form_configs: dict[str, dict] = {}  # form_id -> {detailPage: {formComponents: [...]}}

    # ── 内部工具 ─────────────────────────────────────────
    def _new_id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def _record(self, method: str, **args) -> None:
        self.calls.append({"method": method, "args": copy.deepcopy(args)})

    def _get_headers(self, app_id: str | None = None) -> dict:
        # 本 fixture 中 dict.options 为空，不会触发 httpx 直写路径
        return {"fake": "header", "app_id": app_id or ""}

    # ── 角色 ─────────────────────────────────────────────
    async def create_roles(self, app_id: str, payload: list[dict]) -> None:
        self._record("create_roles", app_id=app_id, payload=payload)
        for r in payload:
            self._roles.append({
                "id": self._new_id(),
                "roleCode": r["roleCode"],
                "roleName": r["roleName"],
            })

    async def query_roles(self, app_id: str) -> list[dict]:
        self._record("query_roles", app_id=app_id)
        return copy.deepcopy(self._roles)

    # ── 字典 ─────────────────────────────────────────────
    async def query_dicts(self, app_id: str) -> list[dict]:
        self._record("query_dicts", app_id=app_id)
        return copy.deepcopy(self._dicts)

    async def create_dicts(self, app_id: str, payload: list[dict]) -> None:
        self._record("create_dicts", app_id=app_id, payload=payload)
        for d in payload:
            self._dicts.append({
                "id": self._new_id(),
                "dictionaryCode": d["dictionaryCode"],
                "dictionaryName": d["dictionaryName"],
            })

    async def query_dict_options(self, app_id: str, dict_id: str) -> list[dict]:
        self._record("query_dict_options", app_id=app_id, dict_id=dict_id)
        return []

    # ── 模型 ─────────────────────────────────────────────
    async def query_models(self, app_id: str) -> list[dict]:
        self._record("query_models", app_id=app_id)
        return copy.deepcopy(self._models)

    async def create_models(self, app_id: str, payload: dict) -> None:
        self._record("create_models", app_id=app_id, payload=payload)
        for m in payload.get("dataModels", []):
            self._models.append({
                "modelCode": m["modelCode"],
                "modelName": m["modelName"],
                "fields": [
                    {"fieldName": f["fieldName"], "fieldCode": f["fieldCode"]}
                    for f in m.get("fields", [])
                ],
            })

    # ── 菜单 ─────────────────────────────────────────────
    async def query_menus(self, app_id: str) -> list[dict]:
        self._record("query_menus", app_id=app_id)
        return []

    async def create_menu(self, app_id: str, name: str, form_id: str, menu_order: int = 0) -> dict:
        self._record("create_menu", app_id=app_id, name=name, form_id=form_id, menu_order=menu_order)
        return {"id": self._new_id()}

    # ── 表单 ─────────────────────────────────────────────
    async def create_form_config(self, app_id: str, payload: list[dict]) -> list[dict]:
        self._record("create_form_config", app_id=app_id, payload=payload)
        result = []
        for fc in payload:
            form_id = self._new_id()
            entry = {
                "id": form_id,
                "formName": fc["formName"],
                "formCode": fc["formCode"],
                "menuId": self._new_id(),
            }
            result.append(entry)
            self._forms.append(entry)
            # 存下 formComponents，供 query_form_config 回放
            self._form_configs[form_id] = {
                "detailPage": {
                    "formComponents": copy.deepcopy(fc.get("formComponents", [])),
                },
            }
        return result

    async def query_form_config(self, app_id: str, form_id: str) -> dict:
        self._record("query_form_config", app_id=app_id, form_id=form_id)
        return copy.deepcopy(self._form_configs.get(form_id, {"detailPage": {"formComponents": []}}))

    async def save_form_config(self, app_id: str, form_config: dict) -> None:
        self._record("save_form_config", app_id=app_id, form_config=form_config)

    async def query_detail_page_config(self, app_id: str, form_id: str) -> dict:
        self._record("query_detail_page_config", app_id=app_id, form_id=form_id)
        return {"detailPage": {"formComponents": []}}

    # ── 权限 ─────────────────────────────────────────────
    async def create_form_permissions(self, app_id: str, payload: list[dict]) -> None:
        self._record("create_form_permissions", app_id=app_id, payload=payload)


# ── 测试主体 ─────────────────────────────────────────────

def _run_generation() -> tuple[list[dict], list[dict]]:
    """同步执行 run_complete_generation 并返回 (events, calls)。"""
    client = FakeAPaaSClient()
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    async def _drive() -> list[dict]:
        out: list[dict] = []
        async for evt in run_complete_generation(client, "fake_app_id", config):
            out.append(copy.deepcopy(evt))
        return out

    events = asyncio.run(_drive())
    return events, client.calls


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_events_and_calls_snapshot():
    events, calls = _run_generation()

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        _dump(EXPECTED_EVENTS_PATH, events)
        _dump(EXPECTED_CALLS_PATH, calls)
        pytest.skip("snapshots updated")

    assert EXPECTED_EVENTS_PATH.exists(), (
        f"snapshot missing: {EXPECTED_EVENTS_PATH}. "
        f"run with UPDATE_SNAPSHOTS=1 to create baseline."
    )
    assert EXPECTED_CALLS_PATH.exists(), (
        f"snapshot missing: {EXPECTED_CALLS_PATH}. "
        f"run with UPDATE_SNAPSHOTS=1 to create baseline."
    )

    expected_events = _load(EXPECTED_EVENTS_PATH)
    expected_calls = _load(EXPECTED_CALLS_PATH)

    assert events == expected_events, "SSE 事件序列与 snapshot 不一致"
    assert calls == expected_calls, "APaaSClient 调用序列与 snapshot 不一致"
