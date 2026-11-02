; ============================================================
;  KChrono - instalador Windows (NSIS)
;  Requer: ter compilado KChrono.exe com build-windows.bat
;  Compile este arquivo no NSIS (compilador makensis).
;
;  Gera: KChrono-Setup-<versão com hífens>.exe (ex.: KChrono-Setup-1-0-13.exe)
;  App nativo com pywebview (WebView2) — NÃO abre navegador.
; ============================================================
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

; VERSAO e VERSAO_ARQ são sincronizados com versao.json por build.py
!define VERSAO "1.0.13"
!define VERSAO_ARQ "1-0-13"
!define APP "KChrono"
!define FABRICANTE "KChrono"
!define EXE "dist\KChrono.exe"

Name "${APP} ${VERSAO}"
OutFile "KChrono-Setup-${VERSAO_ARQ}.exe"
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
  ; BLINDAGEM: fecha o KChrono se estiver rodando (atualização por cima).
  ; Sem isso, o File abaixo falha com "arquivo em uso" quando o app está aberto.
  nsExec::ExecToStack 'taskkill /IM KChrono.exe /T /F'
  Pop $0
  Sleep 800

  ; ATUALIZAÇÃO LIMPA: remove a versão anterior (arquivos, atalhos e
  ; registro) antes de copiar a nova. Feito aqui, sem chamar o desinstalador
  ; antigo, para não abrir diálogos no meio da instalação. Os dados do
  ; usuário (APPDATA\KChrono: banco, config, capturas) são preservados.
  Delete "$INSTDIR\${APP}.exe"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir /r "$SMPROGRAMS\${APP}"
  Delete "$DESKTOP\${APP}*.lnk"
  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}_service"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"

  SetOutPath "$INSTDIR"
  File "${EXE}"
  WriteRegStr HKLM "Software\${APP}" "InstallDir" "$INSTDIR"
  WriteRegStr HKLM "Software\${APP}" "Versao" "${VERSAO}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "DisplayName" "${APP}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "Publisher" "${FABRICANTE}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}" "QuietUninstallString" '"$INSTDIR\Desinstalar.exe" /S'
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

Section "Iniciar com o Windows (Serviço)" SecAuto
  StrCpy $INSTALAR_AUTO 1
  ${If} $INSTALAR_AUTO == 1
    ; Inicia headless (--sem-janela) para rodar como serviço de fundo
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}_service" '"$INSTDIR\${APP}.exe" --sem-janela'
  ${EndIf}
SectionEnd

; ==================== Desinstalação ====================
Section "Uninstall"
  ; fecha o app para poder apagar o exe
  nsExec::ExecToStack 'taskkill /IM ${APP}.exe /T /F'
  Pop $0
  Sleep 500

  ; guarda a pasta de telemetria ANTES de apagar o registro
  ReadRegStr $1 HKLM "Software\${APP}" "TelemetriaDir"

  Delete "$INSTDIR\${APP}.exe"
  Delete "$INSTDIR\Desinstalar.exe"
  Delete "$SMPROGRAMS\${APP}\${APP} (Operador).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Telão).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Gerente de Pista).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Serviço / Headless).lnk"
  RMDir "$SMPROGRAMS\${APP}"
  Delete "$DESKTOP\${APP}.lnk"
  Delete "$DESKTOP\${APP} (Telão).lnk"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
  DeleteRegKey HKLM "Software\${APP}"
  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}_service"
  RMDir "$INSTDIR"

  ; em modo silencioso (/S) nunca pergunta nada — só o desinstalador manual
  ; oferece apagar os dados do usuário
  ${IfNot} ${Silent}
    MessageBox MB_YESNO "Deseja apagar também o histórico e a configuração em APPDATA\KChrono?" IDNO fim
      RMDir /r "$APPDATA\KChrono"
    fim:
    ${If} $1 != ""
      MessageBox MB_YESNO "Deseja apagar também a pasta de telemetria $1?" IDNO fim2
        RMDir /r "$1"
      fim2:
    ${EndIf}
  ${EndIf}
SectionEnd