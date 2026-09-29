<#
.SYNOPSIS
    Installs the units plugin into the local game, or with -DryRun only shows what it would copy
    and where. Never starts the game.

.DESCRIPTION
    A simplified installer, covering the same safety properties as a production one without needing
    a separate offline-checks project (see docs/RUNTIME.md for why this is trimmed down):
    1. Builds the plugin in Release from the working tree.
    2. Plans the copy: the DLL, info.json, and for each unit whose atlas exists under -ArtRoot
       (default runtime\out\<UnitFolder>\<file>\), the pages, masks, frames.tsv and manifest.json
       that manifest.json lists, verified against their own recorded SHA-256 before planning. A unit
       without an atlas is skipped; its editor button stays disabled in game.
       With -DryRun the script stops here and changes nothing.
    3. Refuses while the game is running. Moves an earlier install (BepInEx\plugins\ByzantineUnits)
       into backups\<stamp>-install\ (nothing is deleted), copies the plan, and checks every copy's
       SHA-256. On any failure the new folder is moved aside and the earlier install is moved back.
    4. Checks that no other file under BepInEx\plugins or BepInEx\config changed, and records the
       install in installed.json. BepInEx writes BepInEx\config\ByzantineUnits.cfg itself at the
       first game start.
    Undo with rollback.ps1.

.PARAMETER GamePath
    The game folder. Default: the Steam install on C:.

.PARAMETER DryRun
    Build and print the plan only.

.PARAMETER ArtRoot
    Where per-unit atlas folders are read from (each: <ArtRoot>\<UnitFolder>\<file>\{manifest.json,
    frames.tsv, pageN.png, pageN_m.png}). Default: runtime\out, tools/pack_atlas.py's usual --out.

.EXAMPLE
    pwsh -NoProfile -ExecutionPolicy Bypass -File runtime\install.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$GamePath,
    [switch]$DryRun,
    [string]$ArtRoot
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
if (-not $GamePath) { $GamePath = $DefaultGamePath }
$runtime = $PSScriptRoot
$artRoot = if ($ArtRoot) { [IO.Path]::GetFullPath($ArtRoot).TrimEnd('\') } else { Join-Path $runtime 'out' }
# One folder per UnitCatalog.cs variant (src/UnitCatalog.cs's Variants array, in the same order).
# Building your own catalog with different units: change this list to match.
$UnitCatalogFolders = @('Vanguard', 'Sentinel', 'FireSiphoner', 'Cataphract', 'IconBearer',
    'Varangian/danish_axe', 'Varangian/sword_shield', 'Varangian/one_hand_axe')

if (-not $DryRun) { Assert-GameClosed }
$paths = Get-UnitsPaths $GamePath
$extenderInfo = Join-Path $paths.Plugins '000shcdese\info.json'
if (-not (Test-Path -LiteralPath $extenderInfo)) { throw "The Script Extender is not installed: $extenderInfo is missing. See docs/RUNTIME.md." }
$extenderVersion = (Get-Content -LiteralPath $extenderInfo -Raw | ConvertFrom-Json).Version

# 1. Build ------------------------------------------------------------------------------------
Write-Host 'Building the plugin (Release, warnings are errors)...'
$build = Invoke-Native 'dotnet' @('build', (Join-Path $runtime 'ByzantineUnits.csproj'), '-c', 'Release', '-nologo',
    '--no-incremental', "-p:GameDir=$($paths.Game)")
if ($build.ExitCode -ne 0) { throw "The plugin build failed:`n$($build.Output)" }
if ($build.Output -notmatch '(?m)^\s*0 Warning\(s\)') { throw "The plugin build reported warnings:`n$($build.Output)" }
$info = Get-Content -LiteralPath (Join-Path $runtime 'info.json') -Raw | ConvertFrom-Json

# 2. Plan the files -----------------------------------------------------------------------------
$plan = New-Object System.Collections.Generic.List[object]
function Add-ToPlan([string]$source, [string]$relative, [string]$expected) {
    $sha = Get-Sha $source
    if ($expected -and $sha -ne $expected.ToUpperInvariant()) { throw "$source changed since it was planned: it no longer matches its manifest." }
    $plan.Add([pscustomobject]@{ path = $relative; sha256 = $sha; bytes = (Get-Item -LiteralPath $source).Length; source = $source })
}
Add-ToPlan (Join-Path $runtime 'bin\Release\net481\ByzantineUnits.dll') 'ByzantineUnits.dll' $null
Add-ToPlan (Join-Path $runtime 'info.json') 'info.json' $null

$unitSummaries = @()
foreach ($v in $UnitCatalogFolders) {
    $atlas = Join-Path $artRoot ($v -replace '/', '\')
    $manifestPath = Join-Path $atlas 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) {
        $unitSummaries += [pscustomobject][ordered]@{ folder = $v; installed = $false; reason = "no manifest.json in $atlas" }
        continue
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $installFolder = 'units\' + ($v -replace '/', '\') + '\' + $manifest.file
    $first = $plan.Count
    foreach ($page in $manifest.pages) {
        Add-ToPlan (Join-Path $atlas $page.name) "$installFolder\$($page.name)" $page.sha256
        Add-ToPlan (Join-Path $atlas $page.mask) "$installFolder\$($page.mask)" $page.maskSha256
    }
    Add-ToPlan (Join-Path $atlas 'frames.tsv') "$installFolder\frames.tsv" $manifest.framesSha256
    Add-ToPlan (Join-Path $atlas 'manifest.json') "$installFolder\manifest.json" $null
    $bytes = ($plan | Select-Object -Skip $first | Measure-Object -Property bytes -Sum).Sum
    $unitSummaries += [pscustomobject][ordered]@{
        folder = $v; installed = $true; unit = $manifest.unit; file = $manifest.file; frames = $manifest.normal
        teamColour = $manifest.teamColour; files = $plan.Count - $first; megabytes = [math]::Round($bytes / 1MB, 1)
    }
}
$totalMegabytes = [math]::Round((($plan | Measure-Object -Property bytes -Sum).Sum) / 1MB, 1)

if ($DryRun) {
    Write-Host ''
    Write-Host "DRY RUN: $($info.Name) $($info.Version). Build: 0 warnings."
    Write-Host "Would copy $($plan.Count) files ($totalMegabytes MB) into $($paths.Target):"
    foreach ($p in $plan) { Write-Host ("  {0,-62} <- {1}" -f $p.path, $p.source) }
    Write-Host 'Per unit:'
    foreach ($u in $unitSummaries) {
        if ($u.installed) { Write-Host ("  {0}: {1} frames, {2} files, {3} MB, team colour '{4}'" -f $u.unit, $u.frames, $u.files, $u.megabytes, $u.teamColour) }
        else { Write-Host ("  {0}: skipped, {1}; its button stays disabled" -f $u.folder, $u.reason) }
    }
    if (Test-Path -LiteralPath $paths.Target) { Write-Host "Would move the existing $($paths.Target) into runtime\backups\<stamp>-install\ first." }
    else { Write-Host "There is no earlier install at $($paths.Target); nothing would be moved." }
    Write-Host 'Nothing was copied, moved or recorded. The game was not started.'
    return
}

# 3. Swap the plugin folder ----------------------------------------------------------------------
Assert-GameClosed
$hadInstall = Test-Path -LiteralPath $paths.Target
$before = Get-OthersFingerprint $paths
$backup = New-BackupFolder 'install'
$moved = $null
if ($hadInstall) {
    New-Item -ItemType Directory -Path (Join-Path $backup 'plugins') | Out-Null
    $moved = Join-Path $backup 'plugins\ByzantineUnits'
    Move-Item -LiteralPath $paths.Target -Destination $moved
}
try {
    foreach ($p in $plan) {
        $destination = Join-Path $paths.Target $p.path
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $p.source -Destination $destination
        if ((Get-Sha $destination) -ne $p.sha256) { throw "Hash mismatch after copying $($p.path)." }
    }
}
catch {
    $failure = $_.Exception.Message
    if (Test-Path -LiteralPath $paths.Target) {
        New-Item -ItemType Directory -Path (Join-Path $backup 'failed') -Force | Out-Null
        Move-Item -LiteralPath $paths.Target -Destination (Join-Path $backup 'failed\ByzantineUnits')
    }
    if ($moved) { Move-Item -LiteralPath $moved -Destination $paths.Target }
    throw "Install failed and was undone (the partial copy is in $backup\failed): $failure"
}

# 4. Prove nothing else changed, then record ------------------------------------------------------
$after = Get-OthersFingerprint $paths
$changed = @(Compare-Fingerprint $before $after)
$record = [ordered]@{
    schema = 'byzantine_units_installed/1'; installed = $true; name = $info.Name; version = $info.Version
    installedAt = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz'); game = $paths.Game; scriptExtender = $extenderVersion
    pluginFolder = 'BepInEx\plugins\ByzantineUnits'
    files = @($plan | ForEach-Object { [ordered]@{ path = $_.path; sha256 = $_.sha256; bytes = $_.bytes } })
    units = $unitSummaries; backup = $backup.Substring($runtime.Length + 1); replacedEarlierInstall = [bool]$hadInstall
    otherFilesCompared = $after.Count; otherFilesChanged = $changed; gameStarted = $false
}
Write-Json $RecordPath $record

Write-Host ("Installed {0} {1}: {2} files ({3} MB) in BepInEx\plugins\ByzantineUnits." -f $info.Name, $info.Version, $plan.Count, $totalMegabytes)
foreach ($u in $unitSummaries) {
    if ($u.installed) { Write-Host ("  {0}: {1} frames" -f $u.unit, $u.frames) }
    else { Write-Host ("  {0}: not installed ({1}); its button stays disabled" -f $u.folder, $u.reason) }
}
if ($hadInstall) { Write-Host "The earlier install was moved to $moved." }
if ($changed.Count -eq 0) { Write-Host "Other plugins and configs: $($after.Count) files compared, none changed." }
else { Write-Warning ("Files outside this plugin changed during the install (not by this script):`n" + ($changed -join "`n")) }
Write-Host "Recorded in runtime\installed.json. The game was not started. Undo: runtime\rollback.ps1"
