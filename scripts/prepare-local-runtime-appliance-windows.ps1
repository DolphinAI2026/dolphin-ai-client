param(
  [string]$AgentRuntimeRepo = "",
  [string]$AgenticCodingRoot = "",
  [string]$CodexVendorRoot = "",
  [string]$BuilderDist = "",
  [string]$SuperpowersSource = "",
  [string]$ApplianceDir = ""
)

$ErrorActionPreference = "Stop"

$IsWin = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
  [System.Runtime.InteropServices.OSPlatform]::Windows
)
if (-not $IsWin) {
  throw "The Windows local runtime appliance must be materialized on Windows."
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $ApplianceDir) {
  $ApplianceDir = Join-Path $Root "src-tauri\resources\agent-runtime"
}

function Assert-NativeSuccess($Name, $ExitCode) {
  if ($ExitCode -ne 0) {
    throw "$Name failed with exit code $ExitCode."
  }
}

function Resolve-Directory($Name, [string[]]$Candidates) {
  foreach ($Candidate in $Candidates) {
    if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Container)) {
      return (Resolve-Path -LiteralPath $Candidate).Path
    }
  }
  throw "Unable to locate $Name. Pass its explicit parameter or configure the matching environment variable."
}

function Copy-Tree($Source, $Destination) {
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  & robocopy $Source $Destination /E /NFL /NDL /NJH /NJS /NP /XD __pycache__ /XF *.pyc *.pyo | Out-Null
  if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed from $Source to $Destination with exit code $LASTEXITCODE."
  }
}

function Write-Utf8NoBom($Path, $Content) {
  [IO.File]::WriteAllText($Path, $Content, [Text.UTF8Encoding]::new($false))
}

function Assert-ApplianceFile($RelativePath) {
  $Path = Join-Path $ApplianceDir $RelativePath
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Local runtime appliance is missing $RelativePath."
  }
  if ((Get-Item -LiteralPath $Path).Length -le 0) {
    throw "Local runtime appliance file is empty: $RelativePath."
  }
}

$WorkspaceCandidates = @()
if ($env:DOLPHIN_CODE_WORKSPACE_ROOT) {
  $WorkspaceCandidates += $env:DOLPHIN_CODE_WORKSPACE_ROOT
}
$WorkspaceCandidates += (Split-Path $Root -Parent)

$AgentRuntimeRepo = Resolve-Directory "agent-runtime repository" @(
  $AgentRuntimeRepo,
  $env:DOLPHIN_AGENT_RUNTIME_REPO,
  $(foreach ($Workspace in $WorkspaceCandidates) { Join-Path $Workspace "agent-runtime" })
)
$AgenticCodingRoot = Resolve-Directory "agentic-coding root" @(
  $AgenticCodingRoot,
  $env:AGENTIC_CODING_ROOT,
  $(foreach ($Workspace in $WorkspaceCandidates) { Join-Path $Workspace "agentic-coding" })
)

if (-not $BuilderDist) {
  $BuilderDist = Join-Path $AgentRuntimeRepo "web\builder\dist"
}
$BuilderDist = Resolve-Directory "Builder dist" @($BuilderDist)

if (-not $CodexVendorRoot) {
  $CodexVendorRoot = $env:CODEX_NATIVE_ROOT
}
if (-not $CodexVendorRoot) {
  $CodexCandidates = @(
    Get-ChildItem -Path (Join-Path $env:USERPROFILE ".workbuddy\binaries\node\versions\*\node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc") -Directory -ErrorAction SilentlyContinue
  ) | Sort-Object FullName -Descending
  $CodexVendorRoot = $CodexCandidates | Select-Object -First 1 -ExpandProperty FullName
}
$CodexVendorRoot = Resolve-Directory "Codex Windows vendor" @($CodexVendorRoot)

if (-not $SuperpowersSource) {
  $SuperpowersSource = $env:AGENTIC_SUPERPOWERS_SOURCE
}
if (-not $SuperpowersSource) {
  $ManagedSuperpowers = Join-Path $env:USERPROFILE ".codex\superpowers"
  if (Test-Path -LiteralPath (Join-Path $ManagedSuperpowers ".codex-plugin\plugin.json")) {
    $SuperpowersSource = $ManagedSuperpowers
  } else {
    $TemporaryPlugin = Join-Path $env:USERPROFILE ".codex\.tmp\plugins\plugins\superpowers"
    if (Test-Path -LiteralPath (Join-Path $TemporaryPlugin ".codex-plugin\plugin.json")) {
      $SuperpowersSource = $TemporaryPlugin
    } else {
      $CacheRoot = Join-Path $env:USERPROFILE ".codex\plugins\cache\openai-api-curated\superpowers"
      $SuperpowersSource = Get-ChildItem -LiteralPath $CacheRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName ".codex-plugin\plugin.json") } |
        Sort-Object Name -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    }
  }
}
$SuperpowersSource = Resolve-Directory "Superpowers source" @($SuperpowersSource)

$Go = Get-Command go -ErrorAction SilentlyContinue
if (-not $Go) {
  throw "Go is required to build the Windows local runtime appliance."
}
$SourcePython = Join-Path $AgenticCodingRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $SourcePython -PathType Leaf)) {
  throw "Missing agentic-coding Windows Python: $SourcePython"
}

$RequiredCodexFiles = @(
  "bin\codex.exe",
  "codex-path\rg.exe",
  "codex-resources\codex-command-runner.exe",
  "codex-resources\codex-windows-sandbox-setup.exe"
)
foreach ($RelativePath in $RequiredCodexFiles) {
  if (-not (Test-Path -LiteralPath (Join-Path $CodexVendorRoot $RelativePath) -PathType Leaf)) {
    throw "Codex Windows vendor is incomplete: $RelativePath"
  }
}
if (-not (Test-Path -LiteralPath (Join-Path $BuilderDist "index.html") -PathType Leaf)) {
  throw "Builder dist is missing index.html: $BuilderDist"
}

$TemporaryRoot = Join-Path $env:TEMP ("dolphin-appliance-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $TemporaryRoot | Out-Null
$OriginalPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$OriginalDontWriteBytecode = [Environment]::GetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", "Process")

try {
  Remove-Item -LiteralPath $ApplianceDir -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $ApplianceDir | Out-Null

  Write-Host "[local-runtime-appliance] build Windows agent-runtime"
  $ReconcilerSource = Join-Path $AgentRuntimeRepo "internal\adapters\agenticpack\reconciler.go"
  $PatchedReconcilerPath = Join-Path $Root "scripts\windows-agent-runtime-reconciler.go"
  if (-not (Test-Path -LiteralPath $PatchedReconcilerPath -PathType Leaf)) {
    throw "Missing Windows agent-runtime reconciler overlay: $PatchedReconcilerPath"
  }

  $FileLockSource = Join-Path $AgentRuntimeRepo "internal\adapters\filetxn\lock.go"
  $WindowsFileLockPath = Join-Path $TemporaryRoot "filetxn-lock-windows.go"
  Write-Utf8NoBom $WindowsFileLockPath @'
package filetxn

import (
  "context"
  "errors"
  "fmt"
  "os"
  "path/filepath"
  "syscall"
  "time"
  "unsafe"
)

const (
  lockFileFailImmediately = 0x00000001
  lockFileExclusiveLock   = 0x00000002
  errorLockViolation      = syscall.Errno(33)
)

var (
  errLockBusy   = errors.New("file transaction lock is busy")
  kernel32      = syscall.NewLazyDLL("kernel32.dll")
  procLockFile  = kernel32.NewProc("LockFileEx")
  procUnlockFile = kernel32.NewProc("UnlockFileEx")
)

var ErrLockBusy = errLockBusy

type Lock struct {
  file       *os.File
  overlapped syscall.Overlapped
}

func Acquire(ctx context.Context, path string) (*Lock, error) {
  return acquire(ctx, path, true, true)
}

func AcquireShared(ctx context.Context, path string) (*Lock, error) {
  return acquire(ctx, path, false, true)
}

func TryAcquireExclusive(path string) (*Lock, error) {
  return acquire(context.Background(), path, true, false)
}

func acquire(ctx context.Context, path string, exclusive bool, wait bool) (*Lock, error) {
  if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
    return nil, err
  }
  file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
  if err != nil {
    return nil, err
  }
  for {
    overlapped, err := lockFile(file, exclusive)
    if err == nil {
      return &Lock{file: file, overlapped: overlapped}, nil
    }
    if !errors.Is(err, errorLockViolation) {
      file.Close()
      return nil, err
    }
    if !wait {
      file.Close()
      return nil, ErrLockBusy
    }
    select {
    case <-ctx.Done():
      file.Close()
      return nil, ctx.Err()
    case <-time.After(5 * time.Millisecond):
    }
  }
}

func lockFile(file *os.File, exclusive bool) (syscall.Overlapped, error) {
  flags := uintptr(lockFileFailImmediately)
  if exclusive {
    flags |= lockFileExclusiveLock
  }
  var overlapped syscall.Overlapped
  result, _, callErr := procLockFile.Call(
    file.Fd(),
    flags,
    0,
    uintptr(0xffffffff),
    uintptr(0xffffffff),
    uintptr(unsafe.Pointer(&overlapped)),
  )
  if result == 0 {
    return syscall.Overlapped{}, callErr
  }
  return overlapped, nil
}

func (l *Lock) Release() error {
  if l == nil || l.file == nil {
    return nil
  }
  result, _, callErr := procUnlockFile.Call(
    l.file.Fd(),
    0,
    uintptr(0xffffffff),
    uintptr(0xffffffff),
    uintptr(unsafe.Pointer(&l.overlapped)),
  )
  closeErr := l.file.Close()
  l.file = nil
  if result == 0 {
    return fmt.Errorf("unlock file: %w", callErr)
  }
  return closeErr
}
'@

  $OverlayPath = Join-Path $TemporaryRoot "overlay.json"
  $Overlay = @{ Replace = @{
    $ReconcilerSource = $PatchedReconcilerPath
    $FileLockSource = $WindowsFileLockPath
  } } | ConvertTo-Json -Depth 4
  Write-Utf8NoBom $OverlayPath $Overlay

  $RuntimeDestination = Join-Path $ApplianceDir "bin\agent-runtime.exe"
  New-Item -ItemType Directory -Force -Path (Split-Path $RuntimeDestination -Parent) | Out-Null
  Push-Location $AgentRuntimeRepo
  try {
    & $Go.Source build -trimpath -ldflags "-s -w" "-overlay=$OverlayPath" -o $RuntimeDestination .\cmd\sandbox-runtime
    Assert-NativeSuccess "Windows agent-runtime build" $LASTEXITCODE
  } finally {
    Pop-Location
  }

  Write-Host "[local-runtime-appliance] copy Codex vendor and Builder assets"
  Copy-Tree $CodexVendorRoot (Join-Path $ApplianceDir "codex")
  Copy-Tree $BuilderDist (Join-Path $ApplianceDir "web\builder\dist")

  Write-Host "[local-runtime-appliance] copy agentic-coding toolchain"
  $PackagedAgenticRoot = Join-Path $ApplianceDir "agentic-coding"
  Copy-Tree (Join-Path $AgenticCodingRoot "bin") (Join-Path $PackagedAgenticRoot "bin")
  Copy-Tree (Join-Path $AgenticCodingRoot "python") (Join-Path $PackagedAgenticRoot "python")

  Write-Host "[local-runtime-appliance] create relocatable Python runtime"
  $PythonBase = (& $SourcePython -c "import sys; print(sys.base_prefix)").Trim()
  Assert-NativeSuccess "Resolve agentic-coding Python base" $LASTEXITCODE
  $PythonBase = Resolve-Directory "agentic-coding Python base" @($PythonBase)
  $PortableScripts = Join-Path $PackagedAgenticRoot ".venv\Scripts"
  Copy-Tree $PythonBase $PortableScripts
  $PortableSitePackages = Join-Path $PortableScripts "Lib\site-packages"
  Remove-Item -LiteralPath $PortableSitePackages -Recurse -Force -ErrorAction SilentlyContinue
  Copy-Tree (Join-Path $AgenticCodingRoot ".venv\Lib\site-packages") $PortableSitePackages
  Remove-Item -LiteralPath (Join-Path $PackagedAgenticRoot ".venv\pyvenv.cfg") -Force -ErrorAction SilentlyContinue

  Write-Host "[local-runtime-appliance] build offline agentic pack"
  $PackDir = Join-Path $ApplianceDir "agentic-coding-pack"
  $PreviousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
  try {
    $env:PYTHONPATH = Join-Path $AgenticCodingRoot "python"
    & $SourcePython -m agentic_core.cli pack build --profile sandbox-container --output $PackDir --superpowers-source $SuperpowersSource $AgenticCodingRoot
    Assert-NativeSuccess "Offline agentic pack build" $LASTEXITCODE
  } finally {
    [Environment]::SetEnvironmentVariable("PYTHONPATH", $PreviousPythonPath, "Process")
  }

  Write-Host "[local-runtime-appliance] add Windows pack launchers"
  $DoctorPath = Join-Path $PackDir "python\agentic_core\pack\doctor.py"
  $DoctorText = Get-Content -LiteralPath $DoctorPath -Raw
  $HarnessMarker = "    entrypoint = pack_dir / _HARNESS_EVIDENCE_ENTRYPOINT_PATH"
  $DesignMarker = "    entrypoint = pack_dir / _DESIGN_ENTRYPOINT_PATH"
  $ExecutableMarker = "def _is_executable(path: Path) -> bool:"
  if (
    -not $DoctorText.Contains($HarnessMarker) -or
    -not $DoctorText.Contains($DesignMarker) -or
    -not $DoctorText.Contains($ExecutableMarker)
  ) {
    throw "agentic pack doctor no longer matches the Windows launcher contract."
  }
  $WindowsEntrypoint = "`r`n    if os.name == `"nt`":`r`n        windows_entrypoint = entrypoint.with_name(entrypoint.name + `".exe`")`r`n        if windows_entrypoint.is_file():`r`n            entrypoint = windows_entrypoint"
  $DoctorText = $DoctorText.Replace($HarnessMarker, $HarnessMarker + $WindowsEntrypoint)
  $DoctorText = $DoctorText.Replace($DesignMarker, $DesignMarker + $WindowsEntrypoint)
  $DoctorText = $DoctorText.Replace(
    $ExecutableMarker,
    "$ExecutableMarker`r`n    if os.name == `"nt`":`r`n        windows_entrypoint = path.with_name(path.name + `".exe`")`r`n        return windows_entrypoint.is_file() or path.is_file()"
  )
  Write-Utf8NoBom $DoctorPath $DoctorText

  $LauncherSource = @'
package main

import (
  "fmt"
  "os"
  "os/exec"
  "path/filepath"
  "strings"
)

func main() {
  executable, err := os.Executable()
  if err != nil { exitError(err) }
  name := strings.TrimSuffix(filepath.Base(executable), ".exe")
  packRoot := filepath.Dir(filepath.Dir(executable))
  applianceRoot := filepath.Dir(packRoot)
  python := filepath.Join(applianceRoot, "agentic-coding", ".venv", "Scripts", "python.exe")
  agenticPython := filepath.Join(applianceRoot, "agentic-coding", "python")
  packPython := filepath.Join(packRoot, "python")

  args := []string{"-m"}
  incoming := os.Args[1:]
  switch name {
  case "agentic-pack-doctor", "agentic-pack-reconcile":
    subcommand := strings.TrimPrefix(name, "agentic-pack-")
    args = append(args, "agentic_core.cli", "pack", subcommand, "--pack", packRoot)
  case "agentic-design":
    args = append(args, "agentic_core.cli")
    if len(incoming) > 0 && incoming[0] == "--json" {
      args = append(args, "--json", "design")
      incoming = incoming[1:]
    } else {
      args = append(args, "design")
    }
  case "agentic-evidence":
    args = append(args, "agentic_core.harness_evidence.cli")
  default:
    exitError(fmt.Errorf("unsupported Windows pack launcher %q", name))
  }
  args = append(args, incoming...)

  command := exec.Command(python, args...)
  command.Dir = packRoot
  command.Stdin = os.Stdin
  command.Stdout = os.Stdout
  command.Stderr = os.Stderr
  command.Env = append(
    os.Environ(),
    "PYTHONPATH="+packPython+string(os.PathListSeparator)+agenticPython,
    "PYTHONDONTWRITEBYTECODE=1",
    "PYTHONUTF8=1",
  )
  if err := command.Run(); err != nil {
    if exit, ok := err.(*exec.ExitError); ok { os.Exit(exit.ExitCode()) }
    exitError(err)
  }
}

func exitError(err error) {
  fmt.Fprintln(os.Stderr, err)
  os.Exit(127)
}
'@
  $LauncherSourcePath = Join-Path $TemporaryRoot "pack-launcher.go"
  $LauncherBinary = Join-Path $TemporaryRoot "pack-launcher.exe"
  Write-Utf8NoBom $LauncherSourcePath $LauncherSource
  & $Go.Source build -trimpath -ldflags "-s -w" -o $LauncherBinary $LauncherSourcePath
  Assert-NativeSuccess "Windows pack launcher build" $LASTEXITCODE
  foreach ($Name in @("agentic-pack-doctor", "agentic-pack-reconcile", "agentic-design", "agentic-evidence")) {
    Copy-Item -LiteralPath $LauncherBinary -Destination (Join-Path $PackDir "bin\$Name.exe") -Force
  }

  $DigestScript = Join-Path $TemporaryRoot "rewrite-pack-digest.py"
  Write-Utf8NoBom $DigestScript @'
from pathlib import Path
import shutil
import sys
import yaml
from agentic_core.pack.checksums import compute_pack_digest

pack = Path(sys.argv[1])
for cache in pack.rglob("__pycache__"):
    shutil.rmtree(cache)
manifest_path = pack / "manifest.yaml"
manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
manifest["pack"]["platform"] = "windows"
manifest["pack"]["digest"] = "sha256:"
manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
manifest["pack"]["digest"] = compute_pack_digest(pack)
manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
'@

  $PortablePython = Join-Path $PortableScripts "python.exe"
  $env:PYTHONPATH = (Join-Path $PackDir "python") + [IO.Path]::PathSeparator + (Join-Path $PackagedAgenticRoot "python")
  $env:PYTHONDONTWRITEBYTECODE = "1"
  & $PortablePython $DigestScript $PackDir
  Assert-NativeSuccess "Windows pack digest rewrite" $LASTEXITCODE

  Write-Host "[local-runtime-appliance] validate appliance"
  foreach ($RelativePath in @(
    "bin\agent-runtime.exe",
    "codex\bin\codex.exe",
    "codex\codex-path\rg.exe",
    "codex\codex-resources\codex-command-runner.exe",
    "codex\codex-resources\codex-windows-sandbox-setup.exe",
    "agentic-coding\.venv\Scripts\python.exe",
    "agentic-coding\bin\agentic-pack",
    "agentic-coding\python\agentic_core\cli.py",
    "agentic-coding-pack\manifest.yaml",
    "agentic-coding-pack\bin\agentic-pack-reconcile.exe",
    "agentic-coding-pack\skills\superpowers\skills\brainstorming\SKILL.md",
    "web\builder\dist\index.html"
  )) {
    Assert-ApplianceFile $RelativePath
  }

  & (Join-Path $ApplianceDir "codex\bin\codex.exe") --version | Out-Null
  Assert-NativeSuccess "Packaged Codex validation" $LASTEXITCODE
  & $PortablePython -c "from pydantic import BaseModel; import agentic_core, glob, pathlib, sysconfig, yaml, zoneinfo; assert BaseModel; assert sysconfig.get_config_vars()"
  Assert-NativeSuccess "Portable Python validation" $LASTEXITCODE

  $ProbeHome = Join-Path $TemporaryRoot "codex-home"
  New-Item -ItemType Directory -Force -Path $ProbeHome | Out-Null
  $env:AGENTIC_ROOT = $PackagedAgenticRoot
  $env:AGENTIC_PACK_PYTHON = $PortablePython
  & (Join-Path $PackDir "bin\agentic-pack-reconcile.exe") --codex-home $ProbeHome
  if ($LASTEXITCODE -notin @(0, 10)) {
    throw "Packaged agentic pack reconcile failed with exit code $LASTEXITCODE."
  }
  if (-not (Test-Path -LiteralPath (Join-Path $ProbeHome "skills\superpowers\brainstorming\SKILL.md") -PathType Leaf)) {
    throw "Reconciled Codex home is missing the required Superpowers skill."
  }

  Write-Host "[local-runtime-appliance] complete: $ApplianceDir"
  Get-ChildItem -LiteralPath $ApplianceDir -Directory | Select-Object Name | Format-Table -AutoSize
} finally {
  [Environment]::SetEnvironmentVariable("PYTHONPATH", $OriginalPythonPath, "Process")
  [Environment]::SetEnvironmentVariable("PYTHONDONTWRITEBYTECODE", $OriginalDontWriteBytecode, "Process")
  Remove-Item -LiteralPath $TemporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
}

exit 0
