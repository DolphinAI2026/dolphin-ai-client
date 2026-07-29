param(
  [string]$Version = "",
  [string]$Target = "x86_64-pc-windows-msvc",
  [ValidateSet("nsis", "msi", "all")]
  [string]$Bundle = "nsis",
  [switch]$SkipInstall,
  [string]$AgentRuntimeRepo = "",
  [string]$AgenticCodingRoot = "",
  [string]$CodexVendorRoot = "",
  [string]$BuilderDist = "",
  [string]$SuperpowersSource = ""
)

$ErrorActionPreference = "Stop"

$IsWin = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
  [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $IsWin) {
  throw "Windows desktop packages must be built on Windows because PyInstaller cannot cross-compile the sidecar exe."
}

$StartTs = Get-Date
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Frontend = Join-Path $Root "frontend"
$Backend = Join-Path $Root "backend"
$Tauri = Join-Path $Root "src-tauri"
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

function Write-Utf8NoBom($Path, $Content) {
  [IO.File]::WriteAllText($Path, $Content, [Text.UTF8Encoding]::new($false))
}

function Get-PythonCommand {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { return @("py", "-3") }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) { return @("python") }
  throw "Python 3 is required."
}

try {
  if ($Version) {
    $RestoreConfig = $true
    $text = Get-Content $Config -Raw
    $text = $text -replace '"version"\s*:\s*"[^"]+"', ('"version": "' + $Version + '"')
    Write-Utf8NoBom $Config $text
  }

  if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
    $RestoreConfig = $true
    $text = Get-Content $Config -Raw
    $text = $text -replace '"createUpdaterArtifacts"\s*:\s*true', '"createUpdaterArtifacts": false'
    Write-Utf8NoBom $Config $text
    Write-Host "TAURI_SIGNING_PRIVATE_KEY is not set; updater artifacts are disabled for this installer build."
  }

  Write-Host "==> [build-desktop-windows.ps1] ROOT=$Root TARGET=$Target BUNDLE=$Bundle"

  Invoke-Step "1/6 Materialize Windows local runtime appliance" {
    $Prepare = Join-Path $Root "scripts\prepare-local-runtime-appliance-windows.ps1"
    $PrepareArguments = @{}
    foreach ($Entry in @{
      AgentRuntimeRepo = $AgentRuntimeRepo
      AgenticCodingRoot = $AgenticCodingRoot
      CodexVendorRoot = $CodexVendorRoot
      BuilderDist = $BuilderDist
      SuperpowersSource = $SuperpowersSource
    }.GetEnumerator()) {
      if ($Entry.Value) { $PrepareArguments[$Entry.Key] = $Entry.Value }
    }
    & $Prepare @PrepareArguments
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
    Push-Location $Frontend
    $PreviousViteDesktop = [Environment]::GetEnvironmentVariable("VITE_DESKTOP", "Process")
    $PreviousViteBaseUrl = [Environment]::GetEnvironmentVariable("VITE_BASE_URL", "Process")
    try {
      $env:VITE_DESKTOP = "1"
      $env:VITE_BASE_URL = "/"
      npm exec -- vite build --outDir dist-desktop --emptyOutDir
      Assert-NativeSuccess "Frontend desktop build" $LASTEXITCODE
    } finally {
      [Environment]::SetEnvironmentVariable("VITE_DESKTOP", $PreviousViteDesktop, "Process")
      [Environment]::SetEnvironmentVariable("VITE_BASE_URL", $PreviousViteBaseUrl, "Process")
      Pop-Location
    }
  }

  Invoke-Step "4/6 Build PyInstaller Windows sidecar" {
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
      & $VenvPython -m PyInstaller ruijing-sidecar.spec --noconfirm
      Assert-NativeSuccess "PyInstaller sidecar build" $LASTEXITCODE
    } finally {
      Pop-Location
    }
  }

  Invoke-Step "5/6 Place sidecar binary" {
    $BinDir = Join-Path $Tauri "binaries"
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $Sidecar = Join-Path $Backend "dist\ruijing-sidecar.exe"
    if (-not (Test-Path $Sidecar)) {
      throw "Missing PyInstaller output: $Sidecar"
    }
    $Dest = Join-Path $BinDir "ruijing-sidecar-$Target.exe"
    Copy-Item $Sidecar $Dest -Force
    Get-Item $Dest | Format-List FullName,Length,LastWriteTime
  }

  Invoke-Step "6/6 Build Tauri Windows installer" {
    Push-Location $Root
    try {
      if (-not $SkipInstall -and -not (Test-Path "node_modules")) {
        npm ci
        Assert-NativeSuccess "Root dependency install" $LASTEXITCODE
      }
      npx tauri build --target $Target --bundles $Bundle
      Assert-NativeSuccess "Tauri Windows installer build" $LASTEXITCODE

      $ReleaseResources = Join-Path $Tauri "target\$Target\release\resources\agent-runtime"
      foreach ($RelativePath in @(
        "bin\agent-runtime.exe",
        "codex\bin\codex.exe",
        "agentic-coding\.venv\Scripts\python.exe",
        "agentic-coding-pack\manifest.yaml",
        "web\builder\dist\index.html"
      )) {
        $ResourcePath = Join-Path $ReleaseResources $RelativePath
        if (-not (Test-Path -LiteralPath $ResourcePath -PathType Leaf)) {
          throw "Tauri release resources are missing local runtime file: $RelativePath"
        }
      }
    } finally {
      Pop-Location
    }
  }

  $Elapsed = [int]((Get-Date) - $StartTs).TotalSeconds
  Write-Host ""
  Write-Host "==> Done in ${Elapsed}s. Artifacts:"
  $BundleRoot = Join-Path $Tauri "target\$Target\release\bundle"
  if (-not (Test-Path $BundleRoot)) {
    $BundleRoot = Join-Path $Tauri "target\release\bundle"
  }
  if (Test-Path $BundleRoot) {
    Get-ChildItem $BundleRoot -Recurse -File |
      Where-Object { $_.Extension -in ".exe", ".msi", ".zip", ".sig" } |
      Select-Object FullName,Length,LastWriteTime |
      Format-Table -AutoSize

    if ($PackageVersion) {
      $DownloadDir = Join-Path $Root "dist-desktop\windows"
      New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
      $Installer = Get-ChildItem $BundleRoot -Recurse -File -Filter "*.exe" |
        Where-Object { $_.Name -notlike "*.zip" } |
        Select-Object -First 1
      if ($Installer) {
        $NamedInstaller = Join-Path $DownloadDir "ruijing-$PackageVersion-windows-x86_64-setup.exe"
        Copy-Item $Installer.FullName $NamedInstaller -Force
        Write-Host ""
        Write-Host "Download-ready installer: $NamedInstaller"
      }
      $Msi = Get-ChildItem $BundleRoot -Recurse -File -Filter "*.msi" | Select-Object -First 1
      if ($Msi) {
        $NamedMsi = Join-Path $DownloadDir "ruijing-$PackageVersion-windows-x86_64.msi"
        Copy-Item $Msi.FullName $NamedMsi -Force
        Write-Host "Download-ready MSI: $NamedMsi"
      }
    }
  }
} finally {
  if ($RestoreConfig) {
    Write-Utf8NoBom $Config $OriginalConfig
  }
}
