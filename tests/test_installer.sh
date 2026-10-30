#!/bin/sh
# tests/test_installer.sh - build the Inno Setup installer and exercise it silently on fake folders.
#
#   sh tests/test_installer.sh
#
# What it does, with no real game, Steam folder or save anywhere near it (TASK I1 forbids touching
# them, and forbids starting the game):
#   1. builds the payload folder _fake/test_installer/pkg (the package's text files + stand-ins for the
#      three binaries) and compiles package/obscoop2.iss with ISCC into _fake/test_installer/out
#   2. creates a fake game folder and a fake Steam root (_fake/test_installer/...): two userdata
#      accounts with Obscure II saves, a pre-existing xinput1_3.dll (+ somebody else's .bak), a d3d9.dll,
#      a game save and a differing save already in the mod's save folder
#   3. runs the setup SILENTLY (/VERYSILENT /SUPPRESSMSGBOXES /NOICONS /FAKEHASH /FAKESTEAM=...
#      /SAVEID=222) and checks every copied file, the backup, both patched saves, the imported save,
#      the untouched Steam originals and obscoop_install.txt byte for byte (tests/check_installer.py)
#   4. runs the uninstaller SILENTLY and checks every original file is byte-identical again and nothing
#      the installer added (or imported) is left
#   5. a second, smaller case: an existing obscoop.ini is kept and a Steam root without userdata
#      imports nothing; then the same uninstall check
#
# Env: OBSCOOP_ISCC (default: ../tools/innosetup/ISCC.exe next to this worktree), PYTHON (default: python).
# Every external command has a timeout; a hang is reported with the tail of its log.

set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$ROOT/_fake/test_installer
PY=${PYTHON:-python}
ISCC=${OBSCOOP_ISCC:-$(cd "$ROOT/.." && pwd)/tools/innosetup/ISCC.exe}
VERSION=9.9
SETUP=$WORK/out/obscoop2-$VERSION-setup.exe

win() { if command -v cygpath > /dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi }

fail() {
	echo "FAIL: $*" >&2
	exit 1
}

# Run a Windows exe with Git Bash out of the way (it turns /VERYSILENT into a path) and a timeout.
run_exe() {
	name=$1
	log=$2
	shift 2
	if MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' timeout 240 "$@" > "$log" 2>&1; then
		return 0
	fi
	rc=$?
	taskkill //F //IM "$name" > /dev/null 2>&1 || true
	echo "FAIL: $name exited with $rc (124 = timeout); tail of $log:" >&2
	tail -20 "$log" >&2 || true
	exit 1
}

check() {
	"$PY" "$ROOT/tests/check_installer.py" "$@" || fail "check_installer.py $* reported a failure"
}

# Inno's uninstaller hands the work to a second phase and its first phase returns early: wait for the
# work itself (the manifest goes last) instead of guessing.
wait_gone() {
	path=$1
	secs=$2
	i=0
	while [ -e "$path" ] && [ $i -lt $((secs * 4)) ]; do
		sleep 0.25
		i=$((i + 1))
	done
	[ -e "$path" ] && return 1
	return 0
}

# A command that must FAIL (the setup has to refuse an Obscure2.exe it does not know).
run_exe_expect_fail() {
	name=$1
	log=$2
	shift 2
	if MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' timeout 240 "$@" > "$log" 2>&1; then
		taskkill //F //IM "$name" > /dev/null 2>&1 || true
		fail "$name did not refuse (it exited 0); log: $log"
	fi
	return 0
}

[ -f "$ISCC" ] || fail "no ISCC at $ISCC (set OBSCOOP_ISCC to ISCC.exe, Inno Setup 6/7)"
[ -f "$ROOT/package/obscoop2.iss" ] || fail "package/obscoop2.iss is missing"

echo "test_installer: work folder _fake/test_installer"
rm -rf "$WORK"
mkdir -p "$WORK/pkg/obscoop-relay" "$WORK/out"

# ---------------------------------------------------------------- 1. the payload the setup packs
for f in obscoop.ini obscoop_direct.ini.txt obscoop_o2.ipt README.txt \
	obscoop-relay/start_relay_guest.bat obscoop-relay/steam_appid.txt \
	start_host_steam.bat start_guest_steam.bat start_host_direct.bat start_guest_direct.bat; do
	[ -f "$ROOT/package/$f" ] || fail "package/$f is missing"
	cp "$ROOT/package/$f" "$WORK/pkg/$f"
done
printf 'fake xinput1_3.dll payload\r\n' > "$WORK/pkg/xinput1_3.dll"
printf 'fake obscoop-relay.exe payload\r\n' > "$WORK/pkg/obscoop-relay/obscoop-relay.exe"
printf 'fake steam_api.dll payload\r\n' > "$WORK/pkg/obscoop-relay/steam_api.dll"
printf '%s\n' "$VERSION" > "$WORK/pkg/VERSION.txt"

echo "test_installer: compiling package/obscoop2.iss with ISCC"
if ! MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' timeout 240 "$ISCC" \
	--define="AppVersion=$VERSION" --define="PkgDir=$(win "$WORK/pkg")" \
	--output-dir="$(win "$WORK/out")" "$(win "$ROOT/package/obscoop2.iss")" \
	> "$WORK/iscc.log" 2>&1; then
	tail -20 "$WORK/iscc.log" >&2 || true
	fail "ISCC could not build the setup exe"
fi
grep -qi '^Warning:' "$WORK/iscc.log" && fail "ISCC printed warnings (see _fake/test_installer/iscc.log)"
[ -f "$SETUP" ] || fail "ISCC produced no $SETUP"

# ---------------------------------------------------------------- 2. the fake folders
check fixtures "$WORK"
check snapshot "$WORK/game" "$WORK/game.before.json"
check snapshot "$WORK/game2" "$WORK/game2.before.json"
check snapshot "$WORK/steam" "$WORK/steam.before.json"
check snapshot "$WORK/game3" "$WORK/game3.before.json"

# ---------------------------------------------------------------- 3. install (silent)
echo "test_installer: installing into _fake/test_installer/game"
run_exe "obscoop2-$VERSION-setup.exe" "$WORK/install.log" "$SETUP" \
	/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /FAKEHASH /SAVEID=222 \
	"/DIR=$(win "$WORK/game")" "/FAKESTEAM=$(win "$WORK/steam")" \
	"/LOG=$(win "$WORK/install.log.setup")"
check after-install "$WORK"

# ---------------------------------------------------------------- 4. uninstall
echo "test_installer: uninstalling"
[ -f "$WORK/game/unins000.exe" ] || fail "the installer registered no uninstaller"
run_exe "unins000.exe" "$WORK/uninstall.log" "$WORK/game/unins000.exe" \
	/VERYSILENT /SUPPRESSMSGBOXES /NORESTART \
	"/LOG=$(win "$WORK/uninstall.log.unins")"
wait_gone "$WORK/game/obscoop_install.txt" 60 || fail "the uninstaller did not finish (see _fake/test_installer/uninstall.log.unins)"
wait_gone "$WORK/game/unins000.exe" 20 || fail "unins000.exe is still there after the uninstall"
check after-uninstall "$WORK" game "$WORK/game.before.json"

# ---------------------------------------------------------------- 5. case 2: obscoop.ini kept, no saves
echo "test_installer: installing into _fake/test_installer/game2 (obscoop.ini present, no Steam saves)"
run_exe "obscoop2-$VERSION-setup.exe" "$WORK/install2.log" "$SETUP" \
	/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS /FAKEHASH \
	"/DIR=$(win "$WORK/game2")" "/FAKESTEAM=$(win "$WORK/steam-empty")" \
	"/LOG=$(win "$WORK/install2.log.setup")"
check after-install-ini "$WORK"

echo "test_installer: uninstalling game2"
run_exe "unins000.exe" "$WORK/uninstall2.log" "$WORK/game2/unins000.exe" \
	/VERYSILENT /SUPPRESSMSGBOXES /NORESTART \
	"/LOG=$(win "$WORK/uninstall2.log.unins")"
wait_gone "$WORK/game2/obscoop_install.txt" 60 || fail "the uninstaller did not finish (see _fake/test_installer/uninstall2.log.unins)"
wait_gone "$WORK/game2/unins000.exe" 20 || fail "unins000.exe is still there after the uninstall (case 2)"
check after-uninstall "$WORK" game2 "$WORK/game2.before.json"

# ---------------------------------------------------------------- 6. case 3: an unknown exe is refused
echo "test_installer: an Obscure2.exe that is not the supported build must be refused"
run_exe_expect_fail "obscoop2-$VERSION-setup.exe" "$WORK/refused.log" "$SETUP" \
	/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOICONS \
	"/DIR=$(win "$WORK/game3")" "/FAKESTEAM=$(win "$WORK/steam")" \
	"/LOG=$(win "$WORK/refused.log.setup")"
grep -q "refused (silent):" "$WORK/refused.log.setup" || fail "the setup did not log that it refused the exe"
echo "PASS the setup refused the unsupported Obscure2.exe (log: '$(grep -m1 'refused (silent):' "$WORK/refused.log.setup" | sed 's/^.*refused:/refused:/')')"
check unchanged "$WORK/game3" "$WORK/game3.before.json"

echo ""
echo "test_installer: PASS (install, save import, backup, uninstall, second case, refused exe)"
