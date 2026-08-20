import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

export async function configureTauriUpdater(configPath, enabled) {
  const config = JSON.parse(await readFile(configPath, 'utf8'));
  if (!config.bundle || typeof config.bundle !== 'object') {
    throw new Error('Tauri config is missing bundle configuration');
  }
  config.bundle.createUpdaterArtifacts = enabled;
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
}

async function main(argv) {
  const options = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    options.set(argv[index], argv[index + 1]);
  }

  const configPath = options.get('--config');
  const enabledValue = options.get('--enabled');
  if (!configPath || !['true', 'false'].includes(enabledValue)) {
    throw new Error(
      'Usage: node scripts/configure-tauri-updater.mjs --config <path> --enabled true|false',
    );
  }
  await configureTauriUpdater(configPath, enabledValue === 'true');
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
