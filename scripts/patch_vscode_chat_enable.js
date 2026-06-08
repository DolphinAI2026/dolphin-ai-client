#!/usr/bin/env node
/**
 * patch_vscode_chat_enable.js — 让 code-server 内置 Agent 聊天在「未登录 Copilot」下，
 * 用我们扩展注册的语言模型（apaas-builder.ruijing-ai，vendor=copilot）正常工作。
 *
 * 做两件事：
 *   A. workbench.js 4 个 entitlement 补丁：绕过登录框 / 强制启用模型 / 跳过 entitlement Unknown
 *      检查 / entitlement 强制 Free。（否则即便注册了模型，聊天也卡在 "Sign in to use AI features"。）
 *   B. product.json：
 *      - extensionAllowedProposedApi['apaas-builder.ruijing-ai'] = ['chatProvider']
 *        （放行 proposed API，否则扩展里的 registerLanguageModelChatProvider 不可用）
 *      - 删掉 defaultChatAgent（指向 GitHub.copilot；没模型时渲染它会崩
 *        "Cannot create property 'textContent' on string 'GitHub.copilot'"）
 *
 * 配方与字符串来自本地实证可用的 minimax-chat-provider 的 patch-workbench.sh，
 * 针对 code-server 4.112.0 / VS Code 1.112.0 的 minified workbench.js。换版本需重新对齐这些串。
 * 取代旧的 patch_vscode_chat_fallback.js（activateDefaultAgent 替换法，在 1.112 上会崩）。
 *
 * Usage: node patch_vscode_chat_enable.js /path/to/workbench.js [/path/to/product.json]
 */
const fs = require('fs');
const path = require('path');

const wbPath = process.argv[2];
if (!wbPath || !fs.existsSync(wbPath)) {
  console.error('ERROR: workbench.js path required and must exist');
  process.exit(1);
}
const productPath =
  process.argv[3] ||
  path.join(wbPath.split('/out/vs/code/browser/workbench/workbench.js')[0], 'product.json');

let wb = fs.readFileSync(wbPath, 'utf8');
let applied = 0;
let skipped = 0;
let failed = 0;

function apply(name, oldStr, newStr) {
  if (wb.includes(newStr)) {
    console.log(`[SKIP] ${name} — already applied`);
    skipped++;
    return;
  }
  if (!wb.includes(oldStr)) {
    console.log(`[FAIL] ${name} — target string not found`);
    failed++;
    return;
  }
  wb = wb.split(oldStr).join(newStr);
  console.log(`[OK]   ${name}`);
  applied++;
}

// --- PATCH 1: 绕过登录框（强制走 DefaultSetup）---
apply(
  'Bypass sign-in dialog',
  '!e?.forceSignInDialog&&(t||L6(this.i.entitlement)||this.i.entitlement===bs.Free)||e?.forceAnonymous===bj.EnabledWithoutDialog?n=vp.DefaultSetup:n=await this.r(e)',
  'n=vp.DefaultSetup/*patched*/',
);

// --- PATCH 2: 强制启用模型（entitlement 检查不再拦）---
apply(
  'Force model enablement',
  'n=this.C.isInternal||t!==bs.Unknown&&t!==bs.Available&&!i;this.j.enabled=n&&e.length>0',
  'n=!0/*patched:force-models*/;this.j.enabled=n&&e.length>0',
);

// --- PATCH 3: 聊天视图跳过 entitlement Unknown 检查 ---
apply(
  'Skip entitlement Unknown check in chat view',
  'this.m.state.installed||this.m.state.disabled||this.m.state.untrusted||this.m.state.entitlement===bs.Available||this.m.state.entitlement===bs.Unknown&&!this.z.anonymous?this.X(e,t,i,n,o,r,a,l):this.M(e,t,i,n,o,r,a)',
  'this.m.state.installed||this.m.state.disabled||this.m.state.untrusted||this.m.state.entitlement===bs.Available?this.X(e,t,i,n,o,r,a,l):this.M(e,t,i,n,o,r,a)/*patched:skip-unknown-check*/',
);

// --- PATCH 4: entitlement 强制 Free（避免 anonymous-limited 模式）---
apply(
  'Force entitlement to Free',
  'TKe(this.N,this.G.entitlement,this.G)&&(this.G.sku="no_auth_limited_copilot")',
  '(this.G.entitlement=bs.Free,this.G.sku="no_auth_limited_copilot")/*patched:force-free*/',
);

fs.writeFileSync(wbPath, wb);
console.log(`workbench.js: applied=${applied} skipped=${skipped} failed=${failed}`);

// --- product.json: 放行 proposed API + 删 defaultChatAgent ---
if (fs.existsSync(productPath)) {
  const data = JSON.parse(fs.readFileSync(productPath, 'utf8'));
  const allowed = data.extensionAllowedProposedApi || {};
  // chatProvider → registerLanguageModelChatProvider；defaultChatParticipant → 扩展的 isDefault 聊天参与者
  allowed['apaas-builder.ruijing-ai'] = ['chatProvider', 'defaultChatParticipant'];
  data.extensionAllowedProposedApi = allowed;
  let removedDefault = false;
  if (data.defaultChatAgent) {
    delete data.defaultChatAgent;
    removedDefault = true;
  }
  fs.writeFileSync(productPath, JSON.stringify(data, null, 2));
  console.log(
    `[OK]   product.json: allowed chatProvider for apaas-builder.ruijing-ai` +
      (removedDefault ? ' + removed defaultChatAgent' : ''),
  );
} else {
  console.warn(`[WARN] product.json not found at ${productPath}`);
}

if (failed > 0) {
  console.warn(`\n⚠ ${failed} workbench patch(es) failed — strings may have changed for this code-server version.`);
  process.exit(1);
}
console.log('=== chat enable patch done ===');
