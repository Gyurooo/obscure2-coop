# FINDINGS 32 — installer, player guide, release script (TASK 32)

Base: `0c2d669` (protocol 17). No game source (`src/`, `relay/`) was changed by this task.
Labels: **OBSERVED** = printed by a run in this task or read in the source with a file:line;
**DERIVED** = follows from that code but was not exercised; **GUESS**; **UNKNOWN**.

## 0. What was added

| item | state |
|---|---|
| `tools/build_release.sh <version>` | new: builds `xinput1_3.dll` + `obscoop-relay.exe` from source, assembles `build/obscoop2-<version>/`, writes the zip (sorted entries, fixed entry timestamps) and prints the file list + SHA-256. Toolchain and `steam_api.dll` come from env vars, no absolute user path in the file |
| `package/` | new in the repo: the player-facing sources (see §2) |
| `package/install.ps1` | rewritten: exe SHA-256 gate, backup that never overwrites an existing backup, DXVK/ReShade warning, save patch with backups, manifest of everything it added |
| `package/uninstall.ps1` | new: undoes exactly the manifest (added files first, then the backups) |
| `README.md` | status table (feature / state / how it was tested, every row citing a check and a FINDINGS file), source map, build, how to run the tests |
| `tests/README.md` | all 15 runners, 19 checks and the helper tools with one line each, plus the test-only switches |

## 1. The one open question: LAN / direct IP (**OBSERVED**, decided as "document the truth")

`src/net.c:687` binds the UDP socket to `INADDR_LOOPBACK` ("loopback only: udp is the one-PC test
transport"), so a direct-IP join between two PCs **does not exist** in this build. Two PCs only ever meet
through Steam: the relay (`obscoop-relay.exe host|guest`, plain UDP to 127.0.0.1 next to the game) or
the direct Steam P2P transport (`OBSCOOP_NET=steam`).

The task asked INSTALL.txt to explain joining "over LAN/direct". Two options were real: document the
truth, or add an opt-in LAN bind (`OBSCOOP_LAN=1` for the host, all interfaces for a non-loopback peer)
and ship LAN batch files. That is the owner's call. This run had no interactive user (the ask was
refused as unsafe to answer for them), so the **reversible** option was taken: no network code was
touched and the player files say plainly that there is no direct-IP/LAN mode, with the two Steam routes
documented instead (`package/README.txt`, "There is no direct-IP / LAN mode in this build").
If the owner wants LAN, the change is ~4 lines in `net.c` plus one .bat file and a live test between two
machines - it is listed under NOT DONE below.

## 2. The package (`package/`)

| file | why |
|---|---|
| `INSTALL.txt` | what it is, same version on both sides, install steps, what the installer does line by line, uninstall |
| `README.txt` | what it is, the real flow (main menu -> host loads -> guest follows), joining via the Steam relay, joining via the direct Steam link, the LAN statement, sync/not-synced, known issues, how to report a bug (obscoop.log), uninstall pointer |
| `install.ps1` | the installer (below) |
| `uninstall.ps1` | the uninstaller (below) |
| `obscoop.ini` | settings template: `LOCAL_PAD`, `HIDE_REAL_PADS`, `WINDOWED`, `CAMERA`, with `ROLE`/`NET`/`UDP`/`PEER`/`HOST_*` documented as comments (the .bat files set those) |
| `obscoop_direct.ini.txt` | the direct-Steam template to rename to `obscoop.ini` |
| `obscoop_o2.ipt` | the gamepad input map the mod seeds into `coop_profile\remote\o2.ipt` (`src/obscoop2.c:1704-1713`); unchanged from the 1.2 package |
| `start_host_steam.bat` / `start_guest_steam.bat` | relay + game, the recommended route; the relay is started **before** `SteamAppId` is set so it sees app 480 while the game sees 254480 |
| `start_host_direct.bat` / `start_guest_direct.bat` | Steam P2P without the relay; the guest takes the host's id or name from `host.txt` |
| `obscoop-relay/start_relay_guest.bat` | the guest relay alone, for a game started from Steam's own Play button |
| `obscoop-relay/steam_appid.txt` | `480` (Spacewar) - the relay's app id |
| `VERSION.txt` | written by the build script, read by install.ps1 (`unknown` otherwise) |

Not shipped: game files, saves, logs, `obscoop_levels.txt` (the mod creates it itself, `src/hooks.c:52-68`),
test DLLs, and `steam_api.dll` (third-party, taken from `OBSCOOP_STEAM_API` at build time).

## 3. install.ps1 / uninstall.ps1

**OBSERVED** in the run below:

| step | what it does |
|---|---|
| exe gate | `Get-FileHash Obscure2.exe` against `003f195b...9354` (Steam build 215294, 3733504 bytes); a mismatch **refuses** with expected/found, the reason (widescreen patch / crack / repack) and the Steam "verify files" advice, exit 2, nothing written |
| wrappers | warns when `d3d9.dll` or `dxgi.dll` is next to the exe ("untested with the mod") |
| backup | an existing `xinput1_3.dll` goes to `xinput1_3.dll.bak`; if a `.bak` is already there it is **left alone** and the current DLL goes to `xinput1_3.dll.<stamp>.bak` instead, so the replaced file is always recoverable |
| files | 14 files copied (DLL, ipt, both ini templates, README, VERSION, 4 .bat, the 4 relay files); `obscoop.ini` only when the folder has none (a player's own settings are never replaced) |
| saves | `Save\game*.sav` **and** `coop_profile\remote\game*.sav`: `MTHC` -> `2CHC` (the partner controller), `.1p.bak` before the first patch. Latin-1 (codepage 28591) is a byte-for-byte encoding, so the 2657-2971 bytes above 0x7f in these saves survive; the old script's `[Text.Encoding]::ASCII` would have turned every one of them into `?` |
| manifest | `obscoop_install.txt`: `bak <file> <backup>`, `add <file>`, `save <file> <backup>`, `done` |
| uninstall | reads the manifest: removes the `add` files first, then restores `bak` and `save` backups (a single pass in manifest order would restore the original DLL and delete it again - that bug was found and fixed by this test), deletes the manifest and the relay folder when it is empty, and names `obscoop.log`, `obscoop_levels.txt`, `coop_profile\` as deliberately left behind |

### Live run on a COPY of a test game folder (`%TMPDIR%\instest`, never the owner's install)

The copy held `Obscure2.exe` (the test copy's, unmodified), `Save\game0.sav`, `Save\game1.sav` (rewritten to
store `MTHC`, i.e. an untouched save), a pre-existing `xinput1_3.dll` (a dummy), a `d3d9.dll` (a dummy),
`my-notes.txt` and `obscoop_levels.txt`.

```
$ powershell -NoProfile -ExecutionPolicy Bypass -File <pkg>\install.ps1 "<copy>"
Obscure II co-op 1.3 - installer
  package: ...\release\obscoop2-1.3
  game   : ...\instest
  exe    : Steam build 215294, SHA-256 matches, 3733504 bytes

  WARNING: d3d9.dll is in the game folder (DXVK, ReShade or another wrapper). The mod is
           untested with it. If the game does not start, or the link stays on 'waiting',
           remove that file and try again.
  backup : xinput1_3.dll -> xinput1_3.dll.bak
  copy     xinput1_3.dll
  copy     obscoop_o2.ipt
  copy     obscoop_direct.ini.txt
  copy     README.txt
  copy     start_host_steam.bat
  copy     start_guest_steam.bat
  copy     start_host_direct.bat
  copy     start_guest_direct.bat
  copy     obscoop-relay\obscoop-relay.exe
  copy     obscoop-relay\steam_api.dll
  copy     obscoop-relay\steam_appid.txt
  copy     obscoop-relay\start_relay_guest.bat
  copy     obscoop.ini (new; an existing obscoop.ini is never replaced)
  copy     VERSION.txt
  patch    Save\game1.sav (MTHC -> 2CHC, backup .1p.bak)

Installed: 14 file(s) copied, 1 save(s) patched.
The list of what was changed is in obscoop_install.txt; uninstall.ps1 undoes exactly that.
...
INSTALL EXIT=0

$ powershell -NoProfile -ExecutionPolicy Bypass -File <pkg>\uninstall.ps1 "<copy>"
Obscure II co-op - uninstall
  game: ...\instest
  remove   xinput1_3.dll
  remove   obscoop_o2.ipt
  remove   obscoop_direct.ini.txt
  remove   README.txt
  remove   start_host_steam.bat
  remove   start_guest_steam.bat
  remove   start_host_direct.bat
  remove   start_guest_direct.bat
  remove   obscoop-relay\obscoop-relay.exe
  remove   obscoop-relay\steam_api.dll
  remove   obscoop-relay\steam_appid.txt
  remove   obscoop-relay\start_relay_guest.bat
  remove   obscoop.ini
  remove   VERSION.txt
  restore  xinput1_3.dll  (from xinput1_3.dll.bak)
  restore  Save\game1.sav  (the save the installer patched)
  remove   obscoop-relay\ (empty)

Removed 14 file(s), restored 2 backup(s).
Left in place (the mod writes these while it runs, delete them if you want them gone):
  obscoop.log, obscoop_levels.txt, coop_profile\ (the mod's own save folder)
UNINSTALL EXIT=0
```

Before / after: the folder is back to its original state, file list and hashes identical.

```
--- before ---                                            --- after ---
003f195b...9354 *./Obscure2.exe                          003f195b...9354 *./Obscure2.exe
fedd47f3...7bc2 *./Save/game0.sav                        fedd47f3...7bc2 *./Save/game0.sav
183748f6...2a2c *./Save/game1.sav                        183748f6...2a2c *./Save/game1.sav
2c3a1e59...bb23 *./d3d9.dll                              2c3a1e59...bb23 *./d3d9.dll
037fd8a0...e4de5 *./my-notes.txt                         037fd8a0...e4de5 *./my-notes.txt
9c0cc766...a2d7 *./obscoop_levels.txt                    9c0cc766...a2d7 *./obscoop_levels.txt
36da9d47...c6f0 *./xinput1_3.dll                         36da9d47...c6f0 *./xinput1_3.dll
--- diff ---
FOLDER IDENTICAL (same files, same hashes)
dirs: instest, instest/Save   (no obscoop-relay left)
```

### The refusal (a modified exe)

One byte of a second copy's `Obscure2.exe` was changed (`sha256 da76c9bc...a2a0`, same size):

```
Obscure II co-op 1.3 - installer
  package: ...
  game   : ...\refuse

REFUSED: this Obscure2.exe is not the supported Steam build.
  expected SHA-256 003f195b0e5bff91682f7e436cfe8213b6ca53803e17e98cdb5acd2103769354  (3733504 bytes)
  found    SHA-256 da76c9bc71b155af93ba018b530bf45db8889cb64e80081aca9be3ae2730c2a0  (3733504 bytes)

The mod is written for Steam build 215294 and hooks that exact code. A widescreen patch, a
no-CD crack or a repack changes it and the mod would not work (it refuses to start).
Fix the game first: Steam -> Library -> right-click Obscure II -> Properties -> Installed
files -> Verify integrity of game files. Nothing was changed by this installer.
INSTALL EXIT=2
what it left: Obscure2.exe, Save   (nothing added)
```

`uninstall.ps1` without a manifest refuses too and lists what to delete by hand (**OBSERVED**).

## 4. Release build

```
$ OBSCOOP_LLVM_MINGW=<llvm-mingw bin> OBSCOOP_STEAM_API=<steam_api.dll> sh tools/build_release.sh 1.3
obscoop release 1.3
  source: <worktree>
  output: <tmp>/release/obscoop2-1.3
  dll    : xinput1_3.dll (3 known warning(s))
  relay  : obscoop-relay/obscoop-relay.exe

package obscoop2-1.3:
        2756  INSTALL.txt
        5641  README.txt
           4  VERSION.txt
        8542  install.ps1
       82944  obscoop-relay/obscoop-relay.exe
         910  obscoop-relay/start_relay_guest.bat
      274584  obscoop-relay/steam_api.dll
           3  obscoop-relay/steam_appid.txt
        1279  obscoop.ini
         879  obscoop_direct.ini.txt
         724  obscoop_o2.ipt
        1046  start_guest_direct.bat
        1239  start_guest_steam.bat
         598  start_host_direct.bat
         969  start_host_steam.bat
        3420  uninstall.ps1
      202240  xinput1_3.dll

zip       : <tmp>/release/obscoop2-1.3.zip
zip size  : 275345 bytes
zip sha256: dea31b9988defa3ff7d361a7b135c88c0876e31b2dd1f27a8207efd586f07159
```

- `obscoop-relay.exe` is 82,944 bytes, the same size as the one in the 1.2 package - the relay source is
  unchanged and rebuilds identically in size (**OBSERVED**).
- The DLL build prints exactly the 3 known warnings (`tick`, `watch_start`, `request_shot`); the script
  fails on any extra one (**OBSERVED**).
- Two builds from the same sources produce the same 17-entry file list (**OBSERVED**), but **not** the same
  zip bytes: the linker stamps both binaries with the build time (275146 / 275148 / 275279 / 275345 bytes over
  four runs, the last two after the `uninstall.ps1` and `install.ps1` fixes). Only the file list is reproducible, which is
  what the task asked for; the script's comment says so.

## 5. Smoke test on the packaged DLL

`sh tests/run_pair_menu.sh <packaged xinput1_3.dll> check_party.py check_items.py check_hands.py check_entities.py`
- 2 game processes, foreground, stopped by the runner. Verbatim (middle of the log trimmed, checks
untouched):

```
host pid 27324 guest pid 41064 running [27324, 41064]
== both at the main menu; the host loads save 01 with the game's own LoadByName
guest sync after the transfer wait: ... | saves_done 1 | real load stag
host loadsave game0.sav -> ok real load of "game0.sav" requested (the game thread runs it)
ok: the host in a level after 0.5 s
host after load: mode 1 world 0x1971a550 level I100 humans 2
ok: the guest in the same level (it loads the save itself) after 0.0 s
guest after load: mode 1 world 0x191520f8 level I100 humans 2
  19:02:38.089 [26160] guest: the world this copy built from the save itself is up (level I100, 94 ms after the load)
== check_party.py
party: host ['BOY1', 'GIR1'] guest ['BOY1', 'GIR1'] | inventory: host 44 guest 44
party OK
== check_items.py
items: before host 44 guest 44
items: after host 45 guest 45
items OK
== check_hands.py
in hand: host [('BOY1', 'CBOW'), ('GIR1', 'CSAW')] guest [('BOY1', 'CBOW'), ('GIR1', 'CSAW')]
hands OK (2 characters checked)
== check_entities.py
entity count: host 43 guest 43
entities OK (host 43, guest 43)
still running: []
OWNER FILES UNCHANGED (apart from Steam remotecache.vdf)
RUNNER EXIT=0
```

(The `check_hands.py` line `inventory: host 44 guest 45` is `check_items.py`'s extra item on both copies,
not a mismatch; the check's own assertion is the hands table and it passed.)

The DLL in the final zip was built from the same sources and the same command; the only file that changed
after the smoke run is `uninstall.ps1` (PowerShell), which the run does not use. **DERIVED**, not re-run
(the task allows one smoke run and 4 game processes; 2 were used).

## 6. DONE / NOT DONE / UNKNOWN

**DONE**
- `tools/build_release.sh <version>`: builds the DLL and the relay from source, fixed file list, zip +
  SHA-256 printed; env vars for the toolchain and `steam_api.dll`; no absolute user path in the file.
- `package/`: INSTALL.txt, README.txt, install.ps1, uninstall.ps1, obscoop.ini, obscoop_direct.ini.txt,
  obscoop_o2.ipt, four `start_*.bat`, the relay folder's own guest launcher and app id.
- install.ps1: exe hash gate (refuses, exit 2), non-clobbering backup, DXVK warning, Latin-1 save patch
  with `.1p.bak`, manifest. uninstall.ps1: manifest-driven, folder verified identical afterwards.
- README.md status table (feature / state / how tested) + build + test sections; tests/README.md with
  one line for every runner, every check and every helper tool.
- Smoke test on the packaged DLL: 4 checks OK, RUNNER EXIT=0, no process left running.

**NOT DONE**
- **A direct-IP / LAN transport.** Not implemented in this build (`src/net.c:687`), and adding one was
  the owner's decision (see §1). The docs state it plainly instead of advertising it.
- `steam_api.dll` is not in the repo (third-party binary); the build script needs `OBSCOOP_STEAM_API`.
- The two Steam routes (relay and direct P2P) were **not** run between two Steam accounts in this task -
  no second account on this machine.

**UNKNOWN**
- Whether the shipped relay batch files work end to end against real Steam (the relay code is unchanged
  since the `--udp-link` chaos runs; the .bat files around it are new and only syntax-checked).
- Whether `obscoop.ini` being shipped with `ROLE` commented out confuses a player who starts the game
  from Steam's Play button (they get a game without co-op and no error); README.txt says it, but it was
  not seen with a real player.
- How the installer behaves under a non-Administrator account against `C:\Program Files` (the mod itself
  redirects its writes to `%LOCALAPPDATA%\obscoop`, `src/obscoop2.c:1684-1700`; the installer was only
  run against a folder in `%TEMP%`).
