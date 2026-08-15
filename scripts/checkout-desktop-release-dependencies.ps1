[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$AgentRuntimeRepoUrl,
  [Parameter(Mandatory = $true)]
  [string]$AgentRuntimeRevision,
  [Parameter(Mandatory = $true)]
  [string]$AgenticCodingRepoUrl,
  [Parameter(Mandatory = $true)]
  [string]$AgenticCodingRevision,
  [Parameter(Mandatory = $true)]
  [string]$SuperpowersRepoUrl,
  [Parameter(Mandatory = $true)]
  [string]$SuperpowersRevision,
  [Parameter(Mandatory = $true)]
  [string]$GitUsername,
  [Parameter(Mandatory = $true)]
  [string]$GitToken,
  [Parameter(Mandatory = $true)]
  [string]$Workspace,
  [Parameter(Mandatory = $true)]
  [string]$RunnerTemp
)

$ErrorActionPreference = 'Stop'
$parentDirectory = Split-Path -Parent $Workspace
$runtimeRoot = Join-Path $parentDirectory 'agent-runtime'
$agenticCodingRoot = Join-Path $parentDirectory 'agentic-coding'
$superpowersRoot = Join-Path $parentDirectory 'superpowers'
$temporaryConfig = Join-Path $RunnerTemp ("dolphin-internal-git-" + [Guid]::NewGuid().ToString('N') + '.config')
$hadPreviousGitConfig = Test-Path Env:GIT_CONFIG_GLOBAL
$previousGitConfig = $env:GIT_CONFIG_GLOBAL
$primaryError = $null

try {
  $env:GIT_CONFIG_GLOBAL = $temporaryConfig
  $credentialUrl = "https://$GitUsername`:$GitToken@git.dfy.definesys.cn/"
  git config --global "url.$credentialUrl.insteadOf" 'https://git.dfy.definesys.cn/'
  if ($LASTEXITCODE -ne 0) { throw "Git credential configuration failed with exit code $LASTEXITCODE." }
  git clone $AgentRuntimeRepoUrl $runtimeRoot
  if ($LASTEXITCODE -ne 0) { throw "agent-runtime clone failed with exit code $LASTEXITCODE." }
  git -C $runtimeRoot checkout --detach $AgentRuntimeRevision
  if ($LASTEXITCODE -ne 0) { throw "agent-runtime checkout failed with exit code $LASTEXITCODE." }
  $runtimeHead = git -C $runtimeRoot rev-parse HEAD
  if ($LASTEXITCODE -ne 0) { throw "agent-runtime HEAD verification failed with exit code $LASTEXITCODE." }
  if (-not [string]::Equals($runtimeHead.Trim(), $AgentRuntimeRevision, [StringComparison]::OrdinalIgnoreCase)) { throw 'agent-runtime HEAD does not match the required revision.' }
  git clone $AgenticCodingRepoUrl $agenticCodingRoot
  if ($LASTEXITCODE -ne 0) { throw "agentic-coding clone failed with exit code $LASTEXITCODE." }
  git -C $agenticCodingRoot checkout --detach $AgenticCodingRevision
  if ($LASTEXITCODE -ne 0) { throw "agentic-coding checkout failed with exit code $LASTEXITCODE." }
  $agenticCodingHead = git -C $agenticCodingRoot rev-parse HEAD
  if ($LASTEXITCODE -ne 0) { throw "agentic-coding HEAD verification failed with exit code $LASTEXITCODE." }
  if (-not [string]::Equals($agenticCodingHead.Trim(), $AgenticCodingRevision, [StringComparison]::OrdinalIgnoreCase)) { throw 'agentic-coding HEAD does not match the required revision.' }
} catch {
  $primaryError = $_
  throw
} finally {
  try {
    if ($hadPreviousGitConfig) { $env:GIT_CONFIG_GLOBAL = $previousGitConfig } elseif (Test-Path Env:GIT_CONFIG_GLOBAL) { Remove-Item Env:GIT_CONFIG_GLOBAL -ErrorAction Stop }
  } catch {
    if ($null -eq $primaryError) { throw }
    Write-Warning "Failed to restore GIT_CONFIG_GLOBAL after dependency checkout: $($_.Exception.Message)"
  }
  try {
    Remove-Item -LiteralPath $temporaryConfig -Force -ErrorAction Stop
  } catch {
    if ($null -eq $primaryError) { throw }
    Write-Warning "Failed to remove temporary Git config after dependency checkout: $($_.Exception.Message)"
  }
}

git clone $SuperpowersRepoUrl $superpowersRoot
if ($LASTEXITCODE -ne 0) { throw "Superpowers clone failed with exit code $LASTEXITCODE." }
git -C $superpowersRoot checkout --detach $SuperpowersRevision
if ($LASTEXITCODE -ne 0) { throw "Superpowers checkout failed with exit code $LASTEXITCODE." }
$superpowersHead = git -C $superpowersRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "Superpowers HEAD verification failed with exit code $LASTEXITCODE." }
if (-not [string]::Equals($superpowersHead.Trim(), $SuperpowersRevision, [StringComparison]::OrdinalIgnoreCase)) { throw 'Superpowers HEAD does not match the required revision.' }
if (-not (Test-Path "$superpowersRoot\.codex-plugin\plugin.json" -PathType Leaf)) { throw 'Fixed Superpowers source is incomplete.' }
