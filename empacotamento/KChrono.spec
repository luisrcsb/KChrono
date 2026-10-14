# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller — gera KChrono.exe (arquivo único) para Windows.

Uso (na pasta empacotamento):
    pyinstaller --clean --noconfirm KChrono.spec

Empacota o código do projeto + as pastas somente-leitura (interface/, imagens/).
Os arquivos graváveis (dados/kchrono.db, config.json) ficam AO LADO do .exe.
"""
import os

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))

HIDDEN = [
    # uvicorn (carrega back-ends por import dinâmico)
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "websockets",
    # drivers opcionais
    "serial", "serial.tools", "serial.tools.list_ports",
    "bleak",
    # voz (TTS)
    "pyttsx3", "pyttsx3.drivers", "pyttsx3.drivers.sapi5",
    "comtypes", "comtypes.client", "win32com", "win32com.client",
    # pywebview (janela nativa)
    "webview", "webview.platforms", "webview.platforms.edgechromium",
    "webview.platforms.gtk", "webview.platforms.qt", "webview.platforms.cocoa",
    "webview.dom", "webview.localization",
]

a = Analysis(
    [os.path.join(SPECPATH, "kchrono_launcher.py")],
    pathex=[RAIZ],
    binaries=[],
    datas=[
        (os.path.join(RAIZ, "interface"), "interface"),
        (os.path.join(RAIZ, "imagens"), "imagens"),
    ],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["uvloop", "tkinter"],   # uvloop não existe no Windows
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KChrono",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                    # SEM console — app nativo silencioso
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(RAIZ, "imagens", "KCHRONO-LOGO.ico"),
)
