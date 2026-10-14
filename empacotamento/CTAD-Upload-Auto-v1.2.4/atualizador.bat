@echo off
REM CTAD Upload Auto — atualizador (lançado pelo próprio app).
REM Uso: atualizador.bat "pasta_instal" "pacote.zip" "exe" pid_proprio matar_outras(0/1) sha256
REM Espera o app sair, fecha outras cópias (se autorizado), guarda .bak,
REM extrai, valida, reabre o app e se apaga. NÃO apaga config/estado/logs.
setlocal EnableDelayedExpansion
set INST=%~1
set ZIP=%~2
set EXE=%~3
set MEUPID=%~4
set KILL=%~5
set SHA=%~6
set LOG=%INST%\atualizacao.log
echo [%date% %time%] Atualizador iniciado >> "%LOG%"

:aguardar
REM Espera o app original sair (máx 60 tentativas = ~60s)
set /a WAIT=0
:aguardar
tasklist /FI "PID eq %MEUPID%" /FO LIST 2>nul | findstr /R /C:"^PID:  *%MEUPID% *$" >nul
if not errorlevel 1 (
  if !WAIT! GEQ 60 (
    echo [%date% %time%] TIMEOUT: app nao fechou em 60s. Abortando. >> "%LOG%"
    exit /b 1
  )
  timeout /t 1 /nobreak >nul
  set /a WAIT+=1
  goto aguardar
)

if "%KILL%"=="1" (
  echo [%date% %time%] Fechando outras copias de %EXE% >> "%LOG%"
  for /f "tokens=1,2 delims=," %%a in ('tasklist /FI "IMAGENAME eq %EXE%" /FO CSV /NH 2^>nul') do (
    set P=%%b
    set P=!P:"=!
    echo !P! | findstr /R "^[0-9][0-9]*$" >nul
    if not errorlevel 1 (
      if not "!P!"=="%MEUPID%" taskkill /F /PID !P! >nul 2>&1
    )
  )
  timeout /t 2 /nobreak >nul
)

echo [%date% %time%] Verificando hash SHA256... >> "%LOG%"
for /f %%h in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 ''%ZIP%'').Hash"') do set GOT=%%h
if /i not "%GOT%"=="%SHA%" (
  echo [%date% %time%] FALHA: hash nao confere. Nada foi alterado. >> "%LOG%"
  exit /b 1
)
echo [%date% %time%] Hash SHA256 OK. >> "%LOG%"

if exist "%INST%\%EXE%.bak" del "%INST%\%EXE%.bak" >nul 2>&1
ren "%INST%\%EXE%" "%EXE%.bak" >nul 2>&1
if not exist "%INST%\%EXE%.bak" (
  echo [%date% %time%] FALHA: nao consegui guardar backup. Nada foi alterado. >> "%LOG%"
  exit /b 1
)
echo [%date% %time%] Backup OK. Extraindo... >> "%LOG%"
powershell -NoProfile -Command "Expand-Archive -Path '%ZIP%' -DestinationPath '%INST%' -Force"
if errorlevel 1 (
  echo [%date% %time%] FALHA: extracao falhou, restaurando backup. >> "%LOG%"
  if exist "%INST%\%EXE%" del "%INST%\%EXE%" >nul 2>&1
  ren "%INST%\%EXE%.bak" "%EXE%" >nul 2>&1
  exit /b 1
)
del "%ZIP%" >nul 2>&1
echo [%date% %time%] Atualizado com sucesso. Backup em %EXE%.bak >> "%LOG%"
start "" "%INST%\%EXE%"
(goto) 2>nul & del "%~f0"
