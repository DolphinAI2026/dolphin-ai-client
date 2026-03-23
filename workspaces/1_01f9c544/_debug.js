
const path = require('path')
const cliBase = process.env.DF_APAAS_CLI_PATH || '/Users/mars/.nvm/versions/node/v22.22.0/lib/node_modules/@x-apaas/df-apaas-cli'
const puppeteer = require(path.join(cliBase, 'node_modules/puppeteer-core'))
const os = require('os')

const localServerRunningAt = 'https://localhost:8083/'
const targetEnv = 'app'
const tenantId = '566642786573484033'
const appId = '806997227284201472'
const outputName = 'form-component-star-rating'
const customWidgetList = [{"code": "FORM_CUSTOM_COMPONENT_STAR_RATING", "text": "star-rating", "description": "star-rating"}]

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
          console.log('[DEBUG] ✅ Component injected!');
        };
        s2.onerror = function() { window.__APAAS_DEBUG_INJECTED__ = false; };
        document.head.appendChild(s2);
      }, 2000);
    }
  }, 1000);
})`

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
  const injectParams = { localServerRunningAt, outputName, targetEnv, customWidgetList, tenantId, appId }
  const injectCall = `${INJECT_CODE}(${JSON.stringify(injectParams)})`
  await page.evaluateOnNewDocument(injectCall)
  try {
    await page.goto('https://apaas-dev8.dfy.definesys.cn/platform//', { waitUntil: 'domcontentloaded', timeout: 120000 })
  } catch(e) { console.log('Nav issue:', e.message.split('\n')[0]) }
  await page.evaluate(injectCall)
  console.log('✅ Debug active')
  await new Promise(r => browser.on('disconnected', r))
  process.exit(0)
})()
