# obscure2-coop

Online co-op for Obscure II (Steam, app 254480, build 215294), built on the game's own local co-op.
Sister project of [obscure-coop](https://github.com/Gyurooo/obscure-coop) (Obscure 1).

**Status: early.** Only the isolation and test-input layer exists (a proxy `xinput1_3.dll`). There is no
networking yet. Nothing here is playable online.

- `src/obscoop2.c`: proxy `xinput1_3.dll`. Keeps a test copy away from the real install and saves, offers
  virtual pads and keys through a named pipe, and lets two copies run on one PC (`OBSCOOP_MULTI=1`).
- `src/window.c`: `OBSCOOP_WINDOWED=1` puts the game in a normal window (needed for test runs: a fullscreen device is lost and minimised when the game loses the foreground).
- The game's registry key `HKCU\Software\MRS\Obscure2` is redirected to `Obscure2_coop_test`, so test runs never touch the player's settings.
- Build: `i686-w64-mingw32-gcc -O2 -shared -static -static-libgcc -o build/xinput1_3.dll src/obscoop2.c src/obscoop2.def -Wl,--kill-at -lws2_32 -ld3d9`
- Only the Steam build with `Obscure2.exe` of 3,733,504 bytes and PE timestamp 1395160951 is accepted.

No game files are shipped. MIT license.

Research notes: [coop-anything games/obscure-2](https://github.com/cranebeaker/coop-anything).
