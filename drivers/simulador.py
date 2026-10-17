"""KChrono — simulador de transponder alimentado pelo CTAD.

Baixa uma bateria (sessão) já enviada ao CTAD e reproduz as passagens
como se fosse o decodificador físico: mesmos tempos de volta, mesmos
transponders (vinculados aos pilotos locais), rtc_time em µs — o motor
de corrida, a classificação, a voz e o sync enxergam tudo exatamente
como em pista real.

Fluxo: Admin → Hardware → tipo "Simulador (CTAD)" → escolher sessão →
Conectar. As passagens começam sozinhas quando uma sessão é iniciada no
KChrono e param quando ela finaliza (ou ao reconectar).

Uso típico:
    driver = SimuladorCTAD(cliente=ctad_client, banco=banco, sessao_key="bat_...")
    await driver.connect()          # baixa a bateria do CTAD
    driver.armar_replay()           # chamado no "Iniciar sessão"
    await driver.read_loop(on_passing=...)
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Callable, List, Optional, Tuple

from .base import Callback, Decoder, Passing, Status

log = logging.getLogger("kchrono.driver.simulador")

#: faixa dos transponders simulados (nunca colide com códigos reais)
FAIXA_TRANSPONDER_SIM = 9_000_000

#: espaço entre um piloto e outro na largada virtual (s)
ATRASO_GRADE_S = 1.5

#: batimento cardíaco do "decoder" (status fake p/ o watchdog e a UI)
INTERVALO_STATUS_S = 8


class SimuladorCTAD(Decoder):
    """Reproduz uma sessão do CTAD no lugar do decoder físico."""

    def __init__(self, cliente=None, banco=None, sessao_key: str = "",
                 velocidade: float = 1.0,
                 ao_terminar: Optional[Callable[[], None]] = None,
                 resolver_cliente: Optional[Callable] = None):
        #: cliente CTAD já logado, ou callable que devolve um (login lazy)
        self._cliente = cliente
        self._resolver_cliente = resolver_cliente
        self._banco = banco
        self.sessao_key = sessao_key
        self.velocidade = max(0.1, float(velocidade or 1.0))
        self._ao_terminar = ao_terminar
        self._payload: Optional[dict] = None
        self._aberto = False
        self._iniciar = asyncio.Event()
        self._parar = asyncio.Event()
        #: (codigo, nome) de cada piloto da bateria
        self.transponders: List[Tuple[int, str]] = []

    # ------------------------------------------------------------------ Decoder
    async def connect(self) -> None:
        await asyncio.to_thread(self._baixar_sessao)
        self._aberto = True

    def _baixar_sessao(self) -> None:
        """Baixa a bateria do CTAD e vincula os pilotos locais."""
        if not self.sessao_key:
            raise ValueError("escolha uma sessão do CTAD para simular")
        try:
            cliente = self._cliente or (self._resolver_cliente()
                                        if self._resolver_cliente else None)
            if cliente is None:
                raise ValueError("simulador sem cliente CTAD")
            payload = cliente.rtdb_get(f"baterias/{self.sessao_key}")
        except ValueError:
            raise
        except Exception as e:      # ErroAuth / ErroBanco / rede
            raise ValueError(f"falha ao baixar '{self.sessao_key}' do CTAD: {e}") from e
        if not payload or not payload.get("dados"):
            raise ValueError(f"sessão '{self.sessao_key}' sem dados no CTAD")
        self._payload = payload
        self._vincular_pilotos(payload)
        log.info("simulador: '%s' carregada — %d piloto(s), x%.1f",
                 payload.get("sessao", self.sessao_key), len(self.transponders),
                 self.velocidade)

    def _vincular_pilotos(self, payload: dict) -> None:
        """Garante piloto local + transponder para cada nome da bateria.

        Piloto novo é criado; sem transponder vinculado recebe um código
        da faixa simulada (9.000.000+), sem tocar nos cadastros reais.
        """
        self.transponders = []
        for d in payload.get("dados") or []:
            nome = str(d.get("piloto") or "").strip()
            if not nome or not d.get("laps"):
                continue
            if self._banco is None:
                raise ValueError("simulador sem banco local")
            piloto_id = self._banco.garantir_piloto(nome)
            codigos = self._banco.transponders_do_piloto(piloto_id)
            if codigos:
                codigo = int(codigos[0])
            else:
                codigo = FAIXA_TRANSPONDER_SIM + int(piloto_id)
                self._banco.vincular_transponder(codigo, piloto_id)
            self.transponders.append((codigo, nome))

    async def read_loop(self, on_passing: Optional[Callback] = None,
                        on_status: Optional[Callback] = None,
                        on_desconhecido: Optional[Callback] = None) -> None:
        # status fake no boot: a UI mostra decoder ligado (tensão/temperatura)
        if on_status:
            on_status(Status(temperatura=31, tensao=Decimal("12.4"), ruido=4,
                             decoder_id=9000), None)
        coracao = asyncio.create_task(self._bater(on_status))
        try:
            while self._aberto:
                # espera a sessão abrir no KChrono (armar_replay)
                await self._iniciar.wait()
                self._iniciar.clear()
                if not self._aberto:
                    break
                await self._reproduzir(on_passing)
                self._parar.clear()
                if self._aberto and self._ao_terminar:
                    try:
                        self._ao_terminar()
                    except Exception:
                        log.exception("erro no fim do replay do simulador")
        finally:
            coracao.cancel()

    async def _bater(self, on_status: Optional[Callback]) -> None:
        """Status periódico — mesmo ritmo de um decoder real (evita watchdog)."""
        try:
            while self._aberto:
                await asyncio.sleep(INTERVALO_STATUS_S)
                if on_status:
                    on_status(Status(temperatura=31, tensao=Decimal("12.4"),
                                     ruido=4, decoder_id=9000), None)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------- armar/parar (sessão)
    def armar_replay(self) -> None:
        """Começa a emitir passagens (chamado no 'Iniciar sessão')."""
        self._parar.clear()
        self._iniciar.set()

    def parar_replay(self) -> None:
        """Corta a reprodução em andamento (sessão finalizada)."""
        self._parar.set()

    # ------------------------------------------------------------- reprodução
    def _linha_do_tempo(self) -> List[Tuple[float, int]]:
        """(tempo_s desde a largada virtual, transponder) em ordem cronológica."""
        eventos: List[Tuple[float, int]] = []
        por_nome = {nome: codigo for codigo, nome in self.transponders}
        for i, d in enumerate(self._payload.get("dados") or []):
            nome = str(d.get("piloto") or "").strip()
            codigo = por_nome.get(nome)
            if codigo is None:
                continue
            laps = [t for t in (d.get("laps") or [])
                    if isinstance(t, (int, float)) and t > 0]
            if not laps:
                continue
            t = i * ATRASO_GRADE_S          # cruzamento inicial (largada virtual)
            eventos.append((t, codigo))
            for segundos in laps:           # cada volta soma o tempo real do CTAD
                t += float(segundos)
                eventos.append((t, codigo))
        eventos.sort()
        return eventos

    async def _reproduzir(self, on_passing: Optional[Callback]) -> None:
        eventos = self._linha_do_tempo()
        if not eventos:
            return
        # rtc do "decoder": relógio real de partida; os deltas por transponder
        # são exatamente os tempos de volta da bateria do CTAD
        base_us = int(time.time() * 1_000_000)
        relogio = time.monotonic()
        numero = 0
        for t_s, codigo in eventos:
            if self._parar.is_set() or not self._aberto:
                log.info("simulador: reprodução interrompida em %d passagem(ens)",
                         numero)
                return
            alvo = relogio + t_s / self.velocidade
            espera = alvo - time.monotonic()
            if espera > 0:
                await asyncio.sleep(espera)
            numero += 1
            passing = Passing(transponder=codigo,
                              rtc_time=base_us + int(t_s * 1_000_000),
                              passing_number=numero, strength=8, hits=4)
            if on_passing:
                on_passing(passing, None)
        log.info("simulador: replay concluído (%d passagens)", numero)

    async def close(self) -> None:
        self._aberto = False
        self._parar.set()
        self._iniciar.set()
