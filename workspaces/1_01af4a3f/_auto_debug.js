
const path = require('path')
const fs = require('fs')
const cliBase = process.env.DF_APAAS_CLI_PATH || '/Users/mars/.nvm/versions/node/v22.22.0/lib/node_modules/@x-apaas/df-apaas-cli'
const puppeteer = require(path.join(cliBase, 'node_modules/puppeteer-core'))
const os = require('os')

const localServerRunningAt = 'https://localhost:8086/'
const tenantId = '566642786573484033'
const appId = '806997227284201472'
const outputName = 'form-page-map-view'
const customWidgetList = []

const INJECT_CODE = `(function(params) {
  if (window.__APAAS_DEBUG_INJECTED__) return;
  var checkInterval = setInterval(function() {
    if (window.APaaSSDK && window.df && window.Vue && window.Vue.FormEngine && !window.location.href.includes('/login')) {
      clearInterval(checkInterval);
      if (window.__APAAS_DEBUG_INJECTED__) return;
      window.__APAAS_DEBUG_INJECTED__ = true;
      console.log('[DEBUG] Injecting component...');
      setTimeout(function() {
        var s1 = document.createElement('script');
        s1.src = params.localServerRunningAt + 'js/chunk-vendors.js';
        s1.async = false;
        document.head.appendChild(s1);
        var s2 = document.createElement('script');
        s2.src = params.localServerRunningAt + 'js/app.js';
        s2.async = false;
        s2.onload = function() {
          try {
            var mod = window[params.outputName];
            if (mod && mod.default) mod.default.install(window.Vue);
          } catch(e) { console.warn('[DEBUG] install error:', e.message); }
          try {
            window.Vue.FormEngine.WidgetControl.customComponentEffectMap.set(
              params.customWidgetList[0].code,
              { appIdList: [params.appId], tenantId: params.tenantId }
            );
          } catch(e) {}
          function r() { try { window.APaaSSDK.context.XEventBus.emit('refreshGroupWidgetList'); } catch(e) {} }
          r(); setTimeout(r,1000); setTimeout(r,3000); setTimeout(r,5000);
          console.log('[DEBUG] Component injected!');
        };
        s2.onerror = function() { window.__APAAS_DEBUG_INJECTED__ = false; };
        document.head.appendChild(s2);
      }, 2000);
    }
  }, 1000);
})`

const screenshotsDir = '/Users/mars/Vibe Coding/apaas-builder-ai/workspaces/1_01af4a3f/debug/screenshots'
const resultPath = '/Users/mars/Vibe Coding/apaas-builder-ai/workspaces/1_01af4a3f/debug/result.json'

;(async () => {
  const realArch = os.arch()
  let executablePath
  if (realArch === 'x64') {
    executablePath = path.resolve(cliBase, 'bin/chromium-r1095492-111.0.5555.0/mac/Chromium.app/Contents/MacOS/Chromium')
  } else {
    executablePath = path.resolve(cliBase, 'bin/chromium-r1095492-111.0.5555.0/mac_arm/Chromium.app/Contents/MacOS/Chromium')
  }

  const browser = await puppeteer.launch({
    args: ['--start-maximized', '--ignore-certificate-errors', '--no-sandbox'],
    ignoreDefaultArgs: ['--disable-extensions'],
    executablePath, headless: false, defaultViewport: null
  })
  const pages = await browser.pages()
  const page = pages[0]

  const result = { status: 'ok', screenshots: [], message: '' }

  try {
    // Step 1: Navigate to login page
    console.log('[AUTO-DEBUG] Navigating to login...')
    await page.goto('https://apaas-dev8.dfy.definesys.cn/platform//account/login', { waitUntil: 'networkidle2', timeout: 120000 })
    await page.waitForTimeout(2000)

    // Step 2: Auto-fill credentials and login
    console.log('[AUTO-DEBUG] Filling login form...')
    const inputs = await page.$$('input')
    if (inputs.length >= 2) {
      await inputs[0].click({ clickCount: 3 })
      await inputs[0].type('17621440039')
      const pwdInput = await page.$('input[type="password"]') || inputs[1]
      await pwdInput.click({ clickCount: 3 })
      await pwdInput.type('definesys2019')
    }
    await page.waitForTimeout(500)

    // Click login button
    const loginBtn = await page.evaluateHandle(() => {
      const buttons = Array.from(document.querySelectorAll('button'))
      return buttons.find(b => b.textContent.includes('登录')) || buttons[0]
    })
    if (loginBtn) {
      await loginBtn.click()
    }

    // Wait for login to complete (URL should change away from /login)
    console.log('[AUTO-DEBUG] Waiting for login...')
    await page.waitForFunction(
      () => !window.location.href.includes('/login'),
      { timeout: 120000 }
    )
    await page.waitForTimeout(2000)
    console.log('[AUTO-DEBUG] Login successful!')

    // Step 3: Set up component injection
    const injectParams = { localServerRunningAt, outputName, targetEnv: 'app', customWidgetList, tenantId, appId }
    const injectCall = `${INJECT_CODE}(${JSON.stringify(injectParams)})`
    await page.evaluateOnNewDocument(injectCall)

    // Step 4: Navigate to target page
    console.log('[AUTO-DEBUG] Navigating to app debug target...')
    await page.goto('https://apaas-dev8.dfy.definesys.cn/platform//account/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
    await page.evaluate(injectCall)

    // Step 5: Wait for page load + component injection
    console.log('[AUTO-DEBUG] Waiting for component injection...')
    await page.waitForTimeout(8000)

    // Step 6: Take full-page screenshot
    console.log('[AUTO-DEBUG] Taking screenshot...')
    await page.screenshot({
      path: path.join(screenshotsDir, 'page.png'),
      fullPage: true
    })
    result.screenshots.push('page.png')

    // Step 7: Try to screenshot component panel
    try {
      const panel = await page.$('.widget-list, .custom-component-panel, [class*="widget"]')
      if (panel) {
        await panel.screenshot({
          path: path.join(screenshotsDir, 'panel.png')
        })
        result.screenshots.push('panel.png')
      }
    } catch(e) {
      console.log('[AUTO-DEBUG] Panel screenshot skipped:', e.message)
    }

    result.message = 'Auto debug completed successfully'
  } catch(e) {
    result.status = 'error'
    result.message = e.message
    console.error('[AUTO-DEBUG] Error:', e.message)

    // Take error screenshot
    try {
      await page.screenshot({
        path: path.join(screenshotsDir, 'page.png'),
        fullPage: true
      })
      result.screenshots.push('page.png')
    } catch(e2) {}
  }

  // Write result JSON
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2))
  console.log('[AUTO-DEBUG] Result written to', resultPath)

  // Keep browser open
  await new Promise(r => browser.on('disconnected', r))
  process.exit(0)
})()
