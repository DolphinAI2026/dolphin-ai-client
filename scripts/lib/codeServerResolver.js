/**
 * code-server 版本自动检测与路径解析
 *
 * 功能：
 *   1. 自动扫描 ~/.local/lib/code-server-* 目录
 *   2. 支持 --code-server-path CLI 参数覆盖
 *   3. 返回 { version, basePath, workbenchPath, productJsonPath, extensionHostPath, nodePath }
 *   4. 从 workbench.js 动态提取 minified 属性名映射
 */

const fs = require('fs');
const path = require('path');

const HOME = process.env.HOME || process.env.USERPROFILE || '/root';

/**
 * 自动发现已安装的 code-server 版本
 * @param {string} [explicitPath] - 显式指定的 code-server 根目录
 * @returns {{ version: string, basePath: string, workbenchPath: string, productJsonPath: string, extensionHostPath: string, nodePath: string }}
 */
function resolve(explicitPath) {
  // 1. CLI 显式路径
  if (explicitPath) {
    return _buildPaths(explicitPath);
  }

  // 2. 扫描 ~/.local/lib/code-server-*
  const libDir = path.join(HOME, '.local', 'lib');
  const candidates = [];

  if (fs.existsSync(libDir)) {
    for (const entry of fs.readdirSync(libDir)) {
      if (entry.startsWith('code-server-') || entry === 'code-server') {
        const full = path.join(libDir, entry);
        if (fs.statSync(full).isDirectory()) {
          candidates.push(full);
        }
      }
    }
  }

  // 3. 也检查全局安装路径
  for (const globalPath of ['/usr/local/lib/code-server', '/usr/lib/code-server']) {
    if (fs.existsSync(globalPath)) {
      candidates.push(globalPath);
    }
  }

  if (candidates.length === 0) {
    throw new Error('Could not find any code-server installation. Searched:\n  ' +
      `${libDir}/code-server-*\n  /usr/local/lib/code-server\n  /usr/lib/code-server`);
  }

  // 4. 按版本号排序，优先使用最新版
  candidates.sort((a, b) => {
    const va = _extractVersion(a);
    const vb = _extractVersion(b);
    return _compareVersions(vb, va); // descending
  });

  // 5. 验证 workbench.js 存在
  for (const candidate of candidates) {
    try {
      const info = _buildPaths(candidate);
      if (fs.existsSync(info.workbenchPath)) {
        return info;
      }
    } catch { /* skip */ }
  }

  throw new Error('No valid code-server installation found with workbench.js');
}

/**
 * 从 workbench.js 中提取 activateDefaultAgent 所在类的属性名映射。
 * 通过分析 constructor 参数赋值来推断：
 *   this.XYZ = n → extensionService (第4个参数)
 *   this.ABC = c → chatAgentService (第8个参数)
 *   etc.
 *
 * @param {string} workbenchPath
 * @returns {{ extensionService: string, instantiationService: string, chatAgentService: string, configurationService: string }}
 */
function extractPropertyNames(workbenchPath) {
  const src = fs.readFileSync(workbenchPath, 'utf8');

  // Find the class containing activateDefaultAgent
  const actIdx = src.indexOf('async activateDefaultAgent(e){');
  if (actIdx < 0) {
    // May already be patched — try finding the method with template content
    const altIdx = src.indexOf('activateDefaultAgent(e){');
    if (altIdx < 0) {
      return _defaultNames(); // fallback
    }
  }

  // Search backwards for the constructor
  const searchStart = Math.max(0, (actIdx >= 0 ? actIdx : src.indexOf('activateDefaultAgent(e){')) - 15000);
  const before = src.substring(searchStart, actIdx >= 0 ? actIdx : src.indexOf('activateDefaultAgent(e){'));
  const ctorMatch = before.match(/constructor\(([^)]+)\)\{[^}]*?this\.(\w+)=\1\.split/);

  // Try to find the full constructor with assignments
  const ctorIdx = before.lastIndexOf('constructor(');
  if (ctorIdx < 0) return _defaultNames();

  const ctorCode = before.substring(ctorIdx, ctorIdx + 2000);
  const argsMatch = ctorCode.match(/constructor\(([^)]+)\)/);
  if (!argsMatch) return _defaultNames();

  const args = argsMatch[1].split(',').map(a => a.trim());
  // Extract assignments: this.XXX = argN
  const assignments = {};
  const assignRe = /this\.(\w+)\s*=\s*(\w+)/g;
  let m;
  while ((m = assignRe.exec(ctorCode)) !== null) {
    const propName = m[1];
    const argName = m[2];
    const argIdx = args.indexOf(argName);
    if (argIdx >= 0) {
      assignments[argIdx] = propName;
    }
  }

  // Map constructor positions to known services
  // Position 3 (0-indexed) = extensionService
  // Position 4 = instantiationService
  // Position 7 = chatAgentService
  // Position 8 = configurationService
  return {
    extensionService: assignments[3] || 'extensionService',
    instantiationService: assignments[4] || 'instantiationService',
    chatAgentService: assignments[7] || 'chatAgentService',
    configurationService: assignments[8] || 'configurationService',
  };
}

function _defaultNames() {
  return {
    extensionService: 'extensionService',
    instantiationService: 'instantiationService',
    chatAgentService: 'chatAgentService',
    configurationService: 'configurationService',
  };
}

function _buildPaths(basePath) {
  basePath = basePath.replace(/\/+$/, '');
  const vscodePath = path.join(basePath, 'lib', 'vscode');
  const workbenchDir = path.join(vscodePath, 'out', 'vs', 'code', 'browser', 'workbench');

  // Extract version from package.json or directory name
  let version = 'unknown';
  const pkgPath = path.join(basePath, 'package.json');
  if (fs.existsSync(pkgPath)) {
    try {
      version = JSON.parse(fs.readFileSync(pkgPath, 'utf8')).version || version;
    } catch { /* ignore */ }
  }
  if (version === 'unknown') {
    version = _extractVersion(basePath);
  }

  return {
    version,
    basePath,
    workbenchPath: path.join(workbenchDir, 'workbench.js'),
    workbenchHtmlPath: path.join(workbenchDir, 'workbench.html'),
    productJsonPath: path.join(vscodePath, 'product.json'),
    extensionHostPath: path.join(vscodePath, 'out', 'vs', 'workbench', 'api', 'node', 'extensionHostProcess.js'),
    nodePath: path.join(basePath, 'lib', 'node'),
  };
}

function _extractVersion(dirPath) {
  const match = path.basename(dirPath).match(/code-server-(\d+\.\d+\.\d+)/);
  return match ? match[1] : '0.0.0';
}

function _compareVersions(a, b) {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) {
      return (pa[i] || 0) - (pb[i] || 0);
    }
  }
  return 0;
}

module.exports = { resolve, extractPropertyNames };
