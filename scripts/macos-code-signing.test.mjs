import assert from 'node:assert/strict';
import { chmod, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));

async function withTemporaryDirectory(callback) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'dolphin-macos-signing-'));
  try {
    await callback(directory);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test('ad-hoc signing configuration disables hardened runtime', async () => {
  await withTemporaryDirectory(async (directory) => {
    const configPath = path.join(directory, 'tauri.conf.json');
    await writeFile(
      configPath,
      `${JSON.stringify({ bundle: { macOS: { exceptionDomain: '' } } }, null, 2)}\n`,
      'utf8',
    );

    const result = spawnSync(
      process.execPath,
      [path.join(root, 'scripts/configure-macos-signing.mjs'), '--config', configPath, '--mode', 'adhoc'],
      { encoding: 'utf8' },
    );

    assert.equal(result.status, 0, result.stderr);
    const config = JSON.parse(await readFile(configPath, 'utf8'));
    assert.equal(config.bundle.macOS.signingIdentity, '-');
    assert.equal(config.bundle.macOS.hardenedRuntime, false);
  });
});

test('signing helper signs Mach-O resources and verifies the final app', async () => {
  await withTemporaryDirectory(async (directory) => {
    const fakeBin = path.join(directory, 'bin');
    const resources = path.join(directory, 'resources');
    const app = path.join(directory, 'DolphinAI.app');
    const logPath = path.join(directory, 'codesign.log');
    await mkdir(fakeBin);
    await mkdir(resources);
    await mkdir(app);
    await writeFile(path.join(resources, 'runtime.macho'), 'binary', 'utf8');
    await writeFile(path.join(resources, 'readme.txt'), 'text', 'utf8');

    const fakeFile = path.join(fakeBin, 'file');
    await writeFile(
      fakeFile,
      '#!/usr/bin/env bash\n[[ "$2" == *.macho ]] && echo "Mach-O 64-bit executable" || echo "ASCII text"\n',
      'utf8',
    );
    await chmod(fakeFile, 0o755);

    const fakeCodesign = path.join(fakeBin, 'codesign');
    await writeFile(
      fakeCodesign,
      '#!/usr/bin/env bash\n/usr/bin/printf "%s\\n" "$*" >> "$DOLPHIN_CODESIGN_LOG"\n',
      'utf8',
    );
    await chmod(fakeCodesign, 0o755);

    const helper = path.join(root, 'scripts/macos-code-signing.sh');
    const environment = {
      ...process.env,
      PATH: `${fakeBin}:${process.env.PATH}`,
      DOLPHIN_CODESIGN_LOG: logPath,
    };
    const signResult = spawnSync('bash', [helper, 'sign-resources', resources], {
      encoding: 'utf8',
      env: environment,
    });
    assert.equal(signResult.status, 0, signResult.stderr);

    const verifyResult = spawnSync('bash', [helper, 'verify-app', app], {
      encoding: 'utf8',
      env: environment,
    });
    assert.equal(verifyResult.status, 0, verifyResult.stderr);

    const calls = (await readFile(logPath, 'utf8')).trim().split('\n');
    assert.deepEqual(calls, [
      `--force --sign - --timestamp=none ${path.join(resources, 'runtime.macho')}`,
      `--verify --deep --strict --verbose=4 ${app}`,
    ]);
  });
});

test('desktop build verifies the signed app before packaging and publishing', async () => {
  const buildScript = await readFile(path.join(root, 'scripts/build-desktop.sh'), 'utf8');
  assert.match(
    buildScript,
    /bash "\$ROOT\/scripts\/macos-code-signing\.sh" sign-resources/,
    'the signing helper must not depend on the executable bit being preserved',
  );
  const signResources = buildScript.indexOf('macos-code-signing.sh" sign-resources');
  const tauriBuild = buildScript.indexOf('cd "$ROOT" && run_tauri_build "$BUNDLES"');
  const verifyApp = buildScript.indexOf('macos-code-signing.sh" verify-app');
  const fallbackDmg = buildScript.indexOf('create_macos_fallback_dmg', verifyApp);
  const publish = buildScript.indexOf('publish_macos_arm_release', verifyApp);

  assert.ok(signResources >= 0, 'macOS Runtime resources must be signed');
  assert.ok(signResources < tauriBuild, 'Runtime resources must be signed before Tauri bundles the app');
  assert.ok(verifyApp > tauriBuild, 'the final app must be verified after Tauri bundling');
  assert.ok(fallbackDmg > verifyApp, 'the DMG must be created only after app verification');
  assert.ok(publish > verifyApp, 'release artifacts must be published only after app verification');
});
