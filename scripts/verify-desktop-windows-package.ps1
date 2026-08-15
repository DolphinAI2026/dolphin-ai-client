param(
  [Parameter(Mandatory = $true)]
  [string]$PackageRoot,
  [string]$ApplicationExecutable = "Dolphin Code.exe",
  [string]$ExpectedVersion = "",
  [string]$ExpectedSourceRevision = "",
  [switch]$WriteManifest
)

$ErrorActionPreference = "Stop"

$IsWin = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
  [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $IsWin) {
  throw "Windows desktop package verification must run on Windows."
}

$PackageRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PackageRoot)
if (-not (Test-Path -LiteralPath $PackageRoot -PathType Container)) {
  throw "Desktop package root does not exist: $PackageRoot"
}

$RuntimeRoot = Join-Path $PackageRoot "resources\agent-runtime"
$ManifestPath = Join-Path $PackageRoot "build-manifest.json"
$RelativeFiles = @(
  $ApplicationExecutable,
  "ruijing-sidecar.exe",
  "resources\agent-runtime\bin\agent-runtime.exe",
  "resources\agent-runtime\codex\bin\codex.exe",
  "resources\agent-runtime\codex\codex-path\rg.exe",
  "resources\agent-runtime\codex\codex-resources\codex-command-runner.exe",
  "resources\agent-runtime\codex\codex-resources\codex-windows-sandbox-setup.exe",
  "resources\agent-runtime\agentic-coding\.venv\Scripts\python.exe",
  "resources\agent-runtime\agentic-coding-pack\manifest.yaml",
  "resources\agent-runtime\agentic-coding-pack\bin\agentic-pack-reconcile.exe",
  "resources\agent-runtime\web\builder\dist\index.html"
)

function Assert-PackageFile([string]$RelativePath) {
  $Path = Join-Path $PackageRoot $RelativePath
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Desktop package is missing: $RelativePath"
  }
  if ((Get-Item -LiteralPath $Path).Length -le 0) {
    throw "Desktop package contains an empty file: $RelativePath"
  }
}

function Invoke-PackageCommand(
  [string]$Name,
  [string]$Executable,
  [string[]]$Arguments,
  [int[]]$AllowedExitCodes = @(0)
) {
  $PreviousPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = "Continue"
    $Output = & $Executable @Arguments 2>&1
    $ExitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $PreviousPreference
  }
  if ($ExitCode -notin $AllowedExitCodes) {
    $Detail = (($Output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    if ($Detail.Length -gt 4000) {
      $Detail = $Detail.Substring($Detail.Length - 4000)
    }
    throw "$Name failed with exit code $ExitCode. $Detail"
  }
  Write-Host "[package-gate] PASS $Name (exit $ExitCode)"
  return $Output
}

function ConvertTo-ExtendedPath([string]$Path) {
  $FullPath = [IO.Path]::GetFullPath($Path)
  if ($FullPath.StartsWith("\\?\")) {
    return $FullPath
  }
  if ($FullPath.StartsWith("\\")) {
    return "\\?\UNC\" + $FullPath.TrimStart("\")
  }
  return "\\?\" + $FullPath
}

function Invoke-WithEnvironment([hashtable]$Values, [scriptblock]$Body) {
  $Previous = @{}
  foreach ($EnvironmentName in $Values.Keys) {
    $Previous[$EnvironmentName] = [Environment]::GetEnvironmentVariable($EnvironmentName, "Process")
    [Environment]::SetEnvironmentVariable($EnvironmentName, [string]$Values[$EnvironmentName], "Process")
  }
  try {
    & $Body
  } finally {
    foreach ($EnvironmentName in $Values.Keys) {
      [Environment]::SetEnvironmentVariable($EnvironmentName, $Previous[$EnvironmentName], "Process")
    }
  }
}

function Invoke-ReconcileProbe(
  [string]$ProbeName,
  [string]$ProbeRuntimeRoot,
  [string]$CodexHome,
  [hashtable]$ExtraEnvironment = @{}
) {
  New-Item -ItemType Directory -Force -Path $CodexHome | Out-Null
  $Python = [IO.Path]::Combine($ProbeRuntimeRoot, "agentic-coding\.venv\Scripts\python.exe")
  $Reconciler = [IO.Path]::Combine($ProbeRuntimeRoot, "agentic-coding-pack\bin\agentic-pack-reconcile.exe")
  $Environment = @{
    AGENTIC_ROOT = [IO.Path]::Combine($ProbeRuntimeRoot, "agentic-coding")
    AGENTIC_PACK_PYTHON = $Python
    PYTHONDONTWRITEBYTECODE = "1"
    PYTHONUTF8 = "0"
  }
  foreach ($Key in $ExtraEnvironment.Keys) {
    $Environment[$Key] = $ExtraEnvironment[$Key]
  }
  $CommandOutput = Invoke-WithEnvironment $Environment {
    Invoke-PackageCommand $ProbeName $Reconciler @("--codex-home", $CodexHome) @(0, 10)
  }
  $Applied = [IO.Path]::Combine($CodexHome, ".apaas\agentic-pack-applied.yaml")
  if (-not (Test-Path -LiteralPath $Applied -PathType Leaf)) {
    $Detail = (($CommandOutput | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    throw "$ProbeName did not write the applied pack status: $Applied. $Detail"
  }
}

foreach ($RelativePath in $RelativeFiles) {
  Assert-PackageFile $RelativePath
}
Write-Host "[package-gate] PASS required package files"

$HashFiles = [ordered]@{
  application = $ApplicationExecutable
  sidecar = "ruijing-sidecar.exe"
  agent_runtime = "resources\agent-runtime\bin\agent-runtime.exe"
  codex = "resources\agent-runtime\codex\bin\codex.exe"
  python = "resources\agent-runtime\agentic-coding\.venv\Scripts\python.exe"
  pack_reconcile = "resources\agent-runtime\agentic-coding-pack\bin\agentic-pack-reconcile.exe"
}

if ($WriteManifest) {
  $Hashes = [ordered]@{}
  foreach ($Name in $HashFiles.Keys) {
    $Hashes[$Name] = (Get-FileHash -LiteralPath (Join-Path $PackageRoot $HashFiles[$Name]) -Algorithm SHA256).Hash
  }
  $Manifest = [ordered]@{
    schema_version = 1
    product = "Dolphin Code"
    version = $ExpectedVersion
    source_revision = $ExpectedSourceRevision
    target = "x86_64-pc-windows-msvc"
    built_at_utc = [DateTime]::UtcNow.ToString("o")
    hashes = $Hashes
  }
  [IO.File]::WriteAllText(
    $ManifestPath,
    ($Manifest | ConvertTo-Json -Depth 4),
    [Text.UTF8Encoding]::new($false)
  )
  Write-Host "[package-gate] wrote build manifest: $ManifestPath"
}

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
  throw "Desktop package build manifest is missing: $ManifestPath"
}
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ($ExpectedVersion -and $Manifest.version -ne $ExpectedVersion) {
  throw "Desktop package version mismatch: expected $ExpectedVersion, got $($Manifest.version)"
}
if ($ExpectedSourceRevision -and $Manifest.source_revision -ne $ExpectedSourceRevision) {
  throw "Desktop package source revision mismatch: expected $ExpectedSourceRevision, got $($Manifest.source_revision)"
}
foreach ($Name in $HashFiles.Keys) {
  $ExpectedHash = $Manifest.hashes.$Name
  $ActualHash = (Get-FileHash -LiteralPath (Join-Path $PackageRoot $HashFiles[$Name]) -Algorithm SHA256).Hash
  if (-not $ExpectedHash -or $ActualHash -ne $ExpectedHash) {
    throw "Desktop package hash mismatch: $Name"
  }
}
Write-Host "[package-gate] PASS build manifest and binary hashes"

$Codex = Join-Path $RuntimeRoot "codex\bin\codex.exe"
$Python = Join-Path $RuntimeRoot "agentic-coding\.venv\Scripts\python.exe"
Invoke-PackageCommand "Codex startup" $Codex @("--version") | Out-Null
$AgenticPythonPath = (Join-Path $RuntimeRoot "agentic-coding-pack\python") + [IO.Path]::PathSeparator +
  (Join-Path $RuntimeRoot "agentic-coding\python")
Invoke-WithEnvironment @{
  PYTHONPATH = $AgenticPythonPath
  PYTHONDONTWRITEBYTECODE = "1"
} {
  Invoke-PackageCommand "Python runtime" $Python @(
    "-B",
    "-c",
    "from pydantic import BaseModel; import agentic_core, pathlib, sysconfig, yaml, zoneinfo; assert BaseModel; assert sysconfig.get_config_vars()"
  ) | Out-Null
}

$ProbeRoot = Join-Path $env:TEMP ("dolphin-package-gate-" + [Guid]::NewGuid().ToString("N"))
try {
  New-Item -ItemType Directory -Force -Path $ProbeRoot | Out-Null
  $ExtendedRuntimeRoot = ConvertTo-ExtendedPath $RuntimeRoot

  $CleanHome = ConvertTo-ExtendedPath (Join-Path $ProbeRoot "clean-home")
  Invoke-ReconcileProbe "Pack reconcile clean home" $ExtendedRuntimeRoot $CleanHome
  Invoke-ReconcileProbe "Pack reconcile idempotent repeat" $ExtendedRuntimeRoot $CleanHome

  $ExistingHome = ConvertTo-ExtendedPath (Join-Path $ProbeRoot "existing-home")
  New-Item -ItemType Directory -Force -Path $ExistingHome | Out-Null
  [IO.File]::WriteAllText([IO.Path]::Combine($ExistingHome, "config.toml"), "model = 'existing'", [Text.UTF8Encoding]::new($false))
  Invoke-ReconcileProbe "Pack reconcile existing home" $ExtendedRuntimeRoot $ExistingHome

  $RuntimeInstance = Join-Path $ProbeRoot "runtime-instance"
  $RuntimeHome = ConvertTo-ExtendedPath (Join-Path $RuntimeInstance "codex-home")
  $RuntimeTemp = ConvertTo-ExtendedPath (Join-Path $RuntimeInstance "tmp")
  New-Item -ItemType Directory -Force -Path $RuntimeTemp | Out-Null
  Invoke-ReconcileProbe "Pack reconcile Runtime environment" $ExtendedRuntimeRoot $RuntimeHome @{
    HOME = $RuntimeHome
    USERPROFILE = $RuntimeHome
    APPDATA = $RuntimeHome + "\AppData\Roaming"
    LOCALAPPDATA = $RuntimeHome + "\AppData\Local"
    TEMP = $RuntimeTemp
    TMP = $RuntimeTemp
  }

  $ExtendedHome = ConvertTo-ExtendedPath (Join-Path $ProbeRoot "extended-home")
  Invoke-ReconcileProbe "Pack reconcile extended path" $ExtendedRuntimeRoot $ExtendedHome
} finally {
  Remove-Item -LiteralPath $ProbeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[package-gate] PASS Windows desktop package: $PackageRoot"
