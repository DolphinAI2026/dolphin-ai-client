# Windows desktop package

This project can build the Windows desktop installer on a Windows machine.
PyInstaller cannot cross-compile the sidecar from macOS, so do not run this flow
on a Mac.

## Build in GitHub Actions

1. Open GitHub Actions.
2. Run the `Windows desktop package` workflow manually.
3. Optionally enter the version, for example `0.2.37`.
4. Download the uploaded artifact after the job finishes.

The workflow uploads both the raw Tauri bundle output and a download-ready file:

```text
dist-desktop/windows/ruijing-<version>-windows-x86_64-setup.exe
```

If `TAURI_SIGNING_PRIVATE_KEY` is not configured in repository secrets, the
workflow still builds the installer but skips updater artifacts.

## Build locally on Windows

Prerequisites:

- Windows 10/11
- Node.js 20
- Python 3.11
- Rust stable with MSVC toolchain
- Microsoft Visual Studio Build Tools / C++ build tools
- WebView2 Runtime

Run:

```powershell
.\scripts\build-desktop-windows.ps1 -Version 0.2.37 -Bundle nsis
```

Useful options:

```powershell
.\scripts\build-desktop-windows.ps1 -Bundle msi
.\scripts\build-desktop-windows.ps1 -SkipInstall
```

Output:

```text
dist-desktop/windows/ruijing-<version>-windows-x86_64-setup.exe
src-tauri/target/x86_64-pc-windows-msvc/release/bundle/
```

## Publish to current download service

The account-service download whitelist and version history now accept:

```text
ruijing-<version>-windows-x86_64-setup.exe
```

Upload that file through `/desktop-updates/admin/publish` together with the
manifest if you want it listed in the existing admin download page. The publish
endpoint replaces `latest.json`, so keep the existing macOS `platforms` entries
in the manifest when adding the Windows entry.

## Known Windows limitations

- The interactive workspace terminal endpoint still uses Unix PTY modules and
  needs a Windows-specific implementation or a UI downgrade.
- The app can build and start the sidecar on Windows, but process-tree cleanup
  should be verified on a real Windows machine before broad distribution.
