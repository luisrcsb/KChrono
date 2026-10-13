"""KChrono — módulo de som/locução do servidor (Fase 4).

Centraliza as frases faladas (TTS) e os bipes. Frases configuráveis —
editadas no Admin e persistidas em config.json pelo estado.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from nucleo.voz import Locutor

log = logging.getLogger("kchrono.som")

#: Frases faladas (placeholders {nome}, {tempo}, {n} são preenchidos na chamada)
FRASES_TTS = {
    "atencao": "Atenção pilotos, preparem-se para a largada!",
    "contagem": "{n}",
    "vai": "Vai!",
    "treino_iniciado": "Treino iniciado. Boa prática a todos!",
    "classificacao_iniciada": "Classificação iniciada. Cada piloto tem seu tempo.",
    "corrida_iniciada": "Corrida iniciada. Boa sorte a todos!",
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
}

#: Ordem e rótulo (PT-BR) de cada frase na tela de Admin.
ROTULOS = [
    ("atencao", "Atenção (largada)"),
    ("vai", "Vai!"),
    ("contagem", "Contagem do semáforo"),
    ("treino_iniciado", "Treino iniciado"),
    ("classificacao_iniciada", "Classificação"),
    ("corrida_iniciada", "Corrida iniciada"),
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
        self.habilitados: Dict[str, bool] = {}
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
        """'Atenção pilotos, preparem-se para a largada!' (início do semáforo)."""
        self.falar("atencao")
        if self.locutor:
            self.locutor.bip(660, 200)

    def iniciada(self, tipo: str):
        if tipo == "corrida":
            self.falar("corrida_iniciada")
        elif tipo == "classificacao":
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
