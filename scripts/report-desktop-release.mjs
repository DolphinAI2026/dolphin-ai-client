#!/usr/bin/env node
import { appendFile, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';

const releaseVersionPattern = /^\d+\.\d+\.\d+$/;

function primaryOutputAssets(version) {
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

function requiredAssets(version) {
  const prefix = `dolphin-ai-${version}`;
  return [
    ...Object.values(primaryOutputAssets(version)),
    `${prefix}-windows-x86_64-updater.nsis.zip`,
    `${prefix}-windows-x86_64-updater.nsis.zip.sig`,
    `${prefix}-macos-aarch64-updater.app.tar.gz`,
    `${prefix}-macos-aarch64-updater.app.tar.gz.sig`,
    `${prefix}-linux-x86_64-updater.AppImage.tar.gz`,
    `${prefix}-linux-x86_64-updater.AppImage.tar.gz.sig`,
  ];
}

function releaseVersion(tag) {
  if (!tag?.startsWith('v') || !releaseVersionPattern.test(tag.slice(1))) {
    throw new Error(`GITHUB_REF_NAME must be a vX.Y.Z SemVer tag: ${tag ?? ''}`);
  }
  return tag.slice(1);
}

function urlsFromRelease(release, version) {
  if (!release?.html_url) throw new Error('GitHub Release response is missing html_url');
  const assets = new Map();
  for (const asset of release.assets ?? []) {
    if (!asset?.name || !asset?.browser_download_url) continue;
    if (assets.has(asset.name)) throw new Error(`GitHub Release has duplicate attachment: ${asset.name}`);
    assets.set(asset.name, asset.browser_download_url);
  }
  const urls = { release_url: release.html_url };
  for (const name of requiredAssets(version)) {
    if (!assets.has(name)) throw new Error(`GitHub Release is missing attachment: ${name}`);
  }
  for (const [field, name] of Object.entries(primaryOutputAssets(version))) {
    const url = assets.get(name);
    urls[field] = url;
  }
  return urls;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function retryDelay(attempt) {
  return Math.min(2_000, 250 * (2 ** (attempt - 1)));
}

function isRetryableStatus(status) {
  return status === 404 || status === 408 || status === 429 || status >= 500;
}

async function getRelease({ repository, tag, token, fetchImpl, timeoutMs = 10_000, maxAttempts = 3, sleepImpl = delay }) {
  if (!/^[^/\s]+\/[^/\s]+$/.test(repository ?? '')) {
    throw new Error(`GITHUB_REPOSITORY must be owner/repo: ${repository ?? ''}`);
  }
  if (!token) throw new Error('GITHUB_TOKEN is required to read the Release');
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1) throw new Error('Release API maxAttempts must be a positive integer');
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('Release API timeoutMs must be positive');

  const url = `https://api.github.com/repos/${repository}/releases/tags/${encodeURIComponent(tag)}`;
  let lastError;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let retryable = false;
    try {
      const response = await fetchImpl(url, {
        headers: { Accept: 'application/vnd.github+json', Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (response.ok) {
        const release = await response.json();
        urlsFromRelease(release, releaseVersion(tag));
        return release;
      }
      lastError = new Error(`GitHub Release API returned HTTP ${response.status}`);
      retryable = isRetryableStatus(response.status);
    } catch (error) {
      lastError = controller.signal.aborted
        ? new Error(`GitHub Release API request timed out after ${timeoutMs}ms`)
        : error;
      retryable = true;
    } finally {
      clearTimeout(timeout);
    }
    if (retryable && attempt < maxAttempts) await sleepImpl(retryDelay(attempt));
    else throw lastError;
  }
  throw lastError;
}

async function writeReleaseOutputs(urls, outputPath, summaryPath) {
  const lines = Object.entries(urls).map(([name, value]) => `${name}=${value}`);
  await appendFile(outputPath, `${lines.join('\n')}\n`);
  const summary = ['## DolphinAI desktop download addresses', '', '| Download | URL |', '| --- | --- |'];
  for (const [name, value] of Object.entries(urls)) summary.push(`| ${name} | ${value} |`);
  await appendFile(summaryPath, `${summary.join('\n')}\n`);
}

export async function reportRelease({
  repository, tag, token, outputPath, summaryPath, fetchImpl = fetch, timeoutMs, maxAttempts, sleepImpl,
}) {
  const version = releaseVersion(tag);
  const release = await getRelease({ repository, tag, token, fetchImpl, timeoutMs, maxAttempts, sleepImpl });
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
  const assets = requiredAssets(version)
    .filter((name) => name !== omit)
    .map((name) => ({ name, browser_download_url: `https://downloads.example.test/${name}` }));
  return { html_url: `https://github.com/DolphinAI2026/dolphin-ai-releases/releases/tag/v${version}`, assets };
}

async function assertUnchanged(pathname, expected, failure, expectedText) {
  await expectFailure(failure, expectedText);
  const actual = await readFile(pathname, 'utf8');
  if (actual !== expected) throw new Error(`Failure must not modify ${path.basename(pathname)}`);
}

async function selfTest() {
  const root = await mkdtemp(path.join(os.tmpdir(), 'dolphin-release-report-'));
  const outputPath = path.join(root, 'github-output');
  const summaryPath = path.join(root, 'summary');
  const version = '0.2.70';
  const fetchFixture = (release) => async () => ({ ok: true, status: 200, json: async () => release });
  try {
    for (const invalidTag of ['v0.2.70-rc.1', 'v0.2.70+build.7']) {
      await expectFailure(
        () => reportRelease({
          repository: 'DolphinAI2026/dolphin-ai-releases',
          tag: invalidTag,
          token: 'test-token',
          outputPath,
          summaryPath,
          fetchImpl: fetchFixture(releaseFixture(version)),
        }),
        'GITHUB_REF_NAME must be a vX.Y.Z SemVer tag',
      );
    }
    await writeFile(outputPath, 'output before failure\n');
    await writeFile(summaryPath, 'summary before failure\n');
    await assertUnchanged(
      outputPath,
      'output before failure\n',
      () => reportRelease({
        repository: 'DolphinAI2026/dolphin-ai-releases', tag: `v${version}`, token: 'test-token', outputPath, summaryPath,
        fetchImpl: fetchFixture(releaseFixture(version, 'latest.json')),
      }),
      'latest.json',
    );
    if (await readFile(summaryPath, 'utf8') !== 'summary before failure\n') {
      throw new Error('Missing attachments must not modify the step summary');
    }

    const duplicate = releaseFixture(version);
    duplicate.assets.push({
      name: 'latest.json',
      browser_download_url: 'https://downloads.example.test/duplicate-latest.json',
    });
    await assertUnchanged(
      outputPath,
      'output before failure\n',
      () => reportRelease({
        repository: 'DolphinAI2026/dolphin-ai-releases', tag: `v${version}`, token: 'test-token', outputPath, summaryPath,
        fetchImpl: fetchFixture(duplicate),
      }),
      'duplicate attachment: latest.json',
    );
    if (await readFile(summaryPath, 'utf8') !== 'summary before failure\n') {
      throw new Error('Duplicate attachments must not modify the step summary');
    }

    await rm(outputPath, { force: true });
    await rm(summaryPath, { force: true });
    let attempts = 0;
    const retryFixture = async () => {
      attempts += 1;
      if (attempts < 3) return { ok: false, status: 503, json: async () => ({}) };
      return { ok: true, status: 200, json: async () => releaseFixture(version) };
    };
    const urls = await reportRelease({
      repository: 'DolphinAI2026/dolphin-ai-releases', tag: `v${version}`, token: 'test-token', outputPath, summaryPath,
      fetchImpl: retryFixture,
      sleepImpl: async () => {},
    });
    const output = await readFile(outputPath, 'utf8');
    if (Object.keys(urls).length !== 7 || output.trim().split('\n').length !== 7 || attempts !== 3) {
      throw new Error('Expected all seven Release URL outputs after bounded API retries');
    }

    let jsonAttempts = 0;
    await reportRelease({
      repository: 'DolphinAI2026/dolphin-ai-releases', tag: `v${version}`, token: 'test-token', outputPath, summaryPath,
      fetchImpl: async () => {
        jsonAttempts += 1;
        if (jsonAttempts === 1) return { ok: true, status: 200, json: async () => { throw new Error('injected JSON parse failure'); } };
        return { ok: true, status: 200, json: async () => releaseFixture(version) };
      },
      sleepImpl: async () => {},
    });
    if (jsonAttempts !== 2) throw new Error('JSON parse failures must retry within the bounded Release API loop');

    let notFoundAttempts = 0;
    await reportRelease({
      repository: 'DolphinAI2026/dolphin-ai-releases', tag: `v${version}`, token: 'test-token', outputPath, summaryPath,
      fetchImpl: async () => {
        notFoundAttempts += 1;
        if (notFoundAttempts === 1) return { ok: false, status: 404, json: async () => ({ message: 'not ready' }) };
        return { ok: true, status: 200, json: async () => releaseFixture(version) };
      },
      sleepImpl: async () => {},
    });
    if (notFoundAttempts !== 2) throw new Error('Release API 404 responses must retry within the bounded loop');

    let incompleteAttempts = 0;
    const missingLinuxSignature = `dolphin-ai-${version}-linux-x86_64-updater.AppImage.tar.gz.sig`;
    await reportRelease({
      repository: 'DolphinAI2026/dolphin-ai-releases', tag: `v${version}`, token: 'test-token', outputPath, summaryPath,
      fetchImpl: async () => {
        incompleteAttempts += 1;
        const release = incompleteAttempts === 1 ? releaseFixture(version, missingLinuxSignature) : releaseFixture(version);
        return { ok: true, status: 200, json: async () => release };
      },
      sleepImpl: async () => {},
    });
    if (incompleteAttempts !== 2) {
      throw new Error('HTTP 200 responses with incomplete Release attachments must retry within the bounded loop');
    }

    const timeoutOutput = path.join(root, 'timeout-output');
    const timeoutSummary = path.join(root, 'timeout-summary');
    await writeFile(timeoutOutput, 'output before timeout\n');
    await writeFile(timeoutSummary, 'summary before timeout\n');
    const timeoutFetch = async (_url, request) => {
      if (!request?.signal) throw new Error('Abort signal is required');
      return new Promise((_resolve, reject) => {
        request.signal.addEventListener('abort', () => reject(request.signal.reason), { once: true });
      });
    };
    await assertUnchanged(
      timeoutOutput,
      'output before timeout\n',
      () => reportRelease({
        repository: 'DolphinAI2026/dolphin-ai-releases', tag: `v${version}`, token: 'test-token',
        outputPath: timeoutOutput, summaryPath: timeoutSummary, fetchImpl: timeoutFetch, timeoutMs: 1, maxAttempts: 1,
      }),
      'timed out',
    );
    if (await readFile(timeoutSummary, 'utf8') !== 'summary before timeout\n') {
      throw new Error('Timed out requests must not modify the step summary');
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
  const {
    RELEASE_REPOSITORY, GITHUB_REF_NAME, RELEASES_GITHUB_TOKEN, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY,
  } = process.env;
  if (!GITHUB_OUTPUT || !GITHUB_STEP_SUMMARY) throw new Error('GITHUB_OUTPUT and GITHUB_STEP_SUMMARY are required');
  if (!RELEASE_REPOSITORY) throw new Error('RELEASE_REPOSITORY is required to read the public Release');
  if (!RELEASES_GITHUB_TOKEN) throw new Error('RELEASES_GITHUB_TOKEN is required to read the public Release');
  await reportRelease({
    repository: RELEASE_REPOSITORY,
    tag: GITHUB_REF_NAME,
    token: RELEASES_GITHUB_TOKEN,
    outputPath: GITHUB_OUTPUT,
    summaryPath: GITHUB_STEP_SUMMARY,
  });
}

main().catch((error) => {
  console.error(`Desktop Release report failed: ${error.message}`);
  process.exitCode = 1;
});
