#ifndef AppVersion
#define AppVersion "0.9.0-beta.2"
#endif
[Setup]
AppId={{FBD1B5E8-E68E-419A-9FB9-DC9FE82F2C86}
AppName=Fotos Claras
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\FotosClaras
DefaultGroupName=Fotos Claras
PrivilegesRequired=lowest
OutputBaseFilename=Fotos-Claras-Setup
OutputDir=..\dist
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
CloseApplications=no
UninstallDisplayIcon={app}\versions\{#AppVersion}\FotosClaras.exe
[Files]
Source: "..\dist\FotosClaras\*"; DestDir: "{app}\versions\{#AppVersion}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "FotosClarasLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{userdesktop}\Fotos Claras"; Filename: "{app}\FotosClarasLauncher.exe"
Name: "{group}\Fotos Claras"; Filename: "{app}\FotosClarasLauncher.exe"
Name: "{group}\Volver a la versión anterior"; Filename: "{app}\FotosClarasLauncher.exe"; Parameters: "--rollback"
[Run]
Filename: "{app}\FotosClarasLauncher.exe"; Flags: nowait postinstall; Check: ShouldLaunch
[Code]
function MoveFileEx(ExistingFile: String; NewFile: String; Flags: Cardinal): Boolean;
  external 'MoveFileExW@kernel32.dll stdcall';
function ShouldLaunch(): Boolean;
var I: Integer;
begin
  Result := True;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOAUTOLAUNCH') = 0 then Result := False;
end;
procedure CurStepChanged(CurStep: TSetupStep);
var OldVersion: AnsiString;
begin
  if CurStep = ssPostInstall then begin
    if LoadStringFromFile(ExpandConstant('{app}\active-version.txt'), OldVersion) then
      if Trim(String(OldVersion)) <> '{#AppVersion}' then
        SaveStringToFile(ExpandConstant('{app}\previous-version.txt'), OldVersion, False);
    SaveStringToFile(ExpandConstant('{app}\active-version.new'), '{#AppVersion}', False);
    if not MoveFileEx(ExpandConstant('{app}\active-version.new'), ExpandConstant('{app}\active-version.txt'), 9) then
      RaiseException('No se pudo activar la nueva version. La anterior sigue disponible.');
  end;
end;
