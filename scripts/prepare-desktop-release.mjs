#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { copyFile, mkdir, mkdtemp, readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';

const semverPattern = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;

function artifactNames(version) {
  const prefix = `dolphin-ai-${version}`;
  return {
    windowsSetup: `${prefix}-windows-x86_64-setup.exe`,
    windowsUpdater: `${prefix}-windows-x86_64-updater.nsis.zip`,
    macosDmg: `${prefix}-macos-aarch64.dmg`,
    macosUpdater: `${prefix}-macos-aarch64-updater.app.tar.gz`,
    linuxAppImage: `${prefix}-linux-x86_64.AppImage`,
    linuxDeb: `${prefix}-linux-x86_64.deb`,
    linuxUpdater: `${prefix}-linux-x86_64-updater.AppImage.tar.gz`,
  };
}

function normalizeTag(tag) {
  if (!tag?.startsWith('v') || !semverPattern.test(tag.slice(1))) {
    throw new Error(`Tag must be vX.Y.Z SemVer: ${tag ?? ''}`);
  }
  return tag.slice(1);
}

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--self-test' || argument === '--help' || argument === '-h') {
      options[argument.slice(2) || 'help'] = true;
      continue;
    }
    if (!['--version', '--repository', '--tag', '--input', '--output'].includes(argument)) {
      throw new Error(`Unknown argument: ${argument}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) {
      throw new Error(`Missing value for ${argument}`);
    }
    options[argument.slice(2)] = value;
    index += 1;
  }
  return options;
}

async function filesNamed(root, fileName) {
  const matches = [];
  async function walk(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await walk(absolute);
      } else if (entry.isFile() && entry.name === fileName) {
        matches.push(absolute);
      }
    }
  }
  await walk(root);
  return matches;
}

async function requireSingleFile(input, name) {
  const matches = await filesNamed(input, name);
  if (matches.length !== 1) {
    throw new Error(`Expected exactly one ${name} under ${input}, found ${matches.length}`);
  }
  return matches[0];
}

async function sha256(file) {
  return createHash('sha256').update(await readFile(file)).digest('hex');
}

function releaseUrl(repository, tag, asset) {
  return `https://github.com/${repository}/releases/download/${tag}/${encodeURIComponent(asset)}`;
}

async function publishStagedOutput(staging, output, operations = {}) {
  const renameImpl = operations.rename ?? rename;
  const rmImpl = operations.rm ?? rm;
  const warn = operations.warn ?? ((message) => console.warn(message));
  const parent = path.dirname(output);
  const backup = await mkdtemp(path.join(parent, `.${path.basename(output)}.backup-`));
  await rmImpl(backup, { recursive: true, force: true });
  let movedExistingOutput = false;
  let published = false;
  let primaryError;
  try {
    try {
      await renameImpl(output, backup);
      movedExistingOutput = true;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    await renameImpl(staging, output);
    published = true;
    if (movedExistingOutput) {
      try {
        await rmImpl(backup, { recursive: true, force: true });
      } catch (error) {
        warn(`Desktop Release published at ${output}; backup cleanup failed and was retained at ${backup}: ${error.message}`);
      }
    }
  } catch (error) {
    if (!published && movedExistingOutput) {
      try {
        await renameImpl(backup, output);
      } catch (rollbackError) {
        primaryError = new Error(`${error.message}; rollback failed; backup retained at ${backup}: ${rollbackError.message}`);
        throw primaryError;
      }
    }
    primaryError = error;
    throw error;
  } finally {
    const cleanupErrors = [];
    if (!published) {
      try {
        await rmImpl(staging, { recursive: true, force: true });
      } catch (error) {
        cleanupErrors.push(error);
      }
    }
    if (!movedExistingOutput) {
      try {
        await rmImpl(backup, { recursive: true, force: true });
      } catch (error) {
        cleanupErrors.push(error);
      }
    }
    if (cleanupErrors.length > 0) {
      const cleanupMessage = cleanupErrors.map((error) => error.message).join('; ');
      if (primaryError) warn(`Desktop Release failed: ${primaryError.message}; cleanup also failed: ${cleanupMessage}`);
      else throw new Error(`Desktop Release cleanup failed: ${cleanupMessage}`);
    }
  }
}

export async function prepareRelease({ version, repository, tag, input, output }) {
  if (!semverPattern.test(version ?? '')) {
    throw new Error(`Version must be X.Y.Z SemVer: ${version ?? ''}`);
  }
  if (normalizeTag(tag) !== version) {
    throw new Error(`Tag ${tag} does not match version ${version}`);
  }
  if (!/^[^/\s]+\/[^/\s]+$/.test(repository ?? '')) {
    throw new Error(`Repository must be owner/repo: ${repository ?? ''}`);
  }

  const names = artifactNames(version);
  const required = [
    names.windowsSetup,
    names.windowsUpdater,
    `${names.windowsUpdater}.sig`,
    names.macosDmg,
    names.macosUpdater,
    `${names.macosUpdater}.sig`,
    names.linuxAppImage,
    names.linuxDeb,
    names.linuxUpdater,
    `${names.linuxUpdater}.sig`,
  ];
  const sources = new Map();
  for (const name of required) {
    sources.set(name, await requireSingleFile(input, name));
  }

  const platforms = {
    'windows-x86_64': {
      signature: (await readFile(sources.get(`${names.windowsUpdater}.sig`), 'utf8')).trim(),
      url: releaseUrl(repository, tag, names.windowsUpdater),
    },
    'darwin-aarch64': {
      signature: (await readFile(sources.get(`${names.macosUpdater}.sig`), 'utf8')).trim(),
      url: releaseUrl(repository, tag, names.macosUpdater),
    },
    'linux-x86_64': {
      signature: (await readFile(sources.get(`${names.linuxUpdater}.sig`), 'utf8')).trim(),
      url: releaseUrl(repository, tag, names.linuxUpdater),
    },
  };
  for (const [platform, update] of Object.entries(platforms)) {
    if (!update.signature) {
      throw new Error(`Updater signature is empty for ${platform}`);
    }
  }

  await mkdir(path.dirname(output), { recursive: true });
  const staging = await mkdtemp(path.join(path.dirname(output), `.${path.basename(output)}.staging-`));
  try {
    for (const [name, source] of sources) {
      await copyFile(source, path.join(staging, name));
    }

    const latest = {
      version,
      notes: `DolphinAI ${version}`,
      pub_date: new Date().toISOString(),
      platforms,
    };
    await writeFile(path.join(staging, 'latest.json'), `${JSON.stringify(latest, null, 2)}\n`);

    const checksumNames = [...required, 'latest.json'].sort();
    const sums = await Promise.all(
      checksumNames.map(async (name) => `${await sha256(path.join(staging, name))}  ${name}`),
    );
    await writeFile(path.join(staging, 'SHA256SUMS.txt'), `${sums.join('\n')}\n`);
    await publishStagedOutput(staging, output);
    return { names, latest, output };
  } catch (error) {
    await rm(staging, { recursive: true, force: true });
    throw error;
  }
}

async function expectFailure(action, expectedText) {
  try {
    await action();
  } catch (error) {
    if (error.message.includes(expectedText)) return;
    throw error;
  }
  throw new Error(`Expected failure containing: ${expectedText}`);
}

async function selfTest() {
  const root = await mkdtemp(path.join(os.tmpdir(), 'dolphin-release-'));
  try {
    const version = normalizeTag('v0.2.70');
    if (version !== '0.2.70') throw new Error('Tag normalization failed');
    const names = artifactNames(version);
    const input = path.join(root, 'input');
    const output = path.join(root, 'output');
    await mkdir(input, { recursive: true });
    const fixtures = [
      names.windowsSetup, names.windowsUpdater, `${names.windowsUpdater}.sig`, names.macosDmg,
      names.macosUpdater, `${names.macosUpdater}.sig`, names.linuxAppImage, names.linuxDeb,
      names.linuxUpdater, `${names.linuxUpdater}.sig`,
    ];
    await Promise.all(fixtures.map((name) => writeFile(path.join(input, name), name.endsWith('.sig') ? `signature-${name}` : name)));
    const result = await prepareRelease({
      version,
      repository: 'Mars-hub404/apaas-builder-ai',
      tag: 'v0.2.70',
      input,
      output,
    });
    const latest = JSON.parse(await readFile(path.join(output, 'latest.json'), 'utf8'));
    const expectedUrl = releaseUrl('Mars-hub404/apaas-builder-ai', 'v0.2.70', names.linuxUpdater);
    if (latest.platforms['linux-x86_64'].url !== expectedUrl || result.latest.version !== version) {
      throw new Error('latest.json does not use the release download URL');
    }

    await writeFile(path.join(output, 'sentinel.txt'), 'existing release boundary');
    await writeFile(path.join(input, `${names.windowsUpdater}.sig`), ' \n');
    await expectFailure(
      () => prepareRelease({ version, repository: 'Mars-hub404/apaas-builder-ai', tag: 'v0.2.70', input, output }),
      'Updater signature is empty for windows-x86_64',
    );
    if (await readFile(path.join(output, 'sentinel.txt'), 'utf8') !== 'existing release boundary') {
      throw new Error('Empty updater signatures must not modify the release output boundary');
    }
    await writeFile(path.join(input, `${names.windowsUpdater}.sig`), `signature-${names.windowsUpdater}.sig`);

    const duplicate = path.join(input, 'duplicate');
    await mkdir(duplicate);
    await writeFile(path.join(duplicate, names.linuxDeb), names.linuxDeb);
    await expectFailure(
      () => prepareRelease({ version, repository: 'Mars-hub404/apaas-builder-ai', tag: 'v0.2.70', input, output }),
      `Expected exactly one ${names.linuxDeb}`,
    );
    if (await readFile(path.join(output, 'sentinel.txt'), 'utf8') !== 'existing release boundary') {
      throw new Error('Duplicate inputs must not modify the release output boundary');
    }
    await rm(duplicate, { recursive: true, force: true });

    await rm(path.join(input, names.macosDmg));
    await expectFailure(
      () => prepareRelease({ version, repository: 'Mars-hub404/apaas-builder-ai', tag: 'v0.2.70', input, output }),
      names.macosDmg,
    );

    const transactionRoot = path.join(root, 'transaction-tests');
    await mkdir(transactionRoot);
    const failedOutput = path.join(transactionRoot, 'failed-output');
    const failedStaging = path.join(transactionRoot, 'failed-staging');
    await mkdir(failedOutput);
    await mkdir(failedStaging);
    await writeFile(path.join(failedOutput, 'release.txt'), 'previous release');
    await writeFile(path.join(failedStaging, 'release.txt'), 'next release');
    await expectFailure(
      () => publishStagedOutput(failedStaging, failedOutput, {
        rename: async (from, to) => {
          if (from === failedStaging && to === failedOutput) throw new Error('injected publication rename failure');
          return rename(from, to);
        },
      }),
      'injected publication rename failure',
    );
    if (await readFile(path.join(failedOutput, 'release.txt'), 'utf8') !== 'previous release') {
      throw new Error('A failed publication rename must restore the previous release boundary');
    }

    const primaryCleanupOutput = path.join(transactionRoot, 'primary-cleanup-output');
    const primaryCleanupStaging = path.join(transactionRoot, 'primary-cleanup-staging');
    await mkdir(primaryCleanupOutput);
    await mkdir(primaryCleanupStaging);
    await writeFile(path.join(primaryCleanupOutput, 'release.txt'), 'previous release');
    await writeFile(path.join(primaryCleanupStaging, 'release.txt'), 'next release');
    const primaryCleanupWarnings = [];
    await expectFailure(
      () => publishStagedOutput(primaryCleanupStaging, primaryCleanupOutput, {
        rename: async (from, to) => {
          if (from === primaryCleanupStaging && to === primaryCleanupOutput) throw new Error('injected primary rename failure');
          return rename(from, to);
        },
        rm: async (target, options) => {
          if (target === primaryCleanupStaging) throw new Error('injected staging cleanup failure');
          return rm(target, options);
        },
        warn: (message) => primaryCleanupWarnings.push(message),
      }),
      'injected primary rename failure',
    );
    if (primaryCleanupWarnings.length !== 1) {
      throw new Error('Primary publication failures must retain cleanup diagnostics as warnings');
    }

    const rollbackOutput = path.join(transactionRoot, 'rollback-output');
    const rollbackStaging = path.join(transactionRoot, 'rollback-staging');
    await mkdir(rollbackOutput);
    await mkdir(rollbackStaging);
    await writeFile(path.join(rollbackOutput, 'release.txt'), 'previous release');
    await writeFile(path.join(rollbackStaging, 'release.txt'), 'next release');
    const rollbackWarnings = [];
    await expectFailure(
      () => publishStagedOutput(rollbackStaging, rollbackOutput, {
        rename: async (from, to) => {
          if (from === rollbackStaging && to === rollbackOutput) throw new Error('injected publication rename failure');
          if (to === rollbackOutput) throw new Error('injected rollback rename failure');
          return rename(from, to);
        },
        rm: async (target, options) => {
          if (target === rollbackStaging) throw new Error('injected staging cleanup failure');
          return rm(target, options);
        },
        warn: (message) => rollbackWarnings.push(message),
      }),
      'backup retained at',
    );
    if (rollbackWarnings.length !== 1) {
      throw new Error('Rollback failures must retain cleanup diagnostics as warnings');
    }

    const cleanupOutput = path.join(transactionRoot, 'cleanup-output');
    const cleanupStaging = path.join(transactionRoot, 'cleanup-staging');
    await mkdir(cleanupOutput);
    await mkdir(cleanupStaging);
    await writeFile(path.join(cleanupOutput, 'release.txt'), 'previous release');
    await writeFile(path.join(cleanupStaging, 'release.txt'), 'next release');
    const warnings = [];
    let backupCleanupAttempts = 0;
    await publishStagedOutput(cleanupStaging, cleanupOutput, {
      rm: async (target, options) => {
        if (path.basename(target).startsWith('.cleanup-output.backup-')) {
          backupCleanupAttempts += 1;
          if (backupCleanupAttempts === 2) throw new Error('injected backup cleanup failure');
        }
        return rm(target, options);
      },
      warn: (message) => warnings.push(message),
    });
    if (await readFile(path.join(cleanupOutput, 'release.txt'), 'utf8') !== 'next release' || warnings.length !== 1) {
      throw new Error('Backup cleanup failures must warn without undoing a published release');
    }
    console.log('prepare-desktop-release self-test passed');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log('Usage: node scripts/prepare-desktop-release.mjs --version X.Y.Z --repository owner/repo --tag vX.Y.Z --input dist-desktop/release --output dist-desktop/publish');
    return;
  }
  if (options['self-test']) {
    await selfTest();
    return;
  }
  for (const required of ['version', 'repository', 'tag', 'input', 'output']) {
    if (!options[required]) throw new Error(`Missing --${required}`);
  }
  await prepareRelease(options);
}

main().catch((error) => {
  console.error(`Desktop Release preparation failed: ${error.message}`);
  process.exitCode = 1;
});
