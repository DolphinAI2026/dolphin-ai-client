import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

export async function configureMacosSigning(configPath, mode) {
  if (mode !== 'adhoc') {
    throw new Error(`Unsupported macOS signing mode: ${mode}`);
  }

  const config = JSON.parse(await readFile(configPath, 'utf8'));
  config.bundle ??= {};
  config.bundle.macOS ??= {};
  config.bundle.macOS.signingIdentity = '-';
  config.bundle.macOS.hardenedRuntime = false;
  await writeFile(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
}

function parseArgs(argv) {
  const args = { config: '', mode: '' };
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (name === '--config') args.config = value;
    else if (name === '--mode') args.mode = value;
    else throw new Error(`Unknown argument: ${name}`);
  }
  if (!args.config || !args.mode) {
    throw new Error('Usage: configure-macos-signing.mjs --config <path> --mode adhoc');
  }
  return args;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = parseArgs(process.argv.slice(2));
  await configureMacosSigning(args.config, args.mode);
}
