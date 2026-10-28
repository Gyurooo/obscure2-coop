@echo off
rem Obscure II co-op - the GUEST's Steam relay on its own (for a game started from Steam's Play button).
rem Steam must be running. Start this FIRST, leave the window open, then start Obscure 2 from Steam.
rem For that route obscoop.ini in the game folder must say ROLE=guest, NET=udp, UDP=27962,
rem PEER=127.0.0.1 - which is what the relay feeds. Usually start_guest_steam.bat is simpler: it starts
rem both for you.
rem Finding the host: put the host's Steam ID (17 digits), the host's Steam name, or lobby:<id> on one
rem line in host.txt in the game folder. With no host.txt the relay looks for a Steam friend who is
rem playing Spacewar with an obscoop lobby, and it also answers Join game / a lobby invite.
cd /d "%~dp0"
set HOSTARG=
if exist "..\host.txt" set /p HOSTARG=<"..\host.txt"
if defined HOSTARG (obscoop-relay.exe guest "%HOSTARG%" 27962) else (obscoop-relay.exe guest 27962)
pause
