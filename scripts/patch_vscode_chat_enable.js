#!/usr/bin/env node
/**
 * patch_vscode_chat_enable.js — 让 code-server 内置 Agent 聊天在「未登录 Copilot」下，
 * 用我们扩展注册的语言模型（apaas-builder.ruijing-ai，vendor=copilot）正常工作。
 *
 * 做两件事：
 *   A. workbench.js 补丁：
 *      - 4 个 entitlement 补丁：绕过登录框 / 强制启用模型 / 跳过 entitlement Unknown
 *        检查 / entitlement 强制 Free。（否则即便注册了模型，聊天也卡在 "Sign in"。）
 *      - copilot-chat 安装引用替换：chat setup 的 forwarding 路径硬编码「装/等
 *        GitHub.copilot-chat」，离线 code-server 没这个扩展 → "cannot be installed
 *        because it was not found" → 卡 "Getting chat ready"。全部换成已安装的 ruijing-ai。
 *   B. product.json：
 *      - extensionAllowedProposedApi = ['apaas-builder.ruijing-ai']
 *        （放行 proposed API，否则扩展里的 registerLanguageModelChatProvider 不可用）
 *      - defaultChatAgent **重指向** apaas-builder.ruijing-ai（不能删；删了会回退硬编码
 *        GitHub.copilot-chat 装不到而卡死）
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

// --- PATCH 4b: 绕过 DefaultSetup 里的 setup() 鉴权调用（关键修复）---
// PATCH 1 强制走 DefaultSetup 分支，但分支内仍 `await this.e.value.setup(...)`，
// 那个 setup() 内部做 GitHub 登录鉴权，在我们无 key 环境里永远不返回 →
// "Chat took too long to get ready" → 消息进不去 participant。
// 浏览器实证: 线上(chat_enable)此处未绕过、卡死; 本地(chat_fallback)已绕过、能用。
// 与 chat_fallback Patch 5 等价: 让 setup() 立即 resolve {success:true}，不真调。
apply(
  'Bypass setup() auth call in DefaultSetup',
  'case vp.DefaultSetup:o=await this.e.value.setup(',
  'case vp.DefaultSetup:o=await Promise.resolve({success:true}),0&&this.e.value.setup(',
);

// --- PATCH 5: 重指向 copilot 已安装检查（非 -chat）---
// 让 p=l||f||g 这类「copilot 装了吗」判断对我们已安装的 ruijing-ai 成立。
// 不同 minified 构建用单/双引号，按存在的形态替换（缺某形态不算失败）。
let copilotCheckReplaced = 0;
for (const [oldStr, newStr] of [
  ['u("GitHub.copilot",this.s)', 'u("apaas-builder.ruijing-ai",this.s)'],
  ["u('GitHub.copilot',this.s)", "u('apaas-builder.ruijing-ai',this.s)"],
]) {
  if (wb.includes(oldStr)) {
    wb = wb.split(oldStr).join(newStr);
    copilotCheckReplaced++;
  }
}
if (copilotCheckReplaced > 0) {
  console.log(`[OK]   Redirected ${copilotCheckReplaced} copilot installed-check(s) → ruijing-ai`);
  applied++;
} else {
  console.log('[SKIP] copilot installed-check — no target form present');
  skipped++;
}

// --- PATCH 6: 全局替换剩余所有 GitHub.copilot-chat 引用 ---
// 关键修复：仅重指向 product.json 的 defaultChatAgent 不够。chat setup 的
// forwarding 路径里还硬编码了「安装/等待 GitHub.copilot-chat 扩展」，离线
// code-server 没这个扩展 → "cannot be installed because it was not found" →
// 聊天卡 "Getting chat ready"。把全部引用换成我们已安装的 ruijing-ai。
// （等价 chat_fallback 的 Patch 3/3b，但**不**带 D0→minimax delegate。）
const copilotChatCount = wb.split('GitHub.copilot-chat').length - 1;
if (copilotChatCount > 0) {
  wb = wb.split('GitHub.copilot-chat').join('apaas-builder.ruijing-ai');
  console.log(`[OK]   Replaced ${copilotChatCount} GitHub.copilot-chat refs globally`);
  applied++;
} else {
  console.log('[SKIP] no GitHub.copilot-chat references (already replaced or absent)');
  skipped++;
}

fs.writeFileSync(wbPath, wb);
console.log(`workbench.js: applied=${applied} skipped=${skipped} failed=${failed}`);

// --- product.json: 放行 proposed API + 删 defaultChatAgent ---
if (fs.existsSync(productPath)) {
  const data = JSON.parse(fs.readFileSync(productPath, 'utf8'));
  // 放行 proposed API：数组形态（与本地实证一致）。否则扩展里的
  // registerLanguageModelChatProvider 不可用。
  data.extensionAllowedProposedApi = ['apaas-builder.ruijing-ai'];
  // 关键：defaultChatAgent **不能删**。删了 VS Code 的 chat setup 会回退到硬编码的
  // GitHub.copilot-chat → "cannot be installed because it was not found" → 聊天卡在
  // "Getting chat ready"。照本地做法把它**重指向我们自己的扩展**（已安装）→ setup 秒过。
  data.defaultChatAgent = {
    extensionId: 'apaas-builder.ruijing-ai',
    chatExtensionId: 'apaas-builder.ruijing-ai',
    chatExtensionOutputId: '',
    chatExtensionOutputExtensionStateCommand: '',
    documentationUrl: '',
    termsStatementUrl: '',
    privacyStatementUrl: '',
    skusDocumentationUrl: '',
    publicCodeMatchesUrl: '',
    entitlementSignupLimitedUrl: '',
    provider: {
      default: { id: 'ruijing', name: 'RuijingAI' },
      enterprise: { id: '', name: '' },
      apple: { id: '', name: '' },
      google: { id: '', name: '' },
    },
    providerUriSetting: '',
  };
  fs.writeFileSync(productPath, JSON.stringify(data, null, 2));
  console.log('[OK]   product.json: allowed proposed API + repointed defaultChatAgent → apaas-builder.ruijing-ai');
} else {
  console.warn(`[WARN] product.json not found at ${productPath}`);
}

if (failed > 0) {
  console.warn(`\n⚠ ${failed} workbench patch(es) failed — strings may have changed for this code-server version.`);
  process.exit(1);
}
console.log('=== chat enable patch done ===');
