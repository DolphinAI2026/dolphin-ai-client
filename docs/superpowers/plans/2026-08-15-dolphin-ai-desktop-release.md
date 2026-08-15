# DolphinAI Desktop Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将桌面客户端完整重命名为 DolphinAI，并用 Git 标签自动生成三个系统的正式安装包、GitHub Release 和可回读下载地址。

**Architecture:** Tauri 配置是应用身份和版本的源码入口，桌面构建脚本只在构建期注入标签版本和构建提交。三个系统继续复用现有 Runtime appliance 与包内门禁，GitHub Actions 显式准备 `agent-runtime`、`agentic-coding` 和 Codex 依赖，最后由单一 Release Job 汇总签名产物、生成 updater manifest、创建 Release 并从 API 回读附件 URL。

**Tech Stack:** Tauri 2、Rust、Vue 3、TypeScript、Vite、Element Plus、PyInstaller、PowerShell、Bash、Node.js、GitHub Actions。

## Global Constraints

- 产品显示名固定为 `DolphinAI`。
- Tauri identifier 固定为 `com.definesys.dolphin-ai`。
- sidecar 名称固定为 `dolphin-ai-sidecar`。
- 默认本地根目录名固定为 `DolphinAI`。
- 发布文件前缀固定为 `dolphin-ai`。
- 不迁移或删除 `com.ruijing.builder`、`DolphinCode` 的历史用户数据。
- 不修改 `.ruijing/PROJECT.md`、`ruijing-preview` 等已有工程和消息协议字段。
- Git 标签 `vX.Y.Z` 是正式发布版本的唯一来源。
- 正式 GitHub Release 不上传绿色 ZIP。
- 正式标签缺少 Tauri updater 签名密钥时必须失败。
- 不新增零散测试文件；前端断言扩展 `desktopGuard.spec.ts`，Rust 和脚本使用现有测试及专项命令。
- 不提交未跟踪的 `.agentic/`。

---

### Task 1: 统一 Tauri 身份、sidecar 和默认目录

**Files:**
- Modify: `src-tauri/tauri.conf.json`
- Modify: `src-tauri/capabilities/default.json`
- Modify: `src-tauri/src/desktop_backend.rs`
- Modify: `src-tauri/src/desktop_config.rs`
- Rename: `backend/ruijing-sidecar.spec` -> `backend/dolphin-ai-sidecar.spec`
- Modify: `backend/desktop_sidecar.py`
- Modify: `scripts/build-desktop-windows.ps1`
- Modify: `scripts/build-desktop.sh`
- Modify: `scripts/build-desktop-x86.sh`
- Modify: `scripts/verify-desktop-windows-package.ps1`
- Modify: `docs/windows-desktop-build.md`

**Interfaces:**
- Consumes: Tauri `productName`、`identifier`、`externalBin`，`DesktopPaths`，PyInstaller spec。
- Produces: `DolphinAI` 安装身份、`dolphin-ai-sidecar` 进程及默认 `${HOME}/DolphinAI` 根目录。

- [ ] **Step 1: 扩展现有 Rust 和脚本断言，使旧身份先失败**

在 `desktop_config.rs` 现有 `default_root_dir` 测试和路径 fixture 中，把新默认值断言为：

```rust
assert_eq!(default_root_dir(Path::new("/home/tester")), PathBuf::from("/home/tester/DolphinAI"));
```

在现有 Windows 包门禁中将默认可执行文件和清单字段改为：

```powershell
[string]$ApplicationExecutable = "DolphinAI.exe"
$RequiredFiles = @("dolphin-ai-sidecar.exe", ...)
product = "DolphinAI"
sidecar = "dolphin-ai-sidecar.exe"
```

- [ ] **Step 2: 运行最小失败检查**

Run:

```bash
rg -n 'productName.*DolphinAI|com\.definesys\.dolphin-ai|dolphin-ai-sidecar' \
  src-tauri/tauri.conf.json src-tauri/capabilities/default.json src-tauri/src backend scripts
cargo test --manifest-path src-tauri/Cargo.toml desktop_config::tests -- --nocapture
```

Expected: 品牌扫描缺少新值或 Rust 默认目录测试失败。

- [ ] **Step 3: 修改 Tauri 和 Rust 身份**

`tauri.conf.json` 使用：

```json
{
  "productName": "DolphinAI",
  "identifier": "com.definesys.dolphin-ai",
  "bundle": {
    "externalBin": ["binaries/dolphin-ai-sidecar"]
  }
}
```

`default.json` 注册 `binaries/dolphin-ai-sidecar`，`desktop_backend.rs` 使用：

```rust
app.shell().sidecar("dolphin-ai-sidecar")
```

窗口标题改为 `DolphinAI`，`default_root_dir()` 返回 `home_dir.join("DolphinAI")`。

- [ ] **Step 4: 重命名 PyInstaller 和三平台构建引用**

执行：

```bash
git mv backend/ruijing-sidecar.spec backend/dolphin-ai-sidecar.spec
```

spec 中 `name="dolphin-ai-sidecar"`。Windows、Linux、macOS 构建脚本统一读取
`backend/dist/dolphin-ai-sidecar[.exe]` 并写入
`src-tauri/binaries/dolphin-ai-sidecar-<target>[.exe]`。绿色包调试目录使用
`DolphinAI/DolphinAI.exe`，文件名改为 `dolphin-ai-<version>-windows-x86_64-portable.zip`。

- [ ] **Step 5: 运行身份专项检查**

Run:

```bash
cargo test --manifest-path src-tauri/Cargo.toml desktop_config::tests -- --nocapture
bash -n scripts/build-desktop.sh scripts/build-desktop-x86.sh
rg -n 'ruijing-sidecar|com\.ruijing\.builder|DolphinCode|睿鲸 Builder' \
  src-tauri/tauri.conf.json src-tauri/capabilities/default.json \
  src-tauri/src/desktop_backend.rs src-tauri/src/desktop_config.rs \
  backend/dolphin-ai-sidecar.spec scripts/build-desktop*.sh \
  scripts/build-desktop-windows.ps1 scripts/verify-desktop-windows-package.ps1
```

Expected: Rust 与 Shell 检查通过；最后的 `rg` 无输出。历史协议和非发布代码不在该扫描范围。

- [ ] **Step 6: 提交身份改动**

```bash
git add src-tauri backend/dolphin-ai-sidecar.spec backend/desktop_sidecar.py \
  scripts/build-desktop-windows.ps1 scripts/build-desktop.sh scripts/build-desktop-x86.sh \
  scripts/verify-desktop-windows-package.ps1 docs/windows-desktop-build.md
git commit -m "feat(desktop): rename application to DolphinAI"
```

---

### Task 2: 增加关于弹窗和真实构建元数据

**Files:**
- Create: `frontend/src/components/desktop/DesktopAboutDialog.vue`
- Modify: `frontend/src/views/DesktopSettings.vue`
- Modify: `frontend/src/router/desktopGuard.spec.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/vite-env.d.ts`
- Modify: `frontend/src/views/Login.vue`
- Modify: `frontend/src/views/DesktopSetupWizard.vue`
- Modify: `frontend/src/components/v2/RailSidebar.vue`
- Modify: `frontend/src/assets/brand/ruijing-whale-mark.svg`

**Interfaces:**
- Consumes: `__APP_VERSION__`、新增 `__BUILD_REVISION__`、`__BUILD_TARGET__`、`checkAndPromptUpdate()`。
- Produces: `DesktopAboutDialog` 组件和用户可见的 DolphinAI 品牌。

- [ ] **Step 1: 在现有前端专项测试增加失败断言**

在 `desktopGuard.spec.ts` 读取 `DesktopAboutDialog.vue?raw`，断言：

```ts
expect(aboutDialogSource).toContain('DolphinAI')
expect(aboutDialogSource).toContain('__APP_VERSION__')
expect(aboutDialogSource).toContain('__BUILD_REVISION__')
expect(aboutDialogSource).toContain('__BUILD_TARGET__')
expect(aboutDialogSource).toContain('checkAndPromptUpdate({ silentIfNone: false })')
expect(desktopSettingsSource).toContain('<DesktopAboutDialog')
```

同时断言核心桌面入口不再显示 `Dolphin Code` 或 `睿鲸`。

- [ ] **Step 2: 运行前端专项测试确认失败**

Run:

```bash
cd frontend && npm test -- --run src/router/desktopGuard.spec.ts
```

Expected: `DesktopAboutDialog.vue` 不存在或缺少新构建常量。

- [ ] **Step 3: 注入构建元数据**

`vite.config.ts` 增加：

```ts
const __BUILD_REVISION__ = process.env.DOLPHIN_BUILD_REVISION || 'dev'
const __BUILD_TARGET__ = process.env.DOLPHIN_BUILD_TARGET || `${process.platform}-${process.arch}`
```

并通过 `define` 注入；`vite-env.d.ts` 声明两个 `string` 常量。Windows 和 Shell 构建脚本在
前端构建前设置 `DOLPHIN_BUILD_REVISION` 与 `DOLPHIN_BUILD_TARGET`。

- [ ] **Step 4: 实现独立关于弹窗**

`DesktopAboutDialog.vue` 使用 `el-dialog`，props/emits 为：

```ts
const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: boolean): void }>()
```

弹窗显示 `DolphinAI`、`v${__APP_VERSION__}`、短提交、目标系统；桌面端显示“检查更新”按钮，
Web 预览显示“仅桌面客户端可用”。调用更新时在组件内维护 `checking` 和 `errorText`，不新增系统级
错误弹窗。

- [ ] **Step 5: 在设置中接入弹窗并更新核心品牌文案**

“关于与更新”区域改为简洁入口按钮，点击设置 `aboutDialogOpen = true`。登录页、初始化页和 Rail
标题统一为 `DolphinAI`，鲸鱼图标 SVG 的可访问标题同步改名；不修改 Code 产品页中表示功能模式的
普通 `Code` 文案。

- [ ] **Step 6: 运行前端专项测试和桌面构建**

Run:

```bash
cd frontend
npm test -- --run src/router/desktopGuard.spec.ts
npm run build:desktop
```

Expected: 两条命令通过，`dist-desktop` 中包含新弹窗和 DolphinAI 品牌。

- [ ] **Step 7: 提交前端改动**

```bash
git add frontend/src/components/desktop/DesktopAboutDialog.vue \
  frontend/src/views/DesktopSettings.vue frontend/src/router/desktopGuard.spec.ts \
  frontend/vite.config.ts frontend/src/vite-env.d.ts frontend/src/views/Login.vue \
  frontend/src/views/DesktopSetupWizard.vue frontend/src/components/v2/RailSidebar.vue \
  frontend/src/assets/brand/ruijing-whale-mark.svg
git commit -m "feat(desktop): add DolphinAI about dialog"
```

---

### Task 3: 收敛三平台正式构建产物

**Files:**
- Modify: `scripts/build-desktop-windows.ps1`
- Modify: `scripts/build-desktop.sh`
- Modify: `scripts/build-desktop-x86.sh`
- Create: `scripts/verify-desktop-release-brand.mjs`
- Modify: `src-tauri/tauri.conf.json`
- Modify: `docs/windows-desktop-build.md`

**Interfaces:**
- Consumes: Task 1 的应用身份、Task 2 的构建环境变量、现有 Runtime appliance。
- Produces: 规范命名的 NSIS、DMG、AppImage、Deb 和 updater 签名产物。

- [ ] **Step 1: 创建跨平台品牌门禁并验证它先失败**

`verify-desktop-release-brand.mjs` 接收 `--root`、`--version`、`--platform`，递归检查正式产物：

```js
const forbidden = ['ruijing-', 'Dolphin Code', 'ruijing-sidecar']
const requiredPrefix = `dolphin-ai-${version}-`
```

它要求平台对应文件存在，并在发现旧品牌时退出 `1`。对当前旧命名目录运行应失败。

- [ ] **Step 2: 将正式构建默认命名统一为 dolphin-ai**

Windows NSIS 输出：

```text
dist-desktop/windows/dolphin-ai-X.Y.Z-windows-x86_64-setup.exe
```

macOS 和 Linux 构建完成后复制到 `dist-desktop/release/`：

```text
dolphin-ai-X.Y.Z-macos-aarch64.dmg
dolphin-ai-X.Y.Z-linux-x86_64.AppImage
dolphin-ai-X.Y.Z-linux-x86_64.deb
```

每个平台同时复制 Tauri 生成的 updater 文件及 `.sig`，不把 portable ZIP 放入
`dist-desktop/release/`。

- [ ] **Step 3: 开启 updater artifact 并保持无密钥本地构建可诊断**

`tauri.conf.json` 设置 `createUpdaterArtifacts: true`。构建脚本检测不到
`TAURI_SIGNING_PRIVATE_KEY` 时只对本地非 Release 构建临时关闭 updater artifacts，并在输出中明确
标记；GitHub 标签工作流在调用构建脚本前单独检查密钥，不能依赖这一降级。

- [ ] **Step 4: 运行脚本和前端元数据专项检查**

Run:

```bash
node --check scripts/verify-desktop-release-brand.mjs
bash -n scripts/build-desktop.sh scripts/build-desktop-x86.sh
node scripts/verify-desktop-release-brand.mjs --help
```

Expected: 语法检查和帮助入口通过。

- [ ] **Step 5: 在当前 Windows 主机生成一个正式 NSIS 候选包**

Run from Windows checkout:

```powershell
.\scripts\build-desktop-windows.ps1 -Version 0.2.70 -Bundle nsis
```

Expected: `dolphin-ai-0.2.70-windows-x86_64-setup.exe` 存在，现有 Runtime 包门禁通过，品牌门禁
无旧主程序或 sidecar 名称。

- [ ] **Step 6: 提交构建改动**

```bash
git add scripts/build-desktop-windows.ps1 scripts/build-desktop.sh scripts/build-desktop-x86.sh \
  scripts/verify-desktop-release-brand.mjs src-tauri/tauri.conf.json docs/windows-desktop-build.md
git commit -m "build(desktop): produce formal DolphinAI packages"
```

---

### Task 4: 实现 GitHub 标签发布和下载地址回读

**Files:**
- Create: `.github/workflows/desktop-release.yml`
- Replace: `.github/workflows/desktop-windows.yml`
- Create: `scripts/prepare-desktop-release.mjs`
- Create: `scripts/report-desktop-release.mjs`
- Modify: `src-tauri/tauri.conf.json`
- Modify: `docs/windows-desktop-build.md`

**Interfaces:**
- Consumes: `vX.Y.Z` 标签、三个系统构建 artifact、Tauri `.sig`、GitHub API。
- Produces: `latest.json`、`SHA256SUMS.txt`、GitHub Release 和下载 URL outputs。

- [ ] **Step 1: 为 Release helper 写内置自检入口**

两个 Node 脚本都支持 `--self-test`，使用临时目录验证：

```text
v0.2.70 -> 0.2.70
缺少任一平台附件 -> exit 1
latest.json 平台 URL 指向 release download URL
Release API 缺少附件 -> exit 1
完整 API fixture -> 输出七个 URL 字段
```

Run:

```bash
node scripts/prepare-desktop-release.mjs --self-test
node scripts/report-desktop-release.mjs --self-test
```

Expected before implementation: 文件不存在。

- [ ] **Step 2: 实现发布清单生成器**

`prepare-desktop-release.mjs` 参数：

```text
--version X.Y.Z
--repository Mars-hub404/apaas-builder-ai
--tag vX.Y.Z
--input dist-desktop/release
--output dist-desktop/publish
```

脚本校验四个正式包及 updater 签名，生成 `latest.json`、`SHA256SUMS.txt`，并复制 Release
附件到单一发布目录。`latest.json` 使用：

```text
https://github.com/Mars-hub404/apaas-builder-ai/releases/download/vX.Y.Z/<asset>
```

- [ ] **Step 3: 实现下载地址回读器**

`report-desktop-release.mjs` 从环境读取 `GITHUB_REPOSITORY`、`GITHUB_REF_NAME`、
`GITHUB_TOKEN`，调用：

```text
GET /repos/{owner}/{repo}/releases/tags/{tag}
```

按附件真实 `browser_download_url` 写入 `$GITHUB_OUTPUT` 和 `$GITHUB_STEP_SUMMARY`，字段固定为：

```text
release_url
windows_setup_url
macos_dmg_url
linux_appimage_url
linux_deb_url
latest_json_url
checksums_url
```

- [ ] **Step 4: 建立统一 GitHub Release 工作流**

`desktop-release.yml`：

```yaml
on:
  push:
    tags: ['v*']
  workflow_dispatch:
    inputs:
      version:
        required: true
permissions:
  contents: write
```

工作流先校验 SemVer 和签名 secrets，再并行构建 Windows x64、macOS arm64、Linux x64。
每个平台显式：

1. 检出当前 GitHub 仓库；
2. 使用 `DEFINESYS_GIT_USERNAME`、`DEFINESYS_GIT_TOKEN` 从内部 Git 服务检出固定 revision 的
   `agent-runtime` 和 `agentic-coding` 到相邻目录；
3. 构建 `agent-runtime/web/builder`；
4. 创建 `agentic-coding/.venv` 并安装 `requirements.txt`；
5. 安装固定版本 `@openai/codex`，向 appliance 脚本传递 `CODEX_NATIVE_ROOT`；
6. 调用当前平台构建脚本；
7. 上传仅属于该平台的正式 artifact。

Release Job 下载三个 artifact，运行 `prepare-desktop-release.mjs`，使用
`softprops/action-gh-release` 上传 `dist-desktop/publish/*`，随后运行
`report-desktop-release.mjs` 回读 URL。

- [ ] **Step 5: 更新 updater endpoint 和旧 Windows workflow**

`tauri.conf.json` updater endpoint 改为：

```text
https://github.com/Mars-hub404/apaas-builder-ai/releases/latest/download/latest.json
```

旧 `desktop-windows.yml` 改成调用统一可复用构建逻辑或只保留 portable 调试入口，不能再产生带
`ruijing` 名称的正式安装包。

- [ ] **Step 6: 运行工作流静态专项检查**

Run:

```bash
node scripts/prepare-desktop-release.mjs --self-test
node scripts/report-desktop-release.mjs --self-test
node -e "import('yaml').then(() => process.exit(0)).catch(() => process.exit(0))"
rg -n 'contents: write|tags:|softprops/action-gh-release|report-desktop-release' \
  .github/workflows/desktop-release.yml
rg -n 'ruijing-|Dolphin Code|com\.ruijing\.builder' \
  .github/workflows/desktop-release.yml .github/workflows/desktop-windows.yml \
  scripts/prepare-desktop-release.mjs scripts/report-desktop-release.mjs
```

Expected: 两个 self-test 通过；工作流关键阶段存在；最后品牌扫描无输出。

- [ ] **Step 7: 提交发布流程**

```bash
git add .github/workflows/desktop-release.yml .github/workflows/desktop-windows.yml \
  scripts/prepare-desktop-release.mjs scripts/report-desktop-release.mjs \
  src-tauri/tauri.conf.json docs/windows-desktop-build.md
git commit -m "ci(desktop): publish DolphinAI GitHub releases"
```

---

### Task 5: 聚焦回归和交付说明

**Files:**
- Modify: `docs/windows-desktop-build.md`
- Verify: `dist-desktop/windows/`
- Verify: `.github/workflows/desktop-release.yml`

**Interfaces:**
- Consumes: Tasks 1-4 的实现与当前 Windows 构建环境。
- Produces: 可安装的 Windows 正式候选包、CI 配置清单和未配置 Secrets 列表。

- [ ] **Step 1: 运行源码专项检查**

Run:

```bash
cd frontend && npm test -- --run src/router/desktopGuard.spec.ts && npm run build:desktop
cd ..
cargo test --manifest-path src-tauri/Cargo.toml desktop_config::tests -- --nocapture
bash -n scripts/build-desktop.sh scripts/build-desktop-x86.sh
node scripts/prepare-desktop-release.mjs --self-test
node scripts/report-desktop-release.mjs --self-test
git diff --check
```

Expected: 全部通过。

- [ ] **Step 2: 运行 Windows 正式候选包门禁**

Run from Windows checkout:

```powershell
.\scripts\build-desktop-windows.ps1 -Version 0.2.70 -Bundle nsis
```

Expected: NSIS 构建完成；Runtime、Codex、Python、能力包、长路径、品牌和版本门禁全部通过。

- [ ] **Step 3: 核对安装包身份**

安装候选包后确认：

```text
应用名: DolphinAI
identifier: com.definesys.dolphin-ai
主程序: DolphinAI.exe
sidecar: dolphin-ai-sidecar.exe
默认根目录: %USERPROFILE%\DolphinAI
```

旧版目录仍存在但未被读取或删除。

- [ ] **Step 4: 更新发布使用说明**

文档明确：

```text
git tag v0.2.70
git push github v0.2.70
```

并列出 GitHub Secrets：

```text
DEFINESYS_GIT_USERNAME
DEFINESYS_GIT_TOKEN
TAURI_SIGNING_PRIVATE_KEY
TAURI_SIGNING_PRIVATE_KEY_PASSWORD
```

Windows/macOS 系统签名 Secrets 按平台证书接入；工作流 Summary 是正式下载地址入口。

- [ ] **Step 5: 提交验证文档**

```bash
git add docs/windows-desktop-build.md
git commit -m "docs(desktop): document DolphinAI releases"
```

- [ ] **Step 6: 最终状态检查**

Run:

```bash
git status --short
git log --oneline -6
```

Expected: 仅保留既有未跟踪 `.agentic/`，本轮所有拥有的文件已提交；不创建标签、不推送 Release，
直到用户决定实际发布版本。
