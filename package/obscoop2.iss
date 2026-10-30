; Obscure II online co-op - Windows installer (Inno Setup).
;
; The wizard does what package/install.ps1 does, in this order:
;   welcome -> MIT licence -> game folder (found automatically) -> Steam saves -> ready -> install -> finish
;   * refuses an Obscure2.exe that is not Steam build 215294 (SHA-256, same as install.ps1)
;   * warns (does not refuse) when d3d9.dll / dxgi.dll is next to the exe (DXVK, ReShade)
;   * backs up an existing xinput1_3.dll and never overwrites an existing .bak
;   * installs the same file list install.ps1 installs (obscoop.ini only when the folder has none)
;   * copies the player's Steam saves (Steam\userdata\<id>\254480\remote\game*.sav) into the folder the
;     mod reads its saves from (see ModSaveDirOf below), never moves them and never silently replaces a
;     save that differs; then patches every save MTHC -> 2CHC on the raw bytes (AnsiString byte buffer,
;     no text conversion), .1p.bak before the first patch
;   * writes obscoop_install.txt, the same manifest install.ps1 writes (plus "import" lines for the
;     saves it copied in)
; The uninstaller (registered as "Obscure II Online Co-op <version>") removes what Inno installed,
; then restores the xinput1_3.dll backup and, after asking, the patched saves from their .1p.bak, and
; removes the saves the installer had copied in (only while they are unchanged).
;
; Build: tools/build_release.sh <version> runs this with the defines below, e.g.
;   ISCC --define=AppVersion=1.7 --define=PkgDir=<assembled package> --output-dir=<out> package/obscoop2.iss
; Nobody's home directory is baked into this file.
;
; Test switches (documented in INSTALL.txt; only for the automated test):
;   /FAKESTEAM=<dir>  use <dir> as the Steam root (library folders, userdata) instead of the registry
;   /FAKEHASH         accept any Obscure2.exe instead of the supported SHA-256
;   /SAVEID=<id>      import the saves of that Steam userdata account (instead of the first / the page)

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
OutputBaseFilename=obscoop2-{#AppVersion}-setup
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
; VERSION.txt is written by tools/build_release.sh; a git checkout has none.
#if FileExists(AddBackslash(PkgDir) + "VERSION.txt")
Source: "{#PkgDir}\VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion; BeforeInstall: RememberDest('VERSION.txt'); AfterInstall: RecordFile('VERSION.txt')
#endif

[Icons]
; The two start scripts a player actually runs, named the way install.ps1's closing text names them, plus
; the readme. Inno adds the uninstall entry to the same group.
Name: "{group}\Start host (Steam)"; Filename: "{app}\start_host_steam.bat"; WorkingDir: "{app}"; Comment: "Obscure II co-op: host, both players at the main menu"
Name: "{group}\Start guest (Steam)"; Filename: "{app}\start_guest_steam.bat"; WorkingDir: "{app}"; Comment: "Obscure II co-op: guest, joins the host over Steam"
Name: "{group}\Start host (direct)"; Filename: "{app}\start_host_direct.bat"; WorkingDir: "{app}"; Comment: "Obscure II co-op: host without the relay"
Name: "{group}\Start guest (direct)"; Filename: "{app}\start_guest_direct.bat"; WorkingDir: "{app}"; Comment: "Obscure II co-op: guest without the relay"
Name: "{group}\README"; Filename: "{app}\README.txt"; Comment: "Obscure II co-op manual"

[Code]
const
  SupportedSha  = '003f195b0e5bff91682f7e436cfe8213b6ca53803e17e98cdb5acd2103769354';
  SupportedSize = 3733504;
  ManifestName  = 'obscoop_install.txt';
  SteamAppId    = '254480';
  // manifest path prefix: "~" means the mod's own save folder, which can be outside the game dir
  ModMarker     = '~';

var
  ManifestLine: TStringList;   // lines of obscoop_install.txt as they are collected
  PreNames: TStringList;       // relative name -> SHA-256 the file had before the install ('' = absent)
  PreHashes: TStringList;
  ImportedSaves: TStringList;  // full paths of the saves this run copied out of Steam
  SteamIds: TStringList;       // userdata accounts that have Obscure II saves, sorted
  SavePage: TInputOptionWizardPage;   // only created when there is more than one account
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

{ A byte-for-byte copy. CopyFile's "existing file" rules differ between Inno versions and the saves are
  binary (an AnsiString round trip keeps every byte), so this reads and writes the bytes itself. }
function CopyBytes(const Source, Target: String): Boolean;
var
  Src, Dst: TFileStream;
  Data: AnsiString;
begin
  Result := False;
  try
    Src := TFileStream.Create(Source, fmOpenRead or fmShareDenyNone);
    try
      SetLength(Data, Integer(Src.Size));
      if Src.Size > 0 then
        Src.ReadBuffer(Data, Integer(Src.Size));
    finally
      Src.Free;
    end;
    Dst := TFileStream.Create(Target, fmCreate);
    try
      if Length(Data) > 0 then
        Dst.WriteBuffer(Data, Length(Data));
    finally
      Dst.Free;
    end;
    Result := True;
  except
    Result := False;
  end;
end;

function NormalizeDir(const Path: String): String;
begin
  Result := Trim(Path);
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

{ A switch such as /FAKEHASH: the param:... constant cannot see a parameter that has no "=value", so
  the command line is scanned for the token instead. Test only - nothing here is on unless it is passed. }
function SwitchGiven(const Switch: String): Boolean;
var
  Up, Needle: String;
  P, N: Integer;
  Before, After: Char;
begin
  Result := False;
  Up := Uppercase(GetCmdTail);
  Needle := Uppercase(Switch);
  P := PosFrom(Needle, Up, 1);
  while P > 0 do
  begin
    Before := #0;
    After := #0;
    if P > 1 then
      Before := Up[P - 1];
    N := P + Length(Needle);
    if N <= Length(Up) then
      After := Up[N];
    if ((Before = #0) or (Before = ' ') or (Before = '"')) and
       ((After = #0) or (After = ' ') or (After = '"') or (After = '=')) then
    begin
      Result := True;
      Exit;
    end;
    P := PosFrom(Needle, Up, P + 1);
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

{ /FAKESTEAM=<dir>: the automated test points Steam at a folder it owns, so no real Steam folder, real
  library folder or real save is read. Empty unless the switch is given. }
function FakeSteamRoot: String;
var
  Value: String;
begin
  Result := '';
  Value := ExpandConstant('{param:FAKESTEAM|}');
  if Value <> '' then
    Result := NormalizeDir(Value);
end;

function SteamRoot: String;
var
  Value: String;
begin
  Result := FakeSteamRoot;
  if Result <> '' then
    Exit;
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

{ ------------------------------------------------------------------ where the mod keeps its saves }

{ The same rule as src/obscoop2.c (DllMain, "choose_data_dir"): lower-case game dir contains
  "\program files" -> %LOCALAPPDATA%\obscoop\coop_profile\remote, else <game dir>\coop_profile\remote. }
function ModSaveDirOf(const AppDir: String): String;
begin
  if Pos('\program files', Lowercase(AppDir)) > 0 then
    Result := ExpandConstant('{localappdata}') + '\obscoop\coop_profile\remote'
  else
    Result := AppDir + '\coop_profile\remote';
end;

// A manifest path is relative to the game dir, except "~name": the mod's own save folder.
function ResolveManifestPath(const Rel: String): String;
begin
  if (Rel <> '') and (Rel[1] = ModMarker) then
    Result := ModSaveDirOf(ExpandConstant('{app}')) + '\' + Copy(Rel, 2, Length(Rel))
  else
    Result := ExpandConstant('{app}') + '\' + Rel;
end;

function RelToApp(const FileName: String): String;
var
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  if CompareText(Copy(FileName, 1, Length(AppDir) + 1), AppDir + '\') = 0 then
    Result := Copy(FileName, Length(AppDir) + 2, Length(FileName))
  else
    Result := ModMarker + ExtractFileName(FileName);
end;

{ ------------------------------------------------------------------ the Steam saves }

function FirstSaveName(const Dir: String): String;
var
  Rec: TFindRec;
begin
  Result := '';
  if not DirExists(Dir) then
    Exit;
  if FindFirst(Dir + '\game*.sav', Rec) then
  begin
    if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
      Result := Rec.Name;
    FindClose(Rec);
  end;
end;

function SaveCountIn(const Dir: String): Integer;
var
  Rec: TFindRec;
begin
  Result := 0;
  if not DirExists(Dir) then
    Exit;
  if not FindFirst(Dir + '\game*.sav', Rec) then
    Exit;
  try
    repeat
      if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
        Inc(Result);
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

function SteamIdSaveDir(const Root, Id: String): String;
begin
  Result := Root + '\userdata\' + Id + '\' + SteamAppId + '\remote';
end;

{ Every Steam account folder under <steam>\userdata that holds Obscure II saves, sorted. }
function SteamIdsWithSaves: TStringList;
var
  Root, Dir: String;
  Rec: TFindRec;
begin
  Result := TStringList.Create;
  Root := SteamRoot;
  if Root = '' then
    Exit;
  if not FindFirst(Root + '\userdata\*', Rec) then
    Exit;
  try
    repeat
      if ((Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and (Rec.Name <> '.') and (Rec.Name <> '..') then
      begin
        Dir := SteamIdSaveDir(Root, Rec.Name);
        if FirstSaveName(Dir) <> '' then
          Result.Add(Rec.Name);
      end;
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
  if Result.Count > 1 then
    Result.Sort;
end;

function ListHas(const List: TStringList; const Value: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 0 to List.Count - 1 do
    if CompareText(List.Strings[I], Value) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

{ Which account's saves to copy: /SAVEID= (test), the only account, or the wizard page's choice. '' means
  "import nothing". }
function ChosenSteamId: String;
var
  Value: String;
  Picked: Integer;
begin
  Result := '';
  if SteamIds = nil then
    Exit;
  Value := Trim(ExpandConstant('{param:SAVEID|}'));
  if Value <> '' then
  begin
    if ListHas(SteamIds, Value) then
    begin
      Log('test switch /SAVEID=' + Value + ': using the saves of that Steam account');
      Result := Value;
    end
    else
      Log('test switch /SAVEID=' + Value + ' names no account with saves; ignored');
    if Result <> '' then
      Exit;
  end;
  if SteamIds.Count = 0 then
    Exit;
  if SteamIds.Count = 1 then
  begin
    Result := SteamIds.Strings[0];
    Exit;
  end;
  Picked := 0;
  if SavePage <> nil then
    Picked := SavePage.SelectedValueIndex;
  if (Picked >= 0) and (Picked < SteamIds.Count) then
    Result := SteamIds.Strings[Picked]
  else if Picked >= SteamIds.Count then
    Result := ''   // the "do not copy" line
  else
    Result := SteamIds.Strings[0];
end;

{ Copy <steam>\userdata\<id>\254480\remote\game*.sav into the mod's save folder. Never move, never
  replace a file that differs without asking (a silent install keeps the existing file), original
  untouched. The copies are patched by PatchSavesIn afterwards like any other save in that folder. }
procedure ImportSteamSaves;
var
  AppDir, Id, SrcDir, DstDir, Src, Dst: String;
  Rec: TFindRec;
  Differing: TStringList;
  I: Integer;
  Replace: Boolean;
begin
  AppDir := ExpandConstant('{app}');
  DstDir := ModSaveDirOf(AppDir);
  Id := ChosenSteamId;
  if Id = '' then
  begin
    Log('saves: no Steam save to import (looked in ' + SteamRoot + '\userdata\<id>\' + SteamAppId + '\remote)');
    Exit;
  end;
  SrcDir := SteamIdSaveDir(SteamRoot, Id);
  Log('saves: importing ' + SrcDir + ' -> ' + DstDir);
  if not DirExists(DstDir) then
    ForceDirectories(DstDir);
  Differing := TStringList.Create;
  if FindFirst(SrcDir + '\game*.sav', Rec) then
  try
    repeat
      if (Rec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
      begin
        Src := SrcDir + '\' + Rec.Name;
        Dst := DstDir + '\' + Rec.Name;
        if not FileExists(Dst) then
        begin
          if CopyBytes(Src, Dst) then
          begin
            ImportedSaves.Add(Dst);
            Log('imported save ' + Rec.Name);
          end
          else
            Log('could not copy ' + Src);
        end
        else if CompareText(GetSHA256OfFile(Src), GetSHA256OfFile(Dst)) = 0 then
          Log('save ' + Rec.Name + ' is already in the save folder, same content')
        else
          Differing.Add(Rec.Name);
      end;
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
  if Differing.Count > 0 then
  begin
    Replace := False;
    if not WizardSilent then
      Replace := MsgBox('The mod''s save folder already holds ' + IntToStr(Differing.Count) +
        ' save file(s) that are not the same as the one(s) in Steam:' + CrLf + CrLf + DstDir + CrLf + CrLf +
        'Copy the Steam saves over them? Choose No to keep the files that are there now. (The saves in '
        + 'Steam are never changed either way.)',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
    if Replace then
      for I := 0 to Differing.Count - 1 do
      begin
        Src := SrcDir + '\' + Differing.Strings[I];
        Dst := DstDir + '\' + Differing.Strings[I];
        if CopyBytes(Src, Dst) then
        begin
          ImportedSaves.Add(Dst);
          Log('replaced save ' + Differing.Strings[I] + ' with the Steam copy');
        end
        else
          Log('could not replace ' + Dst);
      end
    else if WizardSilent then
      Log('kept ' + IntToStr(Differing.Count) + ' save(s) that differ from the Steam copy (a silent install never overwrites one)')
    else
      Log('kept the save(s) that are already there: ' + IntToStr(Differing.Count) + ' file(s)');
  end;
  Differing.Free;
end;

function IsImported(const FileName: String): Boolean;
begin
  Result := ListHas(ImportedSaves, FileName);
end;

{ After the patch pass: record the imported saves with the hash they have now, so the uninstaller can
  tell an untouched import (remove it) from one the player has played since (keep it). }
procedure RecordImports;
var
  I: Integer;
  Path: String;
begin
  for I := 0 to ImportedSaves.Count - 1 do
  begin
    Path := ImportedSaves.Strings[I];
    if FileExists(Path) then
      AddManifestLine('import ' + RelToApp(Path) + ' ' + Lowercase(GetSHA256OfFile(Path)))
    else
      Log('imported save vanished before the manifest was written: ' + Path);
  end;
end;

{ ------------------------------------------------------------------ the exe gate }

{ True when Dir holds the one Obscure2.exe the mod's hooks are written for; Problem says why not.
  /FAKEHASH (test only) accepts any exe, still requiring one. }
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
  if SwitchGiven('/FAKEHASH') then
  begin
    Log('test switch /FAKEHASH: the Obscure2.exe check is off for ' + Exe);
    Result := True;
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

function NeedIni: Boolean;
var
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
  if CopyBytes(Dest, Backup) then
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
    if not CopyBytes(FileName, Backup) then
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

{ Patch every game*.sav in Dir. Prefix is the manifest path of that folder: 'Save',
  'coop_profile\remote' (inside the game dir) or "~" (the mod's save folder outside it). }
procedure PatchSavesIn(const Dir, Prefix: String);
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
          Inc(SavesPatched);
          if IsImported(FileName) then
            Log('patched imported ' + FindRec.Name + ' (' + IntToStr(Count) + ' tag(s); the import line covers it)')
          else
          begin
            if Prefix = ModMarker then
              Rel := ModMarker + FindRec.Name
            else
              Rel := Prefix + '\' + FindRec.Name;
            AddManifestLine('save ' + Rel + ' ' + Rel + '.1p.bak');
            Log('patched ' + Rel + ' (MTHC -> 2CHC, ' + IntToStr(Count) + ' tag(s))');
          end;
        end;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

{ ------------------------------------------------------------------ installer events }

function InitializeSetup: Boolean;
var
  Dir, Problem: String;
begin
  Result := True;
  ManifestLine := TStringList.Create;
  AddManifestLine('obscoop install {#AppVersion}');   // the same first line install.ps1 writes
  PreNames := TStringList.Create;
  PreHashes := TStringList.Create;
  ImportedSaves := TStringList.Create;
  SavesPatched := 0;
  { A silent install never sees the directory page, and Inno shows an error dialog for a
    PrepareToInstall failure even in silent mode - which would wait for a click nobody is there to
    give. So when /DIR was passed, the exe gate runs here first and a refusal ends the setup at once. }
  if WizardSilent then
  begin
    Dir := RemoveBackslashUnlessRoot(ExpandConstant('{param:DIR|}'));
    if Dir <> '' then
      if not CheckGameDir(Dir, Problem) then
      begin
        Log('refused (silent): ' + Dir);
        Log(Problem);
        Result := False;
      end;
  end;
end;

{ The "which Steam account" page: only when more than one account has saves on this PC. }
procedure InitializeWizard;
var
  I: Integer;
  Root: String;
begin
  SteamIds := SteamIdsWithSaves;
  Root := SteamRoot;
  if Root = '' then
  begin
    Log('saves: no Steam folder found, nothing to import');
    Exit;
  end;
  Log('saves: ' + IntToStr(SteamIds.Count) + ' Steam account(s) with Obscure II saves in ' + Root);
  if SteamIds.Count <= 1 then
    Exit;
  SavePage := CreateInputOptionPage(wpSelectDir, 'Obscure II saves',
    'More than one Steam account on this PC has Obscure II saves.',
    'Choose the account whose saves the mod should use. The saves are copied; the ones in Steam stay ' +
    'where they are.', True, False);
  for I := 0 to SteamIds.Count - 1 do
    SavePage.Add('Steam account ' + SteamIds.Strings[I] + ' (' +
      IntToStr(SaveCountIn(SteamIdSaveDir(Root, SteamIds.Strings[I]))) + ' save file(s))');
  SavePage.Add('Do not copy any saves');
  SavePage.SelectedValueIndex := 0;
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
    if not WizardSilent then
      MsgBox(Wrappers + ' is in the game folder (DXVK, ReShade or another wrapper). The mod is ' +
        'untested with it. If the game does not start, or the link stays on ''waiting'', remove ' +
        'that file and try again.', mbInformation, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, ModSave, Text: String;
  I: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    AppDir := ExpandConstant('{app}');
    ImportSteamSaves;
    PatchSavesIn(AppDir + '\Save', 'Save');
    ModSave := ModSaveDirOf(AppDir);
    if CompareText(ModSave, AppDir + '\coop_profile\remote') = 0 then
      PatchSavesIn(ModSave, 'coop_profile\remote')
    else
      PatchSavesIn(ModSave, ModMarker);
    RecordImports;
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
      'Start the game with one of the .bat files that are now in the game folder (or the Start menu):' + #13#10 +
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

{ "bak <file> <backup>" / "save <file> <backup>" / "import <file> <sha256>" -> "file|backup" }
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
  AppDir, ManifestPath, Text, Save, Backup, Hash: String;
  Answer: Integer;
  Lines, Baks, Saves, Imports: TStringList;
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
    if not UninstallSilent then
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
  Imports := TStringList.Create;
  SplitLines(Text, Lines);
  CollectPairs(Lines, 'bak', Baks);
  CollectPairs(Lines, 'save', Saves);
  CollectPairs(Lines, 'import', Imports);

  { Inno already removed the files this setup installed (it keeps its own log); this is the rest:
    the backups it made, and the question about the saves. }
  for I := 0 to Baks.Count - 1 do
  begin
    Save := ResolveManifestPath(PairFile(Baks.Strings[I]));
    Backup := ResolveManifestPath(PairBackup(Baks.Strings[I]));
    if not FileExists(Backup) then
      continue;
    if CopyBytes(Backup, Save) then
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
    { A silent uninstall (the test, or a scripted one) has nobody to answer: it puts the saves back,
      which is what the question below defaults to and what install.ps1/uninstall.ps1 do. }
    if UninstallSilent then
      Log('silent uninstall: the ' + IntToStr(Saves.Count) + ' patched save(s) are put back from their .1p.bak')
    else
    begin
      Answer := MsgBox('The installer had switched ' + IntToStr(Saves.Count) + ' save file(s) from the ' +
        'game''s one-player save to real two-player.' + CrLf + CrLf +
        'Put the saves back as they were before the install? (Their .1p.bak copies are next to them.)' + CrLf + CrLf +
        'Choose No if you played with two players since and want to keep those saves - the .1p.bak ' +
        'files are then left in place so nothing is lost.', mbConfirmation, MB_YESNO);
      if Answer = IDNO then
        RestoreSaves := False;
    end;
  end;
  if RestoreSaves then
    for I := 0 to Saves.Count - 1 do
    begin
      Save := ResolveManifestPath(PairFile(Saves.Strings[I]));
      Backup := ResolveManifestPath(PairBackup(Saves.Strings[I]));
      if not FileExists(Backup) then
        continue;
      if CopyBytes(Backup, Save) then
      begin
        DeleteFile(Backup);
        Log('restored save ' + PairFile(Saves.Strings[I]));
      end
      else
        Log('could not restore save ' + PairFile(Saves.Strings[I]) + ' (' + Backup + ' is kept)');
    end
  else
    Log('saves left as they are, ' + IntToStr(Saves.Count) + ' .1p.bak file(s) kept');

  { The saves the installer copied in from Steam: removed again while they are unchanged (the Steam
    originals were never touched). A save the player has played since is left where it is. }
  for I := 0 to Imports.Count - 1 do
  begin
    Save := ResolveManifestPath(PairFile(Imports.Strings[I]));
    Hash := PairBackup(Imports.Strings[I]);
    if not FileExists(Save) then
      continue;
    if CompareText(Lowercase(GetSHA256OfFile(Save)), Lowercase(Hash)) <> 0 then
    begin
      Log('kept the imported save ' + PairFile(Imports.Strings[I]) + ' (it changed after the install)');
      continue;
    end;
    DeleteFile(Save);
    DeleteFile(Save + '.1p.bak');
    Log('removed the imported save ' + PairFile(Imports.Strings[I]));
  end;

  DeleteFile(ManifestPath);
  RemoveDir(AppDir + '\obscoop-relay');
  { the folders the import created, when nothing else is left in them }
  RemoveDir(ModSaveDirOf(AppDir));
  RemoveDir(ExtractFileDir(ModSaveDirOf(AppDir)));
  Lines.Free;
  Baks.Free;
  Saves.Free;
  Imports.Free;
end;
