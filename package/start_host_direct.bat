@echo off
rem Obscure II co-op - HOST, direct Steam link (no relay window).
rem Steam must be running. Both players start at the MAIN MENU; you load a save and the guest follows.
rem The guest needs your Steam ID or Steam name in its host.txt (see start_guest_direct.bat).
rem This path is newer than the relay and has not been tested between two Steam accounts yet.
setlocal
cd /d "%~dp0"
set SteamAppId=254480
set SteamGameId=254480
set OBSCOOP_ROLE=host
set OBSCOOP_NET=steam
set OBSCOOP_REMOTE_PAD=1
set OBSCOOP_VPADS=1
set OBSCOOP_HIDE_REAL_PADS=0
set OBSCOOP_WINDOWED=1
start "" Obscure2.exe
