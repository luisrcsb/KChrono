"""KChrono — módulo de som/locução do servidor (Fase 4).

Centraliza as frases faladas (TTS) e os bipes. Frases configuráveis —
editadas no Admin e persistidas em config.json pelo estado.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Dict, List, Optional

from nucleo.voz import Locutor

log = logging.getLogger("kchrono.som")


def _beep_async(freq: int, ms: int):
    """Bipe não bloqueante.

    ``winsound.Beep`` é síncrono (bloquearia o event loop e atrasaria a linha
    do tempo da largada) — por isso roda numa thread daemon.
    """
    def _run():
        try:
            import winsound
            winsound.Beep(int(freq), int(ms))
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

#: Frases faladas (placeholders {nome}, {tempo}, {n} são preenchidos na chamada)
FRASES_TTS = {
    "atencao": "Atenção pilotos, preparem-se para a largada!",
    "contagem": "{n}",
    "vai": "Vai!",
    "treino_iniciado": "Treino iniciado. Boa prática a todos!",
    "classificacao_iniciada": "Classificação iniciada. Cada piloto tem seu tempo.",
    "pausada": "Sessão pausada.",
    "retomada": "Sessão retomada.",
    "finalizada": "Sessão finalizada. Confiram a classificação.",
    "melhor_volta": "Melhor volta: {nome}, {tempo} segundos.",
    "volta": "Volta {numero}: {nome}, {tempo} segundos.",
    "posicoes": "Posições: {lista}.",
    "recorde_pessoal": "Novo recorde pessoal de {nome}: {tempo} segundos!",
    "recorde_pista": "Novo recorde da pista! {nome}, {tempo} segundos!",
    "ghost_lap": "Atenção: volta inválida detectada.",
    "gato": "Atenção: volta marcada como suspeita.",
    # Sons de passagem (bips) - não usam TTS, são bips puros
    "passagem": "",           # bip curto a cada passagem
    "lider": "",              # bip especial (alto-baixo-alto) quando líder passa
}

#: Ordem e rótulo (PT-BR) de cada frase na tela de Admin.
ROTULOS = [
    ("atencao", "Atenção (largada)"),
    ("vai", "Vai!"),
    ("contagem", "Contagem do semáforo"),
    ("treino_iniciado", "Treino iniciado"),
    ("classificacao_iniciada", "Classificação"),
    ("pausada", "Pausada"),
    ("retomada", "Retomada"),
    ("finalizada", "Finalizada"),
    ("volta", "Leitura de volta"),
    ("posicoes", "Leitura de posições"),
    ("recorde_pessoal", "Recorde pessoal"),
    ("recorde_pista", "Recorde da pista"),
    ("melhor_volta", "Melhor volta"),
    ("ghost_lap", "Volta inválida"),
    ("gato", "Gato (suspeita)"),
    ("passagem", "Bip de passagem (cada piloto)"),
    ("lider", "Bip especial do líder (alto-baixo-alto)"),
]

#: Valores de exemplo usados na pré-escuta de frases com placeholders.
EXEMPLOS = {"{n}": "3", "{nome}": "Piloto", "{tempo}": "9,12",
            "{numero}": "5", "{lista}": "1º Piloto A, 2º Piloto B, 3º Piloto C"}

#: Opções de locução automática (intervalos/eventos), editadas no Admin.
OPCOES_SOM_PADRAO = {
    "intervalo_posicoes": 0,       # segundos entre leituras de posição (0 = desligado)
    "posicoes_topo": 3,            # quantos pilotos ler em cada anúncio
    "anunciar_volta": False,       # fala cada volta (nome + tempo)
    "anunciar_a_cada_voltas": 0,   # lê as posições a cada N voltas do líder (0 = desligado)
    "anunciar_recorde_pessoal": True,
    "anunciar_recorde_pista": True,
    # Sons de passagem
    "som_passagem": True,          # bip a cada passagem
    "som_lider": True,             # bip especial do líder
}


class ModuloSom:
    """Frases faladas (TTS) + bipes; edição salva em config.json pelo estado."""

    def __init__(self, ativo: bool = True, locutor: Optional[Locutor] = None):
        self.frases = dict(FRASES_TTS)
        self.locutor = locutor
        self.ativo = ativo
        #: chave da frase -> caminho ABSOLUTO de um áudio que substitui a fala
        self.audios: Dict[str, str] = {}
        #: chave da frase -> False desliga aquele som (padrão: ligado)
        self.habilitados: Dict[str, bool] = {"passagem": True, "lider": True}
        if self.ativo and self.locutor is None:
            try:
                self.locutor = Locutor()
            except Exception as e:
                log.warning("módulo de som desligado: %s", e)
                self.ativo = False

    # ----- ligar/desligar sons individualmente -----
    def definir_habilitados(self, mapa: Optional[dict]):
        self.habilitados = {k: bool(v) for k, v in (mapa or {}).items()}

    def habilitado(self, chave: str) -> bool:
        return self.habilitados.get(chave, True)


    # ----- áudios gravados (substituem a frase falada) -----
    def definir_audios(self, audios: Optional[dict]):
        self.audios = {k: v for k, v in (audios or {}).items() if v}

    def _audio_de(self, chave: str) -> Optional[str]:
        caminho = self.audios.get(chave)
        if caminho and os.path.isfile(caminho):
            return caminho
        return None

    def tem_audio(self, chave: str) -> bool:
        caminho = self.audios.get(chave)
        return bool(caminho and os.path.isfile(caminho))

    # ----- configuração de frases -----
    def definir_frases(self, frases: Optional[dict]):
        for chave, texto in (frases or {}).items():
            if chave in FRASES_TTS and texto is not None:
                self.frases[chave] = str(texto)

    def texto(self, chave: str, **kwargs) -> str:
        texto = self.frases.get(chave, chave)
        if kwargs:
            try:
                texto = texto.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return texto

    def frases_publicas(self) -> List[dict]:
        return [{"chave": chave, "rotulo": rotulo, "texto": self.frases.get(chave, ""),
                 "habilitado": self.habilitados.get(chave, True)}
                for chave, rotulo in ROTULOS]

    @staticmethod
    def com_exemplo(texto: str) -> str:
        for marco, valor in EXEMPLOS.items():
            texto = texto.replace(marco, valor)
        return texto

    # ----- fala -----
    def falar(self, chave: str, **kwargs):
        """Fala a frase — ou toca o áudio gravado, se houver para essa chave.

        Respeita a chave ligada/desligada em Admin → Voz & Som.
        """
        if not self.ativo or not self.locutor:
            return
        if self.habilitados.get(chave, True) is False:
            return
        caminho = self.audios.get(chave)
        if caminho and os.path.isfile(caminho):
            self.locutor.tocar_audio(caminho)
            return
        self.locutor.falar(self.texto(chave, **kwargs))

    def ouvir(self, texto: str, chave: Optional[str] = None) -> bool:
        """Pré-escuta (Admin): toca o áudio da frase ou fala o texto."""
        if not self.locutor:
            return False
        caminho = self.audios.get(chave) if chave else None
        if caminho and os.path.isfile(caminho):
            self.locutor.tocar_audio(caminho)
            return True
        self.locutor.ouvir(texto)
        return True

    # ----- sons de passagem -----
    def bip_passagem(self):
        """Bip curto e agudo para cada passagem (padrão: 880Hz, 60ms)."""
        if not self.habilitado("passagem"):
            return
        _beep_async(880, 60)  # agudo, curto

    def bip_lider(self):
        """Bip especial do líder: alto-baixo-alto rápido (3 tons)."""
        if not self.habilitado("lider"):
            return
        # Alto (1200Hz) - Baixo (600Hz) - Alto (1200Hz)
        _beep_async(1200, 55)
        _beep_async(600, 55)
        _beep_async(1200, 55)

    def bip_contagem(self):
        """Bip curto de marcação de cada número da contagem (600Hz, 80ms)."""
        _beep_async(600, 80)

    def testar_som_passagem(self):
        """Pré-escuta do bip de passagem (Admin)."""
        self.bip_passagem()
        return True

    def testar_som_lider(self):
        """Pré-escuta do bip do líder (Admin)."""
        self.bip_lider()
        return True

    def audios_publicos(self) -> List[dict]:
        saida = []
        for chave, rotulo in ROTULOS:
            caminho = self.audios.get(chave)
            if caminho and os.path.isfile(caminho):
                saida.append({"chave": chave, "arquivo": os.path.basename(caminho),
                              "url": f"/api/som/audio/{chave}"})
        return saida

    # ----- eventos de corrida -----
    def anunciar_largada(self):
        """'Atenção pilotos, preparem-se para a largada!' + bip de atenção."""
        self.falar("atencao")
        _beep_async(660, 200)

    def bip_largada(self):
        """Bip forte no verde — sinal sonoro da largada (sem locução)."""
        _beep_async(1200, 900)

    def iniciada(self, tipo: str):
        # Na corrida NÃO falamos "Corrida iniciada. Boa sorte a todos!":
        # o anúncio de abertura é a locução da largada ("Atenção pilotos,
        # preparem-se para a largada!"), disparada logo em seguida por
        # anunciar_largada() no fluxo de "Preparar para a Largada".
        if tipo == "corrida":
            return
        if tipo == "classificacao":
            self.falar("classificacao_iniciada")
        else:
            self.falar("treino_iniciado")

    def pausada(self):
        self.falar("pausada")

    def retomada(self):
        self.falar("retomada")

    def finalizada(self):
        self.falar("finalizada")

    def ghost_lap(self):
        self.falar("ghost_lap")

    def gato(self):
        self.falar("gato")
