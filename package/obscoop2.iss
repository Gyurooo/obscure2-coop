; Obscure II online co-op - Windows installer (Inno Setup).
;
; The wizard does what package/install.ps1 does, in this order:
;   welcome -> MIT licence -> game folder (found automatically) -> ready -> install -> finish
;   * refuses an Obscure2.exe that is not Steam build 215294 (SHA-256, same as install.ps1)
;   * warns (does not refuse) when d3d9.dll / dxgi.dll is next to the exe (DXVK, ReShade)
;   * backs up an existing xinput1_3.dll and never overwrites an existing .bak
;   * installs the same file list install.ps1 installs (obscoop.ini only when the folder has none)
;   * patches Save\game*.sav and coop_profile\remote\game*.sav MTHC -> 2CHC on the raw bytes
;     (AnsiString byte buffer, no text conversion), .1p.bak before the first patch
;   * writes obscoop_install.txt, the same manifest install.ps1 writes
; The uninstaller (registered as "Obscure II Online Co-op <version>") removes what Inno installed,
; then restores the xinput1_3.dll backup and, after asking, the patched saves from their .1p.bak.
;
; Build: tools/build_release.sh <version> runs this with the defines below, e.g.
;   ISCC --define=AppVersion=1.7 --define=PkgDir=<assembled package> --output-dir=<out> package/obscoop2.iss
; Nobody's home directory is baked into this file.

#ifndef AppVersion
  #define AppVersion "devel"
#endif
#ifndef PkgDir
  ; compiling straight from a checkout: the package folder itself (it has the text files, not the binaries)
  #define PkgDir SourcePath
#endif

#define ModName "Obscure II Online Co-op"
#define GameExe "Obscure2.exe"

[Setup]
AppId={{6C1E4F3A-9A2B-4C7D-8E55-0B3F1C7A2D91}
AppName={#ModName}
AppVersion={#AppVersion}
AppVerName={#ModName} {#AppVersion}
AppPublisher=the obscure2-coop project
AppPublisherURL=https://github.com/Gyurooo/obscure2-coop
AppSupportURL=https://github.com/Gyurooo/obscure2-coop
AppComments=Online co-op for Obscure II (Steam app 254480, build 215294). MIT licence.
DefaultDirName={code:DefaultGameDir}
DefaultGroupName={#ModName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile={#SourcePath}\LICENSE.txt
OutputDir=.
OutputBaseFilename=Obscoop2-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; No admin rights unless the target folder needs them (Steam usually lives in Program Files (x86)):
; the install-mode dialog lets the player ask for elevation, and silent installs stay non-elevated.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
UninstallDisplayName={#ModName} {#AppVersion}
UninstallDisplayIcon={app}\{#GameExe}
UsePreviousAppDir=no
DirExistsWarning=no
AllowNoIcons=yes
; the player is told to close the game (INSTALL.txt); Restart Manager would only add noise here
CloseApplications=no
RestartApplications=no
SetupLogging=yes
AllowUNCPath=no

[Files]
; The list install.ps1 copies (package/install.ps1 section 4), nothing else. The backup of a previous
; xinput1_3.dll and the "was this file already identical?" check happen in the callbacks below.
Source: "{#PkgDir}\xinput1_3.dll"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('xinput1_3.dll'); AfterInstall: RecordFile('xinput1_3.dll')
Source: "{#PkgDir}\obscoop_o2.ipt"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('obscoop_o2.ipt'); AfterInstall: RecordFile('obscoop_o2.ipt')
Source: "{#PkgDir}\obscoop_direct.ini.txt"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('obscoop_direct.ini.txt'); AfterInstall: RecordFile('obscoop_direct.ini.txt')
Source: "{#PkgDir}\README.txt"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('README.txt'); AfterInstall: RecordFile('README.txt')
Source: "{#PkgDir}\start_host_steam.bat"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('start_host_steam.bat'); AfterInstall: RecordFile('start_host_steam.bat')
Source: "{#PkgDir}\start_guest_steam.bat"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('start_guest_steam.bat'); AfterInstall: RecordFile('start_guest_steam.bat')
Source: "{#PkgDir}\start_host_direct.bat"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('start_host_direct.bat'); AfterInstall: RecordFile('start_host_direct.bat')
Source: "{#PkgDir}\start_guest_direct.bat"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('start_guest_direct.bat'); AfterInstall: RecordFile('start_guest_direct.bat')
Source: "{#PkgDir}\obscoop-relay\obscoop-relay.exe"; DestDir: "{app}\obscoop-relay"; Flags: ignoreversion; BeforeInstall: RememberDest('obscoop-relay\obscoop-relay.exe'); AfterInstall: RecordFile('obscoop-relay\obscoop-relay.exe')
Source: "{#PkgDir}\obscoop-relay\steam_api.dll"; DestDir: "{app}\obscoop-relay"; Flags: ignoreversion; BeforeInstall: RememberDest('obscoop-relay\steam_api.dll'); AfterInstall: RecordFile('obscoop-relay\steam_api.dll')
Source: "{#PkgDir}\obscoop-relay\steam_appid.txt"; DestDir: "{app}\obscoop-relay"; Flags: ignoreversion; BeforeInstall: RememberDest('obscoop-relay\steam_appid.txt'); AfterInstall: RecordFile('obscoop-relay\steam_appid.txt')
Source: "{#PkgDir}\obscoop-relay\start_relay_guest.bat"; DestDir: "{app}\obscoop-relay"; Flags: ignoreversion; BeforeInstall: RememberDest('obscoop-relay\start_relay_guest.bat'); AfterInstall: RecordFile('obscoop-relay\start_relay_guest.bat')
; obscoop.ini is a settings file: a player's own copy (or their obscoop.ini.txt) is never replaced.
Source: "{#PkgDir}\obscoop.ini"; DestDir: "{app}"; Flags: ignoreversion onlyifdoesntexist; Check: NeedIni; BeforeInstall: RememberDest('obscoop.ini'); AfterInstall: RecordFile('obscoop.ini')
; VERSION.txt is written by tools/build_release.sh.
Source: "{#PkgDir}\VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('VERSION.txt'); AfterInstall: RecordFile('VERSION.txt')

[Code]
const
  SupportedSha  = '003f195b0e5bff91682f7e436cfe8213b6ca53803e17e98cdb5acd2103769354';
  SupportedSize = 3733504;
  ManifestName  = 'obscoop_install.txt';

var
  ManifestLine: TStringList;   // lines of obscoop_install.txt as they are collected
  PreNames: TStringList;       // relative name -> SHA-256 the file had before the install ('' = absent)
  PreHashes: TStringList;
  SavesPatched: Integer;

{ ------------------------------------------------------------------ small helpers }

function AppFile(const Rel: String): String;
begin
  Result := ExpandConstant('{app}') + '\' + Rel;
end;

function CrLf: String;
begin
  Result := #13#10;
end;

procedure AddManifestLine(const Line: String);
begin
  ManifestLine.Add(Line);
end;

function FileSizeOf(const FileName: String): Int64;
var
  Stream: TFileStream;
begin
  Result := 0;
  try
    Stream := TFileStream.Create(FileName, fmOpenRead or fmShareDenyNone);
    try
      Result := Stream.Size;
    finally
      Stream.Free;
    end;
  except
    Result := 0;
  end;
end;

{ LoadStringFromFile / SaveStringToFile only take an AnsiString in this Inno version. }
function LoadText(const FileName: String; var Text: String): Boolean;
var
  Bytes: AnsiString;
begin
  Result := LoadStringFromFile(FileName, Bytes);
  if Result then
    Text := Bytes;
end;

function SaveText(const FileName, Text: String): Boolean;
var
  Bytes: AnsiString;
begin
  Bytes := Text;
  Result := SaveStringToFile(FileName, Bytes, False);
end;

function NormalizeDir(const Path: String): String;
begin  Result := Trim(Path);
  { StringChangeEx changes the string in place and returns the number of changes }
  StringChangeEx(Result, '/', '\', True);
  Result := RemoveBackslashUnlessRoot(Result);
end;

function PosFrom(const Sub, Text: String; Start: Integer): Integer;
var
  I, Last: Integer;
begin
  Result := 0;
  if Start < 1 then
    Start := 1;
  Last := Length(Text) - Length(Sub) + 1;
  for I := Start to Last do
    if Copy(Text, I, Length(Sub)) = Sub then
    begin
      Result := I;
      Exit;
    end;
end;

{ Reads the quoted value that follows the quoted key Needle at or after Start. After is left on the
  closing quote (or unchanged when the key is not there), so a caller can loop over all occurrences. }
function QuotedValueAfter(const Needle, Text: String; Start: Integer; var After: Integer): String;
var
  P, Q: Integer;
begin
  Result := '';
  After := Start;
  P := PosFrom(Needle, Text, Start);
  if P = 0 then
    Exit;
  P := P + Length(Needle);
  while (P <= Length(Text)) and ((Text[P] = ' ') or (Text[P] = #9)) do
    Inc(P);
  if (P > Length(Text)) or (Text[P] <> '"') then
    Exit;
  Inc(P);
  Q := P;
  while (P <= Length(Text)) and (Text[P] <> '"') do
    Inc(P);
  Result := Copy(Text, Q, P - Q);
  After := P;
end;

{ All values of "Key" in a Valve keyvalues text file (libraryfolders.vdf, appmanifest_*.acf). }
function VdfValues(const FileName, Key: String): TStringList;
var
  Text, Value: String;
  P, After: Integer;
begin
  Result := TStringList.Create;
  if not FileExists(FileName) then
    Exit;
  if not LoadText(FileName, Text) then
    Exit;
  P := 1;
  while P <= Length(Text) do
  begin
    Value := QuotedValueAfter('"' + Key + '"', Text, P, After);
    if After <= P then
      Break;
    if Value <> '' then
      Result.Add(Value);
    P := After + 1;
  end;
end;

{ ------------------------------------------------------------------ where is the game }

function SteamRoot: String;
var
  Value: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamPath', Value) then
    Result := NormalizeDir(Value);
  if (Result = '') and RegQueryStringValue(HKLM, 'SOFTWARE\Valve\Steam', 'InstallPath', Value) then
    Result := NormalizeDir(Value);
end;

{ Every Steam library folder: the Steam root, then every "path" in steamapps\libraryfolders.vdf. }
function SteamLibraries: TStringList;
var
  Root: String;
  Names: TStringList;
  I, J: Integer;
  Path: String;
  Duplicate: Boolean;
begin
  Result := TStringList.Create;
  Root := SteamRoot;
  if Root = '' then
    Exit;
  Result.Add(Root);
  Names := VdfValues(Root + '\steamapps\libraryfolders.vdf', 'path');
  for I := 0 to Names.Count - 1 do
  begin
    Path := NormalizeDir(Names.Strings[I]);
    Duplicate := False;
    for J := 0 to Result.Count - 1 do
      if CompareText(Result.Strings[J], Path) = 0 then
        Duplicate := True;
    if (not Duplicate) and (Path <> '') then
      Result.Add(Path);
  end;
  Names.Free;
end;

{ The game folder inside one library: appmanifest_254480.acf's installdir first, then the usual names. }
function GameInLibrary(const Library: String): String;
var
  SteamApps: String;
  Names: TStringList;
  I: Integer;
  Candidate: String;
begin
  Result := '';
  SteamApps := Library + '\steamapps';
  Names := VdfValues(SteamApps + '\appmanifest_254480.acf', 'installdir');
  Names.Add('Obscure2');
  Names.Add('Obscure 2');
  for I := 0 to Names.Count - 1 do
  begin
    Candidate := SteamApps + '\common\' + Names.Strings[I];
    if FileExists(Candidate + '\' + '{#GameExe}') then
    begin
      Result := Candidate;
      Break;
    end;
  end;
  Names.Free;
end;

{ The DefaultDirName scripted constant: the game found on this PC, so the player only has to confirm. }
function DefaultGameDir(Param: String): String;
var
  Libraries: TStringList;
  I: Integer;
  Found: String;
begin
  Result := '';
  Libraries := SteamLibraries;
  for I := 0 to Libraries.Count - 1 do
  begin
    Found := GameInLibrary(Libraries.Strings[I]);
    if Found <> '' then
    begin
      Result := Found;
      Break;
    end;
  end;
  if (Result = '') and (Libraries.Count > 0) then
    Result := Libraries.Strings[0] + '\steamapps\common\Obscure2';
  Libraries.Free;
  if Result = '' then
    Result := 'C:\Program Files (x86)\Steam\steamapps\common\Obscure2';
end;

{ ------------------------------------------------------------------ the exe gate }

{ True when Dir holds the one Obscure2.exe the mod's hooks are written for; Problem says why not. }
function CheckGameDir(const Dir: String; var Problem: String): Boolean;
var
  Exe, Hash: String;
  Size: Int64;
begin
  Result := False;
  Problem := '';
  Exe := Dir + '\{#GameExe}';
  if not FileExists(Exe) then
  begin
    Problem := 'Obscure2.exe is not in this folder:' + CrLf + '  ' + Dir + CrLf + CrLf +
      'Choose the Obscure II folder - the one with Obscure2.exe in it, usually' + CrLf +
      '  ...\Steam\steamapps\common\Obscure2' + CrLf + CrLf +
      'Nothing was changed.';
    Exit;
  end;
  Hash := GetSHA256OfFile(Exe);
  if CompareText(Hash, SupportedSha) = 0 then
  begin
    Result := True;
    Exit;
  end;
  Size := FileSizeOf(Exe);
  Problem := 'This Obscure2.exe is not the supported Steam build, so the mod is not installed.' + CrLf + CrLf +
    '  expected SHA-256 ' + SupportedSha + '  (' + IntToStr(SupportedSize) + ' bytes)' + CrLf +
    '  found    SHA-256 ' + Lowercase(Hash) + '  (' + IntToStr(Size) + ' bytes)' + CrLf + CrLf +
    'The mod is written for Steam build 215294 and hooks that exact code. A widescreen patch, a ' +
    'no-CD crack or a repack changes the exe and the mod would not work.' + CrLf + CrLf +
    'Fix the game first: Steam -> Library -> right-click Obscure II -> Properties -> Installed ' +
    'files -> Verify integrity of game files.' + CrLf + CrLf +
    'Nothing was changed by this installer.';
  Log('exe check failed: expected ' + SupportedSha + ', found ' + Lowercase(Hash) + ' (' + IntToStr(Size) + ' bytes)');
end;

function NeedIni: Boolean;var
  Dir: String;
begin
  Dir := ExpandConstant('{app}');
  Result := (not FileExists(Dir + '\obscoop.ini')) and (not FileExists(Dir + '\obscoop.ini.txt'));
end;

{ ------------------------------------------------------------------ per-file callbacks }

function PreHashOf(const Rel: String): String;
var
  I: Integer;
begin
  Result := '';
  for I := 0 to PreNames.Count - 1 do
    if CompareText(PreNames.Strings[I], Rel) = 0 then
    begin
      Result := PreHashes.Strings[I];
      Exit;
    end;
end;

procedure RememberPreHash(const Rel, Hash: String);
begin
  PreNames.Add(Rel);
  PreHashes.Add(Hash);
end;

{ BeforeInstall: remember what the file looked like (so uninstall.ps1's "same file" rule still holds)
  and, for the mod DLL, back up the file that is about to be replaced. }
procedure RememberDest(const Rel: String);
var
  Dest, Backup, Stamp: String;
begin
  Dest := AppFile(Rel);
  if not FileExists(Dest) then
  begin
    RememberPreHash(Rel, '');
    Exit;
  end;
  RememberPreHash(Rel, GetSHA256OfFile(Dest));
  if CompareText(Rel, 'xinput1_3.dll') <> 0 then
    Exit;
  Backup := Dest + '.bak';
  if FileExists(Backup) then
  begin
    { never overwrite a backup - it may be somebody else's - but the DLL being replaced must stay
      recoverable, so it goes to a timestamped name instead }
    Stamp := GetDateTimeString('yyyymmdd-hhnnss', '-', ':');
    Backup := Dest + '.' + Stamp + '.bak';
    Log('xinput1_3.dll.bak already exists and is left alone; the current DLL goes to ' + ExtractFileName(Backup));
  end;
  if CopyFile(Dest, Backup, False) then
  begin
    AddManifestLine('bak xinput1_3.dll ' + ExtractFileName(Backup));
    Log('backup: xinput1_3.dll -> ' + ExtractFileName(Backup));
  end
  else
    Log('could not back up xinput1_3.dll to ' + Backup);
end;

{ AfterInstall: record the file in the manifest unless it was already there unchanged. }
procedure RecordFile(const Rel: String);
var
  Dest, Before, After: String;
begin
  Dest := AppFile(Rel);
  if not FileExists(Dest) then
    Exit;
  Before := PreHashOf(Rel);
  After := GetSHA256OfFile(Dest);
  if (Before = '') or (CompareText(Before, After) <> 0) or (CompareText(Rel, 'VERSION.txt') = 0) then
    AddManifestLine('add ' + Rel);
end;

{ ------------------------------------------------------------------ the campaign saves }

{ MTHC -> 2CHC on the raw bytes of one save. AnsiString holds the file's bytes as they are, so nothing
  above 0x7f is touched (a String/Unicode round trip would re-encode them). }
function PatchSaveFile(const FileName: String; var Replacements: Integer): Boolean;
var
  Data: AnsiString;
  Stream: TFileStream;
  Backup: String;
  I, Found: Integer;
begin
  Result := False;
  Replacements := 0;
  try
    Stream := TFileStream.Create(FileName, fmOpenRead or fmShareDenyNone);
    try
      SetLength(Data, Integer(Stream.Size));
      if Stream.Size > 0 then
        Stream.ReadBuffer(Data, Integer(Stream.Size));
    finally
      Stream.Free;
    end;
  except
    Log('cannot read save ' + FileName);
    Exit;
  end;

  Found := 0;
  I := 1;
  while I <= Length(Data) - 3 do
  begin
    if (Data[I] = 'M') and (Data[I + 1] = 'T') and (Data[I + 2] = 'H') and (Data[I + 3] = 'C') then
    begin
      Data[I] := '2';
      Data[I + 1] := 'C';
      Inc(Found);
      I := I + 4;
    end
    else
      Inc(I);
  end;
  if Found = 0 then
    Exit;

  Backup := FileName + '.1p.bak';
  if not FileExists(Backup) then
    if not CopyFile(FileName, Backup, False) then
    begin
      Log('cannot write the backup ' + Backup);
      Exit;
    end;

  try
    Stream := TFileStream.Create(FileName, fmCreate);
    try
      Stream.WriteBuffer(Data, Length(Data));
    finally
      Stream.Free;
    end;
  except
    Log('cannot write save ' + FileName);
    Exit;
  end;
  Replacements := Found;
  Result := True;
end;

procedure PatchSavesIn(const Dir, RelDir: String);
var
  FindRec: TFindRec;
  FileName, Rel: String;
  Count: Integer;
begin
  if not DirExists(Dir) then
    Exit;
  if not FindFirst(Dir + '\game*.sav', FindRec) then
    Exit;
  try
    repeat
      if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
      begin
        FileName := Dir + '\' + FindRec.Name;
        if PatchSaveFile(FileName, Count) then
        begin
          if RelDir = '' then
            Rel := FindRec.Name
          else
            Rel := RelDir + '\' + FindRec.Name;
          AddManifestLine('save ' + Rel + ' ' + Rel + '.1p.bak');
          Inc(SavesPatched);
          Log('patched ' + Rel + ' (MTHC -> 2CHC, ' + IntToStr(Count) + ' tag(s))');
        end;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

{ ------------------------------------------------------------------ installer events }

function InitializeSetup: Boolean;
begin
  Result := True;
  ManifestLine := TStringList.Create;
  PreNames := TStringList.Create;
  PreHashes := TStringList.Create;
  SavesPatched := 0;
end;

{ The game folder is chosen on the directory page: say right away when it is not one we can use. }
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Problem: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
    if not CheckGameDir(WizardDirValue, Problem) then
    begin
      MsgBox(Problem, mbError, MB_OK);
      Result := False;
    end;
end;

{ Unattended installs never see the directory page, so the same gate runs again here - and this is
  where the wrapper warning goes. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Dir, Problem, Wrappers: String;
begin
  Result := '';
  Dir := ExpandConstant('{app}');
  if not CheckGameDir(Dir, Problem) then
  begin
    Log('refused: ' + Dir);
    Result := Problem;
    Exit;
  end;
  Log('game folder: ' + Dir + ' (Steam build 215294, SHA-256 matches)');

  Wrappers := '';
  if FileExists(Dir + '\d3d9.dll') then
    Wrappers := 'd3d9.dll';
  if FileExists(Dir + '\dxgi.dll') then
  begin
    if Wrappers <> '' then
      Wrappers := Wrappers + ' and ';
    Wrappers := Wrappers + 'dxgi.dll';
  end;
  if Wrappers <> '' then
  begin
    Log('warning: ' + Wrappers + ' in the game folder (DXVK / ReShade or another wrapper)');
    MsgBox(Wrappers + ' is in the game folder (DXVK, ReShade or another wrapper). The mod is ' +
      'untested with it. If the game does not start, or the link stays on ''waiting'', remove ' +
      'that file and try again.', mbInformation, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, Text: String;
  I: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    AppDir := ExpandConstant('{app}');
    PatchSavesIn(AppDir + '\Save', 'Save');
    PatchSavesIn(AppDir + '\coop_profile\remote', 'coop_profile\remote');
    if SavesPatched = 0 then
      Log('saves: nothing to patch (no save still stores the AI partner)');

    AddManifestLine('done');
    Text := '';
    for I := 0 to ManifestLine.Count - 1 do
      Text := Text + ManifestLine.Strings[I] + #13#10;
    if SaveText(AppDir + '\' + ManifestName, Text) then
      Log('manifest: ' + ManifestName + ' (' + IntToStr(ManifestLine.Count) + ' line(s))')
    else
      Log('could not write ' + ManifestName);
    if SavesPatched > 0 then
      Log('patched ' + IntToStr(SavesPatched) + ' save file(s)');
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10 + #13#10 +
      'Start the game with one of the .bat files that are now in the game folder:' + #13#10 +
      '  host, over Steam : start_host_steam.bat     guest, over Steam : start_guest_steam.bat' + #13#10 +
      '  host, direct     : start_host_direct.bat    guest, direct     : start_guest_direct.bat' + #13#10 + #13#10 +
      'Both players start at the MAIN MENU. The host loads a save, the guest follows by itself.' + #13#10 +
      'The same version must be installed on both PCs. README.txt (in the game folder) has the details.';
end;

{ ------------------------------------------------------------------ uninstaller events }

procedure SplitLines(const Text: String; Lines: TStringList);
var
  Rest, Line: String;
  P: Integer;
begin
  Rest := Text;
  StringChangeEx(Rest, #13#10, #10, True);
  P := Pos(#10, Rest);
  while P > 0 do
  begin
    Line := Trim(Copy(Rest, 1, P - 1));
    if Line <> '' then
      Lines.Add(Line);
    Rest := Copy(Rest, P + 1, Length(Rest));
    P := Pos(#10, Rest);
  end;
  Line := Trim(Rest);
  if Line <> '' then
    Lines.Add(Line);
end;

{ "bak <file> <backup>" / "save <file> <backup>" -> "file|backup" }
procedure CollectPairs(const Lines: TStringList; const Kind: String; Pairs: TStringList);
var
  I, P: Integer;
  Line, First, Second: String;
begin
  for I := 0 to Lines.Count - 1 do
  begin
    Line := Lines.Strings[I];
    if Pos(Kind + ' ', Line) <> 1 then
      continue;
    First := Trim(Copy(Line, Length(Kind) + 2, Length(Line)));
    P := Pos(' ', First);
    if P = 0 then
      continue;
    Second := Trim(Copy(First, P + 1, Length(First)));
    First := Trim(Copy(First, 1, P - 1));
    if (First <> '') and (Second <> '') then
      Pairs.Add(First + '|' + Second);
  end;
end;

function PairFile(const Pair: String): String;
var
  P: Integer;
begin
  P := Pos('|', Pair);
  if P = 0 then
    Result := Pair
  else
    Result := Copy(Pair, 1, P - 1);
end;

function PairBackup(const Pair: String): String;
var
  P: Integer;
begin
  P := Pos('|', Pair);
  if P = 0 then
    Result := ''
  else
    Result := Copy(Pair, P + 1, Length(Pair));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDir, ManifestPath, Text, Save, Backup: String;
  Answer: Integer;
  Lines, Baks, Saves: TStringList;
  I: Integer;
  RestoreSaves: Boolean;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  AppDir := ExpandConstant('{app}');
  ManifestPath := AppDir + '\' + ManifestName;
  if not FileExists(ManifestPath) then
  begin
    Log('no ' + ManifestName + ' in ' + AppDir + ': nothing is restored');
    MsgBox('The mod files were removed, but there is no ' + ManifestName + ' in the game folder, so ' +
      'this uninstaller cannot tell which files were the installer''s backups. Nothing was restored.' + CrLf + CrLf +
      'If you are sure, restore these by hand:' + CrLf +
      '  xinput1_3.dll      from xinput1_3.dll.bak' + CrLf +
      '  Save\gameN.sav     from Save\gameN.sav.1p.bak' + CrLf +
      '  coop_profile\remote\gameN.sav from its .1p.bak', mbInformation, MB_OK);
    Exit;
  end;

  if not LoadText(ManifestPath, Text) then
  begin
    Log('cannot read ' + ManifestPath);
    Exit;
  end;
  Lines := TStringList.Create;
  Baks := TStringList.Create;
  Saves := TStringList.Create;
  SplitLines(Text, Lines);
  CollectPairs(Lines, 'bak', Baks);
  CollectPairs(Lines, 'save', Saves);

  { Inno already removed the files this setup installed (it keeps its own log); this is the rest:
    the backups it made, and the question about the saves. }
  for I := 0 to Baks.Count - 1 do
  begin
    Save := AppDir + '\' + PairFile(Baks.Strings[I]);
    Backup := AppDir + '\' + PairBackup(Baks.Strings[I]);
    if not FileExists(Backup) then
      continue;
    if CopyFile(Backup, Save, False) then
    begin
      DeleteFile(Backup);
      Log('restored ' + PairFile(Baks.Strings[I]) + ' from ' + PairBackup(Baks.Strings[I]));
    end
    else
      Log('could not restore ' + PairFile(Baks.Strings[I]) + ' (' + Backup + ' is kept)');
  end;

  RestoreSaves := True;
  if Saves.Count > 0 then
  begin
    Answer := MsgBox('The installer had switched ' + IntToStr(Saves.Count) + ' save file(s) from the ' +
      'game''s one-player save to real two-player.' + CrLf + CrLf +
      'Put the saves back as they were before the install? (Their .1p.bak copies are next to them.)' + CrLf + CrLf +
      'Choose No if you played with two players since and want to keep those saves - the .1p.bak ' +
      'files are then left in place so nothing is lost.', mbConfirmation, MB_YESNO);
    if Answer = IDNO then
      RestoreSaves := False;
  end;
  if RestoreSaves then
    for I := 0 to Saves.Count - 1 do
    begin
      Save := AppDir + '\' + PairFile(Saves.Strings[I]);
      Backup := AppDir + '\' + PairBackup(Saves.Strings[I]);
      if not FileExists(Backup) then
        continue;
      if CopyFile(Backup, Save, False) then
      begin
        DeleteFile(Backup);
        Log('restored save ' + PairFile(Saves.Strings[I]));
      end
      else
        Log('could not restore save ' + PairFile(Saves.Strings[I]) + ' (' + Backup + ' is kept)');
    end
  else
    Log('saves left as they are, ' + IntToStr(Saves.Count) + ' .1p.bak file(s) kept');

  DeleteFile(ManifestPath);
  RemoveDir(AppDir + '\obscoop-relay');
  Lines.Free;
  Baks.Free;
  Saves.Free;
end;
