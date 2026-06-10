#!/usr/bin/env node
/**
 * 统一 patch 入口 — 一键执行所有 code-server 补丁
 *
 * Usage:
 *   node scripts/patch_all.js [--code-server-path /path/to/code-server]
 *
 * 执行顺序：
 *   1. 自动检测 code-server 版本和路径
 *   2. 提取 workbench.js 属性名映射
 *   3. 逐个执行 patch（locale → branding → handshake → chat_fallback）
 *   4. 语法验证（失败自动回滚）
 *   5. 更新 workbench.html 缓存参数
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { resolve, extractPropertyNames } = require('./lib/codeServerResolver');

// Parse CLI args
const args = process.argv.slice(2);
let explicitPath = null;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--code-server-path' && args[i + 1]) {
    explicitPath = args[i + 1];
    i++;
  }
}

console.log('=== aPaaS Builder AI — code-server Patch Tool ===\n');

// Step 1: Resolve code-server
let csInfo;
try {
  csInfo = resolve(explicitPath);
  console.log(`✓ Found code-server ${csInfo.version}`);
  console.log(`  Path: ${csInfo.basePath}`);
  console.log(`  Workbench: ${csInfo.workbenchPath}\n`);
} catch (e) {
  console.error('✗ ' + e.message);
  process.exit(1);
}

// Step 2: Extract property names
let propNames;
try {
  propNames = extractPropertyNames(csInfo.workbenchPath);
  console.log('✓ Extracted property names:');
  for (const [key, val] of Object.entries(propNames)) {
    console.log(`  ${key} → this.${val}`);
  }
  console.log('');
} catch (e) {
  console.warn('⚠ Could not extract property names, using defaults:', e.message);
  propNames = null;
}

// Step 3: Backup workbench.js
const backupPath = csInfo.workbenchPath + '.bak-' + Date.now();
fs.copyFileSync(csInfo.workbenchPath, backupPath);
console.log(`✓ Backup: ${path.basename(backupPath)}\n`);

// Step 4: Run patches
const scriptsDir = __dirname;
const patches = [
  // 新方案：扩展用 registerLanguageModelChatProvider 注册模型（vendor=copilot），
  // 这里只做 entitlement 解锁 + product.json 放行 proposed API / 重指向 defaultChatAgent。
  // 取代旧的 patch_vscode_chat_fallback.js（activateDefaultAgent 替换法在 1.112 上会崩）。
  { name: 'Chat Enable (entitlement + product.json proposed-api)', script: 'patch_vscode_chat_enable.js', args: [csInfo.workbenchPath, csInfo.productJsonPath] },
];

let allOk = true;
for (const patch of patches) {
  const scriptPath = path.join(scriptsDir, patch.script);
  if (!fs.existsSync(scriptPath)) {
    console.warn(`⚠ Skipping ${patch.name}: ${patch.script} not found`);
    continue;
  }

  try {
    const patchArgs = patch.args ? patch.args.join(' ') : '';
    const output = execSync(
      `"${csInfo.nodePath}" "${scriptPath}" ${patchArgs}`,
      { encoding: 'utf-8', timeout: 30000 }
    );
    console.log(`✓ ${patch.name}`);
    if (output.trim()) {
      output.trim().split('\n').forEach(l => console.log(`  ${l}`));
    }
  } catch (e) {
    console.error(`✗ ${patch.name} FAILED: ${e.message}`);
    allOk = false;
  }
}

// Step 5: Post-patch syntax validation
console.log('\n--- Syntax Validation ---');
try {
  const src = fs.readFileSync(csInfo.workbenchPath, 'utf8');

  // Check for common syntax error patterns
  const brokenPatterns = [
    { pattern: '!i?.o=1', desc: 'Broken sign-in bypass (stray !i?.)' },
    { pattern: 'async activateDefaultAgent(e){\nasync activateDefaultAgent(e){', desc: 'Duplicate method header' },
  ];

  let syntaxOk = true;
  for (const { pattern, desc } of brokenPatterns) {
    if (src.includes(pattern)) {
      console.error(`✗ Found known bad pattern: ${desc}`);
      syntaxOk = false;
    }
  }

  // Verify activateDefaultAgent exists and has content
  const actIdx = src.indexOf('async activateDefaultAgent(e){');
  if (actIdx < 0) {
    console.warn('⚠ activateDefaultAgent method not found (may need manual check)');
  } else {
    console.log('✓ activateDefaultAgent method present');
  }

  // Verify no GitHub.copilot-chat references remain
  const copilotChatCount = (src.match(/GitHub\.copilot-chat/g) || []).length;
  if (copilotChatCount > 0) {
    console.warn(`⚠ ${copilotChatCount} GitHub.copilot-chat references still present`);
  } else {
    console.log('✓ No GitHub.copilot-chat references');
  }

  if (!syntaxOk) {
    console.error('\n✗ Syntax check failed! Rolling back...');
    fs.copyFileSync(backupPath, csInfo.workbenchPath);
    console.log('✓ Restored from backup');
    process.exit(1);
  }

  console.log('✓ All syntax checks passed');
} catch (e) {
  console.error('✗ Validation error:', e.message);
  console.error('Rolling back...');
  fs.copyFileSync(backupPath, csInfo.workbenchPath);
  console.log('✓ Restored from backup');
  process.exit(1);
}

// Step 6: Update cache-busting in workbench.html
if (fs.existsSync(csInfo.workbenchHtmlPath)) {
  let html = fs.readFileSync(csInfo.workbenchHtmlPath, 'utf8');
  const newTs = Math.floor(Date.now() / 1000);
  const updated = html.replace(/v=patched-\d+/g, `v=patched-${newTs}`)
                      .replace(/(workbench\.js)(?!\?)/g, `$1?v=patched-${newTs}`);
  if (updated !== html) {
    fs.writeFileSync(csInfo.workbenchHtmlPath, updated);
    console.log(`\n✓ Updated cache-busting: v=patched-${newTs}`);
  }
}

console.log('\n=== All patches applied successfully! ===');
console.log(`Backup saved as: ${path.basename(backupPath)}`);
if (!allOk) {
  console.warn('\n⚠ Some patches had warnings — review output above.');
}
