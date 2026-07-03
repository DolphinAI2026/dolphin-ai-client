# Auth Provider Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let backend auth run in one fixed mode selected by `AUTH_PROVIDER`: local, aPaaS, or Coding Control Plane, without exposing a login-page switch.

**Architecture:** Keep the existing `/api/auth/login` contract and frontend login page unchanged. Add a backend mode dispatcher, extract existing local fallback into a reusable helper, keep explicit aPaaS mode strict, and add a Coding Control Plane OAuth/PKCE login adapter that issues the normal ai-builder JWT after external authentication.

**Tech Stack:** FastAPI, SQLAlchemy async sessions, pytest-asyncio, httpx, cryptography.

---

### Task 1: Auth Provider Dispatch Tests

**Files:**
- Create: `backend/tests/test_auth_provider_modes.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/routes/auth/login.py`

- [ ] **Step 1: Write failing tests**

Create tests that assert:
- `AUTH_PROVIDER=local` skips aPaaS and logs in with the local password.
- `AUTH_PROVIDER=apaas` does not fall back to a local password when aPaaS returns no login response.
- `AUTH_PROVIDER=coding` calls the Coding provider and creates or updates a local `account_source="coding"` user.

- [ ] **Step 2: Verify red**

Run:

```bash
cd backend && ../backend/venv/bin/python -m pytest tests/test_auth_provider_modes.py -q
```

Expected: tests fail because `settings.auth_provider`, local helper extraction, and Coding login dispatch do not exist yet.

- [ ] **Step 3: Implement minimal dispatch**

Add `auth_provider` to `Settings`; add a normalizer that accepts `""`, `local`, `apaas`, and `coding`; extract existing local-login block from `login()` into `_local_login_response`; branch `login()` by provider.

- [ ] **Step 4: Verify green for dispatch**

Run:

```bash
cd backend && ../backend/venv/bin/python -m pytest tests/test_auth_provider_modes.py -q
```

Expected: local/aPaaS dispatch tests pass; Coding test may still fail until Task 2.

### Task 2: Coding Control Plane Login Adapter

**Files:**
- Create: `backend/app/code_runtime/auth.py`
- Modify: `backend/app/routes/auth/login.py`
- Test: `backend/tests/test_auth_provider_modes.py`

- [ ] **Step 1: Write failing Coding adapter test**

Add or keep a test that monkeypatches `login_to_coding_control_plane()` and asserts `/login` uses it when `AUTH_PROVIDER=coding`.

- [ ] **Step 2: Implement minimal adapter interface**

Create a dataclass result with `username`, `display_name`, `external_user_id`, `roles`, `access_token`, and `refresh_token`. Implement the real flow used by d-ai-code: `GET /api/auth/login-key`, `POST /api/auth/authorize`, RSA-OAEP encrypt password for `POST /api/auth/login`, `POST /api/auth/token`, then `GET /api/auth/me`.

- [ ] **Step 3: Upsert local Coding user**

In `login.py`, add `_coding_login_response()` that calls the adapter, creates or updates a local user with `account_source="coding"`, ensures the user has a tenant membership, then returns the normal `LoginResponse`.

- [ ] **Step 4: Verify green**

Run:

```bash
cd backend && ../backend/venv/bin/python -m pytest tests/test_auth_provider_modes.py -q
```

Expected: all auth-provider mode tests pass.

### Task 3: Runtime Verification

**Files:**
- Modify only if tests reveal a behavioral gap.

- [ ] **Step 1: Run focused backend tests**

```bash
cd backend && ../backend/venv/bin/python -m pytest tests/test_auth_provider_modes.py tests/test_platform_admin_tenant_context.py -q
```

- [ ] **Step 2: Restart backend in local mode**

```bash
cd backend && AUTH_PROVIDER=local APAAS_BASE_URL= ./venv/bin/python run.py
```

- [ ] **Step 3: Login smoke test**

Use Playwright or API login against `http://127.0.0.1:8000/api/auth/login` with `admin/admin123`, confirming a token is returned.
