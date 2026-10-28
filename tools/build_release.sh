#!/bin/sh
# tools/build_release.sh <version>
#
# Builds xinput1_3.dll (the proxy mod) and obscoop-relay.exe from source, assembles the player package
# and writes build/obscoop2-<version>.zip. Prints the package file list and the zip's SHA-256.
#
# The zip is written with sorted entries and a fixed entry timestamp, so the same sources always give
# the same file list and the same unpacked files. (The two .exe/.dll binaries themselves are not
# bit-reproducible: the linker stamps them with the build time, so the zip's own hash differs per build.)
# The file list is fixed by this script: never game files, logs, saves or test DLLs.
#
# Environment (no paths are baked into this file):
#   OBSCOOP_LLVM_MINGW  the llvm-mingw bin folder that holds i686-w64-mingw32-gcc (required)
#   OBSCOOP_STEAM_API   the 32-bit steam_api.dll the relay needs at run time (required)
#   OBSCOOP_OUT         output folder (default: <repo>/build)
#   PYTHON              interpreter for the zip + hash step (default: python)
#
# Usage:  OBSCOOP_LLVM_MINGW=... OBSCOOP_STEAM_API=... sh tools/build_release.sh 1.3

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

# ---------------------------------------------------------------- 6. report
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
