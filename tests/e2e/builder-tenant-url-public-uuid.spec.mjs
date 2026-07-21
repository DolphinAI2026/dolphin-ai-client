import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.BUILDER_PLAYWRIGHT_MODULE || "playwright");

const required = {
  builderBaseUrl: process.env.BUILDER_BASE_URL,
  browserChannel: process.env.BROWSER_CHANNEL,
  buildSha: process.env.BUILDER_BUILD_SHA,
  currentTenantId: process.env.BUILDER_CURRENT_TENANT_UUID,
  targetTenantId: process.env.BUILDER_TARGET_TENANT_UUID,
  disabledTenantId: process.env.BUILDER_DISABLED_TENANT_UUID,
  unauthorizedTenantId: process.env.BUILDER_UNAUTHORIZED_TENANT_UUID,
  username: process.env.BUILDER_E2E_USERNAME,
  password: process.env.BUILDER_E2E_PASSWORD,
  codeSessionRef: process.env.BUILDER_CODE_SESSION_REF,
  agentSessionId: process.env.BUILDER_AGENT_SESSION_ID,
};

for (const [name, value] of Object.entries(required)) {
  assert.ok(value, `${name} is required`);
}

assert.match(required.buildSha, /^[0-9a-f]{40}$/);
assert.ok(
  required.browserChannel === "chromium" || required.browserChannel === "msedge",
  `unsupported browser channel: ${required.browserChannel}`,
);

const appBase = `${required.builderBaseUrl.replace(/\/+$/, "")}/ai-builder`;
const authWhitelist = new Set([
  "/ai-builder/api/auth/me",
  "/ai-builder/api/auth/me/tenants",
  "/ai-builder/api/auth/switch-tenant",
  "/ai-builder/api/apaas/status",
]);

function appUrl(path) {
  return `${appBase}${path.startsWith("/") ? path : `/${path}`}`;
}

function routeTenantId(page) {
  return new URL(page.url()).searchParams.get("tenantId");
}

async function launchBrowser() {
  if (required.browserChannel === "chromium") {
    return chromium.launch();
  }
  return chromium.launch({ channel: "msedge" });
}

async function login(page, redirect = "/") {
  const loginUrl = new URL(appUrl("/login"));
  loginUrl.searchParams.set("redirect", redirect);
  await page.goto(loginUrl.toString());
  await page.getByPlaceholder("账号").fill(required.username);
  await page.getByPlaceholder("密码").fill(required.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), {
    timeout: 20_000,
  });
}

async function withContext(browser, fn) {
  const context = await browser.newContext();
  try {
    await fn(context);
  } finally {
    await context.close();
  }
}

async function waitForTenant(page, tenantId) {
  await page.waitForURL((url) => url.searchParams.get("tenantId") === tenantId, {
    timeout: 20_000,
  });
}

function isTenantSwitchResponse(response) {
  const request = response.request();
  const url = new URL(response.url());
  return request.method() === "POST"
    && url.pathname === "/ai-builder/api/auth/switch-tenant";
}

async function navigateAndWaitForTenantSwitch(page, url, tenantId) {
  const responsePromise = page.waitForResponse(isTenantSwitchResponse, {
    timeout: 20_000,
  });
  await page.goto(url);
  const response = await responsePromise;
  assert.equal(response.status(), 200, `tenant switch failed: ${response.status()}`);
  await waitForTenant(page, tenantId);
}

const browser = await launchBrowser();
const browserErrors = [];

try {
  await withContext(browser, async (context) => {
    const page = await context.newPage();
    page.on("pageerror", (error) => browserErrors.push(`pageerror:${error.message}`));

    await login(page, "/apps?tab=legacy#old-link");
    await waitForTenant(page, required.currentTenantId);
    const current = new URL(page.url());
    assert.equal(current.pathname, "/ai-builder/apps");
    assert.equal(current.searchParams.get("tab"), "legacy");
    assert.equal(current.hash, "#old-link");
  });

  await withContext(browser, async (context) => {
    const page = await context.newPage();
    const switchRequests = [];

    page.on("request", (request) => {
      const url = new URL(request.url());
      if (
        request.method() === "POST"
        && url.pathname === "/ai-builder/api/auth/switch-tenant"
      ) {
        switchRequests.push(request.url());
      }
    });

    await login(page);
    await waitForTenant(page, required.currentTenantId);
    await navigateAndWaitForTenantSwitch(
      page,
      appUrl(`/apps?tenantId=${required.targetTenantId}&view=authorized#target`),
      required.targetTenantId,
    );

    assert.equal(switchRequests.length, 1, JSON.stringify(switchRequests));
  });

  for (const rejectedTenantId of [
    required.unauthorizedTenantId,
    required.disabledTenantId,
  ]) {
    await withContext(browser, async (context) => {
      const page = await context.newPage();
      const rejectedBusinessRequests = [];
      let rejectedNavigationActive = false;

      page.on("request", (request) => {
        if (!rejectedNavigationActive) return;
        const url = new URL(request.url());
        if (
          routeTenantId(page) === rejectedTenantId
          && url.pathname.startsWith("/ai-builder/api/")
          && !authWhitelist.has(url.pathname)
        ) {
          rejectedBusinessRequests.push(request.url());
        }
      });

      await login(page);
      await waitForTenant(page, required.currentTenantId);
      rejectedNavigationActive = true;
      await page.goto(
        appUrl(
          `/code/${required.codeSessionRef}?tenantId=${rejectedTenantId}`
          + `&agent=${encodeURIComponent(required.agentSessionId)}`,
        ),
      );
      await waitForTenant(page, required.currentTenantId);
      rejectedNavigationActive = false;

      assert.deepEqual(
        rejectedBusinessRequests,
        [],
        `rejected target issued business requests:\n${rejectedBusinessRequests.join("\n")}`,
      );
      assert.equal(await page.locator("iframe.code-frame").count(), 0);
    });
  }

  await withContext(browser, async (context) => {
    const page = await context.newPage();
    const activationRequests = [];
    const legacyActivationRequests = [];
    const code401s = [];

    page.on("request", (request) => {
      const url = new URL(request.url());
      if (
        request.method() === "POST"
        && url.pathname
          === `/ai-builder/api/code/sessions/${required.codeSessionRef}`
            + `/agent-sessions/${required.agentSessionId}/activate`
      ) {
        activationRequests.push(request.url());
      }
      if (
        request.method() === "POST"
        && url.pathname.startsWith("/ai-builder/api/code-runtime/")
        && url.pathname.endsWith("/activate")
      ) {
        legacyActivationRequests.push(request.url());
      }
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (
        response.status() === 401
        && (
          url.pathname
            === `/ai-builder/api/code/sessions/${required.codeSessionRef}`
              + `/agent-sessions/${required.agentSessionId}/activate`
          || (
            url.pathname.startsWith("/ai-builder/api/code-runtime/")
            && url.pathname.endsWith("/activate")
          )
        )
      ) {
        code401s.push(response.url());
      }
    });

    const redirect = `/code/${required.codeSessionRef}`
      + `?tenantId=${required.currentTenantId}`
      + `&agent=${encodeURIComponent(required.agentSessionId)}`;
    await login(page, redirect);
    await page.waitForURL((url) => (
      url.pathname === `/ai-builder/code/${required.codeSessionRef}`
      && url.searchParams.get("tenantId") === required.currentTenantId
      && url.searchParams.get("agent") === required.agentSessionId
    ), { timeout: 20_000 });

    const frame = page.locator("iframe.code-frame").first();
    await frame.waitFor({ state: "attached", timeout: 20_000 });
    const frameSrc = await frame.getAttribute("src");
    assert.ok(frameSrc, "Code iframe src is missing");
    assert.equal(new URL(frameSrc, required.builderBaseUrl).searchParams.has("tenantId"), false);
    assert.equal(activationRequests.length, 1, JSON.stringify(activationRequests));
    assert.deepEqual(legacyActivationRequests, []);
    assert.deepEqual(code401s, []);
  });

  await withContext(browser, async (context) => {
    const first = await context.newPage();
    const second = await context.newPage();
    let switchCount = 0;

    for (const page of [first, second]) {
      page.on("request", (request) => {
        const url = new URL(request.url());
        if (
          request.method() === "POST"
          && url.pathname === "/ai-builder/api/auth/switch-tenant"
        ) {
          switchCount += 1;
        }
      });
    }

    await login(first);
    await waitForTenant(first, required.currentTenantId);
    await second.goto(appUrl(`/?tenantId=${required.currentTenantId}`));
    await waitForTenant(second, required.currentTenantId);

    await navigateAndWaitForTenantSwitch(
      first,
      appUrl(`/?tenantId=${required.targetTenantId}`),
      required.targetTenantId,
    );
    await waitForTenant(second, required.targetTenantId);

    await navigateAndWaitForTenantSwitch(
      second,
      appUrl(`/?tenantId=${required.currentTenantId}`),
      required.currentTenantId,
    );
    await waitForTenant(first, required.currentTenantId);

    assert.equal(switchCount, 2, `unexpected cross-tab switch count: ${switchCount}`);
  });

  assert.deepEqual(browserErrors, [], browserErrors.join("\n"));
  console.log(
    `TENANT_URL_E2E=PASS channel=${required.browserChannel} build_sha=${required.buildSha}`,
  );
} finally {
  await browser.close();
}
