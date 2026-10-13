@echo off
REM ============================================================
REM  KChrono - build do executavel Windows (PyInstaller)
REM  Gera: empacotamento\dist\KChrono.exe
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/4] Instalando dependencias de build...
python -m pip install --upgrade pyinstaller || goto :erro
python -m pip install -r ..\requirements.txt || goto :erro

echo.
echo [2/4] Limpando builds anteriores...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/4] Compilando KChrono.exe (pode demorar alguns minutos)...
pyinstaller --clean --noconfirm KChrono.spec || goto :erro

echo.
echo [4/4] Pronto!
echo   Executavel: %cd%\dist\KChrono.exe
echo   Os dados (banco/config) serao criados ao lado do .exe no primeiro uso.
echo.
echo Para gerar o instalador, abra o instalador.nsi no NSIS e compile.
pause
exit /b 0

:erro
echo.
echo ERRO no build. Verifique o Python e a conexao de rede.
pause
exit /b 1
