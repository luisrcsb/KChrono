; ============================================================
;  KChrono - instalador Windows (NSIS)
;  Requer: ter compilado KChrono.exe com build-windows.bat
;  Compile este arquivo no NSIS (compilador makensis).
;
;  Gera: KChrono-Setup.exe
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

; ==================== Variáveis de configuração ====================
; Telemetria (integração com outros sistemas)
Var /GLOBAL TELEMETRIA_DIR
Var /GLOBAL TELEMETRIA_EXISTENTE

; CTAD-Upload-Auto
Var /GLOBAL INSTALAR_CTAD
Var /GLOBAL CTAD_DIR

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
Page Custom MinhaPaginaTelemetria
Page Custom MinhaPaginaCTAD
Page Custom MinhaPaginaAutoStart
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

; ==================== Páginas customizadas ====================

; --- Pasta de telemetria (integração) ---
Function MinhaPaginaTelemetria
  !insertmacro MUI_HEADER_TEXT "Pasta de Telemetria" \
    "Escolha onde ficará a pasta de telemetria (dados brutos de voltas). \
     Outros sistemas (ex.: app de análise) podem ler desta pasta."
  ${NSD_CreateLabel} 0 30 100% 14u "Pasta de telemetria:"
  ${NSD_CreateDirRequest} 0 44u 100% 18u "$PROGRAMFILES64\KChrono\Telemetria"
  Pop $TELEMETRIA_DIR
  ${NSD_AddStyle} $TELEMETRIA_DIR ${WS_VISIBLE}|${WS_TABSTOP}|${WS_GROUP}|${ES_AUTOHSCROLL}
  ${GetParameters} $0
  ${NSD_OnChange} $TELEMETRIA_DIR OnTelemetriaChange
FunctionEnd

Function OnTelemetriaChange
  ${NSD_GetText} $TELEMETRIA_DIR $TELEMETRIA_DIR
  ${If} ${FileExists} "$TELEMETRIA_DIR\*"
    StrCpy $TELEMETRIA_EXISTENTE "1"
  ${Else}
    StrCpy $TELEMETRIA_EXISTENTE "0"
  ${EndIf}
FunctionEnd

; --- CTAD-Upload-Auto (PDF) ---
Function MinhaPaginaCTAD
  !insertmacro MUI_HEADER_TEXT "CTAD-Upload-Auto (v1.2.4)" \
    "Incluir o CTAD-Upload-Auto para geração de PDFs de sessão/campeonato. \
     Requer Java 17+ instalado."
  ${NSD_CreateCheckbox} 0 30u 100% 14u "Instalar CTAD-Upload-Auto v1.2.4 (Windows 64-bit)" $INSTALAR_CTAD
  ${NSD_CreateLabel} 0 50u 100% 14u "Pasta de instalação do CTAD:"
  ${NSD_CreateDirRequest} 0 64u 100% 18u "$PROGRAMFILES64\CTAD-Upload-Auto"
  Pop $CTAD_DIR
FunctionEnd

; --- Iniciar com o Windows ---
Function MinhaPaginaAutoStart
  !insertmacro MUI_HEADER_TEXT "Iniciar com o Windows" \
    "O KChrono pode iniciar automaticamente ao ligar o computador (modo serviço, sem navegador)."
  ${NSD_CreateCheckbox} 0 30u 100% 14u "Iniciar KChrono automaticamente com o Windows" $0
  Pop $0
  StrCpy $INSTALAR_AUTO 0
  ${If} $0 == 1
    StrCpy $INSTALAR_AUTO 1
  ${EndIf}
FunctionEnd

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
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\${APP}.exe"
  CreateShortcut "$SMPROGRAMS\${APP}\Telão.lnk" "$INSTDIR\${APP}.exe" "--sem-navegador"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${APP}.exe"

  ; Salva pasta de telemetria escolhida
  ${NSD_GetText} $TELEMETRIA_DIR $TELEMETRIA_DIR
  WriteRegStr HKLM "Software\${APP}" "TelemetriaDir" "$TELEMETRIA_DIR"
SectionEnd

Section "CTAD-Upload-Auto" SecCTAD
  ${NSD_GetState} $INSTALAR_CTAD $INSTALAR_CTAD
  ${If} $INSTALAR_CTAD == ${BST_CHECKED}
    SetOutPath "$CTAD_DIR"
    ; Extrai o zip do CTAD (deve estar na mesma pasta do instalador)
    !define CTAD_ZIP_PATH "..\..\CTAD\downloads\${CTAD_ZIP}"
    ${If} ${FileExists} "${CTAD_ZIP_PATH}"
      File "${CTAD_ZIP_PATH}"
      ; Extrai usando 7zip (precisa estar no PATH) ou PowerShell
      nsExec::ExecToStack 'powershell -Command "Expand-Archive -Path \'$CTAD_DIR\${CTAD_ZIP}\' -DestinationPath \'$CTAD_DIR\' -Force"'
      Pop $0
      Delete "$CTAD_DIR\${CTAD_ZIP}"
      WriteRegStr HKLM "Software\${APP}" "CTADDir" "$CTAD_DIR"
      CreateDirectory "$SMPROGRAMS\CTAD-Upload-Auto"
      CreateShortcut "$SMPROGRAMS\CTAD-Upload-Auto\CTAD-Upload-Auto.lnk" "$CTAD_DIR\${CTAD_EXE}"
      CreateShortcut "$DESKTOP\CTAD-Upload-Auto.lnk" "$CTAD_DIR\${CTAD_EXE}"
    ${Else}
      MessageBox MB_ICONWARNING "Arquivo ${CTAD_ZIP} não encontrado ao lado do instalador.\nO CTAD-Upload-Auto não foi instalado."
    ${EndIf}
  ${EndIf}
SectionEnd

Section "Iniciar com o Windows" SecAuto
  ${NSD_GetState} $INSTALAR_AUTO $INSTALAR_AUTO
  ${If} $INSTALAR_AUTO == ${BST_CHECKED}
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}" '"$INSTDIR\${APP}.exe" --sem-navegador'
  ${EndIf}
SectionEnd

; ==================== Desinstalação ====================
Section "Uninstall"
  Delete "$INSTDIR\${APP}.exe"
  Delete "$INSTDIR\Desinstalar.exe"
  Delete "$SMPROGRAMS\${APP}\${APP}.lnk"
  Delete "$SMPROGRAMS\${APP}\Telão.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir "$SMPROGRAMS\${APP}"

  ; Remove CTAD se foi instalado
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
  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}"
  RMDir "$INSTDIR"

  ; Dados do usuário (pergunta)
  MessageBox MB_YESNO "Deseja apagar também o histórico e a configuração ($APPDATA\KChrono)?" IDNO fim
    RMDir /r "$APPDATA\KChrono"
  fim:
  ; Pasta de telemetria (pergunta separada)
  ReadRegStr $0 HKLM "Software\${APP}" "TelemetriaDir"
  ${If} $0 != ""
    MessageBox MB_YESNO "Deseja apagar também a pasta de telemetria ($0)?" IDNO fim2
      RMDir /r "$0"
    fim2:
  ${EndIf}
SectionEnd