#!/bin/sh
# tools/build_release.sh <version>
#
# Builds xinput1_3.dll (the proxy mod) and obscoop-relay.exe from source, assembles the player package,
# writes build/obscoop2-<version>.zip and - when OBSCOOP_ISCC is set - the installer
# build/obscoop2-<version>-setup.exe (next to the zip). Prints the package file list and the
# SHA-256 of both.
#
# The zip is written with sorted entries and a fixed entry timestamp, so the same sources always give
# the same file list and the same unpacked files. (The two .exe/.dll binaries themselves are not
# bit-reproducible: the linker stamps them with the build time, so the zip's own hash differs per build.)
# The file list is fixed by this script: never game files, logs, saves or test DLLs.
#
# Environment (no paths are baked into this file):
#   OBSCOOP_LLVM_MINGW  the llvm-mingw bin folder that holds i686-w64-mingw32-gcc (required)
#   OBSCOOP_STEAM_API   the 32-bit steam_api.dll the relay needs at run time (required)
#   OBSCOOP_ISCC        the Inno Setup compiler (ISCC.exe); without it no setup exe is built
#   OBSCOOP_OUT         output folder (default: <repo>/build)
#   PYTHON              interpreter for the zip + hash step (default: python)
#
# Usage:  OBSCOOP_LLVM_MINGW=... OBSCOOP_STEAM_API=... OBSCOOP_ISCC=... sh tools/build_release.sh 1.7
#
# The zip stays what it was: unpack it and run install.ps1 by hand. The setup exe is the normal way in
# for players (wizard, licence, game folder found by itself, Steam save import, save patch,
# registered uninstaller).

set -eu

VERSION=${1:-}
case "$VERSION" in
	''|*[!0-9a-zA-Z._-]*) echo "usage: sh tools/build_release.sh <version>   e.g. 1.3" >&2; exit 2 ;;
esac
if [ -z "${OBSCOOP_LLVM_MINGW:-}" ] || [ ! -x "$OBSCOOP_LLVM_MINGW/i686-w64-mingw32-gcc.exe" ]; then
	echo "set OBSCOOP_LLVM_MINGW to the llvm-mingw bin folder (it must hold i686-w64-mingw32-gcc.exe)" >&2
	exit 2
fi
if [ -z "${OBSCOOP_STEAM_API:-}" ] || [ ! -f "$OBSCOOP_STEAM_API" ]; then
	echo "set OBSCOOP_STEAM_API to the 32-bit steam_api.dll the relay runs with (Steamworks.NET standalone)" >&2
	exit 2
fi
PY=${PYTHON:-python}

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=${OBSCOOP_OUT:-$ROOT/build}
PKG=$OUT/obscoop2-$VERSION
ZIP=$OUT/obscoop2-$VERSION.zip
GCC=$OBSCOOP_LLVM_MINGW/i686-w64-mingw32-gcc.exe

echo "obscoop release $VERSION"
echo "  source: $ROOT"
echo "  output: $PKG"

# ---------------------------------------------------------------- clean slate (only our own output)
if [ -d "$PKG" ]; then rm -rf "$PKG"; fi
if [ -f "$ZIP" ]; then rm -f "$ZIP"; fi
mkdir -p "$PKG/obscoop-relay"

# ---------------------------------------------------------------- 1. the mod DLL
WLOG=$OUT/build-$VERSION-dll.log
"$GCC" -O2 -Wall -shared -static -static-libgcc \
	-o "$PKG/xinput1_3.dll" "$ROOT/src/obscoop2.c" "$ROOT/src/obscoop2.def" \
	-Wl,--kill-at -lws2_32 -ld3d9 2> "$WLOG"
WARN=$(grep -c 'warning:' "$WLOG" || true)
if [ "$WARN" -gt 3 ]; then
	echo "the DLL build produced $WARN warnings (3 are known: tick, watch_start, request_shot):" >&2
	cat "$WLOG" >&2
	exit 1
fi
echo "  dll    : xinput1_3.dll ($WARN known warning(s))"

# ---------------------------------------------------------------- 2. the relay
"$GCC" -O2 -Wall -static -o "$PKG/obscoop-relay/obscoop-relay.exe" "$ROOT/relay/relay.c" -lws2_32 2>> "$WLOG"
RLWARN=$(grep -c 'warning:' "$WLOG" || true)
if [ "$RLWARN" -gt 3 ]; then
	echo "warnings outside the three known DLL ones:" >&2
	cat "$WLOG" >&2
	exit 1
fi
echo "  relay  : obscoop-relay/obscoop-relay.exe"

# ---------------------------------------------------------------- 3. the player files
for f in INSTALL.txt README.txt install.ps1 uninstall.ps1 obscoop.ini obscoop_direct.ini.txt \
	obscoop_o2.ipt start_host_steam.bat start_guest_steam.bat start_host_direct.bat start_guest_direct.bat \
	obscoop-relay/start_relay_guest.bat obscoop-relay/steam_appid.txt; do
	if [ ! -f "$ROOT/package/$f" ]; then
		echo "package/$f is missing" >&2
		exit 1
	fi
	cp "$ROOT/package/$f" "$PKG/$f"
done
cp "$OBSCOOP_STEAM_API" "$PKG/obscoop-relay/steam_api.dll"
printf '%s\n' "$VERSION" > "$PKG/VERSION.txt"

# ---------------------------------------------------------------- 4. the file list is fixed
EXPECTED='INSTALL.txt
README.txt
VERSION.txt
install.ps1
obscoop-relay/obscoop-relay.exe
obscoop-relay/start_relay_guest.bat
obscoop-relay/steam_api.dll
obscoop-relay/steam_appid.txt
obscoop.ini
obscoop_direct.ini.txt
obscoop_o2.ipt
start_guest_direct.bat
start_guest_steam.bat
start_host_direct.bat
start_host_steam.bat
uninstall.ps1
xinput1_3.dll'
ACTUAL=$(cd "$PKG" && find . -type f | sed 's|^\./||' | LC_ALL=C sort)
if [ "$ACTUAL" != "$EXPECTED" ]; then
	echo "the package file list changed - update EXPECTED in this script if that is intended:" >&2
	echo "--- expected" >&2; echo "$EXPECTED" >&2
	echo "--- actual" >&2; echo "$ACTUAL" >&2
	exit 1
fi

# ---------------------------------------------------------------- 5. the zip (sorted, fixed timestamps)
"$PY" - "$PKG" "$ZIP" <<'PY'
import hashlib, os, sys, zipfile
pkg, out = sys.argv[1], sys.argv[2]
names = []
for root, dirs, files in os.walk(pkg):
    dirs.sort()
    for f in sorted(files):
        names.append(os.path.relpath(os.path.join(root, f), pkg).replace(os.sep, '/'))
names.sort()
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for name in names:
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        with open(os.path.join(pkg, name), 'rb') as f:
            z.writestr(info, f.read())
PY

# ---------------------------------------------------------------- 6. the setup exe (Inno Setup)
# package/obscoop2.iss packs the files above into the wizard. Only the version comes from here; the
# payload is $PKG, so the setup installs exactly what is in the zip (plus obscoop.ini, and with the
# same "never replace the player's settings" rule install.ps1 uses).
SETUP=$OUT/obscoop2-$VERSION-setup.exe
if [ -n "${OBSCOOP_ISCC:-}" ]; then
	if [ ! -f "$OBSCOOP_ISCC" ]; then
		echo "OBSCOOP_ISCC is set but there is no such file: $OBSCOOP_ISCC (point it at ISCC.exe)" >&2
		exit 2
	fi
	for f in obscoop2.iss LICENSE.txt; do
		if [ ! -f "$ROOT/package/$f" ]; then
			echo "package/$f is missing" >&2
			exit 1
		fi
	done
	if [ -f "$SETUP" ]; then rm -f "$SETUP"; fi
	echo ""
	echo "setup exe: Inno Setup"
	# ISCC wants Windows paths; this line is a no-op on a machine without cygpath.
	winpath() { if command -v cygpath > /dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
	ISCLOG=$OUT/build-$VERSION-iss.log
	if ! "$OBSCOOP_ISCC" --define="AppVersion=$VERSION" --define="PkgDir=$(winpath "$PKG")" \
		--output-dir="$(winpath "$OUT")" "$(winpath "$ROOT/package/obscoop2.iss")" > "$ISCLOG" 2>&1; then
		cat "$ISCLOG" >&2
		echo "ISCC failed (full log: $ISCLOG)" >&2
		exit 1
	fi
	if grep -qi '^Warning:' "$ISCLOG"; then
		echo "ISCC printed warnings - look at $ISCLOG" >&2
		grep -i -A1 '^Warning:' "$ISCLOG" >&2
		exit 1
	fi
	if [ ! -f "$SETUP" ]; then
		cat "$ISCLOG" >&2
		echo "ISCC did not produce $SETUP" >&2
		exit 1
	fi
	echo "  setup  : obscoop2-$VERSION-setup.exe"
else
	echo ""
	echo "OBSCOOP_ISCC is not set: the setup exe was not built (the zip installs by hand with install.ps1)"
fi

# ---------------------------------------------------------------- 7. report
echo ""
echo "package obscoop2-$VERSION ($PKG):"
echo "$ACTUAL" | while read -r f; do
	printf '  %10s  %s\n' "$(wc -c < "$PKG/$f" | tr -d ' ')" "$f"
done
echo ""
"$PY" - "$ZIP" <<'PY'
import hashlib, os, sys
p = sys.argv[1]
h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
print("zip       : %s" % os.path.abspath(p))
print("zip size  : %d bytes" % os.path.getsize(p))
print("zip sha256: %s" % h)
PY
if [ -f "$SETUP" ]; then
	"$PY" - "$SETUP" <<'PY'
import hashlib, os, sys
p = sys.argv[1]
h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
print("setup     : %s" % os.path.abspath(p))
print("setup size: %d bytes" % os.path.getsize(p))
print("setup sha256: %s" % h)
print("")
print("Give players the setup exe (%s bytes) and its SHA-256." % os.path.getsize(p))
print("The zip is the manual route (unpack, install.ps1).")
PY
fi
