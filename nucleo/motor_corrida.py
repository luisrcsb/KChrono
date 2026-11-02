"""KChrono — motor de corrida (Fase 1).

Recebe passings do driver, atribui a pilotos (via transponder), consolida
voltas (diferença de RTC entre passagens consecutivas) e calcula a
classificação. Regras de campeonato (pontuação, nº de voltas, grid) vêm do
CTAD (Fase 3) — aqui vive só a lógica de sessão.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

from drivers.base import Passing
from .modelos import (EstadoSessao, LinhaClassificação, TipoSessao, Volta,
                      formatar_tempo)
from .relogio import agora_monotonic_us

log = logging.getLogger("kchrono.motor")

#: piso absoluto de uma volta válida (1 s). Mesmo com o filtro de ghost lap
#: desligado (tempo mínimo = 0), nenhuma "volta" de milésimos é registrada:
#: isso acontecia quando o decoder repetia a própria passagem de abertura.
TEMPO_MINIMO_ABSOLUTO_US = 1_000_000
#: deltas abaixo disso são ruído/retransmissão do MESMO laço (não é volta
#: nem ghost lap de verdade — não vale avisar o operador).
TEMPO_RUIDO_US = 300_000


@dataclass
class _EstadoPiloto:
    piloto_id: int
    nome: str
    voltas: List[Volta] = field(default_factory=list)
    primeiro_rtc: Optional[int] = None   # rtc da 1ª passagem (largada/saída)
    ultimo_rtc: Optional[int] = None
    #: True depois que o piloto cruzou o laço pela 1ª vez na sessão. A primeira
    #: passagem é SEMPRE abertura de volta (nunca conta volta concluída).
    aberto: bool = False
    transponder: Optional[int] = None
    suspeitas: set = field(default_factory=set)  # nº de voltas marcadas como "gato"

    @property
    def tempo_total_us(self) -> int:
        if self.primeiro_rtc is None or self.ultimo_rtc is None:
            return 0
        return self.ultimo_rtc - self.primeiro_rtc

    @property
    def melhor_volta_us(self) -> Optional[int]:
        return min((v.tempo_us for v in self.voltas), default=None)


class MotorCorrida:
    """Máquina de estados de uma sessão de cronometragem.

    Uso:
        motor = MotorCorrida(banco=None, sessao_id="...")
        motor.registrar_transponder(7096340, piloto_id)
        motor.iniciar(TipoSessao.CORRIDA)
        motor.largada()
        motor.processar_passing(Passing(transponder=7096340, rtc_time=...))
        motor.classificacao()
    """

    def __init__(self, banco=None, sessao_id: str = "local",
                 resolver_piloto: Optional[Callable[[int], Optional[tuple]]] = None,
                 tempo_minimo_volta_us: int = 0,
                 on_rejeicao: Optional[Callable[[int, int, Optional[int]], None]] = None,
                 relogio_sessao: Optional[Callable[[], Optional[int]]] = None):
        self.banco = banco
        self.sessao_id = sessao_id
        self.estado = EstadoSessao.PARADO
        self.tipo: Optional[TipoSessao] = None
        self._pilotos: Dict[int, _EstadoPiloto] = {}
        self._mapa_transponders: Dict[int, int] = {}
        self._transponder_por_piloto: Dict[int, int] = {}
        self._resolver_piloto = resolver_piloto
        self._ultimo_passing_number: Optional[int] = None
        self.gaps: List[Dict] = []        # passings perdidos detectados
        self.passings_sem_piloto: List[int] = []
        self.tempo_minimo_volta_us = tempo_minimo_volta_us  # filtro ghost lap
        self.on_rejeicao = on_rejeicao    # callback(transponder, tempo_us, passing_number)
        self.rejeitados: List[Dict] = []  # ghost laps descartados (auditoria)
        # instante (µs) da última volta registrada de cada piloto, na coordenada
        # do cronômetro da sessão — usado pelo atalho F1..F12
        self._ultimo_passo_us: Dict[int, int] = {}
        # relógio da sessão (µs decorridos, sem contar pausas); None = monotonic
        self.relogio_sessao = relogio_sessao

    # ----- configuração -----
    def agora_sessao_us(self) -> int:
        """Coordenada do cronômetro da sessão (µs decorridos, pausas fora)."""
        if self.relogio_sessao:
            try:
                v = self.relogio_sessao()
                if v is not None:
                    return int(v)
            except Exception:  # relógio do servidor indisponível
                pass
        return agora_monotonic_us()

    def registrar_transponder(self, codigo: int, piloto_id: int):
        self._mapa_transponders[codigo] = piloto_id
        self._transponder_por_piloto[piloto_id] = codigo
        if piloto_id in self._pilotos:
            self._pilotos[piloto_id].transponder = codigo

    def vincular_piloto(self, piloto_id: int, nome: str):
        self._pilotos[piloto_id] = _EstadoPiloto(
            piloto_id=piloto_id, nome=nome,
            transponder=self._transponder_por_piloto.get(piloto_id))

    # ----- máquina de estados -----
    def iniciar(self, tipo: TipoSessao):
        if self.estado != EstadoSessao.PARADO:
            raise RuntimeError(f"sessão já iniciada (estado={self.estado.value})")
        self.tipo = tipo
        if tipo == TipoSessao.CORRIDA:
            self.estado = EstadoSessao.LARGADA
        elif tipo == TipoSessao.CLASSIFICACAO:
            self.estado = EstadoSessao.CLASSIFICACAO
        else:
            self.estado = EstadoSessao.TREINO
        self._persistir_estado()

    def largada(self):
        if self.estado != EstadoSessao.LARGADA:
            raise RuntimeError("largada() só vale no estado LARGADA")
        self.estado = EstadoSessao.CORRENDO
        self._persistir_estado()

    def finalizar(self):
        if self.estado in (EstadoSessao.PARADO, EstadoSessao.FINALIZADO):
            return
        self.estado = EstadoSessao.FINALIZADO
        self._persistir_estado(fechar=True)

    def _persistir_estado(self, fechar: bool = False):
        if not self.banco:
            return
        if fechar:
            self.banco.fechar_sessao(self.sessao_id)
        else:
            self.banco.atualizar_estado_sessao(self.sessao_id, self.estado)

    # ----- núcleo: processamento de passings -----
    def processar_passing(self, passing: Passing) -> Optional[Volta]:
        """Registra um passing; devolve a Volta completada (se houver)."""
        if self.estado in (EstadoSessao.PARADO, EstadoSessao.FINALIZADO):
            log.warning("passing ignorado: sessão %s", self.estado.value)
            return None
        if self.estado == EstadoSessao.LARGADA:
            log.info("passing na largada (transponder %s) — sem volta ainda",
                     passing.transponder)
            return None

        # reconciliação: detectar passings perdidos pela numeração do decoder
        if (passing.passing_number is not None
                and self._ultimo_passing_number is not None
                and passing.passing_number > self._ultimo_passing_number + 1):
            faltando = passing.passing_number - self._ultimo_passing_number - 1
            self.gaps.append({"apos": self._ultimo_passing_number,
                              "recebido": passing.passing_number,
                              "faltando": faltando})
            log.warning("gap detectado: %d passing(s) perdido(s) entre #%d e #%d",
                        faltando, self._ultimo_passing_number, passing.passing_number)
        if passing.passing_number is not None:
            if (self._ultimo_passing_number is None
                    or passing.passing_number > self._ultimo_passing_number):
                self._ultimo_passing_number = passing.passing_number

        # resolve piloto
        piloto_id = self._mapa_transponders.get(passing.transponder)
        nome = ""
        if piloto_id is None and self._resolver_piloto:
            resolvido = self._resolver_piloto(passing.transponder)
            if resolvido:
                piloto_id, nome = resolvido
                self._mapa_transponders[passing.transponder] = piloto_id
        if piloto_id is None:
            self.passings_sem_piloto.append(passing.transponder)
            log.warning("passing sem piloto vinculado (transponder %s)",
                        passing.transponder)
            if self.banco:
                self.banco.registrar_passing(self.sessao_id, passing.transponder,
                                             passing.rtc_time or 0,
                                             passing.passing_number,
                                             passing.strength, passing.hits)
            return None

        estado = self._pilotos.get(piloto_id)
        if estado is None:
            if not nome and self.banco:
                piloto = self.banco.buscar_piloto(piloto_id)
                nome = piloto.nome if piloto else str(piloto_id)
            estado = _EstadoPiloto(piloto_id=piloto_id, nome=nome or str(piloto_id),
                                   transponder=self._transponder_por_piloto.get(piloto_id))
            self._pilotos[piloto_id] = estado

        # sem RTC não há como medir tempo: registra para auditoria e ignora
        if passing.rtc_time is None:
            if self.banco:
                self.banco.registrar_passing(self.sessao_id, passing.transponder,
                                             0, passing.passing_number,
                                             passing.strength, passing.hits, valido=0)
            return None

        # consolida volta (com filtro de tempo mínimo / ghost lap)
        volta = None
        valido = 1
        if not estado.aberto:
            # primeira passagem do piloto = ABERTURA de volta (nunca conta
            # volta). Só a partir da 2ª passagem o tempo é fechado.
            estado.aberto = True
            estado.primeiro_rtc = passing.rtc_time
            estado.ultimo_rtc = passing.rtc_time
        else:
            if passing.rtc_time is None or estado.ultimo_rtc is None:
                valido = 0
            elif passing.rtc_time <= estado.ultimo_rtc:
                # RTC fora de ordem / retransmissão da mesma passagem: ignorar
                # sem mexer na referência (senão nasce uma volta de milésimos
                # ou até negativa).
                valido = 0
                log.debug("passing fora de ordem ignorado: transponder %s "
                          "(rtc %s <= %s)", passing.transponder,
                          passing.rtc_time, estado.ultimo_rtc)
            else:
                tempo_us = passing.rtc_time - estado.ultimo_rtc
                # piso absoluto: mesmo sem tempo mínimo configurado, uma volta
                # jamais pode ter menos de 1 s (proteção contra duplicatas do
                # decoder na abertura).
                minimo = max(int(self.tempo_minimo_volta_us or 0),
                             TEMPO_MINIMO_ABSOLUTO_US)
                if tempo_us < minimo:
                    # GHOST LAP: descarta a volta, mas mantém o passing para
                    # auditoria. Não atualiza a referência: a próxima passagem
                    # real é medida desde a última volta válida.
                    valido = 0
                    self.rejeitados.append({"transponder": passing.transponder,
                                            "tempo_us": tempo_us,
                                            "passing_number": passing.passing_number})
                    if tempo_us >= TEMPO_RUIDO_US:
                        log.warning("ghost lap: transponder %s, delta %d us < mínimo "
                                    "%d us (passing #%s)",
                                    passing.transponder, tempo_us, minimo,
                                    passing.passing_number)
                        if self.on_rejeicao:
                            self.on_rejeicao(passing.transponder, tempo_us,
                                             passing.passing_number)
                    else:
                        log.debug("ruído de laço ignorado: transponder %s, "
                                  "delta %d us (passing #%s)",
                                  passing.transponder, tempo_us,
                                  passing.passing_number)
                else:
                    estado.ultimo_rtc = passing.rtc_time
                    numero = len(estado.voltas) + 1
                    melhor = estado.melhor_volta_us is None or tempo_us < estado.melhor_volta_us
                    volta = Volta(sessao_id=self.sessao_id, piloto_id=piloto_id,
                                  numero=numero, tempo_us=tempo_us, melhor=melhor)
                    if self.banco and not self.banco.registrar_volta(volta):
                        volta = None  # já existia (idempotente)
                    else:
                        estado.voltas.append(volta)
                        self._ultimo_passo_us[piloto_id] = self.agora_sessao_us()

        # persiste passing cru (auditoria; valido=0 quando rejeitado por ghost lap)
        if self.banco:
            self.banco.registrar_passing(self.sessao_id, passing.transponder,
                                         passing.rtc_time or 0, passing.passing_number,
                                         passing.strength, passing.hits, valido=valido)
        return volta

    # ----- classificação -----
    @staticmethod
    def melhor_media_consecutiva(tempos: List[int], n: int) -> Optional[Tuple[float, int]]:
        """Melhor média entre as janelas de N voltas consecutivas.

        Devolve (media_em_us, quantas_voltas_usou) ou None se não há voltas.
        Se o piloto tiver menos de N voltas, usa todas as que tem.
        """
        if not tempos or n <= 0:
            return None
        k = min(n, len(tempos))
        melhor: Optional[Tuple[float, int]] = None
        for i in range(0, len(tempos) - k + 1):
            media = sum(tempos[i:i + k]) / k
            if melhor is None or media < melhor[0]:
                melhor = (media, k)
        return melhor

    def classificacao(self, media_n: int = 0,
                      ordenar_por_media: bool = False) -> List[LinhaClassificação]:
        itens = list(self._pilotos.values())
        n = max(1, int(media_n or 0))
        # melhor média de N voltas consecutivas (para cada piloto)
        medias_n: Dict[int, Optional[Tuple[float, int]]] = {}
        for e in itens:
            medias_n[e.piloto_id] = self.melhor_media_consecutiva(
                [v.tempo_us for v in e.voltas], n)

        if ordenar_por_media:
            # ranking pela média de N voltas consecutivas: quem já tem a janela
            # completa vem primeiro (ordenado pela média); os demais, atrás.
            def _chave(e):
                janela = medias_n.get(e.piloto_id)
                completo = 1 if (janela and janela[1] >= n) else 0
                media = janela[0] if janela else float("inf")
                return (-completo, media, e.melhor_volta_us or 0)
        else:
            def _chave(e):
                return (-len(e.voltas), e.melhor_volta_us or 0, e.tempo_total_us)

        itens.sort(key=_chave)
        linhas: List[LinhaClassificação] = []
        lider = itens[0] if itens else None
        for pos, estado in enumerate(itens, start=1):
            gap = ""
            if lider is not None and estado is not lider:
                if len(estado.voltas) == len(lider.voltas):
                    diff = estado.tempo_total_us - lider.tempo_total_us
                    gap = f"+{formatar_tempo(diff)}"
                else:
                    gap = f"+{len(lider.voltas) - len(estado.voltas)} volta(s)"
            tempos = [v.tempo_us for v in estado.voltas]
            media = sum(tempos) / len(tempos) if tempos else None
            desvio = ((sum((t - media) ** 2 for t in tempos) / len(tempos)) ** 0.5
                      if tempos else None)
            consistencia = max(0.0, 100 * (1 - desvio / media)) if media else None
            janela = medias_n.get(estado.piloto_id)
            linhas.append(LinhaClassificação(
                posicao=pos, piloto_id=estado.piloto_id, nome=estado.nome,
                voltas=len(estado.voltas),
                tempo_total_us=estado.tempo_total_us,
                melhor_volta_us=estado.melhor_volta_us,
                ultima_volta_us=estado.voltas[-1].tempo_us if estado.voltas else None,
                gap=gap,
                abreviado=estado.nome[:3].upper(),
                media_us=media, desvio_us=desvio, consistencia_pct=consistencia,
                media_n_us=janela[0] if janela else None,
                media_n_voltas=janela[1] if janela else 0,
                transponder=estado.transponder,
                suspeita=len(estado.suspeitas) > 0))
        # intervalo: diferença de tempo para o piloto seguinte (mesma volta)
        for i in range(len(linhas) - 1):
            if len(itens[i].voltas) == len(itens[i + 1].voltas):
                linhas[i].intervalo_us = (itens[i].tempo_total_us
                                          - itens[i + 1].tempo_total_us)
        return linhas

    # ----- ações administrativas -----
    def marcar_suspeita(self, piloto_id: int,
                        numero_volta: Optional[int] = None) -> bool:
        """Marca volta como suspeita ('gato'). Sem nº = última volta."""
        estado = self._pilotos.get(piloto_id)
        if not estado or not estado.voltas:
            return False
        if numero_volta is None:
            numero_volta = len(estado.voltas)
        estado.suspeitas.add(numero_volta)
        log.info("volta %s de %s marcada como suspeita ('gato')",
                 numero_volta, estado.nome)
        return True

    def desmarcar_suspeita(self, piloto_id: int,
                           numero_volta: Optional[int] = None) -> bool:
        estado = self._pilotos.get(piloto_id)
        if not estado or not estado.suspeitas:
            return False
        if numero_volta is None:
            numero_volta = max(estado.suspeitas)
        estado.suspeitas.discard(numero_volta)
        return True

    def apagar_volta(self, piloto_id: int,
                     numero_volta: Optional[int] = None) -> bool:
        """Apaga volta (admin). Sem nº = última volta."""
        estado = self._pilotos.get(piloto_id)
        if not estado or not estado.voltas:
            return False
        if numero_volta is None:
            estado.voltas.pop()
            log.info("última volta de %s apagada", estado.nome)
            return True
        antes = len(estado.voltas)
        estado.voltas = [v for v in estado.voltas if v.numero != numero_volta]
        if len(estado.voltas) == antes:
            return False
        estado.suspeitas.discard(numero_volta)
        log.info("volta %s de %s apagada", numero_volta, estado.nome)
        return True

    def adicionar_volta(self, piloto_id: int, tempo_us: int,
                        numero_volta: Optional[int] = None) -> Optional[Volta]:
        """Insere uma volta manual (correção do gerente) para o piloto.

        A volta entra no fim (ou no número indicado) e é gravada no banco,
        para aparecer na classificação e nos gráficos. Devolve a volta
        criada (ou None em caso de falha) — o chamador usa o objeto para
        publicar eventos e disparar a locução/bipes como nas passagens
        reais do transponder.
        """
        estado = self._pilotos.get(piloto_id)
        if not estado or tempo_us <= 0:
            return None
        melhor = estado.melhor_volta_us is None or tempo_us < estado.melhor_volta_us
        numero = numero_volta or (len(estado.voltas) + 1)
        volta = Volta(sessao_id=self.sessao_id, piloto_id=piloto_id,
                      numero=numero, tempo_us=tempo_us, melhor=melhor)
        if self.banco and not self.banco.registrar_volta(volta):
            return None
        estado.voltas.append(volta)
        estado.voltas.sort(key=lambda v: v.numero)
        if melhor:
            for v in estado.voltas:
                v.melhor = (v is volta)
        log.info("volta manual #%s (%d us) adicionada para %s",
                 numero, tempo_us, estado.nome)
        return volta

    def adicionar_volta_por_tecla(self, piloto_id: int, agora_us: Optional[int] = None,
                                  base_us: Optional[int] = None) -> Optional[Volta]:
        """Atalho F1..F12: registra a volta do piloto usando o tempo desde a
        última volta dele (ou desde o início da sessão, se for a primeira).

        Devolve a volta criada, ou None se não der para registrar (piloto
        fora da sessão / tempo inválido).
        """
        estado = self._pilotos.get(piloto_id)
        if not estado:
            return None
        if agora_us is None:
            agora_us = self.agora_sessao_us()
        if base_us is None:
            base_us = 0
        referencia = self._ultimo_passo_us.get(piloto_id, base_us)
        tempo_us = int(agora_us - referencia)
        if tempo_us <= 0:
            return None
        volta = self.adicionar_volta(piloto_id, tempo_us)
        if not volta:
            return None
        self._ultimo_passo_us[piloto_id] = agora_us
        return volta
