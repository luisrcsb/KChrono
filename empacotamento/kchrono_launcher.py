"""KChrono — ponto de entrada do executável empacotado (PyInstaller).

Sobe o servidor local e (por padrão) abre o navegador na interface web.

    KChrono.exe                 → http://localhost:8780
    KChrono.exe --porta 9000    → porta alternativa
    KChrono.exe --sem-navegador → não abre o navegador (uso como serviço)
"""
from __future__ import annotations

import argparse
import multiprocessing
import threading
import webbrowser

import uvicorn

from servidor.api import app

VERSAO = "1.0.0"


def _abrir_navegador(porta: int):
    webbrowser.open(f"http://localhost:{porta}")


def main() -> None:
    multiprocessing.freeze_support()          # necessário no Windows ao empacotar

    ap = argparse.ArgumentParser(prog="KChrono", description="KChrono — cronometragem RC")
    ap.add_argument("--host", default="0.0.0.0", help="interface de rede (default: 0.0.0.0 = LAN)")
    ap.add_argument("--porta", type=int, default=8780, help="porta HTTP (default: 8780)")
    ap.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador")
    args = ap.parse_args()

    print(f"KChrono {VERSAO} — servidor em http://localhost:{args.porta}")
    print(f"Telão:  http://localhost:{args.porta}/telao")
    print("Encerre com Ctrl+C.")

    if not args.sem_navegador:
        threading.Timer(1.5, _abrir_navegador, args=(args.porta,)).start()

    uvicorn.run(app, host=args.host, port=args.porta, log_level="info")


if __name__ == "__main__":
    main()
