; Script Inno Setup - cree JARVIS_Setup.exe (installateur Windows)
; Prerequis : dist\JARVIS\ doit exister (pyinstaller jarvis.spec)

#define MyAppName "J.A.R.V.I.S"
#define MyAppVersion "4.0"
#define MyAppExe "JARVIS.exe"

[Setup]
AppId={{B7E1C0D2-5A4F-4C3B-9D6E-7A1F2B3C4D5E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Rahim Batchabi
DefaultDirName={autopf}\JARVIS
DefaultGroupName=JARVIS
OutputDir=installer_output
OutputBaseFilename=JARVIS_Setup
SetupIconFile=assets\jarvis.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Creer un raccourci sur le Bureau"; Flags: unchecked

[Files]
Source: "dist\JARVIS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\J.A.R.V.I.S"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Modifier mes cles API (.env)"; Filename: "notepad.exe"; Parameters: """{userappdata}\JARVIS\.env"""
Name: "{group}\Desinstaller J.A.R.V.I.S"; Filename: "{uninstallexe}"
Name: "{autodesktop}\J.A.R.V.I.S"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Lancer J.A.R.V.I.S maintenant"; Flags: nowait postinstall skipifsilent
