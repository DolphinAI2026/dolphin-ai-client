import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium, request } = require("playwright");

const required = {
  origin: process.env.BUILDER_ORIGIN,
  revision: process.env.DEPLOYED_REVISION,
  image: process.env.BUILDER_IMAGE,
  namespace: process.env.KUBE_NAMESPACE,
  selector: process.env.KUBE_LABEL_SELECTOR,
  backendContainer: process.env.KUBE_BACKEND_CONTAINER,
  distInitContainer: process.env.KUBE_DIST_INIT_CONTAINER,
  webContainer: process.env.KUBE_WEB_CONTAINER,
  username: process.env.BUILDER_SMOKE_USERNAME,
  password: process.env.BUILDER_SMOKE_PASSWORD,
  tenantName: process.env.BUILDER_SMOKE_TENANT_NAME,
  codeSessionId: process.env.BUILDER_SMOKE_CODE_SESSION_ID,
};

for (const [name, value] of Object.entries(required)) {
  assert.ok(value, `${name} is required`);
}

assert.match(required.origin, /^https?:\/\/[^/\s]+(?:\/[^?\s]*)?$/);
assert.match(required.revision, /^[0-9a-f]{40}$/);
assert.match(required.image, /@sha256:[0-9a-f]{64}$/);

const origin = required.origin.replace(/\/+$/, "");
const appBase = `${origin}/ai-builder`;
const agentId = process.env.BUILDER_SMOKE_AGENT_ID || "";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function authorization(token) {
  return { Authorization: `Bearer ${token}` };
}

async function jsonResponse(response, message) {
  assert.equal(response.status(), 200, message);
  return response.json();
}

async function login(api) {
  const response = await api.post("/ai-builder/api/auth/login", {
    data: {
      username: required.username,
      password: required.password,
    },
  });
  const payload = await jsonResponse(response, "controlled login failed");
  if (!payload.requires_tenant_selection) {
    assert.ok(payload.access_token, "login did not return an access token");
    return payload.access_token;
  }

  assert.ok(payload.selection_token, "tenant selection token is missing");
  assert.ok(Array.isArray(payload.tenants), "tenant selection choices are missing");
  const selected = payload.tenants.find(
    (tenant) => tenant.tenant_name === required.tenantName,
  );
  assert.ok(selected, "configured smoke tenant is unavailable at login");
  assert.match(selected.tenant_public_id, uuidPattern);
  const selection = await api.post("/ai-builder/api/auth/select-tenant", {
    data: {
      selection_token: payload.selection_token,
      tenant_id: selected.tenant_id,
    },
  });
  const selectedPayload = await jsonResponse(selection, "tenant selection failed");
  assert.ok(selectedPayload.access_token, "tenant selection did not return an access token");
  return selectedPayload.access_token;
}

async function getMe(api, token, message) {
  const response = await api.get("/ai-builder/api/auth/me", {
    headers: authorization(token),
  });
  const payload = await jsonResponse(response, message);
  assert.match(payload.tenant_public_id || "", uuidPattern);
  return payload;
}

async function availableTenants(api, token) {
  const response = await api.get("/ai-builder/api/auth/me/tenants", {
    headers: authorization(token),
  });
  const tenants = await jsonResponse(response, "available tenant lookup failed");
  assert.ok(Array.isArray(tenants), "available tenant response is not a list");
  assert.ok(tenants.length > 1, "smoke account needs another accessible tenant");
  for (const tenant of tenants) {
    assert.ok(Number.isInteger(tenant.tenant_id), "available tenant lacks numeric ID");
    assert.match(tenant.tenant_public_id || "", uuidPattern);
  }
  return tenants;
}

async function switchTenant(api, sourceToken, tenantId, expectedPublicId) {
  const response = await api.post("/ai-builder/api/auth/switch-tenant", {
    headers: authorization(sourceToken),
    data: { tenant_id: tenantId },
  });
  const payload = await jsonResponse(response, "tenant switch failed");
  assert.ok(payload.access_token, "tenant switch did not return an access token");
  const candidate = await getMe(
    api,
    payload.access_token,
    "candidate token /auth/me verification failed",
  );
  assert.equal(
    candidate.tenant_public_id,
    expectedPublicId,
    "candidate token tenant UUID mismatch",
  );
  return payload.access_token;
}

function codeUrl(tenantPublicId) {
  const url = new URL(
    `${appBase}/code/${encodeURIComponent(required.codeSessionId)}`,
  );
  url.searchParams.set("tenantId", tenantPublicId);
  if (agentId) url.searchParams.set("agent", agentId);
  return url.toString();
}

function isNewActivation(response) {
  const request = response.request();
  const url = new URL(response.url());
  return request.method() === "POST"
    && url.pathname.startsWith(
      `/ai-builder/api/code/sessions/${required.codeSessionId}/agent-sessions/`,
    )
    && url.pathname.endsWith("/activate");
}

function isLegacyActivation(request) {
  const url = new URL(request.url());
  return request.method() === "POST"
    && url.pathname.startsWith("/ai-builder/api/code-runtime/")
    && url.pathname.endsWith("/activate");
}

function isCode401(response) {
  if (response.status() !== 401) return false;
  const url = new URL(response.url());
  return url.pathname.startsWith("/ai-builder/api/code/");
}

const api = await request.newContext({ baseURL: origin });
const browser = await chromium.launch({ channel: "msedge" });

try {
  let token = await login(api);
  let current = await getMe(api, token, "initial /auth/me verification failed");
  const tenants = await availableTenants(api, token);
  const target = tenants.find((tenant) => tenant.tenant_name === required.tenantName);
  assert.ok(target, "configured smoke tenant is not available");

  if (current.tenant_public_id === target.tenant_public_id) {
    const alternate = tenants.find(
      (tenant) => tenant.tenant_public_id !== target.tenant_public_id,
    );
    assert.ok(alternate, "no alternate accessible tenant is available");
    token = await switchTenant(
      api,
      token,
      alternate.tenant_id,
      alternate.tenant_public_id,
    );
    current = await getMe(api, token, "alternate tenant verification failed");
  }

  assert.notEqual(
    current.tenant_public_id,
    target.tenant_public_id,
    "tenant switch must start from another accessible tenant",
  );
  const candidateToken = await switchTenant(
    api,
    token,
    target.tenant_id,
    target.tenant_public_id,
  );

  const context = await browser.newContext();
  try {
    await context.addInitScript((accessToken) => {
      localStorage.setItem("token", accessToken);
    }, candidateToken);
    const page = await context.newPage();
    const newActivations = [];
    const legacyActivations = [];
    const code401s = [];

    page.on("request", (entry) => {
      if (isLegacyActivation(entry)) legacyActivations.push(entry);
    });
    page.on("response", (entry) => {
      if (isNewActivation(entry)) newActivations.push(entry);
      if (isCode401(entry)) code401s.push(entry);
    });

    await page.goto(codeUrl(target.tenant_public_id));
    await page.waitForURL((url) => (
      url.pathname === `/ai-builder/code/${required.codeSessionId}`
      && url.searchParams.get("tenantId") === target.tenant_public_id
      && (!agentId || url.searchParams.get("agent") === agentId)
    ), { timeout: 20_000 });
    const frame = page.locator("iframe.code-frame").first();
    await frame.waitFor({ state: "attached", timeout: 20_000 });
    const frameSrc = await frame.getAttribute("src");
    assert.ok(frameSrc, "Code iframe src is missing");
    assert.equal(
      new URL(frameSrc, origin).searchParams.has("tenantId"),
      false,
      "outer tenantId leaked into Code iframe src",
    );
    await page.waitForTimeout(500);
    assert.ok(newActivations.length > 0, "new Code activation endpoint was not called");
    for (const response of newActivations) {
      assert.equal(response.status(), 200, "new Code activation did not return 200");
    }
    assert.equal(legacyActivations.length, 0, "legacy Code activation endpoint was called");
    assert.equal(code401s.length, 0, "Code endpoint returned 401");
    const pageText = await page.locator("body").innerText();
    assert.equal(
      pageText.includes("Code runtime token required"),
      false,
      "Code runtime reported a token requirement",
    );
  } finally {
    await context.close();
  }

  console.log(`RELEASE_BROWSER_SMOKE=PASS revision=${required.revision}`);
} finally {
  await browser.close();
  await api.dispose();
}
