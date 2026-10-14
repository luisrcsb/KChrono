; ============================================================
;  KChrono - instalador Windows (NSIS)
;  Requer: ter compilado KChrono.exe com build-windows.bat
;  Compile este arquivo no NSIS (compilador makensis).
;
;  Gera: KChrono-Setup.exe
;  App nativo com pywebview (WebView2) — NÃO abre navegador.
; ============================================================
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

!define VERSAO "1.0.0"
!define APP "KChrono"
!define FABRICANTE "KChrono / CTAD"
!define EXE "dist\KChrono.exe"
!define CTAD_EXE "CTAD-Upload-Auto.exe"
!define CTAD_ZIP "CTAD-Upload-Auto-v1.2.4.zip"

Name "${APP} ${VERSAO}"
OutFile "KChrono-Setup.exe"
InstallDir "$PROGRAMFILES64\${APP}"
InstallDirRegKey HKLM "Software\${APP}" "InstallDir"
RequestExecutionLevel admin
Unicode true
SetCompressor /SOLID lzma

; Ícone do instalador e do app
!define MUI_ICON "..\imagens\KCHRONO-LOGO.ico"
!define MUI_UNICON "..\imagens\KCHRONO-LOGO.ico"

; ==================== Variáveis de configuração ====================
Var /GLOBAL TELEMETRIA_DIR
Var /GLOBAL CTAD_DIR
Var /GLOBAL INSTALAR_CTAD
Var /GLOBAL INSTALAR_AUTO

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

; ==================== Instalação ====================
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
  ; Atalhos do menu Iniciar — cada um abre direto na view certa
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} (Operador).lnk" "$INSTDIR\${APP}.exe" ""
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} (Telão).lnk" "$INSTDIR\${APP}.exe" "--telao --fullscreen"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} (Gerente de Pista).lnk" "$INSTDIR\${APP}.exe" "--gerente"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} (Serviço / Headless).lnk" "$INSTDIR\${APP}.exe" "--sem-janela"

  ; Atalhos na área de trabalho
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${APP}.exe" ""
  CreateShortcut "$DESKTOP\${APP} (Telão).lnk" "$INSTDIR\${APP}.exe" "--telao --fullscreen"

  ; Pasta de dados (banco, logs, capturas) — em APPDATA para persistir entre updates
  StrCpy $TELEMETRIA_DIR "$APPDATA\KChrono"
  WriteRegStr HKLM "Software\${APP}" "TelemetriaDir" "$TELEMETRIA_DIR"
  CreateDirectory "$TELEMETRIA_DIR"
SectionEnd

Section "CTAD-Upload-Auto" SecCTAD
  StrCpy $INSTALAR_CTAD 1
  StrCpy $CTAD_DIR "$PROGRAMFILES64\CTAD-Upload-Auto"
  ${If} $INSTALAR_CTAD == 1
    SetOutPath "$CTAD_DIR"
    !define CTAD_ZIP_PATH "..\..\CTAD\downloads\${CTAD_ZIP}"
    ${If} ${FileExists} "${CTAD_ZIP_PATH}"
      File "${CTAD_ZIP_PATH}"
      nsExec::ExecToStack 'powershell -ExecutionPolicy Bypass -NoProfile -Command "try { Expand-Archive -Path \'$CTAD_DIR\${CTAD_ZIP}\' -DestinationPath \'$CTAD_DIR\' -Force } catch { exit 1 }"'
      Pop $0
      ${If} $0 != 0
        MessageBox MB_ICONEXCLAMATION "Falha ao extrair CTAD-Upload-Auto."
        Delete "$CTAD_DIR\${CTAD_ZIP}"
        Abort
      ${EndIf}
      Delete "$CTAD_DIR\${CTAD_ZIP}"
      WriteRegStr HKLM "Software\${APP}" "CTADDir" "$CTAD_DIR"
      CreateDirectory "$SMPROGRAMS\CTAD-Upload-Auto"
      CreateShortcut "$SMPROGRAMS\CTAD-Upload-Auto\CTAD-Upload-Auto.lnk" "$CTAD_DIR\${CTAD_EXE}"
      CreateShortcut "$DESKTOP\CTAD-Upload-Auto.lnk" "$CTAD_DIR\${CTAD_EXE}"
    ${Else}
      MessageBox MB_OK "Arquivo CTAD-Upload-Auto-v1.2.4.zip nao encontrado ao lado do instalador. O CTAD nao sera instalado."
    ${EndIf}
  ${EndIf}
SectionEnd

Section "Iniciar com o Windows (Serviço)" SecAuto
  StrCpy $INSTALAR_AUTO 1
  ${If} $INSTALAR_AUTO == 1
    ; Inicia headless (--sem-janela) para rodar como serviço de fundo
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}_service" '"$INSTDIR\${APP}.exe" --sem-janela'
  ${EndIf}
SectionEnd

; ==================== Desinstalação ====================
Section "Uninstall"
  Delete "$INSTDIR\${APP}.exe"
  Delete "$INSTDIR\Desinstalar.exe"
  Delete "$SMPROGRAMS\${APP}\${APP} (Operador).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Telão).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Gerente de Pista).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Serviço / Headless).lnk"
  Delete "$DESKTOP\${APP}.lnk"
  Delete "$DESKTOP\${APP} (Telão).lnk"
  RMDir "$SMPROGRAMS\${APP}"

  ReadRegStr $0 HKLM "Software\${APP}" "CTADDir"
  ${If} $0 != ""
    Delete "$0\${CTAD_EXE}"
    Delete "$0\config.json"
    RMDir "$0"
    Delete "$SMPROGRAMS\CTAD-Upload-Auto\CTAD-Upload-Auto.lnk"
    Delete "$DESKTOP\CTAD-Upload-Auto.lnk"
    RMDir "$SMPROGRAMS\CTAD-Upload-Auto"
  ${EndIf}

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
  DeleteRegKey HKLM "Software\${APP}"
  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}_service"
  RMDir "$INSTDIR"

  MessageBox MB_YESNO "Deseja apagar também o histórico e a configuração em APPDATA\KChrono?" IDNO fim
    RMDir /r "$APPDATA\KChrono"
  fim:
  ReadRegStr $0 HKLM "Software\${APP}" "TelemetriaDir"
  ${If} $0 != ""
    MessageBox MB_YESNO "Deseja apagar também a pasta de telemetria $0?" IDNO fim2
      RMDir /r "$0"
    fim2:
  ${EndIf}
SectionEnd