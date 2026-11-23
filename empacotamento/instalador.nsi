; ============================================================
;  KChrono - instalador Windows (NSIS)
;  Requer: ter compilado a pasta dist\KChrono-<versão>\ com build-windows.bat
;  Compile este arquivo no NSIS (compilador makensis).
;
;  Gera: KChrono-Setup-<versão com hífens>.exe (ex.: KChrono-Setup-1-2-5.exe)
;  App nativo com pywebview (WebView2) — NÃO abre navegador.
;
;  Metadados do instalador (VIProductVersion / VIAddVersionKey) preenchidos:
;  instalador sem informações de versão/empresa é um gatilho clássico de
;  heurística de antivírus. O binário do app é onedir (sem auto-extração).
; ============================================================
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

; VERSAO e VERSAO_ARQ são sincronizados com versao.json por build.py
!define VERSAO "1.2.5"
!define VERSAO_ARQ "1-2-5"
!define APP "KChrono"
!define FABRICANTE "KChrono"
!define DESCRICAO "KChrono - Cronometragem de Kart"
!define COPYRIGHT "Copyright (C) 2026 Raphael Belowodski"
!define PASTA_APP "dist\KChrono-${VERSAO}"

Name "${APP} ${VERSAO}"
OutFile "KChrono-Setup-${VERSAO_ARQ}.exe"
InstallDir "$PROGRAMFILES64\${APP}"
InstallDirRegKey HKLM "Software\${APP}" "InstallDir"
RequestExecutionLevel admin
Unicode true
SetCompressor /SOLID lzma

; ---- Metadados do instalador (Propriedades → Detalhes) ----------------
VIProductVersion "${VERSAO}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "CompanyName" "${FABRICANTE}"
VIAddVersionKey "FileDescription" "${DESCRICAO}"
VIAddVersionKey "FileVersion" "${VERSAO}"
VIAddVersionKey "ProductVersion" "${VERSAO}"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "OriginalFilename" "KChrono-Setup-${VERSAO_ARQ}.exe"

; Ícone do instalador e do app
!define MUI_ICON "..\imagens\KCHRONO-LOGO.ico"
!define MUI_UNICON "..\imagens\KCHRONO-LOGO.ico"

; ==================== Variáveis de configuração ====================
Var /GLOBAL TELEMETRIA_DIR

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

; Tela final: opção (marcada por padrão) de abrir o KChrono já instalado.
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP}-${VERSAO}.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Iniciar o KChrono agora"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

; ==================== Instalação ====================
Section "KChrono" SecPrincipal
  ; FECHA O KCHRONO: encerra Operador, Telão, Gerente e Serviço. Repete até não
  ; sobrar processo, porque o WebView2 mantém processos filhos por alguns
  ; instantes e o File abaixo falharia com "arquivo em uso".
  StrCpy $2 0
  ${Do}
    nsExec::ExecToStack 'taskkill /IM ${APP}*.exe /T /F'
    Pop $0              ; código de saída: 128 = nenhum processo encontrado
    ${If} $0 == 128
      ${Break}
    ${EndIf}
    Sleep 500
    IntOp $2 $2 + 1
  ${LoopWhile} $2 < 12

  ; DESINSTALA A VERSÃO ANTERIOR: roda o desinstalador antigo em modo silencioso
  ; (/S não pergunta nada e preserva os dados do usuário em APPDATA\KChrono).
  ; Depois aguarda ele terminar de se remover para não travar o novo arquivo.
  ${If} ${FileExists} "$INSTDIR\Desinstalar.exe"
    ExecWait '"$INSTDIR\Desinstalar.exe" /S' $3
    StrCpy $2 0
    ${Do}
      ${IfNot} ${FileExists} "$INSTDIR\Desinstalar.exe"
        ${Break}
      ${EndIf}
      Sleep 300
      IntOp $2 $2 + 1
    ${LoopWhile} $2 < 20
  ${EndIf}

  ; LIMPEZA RESIDUAL: garante que não sobrou resto da versão anterior (exe com
  ; versão no nome, atalhos e registro), mesmo que não houvesse desinstalador.
  ; Os dados do usuário (APPDATA\KChrono: banco, config, capturas) ficam salvos.
  Delete "$INSTDIR\${APP}*.exe"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir /r "$INSTDIR\_internal"
  RMDir /r "$SMPROGRAMS\${APP}"
  Delete "$DESKTOP\${APP}*.lnk"
  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}_service"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"

  ; Libera a porta padrão (8780) no firewall do Windows para a Gestão Remota
  ; (QR Code). Sem isso o celular não consegue alcançar o servidor.
  nsExec::ExecToStack 'netsh advfirewall firewall add rule name="KChrono" dir=in action=allow protocol=TCP localport=8780'
  Pop $0

  SetOverwrite on
  SetOutPath "$INSTDIR"
  ; App onedir: copia a pasta inteira (exe + _internal). Sem auto-extração
  ; em %TEMP% na abertura, o que evita o falso positivo do tipo PDM.
  File /r "${PASTA_APP}\*.*"
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
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} v${VERSAO} (Operador).lnk" "$INSTDIR\${APP}-${VERSAO}.exe" ""
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} v${VERSAO} (Telão).lnk" "$INSTDIR\${APP}-${VERSAO}.exe" "--telao --fullscreen"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} v${VERSAO} (Gerente de Pista).lnk" "$INSTDIR\${APP}-${VERSAO}.exe" "--gerente"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP} v${VERSAO} (Serviço).lnk" "$INSTDIR\${APP}-${VERSAO}.exe" "--sem-janela"

  ; Atalhos na área de trabalho - versão no nome (rastreabilidade) e nome fixo
  ; (estável) para que o operador sempre encontre o mesmo ícone após updates
  CreateShortcut "$DESKTOP\${APP} v${VERSAO}.lnk" "$INSTDIR\${APP}-${VERSAO}.exe" ""
  CreateShortcut "$DESKTOP\${APP} v${VERSAO} (Telão).lnk" "$INSTDIR\${APP}-${VERSAO}.exe" "--telao --fullscreen"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${APP}-${VERSAO}.exe" ""
  CreateShortcut "$DESKTOP\${APP} (Telão).lnk" "$INSTDIR\${APP}-${VERSAO}.exe" "--telao --fullscreen"

  ; Pasta de dados (banco, logs, capturas) — em APPDATA para persistir entre updates
  StrCpy $TELEMETRIA_DIR "$APPDATA\KChrono"
  WriteRegStr HKLM "Software\${APP}" "TelemetriaDir" "$TELEMETRIA_DIR"
  CreateDirectory "$TELEMETRIA_DIR"
SectionEnd

Section "Iniciar com o Windows (Serviço)" SecAuto
  MessageBox MB_YESNO "Deseja iniciar o KChrono automaticamente com o Windows?" IDNO fim
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}_service" '"$INSTDIR\${APP}-${VERSAO}.exe" --sem-janela'
  fim:
SectionEnd

; ==================== Desinstalação ====================
Section "Uninstall"
  ; fecha o app para poder apagar o exe
  nsExec::ExecToStack 'taskkill /IM ${APP}*.exe /T /F'
  Pop $0
  Sleep 500

  ; guarda a pasta de telemetria ANTES de apagar o registro
  ReadRegStr $1 HKLM "Software\${APP}" "TelemetriaDir"

  Delete "$INSTDIR\${APP}*.exe"
  Delete "$INSTDIR\Desinstalar.exe"
  Delete "$SMPROGRAMS\${APP}\${APP} (Operador).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Telão).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Gerente de Pista).lnk"
  Delete "$SMPROGRAMS\${APP}\${APP} (Serviço / Headless).lnk"
  RMDir /r "$SMPROGRAMS\${APP}"
  Delete "$DESKTOP\${APP}*.lnk"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"
  DeleteRegKey HKLM "Software\${APP}"
  nsExec::ExecToStack 'netsh advfirewall firewall delete rule name="KChrono"'
  Pop $0
  DeleteRegValue HKLM "Software\Microsoft\Windows\CurrentVersion\Run" "${APP}_service"
  RMDir /r "$INSTDIR"

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