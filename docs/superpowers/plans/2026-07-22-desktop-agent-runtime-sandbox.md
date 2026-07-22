# Desktop Agent Runtime Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a desktop Code session run the packaged `agent-runtime` Codex sandbox for its application worktree, while preserving the existing desktop Code conversation and proxy UI.

**Architecture:** `apaas-builder-ai` remains the desktop shell, identity holder, Code-session database, and browser proxy. On desktop it resolves a per-user-per-application local Runtime through `LocalRuntimeClient`; Tauri launches the packaged `agent-runtime` binary inside MXC/Bubblewrap. `agent-runtime` owns Codex app-server, agent sessions, files, previews, and runtime APIs. A typed execution target replaces the old `local-*` demo predicate so local desktop execution is never confused with the Builder demo fallback.

**Tech Stack:** Python/FastAPI/SQLAlchemy, Rust/Tauri/MXC, Go `agent-runtime`, Codex app-server, pytest, Go tests, cargo tests.

---

## Scope and non-goals

- P0 includes real Codex mode, authenticated local Runtime proxying, one shared Runtime per `(tenant, user, application)`, and a safe existing-worktree runtime profile.
- P0 does not add automatic Git synchronization, remote deployment/CI, task worktrees, CPU/memory quotas, Windows/macOS drivers, or a new desktop page.
- The existing `local_builder_workspace_open()` path remains fixture-only. A real application must fail visibly when its local Runtime cannot start; it must not silently open a remote Runtime or a Builder demo.

## File structure

### `apaas-builder-ai`

- `backend/app/code_runtime/execution_target.py` (new): typed runtime target and target-specific behavior predicates.
- `backend/app/code_runtime/local_runtime.py`: prepare an `agent-runtime` desktop-existing-worktree launch request, including real Codex mode and an instance authentication token file.
- `backend/app/code_runtime/service.py`: resolve desktop local execution before Control Plane opening; persist the target on the Code binding and skip entry-token bootstrap for local Runtime targets.
- `backend/app/routes/code_runtime.py`: proxy local Runtime sessions with the per-instance Runtime token; never invoke Control Plane refresh for a local Runtime target.
- `backend/app/models/ai_chat.py`: persist `execution_target` and per-binding local Runtime access metadata.
- `backend/app/database.py`: additive migration for the new nullable columns.
- `src-tauri/src/local_runtime/{contract.rs,manager.rs,mxc_driver.rs}`: accept only file-backed per-instance Runtime auth material, mount it inside the instance runtime directory, and allow the required explicit environment keys.
- `backend/tests/test_code_runtime_local_runtime.py`, `backend/tests/test_code_runtime_service.py`, `backend/tests/test_code_runtime_routes.py`, and Rust module tests: target-specific negative and integration-style coverage.

### `agent-runtime`

- `cmd/sandbox-runtime/main.go`: accept a `desktop_existing_workspace` profile and validate the required local Runtime auth configuration.
- `internal/adapters/config/mounted_file_source.go`: parse the new runtime profile without falling back to seed/fixture behavior.
- `cmd/sandbox-runtime/main_test.go`, `internal/adapters/config/mounted_file_source_test.go`, and existing `internal/http/auth_test.go`: verify real Codex mode, no-seed behavior, and the existing token protection contract.

## Task 1: Define an explicit execution target in `apaas-builder-ai`

**Files:**
- Create: `backend/app/code_runtime/execution_target.py`
- Modify: `backend/app/models/ai_chat.py:66-97`
- Modify: `backend/app/database.py`
- Test: `backend/tests/test_code_runtime_service.py`

- [ ] **Step 1: Write failing target-classification tests**

```python
from app.code_runtime.execution_target import ExecutionTarget, is_local_runtime_target

def test_desktop_local_target_is_not_a_fixture_application():
    assert is_local_runtime_target(ExecutionTarget.DESKTOP_LOCAL)
    assert not is_local_runtime_target(ExecutionTarget.CONTROL_PLANE)
```

- [ ] **Step 2: Run the focused test**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_service.py -q`

Expected: FAIL because `execution_target` does not exist.

- [ ] **Step 3: Add the target model and binding columns**

```python
class ExecutionTarget(StrEnum):
    CONTROL_PLANE = "control_plane"
    DESKTOP_LOCAL = "desktop_local"
    FIXTURE_LOCAL = "fixture_local"

def is_local_runtime_target(value: ExecutionTarget | str | None) -> bool:
    return value in {ExecutionTarget.DESKTOP_LOCAL, ExecutionTarget.FIXTURE_LOCAL}
```

Add nullable `execution_target` and encrypted local Runtime access-token fields to `CodeRuntimeBinding`. Treat an empty legacy value as `control_plane`; do not alter existing rows.

- [ ] **Step 4: Add an additive database migration**

Use the repository's existing `ALTER TABLE` migration list to add the columns without rewriting or backfilling existing bindings.

- [ ] **Step 5: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_service.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/code_runtime/execution_target.py backend/app/models/ai_chat.py backend/app/database.py backend/tests/test_code_runtime_service.py
git commit -m "feat: classify code runtime execution targets"
```

## Task 2: Make the local Runtime launch a real, protected `agent-runtime`

**Files:**
- Modify: `backend/app/code_runtime/local_runtime.py:833-947`
- Modify: `src-tauri/src/local_runtime/mxc_driver.rs:334-369`
- Modify: `src-tauri/src/local_runtime/manager.rs:268-360`
- Test: `backend/tests/test_code_runtime_local_runtime.py`
- Test: `src-tauri/src/local_runtime/mxc_driver.rs`
- Test: `src-tauri/src/local_runtime/manager.rs`

- [ ] **Step 1: Write failing launch-payload tests**

```python
assert start_payload["environment"]["APAAS_CODEX_SESSION_MODE"] == "codex"
assert start_payload["environment"]["APAAS_WORKSPACE_INIT_MODE"] == "desktop_existing_workspace"
assert start_payload["environment"]["APAAS_AUTH_MODE"] == "token"
assert Path(start_payload["environment"]["APAAS_SANDBOX_TOKEN_PATH"]).parent == Path(start_payload["runtime_dir"])
```

Also add a negative Rust test that rejects `APAAS_SANDBOX_TOKEN_PATH` outside `runtime_dir`.

- [ ] **Step 2: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_local_runtime.py -q`

Run: `cargo test local_runtime::mxc_driver local_runtime::manager`

Expected: FAIL because the launch request is still fixture/mock/auth-disabled.

- [ ] **Step 3: Create a desktop-existing-worktree launch profile**

In `LocalRuntimeClient._start()`:

```python
runtime_token = secrets.token_urlsafe(32)
token_path = runtime_dir / "sandbox-token"
_atomic_write_secret_at(paths["runtime_fd"], "sandbox-token", runtime_token)
environment.update({
    "APAAS_CODEX_SESSION_MODE": "codex",
    "APAAS_WORKSPACE_INIT_MODE": "desktop_existing_workspace",
    "APAAS_CI_HANDOFF_MODE": "disabled",
    "APAAS_AUTH_MODE": "token",
    "APAAS_SANDBOX_TOKEN_PATH": str(token_path),
})
```

Persist only an encrypted copy of `runtime_token` on the owning Code binding after a successful manager start. Do not put this token in the runtime context, logs, browser URL, or response payload.

- [ ] **Step 4: Extend manager validation and MXC allowlists**

Allow only these additional environment keys:

```rust
"APAAS_CODEX_SESSION_MODE"
    | "APAAS_SANDBOX_TOKEN_PATH"
```

Require `APAAS_SANDBOX_TOKEN_PATH` to canonicalize to `<runtime_dir>/sandbox-token`; reject symlinks and paths outside the per-instance directory. The file must be mode `0600`.

- [ ] **Step 5: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_local_runtime.py -q`

Run: `cargo test local_runtime::mxc_driver local_runtime::manager`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/code_runtime/local_runtime.py backend/tests/test_code_runtime_local_runtime.py src-tauri/src/local_runtime/mxc_driver.rs src-tauri/src/local_runtime/manager.rs
git commit -m "feat: launch protected local codex runtime"
```

## Task 3: Add the `agent-runtime` desktop-existing-worktree profile

**Files:**
- Modify: `cmd/sandbox-runtime/main.go:148-163,1075-1102`
- Modify: `internal/adapters/config/mounted_file_source.go`
- Test: `cmd/sandbox-runtime/main_test.go`
- Test: `internal/adapters/config/mounted_file_source_test.go`
- Test: `internal/http/auth_test.go`

- [ ] **Step 1: Write failing Go tests**

```go
func TestNewAgentSessionRuntimeUsesCodexForDesktopProfile(t *testing.T) {
    runtime, err := newAgentSessionRuntime("codex", "gpt-5-codex", t.TempDir(), provider)
    if err != nil || runtime == nil {
        t.Fatalf("runtime = %T, err = %v", runtime, err)
    }
}

func TestDesktopExistingWorkspaceProfileDoesNotReleaseSeed(t *testing.T) {
    // Configure APAAS_WORKSPACE_INIT_MODE=desktop_existing_workspace
    // and an existing Git worktree; assert seed releaser is not called.
}
```

Keep the existing auth contract test proving `/api/status` rejects requests without the local token and accepts `Authorization: Bearer <token>`; add only a startup-level test that `APAAS_AUTH_MODE=token` loads the token from `APAAS_SANDBOX_TOKEN_PATH`.

- [ ] **Step 2: Run the focused tests**

Run: `go test ./cmd/sandbox-runtime ./internal/adapters/config ./internal/http`

Expected: FAIL because the profile and token requirement are not implemented.

- [ ] **Step 3: Implement profile validation**

Accept only these workspace initialization modes:

```go
const WorkspaceInitModeDesktopExistingWorkspace = "desktop_existing_workspace"
```

For this mode:

- require `APAAS_WORKSPACE_PATH` to be an existing Git worktree;
- skip clone, seed release, and workspace initialization writes;
- reject control-plane CI handoff and fixture CI handoff;
- use `APAAS_SANDBOX_TOKEN_PATH` with `APAAS_AUTH_MODE=token`;
- keep the standard `codex` session mode requirement enforced by the desktop launcher.

- [ ] **Step 4: Run the focused tests**

Run: `go test ./cmd/sandbox-runtime ./internal/adapters/config ./internal/http`

Expected: PASS.

- [ ] **Step 5: Commit in the `agent-runtime` task worktree**

```bash
git add cmd/sandbox-runtime/main.go internal/adapters/config/mounted_file_source.go cmd/sandbox-runtime/main_test.go internal/adapters/config/mounted_file_source_test.go internal/http/auth_test.go
git commit -m "feat: support protected desktop worktree runtime"
```

## Task 4: Route desktop Code opening to `LocalRuntimeClient`

**Files:**
- Modify: `backend/app/code_runtime/service.py:707-880`
- Modify: `backend/app/routes/code_runtime.py:427-462`
- Test: `backend/tests/test_code_runtime_service.py`
- Test: `backend/tests/test_code_runtime_routes.py`

- [ ] **Step 1: Write failing desktop-open tests**

```python
@pytest.mark.asyncio
async def test_desktop_application_open_uses_local_runtime(monkeypatch, db_session, ctx):
    monkeypatch.setenv("DOLPHIN_LOCAL_RUNTIME_MANAGER_URL", "http://127.0.0.1:41111")
    opened = await open_code_session(db=db_session, session_id=session.id, ctx=ctx)
    assert opened["execution_target"] == "desktop_local"
    assert opened["embed_url"].startswith("/api/code-runtime/")
```

Mock `LocalRuntimeClient.open_application()` and assert `default_workspace_open()` is not called.

- [ ] **Step 2: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py -q`

Expected: FAIL because `open_code_session()` always calls `default_workspace_open()`.

- [ ] **Step 3: Resolve the target before opening the workspace**

Add one narrow resolver:

```python
async def open_execution_target(...):
    if runtime.is_desktop() and local_runtime_manager_is_configured():
        return ExecutionTarget.DESKTOP_LOCAL, await LocalRuntimeClient.from_environment().open_application(db, session, ctx)
    if is_local_code_application_id(external_app_id):
        return ExecutionTarget.FIXTURE_LOCAL, local_builder_workspace_open(external_app_id)
    return ExecutionTarget.CONTROL_PLANE, await default_workspace_open(...)
```

For `DESKTOP_LOCAL`, derive the Runtime base URL directly and skip `bootstrap_runtime_session()`. Do not use `local_builder_url()`.

- [ ] **Step 4: Return target metadata without exposing secrets**

Return:

```json
{
  "execution_target": "desktop_local",
  "runtime_state": "ready"
}
```

Do not return the loopback Runtime URL, manager token, sandbox token, runtime directory, or Codex home path to the browser.

- [ ] **Step 5: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/code_runtime/service.py backend/app/routes/code_runtime.py backend/tests/test_code_runtime_service.py backend/tests/test_code_runtime_routes.py
git commit -m "feat: open desktop code in local agent runtime"
```

## Task 5: Make the browser proxy target-aware and token-authenticated

**Files:**
- Modify: `backend/app/routes/code_runtime.py:465-563,1844-2017,2561-2748`
- Modify: `backend/app/code_runtime/service.py:829-880`
- Test: `backend/tests/test_code_runtime_routes.py`

- [ ] **Step 1: Write failing proxy tests**

```python
async def test_desktop_local_proxy_forwards_instance_bearer_token(client, binding):
    binding.execution_target = "desktop_local"
    binding.local_runtime_token_enc = encrypt_runtime_cookie("runtime-token")
    response = await client.get(f"/api/code-runtime/{binding.session.public_id}/api/status", params={"dolphin_token": embed_token})
    assert response.status_code == 200
    assert upstream_request.headers["authorization"] == "Bearer runtime-token"
```

Add a negative test that a local binding never calls `_renew_proxy_runtime_authorization()`.

- [ ] **Step 2: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_routes.py -q`

Expected: FAIL because the proxy only understands runtime cookies and Control Plane renewal.

- [ ] **Step 3: Add target-specific proxy credentials**

For `desktop_local`:

- outer embed/proxy cookie remains the browser authorization boundary;
- upstream requests use `Authorization: Bearer <decrypted instance token>`;
- omit `apaas_sandbox_token`;
- never call Control Plane renewal;
- on connection failure return a local-runtime-unavailable error suitable for the existing `sandbox.failed` UI event.

Keep current cookie bootstrap/renewal behavior unchanged for `control_plane`.

- [ ] **Step 4: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/code_runtime.py backend/app/code_runtime/service.py backend/tests/test_code_runtime_routes.py
git commit -m "feat: proxy authenticated desktop runtime sessions"
```

## Task 6: Preserve multi-conversation semantics without concurrent writes

**Files:**
- Modify: `backend/app/code_runtime/local_runtime.py`
- Modify: `backend/app/code_runtime/service.py`
- Modify: `backend/app/routes/code_runtime.py`
- Test: `backend/tests/test_code_runtime_local_runtime.py`
- Test: `backend/tests/test_code_runtime_routes.py`

- [ ] **Step 1: Write failing reuse tests**

```python
assert first_open["sandbox_instance_id"] == second_open["sandbox_instance_id"]
assert first_runtime_session_id != second_runtime_session_id
assert runtime_context["conversationId"] in (None, "")
```

Add a test that activating one outer Code conversation never exposes the other conversation's agent session list.

- [ ] **Step 2: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_local_runtime.py backend/tests/test_code_runtime_routes.py -q`

Expected: FAIL because runtime context is initialized with the first conversation ID.

- [ ] **Step 3: Separate application Runtime identity from agent-session identity**

Set `conversationId` in the application Runtime context to empty. After the shared Runtime is ready, create or restore one `runtimeSessionId` per outer Code session through `/api/agent/sessions`; store it in `CodeRuntimeAgentSession`. Reuse the existing application scope and sandbox instance.

For P0, enforce one active write-capable agent session per application in the sidecar. Concurrent read-only inspection remains a later capability because the current Codex protocol does not expose a reliable write-intent classifier.

- [ ] **Step 4: Run the focused tests**

Run: `backend/.venv/bin/pytest backend/tests/test_code_runtime_local_runtime.py backend/tests/test_code_runtime_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/code_runtime/local_runtime.py backend/app/code_runtime/service.py backend/app/routes/code_runtime.py backend/tests/test_code_runtime_local_runtime.py backend/tests/test_code_runtime_routes.py
git commit -m "feat: isolate desktop code conversations in shared runtime"
```

## Task 7: Validate the complete local appliance path

**Files:**
- Modify: `scripts/prepare-local-runtime-appliance-linux.sh` only if the package validation needs an explicit Codex-mode assertion.
- Test: `backend/tests/test_desktop_sidecar.py`
- Test: `src-tauri/src/local_runtime/*`
- Test: `agent-runtime/cmd/sandbox-runtime/*`

- [ ] **Step 1: Add an appliance smoke assertion**

Extend the existing local appliance test harness to start the packaged Runtime with:

```text
APAAS_CODEX_SESSION_MODE=codex
APAAS_WORKSPACE_INIT_MODE=desktop_existing_workspace
APAAS_AUTH_MODE=token
```

Assert `/api/status` reports `runtimeMode=codex` and unauthenticated requests receive `401`.

- [ ] **Step 2: Run subsystem tests**

Run:

```bash
backend/.venv/bin/pytest \
  backend/tests/test_code_runtime_local_runtime.py \
  backend/tests/test_code_runtime_service.py \
  backend/tests/test_code_runtime_routes.py \
  backend/tests/test_desktop_sidecar.py -q

cargo test local_runtime

go test ./cmd/sandbox-runtime ./internal/adapters/config ./internal/http
```

Expected: all PASS.

- [ ] **Step 3: Run a desktop manual acceptance**

1. Start the desktop app with a registered local Git workspace.
2. Open two Code conversations for one application.
3. Confirm both use the same sandbox instance and distinct agent-runtime sessions.
4. Send a real file-edit request in the first conversation.
5. Confirm the Runtime status reports Codex app-server mode.
6. Stop the desktop app and verify manager reconciliation removes only the Runtime it owns.

- [ ] **Step 4: Commit**

```bash
git add scripts/prepare-local-runtime-appliance-linux.sh backend/tests/test_desktop_sidecar.py
git commit -m "test: verify desktop agent runtime appliance"
```

## Deferred follow-up plan

After P0 acceptance, create a separate plan for:

1. application-level write leases and task-specific linked worktrees;
2. Files/Preview runtime status, stop, restart, and idle hibernation;
3. manual two-way synchronization;
4. credentials held by a desktop model gateway rather than readable provider files;
5. per-application independent Git metadata;
6. Windows/macOS sandbox drivers.

## Self-review

- Real Codex mode is covered by Tasks 2, 3, and 7.
- No demo fallback for real desktop applications is covered by Task 4.
- Token-authenticated local Runtime proxying is covered by Tasks 2, 3, and 5.
- Existing code worktrees are protected from seed/fixture behavior in Task 3.
- Multiple conversations sharing one application Runtime are covered in Task 6.
- Automatic sync, deployment, and cross-platform support are explicitly excluded from P0.
