# Engineering Session Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close six correctness and type-contract gaps in engineering-session worktree orchestration without changing unrelated modules or CLI data formats.

**Architecture:** Resolve every service instance to one stable control repository derived from Git's common directory, keep all mutable session actions bound to registered linked worktrees, and centralize Git-state invariants in `GitState` plus `sync_model`. Preserve string-valued YAML/CLI models while retaining enums as normalization and constant namespaces.

**Tech Stack:** Python 3, Pydantic, Git CLI, pytest.

---

### Task 1: Stable control repository from linked worktrees

**Files:**
- Modify: `backend/app/engineering_sessions/git_state.py`
- Modify: `backend/app/engineering_sessions/service.py`
- Test: `backend/tests/test_engineering_sessions_git_state.py`
- Test: `backend/tests/test_engineering_sessions_service.py`
- Test: `backend/tests/test_engineering_sessions_cli.py`

- [ ] Add focused tests proving main/subdirectory and linked-worktree root/subdirectory resolve to the same control repository and registry identity.
- [ ] Add service/CLI tests proving sync, resume, and checkpoint invoked from a linked worktree do not mark the target session missing and only checkpoint the registered target worktree.
- [ ] Run the new tests and record RED failures.
- [ ] Add a common-dir-based control-repository resolver and use it in service initialization.
- [ ] Re-run the focused tests and record GREEN results.

### Task 2: Propagate real checkpoint commit failures

**Files:**
- Modify: `backend/app/engineering_sessions/service.py`
- Test: `backend/tests/test_engineering_sessions_service.py`
- Test: `backend/tests/test_engineering_sessions_cli.py`
- Modify: `README.md`

- [ ] Add tests for service checkpoint failure, archive failure propagation, CLI nonzero exit, registry refresh after failure, and repository `commit.gpgSign=true` being overridden locally.
- [ ] Run the new tests and record RED failures.
- [ ] Add explicit `-c commit.gpgSign=false`; after a nonzero commit, refresh/save state and raise `GitCommandError` with bounded command output.
- [ ] Update README failure semantics and re-run focused tests for GREEN.

### Task 3: Block sessions whose base ref disappeared

**Files:**
- Modify: `backend/app/engineering_sessions/models.py`
- Modify: `backend/app/engineering_sessions/git_state.py`
- Modify: `backend/app/engineering_sessions/service.py`
- Test: `backend/tests/test_engineering_sessions_git_state.py`
- Test: `backend/tests/test_engineering_sessions_service.py`

- [ ] Add tests for `base_missing`, blocked sync/resume/checkpoint/archive, and recovery after restoring the base ref.
- [ ] Run the new tests and record RED failures.
- [ ] Add `GitState.base_missing`, detect absent remote and local refs, map it to `blocked_retained`, and prevent write/archive transitions while blocked.
- [ ] Re-run focused tests and record GREEN results.

### Task 4: Align public model annotations with runtime strings

**Files:**
- Modify: `backend/app/engineering_sessions/models.py`
- Modify: `backend/app/engineering_sessions/registry.py`
- Test: `backend/tests/test_engineering_sessions_models.py`
- Test: `backend/tests/test_engineering_sessions_registry.py`

- [ ] Add tests for Literal/type-alias annotations and string runtime values after direct construction, validation, assignment, and registry round trips.
- [ ] Run the new tests and record RED failures.
- [ ] Introduce explicit string value aliases and enum-to-string validators while keeping `SessionType` and `SessionStatus` enums for normalization/constants.
- [ ] Re-run focused tests and record GREEN results.

### Task 5: Preserve merged, orphan, and blocked states on resume

**Files:**
- Modify: `backend/app/engineering_sessions/service.py`
- Test: `backend/tests/test_engineering_sessions_service.py`

- [ ] Add tests for clean `merged_retained`, merged `orphan_session`, blocked sessions, and an eligible unmerged archived/abandoned session.
- [ ] Run the new tests and record RED failures.
- [ ] Restrict resume activation to valid, unmerged, continuable sessions after synchronization.
- [ ] Re-run focused tests and record GREEN results.

### Task 6: Namespace default worktree parents per repository

**Files:**
- Modify: `backend/app/engineering_sessions/paths.py`
- Test: `backend/tests/test_engineering_sessions_registry.py`
- Test: `backend/tests/test_engineering_sessions_service.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-10-engineering-sessions-worktree-sync-design.md` if the default path is documented there

- [ ] Add sibling-repository tests proving default parents differ by stable `repo_id`, while explicit `worktree_parent` is unchanged.
- [ ] Run the new tests and record RED failures.
- [ ] Add the repository namespace to `default_worktree_parent`.
- [ ] Update current path documentation and re-run focused tests for GREEN.

### Task 7: Full verification and Git closeout

**Files:**
- Review only owned engineering-session files and tests.

- [ ] Run all engineering-session tests and adjacent Git tests.
- [ ] Run `python -m compileall` for the engineering-session application and tests.
- [ ] Run `git diff --check`.
- [ ] Review the final diff for scoped ownership and unintended behavior.
- [ ] Commit the owned changes with clear commit message(s), preserving unrelated work.
