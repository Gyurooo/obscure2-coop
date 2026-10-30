# FINDINGS I1 — Inno Setup installer + Steam save import

Worktree `w-installer`, branch `w/installer`. No game/relay code is changed and no game was launched
(TASK I1 forbids it; another worker runs the live tests). Everything below was run against fake folders
under `_fake/test_installer/` only.
Labels: **OBSERVED** = printed by a run in this task or read in a file with a line reference;
**DERIVED** = follows from the code but was not exercised; **GUESS**; **UNKNOWN**.

## 0. What was there, what is there now

| file | change |
|---|---|
| `package/obscoop2.iss` | wizard: Start-menu entries, the Steam save import, `import` manifest lines, silent-safe gates, test switches |
| `tests/test_installer.sh` | new: builds the setup with ISCC and drives install/uninstall silently on fake folders |
| `tests/check_installer.py` | new: the byte-level checks the driver runs |
| `tools/build_release.sh` | the setup is now `build/obscoop2-<ver>-setup.exe` next to `obscoop2-<ver>.zip` |
| `package/INSTALL.txt` | setup exe is the way in, where the mod's saves live, Steam Cloud note, uninstaller |
| `package/README.txt` | one line: the uninstall entry is Settings -> Apps (uninstall.ps1 is the manual route) |
| `.gitignore` | `_fake/` (the fake folders the test creates) |

`package/install.ps1` and `package/uninstall.ps1` are unchanged: the setup must do what they do (TASK
item 1), and the uninstaller must undo exactly the `obscoop_install.txt` they understand. The one thing
the setup does that install.ps1 does not is the save import (TASK item 2); INSTALL.txt says so.

## 1. Where the mod reads its saves (source, not guessed)

**OBSERVED** `src/obscoop2.c:1958-1980` (`DllMain`):

    GetModuleFileNameA(NULL, g_dir, MAX_PATH);  ... slash removed ...
    strncpy(low, g_dir, MAX_PATH - 1); _strlwr(low);
    strcpy(g_data, g_dir);
    if (strstr(low, "\\program files")) { SHGetFolderPathA(CSIDL_LOCAL_APPDATA) -> g_data = %LOCALAPPDATA%\obscoop }
    _snprintf(g_profile, MAX_PATH, "%s\\coop_profile", g_data);
    _snprintf(g_remote,  MAX_PATH, "%s\\remote", g_profile);

So: game dir contains `\program files` (lower-cased) -> `%LOCALAPPDATA%\obscoop\coop_profile\remote`,
else `<game dir>\coop_profile\remote`. The installer's `ModSaveDirOf` (obscoop2.iss) is the same test
(`Pos('\program files', Lowercase(AppDir))`), and the uninstaller calls it again so both sides resolve
the same folder. **DERIVED**: the `Program Files` branch is not exercised by the test (see §8).

Steam's own copies: `<steam>\userdata\<id>\254480\remote\game*.sav` (README/INSTALL say the same).

## 2. Inno Setup 7.1.0 facts found while building this (OBSERVED, throwaway probes in $TMPDIR)

- `CmdLineParamExists` does not exist in the script engine (compile error, Inno 7.1.0). `{param:NAME|}`
  returns the value of `/NAME=value`, but `''` for a **bare** `/FAKEHASH`. The bare switch is therefore
  found by scanning `GetCmdTail` (`SwitchGiven`), and `/FAKESTEAM=`, `/SAVEID=` use `{param:...}`.
- A default `[Setup]` block (admin) makes a silent run launched from a non-elevated shell **hang** on
  the UAC prompt. `obscoop2.iss` has `PrivilegesRequired=lowest`; that is what makes the silent test
  possible at all.
- `MsgBox` from `[Code]` is **not** answered automatically in a silent run: `/SUPPRESSMSGBOXES` does not
  cover it (the first uninstall run blocked on the "put the saves back?" question, log line
  "Message box (Yes/No):"). Same for the error dialog of a failed `PrepareToInstall`. The script now
  avoids both when silent: the uninstaller restores the saves without asking (`UninstallSilent`), and
  the exe gate runs in `InitializeSetup` for a silent install with `/DIR`, where `Result := False`
  ends setup with exit code 1 and no dialog (observed in the run's setup log: "refused (silent): ...",
  "InitializeSetup returned False; aborting.").
- Git Bash rewrites `/VERYSILENT` into a path, so the driver sets `MSYS2_ARG_CONV_EXCL='*'` and
  `MSYS_NO_PATHCONV=1` for every setup/uninstall call.
- `/NOICONS` (stock Inno switch) keeps the silent test out of the real Start Menu.
- An interactive `[Code]` wizard page is created when there is more than one Steam account with saves;
  silent runs still create it (so the code path is compiled and executed) but never read the selection.
- `{app}` (and `{param:...}`) must not appear inside a `[Code]` comment: the preprocessor expands it and
  the script does not compile. Comments use plain words instead.

## 3. Keep install.ps1's behaviour, step for step

| install.ps1 | obscoop2.iss |
|---|---|
| `$SupportedSha` / size gate, refuses with exit 2 | `CheckGameDir` (SHA-256 via `GetSHA256OfFile`), `NextButtonClick` (dialog) and `PrepareToInstall` (silent) refuse; INSTALL.txt text identical in substance |
| `d3d9.dll` / `dxgi.dll` warning | `PrepareToInstall`, `MsgBox` interactively, `Log` when silent |
| package completeness check | Inno fails the compile if a `[Files]` source is missing (`{#if FileExists}` around `VERSION.txt`, which only a release has) |
| `obscoop.ini` never replaced | `Check: NeedIni` + `onlyifdoesntexist`, `RememberDest`/`RecordFile` for the manifest |
| backup `xinput1_3.dll` -> `.bak`, never overwrite an existing `.bak` | `RememberDest`: plain `.bak` if none, otherwise `xinput1_3.dll.yyyymmdd-hhnnss.bak`; the backup itself is a byte copy (`CopyBytes`, not `CopyFile`, whose overwrite rule differs between Inno versions) |
| copy the 13 files, `add` only when changed | same list in `[Files]`, `BeforeInstall` remembers the hash, `AfterInstall` writes `add` |
| patch `Save\game*.sav` and `coop_profile\remote\game*.sav`, Latin-1 byte for byte, `.1p.bak` first | `PatchSaveFile` reads the file into an `AnsiString` (raw bytes), replaces MTHC -> 2CHC in place, `.1p.bak` only if it does not exist; `PatchSavesIn` for the game's `Save` folder and for `ModSaveDirOf` |
| manifest `obscoop install <ver>` / `bak` / `add` / `save` / `done`, ASCII, CRLF | identical lines in the same order, `SaveStringToFile` with CRLF, no BOM |
| uninstall.ps1: restore `bak` + `save` two-pass, ask about the saves | Inno removes what it installed; `CurUninstallStepChanged(usPostUninstall)` restores the backups, then the saves (asks interactively, restores silently) and removes the untouched imports |

Differences that are deliberate or unavoidable: Inno's own uninstaller removes every `[Files]` entry
even if its content was already identical (install.ps1 only lists `add` for changed files). For the 13
mod files that is the same end state; `obscoop.ini` is only installed when absent, so it is removed
again. The manifest format is unchanged, so `uninstall.ps1` still works on a setup-written manifest
(it ignores the new `import` lines).

## 4. The save import (the bug players hit)

At `ssPostInstall` (after the files are in place), `ImportSteamSaves`:

1. `SteamRoot` = `/FAKESTEAM=` if given, else `HKCU\Software\Valve\Steam\SteamPath`, else
   `HKLM\SOFTWARE\Valve\Steam\InstallPath`.
2. `SteamIdsWithSaves` = every `<steam>\userdata\<name>\254480\remote` that holds `game*.sav`, sorted.
   More than one -> a wizard page with one line per account plus "Do not copy any saves"
   (`CreateInputOptionPage`, default = first). `/SAVEID=<id>` picks one for automation (test only).
3. Each `game*.sav` is copied into `ModSaveDirOf({app})`: missing -> copy; identical -> nothing;
   **different -> never replaced silently** (silent install keeps the file and logs it; interactive
   install asks, default No).
4. `PatchSavesIn` then patches the copies exactly like any other save in that folder (`.1p.bak` is the
   unpatched copy of the imported bytes).
5. After the patch, `RecordImports` writes `import <rel> <sha256-of-the-file-as-installed>`.
   `<rel>` is relative to the game folder, or `~name` when the mod's save folder is the
   `%LOCALAPPDATA%` one (`ResolveManifestPath` resolves both, also in the uninstaller).

Uninstall: an `import` line is removed only while the file still has the recorded hash (and its
`.1p.bak` with it); a save the player played since is left in place and logged. The Steam originals are
read only, never renamed and never written — the test hashes the whole fake Steam tree before and after
both the install and the uninstall.

## 5. The test (tests/test_installer.sh + tests/check_installer.py)

Fake tree the script builds in `_fake/test_installer/`:

- `pkg/`: the package's text files plus stand-ins for `xinput1_3.dll`, `obscoop-relay.exe`,
  `steam_api.dll` (the installer copies bytes, so no compiler is needed)
- `game/`: `Obscure2.exe` (dummy), an old `xinput1_3.dll`, somebody else's `xinput1_3.dll.bak`, a
  `d3d9.dll`, `Save\game1.sav` (contains `MTHC` and bytes >= 0x80), and a differing
  `coop_profile\remote\game2.sav`
- `steam/`: two accounts, `111` (`game1.sav`) and `222` (`game2.sav`, `game3.sav`), each save with
  `MTHC` and non-ASCII bytes
- `game2/`: an `obscoop.ini` of the player's own; `steam-empty/`: a Steam root without userdata
- `game3/`: the exe the installer must refuse

Run 1: setup `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /FAKEHASH /SAVEID=222 /DIR=... /FAKESTEAM=...`
then the checks, then `unins000.exe /VERYSILENT ...` and the restore checks. Run 2 of the script:
`game2` with `/FAKESTEAM=steam-empty` (existing `obscoop.ini` kept, nothing imported), then its
uninstall. Run 3: the same setup without `/FAKEHASH` must refuse and change nothing.

`check_installer.py` asserts, byte for byte: every payload file; the timestamped DLL backup holds the
old DLL; the seeded `.bak` was not overwritten; `Save/game1.sav` equals the original with only
MTHC->2CHC changed, its `.1p.bak` equals the original; the imported `game3.sav` equals the Steam copy
with MTHC->2CHC (both occurrences), its `.1p.bak` equals the Steam copy; the differing `game2.sav` is
the local file (not the Steam one), patched; account 111's save is absent; the fake Steam tree is
byte-identical; the manifest is exactly the expected 20 lines in order. After the uninstall: every
original file is present and byte-identical (full-tree snapshot equality), nothing the installer added
is left, the manifest is gone, the Steam tree is still untouched.

## 6. Results (verbatim, twice; only the worktree path is abbreviated to `<worktree>` - private
paths stay out of committed files - everything else is the script's own output, fake folders only)

    $ sh tests/test_installer.sh
    test_installer: work folder _fake/test_installer
    test_installer: compiling package/obscoop2.iss with ISCC
    fixtures in <worktree>/_fake/test_installer
    all checks PASS
    snapshot <worktree>/_fake/test_installer/game: 6 file(s)
    all checks PASS
    snapshot <worktree>/_fake/test_installer/game2: 2 file(s)
    all checks PASS
    snapshot <worktree>/_fake/test_installer/steam: 6 file(s)
    all checks PASS
    snapshot <worktree>/_fake/test_installer/game3: 2 file(s)
    all checks PASS
    test_installer: installing into _fake/test_installer/game
    PASS installed README.txt is byte-identical to the package
    PASS installed VERSION.txt is byte-identical to the package
    PASS installed obscoop.ini is byte-identical to the package
    PASS installed obscoop_direct.ini.txt is byte-identical to the package
    PASS installed obscoop_o2.ipt is byte-identical to the package
    PASS installed start_guest_direct.bat is byte-identical to the package
    PASS installed start_guest_steam.bat is byte-identical to the package
    PASS installed start_host_direct.bat is byte-identical to the package
    PASS installed start_host_steam.bat is byte-identical to the package
    PASS installed xinput1_3.dll is byte-identical to the package
    PASS installed obscoop-relay/obscoop-relay.exe is byte-identical to the package
    PASS installed obscoop-relay/start_relay_guest.bat is byte-identical to the package
    PASS installed obscoop-relay/steam_api.dll is byte-identical to the package
    PASS installed obscoop-relay/steam_appid.txt is byte-identical to the package
    PASS package payload has the 14 files install.ps1 installs
    PASS the replaced xinput1_3.dll went to a timestamped .bak
    PASS the timestamped backup holds the DLL that was replaced
    PASS an existing xinput1_3.dll.bak is not overwritten
    PASS Save/game1.sav is patched MTHC -> 2CHC, every other byte kept
    PASS Save/game1.sav.1p.bak is the original save
    PASS imported game3.sav (account 222) is copied in and patched
    PASS imported game3.sav.1p.bak is the unpatched Steam copy
    PASS the other account's save (111) is not imported
    PASS a differing save already in the save folder is kept (not replaced), then patched
    PASS the kept save's own bytes are in its .1p.bak
    PASS the fake Steam folder is untouched (originals still there)
    PASS obscoop_install.txt is written
    PASS the manifest lists every added file, backup, patched save and import
    PASS the manifest lists nothing else
    PASS the manifest is in the order install.ps1 writes it
    PASS the manifest ends with 'done'
    all checks PASS
    test_installer: uninstalling
    PASS every original file is still there
    PASS every original file is back to its original bytes
    PASS nothing the installer added is left in the game folder
    PASS obscoop_install.txt is removed
    PASS the fake Steam folder is still untouched after the uninstall
    all checks PASS
    test_installer: installing into _fake/test_installer/game2 (obscoop.ini present, no Steam saves)
    PASS an existing obscoop.ini is kept (never replaced)
    PASS obscoop_install.txt is written (case 2)
    PASS the manifest does not claim it added obscoop.ini
    PASS a Steam folder without userdata imports and patches nothing
    PASS no coop_profile folder is created when there is nothing to import
    all checks PASS
    test_installer: uninstalling game2
    PASS every original file is still there
    PASS every original file is back to its original bytes
    PASS nothing the installer added is left in the game folder
    PASS obscoop_install.txt is removed
    PASS the fake Steam folder is still untouched after the uninstall
    all checks PASS
    test_installer: an Obscure2.exe that is not the supported build must be refused
    PASS the setup refused the unsupported Obscure2.exe (log: '2026-10-30 08:15:36.827   refused (silent): <worktree>\_fake\test_installer\game3')
    PASS the refused install added nothing
    PASS the refused install removed nothing
    PASS the refused install changed no file
    all checks PASS

    test_installer: PASS (install, save import, backup, uninstall, second case, refused exe)

Run B is the same script again immediately afterwards: `50 PASS, 0 FAIL`, same final line
(`test_installer: PASS (install, save import, backup, uninstall, second case, refused exe)`); only
the timestamp inside the refusal line differs. A full run takes about a minute (two installs, two
uninstalls, one refused install).

Decisive lines from the setup log of that run (`_fake/test_installer/install.log.setup`):

    saves: 2 Steam account(s) with Obscure II saves in <worktree>/_fake/test_installer/steam
    warning: d3d9.dll in the game folder (DXVK / ReShade or another wrapper)
    backup: xinput1_3.dll -> xinput1_3.dll.<timestamp>.bak
    saves: importing ...\steam\userdata\222\254480\remote -> ...\game\coop_profile\remote
    imported save game3.sav
    kept 1 save(s) that differ from the Steam copy (a silent install never overwrites one)
    patched Save\game1.sav (MTHC -> 2CHC, 1 tag(s))
    patched coop_profile\remote\game2.sav (MTHC -> 2CHC, 1 tag(s))
    patched imported game3.sav (2 tag(s); the import line covers it)
    manifest: obscoop_install.txt (20 line(s))

## 7. Release wiring

`tools/build_release.sh` (ISCC step unchanged apart from the name) now writes
`build/obscoop2-<ver>-setup.exe` next to `build/obscoop2-<ver>.zip`; `[Setup] OutputBaseFilename` is
`obscoop2-{#AppVersion}-setup`. **OBSERVED** end to end with a scratch output folder:

    zip       : <tmp>/release/obscoop2-1.0.zip
    setup     : <tmp>/release/obscoop2-1.0-setup.exe
    setup size: 2275066 bytes
    setup sha256: cf738d917dfb4604ade10cfd9167247457f8fb85d94a7eee6224c0bf0bb1dcd2

`OBSCOOP_ISCC` stays optional so a checkout without Inno Setup still builds the zip; when it is unset
the script says the setup was not built.

## 8. Not exercised / limits

- **Start-menu shortcuts** (`[Icons]`, host/guest Steam and direct, README): compiled in, but the test
  installs with `/NOICONS` so it does not write into the real Start Menu. Not observed.
- **The interactive wizard** (directory page, the `d3d9.dll` question, the "which Steam account" page,
  the "replace differing saves?" question): the page objects are created (and therefore validated) in
  the silent runs, but no one clicked them. Not observed.
- **The `Program Files` save folder** (`%LOCALAPPDATA%\obscoop\coop_profile\remote`): the test must not
  write there (it is the owner's real data folder), so that branch is DERIVED from the `ModSaveDirOf`
  rule and the source line quoted in §1, not exercised.
- **The real exe gate** cannot be tested without the real Obscure2.exe (to be kept away from): the test
  proves the *refusal* path and that `/FAKEHASH` is the only way past it; the accept path for the real
  SHA-256 is the same `CompareText(Hash, SupportedSha)` the WIP script already had.
- `install.ps1` still does not import Steam saves (the zip's manual route). INSTALL.txt tells the player
  to copy the saves by hand there; a follow-up could port `ImportSteamSaves` to PowerShell.
- Uninstall of an *imported* save is guarded by its hash: if the player played it, it stays (and the
  uninstaller logs that); the Steam original is never the thing being deleted.
