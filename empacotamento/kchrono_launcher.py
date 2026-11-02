"""KChrono — ponto de entrada do executável empacotado (PyInstaller).

Windows: sobe o servidor local (FastAPI/uvicorn) em thread separada e abre
janela NATIVA (WebView2) carregando a interface web — **sem barra de
endereço, abas ou chrome do navegador**.
Linux (AppImage): servidor no fundo + interface no PRÓPRIO navegador
(xdg-open) — dispensa pywebview/WebKitGTK.

Um processo = UMA janela (o pywebview trava ao criar a 2ª janela noutra
thread). O telão abre num processo filho (``--sem-servidor``) com janela
própria, na tela das Configurações.

    KChrono.exe                 → janela nativa 1280x800 em http://localhost:8780
    KChrono.exe --porta 9000    → porta alternativa
    KChrono.exe --telao         → abre direto no telão (/telao)
    KChrono.exe --gerente       → abre direto no gerente (/gerente)
    KChrono.exe --sem-janela    → roda headless (uso como serviço/systemd)
    KChrono.exe --sem-servidor --telao  → só a janela (liga no servidor ativo)
    KChrono.exe --largura 1920 --altura 1080  → tamanho customizado
"""
from __future__ import annotations

import argparse
import multiprocessing
import threading
import time
import sys

import uvicorn

try:
    # pywebview só é usado no Windows; no Linux a "janela" é o navegador
    import webview
except Exception:            # sem GUI disponível — segue no modo navegador
    webview = None

#: Linux → a interface abre no PRÓPRIO navegador (xdg-open): dispensa
#: pywebview/WebKitGTK, que é frágil de empacotar. Windows → janela nativa.
MODO_NAVEGADOR = sys.platform != "win32"

from servidor.api import app
from nucleo.log import configurar_log
from atualizador import VERSAO_ATUAL as VERSAO   # espelha empacotamento/versao.json
TITULO_JANELA = "KChrono — Cronometragem RC"
TITULO_TELAO = "KChrono — Telão"
URL_BASE = "http://127.0.0.1:8780"  # 127.0.0.1 evita prompt de firewall na 1ª execução


class Ponte:
    """Ponte JS→Python, exposta como ``window.pywebview.api``.

    Cada processo tem UMA janela (o pywebview cria janelas filhas numa
    thread separada — trava o app no Windows). O telão abre num processo
    filho (``--sem-servidor``) com janela própria, na tela escolhida.
    """

    def __init__(self):
        self.janela = None            # janela deste processo (modo filho)
        self._proc_telao = None       # processo filho do telão (modo pai)

    # ------------------------------------------------- lado pai (operador)
    def _telao_vivo(self) -> bool:
        return (self._proc_telao is not None
                and self._proc_telao.poll() is None)

    @staticmethod
    def _salvar_pref(**campos):
        """Persiste o estado do telão (config.json) para reabrir igual no boot."""
        try:
            from servidor.config import carregar_config, salvar_config
            cfg = carregar_config()
            cfg.update(campos)
            salvar_config(cfg)
        except Exception:
            pass

    def _abrir_processo_telao(self, fullscreen: bool = False):
        import os
        import subprocess
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--sem-servidor", "--telao"]
        else:
            cmd = [sys.executable,
                   os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "kchrono_launcher.py"),
                   "--sem-servidor", "--telao"]
        if fullscreen:
            cmd.append("--fullscreen")
        self._proc_telao = subprocess.Popen(cmd)

    def abrir_telao(self):
        """Abre o telão em janela nativa própria (processo filho)."""
        try:
            if self._telao_vivo():
                return "ja-aberta"
            try:
                from servidor.config import carregar_config
                fullscreen = bool(carregar_config().get("telao_fullscreen", True))
            except Exception:
                fullscreen = True
            self._abrir_processo_telao(fullscreen)
            self._salvar_pref(telao_aberto=True)
            return "ok"
        except Exception:
            return "falhou"

    def telao_segunda_tela(self):
        """Idem (a tela é a das Configurações → Telão)."""
        return self.abrir_telao()

    def fechar_telao(self):
        """Fecha o telão (o ESC no telão fecha a própria janela)."""
        try:
            if self._telao_vivo():
                self._proc_telao.terminate()
                self._salvar_pref(telao_aberto=False)
                return "ok"
            return "fechada"
        except Exception:
            return "fechada"

    def telao_aberto(self):
        """Diz se a janela do telão está viva (o botão alterna abrir/fechar)."""
        return "aberta" if self._telao_vivo() else "fechada"

    def encerrar_filhos(self):
        try:
            if self._telao_vivo():
                self._proc_telao.terminate()
        except Exception:
            pass

    # ------------------------------------------------ lado filho (telão)
    def fechar_janela(self):
        """Fecha a própria janela (ESC no telão)."""
        try:
            self._salvar_pref(telao_aberto=False)
        except Exception:
            pass
        try:
            if self.janela is not None:
                self.janela.destroy()
                return "ok"
        except Exception:
            pass
        return "falhou"

    def telas(self):
        """Monitores disponíveis (para o seletor em Configurações)."""
        try:
            telas = list(webview.screens)
        except Exception:
            telas = []
        if not telas:
            # fallback: consulta a plataforma diretamente
            try:
                from webview.platforms import winforms as _wf
                telas = list(_wf.get_screens())
            except Exception:
                telas = []
        # O pywebview ordena por posição (esquerda→direita), NÃO pelo monitor
        # principal. Descobrimos o principal pelo .NET para rotular direito.
        principal_idx = 0
        try:
            from System.Windows.Forms import Screen as _Screen
            for i, s in enumerate(_Screen.AllScreens):
                if s.Primary:
                    principal_idx = i
                    break
        except Exception:
            pass
        resultado = []
        for i, s in enumerate(telas):
            try:
                resultado.append({
                    "indice": i,
                    "x": getattr(s, "x", 0),
                    "y": getattr(s, "y", 0),
                    "largura": getattr(s, "width", 0),
                    "altura": getattr(s, "height", 0),
                    "principal": i == principal_idx,
                })
            except Exception:
                continue
        return resultado


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


def _abrir_navegador(url: str) -> bool:
    """Abre a interface no navegador padrão (modo navegador — Linux)."""
    import shutil
    import subprocess
    for cmd in (["xdg-open", url], ["gio", "open", url],
                ["x-www-browser", url], ["sensible-browser", url]):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                return True
            except Exception:
                pass
    print(f"  Abra manualmente no navegador: {url}")
    return False


def _num_telas() -> int:
    """Quantidade de monitores (para só abrir o telão se houver 2ª tela)."""
    try:
        from System.Windows.Forms import Screen
        return len(Screen.AllScreens)
    except Exception:
        pass
    try:
        return len(list(webview.screens))
    except Exception:
        return 1


def main() -> int:
    multiprocessing.freeze_support()
    configurar_log()

    ap = argparse.ArgumentParser(prog="KChrono", description="KChrono — cronometragem RC")
    ap.add_argument("--host", default="127.0.0.1", help="interface de rede (default: 127.0.0.1)")
    ap.add_argument("--porta", type=int, default=8780, help="porta HTTP (default: 8780)")
    ap.add_argument("--telao", action="store_true", help="abre direto no telão (/telao)")
    ap.add_argument("--gerente", action="store_true", help="abre direto no gerente (/gerente)")
    ap.add_argument("--sem-janela", action="store_true", help="roda headless (serviço)")
    ap.add_argument("--largura", type=int, default=1280, help="largura da janela")
    ap.add_argument("--altura", type=int, default=800, help="altura da janela")
    ap.add_argument("--fullscreen", action="store_true",
                    help="tela cheia real (sem barra de título — modo kiosk)")
    ap.add_argument("--janela", dest="janela", action="store_true",
                    help="abre em janela normal (não maximizada) — para desenvolvimento")
    ap.add_argument("--sem-servidor", action="store_true",
                    help="só abre a janela (usa o servidor já ativo; modo do telão)")
    args = ap.parse_args()

    # Por padrão o app abre MAXIMIZADO (tela cheia útil) porém COM a barra de
    # título — assim os botões minimizar/maximizar/fechar continuam à mão.
    # --fullscreen  => tela cheia real, sem barra (kiosk).
    # --janela      => janela normal, redimensionável (desenvolvimento).
    args.maximizado = not args.janela and not args.fullscreen

    # Monta URL final
    rota = "/telao" if args.telao else ("/gerente" if args.gerente else "/")
    url = f"http://{args.host}:{args.porta}{rota}"

    # Modo navegador: uma 2ª execução não sobe outro servidor — só abre a
    # interface da instância que já está rodando
    if MODO_NAVEGADOR and not args.sem_servidor and \
            _esperar_servidor(f"http://{args.host}:{args.porta}", timeout=1.0):
        print(f"KChrono já está rodando — abrindo {url}")
        _abrir_navegador(url)
        return 0

    # Servidor local em background (o modo --sem-servidor usa o que já roda)
    pronto = threading.Event()
    if not args.sem_servidor:
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

    if MODO_NAVEGADOR:
        # Linux: servidor no fundo + interface no navegador (sem janela nativa)
        _abrir_navegador(url)
        print("  Interface no navegador — encerre pelo botão Sair (Admin → Sobre) ou Ctrl+C.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nEncerrando...")
        return 0

    # Caminho do ícone (embutido no exe pelo PyInstaller)
    import os
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    icone = os.path.join(base, "imagens", "KCHRONO-LOGO.png")

    # Cria a ÚNICA janela deste processo (a 2ª janela nasce noutra thread:
    # trava o app no Windows — por isso o telão é um processo filho).
    ponte = Ponte()
    localizacao_pt = {
        "global.quitConfirmation": "Deseja realmente sair do KChrono?",
    }
    if args.telao and args.sem_servidor:
        # modo telão: janela na tela das Configurações, em tela cheia (kiosk)
        # quando a preferência estiver ligada (padrão) ou --fullscreen vier.
        largura_t, altura_t = args.largura, args.altura
        try:
            from servidor.config import carregar_config
            cfg_t = carregar_config()
            indice = max(0, int(cfg_t.get("telao_tela", 1)))
            tela_cheia = bool(args.fullscreen or cfg_t.get("telao_fullscreen", True))
        except Exception:
            indice = 1
            tela_cheia = bool(args.fullscreen)
        x = y = None
        try:
            telas = webview.screens
            alvo = telas[indice] if 0 <= indice < len(telas) else telas[0]
            x, y = alvo.x, alvo.y
            # geometria do monitor escolhido (a janela nasce já do tamanho certo)
            if getattr(alvo, "width", 0) and getattr(alvo, "height", 0):
                largura_t, altura_t = alvo.width, alvo.height
        except Exception:
            pass
        janela = webview.create_window(
            title=TITULO_TELAO,
            url=url,
            width=largura_t,
            height=altura_t,
            x=x,
            y=y,
            maximized=True,          # garante que a janela nasce na tela escolhida
            fullscreen=False,        # real é aplicado após o start (kiosk)
            resizable=True,
            frameless=False,
            on_top=False,
            confirm_close=False,
            background_color="#0D0D0D",
            text_select=False,
            zoomable=False,
            js_api=ponte,
            localization=localizacao_pt,
        )
    else:
        tela_cheia = bool(args.fullscreen)
        janela = webview.create_window(
            title=TITULO_JANELA,
            url=url,
            width=args.largura,
            height=args.altura,
            maximized=args.maximizado,   # tela cheia COM barra de título (botão fechar)
            fullscreen=args.fullscreen,  # tela cheia real, sem barra (--fullscreen)
            min_size=(900, 600),
            resizable=True,
            frameless=False,          # True = sem barra de título (só para telão/kiosk)
            easy_drag=True,
            on_top=False,
            confirm_close=True,
            background_color="#0D0D0D",
            text_select=False,
            zoomable=False,
            js_api=ponte,
            localization=localizacao_pt,
        )
    ponte.janela = janela

    # Define ícone após criar (pywebview permite)
    if os.path.exists(icone):
        try:
            janela.icon = icone
        except Exception:
            pass

    # Tela cheia real (kiosk): o fullscreen do pywebview no Windows/WebView2 às
    # vezes não aplica; repetir após o start cobre esse caso. No modo padrão
    # (maximizado) NÃO mexemos — a barra de título fica intacta.
    def _aplicar_tela_cheia():
        if not tela_cheia:
            return
        try:
            janela.toggle_fullscreen()
        except Exception:
            pass

    def _abrir_telao_inicial():
        """Reabre o telão na 2ª tela, no estado salvo da última execução.

        Só abre quando o operador deixou o telão aberto (ou ligou "abrir ao
        iniciar") E existe um segundo monitor — assim o app nunca cobre a
        própria janela do operador numa máquina de tela única.
        """
        if args.telao or args.sem_servidor:
            return
        try:
            from servidor.config import carregar_config
            cfg = carregar_config()
        except Exception:
            return
        if not (cfg.get("telao_aberto") or cfg.get("telao_autostart")):
            return
        if _num_telas() < 2:
            return
        try:
            ponte.abrir_telao()
            print("  Telão reaberto na segunda tela.")
        except Exception:
            pass

    def _ao_iniciar():
        _aplicar_tela_cheia()
        if not args.telao:
            # deixa a janela principal aparecer antes de subir o processo filho
            threading.Timer(1.2, _abrir_telao_inicial).start()

    # Inicia loop da GUI (bloqueante — encerra quando fecha a janela)
    import atexit
    atexit.register(ponte.encerrar_filhos)
    webview.start(func=_ao_iniciar, debug=False, private_mode=False,
                  storage_path=None)
    ponte.encerrar_filhos()

    print("Janela fechada — encerrando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())