; My Store installer (Inno Setup 6). build.ps1 runs this after PyInstaller has produced dist\MyStore.
; Installs to Program Files (admin-only), which is what makes My Store's admin actions safe: nothing it runs
; elevated can be changed by a standard user.

#define AppName "My Store"
#define AppExe "MyStore.exe"
#define AppVersion GetVersionNumbersString(AddBackslash(SourcePath) + "..\dist\MyStore\" + AppExe)

[Setup]
AppId={{6F1C7E52-9B0A-4D8C-A3E1-5B2D9F47C0A8}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=My Store contributors
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=MyStore-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
WizardStyle=modern
WizardImageFile=wizard-large-100.bmp,wizard-large-200.bmp
WizardSmallImageFile=wizard-small-100.bmp,wizard-small-200.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
ChangesAssociations=yes
UsePreviousTasks=yes

[Tasks]
Name: "desktopicon"; Description: "Put a My Store shortcut on the desktop"; GroupDescription: "Shortcuts:"
Name: "background"; Description: "Keep apps updated in the background (runs as you at sign-in and every 6 hours, no admin)"; GroupDescription: "Updates:"; Flags: unchecked
Name: "storelinks"; Description: "Open Microsoft Store links in My Store (you confirm it in Windows Settings next)"; GroupDescription: "Microsoft Store links:"; Flags: unchecked

[InstallDelete]
; upgrades: drop the previous build's runtime so no stale modules are left behind
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\MyStore\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "MyStore.App"; Comment: "Browse, install and update Microsoft Store apps"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "MyStore.App"; Comment: "Browse, install and update Microsoft Store apps"; Tasks: desktopicon

[Registry]
; offers My Store for ms-windows-store:// links in Settings > Default apps; the user makes the choice there
Root: HKLM; Subkey: "Software\Classes\MyStore.StoreLink"; ValueType: string; ValueData: "Microsoft Store link"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\MyStore.StoreLink\DefaultIcon"; ValueType: string; ValueData: """{app}\{#AppExe}"",0"
Root: HKLM; Subkey: "Software\Classes\MyStore.StoreLink\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKLM; Subkey: "Software\MyStore"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\MyStore\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKLM; Subkey: "Software\MyStore\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Browse, install and update Microsoft Store apps"
Root: HKLM; Subkey: "Software\MyStore\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKLM; Subkey: "Software\MyStore\Capabilities\UrlAssociations"; ValueType: string; ValueName: "ms-windows-store"; ValueData: "MyStore.StoreLink"
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\MyStore\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--enable-background"; StatusMsg: "Turning on background updates..."; Tasks: background; Flags: runasoriginaluser runhidden waituntilterminated
Filename: "ms-settings:defaultapps?registeredAppMachine=My%20Store"; Tasks: storelinks; Flags: shellexec runasoriginaluser nowait
Filename: "{app}\{#AppExe}"; Description: "Open My Store now"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""My Store background updates"" /F"; Flags: runhidden; RunOnceId: "RemoveBackgroundTask"

[UninstallDelete]
; admin work files only - the Store queue backups in rslc-backup are kept on purpose
Type: filesandordirs; Name: "{commonappdata}\MyStore\results"
Type: filesandordirs; Name: "{commonappdata}\MyStore\staging"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    Data := ExpandConstant('{localappdata}\MyStore');
    if DirExists(Data) and (MsgBox('Also delete your My Store settings, history and download cache?' + #13#10#13#10 + Data,
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(Data, True, True, True);
  end;
end;
