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
python -m PyInstaller --clean --noconfirm KChrono.spec || goto :erro

echo.
echo [4/4] Copiando CTAD-Upload-Auto para o instalador...
if exist "..\..\CTAD\downloads\CTAD-Upload-Auto-v1.2.4.zip" (
    copy "..\..\CTAD\downloads\CTAD-Upload-Auto-v1.2.4.zip" "CTAD-Upload-Auto-v1.2.4.zip"
    echo   CTAD-Upload-Auto-v1.2.4.zip copiado.
) else (
    echo AVISO: CTAD-Upload-Auto-v1.2.4.zip nao encontrado em ..\..\CTAD\downloads\
)

echo.
echo [5/4] Pronto!
echo   Executavel: %cd%\dist\KChrono.exe
echo   Os dados (banco/config) serao criados em %%APPDATA%%\KChrono no primeiro uso.
echo.
echo Para gerar o instalador:
echo   1. Instale o NSIS (https://nsis.sourceforge.io/)
echo   2. Compile instalador.nsi no NSIS (makensis instalador.nsi)
echo   3. O CTAD-Upload-Auto-v1.2.4.zip ja esta na pasta empacotamento\
pause
exit /b 0

:erro
echo.
echo ERRO no build. Verifique o Python e a conexao de rede.
pause
exit /b 1
