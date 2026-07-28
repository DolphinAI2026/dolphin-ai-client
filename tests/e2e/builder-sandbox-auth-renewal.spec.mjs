import assert from "node:assert/strict";
import fs from "node:fs";
import { chromium, firefox } from "playwright";

const builder = process.env.BUILDER_BASE_URL;
const controlPlane = process.env.CONTROL_PLANE_BASE_URL;
const clock = process.env.CLOCK_CONTROL_URL;
const clockNonce = process.env.CLOCK_NONCE;
const accessToken = process.env.BUILDER_ACCESS_TOKEN;
const sessionRef = process.env.BUILDER_SESSION_REF;
const databasePath = process.env.BUILDER_DATABASE_PATH;
const secretEvidencePath = process.env.BROWSER_SECRET_EVIDENCE_PATH;

for (const [name, value] of Object.entries({
  builder,
  controlPlane,
  clock,
  clockNonce,
  accessToken,
  sessionRef,
  databasePath,
  secretEvidencePath,
})) {
  assert.ok(value, `${name} is required`);
}

const browserErrors = [];
const response401s = [];
const runtimeCookies = new Set();

async function jsonFetch(page, path, options = {}) {
  return page.evaluate(
    async ({ path, options }) => {
      const response = await fetch(path, options);
      const text = await response.text();
      let body = null;
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = text;
      }
      return { status: response.status, body };
    },
    { path, options },
  );
}

function assertSafeEmbedUrl(embedUrl) {
  const parsed = new URL(embedUrl, builder);
  assert.equal(parsed.searchParams.has("token"), false, "launch token leaked to browser URL");
  assert.ok(parsed.searchParams.get("dolphin_token"), "signed embed token missing");
}

function browserSessionId(embedUrl) {
  const token = new URL(embedUrl, builder).searchParams.get("dolphin_token");
  assert.ok(token, "signed embed token missing");
  const payload = JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString());
  return payload.bsid;
}

async function runtimeCookie(context) {
  const cookies = await context.cookies(
    `${builder}/api/code-runtime/${sessionRef}/api/status`,
  );
  const cookie = cookies.find((item) => item.name === "apaas_sandbox_token");
  assert.ok(cookie?.value, "runtime cookie missing");
  runtimeCookies.add(cookie.value);
  return cookie.value;
}

async function establish(page, context, opened) {
  const response = await jsonFetch(page, opened.body.embed_url);
  assert.notEqual(response.status, 401, "embed bootstrap exposed 401");
  return runtimeCookie(context);
}

async function state() {
  const response = await fetch(`${controlPlane}/__control/state`);
  assert.equal(response.status, 200);
  return response.json();
}

async function setMode(mode) {
  const response = await fetch(`${controlPlane}/__control/mode`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  assert.equal(response.status, 200);
}

async function advance(duration = "20m") {
  const response = await fetch(`${clock}/advance`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${clockNonce}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ duration }),
  });
  assert.equal(response.status, 200);
  return response.json();
}

const chromiumBrowser = await chromium.launch();
const firefoxBrowser = await firefox.launch();

try {
  const contexts = await Promise.all(
    [chromiumBrowser, firefoxBrowser].map((browser) =>
      browser.newContext({
        extraHTTPHeaders: { Authorization: `Bearer ${accessToken}` },
      }),
    ),
  );
  const pages = await Promise.all(contexts.map((context) => context.newPage()));
  for (const page of pages) {
    page.on("console", (message) => {
      if (message.type() === "error") browserErrors.push(`console:${message.text()}`);
    });
    page.on("pageerror", (error) => browserErrors.push(`pageerror:${error.message}`));
    page.on("requestfailed", (request) =>
      browserErrors.push(`requestfailed:${request.url()}:${request.failure()?.errorText}`),
    );
    page.on("response", (response) => {
      if (response.status() === 401) response401s.push(response.url());
    });
    const ready = await page.goto(`${builder}/api/code/internal/sandbox-auth-state`);
    assert.equal(ready.status(), 200);
  }

  const opened = await Promise.all(
    pages.map((page) =>
      jsonFetch(page, `/api/code/sessions/${sessionRef}/open`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
  opened.forEach((item) => {
    assert.equal(item.status, 200, JSON.stringify(item.body));
    assertSafeEmbedUrl(item.body.embed_url);
  });
  const ids = opened.map((item) => browserSessionId(item.body.embed_url));
  assert.notEqual(ids[0], ids[1], "browser_session_id must be isolated");
  const initialCookies = await Promise.all(
    opened.map((item, index) => establish(pages[index], contexts[index], item)),
  );
  assert.ok(initialCookies[0] !== initialCookies[1], "runtime cookies must be isolated");
  assert.equal((await state()).open_count, 2);

  const statusPath = `/api/code-runtime/${sessionRef}/api/status`;
  const initialOpenCount = (await state()).open_count;
  const chromiumCookie = initialCookies[0];

  for (let step = 1; step <= 5; step += 1) {
    await advance("20m");
    const active = await jsonFetch(pages[0], statusPath);
    assert.equal(active.status, 200, JSON.stringify(active.body));
    assert.ok(
      (await runtimeCookie(contexts[0])) === chromiumCookie,
      `active Session value changed at minute ${step * 20}`,
    );
    assert.equal(
      (await state()).open_count,
      initialOpenCount,
      `normal activity reopened workspace at minute ${step * 20}`,
    );
  }

  await advance("20m");
  const absoluteRecovery = await jsonFetch(pages[0], statusPath);
  assert.equal(absoluteRecovery.status, 200, JSON.stringify(absoluteRecovery.body));
  const recoveredChromiumCookie = await runtimeCookie(contexts[0]);
  assert.ok(
    recoveredChromiumCookie !== chromiumCookie,
    "absolute expiry did not create one new Session",
  );
  assert.equal((await state()).open_count, initialOpenCount + 1);

  const chromiumAfterOwnRecovery = await runtimeCookie(contexts[0]);
  const firefoxRecovery = await jsonFetch(pages[1], statusPath);
  assert.equal(firefoxRecovery.status, 200, JSON.stringify(firefoxRecovery.body));
  const recoveredFirefoxCookie = await runtimeCookie(contexts[1]);
  assert.ok(recoveredFirefoxCookie !== initialCookies[1], "Firefox Session did not recover");
  assert.ok(
    (await runtimeCookie(contexts[0])) === chromiumAfterOwnRecovery,
    "Firefox recovery changed the Chromium Session",
  );
  assert.ok(
    recoveredFirefoxCookie !== chromiumAfterOwnRecovery,
    "Firefox recovery reused the Chromium Session",
  );
  assert.equal((await state()).open_count, initialOpenCount + 2);

  await setMode("access_expired");
  await advance("31m");
  const refreshed = await jsonFetch(pages[0], statusPath);
  assert.equal(refreshed.status, 200, JSON.stringify(refreshed.body));
  const refreshedState = await state();
  assert.equal(refreshedState.refresh_count, 1, "access rejection must force one refresh");

  assert.deepEqual(browserErrors, [], browserErrors.join("\n"));
  assert.deepEqual(response401s, [], `recoverable 401 became visible: ${response401s.join(",")}`);
  browserErrors.length = 0;
  response401s.length = 0;

  await setMode("refresh_invalid");
  await advance("31m");
  const refreshInvalid = await jsonFetch(pages[1], statusPath);
  assert.equal(refreshInvalid.status, 401);
  const hardFailureState = await state();
  const opensAfterFailure = hardFailureState.open_count;
  const secondHardFailure = await jsonFetch(pages[1], statusPath);
  assert.equal(secondHardFailure.status, 401);
  assert.equal((await state()).open_count, opensAfterFailure, "hard failure must not loop");

  await setMode("account_disabled");
  await advance("31m");
  const accountDisabled = await jsonFetch(pages[0], statusPath);
  assert.equal(accountDisabled.status, 403);
  const accountDisabledOpens = (await state()).open_count;
  assert.equal((await jsonFetch(pages[0], statusPath)).status, 401);
  assert.equal((await state()).open_count, accountDisabledOpens, "disabled account must not loop");

  await setMode("ok");
  const reopened = await jsonFetch(pages[0], `/api/code/sessions/${sessionRef}/open`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  assert.equal(reopened.status, 200, JSON.stringify(reopened.body));
  assertSafeEmbedUrl(reopened.body.embed_url);
  await establish(pages[0], contexts[0], reopened);
  await setMode("tenant_unbound");
  await advance("31m");
  const tenantUnbound = await jsonFetch(pages[0], statusPath);
  assert.equal(tenantUnbound.status, 403);
  const tenantUnboundOpens = (await state()).open_count;
  assert.equal((await jsonFetch(pages[0], statusPath)).status, 401);
  assert.equal((await state()).open_count, tenantUnboundOpens, "unbound tenant must not loop");

  assert.ok(fs.statSync(databasePath).size > 0, "SQLite fixture database is empty");
  fs.writeFileSync(
    secretEvidencePath,
    JSON.stringify({ runtime_cookies: [...runtimeCookies] }),
    { encoding: "utf8", mode: 0o600 },
  );
  console.log("L3_BROWSER_AUTH_RENEWAL=PASS");
} finally {
  await Promise.allSettled([chromiumBrowser.close(), firefoxBrowser.close()]);
}
