#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { promisify } from 'node:util';
import { execFile as execFileCallback } from 'node:child_process';

const execFile = promisify(execFileCallback);
const releaseVersionPattern = /^\d+\.\d+\.\d+$/;
const metadataMarker = 'dolphin-ai-release-metadata:';
const publicRepositoryFiles = new Set(['README.md', '.gitignore']);
const uploadRetryDelays = [2_000, 5_000, 10_000];
const transientUploadFailurePattern = /error connecting to api\.uploads\.github\.com|ECONNRESET|ETIMEDOUT|EAI_AGAIN|ENOTFOUND|socket hang up|network is unreachable|status 5\d\d|HTTP 5\d\d|status 429|rate limit/i;

function requireVersion(version, label = 'Version') {
  if (!releaseVersionPattern.test(version ?? '')) throw new Error(`${label} must be X.Y.Z SemVer: ${version ?? ''}`);
  return version;
}

function requireRepository(repository, label = 'Repository') {
  if (!/^[^/\s]+\/[^/\s]+$/.test(repository ?? '')) throw new Error(`${label} must be owner/repo: ${repository ?? ''}`);
  return repository;
}

function releaseVersionFromTag(tag) {
  if (!tag?.startsWith('v')) throw new Error(`Release tag must be vX.Y.Z SemVer: ${tag ?? ''}`);
  return requireVersion(tag.slice(1), 'Release tag');
}

export function expectedAssetNames(version) {
  requireVersion(version);
  const prefix = `dolphin-ai-${version}`;
  return [
    `${prefix}-windows-x86_64-setup.exe`,
    `${prefix}-windows-x86_64-setup.exe.sig`,
    `${prefix}-macos-aarch64.dmg`,
    `${prefix}-macos-aarch64-updater.app.tar.gz`,
    `${prefix}-macos-aarch64-updater.app.tar.gz.sig`,
    `${prefix}-linux-x86_64.AppImage`,
    `${prefix}-linux-x86_64.AppImage.sig`,
    `${prefix}-linux-x86_64.deb`,
    'latest.json',
    'SHA256SUMS.txt',
  ];
}

function metadataBody(metadata) {
  return [
    'DolphinAI desktop release.',
    '',
    `<!-- ${metadataMarker} ${JSON.stringify(metadata)} -->`,
  ].join('\n');
}

export function parseReleaseMetadata(body) {
  const match = body?.match(/<!--\s*dolphin-ai-release-metadata:\s*(\{.*?\})\s*-->/s);
  if (!match) throw new Error('Release is missing DolphinAI source metadata');
  let metadata;
  try {
    metadata = JSON.parse(match[1]);
  } catch {
    throw new Error('Release DolphinAI source metadata is invalid JSON');
  }
  for (const field of ['source_repository', 'source_revision', 'updater_public_key_fingerprint', 'built_at']) {
    if (typeof metadata[field] !== 'string' || !metadata[field]) throw new Error(`Release metadata field is missing: ${field}`);
  }
  return metadata;
}

export function validateExistingRelease({ release, tag, sourceRevision }) {
  if (!release) return { state: 'absent' };
  if (release.tag_name !== tag) throw new Error(`Release tag mismatch: expected ${tag}, received ${release.tag_name ?? ''}`);
  if (!release.draft) throw new Error(`Release ${tag} is already published; use a new version`);
  const metadata = parseReleaseMetadata(release.body);
  if (metadata.source_revision !== sourceRevision) {
    throw new Error(`Draft Release source revision ${metadata.source_revision} does not match candidate ${sourceRevision}`);
  }
  return { state: 'draft', metadata };
}

export function validateCandidateVersion({ candidate, currentLatest }) {
  requireVersion(candidate, 'Candidate version');
  if (!currentLatest) return true;
  requireVersion(currentLatest, 'Current latest version');
  const candidateParts = candidate.split('.').map(Number);
  const latestParts = currentLatest.split('.').map(Number);
  for (let index = 0; index < candidateParts.length; index += 1) {
    if (candidateParts[index] > latestParts[index]) return true;
    if (candidateParts[index] < latestParts[index]) break;
  }
  throw new Error(`Candidate version ${candidate} must be strictly newer than current latest ${currentLatest}`);
}

export function validateReleaseAssets({ version, assets, expectedDigests = new Map() }) {
  const expected = expectedAssetNames(version);
  const found = new Map();
  for (const asset of assets ?? []) {
    if (!asset?.name) continue;
    if (found.has(asset.name)) throw new Error(`Release has duplicate attachment: ${asset.name}`);
    found.set(asset.name, asset);
  }
  for (const name of expected) {
    const asset = found.get(name);
    if (!asset) throw new Error(`Release is missing attachment: ${name}`);
    if (!Number.isFinite(asset.size) || asset.size < 1) throw new Error(`Release attachment is empty: ${name}`);
    const expectedDigest = expectedDigests.get(name);
    if (expectedDigest && asset.digest !== `sha256:${expectedDigest}`) {
      throw new Error(`Release attachment SHA-256 mismatch: ${name}`);
    }
  }
  for (const name of found.keys()) {
    if (!expected.includes(name)) throw new Error(`Release has attachment outside the allowlist: ${name}`);
  }
  return true;
}

function parseArgs(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--help' || argument === '-h' || argument === '--self-test') {
      options[argument.replace(/^--?/, '')] = true;
      continue;
    }
    if (!['--repository', '--tag', '--source-repository', '--source-revision', '--input', '--pubkey'].includes(argument)) {
      throw new Error(`Unknown argument: ${argument}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith('--')) throw new Error(`Missing value for ${argument}`);
    options[argument.slice(2)] = value;
    index += 1;
  }
  return options;
}

async function fileDigest(file) {
  return createHash('sha256').update(await readFile(file)).digest('hex');
}

async function runGh(args, { input, parseJson = true } = {}) {
  const result = await execFile('gh', args, { input, maxBuffer: 10 * 1024 * 1024 });
  return parseJson ? JSON.parse(result.stdout) : result.stdout;
}

async function getJson(repository, route) {
  return runGh(['api', `repos/${repository}/${route}`]);
}

async function listReleases(repository) {
  const releases = await getJson(repository, 'releases?per_page=100');
  if (!Array.isArray(releases)) throw new Error('GitHub Releases API returned an invalid collection');
  return releases;
}

async function assertPublicRepositoryLayout(repository) {
  const entries = await getJson(repository, 'contents');
  if (!Array.isArray(entries)) throw new Error('Public releases repository root is not a directory listing');
  for (const entry of entries) {
    if (entry.type !== 'file' || !publicRepositoryFiles.has(entry.name)) {
      throw new Error(`Public releases repository contains prohibited entry: ${entry.name ?? 'unknown'}`);
    }
  }
}

async function createDraftRelease({ repository, tag, body }) {
  return runGh([
    'api', '--method', 'POST', `repos/${repository}/releases`,
    '-f', `tag_name=${tag}`,
    '-f', 'target_commitish=main',
    '-f', `name=DolphinAI ${tag}`,
    '-F', 'draft=true',
    '-F', 'prerelease=false',
    '-f', `body=${body}`,
  ]);
}

async function patchRelease({ repository, releaseId, body, publish = false }) {
  const args = ['api', '--method', 'PATCH', `repos/${repository}/releases/${releaseId}`, '-f', `body=${body}`];
  if (publish) args.push('-F', 'draft=false', '-F', 'make_latest=true');
  return runGh(args);
}

async function removeExpectedDraftAssets({ repository, release }) {
  for (const asset of release.assets ?? []) {
    await runGh(['api', '--method', 'DELETE', `repos/${repository}/releases/assets/${asset.id}`], { parseJson: false });
  }
}

function isTransientUploadFailure(error) {
  return transientUploadFailurePattern.test([
    error?.message,
    error?.stderr,
    error?.stdout,
  ].filter(Boolean).join('\n'));
}

export async function retryTransientUpload(operation, { delays = uploadRetryDelays } = {}) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      const delay = delays[attempt];
      if (!isTransientUploadFailure(error) || delay === undefined) throw error;
      console.warn(`GitHub Release upload connection failed; retrying in ${delay / 1_000}s (${attempt + 1}/${delays.length}).`);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
}

export function releaseUploadArgs({ repository, tag, file }) {
  return ['release', 'upload', tag, file, '--repo', repository, '--clobber'];
}

async function uploadReleaseAsset({ repository, tag, file }) {
  await retryTransientUpload(() => runGh(
    releaseUploadArgs({ repository, tag, file }),
    { parseJson: false },
  ));
}

async function getLatestRelease(repository) {
  try {
    return await getJson(repository, 'releases/latest');
  } catch (error) {
    if (error.stderr?.includes('404') || error.message.includes('404')) return null;
    throw error;
  }
}

function validateManifest({ input, version, repository, tag }) {
  const latest = JSON.parse(input);
  if (latest.version !== version) throw new Error(`latest.json version mismatch: ${latest.version ?? ''}`);
  for (const [platform, update] of Object.entries(latest.platforms ?? {})) {
    if (!update?.url?.startsWith(`https://github.com/${repository}/releases/download/${tag}/`)) {
      throw new Error(`latest.json has an invalid ${platform} updater URL`);
    }
    if (!update.signature) throw new Error(`latest.json has an empty ${platform} updater signature`);
  }
}

async function publishRelease(options) {
  const repository = requireRepository(options.repository, 'Release repository');
  const sourceRepository = requireRepository(options['source-repository'], 'Source repository');
  const tag = options.tag;
  const version = releaseVersionFromTag(tag);
  const sourceRevision = options['source-revision'];
  if (!/^[0-9a-f]{7,64}$/i.test(sourceRevision ?? '')) throw new Error('Source revision must be a Git SHA');
  const input = path.resolve(options.input);
  const pubkey = path.resolve(options.pubkey);
  const sourceFiles = new Map();
  for (const name of expectedAssetNames(version)) {
    const file = path.join(input, name);
    const info = await stat(file).catch(() => null);
    if (!info?.isFile() || info.size < 1) throw new Error(`Release input is missing or empty: ${name}`);
    sourceFiles.set(name, file);
  }
  validateManifest({ input: await readFile(path.join(input, 'latest.json'), 'utf8'), version, repository, tag });
  const publicKeyFingerprint = createHash('sha256').update(await readFile(pubkey)).digest('hex');
  const metadata = {
    source_repository: sourceRepository,
    source_revision: sourceRevision,
    updater_public_key_fingerprint: publicKeyFingerprint,
    built_at: new Date().toISOString(),
  };
  const body = metadataBody(metadata);
  const expectedDigests = new Map(await Promise.all(
    [...sourceFiles].map(async ([name, file]) => [name, await fileDigest(file)]),
  ));

  await assertPublicRepositoryLayout(repository);
  const releases = await listReleases(repository);
  let release = releases.find((candidate) => candidate.tag_name === tag);
  const existing = validateExistingRelease({ release, tag, sourceRevision });
  if (!release) release = await createDraftRelease({ repository, tag, body });
  else {
    if (existing.metadata.updater_public_key_fingerprint !== publicKeyFingerprint) {
      throw new Error('Draft Release updater public key fingerprint differs from the current signing key');
    }
    const allowed = new Set(expectedAssetNames(version));
    const unexpectedAsset = (release.assets ?? []).find((asset) => !allowed.has(asset.name));
    if (unexpectedAsset) throw new Error(`Draft Release has attachment outside the allowlist: ${unexpectedAsset.name}`);
    await removeExpectedDraftAssets({ repository, release });
    release = await patchRelease({ repository, releaseId: release.id, body });
  }

  for (const [, file] of sourceFiles) await uploadReleaseAsset({ repository, tag, file });
  const verified = (await listReleases(repository)).find((candidate) => candidate.id === release.id);
  if (!verified) throw new Error('Draft Release disappeared before verification');
  validateReleaseAssets({ version, assets: verified.assets, expectedDigests });

  const currentLatest = await getLatestRelease(repository);
  validateCandidateVersion({ candidate: version, currentLatest: currentLatest ? releaseVersionFromTag(currentLatest.tag_name) : null });
  const latestBeforePublish = await getLatestRelease(repository);
  validateCandidateVersion({ candidate: version, currentLatest: latestBeforePublish ? releaseVersionFromTag(latestBeforePublish.tag_name) : null });
  const published = await patchRelease({ repository, releaseId: release.id, body, publish: true });
  if (published.draft) throw new Error('GitHub did not publish the verified draft Release');
  return published;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log('Usage: node scripts/publish-desktop-release.mjs --repository owner/repo --tag vX.Y.Z --source-repository owner/repo --source-revision SHA --input dist-desktop/publish --pubkey /path/to/updater.pub');
    return;
  }
  if (options['self-test']) {
    console.log('Run node --test scripts/publish-desktop-release.test.mjs');
    return;
  }
  for (const name of ['repository', 'tag', 'source-repository', 'source-revision', 'input', 'pubkey']) {
    if (!options[name]) throw new Error(`Missing --${name}`);
  }
  const release = await publishRelease(options);
  console.log(`Published ${release.html_url}`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    console.error(`Desktop Release publication failed: ${error.message}`);
    process.exitCode = 1;
  });
}
