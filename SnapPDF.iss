; ============================================================================
; SnapPDF installer  -  Inno Setup script
;
; Build order:
;   1. python installer\build_app.py       <- makes dist\SnapPDF\SnapPDF.exe
;   2. Open THIS file in Inno Setup, click Compile (or press F9)
;   3. The finished installer appears in installer\output\SnapPDFSetup.exe
;
; What this installer does (mirrors SnapShrink exactly):
;   - Installs to a per-user folder - NO admin rights, no UAC prompt
;     (required: config.json lives next to the exe, so the folder must be
;      user-writable; Program Files would break settings saving)
;   - Start Menu shortcut "SnapPDF"
;   - Registers the right-click context menu automatically
;   - Starts the background helper (tray + Ctrl+Alt+P) now and at login
;   - Uninstall reverses all of the above, and nothing else
; ============================================================================

#define MyAppName "SnapPDF"
#define MyAppVersion "1.00.00"
#define MyAppExeName "SnapPDF.exe"
#define MyAppSourceDir "dist\SnapPDF"

[Setup]
; New GUID - never reuse SnapShrink's, they must uninstall independently
AppId={{7A4B9C2D-31E5-4F8A-B6D0-9E2C5F7A1B3E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Vijay Parmar
DefaultDirName={localappdata}\Programs\{#MyAppName}
; No admin prompt at all - installs to the user's own folder:
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=SnapPDFSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut - opens the window
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
; Desktop shortcut (optional tick-box during setup)
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
; Auto-start the background helper (tray + Ctrl+Alt+P) each login. A plain
; Startup-folder shortcut so users can disable it themselves any time
; (shell:startup -> delete), independent of us.
Name: "{userstartup}\{#MyAppName} (background helper)"; \
    Filename: "{app}\{#MyAppExeName}"; Parameters: "--daemon"; \
    WorkingDir: "{app}"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
; Register the right-click menu (the exe registers itself, no shim):
Filename: "{app}\{#MyAppExeName}"; Parameters: "--install-contextmenu"; \
    Flags: runhidden waituntilterminated

; Start the background helper immediately, so Ctrl+Alt+P works right after
; install without waiting for the next login:
Filename: "{app}\{#MyAppExeName}"; Parameters: "--daemon"; \
    Flags: nowait postinstall skipifsilent runasoriginaluser; \
    Description: "Start the background helper now (Ctrl+Alt+P)"

[UninstallRun]
; Order matters:
;   1. Remove registry entries WHILE the exe still exists.
;   2. Kill any running copy so Windows can delete the files.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--uninstall-contextmenu"; \
    Flags: runhidden waituntilterminated; RunOnceId: "UninstallCtxMenu"
Filename: "{cmd}"; Parameters: "/c taskkill /f /im {#MyAppExeName}"; \
    Flags: runhidden waituntilterminated; RunOnceId: "KillSnapPDF"

[Code]
// Placeholder for future edge-case glue (previous-install detection etc.)
