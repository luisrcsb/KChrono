; ============================================================
;  KChrono - instalador Windows (NSIS)
;  Requer: ter compilado KChrono.exe com build-windows.bat
;  Compile este arquivo no NSIS (compilador makensis).
;
;  Gera: KChrono-Setup.exe
; ============================================================
!include "MUI2.nsh"

!define VERSAO "1.0.0"
!define APP "KChrono"
!define FABRICANTE "KChrono / CTAD"
!define EXE "dist\KChrono.exe"

Name "${APP} ${VERSAO}"
OutFile "KChrono-Setup.exe"
InstallDir "$PROGRAMFILES64\${APP}"
InstallDirRegKey HKLM "Software\${APP}" "InstallDir"
RequestExecutionLevel admin
Unicode true
SetCompressor /SOLID lzma

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Section "KChrono" SecPrincipal
  SetOutPath "$INSTDIR"
  File "${EXE}"
  WriteRegStr HKLM "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\${APP}" "Versao" "${VERSAO}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "DisplayName" "${APP}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "Publisher" "${FABRICANTE}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "UninstallString" "$INSTDIR\Desinstalar.exe"
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\${APP}.exe"
  CreateShortcut "$SMPROGRAMS\${APP}\Telão.lnk" "$INSTDIR\${APP}.exe" "--sem-navegador"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${APP}.exe"
SectionEnd

Section "Iniciar com o Windows" SecAuto
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}" '"$INSTDIR\${APP}.exe" --sem-navegador'
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\${APP}.exe"
  Delete "$INSTDIR\Desinstalar.exe"
  Delete "$SMPROGRAMS\${APP}\${APP}.lnk"
  Delete "$SMPROGRAMS\${APP}\Telão.lnk"
  RMDir "$SMPROGRAMS\${APP}"
  Delete "$DESKTOP\${APP}.lnk"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
  DeleteRegKey HKLM "Software\${APP}"
  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}"
  RMDir "$INSTDIR"
  ; Os dados do usuário (banco/config) ficam em %APPDATA%\KChrono
  MessageBox MB_YESNO "Deseja apagar também o histórico e a configuração ($APPDATA\KChrono)?" IDNO fim
    RMDir /r "$APPDATA\KChrono"
  fim:
SectionEnd
