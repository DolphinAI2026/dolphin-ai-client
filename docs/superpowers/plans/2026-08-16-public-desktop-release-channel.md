# DolphinAI Public Desktop Release Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the private DolphinAI source repository build signed Windows, macOS, and Linux packages and publish only verified assets to `DolphinAI2026/dolphin-ai-releases`.

**Architecture:** Build jobs remain in the private source repository with read-only source permissions. A single serialized release job uses a cross-repository secret only to create a public draft release, upload the exact allowlist, verify it, then publish it as latest. The client updater endpoint and generated manifest both resolve exclusively to the public binaries repository.

**Tech Stack:** GitHub Actions, GitHub REST API via `gh`, Node.js release scripts, Tauri updater signing, JSON/YAML static validation.

## Global Constraints

- Public repository: `DolphinAI2026/dolphin-ai-releases`; private source repository: `DolphinAI2026/dolphin-ai-client`.
- Public repository contains only `README.md`, `.gitignore`, and GitHub Release assets; it must never contain business source trees.
- New signing key only; private key and password are GitHub Secrets plus an ACL-restricted desktop backup, never committed or printed.
- `workflow_dispatch` defaults to `publish=false`; dry-run must not tag source or create/write any public release.
- `publish=true` accepts only an already-existing source `vX.Y.Z` tag and cannot create, push, or move a tag.
- All official assets are uploaded as a draft before verification; only a verified complete draft can become latest.
- Do not run full desktop builds locally for this configuration change. Run only Node self-tests, JSON/YAML static checks, and shell/PowerShell syntax checks.

---

### Task 1: Make release helpers explicit about the public repository

**Files:**
- Modify: `scripts/prepare-desktop-release.mjs`
- Modify: `scripts/report-desktop-release.mjs`

**Interfaces:**
- Consumes: `RELEASE_REPOSITORY`, `RELEASES_GITHUB_TOKEN`, `GITHUB_REF_NAME`, `GITHUB_OUTPUT`, `GITHUB_STEP_SUMMARY`.
- Produces: `latest.json` URLs and GitHub Actions URL outputs that reference only `DolphinAI2026/dolphin-ai-releases`.

- [x] **Step 1: Write a failing helper self-test**

Add a self-test invoking the command entry point with `RELEASE_REPOSITORY=DolphinAI2026/dolphin-ai-releases` and assert generated URLs use that repository. Add an invalid `RELEASE_REPOSITORY` assertion that fails before writing outputs.

- [x] **Step 2: Run helper self-tests to verify the new assertion fails**

Run: `node scripts/prepare-desktop-release.mjs --self-test && node scripts/report-desktop-release.mjs --self-test`

Expected: the newly added repository assertion fails before implementation.

- [x] **Step 3: Implement explicit repository/token environment handling**

Keep function parameters testable. Change only the production entry point so it consumes `RELEASE_REPOSITORY` and `RELEASES_GITHUB_TOKEN`, validates `owner/repo`, and refuses to fall back to `GITHUB_REPOSITORY` or `GITHUB_TOKEN`.

- [x] **Step 4: Run helper self-tests**

Run: `node scripts/prepare-desktop-release.mjs --self-test && node scripts/report-desktop-release.mjs --self-test`

Expected: PASS.

### Task 2: Replace private-source release publication with verified public draft publication

**Files:**
- Modify: `.github/workflows/desktop-release.yml`
- Create: `scripts/publish-desktop-release.mjs`

**Interfaces:**
- Consumes: downloaded `dist-desktop/publish/` assets, `RELEASES_GITHUB_TOKEN`, public repository `main`, source tag, source SHA, updater public key.
- Produces: a public draft Release with exact allowlist; after verification, a published latest Release and output download URLs.

- [x] **Step 1: Write a failing Node self-test for release-state validation**

Create `scripts/publish-desktop-release.mjs` with exported pure functions and a `--self-test` mode. Cover: a missing allowlist asset fails, an already-published matching tag fails, an existing draft with a different source SHA fails, and a candidate version not strictly greater than current latest fails.

- [x] **Step 2: Run the self-test to verify the missing implementation fails**

Run: `node scripts/publish-desktop-release.mjs --self-test`

Expected: FAIL because the functions are not implemented.

- [x] **Step 3: Implement draft-first release validation**

Implement pure allowlist/version/draft metadata validation plus a CLI that calls GitHub API through `gh`: create/reuse only a matching draft, remove expected draft assets before retry upload, upload exact assets, re-read attachment names and SHA-256, validate `latest.json` URLs, then publish as latest. Persist source repo/SHA, public key fingerprint, and build timestamp in the Release body. Reject public repository source directories before release actions.

- [x] **Step 4: Update the workflow to use the helper**

Add `publish` boolean input defaulting to false. Make metadata job read-only and require an existing matching source tag only for `publish=true`; tag trigger sets publish true. Build jobs always use the validated SHA. Gate the serialized public release job behind publish, pass only `RELEASES_GITHUB_TOKEN`, pass public repository `main` as release target, prepare artifacts with the public repository, and call the report helper after final publication.

- [x] **Step 5: Run focused checks**

Run: `node scripts/publish-desktop-release.mjs --self-test && ruby -e 'require "yaml"; YAML.load_file(".github/workflows/desktop-release.yml"); puts "workflow YAML valid"'`

Expected: PASS and valid YAML.

### Task 3: Point the client and operations documentation to the new channel

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `docs/windows-desktop-build.md`
- Modify: `scripts/release-desktop.sh`

**Interfaces:**
- Consumes: new updater public key and public release repository URL.
- Produces: updater configuration and operator instructions that cannot route to the legacy repository or legacy manual release script.

- [x] **Step 1: Write the updater configuration assertions**

Use a Node one-liner to assert that `plugins.updater.endpoints` contains the public release URL and that `pubkey` is non-empty; initially it must fail against the legacy URL.

- [x] **Step 2: Run the assertion to verify it fails**

Run the assertion before configuration changes.

Expected: FAIL because the current endpoint is `Mars-hub404/apaas-builder-ai`.

- [x] **Step 3: Apply the new public endpoint and public key**

Generate a new Tauri key pair outside the repository, install its public key in Tauri configuration, rewrite operator documentation for draft-first public releases and dry-run, and mark the obsolete manual upload script as deprecated without deleting historical tooling.

- [x] **Step 4: Run static configuration checks**

Run: JSON parse, the endpoint/public-key assertion, `bash -n scripts/release-desktop.sh`, and a repository-wide search confirming official release configuration has no legacy endpoint.

Expected: PASS.

### Task 4: Provision public release infrastructure and secrets

**Files:**
- External: GitHub repository `DolphinAI2026/dolphin-ai-releases`
- External: GitHub Actions Secrets in `DolphinAI2026/dolphin-ai-client`
- External secure backup: Windows Desktop `DolphinAI-updater-backup/`

**Interfaces:**
- Consumes: a GitHub credential with repository administration, a new Tauri private key, and a cross-repository release token.
- Produces: initialized public repository `main`, restricted Secrets, and an ACL-restricted local recovery backup.

- [x] **Step 1: Provision the empty public repository**

Create `DolphinAI2026/dolphin-ai-releases` as public, add only `README.md` and `.gitignore`, verify its default branch is `main`, and verify it has no source directories.

- [x] **Step 2: Generate and securely back up the new updater key**

Generate the key in `/tmp/d-ai-code/public-desktop-release/`, copy the private key and password to `C:\Users\Administrator\Desktop\DolphinAI-updater-backup\`, restrict the directory to the current Windows user, and maintain a Linux mode-600 recovery copy outside the repository. Do not display secret material.

- [x] **Step 3: Upload repository secrets without logging values**

Set `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, and `RELEASES_GITHUB_TOKEN` in the private source repository. Verify only secret names via GitHub API. Record that the release token should later be replaced with a fine-grained token scoped to the public repository and `Contents: write`.

- [x] **Step 4: Verify GitHub infrastructure state**

Read public repository metadata, default branch, empty source-tree policy, and private source secret-name inventory. Do not dispatch any workflow and do not create a release tag.

### Task 5: Execute dry-run checks and close out the configuration

**Files:**
- Modify if needed: `docs/superpowers/plans/2026-08-16-public-desktop-release-channel.md`

- [x] **Step 1: Run focused static validation**

Run Node helper self-tests, JSON/YAML parse, and shell/PowerShell syntax checks. Do not run a full three-platform build or a GitHub workflow dispatch.

- [x] **Step 2: Inspect Git diff and guardrails**

Confirm dry-run defaults to no publication, source workflow has read-only permissions, public repository references are consistent, and all required assets are in the allowlist.

- [x] **Step 3: Commit and push the owned configuration changes**

Commit only release-channel files from this worktree. Synchronize safely with the source repository default branch through the approved Git workflow; do not force push, publish a tag, or create a release.

- [x] **Step 4: Report usable release entry points**

Return the private source repository and public release repository URLs, the desktop private-key backup directory, the exact dry-run dispatch inputs, and the fact that no production package was published.
