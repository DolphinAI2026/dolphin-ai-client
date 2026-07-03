# Dolphin Code Integration Notes

Date: 2026-07-01

## Verified in this repo

- Entry flow: `Builder / Code` mode switch -> Code `我的应用` -> click application -> create `mode=code` session -> open `/code/:id`.
- Builder and Code application catalogs are isolated by `applications.app_type`:
  - Builder lists `app_type=low-code`.
  - Code lists and creates `app_type=ai-code`.
  - Code session APIs reject low-code applications even if called directly.
- Code sessions are application-bound and shown in the left rail. Code mode defaults to application grouping.
- The embedded runtime is loaded through the local shell proxy:
  - frontend iframe URL: `/api/code-runtime/{sessionId}/builder?dolphin_token=...`
  - backend proxy prefix: `/api/code-runtime/{sessionId}`
  - injected shell config:
    - `window.__APAAS_SHELL__.externalBasePath = /api/code-runtime/{sessionId}`
    - `window.__APAAS_SHELL__.webConsoleOrigin = browser-facing origin`
- Playwright verification passed against local d-ai-code builder at `http://127.0.0.1:5173/builder/`.
- Streaming/event APIs such as `/api/builder/events` are proxied without pre-buffering.
- Runtime cookies set by d-ai-code are scoped to `/api/code-runtime/{sessionId}` and forwarded back to the upstream runtime. The ai-builder proxy cookie is stripped before forwarding.

## Production contract needed from d-ai-code

The production path should use the d-ai-code Control Plane instead of the local fallback.

Expected endpoint:

```http
POST {DOLPHIN_CODE_CONTROL_PLANE_URL}/api/applications/{externalApplicationId}/workspace/open
Authorization: Bearer {DOLPHIN_CODE_CONTROL_PLANE_TOKEN}
X-AI-Builder-Delegated-User-Id: {apaasUserId or localUserId}
X-AI-Builder-Delegated-Tenant-Id: {apaasTenantId or localTenantId}
X-AI-Builder-Local-User-Id: {localUserId}
X-AI-Builder-Local-Tenant-Id: {localTenantId}
X-AI-Builder-Delegated-Username: {username}
X-AI-Builder-Delegated-Display-Name-B64: {base64url(utf8 displayName)}
X-AI-Builder-Shell-Session-Id: {aiBuilderCodeSessionId}
Content-Type: application/json
```

When ai-builder uses a service/admin token for Control Plane calls, d-ai-code
must not use the token owner as the workspace owner. It should validate the
service token, then use the delegated user headers above for workspace lookup
and sandbox ownership. The current d-ai-code workspace uniqueness model is
`application_id + user_id`, so `X-AI-Builder-Delegated-User-Id` is the value
that prevents different ai-builder users from sharing the same Code sandbox.

Expected response fields:

```json
{
  "applicationId": "91001",
  "workspaceId": "93001",
  "sandboxInstanceId": "sandbox-93001",
  "conversationId": "conversation-93001",
  "runtimeSessionId": "runtime-xxx",
  "specReviewUrl": "https://runtime.example.com/workspaces/93001/builder?token=entry-token"
}
```

`specReviewUrl` or `builderUrl` is required. ai-builder derives the runtime proxy base from that URL and does not expose the upstream URL directly to the browser.

## Items d-ai-code should keep/support

- Continue supporting `window.__APAAS_SHELL__.externalBasePath` for all runtime API paths.
- Continue supporting `window.__APAAS_SHELL__.webConsoleOrigin` for parent-window `postMessage`.
- If runtime cookies are used for workspace/session auth, set them from the runtime response; ai-builder rewrites cookie path to the proxy prefix and forwards them on subsequent proxied requests.
- Production builder assets should ideally be served relative to the builder base path or through an explicit external base path. ai-builder currently rewrites Vite dev absolute paths such as `/@vite`, `/src`, `/node_modules`, `/@id`, `/@fs` for local development.
- Event streams and long-running APIs should work behind a reverse proxy under `/api/code-runtime/{sessionId}`.

## Observed local-dev limitations

- `DOLPHIN_CODE_BUILDER_URL=http://127.0.0.1:5173/builder/` is a development fallback only. It maps every app to one local builder instance and does not create isolated workspaces.
- Firefox Playwright reported a local font download failure for `Geist Sans` and d-ai-code reported an antd `Drawer width` deprecation warning. Neither blocked the integration flow.

## Environment variables

- `DOLPHIN_CODE_CONTROL_PLANE_URL`: production Control Plane base URL. Default is `http://127.0.0.1:8080`.
- `DOLPHIN_CODE_CONTROL_PLANE_TOKEN`: optional bearer token for Control Plane requests.
- `DOLPHIN_CODE_BUILDER_URL`: local development fallback builder URL. Do not use this as the production runtime isolation mechanism.
