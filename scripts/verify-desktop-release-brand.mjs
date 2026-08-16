#!/usr/bin/env node
import { readdir } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const forbidden = ['ruijing-', 'Dolphin Code', 'ruijing-sidecar'];

const platforms = {
  windows: ['windows-x86_64-setup.exe'],
  linux: ['linux-x86_64.AppImage', 'linux-x86_64.deb'],
  'linux-x86_64': ['linux-x86_64.AppImage', 'linux-x86_64.deb'],
  macos: ['macos-aarch64.dmg'],
  'macos-aarch64': ['macos-aarch64.dmg'],
  'macos-x86_64': ['macos-x86_64.dmg'],
};

function usage() {
  console.log(`Usage: node scripts/verify-desktop-release-brand.mjs --root <dir> --version <X.Y.Z> --platform <platform> [--require-updater]

Checks a formal desktop artifact directory for the required DolphinAI package name and
rejects legacy branding. Platforms: windows, linux, macos, macos-x86_64.`);
}

function parseArgs(argv) {
  const values = { requireUpdater: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--help' || argument === '-h') {
      values.help = true;
    } else if (argument === '--require-updater') {
      values.requireUpdater = true;
    } else if (argument === '--root' || argument === '--version' || argument === '--platform') {
      const value = argv[index + 1];
      if (!value || value.startsWith('--')) {
        throw new Error(`Missing value for ${argument}`);
      }
      values[argument.slice(2)] = value;
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${argument}`);
    }
  }
  return values;
}

async function listFiles(root) {
  const files = [];
  async function walk(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        await walk(absolute);
      } else if (entry.isFile()) {
        files.push(path.relative(root, absolute));
      }
    }
  }
  await walk(root);
  return files;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    usage();
    return;
  }
  if (!options.root || !options.version || !options.platform) {
    usage();
    throw new Error('--root, --version, and --platform are required');
  }

  const suffixes = platforms[options.platform];
  if (!suffixes) {
    throw new Error(`Unsupported platform: ${options.platform}`);
  }

  const root = path.resolve(options.root);
  const requiredPrefix = `dolphin-ai-${options.version}-`;
  const requiredArtifacts = suffixes.map((suffix) => `${requiredPrefix}${suffix}`);
  let files;
  try {
    files = await listFiles(root);
  } catch (error) {
    throw new Error(`Cannot read artifact directory ${root}: ${error.message}`);
  }

  const failures = [];
  for (const requiredArtifact of requiredArtifacts) {
    if (!files.includes(requiredArtifact)) {
      failures.push(`Missing required artifact: ${requiredArtifact}`);
    }
  }
  let legacyCount = 0;
  for (const file of files) {
    if (forbidden.some((value) => file.toLowerCase().includes(value.toLowerCase()))) {
      legacyCount += 1;
      if (legacyCount <= 20) {
        failures.push(`Legacy brand found: ${file}`);
      }
    }
  }
  if (legacyCount > 20) {
    failures.push(`Legacy brand found in ${legacyCount - 20} additional paths`);
  }
  if (options.requireUpdater && !files.some((file) => file.endsWith('.sig'))) {
    failures.push('Missing updater signature (.sig)');
  }

  if (failures.length > 0) {
    throw new Error(failures.join('\n'));
  }
  console.log(`Desktop release brand gate passed: ${root}`);
}

main().catch((error) => {
  console.error(`Desktop release brand gate failed: ${error.message}`);
  process.exitCode = 1;
});
