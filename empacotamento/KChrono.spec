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
    # voz neural offline (Piper + onnxruntime) — o pacote embarca o
    # espeak-ng-data e os binários do onnxruntime, que precisam ir junto.
    "piper", "piper.voice", "piper.config",
    "onnxruntime", "onnxruntime.capi", "onnxruntime.capi.onnxruntime_pybind11_state",
    # pywebview (janela nativa)
    "webview", "webview.platforms", "webview.platforms.edgechromium",
    "webview.platforms.gtk", "webview.platforms.qt", "webview.platforms.cocoa",
    "webview.dom", "webview.localization",
]

#: dados/binários dos motores neurais (espeak-ng-data do piper, DLLs do
#: onnxruntime). Fica vazio se os pacotes não estiverem instalados — o app
#: segue funcionando com o SAPI do Windows.
def _coletar(mod: str):
    try:
        from PyInstaller.utils.hooks import collect_all
        dados, binarios, ocultos = collect_all(mod)
        return dados, binarios, list(ocultos)
    except Exception:
        return [], [], []


_DADOS_VOZ: list = []
_BIN_VOZ: list = []
for _mod in ("piper", "onnxruntime"):
    _d, _b, _o = _coletar(_mod)
    _DADOS_VOZ += _d
    _BIN_VOZ += _b
    HIDDEN += _o

# Modelos neurais (pt_BR-*.onnx + .json) — embarcados para o exe já nascer
# com a voz neural pronta (copiados p/ APPDATA na 1ª execução por _semear_modelos).
_VOZES_NURAIS: list = []
_pasta_vozes = os.path.join(RAIZ, "dados", "vozes")
if os.path.isdir(_pasta_vozes):
    for _arq in sorted(os.listdir(_pasta_vozes)):
        if _arq.endswith((".onnx", ".onnx.json")):
            _VOZES_NURAIS.append((os.path.join(_pasta_vozes, _arq),
                                  os.path.join("dados", "vozes")))

a = Analysis(
    [os.path.join(SPECPATH, "kchrono_launcher.py")],
    pathex=[RAIZ],
    binaries=_BIN_VOZ,
    datas=[
        (os.path.join(RAIZ, "interface"), "interface"),
        (os.path.join(RAIZ, "imagens"), "imagens"),
        # versão do app (o atualizador compara com o canal de atualização)
        (os.path.join(RAIZ, "empacotamento", "versao.json"), "empacotamento"),
    ] + _DADOS_VOZ + _VOZES_NURAIS,
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
