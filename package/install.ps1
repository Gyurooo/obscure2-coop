# Obscure II online co-op - installer.
#
#   right-click -> Run with PowerShell, or:
#     powershell -ExecutionPolicy Bypass -File install.ps1 "C:\...\Steam\steamapps\common\Obscure II"
#
# Copies the mod next to Obscure2.exe, patches the campaign saves for two players and writes
# obscoop_install.txt: the list of everything this run added or backed up. uninstall.ps1 undoes
# exactly that list and nothing else.
param([string]$GameDir = "")

$ErrorActionPreference = 'Stop'
$PackageDir = $PSScriptRoot

# The one Obscure2.exe the mod's hooks are written for (Steam build 215294).
$SupportedSha  = '003f195b0e5bff91682f7e436cfe8213b6ca53803e17e98cdb5acd2103769354'
$SupportedSize = 3733504
$ManifestName  = 'obscoop_install.txt'

$Version = 'unknown'
if (Test-Path -LiteralPath (Join-Path $PackageDir 'VERSION.txt')) {
    $Version = (Get-Content -LiteralPath (Join-Path $PackageDir 'VERSION.txt') -TotalCount 1).Trim()
}

function Say($text) { Write-Host $text }

Say "Obscure II co-op $Version - installer"
Say "  package: $PackageDir"

# ---------------------------------------------------------------- 1. which game folder
if (-not $GameDir) {
    $GameDir = Read-Host "Path of the Obscure II folder (the one with Obscure2.exe) [$PackageDir]"
    if (-not $GameDir) { $GameDir = $PackageDir }
}
if (-not (Test-Path -LiteralPath $GameDir)) { throw "no such folder: $GameDir" }
$GameDir = (Resolve-Path -LiteralPath $GameDir).Path
$exe = Join-Path $GameDir 'Obscure2.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Obscure2.exe is not in $GameDir - point the installer at the game folder" }
Say "  game   : $GameDir"

# ---------------------------------------------------------------- 2. is this the supported build?
$hash = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLower()
$size = (Get-Item -LiteralPath $exe).Length
if ($hash -ne $SupportedSha) {
    Say ""
    Say "REFUSED: this Obscure2.exe is not the supported Steam build."
    Say "  expected SHA-256 $SupportedSha  ($SupportedSize bytes)"
    Say "  found    SHA-256 $hash  ($size bytes)"
    Say ""
    Say "The mod is written for Steam build 215294 and hooks that exact code. A widescreen patch, a"
    Say "no-CD crack or a repack changes it and the mod would not work (it refuses to start)."
    Say "Fix the game first: Steam -> Library -> right-click Obscure II -> Properties -> Installed"
    Say "files -> Verify integrity of game files. Nothing was changed by this installer."
    exit 2
}
Say "  exe    : Steam build 215294, SHA-256 matches, $size bytes"

# ---------------------------------------------------------------- 3. warnings
foreach ($wrapper in @('d3d9.dll', 'dxgi.dll')) {
    if (Test-Path -LiteralPath (Join-Path $GameDir $wrapper)) {
        Say ""
        Say "  WARNING: $wrapper is in the game folder (DXVK, ReShade or another wrapper). The mod is"
        Say "           untested with it. If the game does not start, or the link stays on 'waiting',"
        Say "           remove that file and try again."
    }
}

# ---------------------------------------------------------------- 4. the files that go in
$files = @(
    'xinput1_3.dll',
    'obscoop_o2.ipt',
    'obscoop_direct.ini.txt',
    'README.txt',
    'start_host_steam.bat',
    'start_guest_steam.bat',
    'start_host_direct.bat',
    'start_guest_direct.bat',
    'obscoop-relay\obscoop-relay.exe',
    'obscoop-relay\steam_api.dll',
    'obscoop-relay\steam_appid.txt',
    'obscoop-relay\start_relay_guest.bat'
)
$missing = @()
foreach ($f in $files) { if (-not (Test-Path -LiteralPath (Join-Path $PackageDir $f))) { $missing += $f } }
if ($missing.Count -gt 0) {
    throw ("the package is incomplete, missing: " + ($missing -join ', ') + " - unpack the whole zip again")
}

# obscoop.ini is a setting file: a player's own copy is never replaced.
$iniCreated = $false
if (-not (Test-Path -LiteralPath (Join-Path $GameDir 'obscoop.ini')) -and
    -not (Test-Path -LiteralPath (Join-Path $GameDir 'obscoop.ini.txt'))) { $iniCreated = $true }

# ---------------------------------------------------------------- 5. backup of an existing DLL
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("obscoop install $Version")
$dll = Join-Path $GameDir 'xinput1_3.dll'
$dllBak = "$dll.bak"
if (Test-Path -LiteralPath $dll) {
    $bak = $dllBak
    if (Test-Path -LiteralPath $bak) {
        # never overwrite a backup - but the DLL being replaced still has to be recoverable
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $bak = "$dll.$stamp.bak"
        Say ""
        Say "  note: xinput1_3.dll.bak already exists and is left as it is (it may be someone else's backup)."
        Say "        The DLL that is there now goes to $([IO.Path]::GetFileName($bak)) instead."
    }
    Copy-Item -LiteralPath $dll -Destination $bak -Force
    $lines.Add("bak xinput1_3.dll $([IO.Path]::GetFileName($bak))")
    Say "  backup : xinput1_3.dll -> $([IO.Path]::GetFileName($bak))"
}

# ---------------------------------------------------------------- 6. copy the mod files
$added = 0
foreach ($f in $files) {
    $dst = Join-Path $GameDir $f
    $dir = Split-Path -Parent $dst
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $same = $false
    if (Test-Path -LiteralPath $dst) {
        $same = ((Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath (Join-Path $PackageDir $f) -Algorithm SHA256).Hash)
    }
    Copy-Item -LiteralPath (Join-Path $PackageDir $f) -Destination $dst -Force
    if (-not $same) { $lines.Add("add $f"); $added++ }
    Say ("  {0,-8} {1}" -f ($(if ($same) { 'same' } else { 'copy' })), $f)
}
if ($iniCreated) {
    Copy-Item -LiteralPath (Join-Path $PackageDir 'obscoop.ini') -Destination (Join-Path $GameDir 'obscoop.ini') -Force
    $lines.Add("add obscoop.ini")
    $added++
    Say "  copy     obscoop.ini (new; an existing obscoop.ini is never replaced)"
} else {
    Say "  keep     obscoop.ini (already there, your settings stay)"
}
# VERSION.txt is written by tools/build_release.sh; a git checkout has none.
if (Test-Path -LiteralPath (Join-Path $PackageDir 'VERSION.txt')) {
    Copy-Item -LiteralPath (Join-Path $PackageDir 'VERSION.txt') -Destination (Join-Path $GameDir 'VERSION.txt') -Force
    $lines.Add("add VERSION.txt")
    $added++
    Say "  copy     VERSION.txt"
}

# ---------------------------------------------------------------- 7. the campaign saves
# The save stores MTHC (the teammate-AI controller) for the partner; player 2 needs 2CHC.
# Latin-1 is a byte-for-byte encoding, so only the four tag bytes change and the rest of the save is
# left exactly as the game wrote it (ASCII would replace every byte above 0x7f with '?').
$enc = [Text.Encoding]::GetEncoding(28591)
$saveDirs = @((Join-Path $GameDir 'Save'), (Join-Path $GameDir 'coop_profile\remote'))
$patched = 0
foreach ($dir in $saveDirs) {
    if (-not (Test-Path -LiteralPath $dir)) { continue }
    foreach ($file in Get-ChildItem -LiteralPath $dir -Filter 'game*.sav' -File) {
        $text = $enc.GetString([IO.File]::ReadAllBytes($file.FullName))
        if (-not $text.Contains('MTHC')) { continue }
        $bak = $file.FullName + '.1p.bak'
        if (-not (Test-Path -LiteralPath $bak)) { Copy-Item -LiteralPath $file.FullName -Destination $bak }
        [IO.File]::WriteAllBytes($file.FullName, $enc.GetBytes($text.Replace('MTHC', '2CHC')))
        $rel = $file.FullName.Substring($GameDir.Length).TrimStart('\')
        $lines.Add("save $rel $($rel + '.1p.bak')")
        $patched++
        Say "  patch    $rel (MTHC -> 2CHC, backup .1p.bak)"
    }
}
if ($patched -eq 0) { Say "  saves    : nothing to patch (no save still stores the AI partner)" }

# ---------------------------------------------------------------- 8. the manifest
$lines.Add("done")
Set-Content -LiteralPath (Join-Path $GameDir $ManifestName) -Value $lines -Encoding ASCII

Say ""
Say "Installed: $added file(s) copied, $patched save(s) patched."
Say "The list of what was changed is in $ManifestName; uninstall.ps1 undoes exactly that."
Say ""
Say "Start the game with one of the .bat files in the game folder:"
Say "  both players at the MAIN MENU, the host loads a save, the guest follows by itself."
Say "  host, over Steam : start_host_steam.bat    guest, over Steam : start_guest_steam.bat"
Say "  host, direct     : start_host_direct.bat   guest, direct     : start_guest_direct.bat"
Say "See README.txt (in the game folder) for the details."
