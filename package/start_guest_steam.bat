@echo off
rem Obscure II co-op - GUEST over the Steam relay.
rem Steam must be running and logged in, and you must be Steam friends with the host.
rem Both players start at the MAIN MENU; the host loads a save and your copy follows by itself.
rem Finding the host: put the host's Steam ID (17 digits), the host's Steam name, or lobby:<id> on one
rem line in host.txt next to Obscure2.exe. Without host.txt the relay looks for a friend playing
rem Spacewar with an obscoop lobby, and it also answers a "Join game" click or an invite from the host.
setlocal
cd /d "%~dp0"
if not exist "obscoop-relay\obscoop-relay.exe" (
	echo obscoop-relay\obscoop-relay.exe is missing. Unpack the whole zip and run install.ps1.
	pause
	exit /b 1
)
set HOSTARG=
if exist "host.txt" set /p HOSTARG=<host.txt
rem The relay must see the 480 app id, the game 254480: start the relay BEFORE SteamAppId is set.
start "obscoop relay (guest)" /D "%~dp0obscoop-relay" "%~dp0obscoop-relay\obscoop-relay.exe" guest "%HOSTARG%" 27962
set SteamAppId=254480
set SteamGameId=254480
set OBSCOOP_ROLE=guest
set OBSCOOP_NET=udp
set OBSCOOP_UDP=27962
set OBSCOOP_PEER=127.0.0.1
set OBSCOOP_LOCAL_PAD=0
set OBSCOOP_HIDE_REAL_PADS=0
set OBSCOOP_WINDOWED=1
start "" Obscure2.exe
