#!/usr/bin/env python3
"""Byte-level checks for tests/test_installer.sh (the Inno Setup installer of TASK I1).

Everything here works on folders the test creates under _fake/: a fake game folder (a dummy
Obscure2.exe - the installer is run with its test switch /FAKEHASH), a fake Steam root (/FAKESTEAM)
with two userdata accounts, and the package payload. No real game, Steam folder or save is touched.

    check_installer.py fixtures <work>                  create the fake folders (exact bytes below)
    check_installer.py snapshot <dir> <out.json>        every file's SHA-256, for "same bytes again"
    check_installer.py after-install <work>             install checks (files, backups, saves, manifest)
    check_installer.py after-uninstall <work> <dir> <before.json>
                                                        every original file is back, nothing extra
    check_installer.py after-install-ini <work>         case 2: an existing obscoop.ini is kept, no import
    check_installer.py unchanged <dir> <before.json>    nothing was added, removed or changed
"""

import hashlib
import json
import os
import re
import sys

# ------------------------------------------------------------------ the bytes the checks are about

GAME_EXE = b"fake Obscure2.exe (the installer runs with /FAKEHASH)\r\n"
OLD_DLL = b"OLD xinput1_3.dll 0.9\r\n\x00\xff\x7f binary tail\r\n"
OLD_BAK = b"SOMEONE ELSES BACKUP - must never be overwritten\r\n"
D3D9 = b"fake d3d9.dll wrapper\r\n"
INI_CUSTOM = b"[obscoop]\r\nROLE=host\r\n; my own settings, never replaced\r\n"

SAVE_S1 = b"SAVE-ONE \x00\x80\xfe MTHC tail \xff\x01 end"          # game\Save\game1.sav
SAVE_G2_LOCAL = b"local game2 save (differs from Steam) MTHC \x90"  # game\coop_profile\remote
SAVE_111_G1 = b"steam account 111 game1 MTHC \x91\x92"
SAVE_222_G2 = b"steam account 222 game2 MTHC \xa0"
SAVE_222_G3 = b"steam account 222 game3 MTHC and MTHC \x80"

MTHC = b"MTHC"
TWO = b"2CHC"

PAYLOAD_BINARIES = {
    "xinput1_3.dll": b"fake xinput1_3.dll payload\r\n",
    "obscoop-relay/obscoop-relay.exe": b"fake obscoop-relay.exe payload\r\n",
    "obscoop-relay/steam_api.dll": b"fake steam_api.dll payload\r\n",
}

MANIFEST = "obscoop_install.txt"
VERSION = "9.9"

FILES = ["xinput1_3.dll", "obscoop_o2.ipt", "obscoop_direct.ini.txt", "README.txt",
         "start_host_steam.bat", "start_guest_steam.bat", "start_host_direct.bat",
         "start_guest_direct.bat",
         "obscoop-relay/obscoop-relay.exe", "obscoop-relay/steam_api.dll",
         "obscoop-relay/steam_appid.txt", "obscoop-relay/start_relay_guest.bat"]


# ------------------------------------------------------------------ helpers

def patched(data):
    return data.replace(MTHC, TWO)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(path):
    with open(path, "rb") as f:
        return f.read()


def write(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def walk(root):
    """relative posix path -> full path, for every file below root"""
    found = {}
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            found[rel] = full
    return found


def snapshot(root):
    return {rel: sha(full) for rel, full in walk(root).items()}


FAILED = []


def ok(msg):
    print("PASS " + msg)


def fail(msg):
    FAILED.append(msg)
    print("FAIL " + msg)


def check(cond, msg, detail=""):
    if cond:
        ok(msg)
    else:
        fail(msg + (("  [" + detail + "]") if detail else ""))
    return cond


def check_bytes(path, expected, msg):
    if not os.path.isfile(path):
        return check(False, msg, "missing " + path)
    got = read(path)
    return check(got == expected, msg,
                 "got %d bytes %r, expected %d bytes %r" % (len(got), got[:48], len(expected), expected[:48]))


def manifest_lines(game):
    path = os.path.join(game, MANIFEST)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="ascii") as f:
        return [line.rstrip("\r\n") for line in f.read().splitlines()]


# ------------------------------------------------------------------ fixtures

def cmd_fixtures(work):
    game = os.path.join(work, "game")
    write(os.path.join(game, "Obscure2.exe"), GAME_EXE)
    write(os.path.join(game, "xinput1_3.dll"), OLD_DLL)
    write(os.path.join(game, "xinput1_3.dll.bak"), OLD_BAK)          # somebody else's backup
    write(os.path.join(game, "d3d9.dll"), D3D9)                      # the wrapper warning
    write(os.path.join(game, "Save", "game1.sav"), SAVE_S1)
    write(os.path.join(game, "coop_profile", "remote", "game2.sav"), SAVE_G2_LOCAL)

    game2 = os.path.join(work, "game2")
    write(os.path.join(game2, "Obscure2.exe"), GAME_EXE)
    write(os.path.join(game2, "obscoop.ini"), INI_CUSTOM)

    # case 3: an exe the installer must refuse (no /FAKEHASH)
    game3 = os.path.join(work, "game3")
    write(os.path.join(game3, "Obscure2.exe"), GAME_EXE)
    write(os.path.join(game3, "xinput1_3.dll"), OLD_DLL)

    steam = os.path.join(work, "steam")
    write(os.path.join(steam, "steamapps", "libraryfolders.vdf"),
          ('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
           % steam.replace("\\", "\\\\")).encode("utf-8"))
    write(os.path.join(steam, "steamapps", "appmanifest_254480.acf"),
          b'"AppState"\n{\n\t"appid"\t\t"254480"\n\t"installdir"\t\t"Obscure2"\n}\n')
    write(os.path.join(steam, "steamapps", "common", "Obscure2", "Obscure2.exe"), GAME_EXE)
    write(os.path.join(steam, "userdata", "111", "254480", "remote", "game1.sav"), SAVE_111_G1)
    write(os.path.join(steam, "userdata", "222", "254480", "remote", "game2.sav"), SAVE_222_G2)
    write(os.path.join(steam, "userdata", "222", "254480", "remote", "game3.sav"), SAVE_222_G3)

    # a Steam root with no userdata at all (case 2: nothing to import)
    empty = os.path.join(work, "steam-empty")
    os.makedirs(os.path.join(empty, "steamapps"), exist_ok=True)
    print("fixtures in " + work)


# ------------------------------------------------------------------ install checks

def cmd_after_install(work):
    game = os.path.join(work, "game")
    pkg = os.path.join(work, "pkg")
    steam = os.path.join(work, "steam")

    # 1. every payload file is there, byte for byte
    payload = walk(pkg)
    for rel, src in payload.items():
        dst = os.path.join(game, rel.replace("/", os.sep))
        if check_bytes(dst, read(src), "installed %s is byte-identical to the package" % rel):
            pass
    check(len(payload) == len(FILES) + 2,            # + obscoop.ini + VERSION.txt
          "package payload has the 14 files install.ps1 installs", str(sorted(payload)))

    # 2. the old DLL is backed up under a timestamp, the seeded .bak is untouched
    baks = [n for n in os.listdir(game)
            if re.match(r"^xinput1_3\.dll\.\d{8}-\d{6}\.bak$", n)]
    check(len(baks) == 1, "the replaced xinput1_3.dll went to a timestamped .bak", str(baks))
    if baks:
        check_bytes(os.path.join(game, baks[0]), OLD_DLL,
                    "the timestamped backup holds the DLL that was replaced")
    check_bytes(os.path.join(game, "xinput1_3.dll.bak"), OLD_BAK,
                "an existing xinput1_3.dll.bak is not overwritten")

    # 3. the game's own save: patched in place, .1p.bak = the original bytes
    check_bytes(os.path.join(game, "Save", "game1.sav"), patched(SAVE_S1),
                "Save/game1.sav is patched MTHC -> 2CHC, every other byte kept")
    check_bytes(os.path.join(game, "Save", "game1.sav.1p.bak"), SAVE_S1,
                "Save/game1.sav.1p.bak is the original save")

    # 4. the import: account 222 only, never account 111
    remote = os.path.join(game, "coop_profile", "remote")
    check_bytes(os.path.join(remote, "game3.sav"), patched(SAVE_222_G3),
                "imported game3.sav (account 222) is copied in and patched")
    check_bytes(os.path.join(remote, "game3.sav.1p.bak"), SAVE_222_G3,
                "imported game3.sav.1p.bak is the unpatched Steam copy")
    check(not os.path.exists(os.path.join(remote, "game1.sav")),
          "the other account's save (111) is not imported")
    check_bytes(os.path.join(remote, "game2.sav"), patched(SAVE_G2_LOCAL),
                "a differing save already in the save folder is kept (not replaced), then patched")
    check_bytes(os.path.join(remote, "game2.sav.1p.bak"), SAVE_G2_LOCAL,
                "the kept save's own bytes are in its .1p.bak")

    # 5. the Steam originals were only read
    before_path = os.path.join(work, "steam.before.json")
    if os.path.isfile(before_path):
        before = json.load(open(before_path))
        check(snapshot(steam) == before, "the fake Steam folder is untouched (originals still there)")

    # 6. the manifest
    lines = manifest_lines(game)
    if lines is None:
        return check(False, "obscoop_install.txt is written")
    ok("obscoop_install.txt is written")
    expected = ["obscoop install " + VERSION]
    baks = [n for n in os.listdir(game) if re.match(r"^xinput1_3\.dll\.\d{8}-\d{6}\.bak$", n)]
    expected.append("bak xinput1_3.dll " + (baks[0] if baks else "?"))
    for rel in FILES:
        expected.append("add " + rel.replace("/", "\\"))
    expected.append("add obscoop.ini")
    expected.append("add VERSION.txt")
    expected.append("save Save\\game1.sav Save\\game1.sav.1p.bak")
    expected.append("save coop_profile\\remote\\game2.sav coop_profile\\remote\\game2.sav.1p.bak")
    expected.append("import coop_profile\\remote\\game3.sav %s" % sha(os.path.join(remote, "game3.sav")))
    expected.append("done")
    missing = [l for l in expected if l not in lines]
    extra = [l for l in lines if l not in expected]
    check(not missing, "the manifest lists every added file, backup, patched save and import",
          "missing: %s" % missing)
    check(not extra, "the manifest lists nothing else", "unexpected: %s" % extra)
    check(lines == expected, "the manifest is in the order install.ps1 writes it",
          "%r != %r" % (lines, expected))
    check(lines[-1] == "done", "the manifest ends with 'done'")


# ------------------------------------------------------------------ uninstall check

def cmd_after_uninstall(work, game_arg, before_path):
    game = os.path.join(work, game_arg) if not os.path.isabs(game_arg) else game_arg
    before = json.load(open(before_path))
    after = snapshot(game)
    left = sorted(k for k in after if k not in before)
    gone = sorted(k for k in before if k not in after)
    different = sorted(k for k in before if k in after and before[k] != after[k])
    check(not gone, "every original file is still there", "missing: %s" % gone)
    check(not different, "every original file is back to its original bytes", "changed: %s" % different)
    check(not left, "nothing the installer added is left in the game folder", "left: %s" % left)
    check(not os.path.exists(os.path.join(game, MANIFEST)),
          "obscoop_install.txt is removed")
    # the fake Steam copies are still exactly as they were
    steam = os.path.join(work, "steam")
    steam_before = os.path.join(work, "steam.before.json")
    if os.path.isfile(steam_before):
        check(snapshot(steam) == json.load(open(steam_before)),
              "the fake Steam folder is still untouched after the uninstall")


# ------------------------------------------------------------------ unchanged (refused install)

def cmd_unchanged(root, before_path):
    before = json.load(open(before_path))
    after = snapshot(root)
    extra = sorted(k for k in after if k not in before)
    gone = sorted(k for k in before if k not in after)
    different = sorted(k for k in before if k in after and before[k] != after[k])
    check(not extra, "the refused install added nothing", "left: %s" % extra)
    check(not gone, "the refused install removed nothing", "missing: %s" % gone)
    check(not different, "the refused install changed no file", "changed: %s" % different)


# ------------------------------------------------------------------ case 2: an existing obscoop.ini

def cmd_after_install_ini(work):
    game = os.path.join(work, "game2")
    check_bytes(os.path.join(game, "obscoop.ini"), INI_CUSTOM,
                "an existing obscoop.ini is kept (never replaced)")
    lines = manifest_lines(game)
    if lines is None:
        return check(False, "obscoop_install.txt is written (case 2)")
    ok("obscoop_install.txt is written (case 2)")
    check("add obscoop.ini" not in lines, "the manifest does not claim it added obscoop.ini")
    check(not any(l.startswith("save ") or l.startswith("import ") for l in lines),
          "a Steam folder without userdata imports and patches nothing")
    check(not os.path.exists(os.path.join(game, "coop_profile")),
          "no coop_profile folder is created when there is nothing to import")


# ------------------------------------------------------------------ main

def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    cmd = argv[1]
    if cmd == "fixtures":
        cmd_fixtures(argv[2])
    elif cmd == "snapshot":
        root, out = argv[2], argv[3]
        with open(out, "w", encoding="ascii") as f:
            json.dump(snapshot(root), f, indent=1, sort_keys=True)
        print("snapshot %s: %d file(s)" % (root, len(json.load(open(out)))))
    elif cmd == "after-install":
        cmd_after_install(argv[2])
    elif cmd == "after-uninstall":
        cmd_after_uninstall(argv[2], argv[3], argv[4])
    elif cmd == "unchanged":
        cmd_unchanged(argv[2], argv[3])
    elif cmd == "after-install-ini":
        cmd_after_install_ini(argv[2])
    else:
        sys.exit("unknown command " + cmd)
    if FAILED:
        print("%d check(s) FAILED" % len(FAILED))
        return 1
    print("all checks PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
