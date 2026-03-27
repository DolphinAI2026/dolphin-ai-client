const fs = require('fs');
const path = require('path');

const workbenchPath =
  '/Users/mars/.local/lib/code-server-4.112.0/lib/vscode/out/vs/code/browser/workbench/workbench.js';
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

if (!changed) {
  console.log('Patch already applied.');
  process.exit(0);
}

fs.copyFileSync(workbenchPath, `${workbenchPath}.bak-dynamic-agent-20260327`);
fs.writeFileSync(workbenchPath, updated);
console.log('Patched workbench.js with MiniMax dynamic agent fallback and VSDA browser fallback.');
