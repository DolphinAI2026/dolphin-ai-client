# Delete Vibe Coding Backend (Stage 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the dead Vibe Coding / online-coding backend (files, routes, wiring, and the couplings into retained code) without breaking the retained 睿鲸 AI Coding or `app.main` import.

**Architecture:** This is **surgical deletion, not a refactor.** The handoff feared a deep refactor (extract shared workspace/IDE/thread infra, give AI Coding its own models, rewrite `coding.py`'s `oc_` branch). Investigation on 2026-05-29 proved that wrong: retained AI Coding **already owns** its complete workspace infra (`app/coding/workspace.py`, 5532 lines, project-prefixed IDs). `online_coding.py` is a **separate** layer storing `oc_`-prefixed workspaces under `WORKSPACE_ROOT/_online_coding/`. Every coupling from retained code into the vibe cluster is either (a) gated behind `ws_id.startswith("oc_")` (dead online-coding path with a working non-oc fallback right beside it), or (b) a small vibe-only snippet. So we sever the references in retained code first, then unwire `main.py`/`models`/`database.py`, then delete the orphaned files — keeping `import app.main` green at every commit.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy (async). Backend venv: `backend/venv/bin/python`. Baseline `import app.main` is **green** as of plan time.

---

## Corrected coupling map (verified 2026-05-29)

Handoff path corrections found during investigation:
- `sandboxes.py` is at `app/routes/sandboxes.py` (not `app/sandboxes.py`) — and is **100% vibe** (`prefix="/online-coding/sandboxes"`, tag `vibe-coding-sandboxes`). Delete the whole file.
- `agents_config.py` is at `app/routes/agents_config.py` (not `app/agents_config.py`) — retained, has a small vibe snippet.
- The handoff missed these retained files that touch the vibe cluster: `tenant_quota.py`, `browser.py`, `coding_prompt_seed.py`, and embedded vibe tools in `mcp_server.py`.
- `requirements.py` and `current_app.py` are **retained** (low-code design-doc bridge + MCP identity slot) — NOT vibe. Do not touch.

**DELETE (files):** `app/vibe_coding/` (dir: agent.py, docker_runtime.py, k8s_runtime.py, prompts.py, tools.py, workspace.py, __init__.py), `app/routes/online_coding.py`, `app/routes/online_coding_runtime.py`, `app/routes/vibe_coding_chat.py`, `app/routes/sandboxes.py`, `app/models/vibe_coding.py`, `app/models/app_prototype.py`, `app/routes/applications/prototype.py`, `app/coding/vibe_agent.py`.

**SEVER (retained files, edit only):** `app/routes/coding.py` (oc_ branches), `app/tenant_quota.py` (`_count_workspaces`), `app/routes/browser.py` (online_coding meta lookup), `app/routes/agents_config.py` (vibe agent entry), `app/services/coding_prompt_seed.py` (`_load_vibe_prompts`), `app/mcp_server.py` (contiguous vibe-tool block), `app/main.py` (imports + mounts + startup hooks), `app/models/__init__.py` (vibe imports), `app/database.py` (vibe ALTERs), `app/routes/applications/__init__.py` (prototype mount), frontend `BuilderCommandPalette.vue` + orphaned `api/sandbox*.ts`.

**KEEP (focus, do not touch):** `app/coding/workspace.py`, `app/coding/tools.py`, `app/routes/coding.py` (non-oc paths), the retained MCP workspace tools in `mcp_server.py` (`read_workspace_file`/`write_workspace_files`/`edit_workspace_files`/`glob_workspace`/`grep_workspace`/`run_workspace_command`/`get_dev_workspace_status`/`create_dev_workspace`/`save_dev_spec` — all resolve via `WorkspaceManager`), `coding_v2`/`coding_v2_spec`/`orchestrator`/`agents` (zero vibe coupling).

**DECISION REQUIRED (Task 7, not auto):** `mcp_server.py`'s `import_zip_to_workspace` + `publish_dev_workspace` (+ their `~line 2710` workspace-resolution helper) use lazy `online_coding._find_workspace_dir` imports but tie into the retained apaas `PAGE_CUSTOM_DEV` publish flow. Lazy imports mean they won't break `import app.main` after deletion — they become "dead-at-call, importable" (same harmless status as deferred DB drops). Needs a user call before touching.

**OUT OF SCOPE (Stage 3, follow-up):** DB table drops (`vibe_coding_threads`/`vibe_coding_messages`/`vibe_coding_tool_calls`, `online_coding_workspaces`, `app_prototypes`); `app_type` `ai-code` classification cleanup (schemas.py, `_helpers.py`, Apps.vue label). Orphan tables/columns left in DB are harmless.

## Verification ritual (run after EVERY task, before commit)

```bash
cd backend
./venv/bin/python -m py_compile <each edited .py file>
./venv/bin/python -c "import app.main; print('IMPORT OK')" 2>&1 | tail -1
```
Expected last line: `IMPORT OK`. If anything else, STOP and fix before committing. Functional verification (retained `/coding` + `/chat` still work) is the user's browser test after restart — note this in the final summary; do not claim functional success from import-only checks.

---

### Task 1: Sever `coding.py` oc_ branches

**Files:**
- Modify: `backend/app/routes/coding.py` (function `_inject_online_workspace_context` ~line 338; its only caller ~line 1748-1749; the oc_ block in `ide_apply_file_edits` ~line 1589-1618)

- [ ] **Step 1: Locate the three oc_ sites**

Run: `grep -n "oc_\|online_coding\|_inject_online_workspace_context" backend/app/routes/coding.py`
Expected: 5 hits — def @338, import @361, caller @1749, two `startswith("oc_")` @1589 and @1748.

- [ ] **Step 2: Remove the `_inject_online_workspace_context` function**

Read the full function (starts at the `def _inject_online_workspace_context(ws_id: str, payload: dict[str, Any]) -> None:` line, ~338; it contains the `try: from app.routes.online_coding import (_build_ide_workspace_context, _find_workspace_dir, _repo_path)` block) and delete the entire function body through its final `return`/`except` line. This is the function the import at line 361 lives inside.

- [ ] **Step 3: Remove its only caller**

Delete these two lines (~1748-1749):
```python
    if ws_id.startswith("oc_"):
        _inject_online_workspace_context(ws_id, payload)
```

- [ ] **Step 4: Remove the oc_ block in `ide_apply_file_edits`, keep the non-oc fallthrough**

Delete this block (~1589-1618) entirely:
```python
    if ws_id.startswith("oc_"):
        from app.routes.online_coding import (
            _find_workspace_dir,
            _repo_path,
            _summarize_repo,
            _write_workspace,
        )

        ws_dir, meta = _find_workspace_dir(ws_id)
        if str(meta.get("user_id")) != str(token_payload.get("sub")):
            raise HTTPException(status_code=403, detail="IDE 访问令牌与当前工作区用户不匹配")
        if str(meta.get("tenant_id")) != str(token_payload.get("tid")):
            raise HTTPException(status_code=403, detail="IDE 访问令牌与当前租户不匹配")

        repo_dir = _repo_path(ws_dir)
        repo_dir.mkdir(parents=True, exist_ok=True)
        result = _apply_ide_edits_to_path(repo_dir, req.edits)
        if result["applied"]:
            file_count, files = _summarize_repo(repo_dir)
            meta.update({
                "status": "repo_imported",
                "sandbox_status": "repo_ready",
                "file_count": file_count,
                "files": files,
                "import_error": None,
                "updated_at": datetime.utcnow().isoformat(),
            })
            _write_workspace(ws_dir, meta)
        return result
```
The function continues with the retained path — leave it exactly as-is:
```python
    try:
        workspace_path = workspace_mgr.get_workspace_path(ws_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return _apply_ide_edits_to_path(workspace_path, req.edits)
```

- [ ] **Step 5: Verify zero residual references**

Run: `grep -n "oc_\|online_coding\|_inject_online_workspace_context" backend/app/routes/coding.py`
Expected: no matches (or only unrelated substrings — inspect each; there should be none).

- [ ] **Step 6: Compile + import check**

Run: `cd backend && ./venv/bin/python -m py_compile app/routes/coding.py && ./venv/bin/python -c "import app.main; print('IMPORT OK')" 2>&1 | tail -1`
Expected: `IMPORT OK`

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/coding.py
git commit -m "refactor(coding): 砍掉 coding.py 的 oc_ 死分支 — 保留 AI Coding 非 oc 路径 (vibe 删除 2/n)"
```

---

### Task 2: Sever small retained couplings (tenant_quota, browser, agents_config, coding_prompt_seed)

**Files:**
- Modify: `backend/app/tenant_quota.py` (`_count_workspaces` ~line 54-71)
- Modify: `backend/app/routes/browser.py` (online_coding lookup ~line 37-40)
- Modify: `backend/app/routes/agents_config.py` (import @41 + vibe agent registry entry)
- Modify: `backend/app/services/coding_prompt_seed.py` (`_load_vibe_prompts` ~line 58 + caller)
- Test: `backend/tests/test_tenant_quota.py`

- [ ] **Step 1: tenant_quota — make `_count_workspaces` return 0**

Replace the body of `_count_workspaces` (the version that does `from app.routes.online_coding import _iter_workspace_meta_dirs, _meta_path` and scans the filesystem) with:
```python
def _count_workspaces(tenant_id: int) -> int:
    """Vibe Coding 已下线（2026-05-29），工作区配额维度恒为 0。"""
    return 0
```
Leave the `"workspaces"` ResourceKind and the quota dict entries intact (schema/UI stability — they now report `0/max`).

- [ ] **Step 2: browser.py — drop the online_coding meta lookup**

Replace the lookup block (~line 37-40):
```python
    try:
        from app.routes.online_coding import _find_workspace_dir
        _, meta = _find_workspace_dir(ws_id)
    except HTTPException:
        meta = None
```
with:
```python
    meta = None  # Vibe online-coding workspaces 已下线；retained workspace 本就走 meta=None 跳过交叉校验
```
The downstream `if meta is not None:` block stays and is simply never entered (same behavior retained workspaces already had).

- [ ] **Step 3: agents_config.py — remove the vibe agent**

Remove the import (line 41): `from app.vibe_coding.prompts import SYSTEM_PROMPT as _VIBE_PROMPT`.
Then read the default agent registry below it and remove the registry entry that uses `_VIBE_PROMPT` (the vibe/whale agent — id likely `vibe` or `whale`). Keep the `builder` and `coding` entries. Locate via: `grep -n "_VIBE_PROMPT\|whale\|vibe" backend/app/routes/agents_config.py`.

- [ ] **Step 4: coding_prompt_seed.py — remove `_load_vibe_prompts` and its caller**

Remove the entire `def _load_vibe_prompts() -> dict[str, str]:` function (~line 58, contains `from app.vibe_coding import prompts as p`). Then find and remove its caller: `grep -n "_load_vibe_prompts" backend/app/services/coding_prompt_seed.py` — remove the call site (and any dict-merge of its result).

- [ ] **Step 5: Verify zero residual references in these four files**

Run: `grep -rn "vibe\|online_coding\|VibeCoding" backend/app/tenant_quota.py backend/app/routes/browser.py backend/app/routes/agents_config.py backend/app/services/coding_prompt_seed.py`
Expected: no matches except the harmless comment strings added in Steps 1-2.

- [ ] **Step 6: Compile + import + quota test**

Run:
```bash
cd backend && ./venv/bin/python -m py_compile app/tenant_quota.py app/routes/browser.py app/routes/agents_config.py app/services/coding_prompt_seed.py && ./venv/bin/python -c "import app.main; print('IMPORT OK')" 2>&1 | tail -1 && ./venv/bin/python -m pytest tests/test_tenant_quota.py -q 2>&1 | tail -15
```
Expected: `IMPORT OK`, and tenant_quota tests pass (or fail only on the now-`0` workspace count — if so, update the test's workspace expectation to 0).

- [ ] **Step 7: Commit**

```bash
git add backend/app/tenant_quota.py backend/app/routes/browser.py backend/app/routes/agents_config.py backend/app/services/coding_prompt_seed.py backend/tests/test_tenant_quota.py
git commit -m "refactor(backend): 拆 tenant_quota/browser/agents_config/prompt_seed 的 vibe 引用 (vibe 删除 3/n)"
```

---

### Task 3: Remove the contiguous vibe-tool block from `mcp_server.py`

**Files:**
- Modify: `backend/app/mcp_server.py` (vibe block: `_resolve_vibe_thread` ~2985 through `vibe_http_check` ~3238, ending right before `list_apaas_app_roles` ~3239)

**Scope note:** Remove ONLY the unambiguous contiguous vibe block. Do NOT touch `import_zip_to_workspace`/`publish_dev_workspace`/`_classify_publish_failure`/the `~2710` resolution helper (those are Task 7). Do NOT touch the retained workspace tools above ~2700 (`read_workspace_file` … `save_dev_spec`).

- [ ] **Step 1: Identify exact block bounds**

Run: `grep -n "_resolve_vibe_thread\|_call_vibe_executor\|async def vibe_\|async def list_apaas_app_roles" backend/app/mcp_server.py`
Expected: `_resolve_vibe_thread` (~2985), `_call_vibe_executor` (~3029), 10 `vibe_*` tools (`vibe_create_workspace` ~3053 … `vibe_http_check` ~3214), and `list_apaas_app_roles` (~3239) as the first NON-vibe tool after the block.

- [ ] **Step 2: Read the block to confirm it is self-contained**

Read `backend/app/mcp_server.py` from the `_resolve_vibe_thread` definition down to (but not including) the `@mcp.tool()` decorator immediately above `async def list_apaas_app_roles`. Confirm the only things defined in this span are: `_resolve_vibe_thread`, any `_resolve_vibe_thread_ctx`, `_call_vibe_executor`, and the 10 `vibe_*` tools. Confirm nothing OUTSIDE this span calls these names: `grep -n "vibe_create_workspace\|vibe_read_file\|vibe_write_file\|vibe_edit_file\|vibe_glob\|vibe_grep\|vibe_run_command\|vibe_todo_write\|vibe_http_check\|vibe_get_workspace_status\|_call_vibe_executor\|_resolve_vibe_thread" backend/app/mcp_server.py` → all hits must fall inside the block.

- [ ] **Step 3: Delete the block**

Delete from the line above `_resolve_vibe_thread`'s definition (including its section-comment banner if present, e.g. the `# 用途：让外部 agent ... vibe-coding ...` comment ~line 2981) through the last line of `vibe_http_check`, stopping immediately before the `@mcp.tool()` that decorates `list_apaas_app_roles`.

- [ ] **Step 4: Verify + count tools**

Run:
```bash
cd backend && ./venv/bin/python -m py_compile app/mcp_server.py && ./venv/bin/python -c "import app.main; print('IMPORT OK')" 2>&1 | tail -1 && grep -c "@mcp.tool()" app/mcp_server.py
```
Expected: `IMPORT OK`. Tool count drops by exactly 10 vs. before. `grep -n "async def vibe_" app/mcp_server.py` → no matches.

- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp_server.py
git commit -m "refactor(mcp): 删除 mcp_server 的 10 个 vibe_* 工具 + 桥接 helper (vibe 删除 4/n)"
```

---

### Task 4: Unwire `main.py` + `models/__init__.py` + `database.py` + applications prototype mount

**Files:**
- Modify: `backend/app/main.py` (routes import block ~15-60; include_router lines @209-211 + @214; startup hooks: `pkill vibe-serve.js` @76, `_vibe_reap_loop` @124-140)
- Modify: `backend/app/models/__init__.py` (vibe_coding import @380-383; app_prototype import @406)
- Modify: `backend/app/database.py` (vibe ALTERs @124, @126 + comments @120/123/125)
- Modify: `backend/app/routes/applications/__init__.py` (prototype import + include @1941-1943)

- [ ] **Step 1: main.py — remove the four vibe route imports**

In the `from app.routes import (...)` block (~15-60), delete these four lines: `    online_coding,` / `    online_coding_runtime,` / `    sandboxes,` / `    vibe_coding_chat,`. Keep `browser,` and all others.

- [ ] **Step 2: main.py — remove the four include_router lines**

Delete (~209-214):
```python
app.include_router(online_coding.router, prefix="/api")
app.include_router(online_coding_runtime.router, prefix="/api")
app.include_router(vibe_coding_chat.router, prefix="/api")
```
and
```python
app.include_router(sandboxes.router, prefix="/api")
```

- [ ] **Step 3: main.py — remove the vibe startup hooks**

Delete the orphan-process cleanup (~76): `    subprocess.run(["pkill", "-f", "vibe-serve.js"], capture_output=True)` (and its comment line above it).
Delete the entire `_vibe_reap_loop` block (~124-140): the `async def _vibe_reap_loop():` definition (which does `from app.vibe_coding.docker_runtime import get_runtime`) and the `_asyncio.create_task(_vibe_reap_loop())` line that schedules it, plus the comment banner above.

- [ ] **Step 4: models/__init__.py — remove vibe model imports**

Delete (~380-383):
```python
from app.models.vibe_coding import (  # noqa: E402, F401
    VibeCodingThread,
    VibeCodingMessage,
    VibeCodingToolCall,
)
```
Delete (~406):
```python
from app.models.app_prototype import AppPrototype  # noqa: E402, F401  — AI Coding HTML 原型快照
```

- [ ] **Step 5: database.py — remove vibe ALTER migrations**

Delete the two `ALTER TABLE vibe_coding_threads ADD COLUMN ...` entries (~124 `requirement_baseline`, ~126 `token_usage`) and their comment lines (~123, ~125). Verify the surrounding migration list still has valid syntax (no dangling comma into a `]`).

- [ ] **Step 6: applications/__init__.py — remove prototype mount**

Delete (~1941-1943):
```python
# POST /{app_id}/prototype/generate — LLM 流式产出单文件 HTML, 存 app_prototypes.
from . import prototype as _prototype  # noqa: E402
router.include_router(_prototype.router)
```

- [ ] **Step 7: Verify (files still present, just unwired → import must stay green)**

Run:
```bash
cd backend && ./venv/bin/python -m py_compile app/main.py app/models/__init__.py app/database.py app/routes/applications/__init__.py && ./venv/bin/python -c "import app.main; print('IMPORT OK')" 2>&1 | tail -1
```
Expected: `IMPORT OK` (the vibe files still exist on disk but are now imported by nobody).

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/app/models/__init__.py backend/app/database.py backend/app/routes/applications/__init__.py
git commit -m "refactor(backend): 拆 main/models/database/applications 的 vibe 装配线 (vibe 删除 5/n)"
```

---

### Task 5: Delete the orphaned vibe files + full residual sweep

**Files (delete):** `app/vibe_coding/` (dir), `app/routes/online_coding.py`, `app/routes/online_coding_runtime.py`, `app/routes/vibe_coding_chat.py`, `app/routes/sandboxes.py`, `app/models/vibe_coding.py`, `app/models/app_prototype.py`, `app/routes/applications/prototype.py`, `app/coding/vibe_agent.py`

- [ ] **Step 1: Pre-delete — confirm zero remaining importers**

Run:
```bash
cd backend && grep -rn "from app.vibe_coding\|import app.vibe_coding\|from app.routes.online_coding\|from app.routes import online_coding\|online_coding_runtime\|vibe_coding_chat\|from app.routes import sandboxes\|from app.routes.sandboxes\|from app.models.vibe_coding\|from app.models.app_prototype\|from app.coding.vibe_agent\|from app.coding import vibe_agent\|routes.applications.prototype\|applications import prototype" app --include='*.py' | grep -v "^app/vibe_coding/\|^app/routes/online_coding\|^app/routes/vibe_coding_chat\|^app/routes/sandboxes\|^app/models/vibe_coding\|^app/models/app_prototype\|^app/coding/vibe_agent\|^app/routes/applications/prototype"
```
Expected: **no output** (the only importers left are inside the to-be-deleted files themselves, which are filtered out). If any retained file still appears, STOP — go sever it before deleting.

- [ ] **Step 2: Delete the files**

```bash
cd backend && git rm -r app/vibe_coding app/routes/online_coding.py app/routes/online_coding_runtime.py app/routes/vibe_coding_chat.py app/routes/sandboxes.py app/models/vibe_coding.py app/models/app_prototype.py app/routes/applications/prototype.py app/coding/vibe_agent.py
```

- [ ] **Step 3: Clear stale bytecode + full compile**

```bash
cd backend && find app -name "__pycache__" -type d -exec rm -rf {} + ; ./venv/bin/python -m compileall -q app && echo "COMPILEALL OK"
```
Expected: `COMPILEALL OK` (no compile errors). (Clearing `__pycache__` avoids the py3.13 stale-.pyc trap noted in project memory.)

- [ ] **Step 4: Import check + whole-tree residual grep**

```bash
cd backend && ./venv/bin/python -c "import app.main; print('IMPORT OK')" 2>&1 | tail -1 && echo "--- residual refs (expect only comments / Task-7 import_zip+publish lazy refs) ---" && grep -rn "vibe_coding\|VibeCoding\|online_coding\|vibe_agent\|app_prototype" app --include='*.py'
```
Expected: `IMPORT OK`. Residual grep should show ONLY: (a) comment/docstring mentions, and (b) the lazy `from app.routes.online_coding import _find_workspace_dir` refs inside `import_zip_to_workspace`/`publish_dev_workspace`/their helper (deferred to Task 7). No top-level imports, no references from any other code path.

- [ ] **Step 5: Commit**

```bash
git add -A backend
git commit -m "refactor(backend): 删除 Vibe Coding 后端文件 — vibe_coding/ + online_coding + sandboxes + 模型 (vibe 删除 6/n)"
```

---

### Task 6: Frontend dangling cleanup

**Files:**
- Modify: `frontend/src/components/BuilderCommandPalette.vue` (Vibe Coding entry ~line 55)
- Delete (if unused): `frontend/src/api/sandbox.ts`, `frontend/src/api/sandboxes.ts`
- Optional cosmetic: comments in `App.vue:29`, `LandingComposer.vue:5`, `ChatPage.vue:6994`, string in `PlatformTenants.vue:672`

- [ ] **Step 1: Remove the dead command-palette entry**

In `frontend/src/components/BuilderCommandPalette.vue`, delete the command object pointing to `/vibe-coding` (~line 55): `{ icon: Connection, title: 'Vibe Coding', meta: '查看全代码仓库工作区和导入记录', to: '/vibe-coding' },`. If `Connection` icon import becomes unused, remove it too (`grep -n "Connection" frontend/src/components/BuilderCommandPalette.vue`).

- [ ] **Step 2: Check whether the sandbox api modules are imported anywhere**

Run: `grep -rn "api/sandbox\b\|api/sandboxes\|from.*sandbox" frontend/src --include='*.vue' --include='*.ts' | grep -v "src/api/sandbox"`
Expected: no output (the page that used them, `SandboxMonitorPage`, was deleted in Stage 1). If empty, delete both: `git rm frontend/src/api/sandbox.ts frontend/src/api/sandboxes.ts`. If anything still imports them, leave them and note it.

- [ ] **Step 3: (Optional) tidy stale comments**

Update the comment strings in `App.vue:29`, `LandingComposer.vue:5`, `ChatPage.vue:6994`, and the `_online_coding/` mention in `PlatformTenants.vue:672` to drop Vibe Coding references. Skip if low value.

- [ ] **Step 4: Type-check against baseline**

Run: `cd frontend && npx vue-tsc --noEmit 2>&1 | grep -c "error TS"`
Expected: ≤ 399 (the Stage-1 baseline). It must NOT increase. (Pre-existing errors are unrelated to this work.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "refactor(frontend): 清理 Vibe Coding 残留入口 + 孤儿 sandbox api (vibe 删除 7/n)"
```

---

### Task 7: DECISION — `import_zip_to_workspace` + `publish_dev_workspace` (do NOT auto-execute)

These two `mcp_server.py` tools (+ their `~line 2710` workspace-resolution helper) use lazy `online_coding._find_workspace_dir` imports. After Task 5 they are "dead-at-call but importable" — harmless to leave, but not clean. They tie into the retained apaas `PAGE_CUSTOM_DEV` build/publish flow (see project memory `build_output_dir_page_custom_dev_2026_05_16`), so deleting them blindly could break a retained capability.

**Present to the user, then implement the chosen option:**

- **Option A — Delete them** (if the apaas publish-from-workspace flow is confirmed dead): remove `import_zip_to_workspace`, `publish_dev_workspace`, `_classify_publish_failure`, and the `~2710` helper. Verify import + tool count.
- **Option B — Keep + re-point** (if the flow is still used): change their workspace resolution from `online_coding._find_workspace_dir` to the retained `WorkspaceManager().get_workspace_path()` (the AI-coding branch already present in the `~2710` helper), then remove the now-unused vibe branch. Verify import + a manual publish smoke test.
- **Option C — Defer**: leave as-is (dead-at-call lazy refs), revisit with Stage 3 DB drops.

---

## Self-Review

**Spec coverage (vs. handoff/memory delete list):**
- `app/vibe_coding/` dir → Task 5 ✅
- `routes/vibe_coding_chat.py`, `online_coding.py`, `online_coding_runtime.py` → Task 5 ✅
- `models/vibe_coding.py`, `models/app_prototype.py` → Task 5 ✅ (imports unwired Task 4)
- `routes/applications/prototype.py` → Task 5 ✅ (mount removed Task 4)
- `coding/vibe_agent.py` → Task 5 ✅ (verified zero code importers — only docstring mentions)
- `main.py` include_routers + docker_runtime startup hook → Task 4 ✅
- `models/__init__.py` imports → Task 4 ✅
- `database.py` vibe ALTERs → Task 4 ✅
- `mcp_server` vibe tools → Task 3 (clean block) + Task 7 (ambiguous tools) ✅
- `sandboxes.py` → Task 4 (unmount) + Task 5 (delete) ✅
- coding.py oc_ branch → Task 1 ✅
- Extra retained couplings found in investigation (tenant_quota, browser, agents_config, coding_prompt_seed) → Task 2 ✅
- Frontend dangling (command palette, api modules) → Task 6 ✅
- DB table drops + app_type cleanup → explicitly Stage 3, out of scope ✅

**Ordering invariant:** Sever-in-retained (T1-T3) → unwire assembly (T4) → delete files (T5). `import app.main` is green after every task because files are only deleted (T5) after the last importer is removed (T4), and the T5 pre-delete grep (Step 1) enforces this. ✅

**Placeholder scan:** Every removal step shows the exact current code to delete (read from the tree on 2026-05-29) or a precise grep to locate it. No "TBD"/"handle edge cases". ✅

**Type/name consistency:** Retained fallback in `ide_apply_file_edits` uses `workspace_mgr.get_workspace_path` (confirmed present). `_count_workspaces` keeps its signature `(tenant_id: int) -> int`. Retained MCP tools resolve via `WorkspaceManager` (confirmed). ✅

**Risk note:** Import-only verification cannot prove the retained `/coding` and `/chat` flows still work end-to-end. After Task 5 (and Task 6), the user must restart the backend (`cd backend && ./venv/bin/python run.py`) and exercise `/coding` (open Web IDE, apply an edit) + `/chat` (low-code builder) in the browser. State this in the final summary; do not claim functional success from `import app.main` alone.
