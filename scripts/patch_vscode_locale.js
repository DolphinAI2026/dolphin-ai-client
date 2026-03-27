const fs = require('fs');
const path = require('path');

const homeDir = process.env.HOME || '/Users/mars';
const codeServerDataDir =
  process.env.CODE_SERVER_DATA_DIR || path.join(homeDir, '.local', 'share', 'code-server');
const serverCliPath =
  '/Users/mars/.local/lib/code-server-4.112.0/lib/vscode/out/server-cli.js';
const codeServerConfigPath = path.join(homeDir, '.config', 'code-server', 'config.yaml');
const localeFilePath = path.join(codeServerDataDir, 'User', 'locale.json');
const languagePacksPath = path.join(codeServerDataDir, 'languagepacks.json');
const languagePackDir = path.join(
  codeServerDataDir,
  'extensions',
  'ms-ceintl.vscode-language-pack-zh-hans-1.110.0-universal',
);
const languagePackManifestPath = path.join(languagePackDir, 'package.json');

const hardcodedNlsSnippet =
  'var g2=await f2({userLocale:"en",osLocale:"en",commit:ri.commit,userDataPath:"",nlsMetadataPath:import.meta.dirname});';
const dynamicNlsSnippet =
  'var m2="en",b2=process.env.CODE_SERVER_DATA_DIR||K(process.env.HOME||"",".local","share","code-server");try{const e=JSON.parse(await y1.readFile(K(b2,"User","locale.json"),"utf-8"));typeof e?.locale=="string"&&e.locale&&(m2=e.locale.toLowerCase())}catch{}var g2=await f2({userLocale:m2,osLocale:m2,commit:ri.commit,userDataPath:b2,nlsMetadataPath:import.meta.dirname});';

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function ensureLocaleFiles() {
  ensureDir(path.dirname(localeFilePath));

  const localePayload = JSON.stringify({ locale: 'zh-cn' }, null, 2);
  if (!fs.existsSync(localeFilePath) || fs.readFileSync(localeFilePath, 'utf8').trim() !== localePayload) {
    fs.writeFileSync(localeFilePath, `${localePayload}\n`);
  }

  if (fs.existsSync(codeServerConfigPath)) {
    const config = fs.readFileSync(codeServerConfigPath, 'utf8');
    if (!/^\s*locale:\s*zh-cn\s*$/m.test(config)) {
      const next = `${config.replace(/\s+$/, '')}\nlocale: zh-cn\n`;
      fs.writeFileSync(codeServerConfigPath, next);
    }
  }
}

function writeLanguagePackIndex() {
  if (!fs.existsSync(languagePackManifestPath)) {
    throw new Error(`Language pack manifest not found: ${languagePackManifestPath}`);
  }

  const manifest = JSON.parse(fs.readFileSync(languagePackManifestPath, 'utf8'));
  const localization = manifest.contributes?.localizations?.find((entry) => entry.languageId === 'zh-cn');
  if (!localization) {
    throw new Error('Could not find zh-cn localization entry in language pack manifest');
  }

  const translations = Object.fromEntries(
    localization.translations.map((entry) => [
      entry.id,
      path.join(languagePackDir, entry.path.replace(/^\.\//, '')),
    ]),
  );

  const payload = {
    'zh-cn': {
      hash: 'ms-ceintl.vscode-language-pack-zh-hans',
      extensions: [
        {
          extensionIdentifier: { id: 'ms-ceintl.vscode-language-pack-zh-hans' },
          version: manifest.version,
        },
      ],
      translations,
    },
  };

  ensureDir(path.dirname(languagePacksPath));
  fs.writeFileSync(languagePacksPath, `${JSON.stringify(payload, null, 2)}\n`);
}

function patchServerCli() {
  const source = fs.readFileSync(serverCliPath, 'utf8');
  if (source.includes(dynamicNlsSnippet)) {
    return 'already-patched';
  }

  if (!source.includes(hardcodedNlsSnippet)) {
    throw new Error('Could not locate hardcoded NLS bootstrap snippet in server-cli.js');
  }

  fs.copyFileSync(serverCliPath, `${serverCliPath}.bak-locale-20260327`);
  fs.writeFileSync(serverCliPath, source.replace(hardcodedNlsSnippet, dynamicNlsSnippet));
  return 'patched';
}

function main() {
  ensureLocaleFiles();
  writeLanguagePackIndex();
  const patchState = patchServerCli();
  console.log(`Locale bootstrap ${patchState}.`);
  console.log(`Locale file: ${localeFilePath}`);
  console.log(`Language packs index: ${languagePacksPath}`);
}

main();
