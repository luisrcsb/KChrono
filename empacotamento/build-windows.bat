@echo off
REM ============================================================
REM  KChrono - build do executavel Windows (PyInstaller + pywebview)
REM  Gera: empacotamento\dist\KChrono.exe
REM  Requisitos: WebView2 Runtime (já incluso no Windows 10/11 moderno)
REM ============================================================
setlocal
cd /d "%~dp0"

echo [1/5] Instalando dependencias de build...
python -m pip install --upgrade pyinstaller || goto :erro
python -m pip install -r ..\requirements.txt || goto :erro

echo.
echo [2/5] Limpando builds anteriores...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo [3/5] Compilando KChrono.exe (pode demorar alguns minutos)...
python -m PyInstaller --clean --noconfirm KChrono.spec || goto :erro

echo.
echo [4/5] Copiando CTAD-Upload-Auto para o instalador...
if exist "..\..\CTAD\downloads\CTAD-Upload-Auto-v1.2.4.zip" (
    copy "..\..\CTAD\downloads\CTAD-Upload-Auto-v1.2.4.zip" "CTAD-Upload-Auto-v1.2.4.zip"
    echo   CTAD-Upload-Auto-v1.2.4.zip copiado.
) else (
    echo AVISO: CTAD-Upload-Auto-v1.2.4.zip nao encontrado em ..\..\CTAD\downloads\
)

echo.
echo [5/5] Pronto!
echo   Executavel: %cd%\dist\KChrono.exe
echo   Janela nativa (WebView2) — SEM navegador, SEM barra de endereço.
echo   Dados (banco/config) em %%APPDATA%%\KChrono no primeiro uso.
echo.
echo Para gerar o instalador NSIS:
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
