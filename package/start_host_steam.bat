@echo off
rem Obscure II co-op - HOST over the Steam relay.
rem Steam must be running and logged in. Both players start at the MAIN MENU; you (the host) load a
rem save and the guest follows by itself. Leave this and the relay window open while you play.
rem The relay runs as Steam app 480 ("Spacewar"), so friends can right-click your name -> Join game.
setlocal
cd /d "%~dp0"
if not exist "obscoop-relay\obscoop-relay.exe" (
	echo obscoop-relay\obscoop-relay.exe is missing. Unpack the whole zip and run install.ps1.
	pause
	exit /b 1
)
rem The relay must see the 480 app id, the game 254480: start the relay BEFORE SteamAppId is set.
start "obscoop relay (host)" /D "%~dp0obscoop-relay" "%~dp0obscoop-relay\obscoop-relay.exe" host 27961
set SteamAppId=254480
set SteamGameId=254480
set OBSCOOP_ROLE=host
set OBSCOOP_NET=udp
set OBSCOOP_UDP=27961
set OBSCOOP_REMOTE_PAD=1
set OBSCOOP_VPADS=1
set OBSCOOP_HIDE_REAL_PADS=0
set OBSCOOP_WINDOWED=1
start "" Obscure2.exe
