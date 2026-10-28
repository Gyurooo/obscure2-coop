# Obscure II online co-op - uninstaller.
#
#   right-click -> Run with PowerShell, or:
#     powershell -ExecutionPolicy Bypass -File uninstall.ps1 "C:\...\Steam\steamapps\common\Obscure II"
#
# Removes only what install.ps1 added and restores the backups it made, both taken from the manifest
# obscoop_install.txt that install.ps1 wrote. Anything you put there yourself is left alone.
param([string]$GameDir = "")

$ErrorActionPreference = 'Stop'
$ManifestName = 'obscoop_install.txt'

function Say($text) { Write-Host $text }

if (-not $GameDir) {
    $GameDir = Read-Host "Path of the Obscure II folder (the one with Obscure2.exe)"
    if (-not $GameDir) { throw "no folder given" }
}
if (-not (Test-Path -LiteralPath $GameDir)) { throw "no such folder: $GameDir" }
$GameDir = (Resolve-Path -LiteralPath $GameDir).Path
$manifest = Join-Path $GameDir $ManifestName
if (-not (Test-Path -LiteralPath $manifest)) {
    Say "REFUSED: $ManifestName is not in $GameDir, so there is no record of what the installer did."
    Say "Without it this script cannot tell an installed file from one that was always yours. Nothing was"
    Say "removed. Delete these by hand if you are sure they are the mod's:"
    Say "  xinput1_3.dll, obscoop_o2.ipt, obscoop.ini, obscoop_direct.ini.txt, README.txt, VERSION.txt,"
    Say "  start_host_steam.bat, start_guest_steam.bat, start_host_direct.bat, start_guest_direct.bat,"
    Say "  obscoop-relay\ (the whole folder), obscoop.log, obscoop_levels.txt, coop_profile\"
    Say "and rename xinput1_3.dll.bak / Save\gameN.sav.1p.bak back if the installer made them."
    exit 2
}

Say "Obscure II co-op - uninstall"
Say "  game: $GameDir"

$removed = 0
$restored = 0
$entries = @(Get-Content -LiteralPath $manifest | ForEach-Object { , ($_.Trim() -split ' ') })
# Two passes: files this installer added go first, then the backups come back. (The manifest lists a
# backup before the file it replaces, so a single pass would restore the original and delete it again.)
foreach ($part in $entries) {
    if ($part[0] -ne 'add') { continue }
    $path = Join-Path $GameDir $part[1]
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
        Say "  remove   $($part[1])"
        $removed++
    }
}
foreach ($part in $entries) {
    if ($part.Count -lt 2) { continue }
    if ($part[0] -ne 'bak' -and $part[0] -ne 'save') { continue }
    $path = Join-Path $GameDir $part[1]
    $backup = Join-Path $GameDir $part[2]
    if (-not (Test-Path -LiteralPath $backup)) { continue }
    Copy-Item -LiteralPath $backup -Destination $path -Force
    Remove-Item -LiteralPath $backup -Force
    switch ($part[0]) {
        'bak'  { Say "  restore  $($part[1])  (from $($part[2]))" }
        'save' { Say "  restore  $($part[1])  (the save the installer patched)" }
    }
    $restored++
}

# the manifest itself, and the relay folder when it is empty now
Remove-Item -LiteralPath $manifest -Force
$relay = Join-Path $GameDir 'obscoop-relay'
if ((Test-Path -LiteralPath $relay) -and -not (Get-ChildItem -LiteralPath $relay -Force)) {
    Remove-Item -LiteralPath $relay -Force
    Say "  remove   obscoop-relay\ (empty)"
}

Say ""
Say "Removed $removed file(s), restored $restored backup(s)."
Say "Left in place (the mod writes these while it runs, delete them if you want them gone):"
Say "  obscoop.log, obscoop_levels.txt, coop_profile\ (the mod's own save folder)"
