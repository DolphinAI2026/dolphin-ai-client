# add_apaas_field_to_form 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一个 MCP 工具 `add_apaas_field_to_form`,一步做完「给模型加字段 + 把字段铺到表单详情页(可选上列表页)」,根治「对话加字段只建了模型、没出现在表单上」。

**Architecture:** 核心逻辑抽成接收 `client` 首参的纯函数 `_add_field_to_form_core`(镜像 `operations/form_name_repair.repair_form_menu_names` 范式,可直接喂 fake client 单测);薄 `@mcp.tool()` 包装 `add_apaas_field_to_form` 经 `_with_client` 调它(拿 client + 401 relogin)。复用现成件:`_build_basic_component_from_model_field`(组件类型自动推导)、`_save_form_config_with_retry`(乐观锁重试)、`is_apaas_token_error`(token 错误识别)、`_invalidate_section_cache_after_write`(缓存失效)。整段操作幂等可重跑;token 错误一律 raise 交上层 relogin 重试。

**Tech Stack:** Python 3.13 / FastMCP / pytest / asyncio。后端在 `backend/`,测试在 `backend/tests/`。

---

## File Structure

- **Modify** `backend/app/mcp_tools/apaas_form_tools.py` — 加 `_is_dup_field_error` 助手 + `_add_field_to_form_core` 核心 + `add_apaas_field_to_form` 工具 + register() tools 列表加一项。
- **Modify** `backend/tool_registry.yaml` — 加 `add_apaas_field_to_form` 条目。
- **Modify** `backend/tests/test_tool_registry.py` — `_EXPECTED_CONFIG_WHITELIST` 加工具名(否则 config 白名单 byte-equal 测试拦)。
- **Create** `backend/tests/test_add_field_to_form.py` — 核心单测(fake client)。

复用件(只读,不改):
- `backend/app/mcp_tools/apaas_form_tools.py:1338` `_build_basic_component_from_model_field`
- `backend/app/mcp_tools/apaas_form_tools.py:1323` `_component_type_from_model_field`
- `backend/app/mcp_tools/apaas_form_tools.py:615` `_invalidate_section_cache_after_write`
- `backend/app/operations/form_config.py:300` `_save_form_config_with_retry`
- `backend/app/error_messages.py:62` `is_apaas_token_error`(markers 含 "401"/"Unauthorized"/"Token已过期")

---

## Task 1: 核心单测(red)

**Files:**
- Create: `backend/tests/test_add_field_to_form.py`

- [ ] **Step 1: 写失败测试(完整文件)**

```python
"""TDD for app.mcp_tools.apaas_form_tools._add_field_to_form_core

根因: aPaaS 模型字段与表单 formComponents 两套独立, add_apaas_model_field 只到模型层,
缺增量铺表单工具 → 对话加字段只建了模型、没出现在表单上。本核心函数一步做完
「加模型字段(若不存在) + 把字段作为组件追加到表单详情页(可选上列表页)」。

设计见 docs/superpowers/specs/2026-06-18-add-field-to-form-design.md。
"""
from __future__ import annotations

import asyncio
import copy

import pytest

from app.mcp_tools.apaas_form_tools import _add_field_to_form_core


class FakeClient:
    """假 apaas client: 持有一份 form_config + 记录 add_model_field 调用, 可注入错误。"""

    def __init__(self, form_config=None, add_field_error=None, save_error=None):
        self._form_config = form_config if form_config is not None else {"detailPage": {"formComponents": []}}
        self._add_field_error = add_field_error
        self._save_error = save_error
        self.add_model_field_calls = []
        self.saved_config = None

    async def add_model_field(self, app_id, model_id, model_code, field_code, field_name,
                              field_type="STRING", max_length=255, comment="", **kw):
        self.add_model_field_calls.append({
            "model_code": model_code, "field_code": field_code,
            "field_name": field_name, "field_type": field_type,
        })
        if self._add_field_error is not None:
            raise self._add_field_error
        return {"code": "ok"}

    async def query_form_config(self, app_id, form_id):
        return copy.deepcopy(self._form_config)

    async def save_form_config(self, app_id, form_config):
        if self._save_error is not None:
            raise self._save_error
        self.saved_config = form_config
        return {"code": "ok"}


def _run(coro):
    return asyncio.run(coro)


def _kw(**over):
    base = dict(apaas_app_id="app1", model_id="m1", model_code="customer",
                field_code="phone", field_name="手机号", field_type="STRING",
                max_length=20, comment="", form_id="f1", show_in_list=False)
    base.update(over)
    return base


def test_new_field_added_to_model_and_form():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is True and not res.get("skipped")
    assert client.add_model_field_calls == [
        {"model_code": "customer", "field_code": "phone", "field_name": "手机号", "field_type": "STRING"}
    ]
    comps = client.saved_config["detailPage"]["formComponents"]
    assert any(c["modelField"] == "customer.phone" for c in comps)
    assert "customer" in client.saved_config["allModelCodes"]


def test_component_type_derived_from_field_type():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw(field_code="amount", field_name="金额", field_type="NUM")))
    assert res["component_type"] == "FORM_NUMBER_INPUT"
    comps = client.saved_config["detailPage"]["formComponents"]
    assert any(c["modelField"] == "customer.amount" and c["componentType"] == "FORM_NUMBER_INPUT" for c in comps)


def test_idempotent_when_field_already_on_form():
    preset = {"detailPage": {"formComponents": [
        {"componentType": "FORM_TEXT_INPUT", "modelField": "customer.phone", "label": "手机号"}
    ]}}
    client = FakeClient(preset)
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is True and res["skipped"] is True
    assert res["reason"] == "FIELD_ALREADY_ON_FORM"
    assert client.saved_config is None


def test_tolerates_field_already_on_model():
    client = FakeClient({"detailPage": {"formComponents": []}}, add_field_error=Exception("字段编码已存在"))
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is True
    comps = client.saved_config["detailPage"]["formComponents"]
    assert any(c["modelField"] == "customer.phone" for c in comps)


def test_add_field_real_failure_aborts_before_form():
    client = FakeClient({"detailPage": {"formComponents": []}}, add_field_error=Exception("模型不存在"))
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is False and res["error_code"] == "ADD_FIELD_FAILED"
    assert client.saved_config is None


def test_token_error_on_add_propagates():
    client = FakeClient({"detailPage": {"formComponents": []}},
                        add_field_error=Exception("Client error 401 token 失效"))
    with pytest.raises(Exception) as ei:
        _run(_add_field_to_form_core(client, **_kw()))
    assert "401" in str(ei.value)


def test_show_in_list_adds_to_query_list():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw(show_in_list=True)))
    assert res["ok"] is True and res["show_in_list"] is True
    ql = client.saved_config["detailPage"]["listPageView"]["queryList"]
    assert "customer.phone" in ql


def test_default_does_not_touch_query_list():
    client = FakeClient({"detailPage": {"formComponents": []}})
    _run(_add_field_to_form_core(client, **_kw(show_in_list=False)))
    detail = client.saved_config["detailPage"]
    assert "customer.phone" not in (detail.get("listPageView", {}).get("queryList", []))


def test_partial_failure_when_form_save_fails():
    client = FakeClient({"detailPage": {"formComponents": []}}, save_error=Exception("平台拒绝保存表单"))
    res = _run(_add_field_to_form_core(client, **_kw()))
    assert res["ok"] is False and res["error_code"] == "FORM_SAVE_FAILED"
    assert res["field_on_model"] is True and res["field_on_form"] is False
    assert len(client.add_model_field_calls) == 1


def test_reserved_field_code_rejected_before_client():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw(field_code="approval_status")))
    assert res["ok"] is False and res["error_code"] == "RESERVED_FIELD_CODE"
    assert client.add_model_field_calls == []


def test_missing_required_params_rejected():
    client = FakeClient({"detailPage": {"formComponents": []}})
    res = _run(_add_field_to_form_core(client, **_kw(form_id="")))
    assert res["ok"] is False and res["error_code"] == "INVALID_PARAMS"
    assert client.add_model_field_calls == []
```

- [ ] **Step 2: 跑测试确认全红(函数未定义)**

Run: `cd backend && python -m pytest tests/test_add_field_to_form.py -v`
Expected: 全部 FAIL/ERROR — `ImportError: cannot import name '_add_field_to_form_core'`。

---

## Task 2: 核心实现(green)

**Files:**
- Modify: `backend/app/mcp_tools/apaas_form_tools.py`(在 `_pick_main_model` 之后、`register` 之前,即第 1375 行附近插入)

- [ ] **Step 1: 加 `_is_dup_field_error` 助手 + `_add_field_to_form_core` 核心**

在 `backend/app/mcp_tools/apaas_form_tools.py` 的 `_pick_main_model(...)` 函数定义结束之后(约 1375 行)、`def register(` 之前,插入:

```python
def _is_dup_field_error(exc: Exception) -> bool:
    """字段已存在类业务错误 — 用于合并工具容忍 re-run / 「字段已在模型」场景。

    token 错误(401/登录失效)不含这些 marker → 不会被误判为 dup → 由调用方先行 raise 走 relogin。
    """
    raw = str(exc)
    if any(m in raw for m in ("已存在", "重复", "已被使用")):
        return True
    low = raw.lower()
    return "duplicate" in low or "already exist" in low


async def _add_field_to_form_core(
    client,
    *,
    apaas_app_id: str,
    model_id: str,
    model_code: str,
    field_code: str,
    field_name: str,
    field_type: str = "STRING",
    max_length: int = 255,
    comment: str = "",
    form_id: str = "",
    show_in_list: bool = False,
) -> dict:
    """给模型加字段(若不存在)并把字段铺到表单详情页(可选上列表页)。

    接收 client 作首参 → 可直接喂 fake client 单测(镜像 repair_form_menu_names 范式)。
    token 错误一律 raise 交上层 call_apaas_with_relogin 重试;整段操作幂等可重跑。
    """
    from app.error_messages import is_apaas_token_error

    # ── 入参 + 保留字校验(不碰 client)──
    if not (apaas_app_id.strip() and model_id.strip() and model_code.strip()
            and field_code.strip() and field_name.strip() and form_id.strip()):
        return {"ok": False, "error_code": "INVALID_PARAMS",
                "message": "apaas_app_id/model_id/model_code/field_code/field_name/form_id 都必填"}
    fc = field_code.strip().lower()
    if fc in {"approver_id", "id", "tenant_id"} or fc.startswith("approval_"):
        return {"ok": False, "error_code": "RESERVED_FIELD_CODE",
                "message": f"field_code '{field_code}' 命中 apaas 保留字 — 建议改成 {model_code}_{field_code}"}

    aid = apaas_app_id.strip()
    mcode = model_code.strip()
    fcode = field_code.strip()
    target = f"{mcode}.{fcode}"

    # ── 1. 加模型字段(容忍已存在;token 错 / 真失败照常处理)──
    try:
        await client.add_model_field(aid, model_id.strip(), mcode, fcode, field_name.strip(),
                                     field_type=field_type, max_length=max_length, comment=comment)
    except Exception as exc:
        if is_apaas_token_error(str(exc)):
            raise
        if not _is_dup_field_error(exc):
            return {"ok": False, "error_code": "ADD_FIELD_FAILED",
                    "message": f"给模型 {mcode} 加字段「{field_name}」失败：{exc}"}
        logger.info("add_apaas_field_to_form: 字段 %s 已在模型上, 跳过建字段直接铺表单", target)

    # ── 2. 构造组件(类型自动推导, 复用现成构造器)──
    field = {
        "field_code": fcode,
        "field_name": field_name.strip(),
        "data_type": field_type,
        "max_length": max_length,
        "dictionary_code": "",
        "required": False,
    }
    component = _build_basic_component_from_model_field(field, mcode)

    def _apply_append(cfg: dict) -> None:
        detail = cfg.setdefault("detailPage", {})
        comps = detail.setdefault("formComponents", [])
        if not any(isinstance(c, dict) and str(c.get("modelField") or "") == target for c in comps):
            comps.append(component)
        amc = cfg.get("allModelCodes")
        if not isinstance(amc, list):
            amc = []
            cfg["allModelCodes"] = amc
        if mcode not in amc:
            amc.append(mcode)
        if show_in_list:
            ql = detail.setdefault("listPageView", {}).setdefault("queryList", [])
            if target not in ql:
                ql.append(target)

    # ── 3. 读表单 → 幂等短路 → 追加 → 存回(乐观锁重试)──
    form_config = await client.query_form_config(aid, form_id.strip())
    existing = (form_config.get("detailPage") or {}).get("formComponents") or []
    if any(isinstance(c, dict) and str(c.get("modelField") or "") == target for c in existing):
        return {"ok": True, "skipped": True, "reason": "FIELD_ALREADY_ON_FORM",
                "form_id": form_id, "model_field": target,
                "message": f"字段「{field_name}」已在表单上, 未重复添加。"}

    _apply_append(form_config)

    from app.operations.form_config import _save_form_config_with_retry
    try:
        await _save_form_config_with_retry(client, aid, form_config,
                                           form_id=form_id.strip(), apply_latest=_apply_append,
                                           reason="对话加字段铺表单")
    except Exception as exc:
        if is_apaas_token_error(str(exc)):
            raise
        return {"ok": False, "error_code": "FORM_SAVE_FAILED",
                "message": f"字段「{field_name}」已加到模型 {mcode}, 但铺到表单失败：{exc}",
                "field_on_model": True, "field_on_form": False}

    return {"ok": True, "form_id": form_id, "model_code": mcode, "field_code": fcode,
            "model_field": target, "component_type": component["componentType"],
            "show_in_list": show_in_list,
            "message": f"字段「{field_name}」({fcode}) 已加到模型「{mcode}」并铺到表单。",
            "next_step": "调 republish_apaas_app 让模型变更生效; 刷新表单设计器查看新字段。"}
```

- [ ] **Step 2: 跑测试确认全绿**

Run: `cd backend && python -m pytest tests/test_add_field_to_form.py -v`
Expected: 11 passed。

- [ ] **Step 3: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/tests/test_add_field_to_form.py backend/app/mcp_tools/apaas_form_tools.py
git commit -m "feat(apaas): _add_field_to_form_core — 加模型字段并铺到表单核心 + 单测

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: MCP 工具包装 + 注册

**Files:**
- Modify: `backend/app/mcp_tools/apaas_form_tools.py`(紧接 `_add_field_to_form_core` 之后加 `@mcp.tool()` 包装;再改 `register()` 的 `tools` 列表)

- [ ] **Step 1: 加 `@mcp.tool()` 包装函数**

在 `_add_field_to_form_core(...)` 定义结束之后、`def register(` 之前,插入:

```python
@mcp.tool()
async def add_apaas_field_to_form(
    env_id: int, apaas_app_id: str, model_id: str, model_code: str,
    field_code: str, field_name: str,
    field_type: str = "STRING", max_length: int = 255, comment: str = "",
    form_id: str = "", show_in_list: bool = False,
) -> dict:
    """给模型加一个字段并直接铺到表单(详情页, 可选上列表页) — 一步到位。

    解决「对话加字段只建了模型、没出现在表单上」: 本工具内部先给模型加字段
    (若已存在则跳过建字段), 再把该字段作为组件追加到指定表单的详情页。
    show_in_list=True 时字段也加进列表页的列(queryList)。

    field_type 常用: STRING / NUM / DATE / DATETIME / BOOLEAN / TEXT / BIG_TEXT。
    form_id 先 list_apaas_app_menus(menu_type_filter=MODEL) 拿。
    下拉字段建完后再调 bind_apaas_form_field_to_dict 绑字典。
    """
    ok, raw = await _with_client(
        env_id, "加字段并铺到表单",
        lambda c: _add_field_to_form_core(
            c, apaas_app_id=apaas_app_id, model_id=model_id, model_code=model_code,
            field_code=field_code, field_name=field_name, field_type=field_type,
            max_length=max_length, comment=comment, form_id=form_id, show_in_list=show_in_list))
    if not ok:
        return raw
    if isinstance(raw, dict) and raw.get("ok"):
        _invalidate_section_cache_after_write(apaas_app_id)
    return raw
```

> ⚠️ docstring 必须是纯字面量(FastMCP 靠它生成工具描述;拼接 → `__doc__=None` → 描述空)。

- [ ] **Step 2: 把工具加进 `register()` 的 `tools` 列表**

在 `backend/app/mcp_tools/apaas_form_tools.py` 的 `register()` 里,`tools = [...]` 列表(约 1391–1401 行)末尾 `set_apaas_app_access,` 之后加一行:

找到:
```python
        set_apaas_form_permissions,
        set_apaas_app_access,
    ]
```
改成:
```python
        set_apaas_form_permissions,
        set_apaas_app_access,
        add_apaas_field_to_form,
    ]
```

- [ ] **Step 3: 导入冒烟 + 工具注册自检**

Run:
```bash
cd backend && python -c "
import asyncio
from app.mcp_tools import apaas_form_tools as m

class _MCP:
    def tool(self):
        def d(fn): return fn
        return d

reg = m.register(_MCP(), with_client=lambda *a, **k: None, list_app_menus=None, list_app_models=None)
assert 'add_apaas_field_to_form' in reg, reg.keys()
print('OK registered:', 'add_apaas_field_to_form' in reg)
"
```
Expected: `OK registered: True`(无 import 错)。

- [ ] **Step 4: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/app/mcp_tools/apaas_form_tools.py
git commit -m "feat(apaas): add_apaas_field_to_form MCP 工具 + 注册

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: tool_registry.yaml 条目 + 白名单同步

**Files:**
- Modify: `backend/tool_registry.yaml`
- Modify: `backend/tests/test_tool_registry.py`

- [ ] **Step 1: 加 registry 条目**

在 `backend/tool_registry.yaml` 里找到 `add_apaas_model_field:` 那一条(第 26 行附近):
```yaml
  add_apaas_model_field:
    sections: [data]
    agents: [builder, config]
    category: update
    description: "给已有模型加一个字段。"
```
在它**之前**插入新条目:
```yaml
  add_apaas_field_to_form:
    sections: [data, ui]
    agents: [builder, config]
    category: update
    description: "给模型加字段并直接铺到表单(详情页, 可选上列表页) — 一步到位, 避免只建模型没上表单。"
    search_hint: "加字段 表单加字段 字段不显示 字段没上表单 新增字段 加列"
    writes_apaas: true
```

- [ ] **Step 2: 同步 config 白名单快照**

在 `backend/tests/test_tool_registry.py` 的 `_EXPECTED_CONFIG_WHITELIST` frozenset 里(约第 51 行,`"add_apaas_dict_option",` 之后、`"add_apaas_model_field",` 之前)加一行:
```python
    "add_apaas_dict_option",
    "add_apaas_field_to_form",
    "add_apaas_model_field",
```

- [ ] **Step 3: 跑 registry 测试确认绿(drift / 白名单 / schema 全过)**

Run: `cd backend && python -m pytest tests/test_tool_registry.py -v`
Expected: 全部 passed。关键三条:
- `test_config_whitelist_matches_current_expected`(白名单 byte-equal)
- `test_yaml_matches_mcp_server_source`(yaml ↔ 源码 `@mcp.tool()` 无 drift)
- `test_runtime_drift_check_passes_in_clean_state`(yaml ↔ FastMCP 运行时注册一致)

若 `test_yaml_matches_mcp_server_source` 报 yaml-only 或 source-only,说明 Task 3 的 `@mcp.tool()` 或 register() 列表漏了 — 回 Task 3 补。

- [ ] **Step 4: Commit**

```bash
cd "/Users/mars/Vibe Coding/ai-builder"
git add backend/tool_registry.yaml backend/tests/test_tool_registry.py
git commit -m "feat(apaas): 注册 add_apaas_field_to_form 进 tool_registry + 白名单

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 回归 + 真机冒烟清单

**Files:** 无(验证)

- [ ] **Step 1: 跑相关后端测试,确认无新增回归**

Run:
```bash
cd backend && python -m pytest tests/test_add_field_to_form.py tests/test_tool_registry.py tests/test_form_component_tools.py tests/test_form_no_webform_settings_injection.py -v
```
Expected: 全 passed。

- [ ] **Step 2: 全量后端测试(对比预存失败基线)**

Run: `cd backend && python -m pytest -q`
Expected: 仅有**改动前就存在**的预存失败(本地 SQLite 相关,见仓库 handoff);本计划不应引入新失败。若出现 `test_add_field_to_form` / `test_tool_registry` 之外的新失败,定位修复。

- [ ] **Step 3: 真机冒烟清单(手动,连真 apaas;首次必做)**

设计里两条「首次真机必验」项,落地后跑一次真实场景验证:
1. 对话里对一个**已有表单**说「给 XX 表单加个字段 YY」→ agent 调 `add_apaas_field_to_form` → 刷新表单设计器:**新字段出现在详情页画布**(不空白)。这条覆盖设计风险②(追加组件后画布渲染正常;若空白,对照 `_ensure_canvas_form_components` 给组件补 `uuid` 再存)。
2. 带 `show_in_list=True` 跑一次 → 看**列表页表格新增该列**。这条覆盖设计风险①(`detailPage.listPageView.queryList` 跟 `save_form_config` 一起存平台认不认)。若列表页没变,说明列表列需独立写回口径 → 降级为 Phase 2,详情页主路径不受影响。
3. 对**同一字段**再跑一次 → 返回 `FIELD_ALREADY_ON_FORM` 跳过、不重复加(幂等)。

> 提醒:改后端必**重启 preview backend 进程**(`backend/run.py` reload=False)才生效。

---

## Self-Review

- **Spec 覆盖**:合并加字段+铺表单(Task 2 核心)✓;默认只上详情、`show_in_list` 上列表(Task 1 `test_show_in_list_*` + Task 2 `_apply_append`)✓;组件类型自动推导复用构造器(`_build_basic_component_from_model_field`)✓;幂等(`FIELD_ALREADY_ON_FORM` + `_apply_append` 去重)✓;字段已在模型容忍(`_is_dup_field_error`)✓;部分失败不静默吞(`FORM_SAVE_FAILED` + `field_on_model/field_on_form`)✓;保留字预检 ✓;乐观锁重试(`_save_form_config_with_retry`)✓;缓存失效(`_invalidate_section_cache_after_write`)✓;工具注册三处(`@mcp.tool()` / register tools / yaml / 白名单)✓;两条真机风险落到 Task 5 清单 ✓。
- **占位扫描**:无 TBD/TODO;每个 code step 都是完整代码。
- **类型一致**:`_add_field_to_form_core` / `_is_dup_field_error` / `add_apaas_field_to_form` 三处签名与调用一致;返回 dict 的 `error_code` 值(`INVALID_PARAMS`/`RESERVED_FIELD_CODE`/`ADD_FIELD_FAILED`/`FORM_SAVE_FAILED`)在测试断言里逐一对上;`target = f"{mcode}.{fcode}"` 与组件 `modelField`(`_build_basic_component_from_model_field` 产出 `f"{model_code}.{field_code}"`)格式一致 → 幂等比对成立。
