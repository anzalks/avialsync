#define MyAppName "AvialSync"
#define MyAppVersion GetEnv("AVIALSYNC_VERSION")
#define MyAppPublisher "AvialSync contributors"
#define MyAppExeName "avialsync.exe"

[Setup]
AppId={{D22B1886-CB89-4D3D-94F6-3D3C2CD8ABF0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\installer-output
OutputBaseFilename=AvialSync-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=avialsync.ico
ArchitecturesInstallIn64BitMode=x64 arm64

[Files]
Source: "..\..\dist\avialsync\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
