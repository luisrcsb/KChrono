"""KChrono — locução (TTS) e reprodução de áudio (Fase 4/6).

Backends de fala, em ordem de preferência:

1. **SAPI nativo (comtypes)** — enxerga TANTO as vozes SAPI clássicas
   (``HKLM\\SOFTWARE\\Microsoft\\Speech\\Voices``) QUANTO as vozes *OneCore*
   do Windows 10/11 (``...\\Speech_OneCore\\Voices``), que incluem
   ``Microsoft Daniel`` (pt-BR masculino) e ``Microsoft Maria``. Tudo offline.
2. **pyttsx3** — usado só se o backend nativo não puder ser criado.
3. **modo log** — não quebra o sistema se nada estiver disponível.

Também reproduz arquivos de áudio (WAV via ``winsound``; MP3/outros via
MCI/winmm), usados quando uma frase é substituída por um áudio gravado.

IMPORTANTE: o motor de fala é criado **dentro da thread do locutor**. Criar o
motor na thread principal e falar de outra thread faz o ``runAndWait``/``Speak``
retornar na hora, sem som nenhum.
"""
from __future__ import annotations

import logging
import os
import queue
import shutil
import tempfile
import threading
from typing import Dict, List, Optional

log = logging.getLogger("kchrono.voz")

#: Categorias de vozes do Windows (SAPI clássico + OneCore).
CAT_SAPI = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices"
CAT_ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"
PREFIXO_ONECORE = "onecore:"
PREFIXO_EDGE = "edge:"

#: LCIDs conhecidos -> rótulo amigável de idioma.
_IDIOMAS = {
    0x0416: "pt-BR", 0x0816: "pt-PT",
    0x0409: "en-US", 0x0809: "en-GB", 0x0C09: "en-AU",
    0x040A: "es-ES", 0x080A: "es-MX", 0x2C0A: "es-AR",
    0x0411: "ja-JP", 0x040C: "fr-FR", 0x0407: "de-DE",
    0x0410: "it-IT",
}


def _rotulo_idioma(lcid: Optional[int]) -> str:
    if not lcid:
        return ""
    return _IDIOMAS.get(lcid, f"0x{lcid:04x}")


def _codigo_idioma(token) -> Optional[int]:
    try:
        bruto = token.GetAttribute("Language") or ""
        return int(bruto, 16) if bruto else None
    except Exception:
        return None


# ------------------------------------------------------------------ áudio
def _tocar_wav(caminho: str) -> bool:
    try:
        import winsound
        winsound.PlaySound(caminho, winsound.SND_FILENAME)      # bloqueante
        return True
    except Exception as e:
        log.warning("winsound falhou (%s)", e)
        return False


def _tocar_mci(caminho: str) -> bool:
    """Toca MP3/WAV/etc. pelo MCI do Windows (winmm), sem dependências."""
    try:
        import ctypes
        mci = ctypes.windll.winmm.mciSendStringW
        alias = "kchrono_audio"
        mci(f"close {alias}", None, 0, None)
        caminho = os.path.abspath(caminho)
        if mci(f'open "{caminho}" alias {alias}', None, 0, None) != 0:
            if mci(f'open "{caminho}" type mpegvideo alias {alias}',
                   None, 0, None) != 0:
                return False
        mci(f"play {alias} wait", None, 0, None)
        mci(f"close {alias}", None, 0, None)
        return True
    except Exception as e:
        log.warning("MCI falhou (%s)", e)
        return False


def tocar_arquivo(caminho: str) -> bool:
    """Toca um arquivo de áudio (WAV por winsound; demais via MCI)."""
    if not caminho or not os.path.exists(caminho):
        return False
    if caminho.lower().endswith(".wav"):
        return _tocar_wav(caminho)
    return _tocar_mci(caminho) or _tocar_wav(caminho)


def edge_disponivel() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        return False


def espeak_disponivel() -> bool:
    return shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None


# ------------------------------------------------------- enumeração de vozes
def _info_token(token, prefixo: str, fonte: str) -> Dict:
    try:
        nome = token.GetDescription()
    except Exception:
        nome = token.Id.rsplit("\\", 1)[-1]
    lcid = _codigo_idioma(token)
    return {"id": prefixo + token.Id, "nome": nome, "fonte": fonte,
            "idiomas": _rotulo_idioma(lcid), "lcid": lcid}


def listar_vozes(tokens: Optional[List[Dict]] = None) -> List[Dict]:
    """Vozes disponíveis (SAPI clássico + OneCore), sem duplicar."""
    if tokens is None:
        tokens = _listar_vozes_comtypes()
    vistos = set()
    saida: List[Dict] = []
    for v in tokens:
        chave = (v["nome"].lower(), v.get("idiomas", ""))
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(v)
    return saida


def _listar_vozes_comtypes() -> List[Dict]:
    try:
        import comtypes.client as cc
    except Exception as e:
        log.debug("comtypes indisponível (%s)", e)
        return []
    vozes: List[Dict] = []
    for prefixo, categoria, fonte in (("", CAT_SAPI, "sapi"),
                                      (PREFIXO_ONECORE, CAT_ONECORE, "onecore")):
        try:
            cat = cc.CreateObject("SAPI.SpObjectTokenCategory")
            cat.SetId(categoria, False)
            for token in cat.EnumerateTokens():
                vozes.append(_info_token(token, prefixo, fonte))
        except Exception as e:
            log.debug("categoria de vozes %s falhou: %s", categoria, e)
    return vozes


def _escolher_voz_padrao(vozes: List[Dict]) -> Optional[str]:
    """Prefere pt-BR; mantém prioridade para as vozes SAPI clássicas."""
    for fonte in ("sapi", "onecore"):
        for v in vozes:
            if v["fonte"] == fonte and (v.get("lcid") or 0) & 0x3FF == 0x16:
                return v["id"]
    return vozes[0]["id"] if vozes else None


# --------------------------------------------------------------- backends
class _BackendSapi:
    """Backend SAPI nativo (comtypes) — fala vozes clássicas e OneCore."""

    def __init__(self, voz_id: Optional[str] = None, volume: float = 0.9,
                 velocidade: int = 180):
        import comtypes.client as cc
        self._cc = cc
        self._sp = cc.CreateObject("SAPI.SpVoice")
        self._tokens: Dict[str, str] = {}
        for categoria in (CAT_SAPI, CAT_ONECORE):
            try:
                cat = cc.CreateObject("SAPI.SpObjectTokenCategory")
                cat.SetId(categoria, False)
                for token in cat.EnumerateTokens():
                    self._tokens[token.Id] = categoria
            except Exception:
                pass
        self.set_volume(volume)
        self.set_rate(velocidade)
        if voz_id:
            self.definir_voz(voz_id)

    def definir_voz(self, voz_id: str) -> bool:
        bruto = voz_id[len(PREFIXO_ONECORE):] if voz_id.startswith(PREFIXO_ONECORE) else voz_id
        categoria = self._tokens.get(bruto)
        if categoria is None:
            return False
        token = self._cc.CreateObject("SAPI.SpObjectToken")
        token.SetId(bruto, categoria)
        self._sp.Voice = token
        return True

    def set_volume(self, valor: float):
        try:
            self._sp.Volume = max(0, min(100, int(round(float(valor) * 100))))
        except Exception:
            pass

    def set_rate(self, wpm: int):
        try:
            self._sp.Rate = max(-10, min(10, int(round((float(wpm) - 180) / 25))))
        except Exception:
            pass

    def falar(self, texto: str):
        self._sp.Speak(texto, 0)      # 0 = síncrono (bloqueia até terminar)


class _BackendPyttsx3:
    """Fallback via pyttsx3 (ex.: espeak-ng no Linux)."""

    def __init__(self, voz_id: Optional[str] = None, volume: float = 0.9,
                 velocidade: int = 180):
        import pyttsx3
        self._engine = pyttsx3.init()
        self.set_volume(volume)
        self.set_rate(velocidade)
        if voz_id:
            self.definir_voz(voz_id)

    def definir_voz(self, voz_id: str) -> bool:
        if voz_id.startswith(PREFIXO_ONECORE) or voz_id.startswith(PREFIXO_EDGE):
            return False
        try:
            self._engine.setProperty("voice", voz_id)
            return True
        except Exception:
            return False

    def set_volume(self, valor: float):
        try:
            self._engine.setProperty("volume", max(0.0, min(1.0, float(valor))))
        except Exception:
            pass

    def set_rate(self, wpm: int):
        try:
            self._engine.setProperty("rate", int(wpm))
        except Exception:
            pass

    def falar(self, texto: str):
        self._engine.say(texto)
        self._engine.runAndWait()


class Locutor:
    """Fila thread-safe de falas/áudios; degrada para log se não houver TTS."""

    def __init__(self, volume: float = 0.9, velocidade: int = 180,
                 preferir_pt: bool = True):
        self.volume = volume
        self.velocidade = velocidade
        self.voz_id: Optional[str] = None
        self.tts_ativo = False
        self._backend = None
        self._vozes: List[Dict] = []
        self._fila: "queue.Queue" = queue.Queue()
        self._pronto = threading.Event()
        self._temp = tempfile.mkdtemp(prefix="kchrono_tts_")

        self._vozes = listar_vozes()
        if preferir_pt:
            self.voz_id = _escolher_voz_padrao(self._vozes)
        elif self._vozes:
            self.voz_id = self._vozes[0]["id"]
        if self._vozes:
            self.tts_ativo = True

        threading.Thread(target=self._loop, daemon=True,
                         name="kchrono-locutor").start()

    # ----- API -----
    def falar(self, texto: str):
        self._fila.put({"acao": "falar", "texto": texto})

    def ouvir(self, texto: str):
        """Pré-escuta de uma frase exatamente como será falada."""
        self.falar(texto)

    def tocar_audio(self, caminho: str):
        """Toca um arquivo de áudio pela mesma fila (respeita a ordem)."""
        self._fila.put({"acao": "audio", "caminho": caminho})

    def definir_voz(self, voz_id: Optional[str]):
        self.voz_id = voz_id
        self._fila.put({"acao": "voz", "valor": voz_id})

    def set_volume(self, valor: float):
        self.volume = max(0.0, min(1.0, float(valor)))
        self._fila.put({"acao": "volume", "valor": self.volume})

    def set_velocidade(self, valor: int):
        self.velocidade = int(valor)
        self._fila.put({"acao": "rate", "valor": self.velocidade})

    def bip(self, freq: int = 440, ms: int = 120):
        """Bipe curto (winsound, Windows)."""
        try:
            import winsound
            winsound.Beep(freq, ms)
        except Exception:
            pass

    def parar(self):
        self._fila.put({"acao": "parar"})

    def aguardar_pronto(self, timeout: float = 4.0) -> bool:
        """Espera o motor da thread ficar pronto (status confiável)."""
        return self._pronto.wait(timeout)

    def sincronizar(self, timeout: float = 30.0) -> bool:
        """Bloqueia até a fila esvaziar (útil p/ testes e desligamento)."""
        evento = threading.Event()
        self._fila.put({"acao": "_sincronizar", "evento": evento})
        return evento.wait(timeout)

    # ----- introspecção -----
    def listar_vozes(self) -> List[Dict]:
        return list(self._vozes)

    def status(self) -> Dict:
        return {"tts_ativo": bool(self._backend is not None or self.tts_ativo),
                "volume": self.volume,
                "velocidade": self.velocidade,
                "voz_id": self.voz_id,
                "edge_disponivel": edge_disponivel(),
                "vozes": self.listar_vozes()}

    # ----- thread -----
    def _loop(self):
        # COM precisa ser inicializado NESTA thread antes de criar o SAPI
        try:
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # STA
        except Exception:
            pass
        # motor criado AQUI dentro (thread do locutor)
        try:
            self._backend = _BackendSapi(voz_id=self.voz_id,
                                         volume=self.volume,
                                         velocidade=self.velocidade)
            self.tts_ativo = True
            log.info("TTS SAPI nativo ativo (thread do locutor)")
        except Exception as e:
            log.warning("SAPI nativo indisponível (%s) — tentando pyttsx3", e)
            try:
                self._backend = _BackendPyttsx3(voz_id=self.voz_id,
                                                volume=self.volume,
                                                velocidade=self.velocidade)
                self.tts_ativo = True
                log.info("TTS pyttsx3 ativo (thread do locutor)")
            except Exception as e2:
                log.warning("nenhum TTS disponível (%s) — locução em modo log", e2)
                self._backend = None
                self.tts_ativo = False
        self._pronto.set()

        while True:
            item = self._fila.get()
            if isinstance(item, dict):
                acao = item.get("acao")
                if acao == "parar":
                    continue
                if acao == "_sincronizar":
                    evento = item.get("evento")
                    if evento is not None:
                        evento.set()
                    continue
                if acao == "voz":
                    self._aplicar_voz(item.get("valor"))
                    continue
                if acao == "volume":
                    if self._backend:
                        self._backend.set_volume(item.get("valor"))
                    self.volume = item.get("valor", self.volume)
                    continue
                if acao == "rate":
                    if self._backend:
                        self._backend.set_rate(item.get("valor"))
                    self.velocidade = item.get("valor", self.velocidade)
                    continue
                if acao == "audio":
                    self._tocar(item.get("caminho", ""))
                    continue
                texto = item.get("texto", "")
            else:                       # compatibilidade: item cru é fala
                texto = item
            if texto:
                self._dizer(texto)

    def _dizer(self, texto: str):
        vid = self.voz_id or ""
        if vid.startswith(PREFIXO_EDGE) and edge_disponivel():
            if self._dizer_edge(texto, vid[len(PREFIXO_EDGE):]):
                return
        if self._backend is not None:
            try:
                self._backend.falar(texto)
                return
            except Exception as e:
                log.warning("falha ao sintetizar (%s) — segue para o log", e)
        log.info("[locução] %s", texto)

    def _aplicar(self, acao: str, valor):
        """Retrocompatível: aplica voz/volume/velocidade na thread."""
        if acao == "voz":
            self._aplicar_voz(valor)
        elif acao == "volume":
            self.volume = max(0.0, min(1.0, float(valor)))
            if self._backend:
                self._backend.set_volume(self.volume)
        elif acao == "rate":
            self.velocidade = int(valor)
            if self._backend:
                self._backend.set_rate(self.velocidade)

    def _aplicar_voz(self, voz_id: Optional[str]):
        self.voz_id = voz_id
        if self._backend is not None and voz_id:
            try:
                self._backend.definir_voz(voz_id)
            except Exception as e:
                log.warning("não foi possível trocar a voz (%s)", e)

    def _dizer_edge(self, texto: str, short: str) -> bool:
        caminho = os.path.join(self._temp, "edge.mp3")
        try:
            import asyncio
            import edge_tts
            pct = max(-50, min(100, int(round((self.velocidade - 180) / 180 * 100))))
            volume = f"{int((self.volume - 1.0) * 100)}%"

            async def gerar():
                await edge_tts.Communicate(
                    texto, short, rate=f"{pct:+d}%", volume=volume).save(caminho)

            asyncio.run(gerar())
        except Exception as e:
            log.warning("edge-tts falhou (%s) — caindo para SAPI", e)
            return False
        return _tocar_mci(caminho) or _tocar_wav(caminho)

    def _tocar(self, caminho: str):
        if not caminho or not os.path.isfile(caminho):
            log.info("[áudio] arquivo não encontrado: %s", caminho)
            return
        if caminho.lower().endswith(".wav"):
            if _tocar_wav(caminho):
                return
        if _tocar_mci(caminho):
            return
        _tocar_wav(caminho)
