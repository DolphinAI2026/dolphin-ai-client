import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { configureTauriUpdater } from './configure-tauri-updater.mjs';

async function withConfig(callback) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'dolphin-tauri-updater-'));
  const configPath = path.join(directory, 'tauri.conf.json');
  await writeFile(
    configPath,
    `${JSON.stringify({
      productName: 'DolphinAI',
      version: '0.4.2',
      bundle: { createUpdaterArtifacts: false, targets: ['app', 'dmg'] },
    }, null, 2)}\n`,
    'utf8',
  );

  try {
    await callback(configPath);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test('release configuration enables Tauri updater artifacts without changing other fields', async () => {
  await withConfig(async (configPath) => {
    await configureTauriUpdater(configPath, true);

    const config = JSON.parse(await readFile(configPath, 'utf8'));
    assert.equal(config.bundle.createUpdaterArtifacts, true);
    assert.equal(config.version, '0.4.2');
    assert.deepEqual(config.bundle.targets, ['app', 'dmg']);
  });
});

test('local unsigned configuration disables Tauri updater artifacts', async () => {
  await withConfig(async (configPath) => {
    await configureTauriUpdater(configPath, true);
    await configureTauriUpdater(configPath, false);

    const config = JSON.parse(await readFile(configPath, 'utf8'));
    assert.equal(config.bundle.createUpdaterArtifacts, false);
  });
});
