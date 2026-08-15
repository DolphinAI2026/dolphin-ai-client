#!/usr/bin/env node
import { appendFile, mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';

const semverPattern = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;

function requiredAssets(version) {
  const prefix = `dolphin-ai-${version}`;
  return {
    windows_setup_url: `${prefix}-windows-x86_64-setup.exe`,
    macos_dmg_url: `${prefix}-macos-aarch64.dmg`,
    linux_appimage_url: `${prefix}-linux-x86_64.AppImage`,
    linux_deb_url: `${prefix}-linux-x86_64.deb`,
    latest_json_url: 'latest.json',
    checksums_url: 'SHA256SUMS.txt',
  };
}

function releaseVersion(tag) {
  if (!tag?.startsWith('v') || !semverPattern.test(tag.slice(1))) {
    throw new Error(`GITHUB_REF_NAME must be a vX.Y.Z SemVer tag: ${tag ?? ''}`);
  }
  return tag.slice(1);
}

function urlsFromRelease(release, version) {
  if (!release?.html_url) throw new Error('GitHub Release response is missing html_url');
  const assets = new Map();
  for (const asset of release.assets ?? []) {
    if (asset?.name && asset?.browser_download_url) assets.set(asset.name, asset.browser_download_url);
  }
  const urls = { release_url: release.html_url };
  for (const [field, name] of Object.entries(requiredAssets(version))) {
    const url = assets.get(name);
    if (!url) throw new Error(`GitHub Release is missing attachment: ${name}`);
    urls[field] = url;
  }
  return urls;
}

async function getRelease({ repository, tag, token, fetchImpl }) {
  if (!/^[^/\s]+\/[^/\s]+$/.test(repository ?? '')) {
    throw new Error(`GITHUB_REPOSITORY must be owner/repo: ${repository ?? ''}`);
  }
  if (!token) throw new Error('GITHUB_TOKEN is required to read the Release');
  const response = await fetchImpl(
    `https://api.github.com/repos/${repository}/releases/tags/${encodeURIComponent(tag)}`,
    { headers: { Accept: 'application/vnd.github+json', Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) throw new Error(`GitHub Release API returned HTTP ${response.status}`);
  return response.json();
}

async function writeReleaseOutputs(urls, outputPath, summaryPath) {
  const lines = Object.entries(urls).map(([name, value]) => `${name}=${value}`);
  await appendFile(outputPath, `${lines.join('\n')}\n`);
  const summary = ['## DolphinAI desktop download addresses', '', '| Download | URL |', '| --- | --- |'];
  for (const [name, value] of Object.entries(urls)) summary.push(`| ${name} | ${value} |`);
  await appendFile(summaryPath, `${summary.join('\n')}\n`);
}

export async function reportRelease({ repository, tag, token, outputPath, summaryPath, fetchImpl = fetch }) {
  const version = releaseVersion(tag);
  const release = await getRelease({ repository, tag, token, fetchImpl });
  const urls = urlsFromRelease(release, version);
  await writeReleaseOutputs(urls, outputPath, summaryPath);
  return urls;
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

function releaseFixture(version, omit = '') {
  const assets = Object.values(requiredAssets(version))
    .filter((name) => name !== omit)
    .map((name) => ({ name, browser_download_url: `https://downloads.example.test/${name}` }));
  return { html_url: `https://github.com/Mars-hub404/apaas-builder-ai/releases/tag/v${version}`, assets };
}

async function selfTest() {
  const root = await mkdtemp(path.join(os.tmpdir(), 'dolphin-release-report-'));
  const outputPath = path.join(root, 'github-output');
  const summaryPath = path.join(root, 'summary');
  const version = '0.2.70';
  const fetchFixture = (release) => async () => ({ ok: true, status: 200, json: async () => release });
  try {
    await expectFailure(
      () => reportRelease({
        repository: 'Mars-hub404/apaas-builder-ai', tag: `v${version}`, token: 'test-token', outputPath, summaryPath,
        fetchImpl: fetchFixture(releaseFixture(version, 'latest.json')),
      }),
      'latest.json',
    );
    const urls = await reportRelease({
      repository: 'Mars-hub404/apaas-builder-ai', tag: `v${version}`, token: 'test-token', outputPath, summaryPath,
      fetchImpl: fetchFixture(releaseFixture(version)),
    });
    const output = await readFile(outputPath, 'utf8');
    if (Object.keys(urls).length !== 7 || output.trim().split('\n').length !== 7) {
      throw new Error('Expected all seven Release URL outputs');
    }
    console.log('report-desktop-release self-test passed');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function main() {
  if (process.argv.slice(2).includes('--self-test')) {
    await selfTest();
    return;
  }
  if (process.argv.slice(2).length > 0) throw new Error('Only --self-test is supported');
  const { GITHUB_REPOSITORY, GITHUB_REF_NAME, GITHUB_TOKEN, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY } = process.env;
  if (!GITHUB_OUTPUT || !GITHUB_STEP_SUMMARY) throw new Error('GITHUB_OUTPUT and GITHUB_STEP_SUMMARY are required');
  await reportRelease({
    repository: GITHUB_REPOSITORY,
    tag: GITHUB_REF_NAME,
    token: GITHUB_TOKEN,
    outputPath: GITHUB_OUTPUT,
    summaryPath: GITHUB_STEP_SUMMARY,
  });
}

main().catch((error) => {
  console.error(`Desktop Release report failed: ${error.message}`);
  process.exitCode = 1;
});
