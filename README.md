# obscure2-coop

Online co-op for Obscure II (Steam, app 254480, build 215294), built on the game's own local co-op.
Sister project of [obscure-coop](https://github.com/Gyurooo/obscure-coop) (Obscure 1).

**Status: prototype (1.1).** Two copies on one PC (UDP loopback) stay in sync for movement, level changes, prompts,
subtitles, door transitions, saves, items and health. A save loads on both copies (the guest's own save load now
changes the level); a dead player 1 hands the host pad to the alive partner; the 44-item inventory and every change are
mirrored to the guest; each character's life is in the state snapshot and applied on the guest. The host's snapshot
repeats the host's pad and camera angle (protocol 4); START on either controller pauses both copies; the "Player 2 is
joining" dialog is auto-accepted; free look is local; the test-only level guard (0.9) refuses guessed level tags. An
idle second player no longer walks off (0.7 catch-up hook). The Steam transport is ported but still untested;
unattached AI controllers expose no character health. Not playable online yet (loopback tested).

- `src/obscoop2.c`: proxy `xinput1_3.dll`. Keeps a test copy away from the real install and saves, offers
  virtual pads and keys through a named pipe, and lets two copies run on one PC (`OBSCOOP_MULTI=1`).
- `src/net.c`, `src/sync.c` also carry the host's pad and camera yaw inside the state snapshot (protocol 4), and
  the proxy drops the remote pad's right stick so free look stays local.
- `src/hooks.c`: hooks on the game's level/load/menu requests, and on the character input update so an off-screen
  second character is not walked to the camera target by the local co-op catch-up while two copies are linked.
- `src/window.c`: `OBSCOOP_WINDOWED=1` puts the game in a normal window (needed for test runs: a fullscreen device is lost and minimised when the game loses the foreground).
- The game's registry key `HKCU\Software\MRS\Obscure2` is redirected to `Obscure2_coop_test`, so test runs never touch the player's settings.
- `src/net.c`, `src/sync.c`: host/guest link. Each copy simulates both players (the host's controller is the guest's player 1, the guest's controller is the host's player 2); the host sends level/load/menu requests and position snapshots.
- `OBSCOOP_ROLE=host|guest`, `OBSCOOP_NET=udp|steam`, `OBSCOOP_UDP=<port>`, `OBSCOOP_MULTI=1` (two copies on one PC).
- Build: `i686-w64-mingw32-gcc -O2 -shared -static -static-libgcc -o build/xinput1_3.dll src/obscoop2.c src/obscoop2.def -Wl,--kill-at -lws2_32 -ld3d9`
- Only the Steam build with `Obscure2.exe` of 3,733,504 bytes and PE timestamp 1395160951 is accepted.

No game files are shipped. MIT license.

Research notes: [coop-anything games/obscure-2](https://github.com/cranebeaker/coop-anything).

1.1 (2.1): player 2 is attached to the second input controller after a save load on both copies (the game may still
be in one-player mode, so the partner can remain AI); the installer (install.ps1 / INSTALL.txt) is included; the
save-file transfer (PKT_SAVE/PKT_SAVE_ACK) is present but only advances one chunk, so it is unreleased. Known gaps:
the 2P mode after load, world item pickup, attack animation, item usage, destructibles (windows), enemy AI health
(not exposed by the game). Tests: save/items/health pass on both loopback copies; the death/partner-control check
fails for the 1P-mode reason.
