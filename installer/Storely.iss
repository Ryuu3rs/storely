; Storely installer (Inno Setup 6). build.ps1 runs this after PyInstaller has produced dist\Storely:
;   ISCC /DArch=x64 installer\Storely.iss      (or /DArch=arm64 on an ARM64 build)
; Installs to Program Files (admin-only), which is what makes Storely's admin actions safe: nothing it runs
; elevated can be changed by a standard user.

#ifndef Arch
  #define Arch "x64"
#endif
#define AppName "Storely"
#define AppExe "Storely.exe"
#define AppVersion GetVersionNumbersString(AddBackslash(SourcePath) + "..\dist\Storely\" + AppExe)
#define AppUrl "https://github.com/Ryuu3rs/storely"

[Setup]
; same AppId as "My Store" (this app's name before 1.2), so installing upgrades it
AppId={{6F1C7E52-9B0A-4D8C-A3E1-5B2D9F47C0A8}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Storely contributors
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
UsePreviousAppDir=no
DisableProgramGroupPage=yes
PrivilegesRequired=admin
#if Arch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif
MinVersion=10.0.17763
OutputDir=..\dist
OutputBaseFilename=Storely-Setup-{#AppVersion}-{#Arch}
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
Name: "desktopicon"; Description: "Put an Storely shortcut on the desktop"; GroupDescription: "Shortcuts:"
Name: "background"; Description: "Keep apps updated in the background (runs as you at sign-in and every 6 hours, no admin)"; GroupDescription: "Updates:"; Flags: unchecked
Name: "storelinks"; Description: "Open Microsoft Store links in Storely (you confirm it in Windows Settings next)"; GroupDescription: "Microsoft Store links:"; Flags: unchecked

[InstallDelete]
; upgrades: drop the previous build's runtime so no stale modules are left behind
Type: filesandordirs; Name: "{app}\_internal"
; "My Store" (before 1.2): its program folder and shortcuts - settings are carried over by the app itself
Type: filesandordirs; Name: "{autopf}\My Store"
Type: files; Name: "{autoprograms}\My Store.lnk"
Type: files; Name: "{autodesktop}\My Store.lnk"

[Files]
Source: "..\dist\Storely\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Storely.App"; Comment: "Install and update every Windows app, without the jams"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "Storely.App"; Comment: "Install and update every Windows app, without the jams"; Tasks: desktopicon

[Registry]
; the old name's registrations
Root: HKLM; Subkey: "Software\Classes\MyStore.StoreLink"; Flags: deletekey
Root: HKLM; Subkey: "Software\MyStore"; Flags: deletekey
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueName: "My Store"; Flags: deletevalue
; storely:// - notification buttons ("Update all") start or reach the app through this
Root: HKLM; Subkey: "Software\Classes\storely"; ValueType: string; ValueData: "URL:Storely"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\storely"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKLM; Subkey: "Software\Classes\storely\DefaultIcon"; ValueType: string; ValueData: """{app}\{#AppExe}"",0"
Root: HKLM; Subkey: "Software\Classes\storely\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
; offers Storely for ms-windows-store:// links in Settings > Default apps; the user makes the choice there
Root: HKLM; Subkey: "Software\Classes\Storely.StoreLink"; ValueType: string; ValueData: "Microsoft Store link"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\Storely.StoreLink\DefaultIcon"; ValueType: string; ValueData: """{app}\{#AppExe}"",0"
Root: HKLM; Subkey: "Software\Classes\Storely.StoreLink\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKLM; Subkey: "Software\Storely"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Storely\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKLM; Subkey: "Software\Storely\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Install and update every Windows app, without the jams"
Root: HKLM; Subkey: "Software\Storely\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKLM; Subkey: "Software\Storely\Capabilities\UrlAssociations"; ValueType: string; ValueName: "ms-windows-store"; ValueData: "Storely.StoreLink"
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "Software\Storely\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "--enable-background"; StatusMsg: "Turning on background updates..."; Tasks: background; Flags: runasoriginaluser runhidden waituntilterminated
Filename: "ms-settings:defaultapps?registeredAppMachine=Storely"; Tasks: storelinks; Flags: shellexec runasoriginaluser nowait
Filename: "{app}\{#AppExe}"; Description: "Open Storely now"; Flags: postinstall nowait skipifsilent runasoriginaluser
; self-update runs setup silently: reopen the app afterwards
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""Storely background updates"" /F"; Flags: runhidden; RunOnceId: "RemoveBackgroundTask"
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""My Store background updates"" /F"; Flags: runhidden; RunOnceId: "RemoveOldBackgroundTask"

[UninstallDelete]
; admin work files only - the Store queue backups in rslc-backup are kept on purpose
Type: filesandordirs; Name: "{commonappdata}\Storely\results"
Type: filesandordirs; Name: "{commonappdata}\Storely\staging"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  { the pre-1.2 "My Store" lives in another folder, so Windows' restart manager won't close it for us }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM MyStore.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(2000);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM MyStore.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    Data := ExpandConstant('{localappdata}\Storely');
    if DirExists(Data) and (MsgBox('Also delete your Storely settings, history and download cache?' + #13#10#13#10 + Data,
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(Data, True, True, True);
  end;
end;
