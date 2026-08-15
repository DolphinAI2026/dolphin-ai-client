# Windows DolphinAI 正式构建与放行检查

Windows 安装包和绿色包必须在原生 Windows 上构建。PyInstaller 不能从 Linux 或 macOS 交叉生成可用的
Windows sidecar。

## 构建命令

```powershell
# 本地绿色验证包（不进入正式发布目录）
.\scripts\build-desktop-windows.ps1 -Version 0.2.70 -Bundle portable

# Windows 正式 NSIS 安装包
.\scripts\build-desktop-windows.ps1 -Version 0.2.70 -Bundle nsis
```

`-UsePreparedRuntimeAppliance`、`-SkipFrontendBuild`、`-SkipSidecarBuild` 和 `-SkipTauriBuild` 只用于确认对应
产物已经由同一源码版本生成的增量构建。正式发布默认不使用这些参数。

脚本在前端构建前写入当前 Git revision 和 `windows-x86_64` 目标到
`DOLPHIN_BUILD_REVISION`、`DOLPHIN_BUILD_TARGET`。`src-tauri/tauri.conf.json` 默认开启 updater
artifact。非 Release 本地构建缺少 `TAURI_SIGNING_PRIVATE_KEY` 时，脚本只在本次进程中临时关闭 updater
artifact，并在输出中标记该降级；标签构建（`DOLPHIN_RELEASE_BUILD=1`、`GITHUB_REF_TYPE=tag` 或
`GITHUB_REF=refs/tags/...`）缺少密钥会立即失败，绝不生成未签名的正式 Release 包。

## GitHub 标签发布

发布 `0.2.70` 时执行：

```bash
git tag v0.2.70
git push github v0.2.70
```

正式包由 `.github/workflows/desktop-release.yml` 在 `vX.Y.Z` 标签或手动填写 `X.Y.Z` 后发布。它在构建前
校验 updater 签名私钥，并在 Windows x64、macOS arm64、Linux x64 上分别从固定 revision 准备
`agent-runtime`、`agentic-coding`、Superpowers、Builder 前端、Python 环境和固定版本 Codex，并在构建前
物化本地 Runtime appliance。手动发布会先创建或验证 `vX.Y.Z` 标签精确指向当前构建提交，再以该提交构建三端包。
标签创建完成后任一构建失败时，该标签会保留，便于修复后从同一版本标签重新触发或明确处置；它不会被工作流自动删除。
macOS 和 Linux appliance 使用已校验 SHA-256 的 `python-build-standalone` 解释器根目录，并在迁移 appliance
目录后运行包内 Python 与 `agentic-pack-reconcile`，不复制构建 runner 的 `.venv`。
三端只上传正式主包及
Tauri updater 有效载荷；Release job 汇总为 `dist-desktop/publish/`，生成 `latest.json` 和
`SHA256SUMS.txt` 后发布。

正式工作流只接受纯 `X.Y.Z` / `vX.Y.Z`，会在创建 Release 前拒绝 `rc`、`beta` 和 build metadata；portable
调试包仍可使用完整 SemVer 标记测试版本。

GitHub Actions 需要以下 Secrets：`TAURI_SIGNING_PRIVATE_KEY`、可选的
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`、`DEFINESYS_GIT_USERNAME`、`DEFINESYS_GIT_TOKEN` 和默认
`GITHUB_TOKEN`。`DEFINESYS_GIT_TOKEN` 必须仅授予 `agent-runtime` 和 `agentic-coding` 的只读拉取权限；
工作流仅将其写入一次性 Git 配置，并在内部仓库 clone 完成后立即删除。缺少签名私钥时标签发布会在任一平台构建开始前失败。

客户端 updater 固定读取
`https://github.com/Mars-hub404/apaas-builder-ai/releases/latest/download/latest.json`。工作流在 Release
创建后再通过 GitHub API 回读实际附件的 `browser_download_url`，输出 Windows 安装包、macOS DMG、Linux
AppImage、Linux DEB、manifest 和 checksum 下载地址。旧 `desktop-windows.yml` 仅生成不签名的 portable
调试包，不能用于正式发布。

## 自动构建门禁

以下检查由构建脚本按顺序执行。任一步失败都不会生成或复制“可下载包”。

1. **源码版本**：读取当前 Git revision，写入前端构建元数据和包内 `build-manifest.json`。
2. **Runtime appliance**：重新生成 Windows `agent-runtime.exe`、Codex、Python、能力包和 Builder 静态资源。
3. **前端**：生成桌面模式前端资源，不复用缺失或不完整的 `dist-desktop`。
4. **sidecar**：使用 PyInstaller `--clean` 生成 Windows sidecar，避免缓存旧 Python 代码。
5. **Tauri 主程序**：清理旧 Runtime resources 后生成当前 Tauri 主程序和资源目录。
6. **包结构**：校验主程序、sidecar、Runtime、Codex、Python、能力包和 Builder 首页都存在且非空，并且不包含任何 `.git` 仓库元数据。
7. **二进制身份**：记录并复核主程序、sidecar、Runtime、Codex、Python 和 reconcile 启动器的 SHA-256。
8. **运行依赖**：实际启动包内 Codex 和 Python，确认核心模块可导入。
9. **能力包刷新**：实际执行以下五组 `agentic-pack-reconcile`：
   - 宿主环境强制关闭 Python UTF-8 模式，验证启动器不依赖 Windows 当前代码页；
   - 全新 Codex home；
   - 同一 home 重复执行，验证幂等；
   - 已有 `config.toml` 的 home；
   - 与客户端一致的 `HOME`、`USERPROFILE`、`APPDATA`、`LOCALAPPDATA`、`TEMP`；
   - Windows `\\?\` 扩展路径。
10. **真实解压目录**：绿色 ZIP 生成后重新解压到新的临时目录，再完整执行第 6 至 9 项。
11. **版本核对**：解压后的 `build-manifest.json` 必须与本次 version、Git revision 和文件哈希一致。
12. **产物摘要**：输出最终文件路径、大小、修改时间和 ZIP SHA-256。
13. **正式品牌**：正式 NSIS 输出必须为 `dolphin-ai-<version>-windows-x86_64-setup.exe`，并拒绝
    `ruijing-`、`Dolphin Code` 和 `ruijing-sidecar` 的旧产物名。

专项门禁也可以单独执行：

```powershell
.\scripts\verify-desktop-windows-package.ps1 `
  -PackageRoot "C:\path\to\DolphinAI" `
  -ExpectedVersion "0.2.70" `
  -ExpectedSourceRevision "<git-revision>"
```

正式产物的品牌门禁可以单独执行：

```powershell
node .\scripts\verify-desktop-release-brand.mjs `
  --root .\dist-desktop\windows `
  --version 0.2.70 `
  --platform windows
```

## 0.2.70 Windows 候选包

2026-08-16 已在原生 Windows 上从源码提交 `b768a2df4705459aad654d737c487bbec9a43ff3` 生成 NSIS 候选包：

```text
D:\downloads\dolphin-ai-build-0.2.70\dist-desktop\windows\dolphin-ai-0.2.70-windows-x86_64-setup.exe
SHA-256: 03A53D2BE7516A94510BE9B1BCAA16E8A346DB1F40D2E2934CF18162B2F9739B
大小: 202840890 bytes
```

候选包的 `ProductName` 为 `DolphinAI`，文件版本为 `0.2.70`；包内主程序、`dolphin-ai-sidecar.exe`、
Runtime、Codex、Python、能力包和 Builder 入口均通过自动门禁。该本地候选包没有 Tauri updater 私钥和
Windows 代码签名，只用于发布前验证；GitHub 标签构建必须生成签名 updater 产物。为避免覆盖当前客户端，
本次未静默安装候选包，真实账号、本地应用和 Code 流式会话仍按下节执行。

## 客户端放行检查

下面三项依赖真实桌面配置、远程账号和 Coding 模型，不在无账号的通用构建脚本中伪造。交付给用户前必须用
本次解压目录执行，不能沿用仍在运行的旧客户端进程。

1. 关闭所有旧的 `DolphinAI.exe`、`dolphin-ai-sidecar.exe` 和 `agent-runtime.exe`，再从本次解压目录启动。
2. 打开一个本地应用，确认本地 Runtime 状态到达 `ready`，且过程中没有命令行黑框。
3. 新建一个 Code 会话并发送最小消息，确认 agent session 创建成功并收到首个流式事件。

若第 2 项失败，必须保留错误中指定实例的 `runtime.stderr.log`。Windows Runtime 会对能力包刷新退出码 `1`
做一次短延迟重试；第二次仍失败时，两次 stderr 都会进入该日志，不再只留下无原因的 exit code。

## 产物

```text
dist-desktop/windows/dolphin-ai-<version>-windows-x86_64-setup.exe
dist-desktop/windows/dolphin-ai-<version>-windows-x86_64-updater.nsis.zip
dist-desktop/windows/dolphin-ai-<version>-windows-x86_64-updater.nsis.zip.sig
dist-desktop/release/dolphin-ai-<version>-macos-aarch64.dmg
dist-desktop/release/dolphin-ai-<version>-linux-x86_64.AppImage
dist-desktop/release/dolphin-ai-<version>-linux-x86_64.deb
```

Windows、macOS 和 Linux 脚本会与主包一同复制 Tauri 生成的 updater 有效载荷和 `.sig`，且名称使用相同
`dolphin-ai-<version>-<platform>-<arch>` 前缀。`dist-desktop/release/` 不包含 portable ZIP。绿色包只适合
快速验证；NSIS 安装包提供标准卸载和后续更新能力。两种 Windows 包都必须通过相同的 Runtime 资源与能力包刷新门禁。
