param(
  [string]$Version = "",
  [string]$Target = "x86_64-pc-windows-msvc",
  [ValidateSet("portable", "nsis", "msi", "all")]
  [string]$Bundle = "portable",
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
    Write-Host "TAURI_SIGNING_PRIVATE_KEY is not set; updater artifacts are disabled for this desktop build."
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
      node .\node_modules\vite\bin\vite.js build --outDir dist-desktop --emptyOutDir
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

  Invoke-Step "6/6 Build Tauri Windows package" {
    Push-Location $Root
    try {
      Initialize-MsvcEnvironment
      if (-not $SkipInstall -and -not (Test-Path "node_modules")) {
        npm ci
        Assert-NativeSuccess "Root dependency install" $LASTEXITCODE
      }
      if ($Bundle -eq "portable") {
        node .\node_modules\@tauri-apps\cli\tauri.js build --target $Target --no-bundle
      } else {
        node .\node_modules\@tauri-apps\cli\tauri.js build --target $Target --bundles $Bundle
      }
      Assert-NativeSuccess "Tauri Windows build" $LASTEXITCODE

      # Keep this relative layout identical to packaged_agent_runtime_root() in desktop_backend.rs.
      $PackagedApplianceRelativePath = "resources/agent-runtime"
      $ReleaseRoot = Join-Path $Tauri "target\$Target\release"
      $PackagedApplianceRoot = Join-Path $ReleaseRoot $PackagedApplianceRelativePath
      foreach ($RelativePath in @(
        "bin\agent-runtime.exe",
        "codex\bin\codex.exe",
        "agentic-coding\.venv\Scripts\python.exe",
        "agentic-coding-pack\manifest.yaml",
        "web\builder\dist\index.html"
      )) {
        $ResourcePath = Join-Path $PackagedApplianceRoot $RelativePath
        if (-not (Test-Path -LiteralPath $ResourcePath -PathType Leaf)) {
          throw "Tauri packaged appliance is missing $PackagedApplianceRelativePath\$RelativePath"
        }
      }

      if ($Bundle -eq "portable") {
        $DownloadDir = Join-Path $Root "dist-desktop\windows"
        $PortableStagingRoot = Join-Path $env:TEMP "ruijing-$PackageVersion-portable"
        $PortableAppRoot = Join-Path $PortableStagingRoot "Dolphin Code"
        $PortableZip = Join-Path $DownloadDir "ruijing-$PackageVersion-windows-x86_64-portable.zip"

        Remove-Item $PortableStagingRoot -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $PortableAppRoot | Out-Null
        New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
        Get-ChildItem $DownloadDir -File -Filter "ruijing-*-windows-x86_64-portable.zip" |
          Remove-Item -Force

        Copy-Item (Join-Path $ReleaseRoot "app.exe") (Join-Path $PortableAppRoot "Dolphin Code.exe") -Force
        Copy-Item (Join-Path $ReleaseRoot "ruijing-sidecar.exe") $PortableAppRoot -Force
        Copy-Item (Join-Path $ReleaseRoot "resources") $PortableAppRoot -Recurse -Force

        foreach ($RelativePath in @(
          "Dolphin Code.exe",
          "ruijing-sidecar.exe",
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

        Push-Location $PortableStagingRoot
        try {
          & tar.exe -a -c -f $PortableZip "Dolphin Code"
          if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $PortableZip -PathType Leaf)) {
            throw "Failed to create portable package with tar.exe"
          }
        } finally {
          Pop-Location
        }
        Write-Host ""
        Write-Host "Download-ready portable package: $PortableZip"
        Get-Item $PortableZip | Format-List FullName,Length,LastWriteTime
        Get-FileHash $PortableZip -Algorithm SHA256 | Format-List
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
  if ($Bundle -ne "portable" -and (Test-Path $BundleRoot)) {
    Get-ChildItem $BundleRoot -Recurse -File |
      Where-Object { $_.Extension -in ".exe", ".msi", ".zip", ".sig" } |
      Select-Object FullName,Length,LastWriteTime |
      Format-Table -AutoSize

    if ($PackageVersion) {
      $DownloadDir = Join-Path $Root "dist-desktop\windows"
      New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
      $VersionPattern = "(^|[^0-9A-Za-z])$([Regex]::Escape($PackageVersion))([^0-9A-Za-z]|$)"
      $Installer = Get-ChildItem $BundleRoot -Recurse -File -Filter "*.exe" |
        Where-Object { $_.Name -notlike "*.zip" } |
        Where-Object { $_.Name -match $VersionPattern } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
      if ($Installer) {
        Get-ChildItem $DownloadDir -File -Filter "ruijing-*-windows-x86_64-setup.exe" |
          Remove-Item -Force
        $NamedInstaller = Join-Path $DownloadDir "ruijing-$PackageVersion-windows-x86_64-setup.exe"
        Copy-Item $Installer.FullName $NamedInstaller -Force
        Write-Host ""
        Write-Host "Download-ready installer: $NamedInstaller"
      } elseif ($Bundle -in "nsis", "all") {
        throw "Missing NSIS installer for package version $PackageVersion under $BundleRoot"
      }
      $Msi = Get-ChildItem $BundleRoot -Recurse -File -Filter "*.msi" |
        Where-Object { $_.Name -match $VersionPattern } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
      if ($Msi) {
        Get-ChildItem $DownloadDir -File -Filter "ruijing-*-windows-x86_64.msi" |
          Remove-Item -Force
        $NamedMsi = Join-Path $DownloadDir "ruijing-$PackageVersion-windows-x86_64.msi"
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
