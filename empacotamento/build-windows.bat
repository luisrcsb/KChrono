@echo off
REM ============================================================
REM  KChrono - build do executavel Windows (PyInstaller + pywebview)
REM  Gera: empacotamento\dist\KChrono-<versao>\ (onedir)
REM  Requisitos: WebView2 Runtime (já incluso no Windows 10/11 moderno)
REM
REM  Prefira "python empacotamento\build.py": ele confere a versao,
REM  sincroniza o NSIS e assina o .exe se houver certificado configurado.
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
echo [3/5] Compilando KChrono (onedir, pode demorar alguns minutos)...
python empacotamento\build.py || goto :erro

echo.
echo [4/5] Build completo!
echo.
echo [5/5] Pronto!
echo   Pasta:      %cd%\dist\  (subpasta KChrono-1.1.x, onedir)
echo   Executavel: dentro dessa pasta: KChrono-1.1.x.exe
echo   Janela nativa (WebView2) — SEM navegador, SEM barra de endereço.
echo   Dados (banco/config) em %%APPDATA%%\KChrono no primeiro uso.
echo.
echo Para gerar o instalador NSIS:
echo   1. Instale o NSIS (https://nsis.sourceforge.io/)
echo   2. Compile instalador.nsi no NSIS (makensis instalador.nsi)
echo.
pause
exit /b 0

:erro
echo.
echo ERRO no build. Verifique o Python e a conexao de rede.
pause
exit /b 1
