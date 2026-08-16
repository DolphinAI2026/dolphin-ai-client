param(
  [string]$Version = "",
  [string]$SourceRevision = "",
  [string]$Target = "x86_64-pc-windows-msvc",
  [ValidateSet("portable", "nsis", "msi", "all")]
  [string]$Bundle = "nsis",
  [switch]$SkipInstall,
  [switch]$UsePreparedRuntimeAppliance,
  [switch]$SkipFrontendBuild,
  [switch]$SkipSidecarBuild,
  [switch]$SkipTauriBuild
)
$ErrorActionPreference = "Stop"
$IsWin = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
  [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $IsWin) {
  throw "Windows desktop packages must be built on Windows because PyInstaller cannot cross-compile the sidecar exe."
}
if ($env:CARGO_TARGET_DIR) {
  $env:CARGO_TARGET_DIR = $env:CARGO_TARGET_DIR.Trim()
}

$StartTs = Get-Date
$Root = (Get-Item (Join-Path $PSScriptRoot "..")).FullName
$Frontend = Join-Path $Root "frontend"
$Backend = Join-Path $Root "backend"
$Tauri = Join-Path $Root "src-tauri"
$CargoTargetRoot = if ($env:CARGO_TARGET_DIR) {
  $env:CARGO_TARGET_DIR
} else {
  Join-Path $Tauri "target"
}
$Config = Join-Path $Tauri "tauri.conf.json"
$OriginalConfig = Get-Content $Config -Raw
$RestoreConfig = $false
$PackageVersion = $Version
if (-not $PackageVersion -and $OriginalConfig -match '"version"\s*:\s*"([^"]+)"') {
  $PackageVersion = $Matches[1]
}

function Invoke-Step($Name, [scriptblock]$Body) {
  Write-Host ""
  Write-Host "==> $Name"
  & $Body
}

function Assert-NativeSuccess($Name, $ExitCode) {
  if ($ExitCode -ne 0) {
    throw "$Name failed with exit code $ExitCode."
  }
}

function Copy-Tree($Source, $Destination) {
  $SourcePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Source)
  $DestinationPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Destination)
  New-Item -ItemType Directory -Force -Path $DestinationPath | Out-Null
  & robocopy $SourcePath $DestinationPath /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ /XF *.pyc *.pyo | Out-Null
  if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed from $SourcePath to $DestinationPath with exit code $LASTEXITCODE."
  }
}

function Remove-Tree($Path) {
  $DirectoryPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
  $ExtendedPath = if ($DirectoryPath.StartsWith("\\")) {
    "\\?\UNC\" + $DirectoryPath.TrimStart("\")
  } else {
    "\\?\" + $DirectoryPath
  }
  if (-not (Test-Path -LiteralPath $ExtendedPath)) {
    return
  }
  Get-ChildItem -LiteralPath $ExtendedPath -Force -Recurse -File | ForEach-Object {
    if ($_.IsReadOnly) {
      $_.IsReadOnly = $false
    }
  }
  Remove-Item -LiteralPath $ExtendedPath -Recurse -Force
  if (Test-Path -LiteralPath $ExtendedPath) {
    throw "Failed to remove stale build tree: $DirectoryPath"
  }
}

function Write-Utf8NoBom($Path, $Content) {
  $FilePath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
  [IO.File]::WriteAllText($FilePath, $Content, [Text.UTF8Encoding]::new($false))
}

function Get-PythonCommand {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) { return @("python") }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { return @("py", "-3") }
  throw "Python 3 is required."
}

function Initialize-MsvcEnvironment {
  if (Get-Command link.exe -ErrorAction SilentlyContinue) {
    return
  }

  $VcVarsCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
    (Join-Path $env:ProgramFiles "Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
    "C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    "D:\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -Unique

  $VcVars = $VcVarsCandidates | Select-Object -First 1
  if (-not $VcVars) {
    throw "MSVC Build Tools with vcvars64.bat are required."
  }

  Write-Host "Loading MSVC build environment: $VcVars"
  $EnvironmentLines = & $env:ComSpec /d /s /c "`"$VcVars`" >nul && set"
  Assert-NativeSuccess "MSVC environment initialization" $LASTEXITCODE
  foreach ($Line in $EnvironmentLines) {
    $Separator = $Line.IndexOf("=")
    if ($Separator -gt 0) {
      $Name = $Line.Substring(0, $Separator)
      $Value = $Line.Substring($Separator + 1)
      [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }
  }

  if (-not (Get-Command link.exe -ErrorAction SilentlyContinue)) {
    throw "MSVC environment initialized but link.exe is still unavailable."
  }
}

$CurrentRevision = (& git -C $Root rev-parse HEAD).Trim()
Assert-NativeSuccess "Source revision lookup" $LASTEXITCODE
if ($SourceRevision -and $SourceRevision -ne $CurrentRevision) {
  throw "SourceRevision must match the current Git revision: $CurrentRevision"
}
$SourceRevision = $CurrentRevision
$IsReleaseBuild = $env:DOLPHIN_RELEASE_BUILD -eq "1" -or
  $env:GITHUB_REF_TYPE -eq "tag" -or
  $env:GITHUB_REF -like "refs/tags/*"
$UpdaterArtifactsEnabled = $true

try {
  if ($Version) {
    $RestoreConfig = $true
    $text = Get-Content $Config -Raw
    $text = $text -replace '"version"\s*:\s*"[^"]+"', ('"version": "' + $Version + '"')
    Write-Utf8NoBom $Config $text
  }

  if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
    if ($IsReleaseBuild) {
      throw "TAURI_SIGNING_PRIVATE_KEY is required for a Release-tag desktop build."
    }
    $RestoreConfig = $true
    $text = Get-Content $Config -Raw
    $text = $text -replace '"createUpdaterArtifacts"\s*:\s*true', '"createUpdaterArtifacts": false'
    Write-Utf8NoBom $Config $text
    $UpdaterArtifactsEnabled = $false
    Write-Host "TAURI_SIGNING_PRIVATE_KEY is not set; updater artifacts are temporarily disabled for this non-Release desktop build."
  }

  Write-Host "==> [build-desktop-windows.ps1] ROOT=$Root TARGET=$Target BUNDLE=$Bundle"

  Invoke-Step "1/6 Prepare Windows local Runtime appliance" {
    if (-not $UsePreparedRuntimeAppliance) {
      & (Join-Path $Root "scripts\prepare-local-runtime-appliance-windows.ps1")
      Assert-NativeSuccess "Windows local Runtime appliance preparation" $LASTEXITCODE
    }
    foreach ($RelativePath in @(
      "bin\agent-runtime.exe",
      "codex\bin\codex.exe",
      "codex\codex-resources\codex-command-runner.exe",
      "codex\codex-resources\codex-windows-sandbox-setup.exe",
      "agentic-coding\.venv\Scripts\python.exe",
      "agentic-coding-pack\manifest.yaml",
      "web\builder\dist\index.html"
    )) {
      if (-not (Test-Path -LiteralPath (Join-Path $Tauri "resources\agent-runtime\$RelativePath") -PathType Leaf)) {
        throw "Prepared local Runtime appliance is missing: $RelativePath"
      }
    }
  }

  Invoke-Step "2/6 Install frontend dependencies" {
    Push-Location $Frontend
    try {
      if (-not $SkipInstall -and -not (Test-Path "node_modules")) {
        npm ci
        Assert-NativeSuccess "Frontend dependency install" $LASTEXITCODE
      }
    } finally {
      Pop-Location
    }
  }

  Invoke-Step "3/6 Build frontend desktop bundle" {
    if ($SkipFrontendBuild) {
      $FrontendEntry = Join-Path $Frontend "dist-desktop\index.html"
      if (-not (Test-Path -LiteralPath $FrontendEntry -PathType Leaf)) {
        throw "Cannot skip frontend build because desktop bundle is missing: $FrontendEntry"
      }
      Write-Host "Using prepared frontend desktop bundle: $FrontendEntry"
      return
    }
    Push-Location $Frontend
    $PreviousViteDesktop = [Environment]::GetEnvironmentVariable("VITE_DESKTOP", "Process")
    $PreviousViteBaseUrl = [Environment]::GetEnvironmentVariable("VITE_BASE_URL", "Process")
    $PreviousDolphinBuildRevision = [Environment]::GetEnvironmentVariable("DOLPHIN_BUILD_REVISION", "Process")
    $PreviousDolphinBuildTarget = [Environment]::GetEnvironmentVariable("DOLPHIN_BUILD_TARGET", "Process")
    try {
      $env:VITE_DESKTOP = "1"
      $env:VITE_BASE_URL = "/"
      $env:DOLPHIN_BUILD_REVISION = $SourceRevision
      $env:DOLPHIN_BUILD_TARGET = "windows-x86_64"
      node .\node_modules\vite\bin\vite.js build --outDir dist-desktop --emptyOutDir
      Assert-NativeSuccess "Frontend desktop build" $LASTEXITCODE
    } finally {
      [Environment]::SetEnvironmentVariable("VITE_DESKTOP", $PreviousViteDesktop, "Process")
      [Environment]::SetEnvironmentVariable("VITE_BASE_URL", $PreviousViteBaseUrl, "Process")
      [Environment]::SetEnvironmentVariable("DOLPHIN_BUILD_REVISION", $PreviousDolphinBuildRevision, "Process")
      [Environment]::SetEnvironmentVariable("DOLPHIN_BUILD_TARGET", $PreviousDolphinBuildTarget, "Process")
      Pop-Location
    }
  }

  Invoke-Step "4/6 Build PyInstaller Windows sidecar" {
    if ($SkipSidecarBuild) {
      $PreparedSidecar = Join-Path $Backend "dist\dolphin-ai-sidecar.exe"
      if (-not (Test-Path -LiteralPath $PreparedSidecar -PathType Leaf)) {
        throw "Cannot skip sidecar build because prepared executable is missing: $PreparedSidecar"
      }
      Write-Host "Using prepared Windows sidecar: $PreparedSidecar"
      return
    }
    Push-Location $Backend
    try {
      $VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"
      if (-not (Test-Path $VenvPython)) {
        $cmd = @(Get-PythonCommand)
        if ($cmd.Length -gt 1) {
          & $cmd[0] @($cmd[1..($cmd.Length - 1)] + @("-m", "venv", ".venv"))
          Assert-NativeSuccess "Python virtual environment creation" $LASTEXITCODE
        } else {
          & $cmd[0] -m venv .venv
          Assert-NativeSuccess "Python virtual environment creation" $LASTEXITCODE
        }
      }
      if (-not $SkipInstall) {
        & $VenvPython -m pip install --upgrade pip
        Assert-NativeSuccess "Python pip upgrade" $LASTEXITCODE
        & $VenvPython -m pip install -r requirements.txt
        Assert-NativeSuccess "Python requirements install" $LASTEXITCODE
        & $VenvPython -m pip install "pyinstaller>=6.6"
        Assert-NativeSuccess "PyInstaller dependency install" $LASTEXITCODE
      } else {
        & $VenvPython -m PyInstaller --version | Out-Null
        Assert-NativeSuccess "PyInstaller availability check" $LASTEXITCODE
      }
      & $VenvPython -m PyInstaller dolphin-ai-sidecar.spec --clean --noconfirm
      Assert-NativeSuccess "PyInstaller sidecar build" $LASTEXITCODE
    } finally {
      Pop-Location
    }
  }

  Invoke-Step "5/6 Place sidecar binary" {
    $BinDir = Join-Path $Tauri "binaries"
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $Sidecar = Join-Path $Backend "dist\dolphin-ai-sidecar.exe"
    if (-not (Test-Path $Sidecar)) {
      throw "Missing PyInstaller output: $Sidecar"
    }
    $Dest = Join-Path $BinDir "dolphin-ai-sidecar-$Target.exe"
    Copy-Item $Sidecar $Dest -Force
    Get-Item $Dest | Format-List FullName,Length,LastWriteTime
  }

  Invoke-Step "6/6 Build Tauri Windows package" {
    Push-Location $Root
    try {
      Initialize-MsvcEnvironment
      if (-not $SkipInstall -and -not (Test-Path "node_modules")) {
        npm ci
        Assert-NativeSuccess "Root dependency install" $LASTEXITCODE
      }
      $ReleaseRoot = Join-Path $CargoTargetRoot "$Target\release"
      $ReleaseAgentRuntime = Join-Path $ReleaseRoot "resources\agent-runtime"
      if ($SkipTauriBuild) {
        foreach ($PreparedBinary in @("DolphinAI.exe", "dolphin-ai-sidecar.exe")) {
          if (-not (Test-Path -LiteralPath (Join-Path $ReleaseRoot $PreparedBinary) -PathType Leaf)) {
            throw "Cannot skip Tauri build because prepared binary is missing: $PreparedBinary"
          }
        }
        Write-Host "Using prepared Tauri binaries: $ReleaseRoot"
      } else {
        Remove-Tree $ReleaseAgentRuntime
        if ($Bundle -eq "portable") {
          node .\node_modules\@tauri-apps\cli\tauri.js build --target $Target --no-bundle
        } else {
          node .\node_modules\@tauri-apps\cli\tauri.js build --target $Target --bundles $Bundle
        }
        Assert-NativeSuccess "Tauri Windows build" $LASTEXITCODE
      }

      $ReleaseResources = if ($SkipTauriBuild) {
        Join-Path $Tauri "resources\agent-runtime"
      } else {
        Join-Path $ReleaseRoot "resources\agent-runtime"
      }
      foreach ($RelativePath in @(
        "bin\agent-runtime.exe",
        "codex\bin\codex.exe",
        "codex\codex-resources\codex-command-runner.exe",
        "codex\codex-resources\codex-windows-sandbox-setup.exe",
        "agentic-coding\.venv\Scripts\python.exe",
        "agentic-coding-pack\manifest.yaml",
        "web\builder\dist\index.html"
      )) {
        if (-not (Test-Path -LiteralPath (Join-Path $ReleaseResources $RelativePath) -PathType Leaf)) {
          throw "Tauri package is missing local Runtime resource: $RelativePath"
        }
      }
      $ReleasePython = Join-Path $ReleaseResources "agentic-coding\.venv\Scripts\python.exe"
      & $ReleasePython -B -c "from pydantic import BaseModel; import glob, pathlib, sysconfig, zoneinfo; assert BaseModel; assert sysconfig.get_config_vars()"
      Assert-NativeSuccess "Packaged Runtime Python validation" $LASTEXITCODE
      if ($Bundle -eq "portable") {
        $DownloadDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath(
          (Join-Path $Root "dist-desktop\windows")
        )
        $PortableStagingRoot = Join-Path $env:TEMP "dolphin-ai-$PackageVersion-portable"
        $PortableAppRoot = Join-Path $PortableStagingRoot "DolphinAI"
        $PortableZip = Join-Path $DownloadDir "dolphin-ai-$PackageVersion-windows-x86_64-portable.zip"

        Remove-Tree $PortableStagingRoot
        New-Item -ItemType Directory -Force -Path $PortableAppRoot | Out-Null
        New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
        Get-ChildItem $DownloadDir -File -Filter "dolphin-ai-*-windows-x86_64-portable.zip" |
          Remove-Item -Force

        Copy-Item (Join-Path $ReleaseRoot "DolphinAI.exe") (Join-Path $PortableAppRoot "DolphinAI.exe") -Force
        Copy-Item (Join-Path $ReleaseRoot "dolphin-ai-sidecar.exe") $PortableAppRoot -Force
        if ($SkipTauriBuild) {
          Copy-Tree (Join-Path $Tauri "resources\agent-runtime") (Join-Path $PortableAppRoot "resources\agent-runtime")
        } else {
          Copy-Tree (Join-Path $ReleaseRoot "resources") (Join-Path $PortableAppRoot "resources")
        }

        foreach ($RelativePath in @(
          "DolphinAI.exe",
          "dolphin-ai-sidecar.exe",
          "resources\agent-runtime\bin\agent-runtime.exe",
          "resources\agent-runtime\codex\bin\codex.exe",
          "resources\agent-runtime\agentic-coding\.venv\Scripts\python.exe",
          "resources\agent-runtime\agentic-coding-pack\manifest.yaml",
          "resources\agent-runtime\web\builder\dist\index.html"
        )) {
          $PortablePath = Join-Path $PortableAppRoot $RelativePath
          if (-not (Test-Path -LiteralPath $PortablePath -PathType Leaf)) {
            throw "Portable package is missing $RelativePath"
          }
        }
        $PortablePython = Join-Path $PortableAppRoot "resources\agent-runtime\agentic-coding\.venv\Scripts\python.exe"
        & $PortablePython -B -c "from pydantic import BaseModel; import glob, pathlib, sysconfig, zoneinfo; assert BaseModel; assert sysconfig.get_config_vars()"
        Assert-NativeSuccess "Portable Runtime Python validation" $LASTEXITCODE

        & (Join-Path $Root "scripts\verify-desktop-windows-package.ps1") `
          -PackageRoot $PortableAppRoot `
          -ExpectedVersion $PackageVersion `
          -ExpectedSourceRevision $SourceRevision `
          -WriteManifest
        Assert-NativeSuccess "Portable staging package verification" $LASTEXITCODE

        Push-Location $PortableStagingRoot
        try {
          & tar.exe -a -c -f $PortableZip "DolphinAI"
          if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $PortableZip -PathType Leaf)) {
            throw "Failed to create portable package with tar.exe"
          }
        } finally {
          Pop-Location
        }

        $VerificationRoot = Join-Path $env:TEMP ("dolphin-ai-$PackageVersion-verify-" + [Guid]::NewGuid().ToString("N"))
        try {
          New-Item -ItemType Directory -Force -Path $VerificationRoot | Out-Null
          & tar.exe -xf $PortableZip -C $VerificationRoot
          Assert-NativeSuccess "Portable package extraction" $LASTEXITCODE
          & (Join-Path $Root "scripts\verify-desktop-windows-package.ps1") `
            -PackageRoot (Join-Path $VerificationRoot "DolphinAI") `
            -ExpectedVersion $PackageVersion `
            -ExpectedSourceRevision $SourceRevision
          Assert-NativeSuccess "Extracted portable package verification" $LASTEXITCODE
        } finally {
          $ExtendedVerificationRoot = "\\?\" + $VerificationRoot
          Remove-Item -LiteralPath $ExtendedVerificationRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        Write-Host ""
        Write-Host "Download-ready portable package: $PortableZip"
        Get-Item $PortableZip | Format-List FullName,Length,LastWriteTime
        Get-FileHash $PortableZip -Algorithm SHA256 | Format-List
      } else {
        & (Join-Path $Root "scripts\verify-desktop-windows-package.ps1") `
          -PackageRoot $ReleaseRoot `
          -ApplicationExecutable "app.exe" `
          -ExpectedVersion $PackageVersion `
          -ExpectedSourceRevision $SourceRevision `
          -WriteManifest
        Assert-NativeSuccess "Windows installer staging verification" $LASTEXITCODE
      }
    } finally {
      Pop-Location
    }
  }

  $Elapsed = [int]((Get-Date) - $StartTs).TotalSeconds
  Write-Host ""
  Write-Host "==> Done in ${Elapsed}s. Artifacts:"
  $BundleRoot = Join-Path $CargoTargetRoot "$Target\release\bundle"
  if (-not (Test-Path $BundleRoot)) {
    $BundleRoot = Join-Path $CargoTargetRoot "release\bundle"
  }
  if ($Bundle -ne "portable" -and (Test-Path $BundleRoot)) {
    Get-ChildItem $BundleRoot -Recurse -File |
      Where-Object { $_.Extension -in ".exe", ".msi", ".zip", ".sig" } |
      Select-Object FullName,Length,LastWriteTime |
      Format-Table -AutoSize

    if ($PackageVersion) {
      $DownloadDir = Join-Path $Root "dist-desktop\windows"
      New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
      Get-ChildItem $DownloadDir -File |
        Where-Object { $_.Name -match "ruijing-|Dolphin Code|ruijing-sidecar" } |
        Remove-Item -Force
      $VersionPattern = "(^|[^0-9A-Za-z])$([Regex]::Escape($PackageVersion))([^0-9A-Za-z]|$)"
      $Installer = Get-ChildItem $BundleRoot -Recurse -File -Filter "*.exe" |
        Where-Object { $_.Name -notlike "*.zip" } |
        Where-Object { $_.Name -match $VersionPattern } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
      if ($Installer) {
        Get-ChildItem $DownloadDir -File -Filter "dolphin-ai-*-windows-x86_64-setup.exe" |
          Remove-Item -Force
        $NamedInstaller = Join-Path $DownloadDir "dolphin-ai-$PackageVersion-windows-x86_64-setup.exe"
        Copy-Item $Installer.FullName $NamedInstaller -Force
        Write-Host ""
        Write-Host "Download-ready installer: $NamedInstaller"
        $InstallerSignatures = Get-ChildItem $BundleRoot -Recurse -File -Filter "*.sig" |
          Where-Object { $_.Name -match "\.exe\.sig$" -or $_.Name -match "\.nsis\.zip\.sig$" }
        foreach ($InstallerSignature in $InstallerSignatures) {
          $SignatureName = if ($InstallerSignature.Name -match "\.nsis\.zip\.sig$") {
            "dolphin-ai-$PackageVersion-windows-x86_64-updater.nsis.zip.sig"
          } else {
            "dolphin-ai-$PackageVersion-windows-x86_64-setup.exe.sig"
          }
          Copy-Item $InstallerSignature.FullName (Join-Path $DownloadDir $SignatureName) -Force
        }
        $UpdaterPayload = Get-ChildItem $BundleRoot -Recurse -File -Filter "*.nsis.zip" |
          Sort-Object LastWriteTime -Descending |
          Select-Object -First 1
        if ($UpdaterPayload) {
          Copy-Item $UpdaterPayload.FullName (Join-Path $DownloadDir "dolphin-ai-$PackageVersion-windows-x86_64-updater.nsis.zip") -Force
        }
        if ($UpdaterArtifactsEnabled -and -not $InstallerSignatures) {
          throw "Missing Tauri updater signature for Windows package version $PackageVersion."
        }
        $BrandGateArgs = @(
          (Join-Path $Root "scripts\verify-desktop-release-brand.mjs"),
          "--root", $DownloadDir,
          "--version", $PackageVersion,
          "--platform", "windows"
        )
        if ($UpdaterArtifactsEnabled) {
          $BrandGateArgs += "--require-updater"
        }
        & node @BrandGateArgs
        Assert-NativeSuccess "Windows release brand verification" $LASTEXITCODE
      } elseif ($Bundle -in "nsis", "all") {
        throw "Missing NSIS installer for package version $PackageVersion under $BundleRoot"
      }
      $Msi = Get-ChildItem $BundleRoot -Recurse -File -Filter "*.msi" |
        Where-Object { $_.Name -match $VersionPattern } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
      if ($Msi) {
        Get-ChildItem $DownloadDir -File -Filter "dolphin-ai-*-windows-x86_64.msi" |
          Remove-Item -Force
        $NamedMsi = Join-Path $DownloadDir "dolphin-ai-$PackageVersion-windows-x86_64.msi"
        Copy-Item $Msi.FullName $NamedMsi -Force
        Write-Host "Download-ready MSI: $NamedMsi"
      } elseif ($Bundle -in "msi", "all") {
        throw "Missing MSI installer for package version $PackageVersion under $BundleRoot"
      }
    }
  }
} finally {
  if ($RestoreConfig) {
    Write-Utf8NoBom $Config $OriginalConfig
  }
}
