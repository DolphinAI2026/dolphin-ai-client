const fs = require('fs');
const path = require('path');

// 支持两种调用方式：
// 1. node patch_vscode_chat_fallback.js /explicit/path/to/workbench.js
// 2. 自动检测（通过 codeServerResolver）
let workbenchPath = process.argv[2];
if (!workbenchPath || !fs.existsSync(workbenchPath)) {
  try {
    const { resolve } = require('./lib/codeServerResolver');
    const csInfo = resolve(workbenchPath && !fs.existsSync(workbenchPath) ? null : workbenchPath);
    workbenchPath = csInfo.workbenchPath;
    console.log(`Auto-detected code-server ${csInfo.version}: ${workbenchPath}`);
  } catch {
    // Fallback: 兼容旧的候选路径方式
    const HOME = process.env.HOME || '';
    const candidatePaths = [
      '/usr/local/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js',
      '/usr/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js',
      `${HOME}/.local/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js`,
    ].filter(Boolean);
    // 扫描所有 code-server-* 版本目录
    const libDir = path.join(HOME, '.local', 'lib');
    if (fs.existsSync(libDir)) {
      for (const entry of fs.readdirSync(libDir).sort().reverse()) {
        if (entry.startsWith('code-server')) {
          candidatePaths.push(path.join(libDir, entry, 'lib/vscode/out/vs/code/browser/workbench/workbench.js'));
        }
      }
    }
    workbenchPath = candidatePaths.find(p => { try { fs.accessSync(p); return true; } catch { return false; } });
    if (!workbenchPath) {
      console.error('Could not find workbench.js. Searched:\n' + candidatePaths.join('\n'));
      process.exit(1);
    }
  }
}
const templatePath = path.join(__dirname, 'patch_vscode_chat_fallback.template.txt');

const startMarker = 'async activateDefaultAgent(e){';
const endMarker = '}getSession(e){';

const source = fs.readFileSync(workbenchPath, 'utf8');
const replacement = fs.readFileSync(templatePath, 'utf8');
const vsdaSnippet = 'createNewMessage:i=>i,validate:()=>!0,dispose:()=>{}}';
const vsdaReplacementSnippet = 'createNewMessage:i=>i,validate:()=>"ok",dispose:()=>{}}';

let updated = source;
let changed = false;

function neutralizeLegacyMiniMaxExtension() {
  const home = process.env.HOME || '';
  if (!home) return false;
  const extensionsRoot = path.join(home, '.local', 'share', 'code-server', 'extensions');
  if (!fs.existsSync(extensionsRoot)) return false;

  let changedLegacy = false;
  for (const entry of fs.readdirSync(extensionsRoot)) {
    if (!/^apaas-builder\.minimax-chat-provider-/.test(entry)) continue;
    const pkgPath = path.join(extensionsRoot, entry, 'package.json');
    if (!fs.existsSync(pkgPath)) continue;

    const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
    const desiredActivationEvents = ['onStartupFinished', 'onChatParticipant:minimax'];
    const desiredLanguageModelChatProviders = [
      {
        vendor: 'copilot',
        displayName: 'MiniMax (via Copilot)',
      },
    ];
    const alreadyNeutralized =
      Array.isArray(pkg.activationEvents) &&
      pkg.activationEvents.join('|') === desiredActivationEvents.join('|') &&
      JSON.stringify(pkg.contributes?.languageModelChatProviders || []) === JSON.stringify(desiredLanguageModelChatProviders) &&
      (pkg.contributes?.chatParticipants || []).every(participant => participant.isDefault === false) &&
      pkg.__neutralizedByApaasBuilderAI;
    if (alreadyNeutralized) continue;

    fs.copyFileSync(pkgPath, `${pkgPath}.bak-neutralize-legacy-${Date.now()}`);
    pkg.activationEvents = desiredActivationEvents;
    if (pkg.contributes?.chatParticipants) {
      pkg.contributes.chatParticipants = pkg.contributes.chatParticipants.map(participant => ({
        ...participant,
        isDefault: false,
      }));
    }
    if (pkg.contributes) {
      pkg.contributes.languageModelChatProviders = desiredLanguageModelChatProviders;
    }
    delete pkg.__disabledByApaasBuilderAI;
    pkg.__neutralizedByApaasBuilderAI = {
      reason: 'Keep legacy extension only as VS Code Chat compatibility shell; default traffic is routed to apaas-builder.ruijing-ai',
      updatedAt: new Date().toISOString(),
    };
    fs.writeFileSync(pkgPath, `${JSON.stringify(pkg, null, 2)}\n`);
    console.log(`  Neutralized legacy MiniMax extension: ${entry}`);
    changedLegacy = true;
  }
  return changedLegacy;
}

const start = updated.indexOf(startMarker);
const end = updated.indexOf(endMarker, start);

if (start < 0 || end < 0) {
  console.error('Could not locate activateDefaultAgent method in workbench.js');
  process.exit(1);
}

const current = updated.slice(start, end + endMarker.length);
if (current !== replacement) {
  updated = updated.slice(0, start) + replacement + updated.slice(end + endMarker.length);
  changed = true;
}

if (updated.includes(vsdaSnippet)) {
  updated = updated.replace(vsdaSnippet, vsdaReplacementSnippet);
  changed = true;
}

// code-server 4.112 uses a class-based VSDA loader that still tries to fetch
// node_modules/vsda/rust/web/vsda.js and vsda_bg.wasm in the browser. The
// files are absent in our deployment and the built-in signing path is not used
// by ruijing-ai, so replace the loader with a no-op validator/signer.
const vsdaWebStart = 'async j(){const e=new r5;let[t]=await Promise.all([this.k(),new Promise((n,o)=>{Sf("vsda","rust/web/vsda.js")';
const vsdaDecorateMarker = ';__decorate([si],$Be.prototype,"j",null)';
const vsdaStart = updated.indexOf(vsdaWebStart);
const vsdaEnd = vsdaStart >= 0 ? updated.indexOf(vsdaDecorateMarker, vsdaStart) : -1;
if (vsdaStart >= 0 && vsdaEnd > vsdaStart && !updated.slice(vsdaStart, vsdaEnd).includes('patched:vsda-noop')) {
  updated = updated.slice(0, vsdaStart) +
    'async j(){return{validator:class{createNewMessage(e){return e}validate(){return"ok"}free(){}},sign:e=>e}}/*patched:vsda-noop*/async k(){return new ArrayBuffer(0)}}' +
    updated.slice(vsdaEnd);
  console.log('  Patched VSDA web loader to no-op validator');
  changed = true;
}

// Patch 3: Extension-installed check — the setup flow checks if GitHub.copilot
// and GitHub.copilot-chat extensions are installed to determine chat readiness.
// Since we use apaas-builder.ruijing-ai instead, redirect these checks.
const extChecks = [
  // In the u() function that checks installed extensions set
  { from: 'u("GitHub.copilot-chat",this.s)', to: 'u("apaas-builder.ruijing-ai",this.s)' },
  { from: "u('GitHub.copilot-chat',this.s)", to: "u('apaas-builder.ruijing-ai',this.s)" },
  // Also redirect the non-chat copilot check so p = l||f||g becomes true
  { from: 'u("GitHub.copilot",this.s)', to: 'u("apaas-builder.ruijing-ai",this.s)' },
  { from: "u('GitHub.copilot',this.s)", to: "u('apaas-builder.ruijing-ai',this.s)" },
];
for (const { from, to } of extChecks) {
  if (updated.includes(from)) {
    updated = updated.split(from).join(to);
    console.log(`  Replaced extension check: ${from.slice(0, 40)}...`);
    changed = true;
  }
}

// Patch 3b: Global replace of ALL remaining GitHub.copilot-chat references.
// The setup forwarding path (M→N→O) also waits for GitHub.copilot-chat extension
// to become ready, causing a timeout. Replace all remaining references.
const copilotChatCount = updated.split('GitHub.copilot-chat').length - 1;
if (copilotChatCount > 0) {
  updated = updated.split('GitHub.copilot-chat').join('apaas-builder.ruijing-ai');
  console.log(`  Replaced ${copilotChatCount} remaining GitHub.copilot-chat references globally`);
  changed = true;
}

// Patch 3c: code-server also inlines product.defaultChatAgent into
// workbench.js. If this remains extensionId:"GitHub.copilot", the native Chat
// session still initializes through the wrong default agent even when
// product.json has been repointed.
let embeddedProductReplaced = 0;
for (const [from, to] of [
  [
    'extensionId:"GitHub.copilot"',
    'extensionId:"apaas-builder.ruijing-ai"/*patched:embedded-default-agent*/',
  ],
  [
    'provider:{default:{id:"github",name:"GitHub"},enterprise:{id:"github-enterprise",name:"GitHub Enterprise"}}',
    'provider:{default:{id:"ruijing-ai.chat",name:"睿鲸AI"},enterprise:{id:"",name:""}}/*patched:embedded-provider*/',
  ],
  [
    'chatExtensionOutputId:"apaas-builder.ruijing-ai.GitHub Copilot Chat.log"',
    'chatExtensionOutputId:""/*patched:embedded-output*/',
  ],
  [
    'chatExtensionOutputExtensionStateCommand:"github.copilot.debug.extensionState"',
    'chatExtensionOutputExtensionStateCommand:""/*patched:embedded-state-command*/',
  ],
]) {
  const count = updated.split(from).length - 1;
  if (count > 0) {
    updated = updated.split(from).join(to);
    embeddedProductReplaced += count;
  }
}
if (embeddedProductReplaced > 0) {
  console.log(`  Patched ${embeddedProductReplaced} embedded defaultChatAgent field(s)`);
  changed = true;
}

// Patch 4: Bypass sign-in dialog in chat setup flow.
// The setup flow checks entitlement/auth before allowing chat. Since we use our
// own backend (MiniMax), we skip the sign-in dialog entirely by forcing DefaultSetup.
const signInCondition = /!e\?\.forceSignInDialog&&\(t\|\|L6\(this\.i\.entitlement\)\|\|this\.i\.entitlement===\w+\.Free\)\|\|e\?\.forceAnonymous===\w+\.EnabledWithoutDialog\?n=(\w+)\.DefaultSetup:n=await this\.r\(e\)/;
const signInMatch = updated.match(signInCondition);
if (signInMatch) {
  const vpName = signInMatch[1]; // capture the vp namespace
  updated = updated.replace(signInCondition, `n=${vpName}.DefaultSetup/*patched:skip-signin*/`);
  console.log('  Bypassed sign-in dialog in setup flow');
  changed = true;
}

// Patch 5: Bypass the setup() call in DefaultSetup case — it also does auth internally.
// Replace the setup call to just resolve successfully without auth.
const setupCallPattern = `case ${signInMatch?.[1] || 'vp'}.DefaultSetup:o=await this.e.value.setup(`;
if (signInMatch && updated.includes(setupCallPattern)) {
  updated = updated.replace(
    setupCallPattern,
    `case ${signInMatch[1]}.DefaultSetup:o=await Promise.resolve({success:true}),0&&this.e.value.setup(`
  );
  console.log('  Bypassed setup() auth call in DefaultSetup case');
  changed = true;
}

// Patch 6: Bypass the ENTIRE D0 core agent invoke path.
const invokePattern = 'return this.L(e,d=>t([d]),n,o,r,a,l,c)';
if (updated.includes(invokePattern)) {
  updated = updated.replace(
    invokePattern,
    'return(globalThis.__apaasMiniMaxHandler?.invoke?globalThis.__apaasMiniMaxHandler.invoke(e,t,[],null):{}/*patched:delegate-to-minimax*/)'
  );
  console.log('  Patched D0 invoke to delegate to MiniMax handler');
  changed = true;
}

// Patch 6b: VS Code 1.114/code-server 4.114 changed the setup-agent invoke
// shape. The previous direct `this.L(...)` call is now wrapped by
// `this.doInvoke(...)`, so delegate at the setup invoke boundary instead.
const setupInvokePattern = /async invoke\(e,t\)\{return this\.instantiationService\.invokeFunction\(async o=>\{let n=o\.get\((\w+)\),r=o\.get\((\w+)\),s=o\.get\((\w+)\),l=o\.get\((\w+)\),c=o\.get\((\w+)\),u=o\.get\((\w+)\);return this\.doInvoke\(e,p=>t\(\[p\]\),n,r,s,l,c,u\)\}\)\}/;
const setupInvokeMatch = updated.match(setupInvokePattern);
if (setupInvokeMatch && !updated.includes('patched:delegate-setup-to-minimax')) {
  const [full, dep1, dep2, dep3, dep4, dep5, dep6] = setupInvokeMatch;
  updated = updated.replace(
    full,
    `async invoke(e,t){if(globalThis.__apaasMiniMaxHandler?.invoke)return globalThis.__apaasMiniMaxHandler.invoke(e,t,[],null)/*patched:delegate-setup-to-minimax*/;return this.instantiationService.invokeFunction(async o=>{let n=o.get(${dep1}),r=o.get(${dep2}),s=o.get(${dep3}),l=o.get(${dep4}),c=o.get(${dep5}),u=o.get(${dep6});return this.doInvoke(e,p=>t([p]),n,r,s,l,c,u)})}`
  );
  console.log('  Patched setup invoke to delegate to MiniMax handler');
  changed = true;
}

// Patch 7: Make the built-in Chat view register in local Vibe IDE.
//
// code-server's stock Chat view is guarded by a Copilot/setup context key. In
// this product we provide the agent ourselves, so the native view should exist
// even when that upstream setup context never flips.
const chatViewWhenPattern = 'when:C.or(C.or(te.Setup.hidden,te.Setup.disabled)?.negate(),te.panelParticipantRegistered,te.extensionInvalid)';
if (updated.includes(chatViewWhenPattern) && !updated.includes('patched:always-show-native-chat-view')) {
  updated = updated.replace(
    chatViewWhenPattern,
    'when:void 0/*patched:always-show-native-chat-view*/'
  );
  console.log('  Patched native Chat view visibility guard');
  changed = true;
}

// Patch 8: Open the native VS Code Chat view for Vibe IDE workspaces.
//
// This intentionally does NOT inject a custom assistant panel. It calls the
// workbench command service after the native workbench is ready, so the user
// sees VS Code's built-in Chat UI and our dynamic/default agent handles the
// request path.
const nativeChatBootMarker = 'patched:apaas-open-native-chat-on-vibe';
if (!updated.includes(nativeChatBootMarker)) {
  const exportMarker = 'export{PBi as LocalStorageSecretStorageProvider};';
  const nativeChatBoot = `
;(()=>{/*${nativeChatBootMarker}*/
const _w=globalThis;
if(_w.__apaasNativeChatOpenBoot)return;
let _hasVibeContext=false;
try{
const _u=new URL(_w.location?.href||"http://localhost/");
_hasVibeContext=!!(_u.searchParams.get("vibe_workspace_id")||_u.searchParams.get("vibe_api_base"));
}catch{}
if(!_hasVibeContext)return;
_w.__apaasNativeChatOpenBoot=true;
let _tries=0;
const _open=()=>{
_tries++;
try{
if(typeof hDo==="undefined"||!hDo?.executeCommand)throw new Error("native command bridge not ready");
hDo.executeCommand("workbench.action.chat.open").then(()=>{
try{hDo.executeCommand("workbench.action.chat.focusInput").catch(()=>{});}catch{}
console.log("[PATCH] opened native VS Code Chat view for Vibe IDE");
}).catch(_err=>{
if(_tries<16)setTimeout(_open,500);
else console.warn("[PATCH] open native Chat failed",_err);
});
}catch(_err){
if(_tries<16)setTimeout(_open,500);
else console.warn("[PATCH] open native Chat unavailable",_err);
}
};
setTimeout(_open,900);
})();
`;
  if (updated.includes(exportMarker)) {
    updated = updated.replace(exportMarker, nativeChatBoot + exportMarker);
    console.log('  Added native VS Code Chat auto-open boot hook');
    changed = true;
  } else {
    console.warn('  Could not locate workbench export marker for native chat boot hook');
  }
}

function bumpWorkbenchHtmlCache() {
  const htmlPath = workbenchPath.replace(/workbench\.js$/, 'workbench.html');
  if (!fs.existsSync(htmlPath)) return false;
  const cacheBust = `patched-${Date.now()}`;
  const html = fs.readFileSync(htmlPath, 'utf8');
  const cleanedHtml = html.replace(/\n?<!-- APAAS_AI_ASSISTANT_FALLBACK_START -->[\s\S]*?<!-- APAAS_AI_ASSISTANT_FALLBACK_END -->/g, '');
  const bumped = cleanedHtml
    .replace(/workbench\.js\?v=patched-\d+/g, `workbench.js?v=${cacheBust}`)
    .replace(/workbench\.js(?!\?v=)/g, `workbench.js?v=${cacheBust}`);
  if (bumped !== html) {
    fs.writeFileSync(htmlPath, bumped);
    console.log(`Updated workbench.html cache buster: ${cacheBust}`);
    return true;
  }
  return false;
}

if (!changed) {
  bumpWorkbenchHtmlCache();
  neutralizeLegacyMiniMaxExtension();
  console.log('Patch already applied.');
  process.exit(0);
}

fs.copyFileSync(workbenchPath, `${workbenchPath}.bak-dynamic-agent-20260327`);
fs.writeFileSync(workbenchPath, updated);
bumpWorkbenchHtmlCache();
neutralizeLegacyMiniMaxExtension();
console.log('Patched workbench.js with MiniMax dynamic agent fallback and VSDA browser fallback.');
