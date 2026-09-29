<#
.SYNOPSIS
    Removes the units plugin from the game in one command. Deletes nothing.

.DESCRIPTION
    Moves BepInEx\plugins\ByzantineUnits into runtime\backups\<stamp>-rollback\, and
    BepInEx\config\ByzantineUnits.cfg too unless that file existed before the first install this
    repo's installed.json remembers. This leaves the game as it was before the plugin was installed.
    Refuses while the game is running and never starts it. Checks that no other file under
    BepInEx\plugins or BepInEx\config changed, and records the result in installed.json. install.ps1
    puts the plugin back. Units placed with this plugin's buttons stay in their maps as ordinary
    carriers with stock art; their saved tags are kept in the map files and apply again after a
    reinstall.

.PARAMETER GamePath
    The game folder. Default: the Steam install on C:.

.PARAMETER DryRun
    Print what would be moved and change nothing.

.EXAMPLE
    pwsh -NoProfile -ExecutionPolicy Bypass -File runtime\rollback.ps1
#>
[CmdletBinding()]
param(
    [string]$GamePath,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
if (-not $GamePath) { $GamePath = $DefaultGamePath }
$runtime = $PSScriptRoot
$paths = Get-UnitsPaths $GamePath
$previous = Read-Record
$hadInstall = Test-Path -LiteralPath $paths.Target
$configExists = Test-Path -LiteralPath $paths.ConfigFile
# Only remove the config if it is ours: it didn't exist before our first recorded install.
$configWasOurs = $configExists -and $previous -and $previous.installed -and -not $previous.configExistedBeforeFirstInstall

if (-not $hadInstall -and -not $configWasOurs) {
    Write-Host "Nothing to roll back: $($paths.Target) does not exist, and the config is not recorded as ours."
    return
}
if ($DryRun) {
    Write-Host 'DRY RUN:'
    if ($hadInstall) { Write-Host "  Would move $($paths.Target) to runtime\backups\<stamp>-rollback\plugins\ByzantineUnits" }
    if ($configWasOurs) { Write-Host "  Would move $($paths.ConfigFile) to runtime\backups\<stamp>-rollback\config\ByzantineUnits.cfg" }
    elseif ($configExists) { Write-Host "  Would leave $($paths.ConfigFile): it existed before this plugin's first install." }
    Write-Host 'Nothing was moved. The game was not started.'
    return
}

Assert-GameClosed
$before = Get-OthersFingerprint $paths
$backup = New-BackupFolder 'rollback'
if ($hadInstall) {
    New-Item -ItemType Directory -Path (Join-Path $backup 'plugins') | Out-Null
    Move-Item -LiteralPath $paths.Target -Destination (Join-Path $backup 'plugins\ByzantineUnits')
}
if ($configWasOurs) {
    New-Item -ItemType Directory -Path (Join-Path $backup 'config') | Out-Null
    Move-Item -LiteralPath $paths.ConfigFile -Destination (Join-Path $backup 'config\ByzantineUnits.cfg')
}
$after = Get-OthersFingerprint $paths
$changed = @(Compare-Fingerprint $before $after)
Write-Json $RecordPath ([ordered]@{
    schema = 'byzantine_units_installed/1'; installed = $false
    rolledBackAt = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz'); game = $paths.Game
    backup = $backup.Substring($runtime.Length + 1); movedPlugin = [bool]$hadInstall; movedConfig = [bool]$configWasOurs
    otherFilesCompared = $after.Count; otherFilesChanged = $changed
})
if ($hadInstall) { Write-Host "Moved the plugin to $backup\plugins\ByzantineUnits." }
if ($configWasOurs) { Write-Host "Moved the config to $backup\config\ByzantineUnits.cfg." }
elseif ($configExists) { Write-Host "Left $($paths.ConfigFile) in place: it existed before this plugin's first install." }
if ($changed.Count -eq 0) { Write-Host "Other plugins and configs: $($after.Count) files compared, none changed." }
else { Write-Warning ("Files outside this plugin changed during the rollback (not by this script):`n" + ($changed -join "`n")) }
Write-Host "Recorded in runtime\installed.json. The game was not started. Reinstall: runtime\install.ps1"
