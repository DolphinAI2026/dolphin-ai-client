# Desktop ACL Fix and Windows Portable Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复桌面自定义命令的 Tauri ACL 拒绝，并产出经过 Windows 真实启动烟测的免安装绿色 ZIP。

**Architecture:** 使用一个应用级聚合 permission 授权现有八个 `desktop_*` 命令，现有 capability 继续只覆盖本机 sidecar origin。Windows 构建脚本增加独立 `portable` 模式，复用现有构建步骤并从 Tauri release 目录组装、校验和压缩绿色目录。

**Tech Stack:** Tauri 2.11、Rust、PowerShell、PyInstaller、Vite、Windows x86_64 MSVC

---

## 文件结构

- 创建 `src-tauri/permissions/desktop.toml`：桌面自定义命令的唯一 ACL 清单。
- 修改 `src-tauri/capabilities/default.json`：把聚合 permission 授予主窗口和本机 sidecar origin。
- 修改 `scripts/build-desktop-windows.ps1`：增加 portable 构建、目录校验、ZIP 和 SHA-256 输出。
- 不新增测试文件；用生成的 ACL manifest、PowerShell 参数绑定和真实绿色版启动做最小验证。

### Task 1: 修复桌面命令 ACL

**Files:**
- Create: `src-tauri/permissions/desktop.toml`
- Modify: `src-tauri/capabilities/default.json`
- Verify: `src-tauri/gen/schemas/acl-manifests.json`

- [ ] **Step 1: 运行失败检查，确认应用 ACL 尚未注册**

Run:

```bash
node - <<'NODE'
const fs = require('fs');
const acl = JSON.parse(fs.readFileSync('src-tauri/gen/schemas/acl-manifests.json', 'utf8'));
if (!acl.__app__) throw new Error('missing Tauri app ACL manifest');
NODE
```

Expected: FAIL with `missing Tauri app ACL manifest`.

- [ ] **Step 2: 创建聚合 permission**

Create `src-tauri/permissions/desktop.toml`:

```toml
[[permission]]
identifier = "desktop-commands"
description = "Allows the desktop shell to manage setup, login, workspace scope, paths, and runtime recovery."
commands.allow = [
  "desktop_get_state",
  "desktop_save_setup",
  "desktop_test_service",
  "desktop_enter_login_setup",
  "desktop_retry_start",
  "desktop_update_login",
  "desktop_update_workspace_entry_scope",
  "desktop_open_path",
]
```

- [ ] **Step 3: 把聚合 permission 加入默认 capability**

Add `"desktop-commands"` to the `permissions` array in
`src-tauri/capabilities/default.json`, preserving the existing loopback-only `remote.urls`.

- [ ] **Step 4: 生成并核验 ACL manifest**

Run:

```bash
cargo check --manifest-path src-tauri/Cargo.toml
node - <<'NODE'
const fs = require('fs');
const expected = [
  'desktop_get_state',
  'desktop_save_setup',
  'desktop_test_service',
  'desktop_enter_login_setup',
  'desktop_retry_start',
  'desktop_update_login',
  'desktop_update_workspace_entry_scope',
  'desktop_open_path',
].sort();
const acl = JSON.parse(fs.readFileSync('src-tauri/gen/schemas/acl-manifests.json', 'utf8'));
const actual = [...acl.__app__.permissions['desktop-commands'].commands.allow].sort();
if (JSON.stringify(actual) !== JSON.stringify(expected)) {
  throw new Error(`desktop ACL mismatch: ${JSON.stringify(actual)}`);
}
NODE
```

Expected: `cargo check` succeeds and the Node command exits `0`.

- [ ] **Step 5: 提交 ACL 修复**

```bash
git add src-tauri/permissions/desktop.toml src-tauri/capabilities/default.json src-tauri/gen/schemas
git commit -m "fix(desktop): allow custom commands through Tauri ACL"
```

### Task 2: 增加并实跑 Windows 绿色版

**Files:**
- Modify: `scripts/build-desktop-windows.ps1`
- Output: `dist-desktop/windows/ruijing-<version>-windows-x86_64-portable.zip`

- [ ] **Step 1: 运行失败检查，确认脚本尚不接受 portable**

Run from WSL with the script path converted by `wslpath -w`:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass \
  -File "$(wslpath -w scripts/build-desktop-windows.ps1)" \
  -Bundle portable -SkipInstall
```

Expected: parameter validation fails because `portable` is not in the current `ValidateSet`.

- [ ] **Step 2: 增加 portable 构建选择**

Change the parameter declaration to:

```powershell
[ValidateSet("portable", "nsis", "msi", "all")]
[string]$Bundle = "portable",
```

In build step 6, execute Tauri without an installer bundler for portable mode:

```powershell
if ($Bundle -eq "portable") {
  npx tauri build --target $Target --no-bundle
} else {
  npx tauri build --target $Target --bundles $Bundle
}
Assert-NativeSuccess "Tauri Windows build" $LASTEXITCODE
```

- [ ] **Step 3: 组装并校验绿色目录**

After the existing Runtime appliance checks, for portable mode:

```powershell
$DownloadDir = Join-Path $Root "dist-desktop\windows"
$PortableName = "ruijing-$PackageVersion-windows-x86_64-portable"
$PortableRoot = Join-Path $DownloadDir $PortableName
$PortableZip = "$PortableRoot.zip"

Remove-Item $PortableRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $PortableZip -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $PortableRoot | Out-Null

Copy-Item (Join-Path $ReleaseRoot "app.exe") (Join-Path $PortableRoot "Dolphin Code.exe") -Force
Copy-Item (Join-Path $ReleaseRoot "ruijing-sidecar.exe") $PortableRoot -Force
Copy-Item (Join-Path $ReleaseRoot "resources") $PortableRoot -Recurse -Force

foreach ($RelativePath in @(
  "Dolphin Code.exe",
  "ruijing-sidecar.exe",
  "resources\agent-runtime\bin\agent-runtime.exe",
  "resources\agent-runtime\codex\bin\codex.exe",
  "resources\agent-runtime\agentic-coding\.venv\Scripts\python.exe",
  "resources\agent-runtime\agentic-coding-pack\manifest.yaml",
  "resources\agent-runtime\web\builder\dist\index.html"
)) {
  if (-not (Test-Path (Join-Path $PortableRoot $RelativePath) -PathType Leaf)) {
    throw "Portable package is missing $RelativePath"
  }
}

Compress-Archive -Path $PortableRoot -DestinationPath $PortableZip -CompressionLevel Optimal
Get-FileHash $PortableZip -Algorithm SHA256 | Format-List
```

Keep the installer artifact copy logic only for non-portable modes.

- [ ] **Step 4: 运行脚本级语法检查并提交**

Run:

```bash
powershell.exe -NoProfile -Command \
  "[void][scriptblock]::Create((Get-Content -Raw '$(wslpath -w scripts/build-desktop-windows.ps1)'))"
git diff --check
```

Expected: both commands exit `0`.

Commit:

```bash
git add scripts/build-desktop-windows.ps1
git commit -m "build(desktop): add portable Windows package"
```

- [ ] **Step 5: 构建绿色版并核验 ZIP**

Run on Windows from a Windows-accessible checkout containing these commits:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass \
  -File scripts/build-desktop-windows.ps1 \
  -Version 0.2.40 -Bundle portable -SkipInstall
```

Expected: build succeeds and produces
`dist-desktop/windows/ruijing-0.2.40-windows-x86_64-portable.zip` with a printed SHA-256.

- [ ] **Step 6: 从新的解压目录真实启动**

Stop only the previously installed Dolphin Code processes, extract the ZIP to a new temporary Windows
directory, then launch `Dolphin Code.exe`. Verify:

```text
- Dolphin Code.exe remains running.
- ruijing-sidecar.exe starts from the extracted directory.
- The main window advances past the Tauri bootstrap screen.
- Current desktop logs do not contain "not allowed by ACL" or "desktop_get_state" ACL rejection.
```

If a later login or Runtime error appears, preserve its exact diagnostic and fix only when it is caused by
this package layout; do not add unrelated feature work.

- [ ] **Step 7: 记录最终交付信息**

Report the ZIP absolute Windows path, byte size, SHA-256, source commit, and the observed startup result.
