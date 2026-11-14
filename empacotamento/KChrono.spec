# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller — gera o app do KChrono.

  Windows → dist/KChrono-<versão>/  (onedir, janela nativa WebView2)
  Linux   → dist/KChrono-<versão>/  (onedir; depois vira o AppImage e a
                                     interface abre no navegador)

Uso:  python empacotamento/build.py   (ou pyinstaller --clean --noconfirm
                                       KChrono.spec na pasta empacotamento)

Empacota o código do projeto + as pastas somente-leitura (interface/,
imagens/). Os arquivos graváveis (banco, config.json) ficam em %APPDATA%
(Windows) ou ~/.local/share (Linux).

Notas de empacotamento (redução de falso positivo de antivírus — sem
ofuscação nem evasão, apenas builds convencionais e documentados):

  · ``upx=False`` — o UPX comprime o executável e é um dos maiores gatilhos
    de heurística (binário "empacotado" parece malware).
  · ``onedir`` no Windows — o ``onefile`` se auto-extrai para ``%TEMP%\\_MEIxxxx``
    a cada abertura, comportamento que a defesa proativa (PDM) trata como
    suspeito. No onedir os arquivos ficam ao lado do executável.
  · ``version=`` — metadados completos (empresa, produto, descrição, versão,
    copyright) no ``VS_VERSION_INFO`` do .exe.
  · ``uac_admin=False`` — o app não pede administrador (só escuta a porta
    8780, acima das privilegiadas).
"""
import os
import sys
import json

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
LINUX = sys.platform != "win32"

# Ler versão do arquivo versao.json
_VERSAO_PATH = os.path.join(RAIZ, "empacotamento", "versao.json")
try:
    with open(_VERSAO_PATH, 'r', encoding='utf-8') as f:
        _VERSAO_DATA = json.load(f)
        _VERSAO = _VERSAO_DATA.get("versao", "0.0.0")
        # Formato: 1.1.2 -> KChrono-1.1.2
        _NOME_APP = f"KChrono-{_VERSAO}"
except:
    _VERSAO = "0.0.0"
    _NOME_APP = "KChrono"


# ------------------------------------------------------------------ metadados
# VS_VERSION_INFO do executável. Metadados completos aparecem em
# Propriedades → Detalhes e reduzem a chance de falso positivo.
def _tupla_versao(v: str) -> tuple:
    partes = []
    for p in (v or "0.0.0").split("."):
        digitos = "".join(c for c in p if c.isdigit())
        partes.append(int(digitos) if digitos else 0)
    while len(partes) < 4:
        partes.append(0)
    return tuple(partes[:4])


def _escrever_versao_info(versao: str, nome_exe: str) -> str:
    a, b, c, d = _tupla_versao(versao)
    texto = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}),
    prodvers=({a}, {b}, {c}, {d}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'KChrono'),
        StringStruct('FileDescription', 'KChrono - Cronometragem RC'),
        StringStruct('FileVersion', '{versao}'),
        StringStruct('InternalName', 'KChrono'),
        StringStruct('LegalCopyright', 'Copyright (C) 2026 Raphael Belowodski'),
        StringStruct('OriginalFilename', '{nome_exe}'),
        StringStruct('ProductName', 'KChrono'),
        StringStruct('ProductVersion', '{versao}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    destino = os.path.join(SPECPATH, "build", "versao_info.txt")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(texto)
    return destino


_VERSION_FILE = _escrever_versao_info(_VERSAO, f"{_NOME_APP}.exe")

HIDDEN = [
    # cliente HTTP do sync com o CTAD (sync/ctad_client.py). Sem isso o
    # PyInstaller pode deixar o requests de fora e o app empacotado quebra no
    # boot ("No module named 'requests'").
    "requests", "urllib3", "certifi", "charset_normalizer", "idna",
    # uvicorn (carrega back-ends por import dinâmico)
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    # QR Code da gestão remota (servidor/qr.py importa segno dentro de try/except,
    # então o PyInstaller não detecta a dependência automaticamente)
    "segno",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "websockets",
    # drivers opcionais
    "serial", "serial.tools", "serial.tools.list_ports",
    "bleak",
    # voz (TTS)
    "pyttsx3", "pyttsx3.drivers",
    # voz neural offline (Piper + onnxruntime) — o pacote embarca o
    # espeak-ng-data e os binários do onnxruntime, que precisam ir junto.
    "piper", "piper.voice", "piper.config",
    "onnxruntime", "onnxruntime.capi", "onnxruntime.capi.onnxruntime_pybind11_state",
]

if LINUX:
    HIDDEN += [
        # driver espeak do pyttsx3 (fallback de voz no Linux)
        "pyttsx3.drivers.espeak",
        # pywebview (reserva; no Linux a janela é o navegador)
        "webview", "webview.dom", "webview.localization",
    ]
else:
    HIDDEN += [
        # voz TTS do Windows (SAPI via COM)
        "pyttsx3.drivers.sapi5",
        "comtypes", "comtypes.client", "win32com", "win32com.client",
        # pywebview (janela nativa WebView2)
        "webview", "webview.platforms", "webview.platforms.edgechromium",
        "webview.dom", "webview.localization",
    ]

#: dados/binários dos motores neurais (espeak-ng-data do piper, DLLs do
#: onnxruntime). Fica vazio se os pacotes não estiverem instalados — o app
#: segue funcionando com o SAPI do Windows / espeak do Linux.
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

# Modelos neurais (pt_BR-*.onnx + .json) — embarcados para o app já nascer
# com a voz neural pronta (copiados p/ ~/.local/share|%APPDATA% na 1ª execução
# por _semear_modelos). Não há no repositório (dados/ é local) — o CI monta o
# Linux sem eles e o Admin baixa as vozes na 1ª execução.
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
    excludes=["uvloop", "tkinter"],   # uvloop não entra (loop padrão basta)
    noarchive=False,
)

pyz = PYZ(a.pure)

if LINUX:
    # onedir: sem extração em /tmp a cada abertura (importante na live que
    # roda em RAM) e o AppDir vira o AppImage.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=_NOME_APP,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,                        # sem compressão (heurística de AV)
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=_NOME_APP,
    )
else:
    # onedir: os arquivos ficam ao lado do executável (dist/KChrono-<versão>/).
    # O onefile se auto-extraía para %TEMP%\_MEIxxxx a cada abertura — um dos
    # gatilhos do falso positivo PDM. O instalador copia a pasta inteira.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=_NOME_APP,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,                        # sem UPX (evita heurística)
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,                    # SEM console — app nativo silencioso
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=os.path.join(RAIZ, "imagens", "KCHRONO-LOGO.ico"),
        version=_VERSION_FILE,            # metadados VS_VERSION_INFO
        uac_admin=False,                  # não pede administrador
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=_NOME_APP,
    )
