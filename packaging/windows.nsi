Unicode True
!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"
!ifndef APP_VERSION
!define APP_VERSION "0.4.1"
!endif
Name "Voice Loop"
OutFile "..\dist\VoiceLoop-${APP_VERSION}-windows-x64-setup.exe"
InstallDir "$PROGRAMFILES64\VoiceLoop"
InstallDirRegKey HKLM "Software\VoiceLoop" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
ShowInstDetails show
BrandingText "Voice Loop • Local audio, without a meeting bot"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TEXT "Install Voice Loop and its virtual audio devices.$\r$\n$\r$\nVB-CABLE and Hi-Fi Cable are made by VB-Audio Software (www.vb-cable.com). They are donationware; contributions are welcome at vb-audio.com.$\r$\n$\r$\nAudio setup downloads Hi-Fi Cable from VB-Audio. Windows may request driver approval and a restart."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TEXT "Voice Loop is installed. Open it from the Start menu.$\r$\n$\r$\nIf Windows needs a restart, restart first, then open Audio setup to finish configuring VoiceLoop Mic and VoiceLoop Speaker."
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "This installer requires Windows x64."
    Abort
  ${EndIf}
FunctionEnd

Section "Voice Loop desktop app" App
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "..\dist\VoiceLoop\*"
  SetOutPath "$INSTDIR\drivers\vbcable"
  File /r "vendor\vbcable\*"
  SetOutPath "$INSTDIR"
  File "DRIVER-NOTICE.txt"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\Voice Loop"
  CreateShortcut "$SMPROGRAMS\Voice Loop\Voice Loop.lnk" "$INSTDIR\VoiceLoop.exe"
  WriteRegStr HKLM "Software\VoiceLoop" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceLoop" "DisplayName" "Voice Loop"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceLoop" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceLoop" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceLoop" "NoModify" 1
  WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceLoop" "NoRepair" 1
SectionEnd

Section "Virtual audio devices (VB-Audio donationware)" Drivers
  DetailPrint "Installing VB-CABLE and downloading Hi-Fi Cable from VB-Audio…"
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\_internal\voiceloop\resources\windows-audio.ps1" -CablePackage "$INSTDIR\drivers\vbcable"'
  Pop $0
  ${If} $0 == 3010
    SetRebootFlag true
    DetailPrint "Restart Windows, then open Audio setup to finish device naming."
  ${ElseIf} $0 != 0
    DetailPrint "Audio setup needs attention. See $APPDATA\VoiceLoop\setup.log."
    MessageBox MB_ICONEXCLAMATION|MB_OK "Voice Loop installed, but audio setup did not finish. Open Audio setup to retry. Details: $APPDATA\VoiceLoop\setup.log" /SD IDOK
    SetErrorLevel 1
  ${EndIf}
SectionEnd

Section "Uninstall"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "VoiceLoop"
  SetShellVarContext all
  Delete "$SMPROGRAMS\Voice Loop\Voice Loop.lnk"
  RMDir "$SMPROGRAMS\Voice Loop"
  Delete "$INSTDIR\VoiceLoop.exe"
  Delete "$INSTDIR\DRIVER-NOTICE.txt"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$INSTDIR\drivers"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKLM "Software\VoiceLoop"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\VoiceLoop"
  ; Shared drivers and user recordings remain. Vendor uninstallers own driver removal.
SectionEnd
