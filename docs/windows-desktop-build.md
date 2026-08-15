# Windows 桌面客户端构建与放行检查

Windows 安装包和绿色包必须在原生 Windows 上构建。PyInstaller 不能从 Linux 或 macOS 交叉生成可用的
Windows sidecar。

## 构建命令

```powershell
# 绿色包
.\scripts\build-desktop-windows.ps1 -Version 0.2.66 -Bundle portable

# 安装包
.\scripts\build-desktop-windows.ps1 -Version 0.2.66 -Bundle nsis
```

`-UsePreparedRuntimeAppliance`、`-SkipFrontendBuild`、`-SkipSidecarBuild` 和 `-SkipTauriBuild` 只用于确认对应
产物已经由同一源码版本生成的增量构建。正式发布默认不使用这些参数。

## 自动构建门禁

以下检查由构建脚本按顺序执行。任一步失败都不会生成或复制“可下载包”。

1. **源码版本**：读取当前 Git revision，写入包内 `build-manifest.json`。
2. **Runtime appliance**：重新生成 Windows `agent-runtime.exe`、Codex、Python、能力包和 Builder 静态资源。
3. **前端**：生成桌面模式前端资源，不复用缺失或不完整的 `dist-desktop`。
4. **sidecar**：使用 PyInstaller `--clean` 生成 Windows sidecar，避免缓存旧 Python 代码。
5. **Tauri 主程序**：清理旧 Runtime resources 后生成当前 Tauri 主程序和资源目录。
6. **包结构**：校验主程序、sidecar、Runtime、Codex、Python、能力包和 Builder 首页都存在且非空。
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

专项门禁也可以单独执行：

```powershell
.\scripts\verify-desktop-windows-package.ps1 `
  -PackageRoot "C:\path\to\Dolphin Code" `
  -ExpectedVersion "0.2.66" `
  -ExpectedSourceRevision "<git-revision>"
```

## 客户端放行检查

下面三项依赖真实桌面配置、远程账号和 Coding 模型，不在无账号的通用构建脚本中伪造。交付给用户前必须用
本次解压目录执行，不能沿用仍在运行的旧客户端进程。

1. 关闭所有旧的 `Dolphin Code.exe`、`ruijing-sidecar.exe` 和 `agent-runtime.exe`，再从本次解压目录启动。
2. 打开一个本地应用，确认本地 Runtime 状态到达 `ready`，且过程中没有命令行黑框。
3. 新建一个 Code 会话并发送最小消息，确认 agent session 创建成功并收到首个流式事件。

若第 2 项失败，必须保留错误中指定实例的 `runtime.stderr.log`。Windows Runtime 会对能力包刷新退出码 `1`
做一次短延迟重试；第二次仍失败时，两次 stderr 都会进入该日志，不再只留下无原因的 exit code。

## 产物

```text
dist-desktop/windows/ruijing-<version>-windows-x86_64-portable.zip
dist-desktop/windows/ruijing-<version>-windows-x86_64-setup.exe
dist-desktop/windows/ruijing-<version>-windows-x86_64.msi
```

绿色包适合快速验证和并行保留多个版本；安装包提供标准卸载和后续更新能力。两种包都必须通过相同的 Runtime
资源与能力包刷新门禁。
