"""KChrono — ponto de entrada do executável empacotado (PyInstaller + pywebview).

Sobe o servidor local (FastAPI/uvicorn) em thread separada e abre janela nativa
(WebView2 no Windows) carregando a interface web — **sem barra de endereço,
abas ou chrome do navegador**.

    KChrono.exe                 → janela nativa 1280x800 em http://localhost:8780
    KChrono.exe --porta 9000    → porta alternativa
    KChrono.exe --telao         → abre direto no telão (/telao)
    KChrono.exe --gerente       → abre direto no gerente (/gerente)
    KChrono.exe --sem-janela    → roda headless (uso como serviço/systemd)
    KChrono.exe --largura 1920 --altura 1080  → tamanho customizado
"""
from __future__ import annotations

import argparse
import multiprocessing
import threading
import time
import sys

import uvicorn
import webview

from servidor.api import app

VERSAO = "1.0.0"
TITULO_JANELA = "KChrono — Cronometragem RC"
URL_BASE = "http://127.0.0.1:8780"  # 127.0.0.1 evita prompt de firewall na 1ª execução


def _rodar_servidor(host: str, porta: int, pronto: threading.Event):
    """Roda uvicorn em thread daemon; sinaliza quando pronto."""
    # uvicorn roda o loop asyncio — usamos run() bloqueante
    config = uvicorn.Config(app, host=host, port=porta, log_level="info", lifespan="on")
    server = uvicorn.Server(config)

    async def _servir():
        await server.serve()
        pronto.set()

    import asyncio
    asyncio.run(_servir())


def _esperar_servidor(url: str, timeout: float = 15.0) -> bool:
    """Aguarda o servidor responder HTTP 200 em /api/status."""
    import urllib.request
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            with urllib.request.urlopen(f"{url}/api/status", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def main() -> int:
    multiprocessing.freeze_support()

    ap = argparse.ArgumentParser(prog="KChrono", description="KChrono — cronometragem RC")
    ap.add_argument("--host", default="127.0.0.1", help="interface de rede (default: 127.0.0.1)")
    ap.add_argument("--porta", type=int, default=8780, help="porta HTTP (default: 8780)")
    ap.add_argument("--telao", action="store_true", help="abre direto no telão (/telao)")
    ap.add_argument("--gerente", action="store_true", help="abre direto no gerente (/gerente)")
    ap.add_argument("--sem-janela", action="store_true", help="roda headless (serviço)")
    ap.add_argument("--largura", type=int, default=1280, help="largura da janela")
    ap.add_argument("--altura", type=int, default=800, help="altura da janela")
    ap.add_argument("--fullscreen", action="store_true", help="janela em tela cheia (telão)")
    args = ap.parse_args()

    # Monta URL final
    rota = "/telao" if args.telao else ("/gerente" if args.gerente else "/")
    url = f"http://{args.host}:{args.porta}{rota}"

    # Inicia servidor em background
    pronto = threading.Event()
    t_server = threading.Thread(
        target=_rodar_servidor, args=(args.host, args.porta, pronto), daemon=True
    )
    t_server.start()

    print(f"KChrono {VERSAO} — servidor em http://{args.host}:{args.porta}")
    print(f"  Interface: {url}")
    print("  Encerre com Ctrl+C.")

    if args.sem_janela:
        # Modo headless: só mantém o processo vivo
        try:
            pronto.wait()
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nEncerrando...")
        return 0

    # Aguarda servidor subir
    if not _esperar_servidor(f"http://{args.host}:{args.porta}"):
        print("ERRO: servidor não respondeu a tempo.")
        return 1

    # Caminho do ícone (embutido no exe pelo PyInstaller)
    import os
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    icone = os.path.join(base, "imagens", "KCHRONO-LOGO.png")

    # Cria janela nativa
    janela = webview.create_window(
        title=TITULO_JANELA,
        url=url,
        width=args.largura,
        height=args.altura,
        fullscreen=args.fullscreen,
        min_size=(900, 600),
        resizable=True,
        frameless=False,          # True = sem barra de título (só para telão/kiosk)
        easy_drag=True,
        on_top=False,
        confirm_close=True,
        background_color="#0D0D0D",
        text_select=False,
        zoomable=False,
    )

    # Define ícone após criar (pywebview permite)
    if os.path.exists(icone):
        try:
            janela.icon = icone
        except Exception:
            pass

    # Inicia loop da GUI (bloqueante — encerra quando fecha a janela)
    webview.start(debug=False, private_mode=False, storage_path=None)

    print("Janela fechada — encerrando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())