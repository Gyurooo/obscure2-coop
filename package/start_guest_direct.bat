@echo off
rem Obscure II co-op - GUEST, direct Steam link (no relay window).
rem Steam must be running and you must be Steam friends with the host.
rem Put the host's Steam ID (17 digits) or the host's Steam name on one line in host.txt next to
rem Obscure2.exe. The host's ID is in its window title and in steam_id.txt.
rem This path is newer than the relay and has not been tested between two Steam accounts yet.
setlocal
cd /d "%~dp0"
set HOSTARG=
if exist "host.txt" set /p HOSTARG=<host.txt
if "%HOSTARG%"=="" (
	echo.
	echo Put the host's Steam ID or Steam name on one line in host.txt next to Obscure2.exe first.
	echo The host sees its Steam ID in its window title.
	pause
	exit /b 1
)
set SteamAppId=254480
set SteamGameId=254480
set OBSCOOP_ROLE=guest
set OBSCOOP_NET=steam
rem A 17-digit number is the ID, anything else is a name: setting both is harmless, the ID wins.
set OBSCOOP_HOST_STEAMID=%HOSTARG%
set OBSCOOP_HOST_NAME=%HOSTARG%
set OBSCOOP_LOCAL_PAD=0
set OBSCOOP_HIDE_REAL_PADS=0
set OBSCOOP_WINDOWED=1
start "" Obscure2.exe
