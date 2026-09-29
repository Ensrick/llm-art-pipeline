# Shared by install.ps1 and rollback.ps1 (dot-sourced). Windows PowerShell 5.1 and PowerShell 7.
# This plugin owns exactly two paths in the game: BepInEx\plugins\ByzantineUnits\ and
# BepInEx\config\ByzantineUnits.cfg (which BepInEx writes at the first start). Everything else under
# BepInEx\plugins and BepInEx\config is fingerprinted before and after each change to prove it was
# left alone.

$script:DefaultGamePath = 'C:\Program Files (x86)\Steam\steamapps\common\Stronghold Crusader Definitive Edition'
$script:GameProcess = 'Stronghold Crusader Definitive Edition'
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$script:RecordPath = Join-Path $PSScriptRoot 'installed.json'

function Get-UnitsPaths([string]$gamePath) {
    $game = [IO.Path]::GetFullPath($gamePath).TrimEnd('\')
    $plugins = Join-Path (Join-Path $game 'BepInEx') 'plugins'
    $config = Join-Path (Join-Path $game 'BepInEx') 'config'
    if (-not (Test-Path -LiteralPath $plugins -PathType Container)) { throw "No BepInEx\plugins folder in $game. Is BepInEx 5 installed?" }
    if (-not (Test-Path -LiteralPath $config -PathType Container)) { throw "No BepInEx\config folder in $game." }
    # Folders are moved, never copied and deleted, so the backups must be on the game's drive.
    if ([IO.Path]::GetPathRoot($game) -ne [IO.Path]::GetPathRoot($PSScriptRoot)) {
        throw "The game ($game) and this repo are on different drives; the backups move folders and need the same drive."
    }
    [pscustomobject]@{
        Game       = $game
        Plugins    = $plugins
        Config     = $config
        Target     = Join-Path $plugins 'ByzantineUnits'
        ConfigFile = Join-Path $config 'ByzantineUnits.cfg'
    }
}

function Assert-GameClosed {
    if (Get-Process -Name $script:GameProcess -ErrorAction SilentlyContinue) {
        throw 'The game is running. Close it first: this script never touches a running game.'
    }
}

function Get-Sha([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash }

function Write-Json([string]$path, $object) {
    [IO.File]::WriteAllText($path, ($object | ConvertTo-Json -Depth 8), $script:Utf8NoBom)
}

function Read-Record {
    if (Test-Path -LiteralPath $script:RecordPath) { Get-Content -LiteralPath $script:RecordPath -Raw | ConvertFrom-Json } else { $null }
}

function New-BackupFolder([string]$kind) {
    $folder = Join-Path (Join-Path $PSScriptRoot 'backups') ((Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $kind)
    if (Test-Path -LiteralPath $folder) { throw "Backup folder already exists: $folder" }
    New-Item -ItemType Directory -Path $folder | Out-Null
    $folder
}

# Every file under BepInEx\plugins and BepInEx\config except this plugin's own two paths, one
# "path|bytes|last write" line each, sorted. Compare two of these with Compare-Fingerprint.
function Get-OthersFingerprint($paths) {
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($dir in @($paths.Plugins, $paths.Config)) {
        foreach ($file in (Get-ChildItem -LiteralPath $dir -Recurse -File -Force)) {
            $full = $file.FullName
            if ($full.StartsWith($paths.Target + '\', [StringComparison]::OrdinalIgnoreCase)) { continue }
            if ([string]::Equals($full, $paths.ConfigFile, [StringComparison]::OrdinalIgnoreCase)) { continue }
            $lines.Add(('{0}|{1}|{2}' -f $full.Substring($paths.Game.Length + 1), $file.Length, $file.LastWriteTimeUtc.Ticks))
        }
    }
    $lines.Sort([StringComparer]::Ordinal)
    [pscustomobject]@{ Count = $lines.Count; Text = ($lines -join "`n") }
}

# Returns the lines that differ ("-" before only, "+" after only); empty when nothing changed.
function Compare-Fingerprint($before, $after) {
    if ($before.Text -ceq $after.Text) { return @() }
    $old = $before.Text -split "`n"
    $new = $after.Text -split "`n"
    @(Compare-Object -ReferenceObject $old -DifferenceObject $new -CaseSensitive | ForEach-Object {
        $(if ($_.SideIndicator -eq '<=') { '- ' } else { '+ ' }) + $_.InputObject
    })
}

# Runs a program with stderr folded into the output, without PowerShell 5.1 turning stderr into
# a terminating error.
function Invoke-Native([string]$program, [string[]]$arguments) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = (& $program @arguments 2>&1 | ForEach-Object { "$_" }) -join [Environment]::NewLine }
    finally { $ErrorActionPreference = $saved }
    [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = $output }
}
