# Code Rail Shell History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a clicked Code application appear immediately in the outer left rail, keep new task creation on the application group, and hide iframe-internal history/new-session entry points.

**Architecture:** Treat ai-builder `AIChatSession(mode="code")` as the authoritative shell-session record for the outer rail. Use `CodeRuntimeBinding` only as optional runtime state. The frontend rail normalizes shell-only sessions and runtime agent sessions into one list, refreshes after application clicks, and delegates iframe history/new-session hiding through URL/config flags.

**Tech Stack:** FastAPI, SQLAlchemy async, Vue 3, Pinia/router, Vitest, pytest.

---

### Task 1: Shell Sessions In Rail

**Files:**
- Modify: `backend/app/routes/code_runtime.py`
- Test: `backend/tests/test_code_runtime_routes.py`
- Modify: `frontend/src/composables/railSessions.ts`
- Test: `frontend/src/composables/railSessions.spec.ts`

- [ ] Add a backend test proving `/code/rail/history` includes a code shell session before any `CodeRuntimeBinding` exists.
- [ ] Add a frontend test proving `normalizeCodeRailHistory()` emits a shell rail item when an app has no runtime agent sessions.
- [ ] Change `list_code_runtime_rail_history()` to left join bindings and emit app groups for shell-only sessions.
- [ ] Change rail normalization so shell-only items route to `/code/{shellSessionId}` and group by the app name.

### Task 2: Rail Refresh After App Click

**Files:**
- Modify: `frontend/src/views/Apps.vue`
- Modify: `frontend/src/components/v2/RailSidebar.vue`
- Test: `frontend/src/views/Apps.codeMode.spec.ts`
- Test: `frontend/src/components/v2/RailSidebar.spec.ts`

- [ ] Add tests checking the app click path dispatches a rail refresh event and the rail listens for it.
- [ ] Dispatch `code-rail-refresh` after `createSessionFromExternalApp()` succeeds.
- [ ] Listen for that event in `RailSidebar.vue` and reload apps/sessions.

### Task 3: Hide Inner History And New Buttons

**Files:**
- Modify: `backend/app/code_runtime/service.py`
- Test: `backend/tests/test_code_runtime_service.py`

- [ ] Add a test proving `build_embed_url()` adds `externalSessionRail=1`, `hideHistory=1`, and `hideNewSession=1`.
- [ ] Add those query flags to every generated iframe URL, preserving existing query params.

### Task 4: Verification

**Commands:**
- `cd backend && ./venv/bin/python -m pytest tests/test_code_runtime_routes.py tests/test_code_runtime_service.py -q`
- `npm --prefix frontend test -- src/composables/railSessions.spec.ts src/views/Apps.codeMode.spec.ts src/components/v2/RailSidebar.spec.ts`
- Playwright: login, open `/ai-builder/code/apps`, click CRM, verify the outer rail shows the CRM group/session and the iframe URL has the hiding flags.
