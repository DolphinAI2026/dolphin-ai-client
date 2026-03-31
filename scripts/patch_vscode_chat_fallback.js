const fs = require('fs');
const path = require('path');

const candidatePaths = [
  process.argv[2], // allow explicit path as first argument
  '/usr/local/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js',
  '/usr/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js',
  `${process.env.HOME}/.local/lib/code-server/lib/vscode/out/vs/code/browser/workbench/workbench.js`,
  `${process.env.HOME}/.local/lib/code-server-4.112.0/lib/vscode/out/vs/code/browser/workbench/workbench.js`,
].filter(Boolean);

const workbenchPath = candidatePaths.find(p => {
  try { fs.accessSync(p); return true; } catch { return false; }
});
if (!workbenchPath) {
  console.error('Could not find workbench.js. Searched:\n' + candidatePaths.join('\n'));
  process.exit(1);
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

if (!changed) {
  console.log('Patch already applied.');
  process.exit(0);
}

fs.copyFileSync(workbenchPath, `${workbenchPath}.bak-dynamic-agent-20260327`);
fs.writeFileSync(workbenchPath, updated);
console.log('Patched workbench.js with MiniMax dynamic agent fallback and VSDA browser fallback.');
