Obscure II online co-op
=======================
(version 1.3 - the host and the guest must run the same version)

What it is
  Two players, two PCs, one Obscure II campaign. The game already knows how to run two players on one
  screen; this mod moves player 2 to the other PC. You both see your own character.
  Install first: see INSTALL.txt in this folder.

How a session goes
  1. Both start their game at the main menu (the .bat files below do it).
  2. The window title says "co-op host: waiting for a guest" or "co-op guest: waiting", then
     "connected" once you are linked.
  3. The HOST loads a save (Continue / Load game). The guest does nothing: its copy puts itself into
     the same level a couple of seconds later.
  4. Done. Play. If the link drops, the guest reconnects by itself and stays where it was.

Joining over Steam (recommended, no IP addresses)
  Each side runs a small relay next to the game; Steam carries the traffic between the two relays.
  HOST:   start_host_steam.bat   - opens the relay window (Steam app 480, "Spacewar"), then the game.
                                   A friend can right-click your name in Steam and choose "Join game".
  GUEST:  start_guest_steam.bat  - asks Steam for the host.
          To point it at one host, put the host's Steam ID (17 digits, the host's relay window and
          steam_id.txt show it), the host's Steam name, or lobby:<id> on one line in host.txt next to
          Obscure2.exe. With no host.txt it looks for a friend who is playing Spacewar with an
          obscoop lobby, and it also answers a "Join game" click or an invite.
  Leave both relay windows open while you play.

Joining without the relay (direct Steam link)
  HOST:   start_host_direct.bat
  GUEST:  start_guest_direct.bat, with the host's Steam ID or Steam name in host.txt next to
          Obscure2.exe. You must be Steam friends.
  This path is newer and has not been tested between two Steam accounts yet - try the relay first.

There is no direct-IP / LAN mode in this build
  The mod's plain-UDP transport only talks to the same PC (it is the test transport). Two PCs always
  go through Steam: the relay above, or the direct Steam link. A local network makes no difference.

Starting the game from Steam instead of the .bat files
  Copy obscoop_direct.ini.txt to obscoop.ini in the game folder and fill in ROLE (host or guest),
  NET=steam and the host's ID or name. obscoop.ini is read when the game starts; the .bat files set
  the same values themselves and win over the file.

Settings (obscoop.ini next to Obscure2.exe)
  WINDOWED=1     runs the game in a window. Recommended: a fullscreen game that loses focus gets
                 minimised. Set 0 if you prefer fullscreen.
  CAMERA=own     your camera follows your own character; CAMERA=shared makes the guest's camera
                 follow the host's player 1.
  LOCAL_PAD=0    which controller on this PC is yours (0 = the first one).
  HIDE_REAL_PADS=1  hides real controllers from the game, for a player whose only pad is virtual.
  Lines that start with ';' are comments. A setting in the .bat file wins over obscoop.ini.

What is synced (tested on two copies on one PC)
  - both characters: position, facing, animation, life, death and the pad that took over afterwards
  - the party (which characters are in play), the inventory (all 44 items) and every change to it
  - the weapons in both pairs of hands, and the selected slot
  - using items (first-aid kits etc.), healing
  - level changes, doors and loading zones: the guest follows the host
  - the world: chairs and the other breakables (pick up, carry, break), doors opening, windows
  - the save: the host's loaded save reaches the guest, and both copies build the same world
  - the scripted events: subtitles and the "press to skip" bar, and a skip on ONE side ends the
    cutscene on BOTH    (a skip is the only input that reaches across; everything else is local)
  - pause: START on either controller pauses both copies

What is NOT synced (or not proven)
  - Attacks, enemies and combat: the bot tests could not make the test save attack at all, so combat
    sync is unproven (the game's aim/target search finds no target in these levels, with or without
    the mod). Enemies are simulated twice, once per copy; they can drift apart in a real fight.
  - Character abilities (lock picking, the heavy case): the result sync is in the build but was never
    driven to a result in a test.
  - Cases and chests, and item drops from broken things.
  - Anything the game decides on its own, like a cutscene that starts at a different moment.

Known issues
  - Steam Cloud: turn it OFF for Obscure II (Steam -> Properties -> General). It can overwrite the
    saves the mod patches with copies from another PC. This is not needed by the mod itself.
  - The first seconds after a load: the guest's world may show a character in the wrong spot for a
    moment, then it snaps to the right place.
  - If a run starts with no world at all on one copy, restart both with the .bat files.
  - A game started from Steam's own Play button has no co-op unless obscoop.ini sets ROLE.

Reporting a bug
  Attach obscoop.log from BOTH game folders (the mod writes it next to Obscure2.exe; under
  C:\Program Files the write is redirected, so look in %LOCALAPPDATA%\obscoop instead).
  Say what you were doing, what you expected, what happened, and the version (line 1 of this file).
  obscoop.log is plain text and the tail of it after the problem is the part that matters.

Uninstall: see INSTALL.txt (uninstall.ps1).
No game files are shipped. MIT license.
